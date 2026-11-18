"""HTML version of the notification emails.

Templates stay plain text with a tiny formatting syntax; every email is sent as text/plain + text/html:

    **bold**            bold text
    [text](https://x)   a link (http / https only)
    - item              a bullet list (consecutive lines)
    # Heading           a heading line
    blank line          new paragraph (a single line break stays a line break)

Placeholder values are HTML-escaped and cannot add formatting or links of their own, so a name or a comment can
never inject markup. The HTML is wrapped in a simple branded layout (logo header and footer); the logo is embedded
in the message so it also shows when the recipient's client blocks remote images.
"""
from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .notifications import PLACEHOLDER_RE

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "email_logo.png"
LOGO_CID = "hackeduler-logo"
FOOTER_LINES = (
    "This is an automated message from Hackeduler - please do not reply to it.",
    "Designed and developed by OffSec Team, InfoSec, IBS Group",
)
FOOTER_CONTACT = "OffSec_Team@ibsplc.com"

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_HEADING = re.compile(r"^#{1,3}\s+")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")


@lru_cache(maxsize=1)
def logo_bytes() -> bytes:
    try:
        return LOGO_PATH.read_bytes()
    except OSError:
        return b""


# ------------------------------------------------------------------ plain text
def to_plain(template: str) -> str:
    """The template without the formatting marks, for the text/plain part."""
    t = _BOLD.sub(r"\1", template)
    t = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", t)
    return "\n".join(_HEADING.sub("", ln) for ln in t.split("\n"))


def render_plain(template: str, ctx: dict[str, Any]) -> str:
    return PLACEHOLDER_RE.sub(lambda m: str(ctx.get(m.group(1), "")), to_plain(template))


# ------------------------------------------------------------------------ html
def _neutral(value: str) -> str:
    """Escape a placeholder value so it can neither be markup nor formatting syntax."""
    v = html.escape(value, quote=True)
    return v.replace("*", "&#42;").replace("[", "&#91;").replace("]", "&#93;").replace("#", "&#35;")


def _inline(text: str) -> str:
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return _LINK.sub(lambda m: f'<a href="{m.group(2)}" style="color:#1d4ed8;">{m.group(1)}</a>', text)


def render_body_html(template: str, ctx: dict[str, Any]) -> str:
    """Template -> HTML fragment. Template text and values are escaped first; structure is built afterwards."""
    esc = html.escape(template, quote=True)                       # the author's text is text, never markup
    esc = PLACEHOLDER_RE.sub(lambda m: _neutral(str(ctx.get(m.group(1), ""))), esc)
    blocks: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        nonlocal para, items
        if para:
            blocks.append('<p style="margin:0 0 14px;">' + "<br>".join(_inline(x) for x in para) + "</p>")
        if items:
            blocks.append('<ul style="margin:0 0 14px;padding-left:22px;">' + "".join(f'<li style="margin:2px 0;">{_inline(x)}</li>' for x in items) + "</ul>")
        para, items = [], []

    for line in esc.split("\n"):
        line = line.rstrip()
        b = _BULLET.match(line)
        if not line.strip():
            flush()
        elif b:
            if para:
                flush()
            items.append(b.group(1))
        elif _HEADING.match(line):
            flush()
            blocks.append('<h3 style="margin:0 0 10px;font-size:16px;color:#0f172a;">' + _inline(_HEADING.sub("", line)) + "</h3>")
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return "\n".join(blocks)


def wrap_layout(inner: str, subject: str, logo_src: str) -> str:
    footer = "".join(f'<div style="margin-bottom:4px;">{html.escape(x)}</div>' for x in FOOTER_LINES)
    contact = html.escape(FOOTER_CONTACT)
    logo = (f'<img src="{logo_src}" width="44" height="44" alt="" style="display:block;border:0;border-radius:8px;">' if logo_src else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;font-family:Segoe UI,Arial,Helvetica,sans-serif;">
<tr><td style="background:#0f2744;padding:14px 22px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:12px;">{logo}</td>
<td style="color:#ffffff;font-size:20px;font-weight:600;letter-spacing:.2px;">Hackeduler</td>
</tr></table></td></tr>
<tr><td style="padding:24px 22px 8px;font-size:14px;line-height:1.55;color:#1e293b;">
{inner}
</td></tr>
<tr><td style="padding:14px 22px 20px;border-top:1px solid #e2e8f0;background:#f8fafc;font-size:12px;line-height:1.5;color:#64748b;">
{footer}<div><a href="mailto:{contact}" style="color:#64748b;">{contact}</a></div>
</td></tr>
</table></td></tr></table>
</body></html>"""


def render_html(template: str, ctx: dict[str, Any], subject: str, *, logo_src: str = f"cid:{LOGO_CID}") -> str:
    return wrap_layout(render_body_html(template, ctx), subject, logo_src)
