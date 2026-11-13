"""Outbox delivery: sends queued rows from ``email_notification_logs``.

Each row is claimed with ``FOR UPDATE SKIP LOCKED`` so multiple workers can run
safely. Failures are recorded (attempts, last_error) and retried with
exponential backoff until ``max_attempts``; afterwards status becomes 'failed'.
Delivery never touches booking rows, so it cannot corrupt booking data.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, make_msgid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import EmailNotificationLog
from . import settings_service
from .availability import now_utc

log = logging.getLogger(__name__)

# In-memory sink used by the 'memory' backend (tests / local demos)
SENT_MESSAGES: list[EmailMessage] = []


class EmailBackendError(Exception):
    pass


def smtp_config(db: Session) -> dict:
    env = get_settings()

    def pick(key, default):
        v = settings_service.get_setting(db, key)
        return default if v is None else v

    return {
        "host": pick("smtp_host", env.smtp_host),
        "port": pick("smtp_port", env.smtp_port),
        "username": pick("smtp_username", env.smtp_username),
        "starttls": pick("smtp_starttls", env.smtp_starttls),
        "ssl": env.smtp_ssl,
        "timeout": env.smtp_timeout,
    }


def build_message(db: Session, row: EmailNotificationLog) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = row.subject
    msg["From"] = formataddr((settings_service.get_setting(db, "email_sender_name"),
                              settings_service.get_setting(db, "email_sender_address")))
    msg["To"] = row.recipient
    msg["Message-ID"] = make_msgid(domain="hackeduler")
    msg.set_content(row.body)  # text/plain only
    return msg


PROVIDERS = ("smtp", "ses")


def provider_chain(db: Session) -> list[str]:
    """Mail services to try, in order: the primary, then the fallback if one is configured.
    Admin Settings override the HACKEDULER_EMAIL_PRIMARY / HACKEDULER_EMAIL_FALLBACK environment defaults."""
    env = get_settings()
    primary = settings_service.get_setting(db, "email_primary") or env.email_primary or "smtp"
    fallback = settings_service.get_setting(db, "email_fallback") or env.email_fallback or "none"
    chain = [primary if primary in PROVIDERS else "smtp"]
    if fallback in PROVIDERS and fallback != chain[0]:
        chain.append(fallback)
    return chain


def ses_config(db: Session) -> dict:
    env = get_settings()
    return {
        "region": settings_service.get_setting(db, "ses_region") or env.aws_region or None,
        "configuration_set": settings_service.get_setting(db, "ses_configuration_set") or env.ses_configuration_set or None,
        "timeout": env.smtp_timeout,
    }


_SES_CLIENTS: dict[tuple, object] = {}


def _ses_client(region: str | None, timeout: int):
    """One cached SES v2 client per region. Credentials come from the standard AWS chain (EC2 instance role)."""
    key = (region, timeout)
    if key not in _SES_CLIENTS:
        import boto3
        from botocore.config import Config

        _SES_CLIENTS[key] = boto3.client("sesv2", region_name=region,
                                         config=Config(connect_timeout=timeout, read_timeout=timeout, retries={"max_attempts": 1}))
    return _SES_CLIENTS[key]


def _send_smtp(db: Session, msg: EmailMessage) -> None:
    cfg = smtp_config(db)
    password = get_settings().smtp_password
    try:
        if cfg["ssl"]:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=cfg["timeout"], context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=cfg["timeout"])
        with server:
            if cfg["starttls"] and not cfg["ssl"]:
                server.starttls(context=ssl.create_default_context())
            if cfg["username"]:
                server.login(cfg["username"], password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailBackendError(f"SMTP {type(e).__name__}: {e}") from e


def _send_ses(db: Session, msg: EmailMessage) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    cfg = ses_config(db)
    recipients = [a for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []) + msg.get_all("Bcc", []))]
    if not recipients:
        raise EmailBackendError("SES: the message has no recipients")
    kwargs = {"Destination": {"ToAddresses": recipients}, "Content": {"Raw": {"Data": msg.as_bytes()}}}
    if cfg["configuration_set"]:
        kwargs["ConfigurationSetName"] = cfg["configuration_set"]
    try:
        _ses_client(cfg["region"], cfg["timeout"]).send_email(**kwargs)
    except ClientError as e:
        err = e.response.get("Error", {})
        raise EmailBackendError(f"SES {err.get('Code', 'Error')}: {err.get('Message', e)}") from e
    except (BotoCoreError, OSError) as e:
        raise EmailBackendError(f"SES {type(e).__name__}: {e}") from e


_SENDERS = {"smtp": _send_smtp, "ses": _send_ses}


def send_via(db: Session, provider: str, msg: EmailMessage) -> None:
    """Send through exactly one service (used by the admin 'send test email' button)."""
    _SENDERS[provider](db, msg)


def deliver(db: Session, msg: EmailMessage) -> str:
    """Send ``msg`` and return the service that delivered it. The primary is tried first; if it fails and a fallback
    is configured the fallback is tried before the failure counts as an attempt."""
    backend = get_settings().email_backend
    if backend == "memory":
        SENT_MESSAGES.append(msg)
        return "memory"
    if backend == "console":
        log.info("EMAIL (console backend)\n%s", msg.as_string())
        return "console"
    errors: list[str] = []
    for provider in provider_chain(db):
        try:
            send_via(db, provider, msg)
            if errors:
                log.warning("email delivered by fallback %s after: %s", provider, "; ".join(errors))
            return provider
        except EmailBackendError as e:
            errors.append(str(e))
    raise EmailBackendError(" | ".join(errors))


def process_outbox(db: Session, batch: int = 25) -> dict[str, int]:
    rows = db.scalars(
        select(EmailNotificationLog)
        .where(EmailNotificationLog.status == "queued", EmailNotificationLog.next_attempt_at <= now_utc())
        .order_by(EmailNotificationLog.created_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    stats = {"sent": 0, "retry": 0, "failed": 0}
    for row in rows:
        row.attempts += 1
        try:
            row.provider = deliver(db, build_message(db, row))
            row.status, row.sent_at, row.last_error = "sent", now_utc(), None
            stats["sent"] += 1
        except Exception as e:  # noqa: BLE001 - every failure must be logged, never raised
            row.last_error = str(e)[:2000]
            if row.attempts >= row.max_attempts:
                row.status = "failed"
                stats["failed"] += 1
                log.error("email %s to %s permanently failed: %s", row.id, row.recipient, e)
            else:
                row.next_attempt_at = now_utc() + timedelta(seconds=60 * (2 ** (row.attempts - 1)))
                stats["retry"] += 1
                log.warning("email %s to %s failed (attempt %s): %s", row.id, row.recipient, row.attempts, e)
        row.updated_at = now_utc()
    db.commit()
    return stats
