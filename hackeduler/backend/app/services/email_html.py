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
from html.parser import HTMLParser
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
LAYOUTS = ("classic", "minimal", "banner")
DEFAULT_ACCENT = "#0f2744"
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

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


_RESPONSIVE_CSS = (
    "@media only screen and (max-width:480px){"
    ".bd{padding:16px!important}.hd{padding:12px 16px!important}.ft{padding:12px 16px 16px!important}"
    ".kv td{display:block!important;width:100%!important;box-sizing:border-box}"
    ".kv td.k{padding-bottom:0!important;border-bottom:0!important;font-size:12px!important}"
    "a.btn{display:block!important;text-align:center!important}}"
)


def wrap_layout(inner: str, subject: str, logo_src: str, layout: str = "classic", accent: str = DEFAULT_ACCENT) -> str:
    """The branded email: logo header, body, footer. ``layout`` is classic / minimal / banner; ``accent`` a #rrggbb colour."""
    if layout not in LAYOUTS:
        layout = "classic"
    if not ACCENT_RE.match(accent or ""):
        accent = DEFAULT_ACCENT
    footer = "".join(f'<div style="margin-bottom:4px;">{html.escape(x)}</div>' for x in FOOTER_LINES)
    contact = html.escape(FOOTER_CONTACT)
    size = 52 if layout == "banner" else 44
    tile = "" if layout == "minimal" else "background:#ffffff;padding:4px;"   # the logo is dark: give it a light tile on coloured headers
    logo = (f'<img src="{logo_src}" width="{size}" height="{size}" alt="" style="display:block;border:0;border-radius:8px;{tile}">' if logo_src else "")
    if layout == "minimal":
        head_style, name_color = f"background:#ffffff;padding:14px 22px;border-bottom:3px solid {accent};", "#0f172a"
    else:
        head_style, name_color = f"background:{accent};padding:{'22px' if layout == 'banner' else '14px 22px'};", "#ffffff"
    brand = (f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="padding-right:12px;">{logo}</td>'
             f'<td style="color:{name_color};font-size:20px;font-weight:600;letter-spacing:.2px;">Hackeduler</td></tr></table>')
    title = (f'<div style="color:#ffffff;font-size:15px;line-height:1.4;margin-top:14px;opacity:.92;">{html.escape(subject)}</div>' if layout == "banner" else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(subject)}</title>
