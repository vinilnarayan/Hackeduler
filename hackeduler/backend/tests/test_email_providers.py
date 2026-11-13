"""Mail delivery through SMTP and Amazon SES, with optional fallback, and the admin settings that control it."""
import smtplib
from unittest import mock

import pytest
from botocore.exceptions import ClientError

from app.config import get_settings
from app.db import SessionLocal
from app.models import EmailNotificationLog
from app.services import email_sender, settings_service


@pytest.fixture
def real_delivery(monkeypatch):
    """Switch from the in-memory test backend to real delivery, with every network call replaced."""
    monkeypatch.setattr(get_settings(), "email_backend", "smtp")
    email_sender._SES_CLIENTS.clear()
    yield


def _queue(db, to="poc@example.com"):
    from app.services.availability import now_utc
    import uuid
    row = EmailNotificationLog(id=uuid.uuid4(), template_key="t", recipient=to, subject="s", body="b",
                               status="queued", attempts=0, max_attempts=3, next_attempt_at=now_utc())
    db.add(row)
    db.commit()
    return row.id


def _ses_ok():
    c = mock.MagicMock()
    c.send_email.return_value = {"MessageId": "x"}
    return c


def _ses_fail(code="MessageRejected", msg="Email address is not verified."):
    c = mock.MagicMock()
    c.send_email.side_effect = ClientError({"Error": {"Code": code, "Message": msg}}, "SendEmailV2")
    return c


def _smtp(ok=True):
    s = mock.MagicMock()
    if not ok:
        s.side_effect = smtplib.SMTPConnectError(421, "no route")
    return s


def test_default_chain_is_smtp_only(data, real_delivery):
    with SessionLocal() as db:
        assert email_sender.provider_chain(db) == ["smtp"]


def test_chain_from_admin_settings_and_environment(data, real_delivery, monkeypatch):
    def put(db, k, v):
        settings_service.set_setting(db, k, v)
        db.flush()

    with SessionLocal() as db:
        put(db, "email_primary", "ses")
        put(db, "email_fallback", "smtp")
        assert email_sender.provider_chain(db) == ["ses", "smtp"]
        put(db, "email_fallback", "none")
        assert email_sender.provider_chain(db) == ["ses"]
        put(db, "email_fallback", "ses")      # same as primary: no duplicate
        assert email_sender.provider_chain(db) == ["ses"]
        # environment defaults apply when the admin setting is unset
        put(db, "email_primary", None)
        put(db, "email_fallback", None)
        monkeypatch.setattr(get_settings(), "email_primary", "ses")
        monkeypatch.setattr(get_settings(), "email_fallback", "smtp")
        assert email_sender.provider_chain(db) == ["ses", "smtp"]


def test_ses_delivery_uses_raw_message_region_and_configuration_set(data, real_delivery):
    client = _ses_ok()
    with SessionLocal() as db, mock.patch.object(email_sender, "_ses_client", return_value=client) as get_client:
        settings_service.set_setting(db, "email_primary", "ses")
        settings_service.set_setting(db, "ses_region", "ap-south-1")
        settings_service.set_setting(db, "ses_configuration_set", "hackeduler-cs")
        db.commit()
        rid = _queue(db)
        assert email_sender.process_outbox(db)["sent"] == 1
        row = db.get(EmailNotificationLog, rid)
        assert row.status == "sent" and row.provider == "ses"
    assert get_client.call_args.args[0] == "ap-south-1"
    kw = client.send_email.call_args.kwargs
    assert kw["Destination"]["ToAddresses"] == ["poc@example.com"] and kw["ConfigurationSetName"] == "hackeduler-cs"
    assert b"Subject: s" in kw["Content"]["Raw"]["Data"]