<style>{_RESPONSIVE_CSS}</style></head>
<body style="margin:0;padding:0;background:#f1f5f9;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;font-family:Segoe UI,Arial,Helvetica,sans-serif;">
<tr><td class="hd" style="{head_style}">{brand}{title}</td></tr>
<tr><td class="bd" style="padding:24px 22px 8px;font-size:14px;line-height:1.55;color:#1e293b;">
{inner}
</td></tr>
<tr><td class="ft" style="padding:14px 22px 20px;border-top:1px solid #e2e8f0;background:#f8fafc;font-size:12px;line-height:1.5;color:#64748b;">
{footer}<div><a href="mailto:{contact}" style="color:#64748b;">{contact}</a></div>
</td></tr>
</table></td></tr></table>
</body></html>"""


def render_html(template: str, ctx: dict[str, Any], subject: str, *, logo_src: str = f"cid:{LOGO_CID}",
                layout: str = "classic", accent: str = DEFAULT_ACCENT) -> str:
    return wrap_layout(render_body_html(template, ctx), subject, logo_src, layout, accent)


# --------------------------------------------------------------- visual (HTML) templates
# The visual editor saves HTML. It is cleaned to a small allow-list (no scripts, styles, images, event handlers, or
# links other than http/https) and re-written with inline styles, so whatever is stored or pasted renders safely.
_SKIP = {"script", "style", "iframe", "object", "embed", "head", "title", "svg", "math", "noscript", "template"}
_ALIAS = {"b": "strong", "i": "em", "div": "p", "h1": "h2", "h4": "h3", "h5": "h3", "h6": "h3", "th": "td"}
_TAGS = {"p", "br", "h2", "h3", "strong", "em", "u", "ul", "ol", "li", "a", "table", "tbody", "tr", "td", "hr"}
_VOID = {"br", "hr"}
_LINK_OK = re.compile(r"^https?://[^\s\"'<>]+$", re.I)


def _style(tag: str, cls: str, accent: str, first_cell: bool) -> str:
    if tag == "p":
        return "margin:0 0 14px;"
    if tag == "h2":
        return "margin:0 0 10px;font-size:18px;line-height:1.3;color:#0f172a;"
    if tag == "h3":
        return "margin:0 0 10px;font-size:16px;line-height:1.3;color:#0f172a;"
    if tag in ("ul", "ol"):
        return "margin:0 0 14px;padding-left:22px;"
    if tag == "li":
        return "margin:2px 0;"
    if tag == "hr":
        return "border:0;border-top:1px solid #e2e8f0;margin:14px 0;"
    if tag == "table":
        return "width:100%;border-collapse:collapse;margin:0 0 14px;background:#f8fafc;"
    if tag == "td":
        base = "border-bottom:1px solid #e2e8f0;padding:8px 10px;vertical-align:top;"
        return base + ("color:#64748b;width:38%;" if first_cell else "")
    if tag == "a":
        if cls == "btn":
            return f"display:inline-block;background:{accent};color:#ffffff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600;"
        return "color:#1d4ed8;"
    return ""


class _Cleaner(HTMLParser):
    """Allow-list sanitiser. Output is HTML with inline styles; text keeps {{placeholders}} for later substitution."""

    def __init__(self, accent: str):
        super().__init__(convert_charrefs=True)
        self.accent, self.out, self.stack, self.skip = accent, [], [], 0
        self.cells: list[int] = []   # per open <tr>: how many cells so far

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        tag = _ALIAS.get(tag, tag)
        if self.skip or tag not in _TAGS:
            return
        at = dict(attrs)
        if tag in _VOID:
            self.out.append("<br>" if tag == "br" else f'<hr style="{_style("hr", "", self.accent, False)}">')
            return
        cls = ""
        extra = ""
        if tag == "a":
            href = (at.get("href") or "").strip()
            if not _LINK_OK.match(href):
                self.stack.append(None)     # not a safe link: keep the text only
                return
            cls = "btn" if "btn" in (at.get("class") or "").split() else ""
            extra = f' href="{html.escape(href, quote=True)}"' + (' class="btn"' if cls else "")
        elif tag == "table":
            extra = ' class="kv" role="presentation" cellpadding="0" cellspacing="0"'
        elif tag == "tr":
            self.cells.append(0)
        elif tag == "td":
            first = bool(self.cells) and self.cells[-1] == 0
            if self.cells:
                self.cells[-1] += 1
            extra = ' class="k"' if first else ""
            self.out.append(f'<td{extra} style="{_style("td", "", self.accent, first)}">')
            self.stack.append("td")
            return
        self.out.append(f'<{tag}{extra} style="{_style(tag, cls, self.accent, False)}">')
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        tag = _ALIAS.get(tag, tag)
        if self.skip or tag not in _TAGS or tag in _VOID:
            return
        if tag == "tr" and self.cells:
            self.cells.pop()
        # close down to the matching open tag (tolerates the sloppy HTML browsers produce)
        if tag in self.stack or (tag == "a" and None in self.stack):
            while self.stack:
                t = self.stack.pop()
                if t is not None:
                    self.out.append(f"</{t}>")
                if t == tag or (tag == "a" and t is None):
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            t = self.stack.pop()
            if t is not None:
                self.out.append(f"</{t}>")
        return "".join(self.out)


def clean_html(src: str, accent: str = DEFAULT_ACCENT) -> str:
    c = _Cleaner(accent if ACCENT_RE.match(accent or "") else DEFAULT_ACCENT)
    c.feed(src or "")
    c.close()
    return c.result()


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.href: str | None = None
        self.link_text: list[str] = []
        self.skip = 0

    def _w(self, t: str) -> None:
        (self.cell if self.cell is not None else self.parts).append(t)

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag == "br":
            self._w("\n")
        elif tag == "li":
            self._w("\n- ")
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "ul", "ol", "table", "hr"):
            self._w("\n\n")
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "a":
            h = (dict(attrs).get("href") or "").strip()
            self.href, self.link_text = (h if _LINK_OK.match(h) else None), []

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            cells = [c for c in self.row if c]
            self.parts.append("\n" + (f"{cells[0]}: {' '.join(cells[1:])}" if len(cells) > 1 else " ".join(cells)))
            self.row = None
        elif tag == "a" and self.href:
            text = "".join(self.link_text).strip()
            if self.href not in text:
                self._w(f" ({self.href})")
            self.href = None
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "ul", "ol", "table"):
            self._w("\n\n")

    def handle_data(self, data):
        if self.skip:
            return
        data = re.sub(r"\s+", " ", data)
        if self.href is not None:
            self.link_text.append(data)
        self._w(data)


def html_to_plain(src: str) -> str:
    p = _Plain()
    p.feed(src or "")
    p.close()
    t = "".join(p.parts).replace("\xa0", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def render_rich(template: str, ctx: dict[str, Any], accent: str = DEFAULT_ACCENT) -> tuple[str, str]:
    """(plain text, HTML fragment) for a visual-editor template. Values are escaped; they can never add markup."""
    safe = clean_html(template, accent)
    inner = PLACEHOLDER_RE.sub(lambda m: html.escape(str(ctx.get(m.group(1), "")), quote=True), safe)
    plain = PLACEHOLDER_RE.sub(lambda m: str(ctx.get(m.group(1), "")), html_to_plain(safe))
    return plain, inner


def build(template: str, fmt: str, ctx: dict[str, Any], subject: str, *, layout: str = "classic",
          accent: str = DEFAULT_ACCENT, logo_src: str = f"cid:{LOGO_CID}") -> tuple[str, str]:
    """(plain text, complete HTML document) for one email. ``fmt`` is 'html' (visual editor) or 'text' (older syntax)."""
    if fmt == "html":
        plain, inner = render_rich(template, ctx, accent)
    else:
        plain, inner = render_plain(template, ctx), render_body_html(template, ctx)
    return plain, wrap_layout(inner, subject, logo_src, layout, accent)