def test_fallback_used_when_primary_fails_and_is_recorded(data, real_delivery):
    smtp = _smtp()
    with SessionLocal() as db, mock.patch.object(email_sender, "_ses_client", return_value=_ses_fail()), \
            mock.patch("smtplib.SMTP", smtp):
        settings_service.set_setting(db, "email_primary", "ses")
        settings_service.set_setting(db, "email_fallback", "smtp")
        db.commit()
        rid = _queue(db)
        assert email_sender.process_outbox(db)["sent"] == 1
        row = db.get(EmailNotificationLog, rid)
        assert row.status == "sent" and row.provider == "smtp" and row.attempts == 1


def test_both_fail_keeps_both_errors_and_retries(data, real_delivery):
    with SessionLocal() as db, mock.patch.object(email_sender, "_ses_client", return_value=_ses_fail()), \
            mock.patch("smtplib.SMTP", _smtp(ok=False)):
        settings_service.set_setting(db, "email_primary", "ses")
        settings_service.set_setting(db, "email_fallback", "smtp")
        db.commit()
        rid = _queue(db)
        assert email_sender.process_outbox(db)["retry"] == 1
        row = db.get(EmailNotificationLog, rid)
        assert row.status == "queued" and row.provider is None
        assert "SES MessageRejected" in row.last_error and "SMTP SMTPConnectError" in row.last_error


def test_no_fallback_means_failure_is_not_masked(data, real_delivery):
    with SessionLocal() as db, mock.patch.object(email_sender, "_ses_client", return_value=_ses_fail()), \
            mock.patch("smtplib.SMTP") as smtp:
        settings_service.set_setting(db, "email_primary", "ses")
        db.commit()
        rid = _queue(db)
        assert email_sender.process_outbox(db)["retry"] == 1
        smtp.assert_not_called()


def test_missing_region_is_a_clear_error_not_a_crash(data, real_delivery, monkeypatch):
    for k in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_CONFIG_FILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    email_sender._SES_CLIENTS.clear()
    with SessionLocal() as db:
        settings_service.set_setting(db, "email_primary", "ses")
        db.commit()
        rid = _queue(db)
        assert email_sender.process_outbox(db)["retry"] == 1
        assert "SES" in db.get(EmailNotificationLog, rid).last_error


def test_admin_test_email_button_each_service(admin, data, real_delivery):
    with mock.patch.object(email_sender, "_ses_client", return_value=_ses_ok()), mock.patch("smtplib.SMTP", _smtp()):
        r = admin.post("/api/admin/settings/test-email", json={"to": "me@example.com", "provider": "ses"})
        assert r.status_code == 200 and r.json() == {"ok": True, "provider": "ses", "error": None}
        r = admin.post("/api/admin/settings/test-email", json={"to": "me@example.com", "provider": "smtp"})
        assert r.json()["ok"] is True and r.json()["provider"] == "smtp"
    with mock.patch.object(email_sender, "_ses_client", return_value=_ses_fail()):
        r = admin.post("/api/admin/settings/test-email", json={"to": "me@example.com", "provider": "ses"})
        assert r.status_code == 200 and r.json()["ok"] is False and "MessageRejected" in r.json()["error"]


def test_admin_settings_validation_and_secrets_never_exposed(admin, data):
    ok = admin.put("/api/admin/settings", json={"values": {"email_primary": "ses", "email_fallback": "smtp",
                                                          "ses_region": "ap-south-1", "ses_configuration_set": "cs-1"}})
    assert ok.status_code == 200 and ok.json()["values"]["email_primary"] == "ses"
    for bad in ({"email_primary": "pigeon"}, {"email_fallback": "x"}, {"ses_region": "India"}, {"ses_configuration_set": "a b"}):
        assert admin.put("/api/admin/settings", json={"values": bad}).status_code == 422, bad
    s = admin.get("/api/admin/settings").json()
    assert s["email_chain"] == ["ses", "smtp"]
    assert "password" not in str(s["environment"]).lower().replace("smtp_password_configured", "")


def test_requester_cannot_send_test_email(req1, data):
    assert req1.post("/api/admin/settings/test-email", json={"to": "x@example.com"}).status_code == 403
