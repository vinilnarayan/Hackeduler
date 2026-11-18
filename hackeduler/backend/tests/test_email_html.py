"""HTML emails: formatting syntax, escaping, branded layout, multipart message, template preview."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import EmailNotificationLog
from app.services import email_html as eh, email_sender

from .conftest import booking_payload


def test_formatting_syntax():
    h = eh.render_body_html("# Title\n\nHello **{{Name}}**,\nsecond line\n\n- one\n- two\n\nSee [the docs](https://example.com/a?b=1&c=2).", {"Name": "Jane"})
    assert "<h3" in h and "Title" in h
    assert "<strong>Jane</strong>" in h and "second line" in h and "<br>" in h
    assert h.count("<li") == 2 and "<ul" in h
    assert 'href="https://example.com/a?b=1&amp;c=2"' in h


def test_values_cannot_inject_markup_or_formatting():
    ctx = {"Comment": '<script>alert(1)</script> **bold** [x](https://evil.example) # not a heading'}
    h = eh.render_body_html("Note: {{Comment}}", ctx)
    assert "<script" not in h and "&lt;script&gt;" in h
    assert "<strong>" not in h and "<a " not in h and "evil.example" in h        # shown as text only
    assert "<h3" not in h


def test_template_author_html_and_unsafe_links_are_text():
    h = eh.render_body_html("<img src=x onerror=alert(1)> [bad](javascript:alert(1)) [ok](http://a.example)", {})
    assert "<img" not in h and "&lt;img" in h
    assert 'href="javascript' not in h and 'href="http://a.example"' in h


def test_multiline_value_becomes_a_list():
    h = eh.render_body_html("Please send:\n{{Required Details}}\n\nThanks", {"Required Details": "- Test URL\n- Credentials\n- Scope"})
    assert h.count("<li") == 3 and "Thanks" in h


def test_plain_text_version_has_no_marks():
    t = eh.render_plain("# Hi **{{Name}}**\nSee [docs](https://x.example)", {"Name": "Jane"})
    assert t == "Hi Jane\nSee docs (https://x.example)"


def test_layout_has_logo_header_and_footer():
    full = eh.render_html("Hello", {}, "A subject")
    assert "Hackeduler" in full and "cid:hackeduler-logo" in full
    assert "Designed and developed by OffSec Team, InfoSec, IBS Group" in full and "OffSec_Team@ibsplc.com" in full
    assert eh.logo_bytes()[:4] == b"\x89PNG"


def _row(**kw):
    base = dict(template_key="t", recipient="a@x.com", subject="Subj", body="plain body")
    base.update(kw)
    return EmailNotificationLog(**base)


def test_message_is_multipart_with_inline_logo(admin):
    db = SessionLocal()
    try:
        msg = email_sender.build_message(db, _row(body_html="<p>hi <strong>there</strong></p>"))
    finally:
        db.close()
    assert msg.get_content_type() == "multipart/alternative"
    assert msg.get_body(("plain",)).get_content().strip() == "plain body"
    html_part = msg.get_body(("html",))
    assert "<strong>there</strong>" in html_part.get_content() and "Designed and developed by" in html_part.get_content()
    related = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(related) == 1 and related[0]["Content-ID"] == "<hackeduler-logo>"


def test_row_without_html_stays_plain_text(admin):
    db = SessionLocal()
    try:
        msg = email_sender.build_message(db, _row())
    finally:
        db.close()
    assert msg.get_content_type() == "text/plain" and msg.get_content().strip() == "plain body"


def test_queued_emails_carry_both_versions(req1, admin, data):
    r = req1.post("/api/bookings", json=booking_payload(data))
    admin.post(f"/api/admin/bookings/{r.json()['id']}/approve")
    db = SessionLocal()
    try:
        row = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == "booking_approved_poc")).first()
        assert row.body_html and "<p" in row.body_html and "**" not in row.body
        msg = email_sender.build_message(db, row)
        assert msg.get_body(("html",)) is not None and msg.get_body(("plain",)) is not None
    finally:
        db.close()


def test_preview_returns_html_with_logo(admin):
    key = admin.get("/api/admin/email-templates").json()[0]["key"]
    r = admin.post(f"/api/admin/email-templates/{key}/preview", json={"body_template": "# Hello **{{Application Name}}**\n- a\n- b"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "<strong>" in j["html"] and "data:image/png;base64," in j["html"] and "OffSec_Team@ibsplc.com" in j["html"]
    assert "**" not in j["body"] and "<Application Name>" in j["body"]
    assert "&lt;Application Name&gt;" in j["html"]


def test_preview_requires_admin(req1):
    assert req1.post("/api/admin/email-templates/x/preview", json={}).status_code == 403


# ----------------------------------------------------------------------------- visual editor (HTML templates)
RICH = ('<h2>Approved</h2><p>Hi <b>{{Name}}</b>,</p><ul><li>one</li><li>two</li></ul>'
        '<table class="kv"><tr><td>Dates</td><td>{{Start}} to {{End}}</td></tr></table>'
        '<p><a class="btn" href="https://app.example/b/1">View booking</a></p>')


def test_rich_template_is_rewritten_with_inline_styles():
    plain, inner = eh.render_rich(RICH, {"Name": "Jane", "Start": "1 Dec", "End": "5 Dec"}, "#0f766e")
    assert "<strong" in inner and "Jane" in inner and inner.count("<li") == 2
    assert "background:#0f766e" in inner and 'href="https://app.example/b/1"' in inner     # accent drives the button
    assert 'class="k"' in inner                                                          # label cell (for the phone layout)
    assert plain.startswith("Approved") and "- one" in plain and "Dates: 1 Dec to 5 Dec" in plain
    assert "View booking (https://app.example/b/1)" in plain and "<" not in plain


def test_rich_template_drops_scripts_handlers_images_and_unsafe_links():
    evil = ('<p onclick="x()" style="position:fixed">hi</p><script>alert(1)</script><style>p{}</style>'
            '<img src=x onerror=alert(1)><iframe src="https://e.example"></iframe>'
            '<a href="javascript:alert(1)">bad</a> <a href="https://ok.example" onmouseover="y()">ok</a>')
    _, inner = eh.render_rich(evil, {})
    low = inner.lower()
    for bad in ("<script", "alert(1)", "onclick", "onerror", "onmouseover", "<img", "<iframe", "javascript:", "position:fixed", "<style"):
        assert bad not in low
    assert 'href="https://ok.example"' in inner and "bad" in inner and "hi" in inner


def test_rich_values_are_escaped():
    _, inner = eh.render_rich("<p>{{Comment}}</p>", {"Comment": '<img src=x onerror=1> <b>x</b>'})
    assert "<img" not in inner and "&lt;img" in inner and "<b>" not in inner


def test_rich_handles_browser_markup():
    _, inner = eh.render_rich("<div>one<br>two</div><div><b>bold <i>both</i></b></div><p>unclosed", {})
    assert inner.count("<p") == 3 and "<br>" in inner and inner.count("<p") == inner.count("</p>")


def test_layouts_and_accent():
    for layout in eh.LAYOUTS:
        full = eh.wrap_layout("<p>x</p>", "Subj", "cid:l", layout, "#9a3412")
        assert "#9a3412" in full and "@media" in full and "Designed and developed by OffSec Team" in full
    assert "Subj</div>" in eh.wrap_layout("x", "Subj", "cid:l", "banner")                    # banner shows the subject
    assert "#0f2744" in eh.wrap_layout("x", "S", "", "nonsense", "red")                     # bad input falls back


def test_template_design_saved_previewed_and_sent(req1, admin, data):
    key = "booking_approved_poc"
    design = {"body_template": "<p>Hello <b>{{Application Name}}</b></p><p><a class=\"btn\" href=\"https://app.example/x\">Open</a></p>",
              "body_format": "html", "layout": "banner", "accent": "#1f5fd1"}
    r = admin.put(f"/api/admin/email-templates/{key}", json=design)
    assert r.status_code == 200, r.text
    assert (r.json()["body_format"], r.json()["layout"], r.json()["accent"]) == ("html", "banner", "#1f5fd1")

    pv = admin.post(f"/api/admin/email-templates/{key}/preview", json={"layout": "minimal", "accent": "#9a3412"}).json()   # unsaved change
    assert "border-bottom:3px solid #9a3412" in pv["html"] and "Open (https://app.example/x)" in pv["body"]

    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    db = SessionLocal()
    try:
        row = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == key)).first()
        assert row.body_html.startswith("<!doctype") and "background:#1f5fd1" in row.body_html and "<b>" not in row.body_html
        assert "Hello " in row.body and "<" not in row.body
        msg = email_sender.build_message(db, row)
        assert "background:#1f5fd1" in msg.get_body(("html",)).get_content()
    finally:
        db.close()


def test_template_design_is_validated(admin):
    key = "booking_approved_poc"
    for bad in ({"accent": "red"}, {"accent": "#12345"}, {"accent": "#1f5fd1;background:url(x)"}, {"layout": "weird"}, {"body_format": "markdown"}):
        assert admin.put(f"/api/admin/email-templates/{key}", json=bad).status_code == 422
    assert admin.put(f"/api/admin/email-templates/{key}", json={"body_template": "<p>{{Not A Variable}}</p>", "body_format": "html"}).status_code == 422


def test_existing_text_templates_still_render_unchanged(admin):
    t = next(x for x in admin.get("/api/admin/email-templates").json() if x["key"] == "booking_approved_poc")
    assert (t["body_format"], t["layout"], t["accent"]) == ("text", "classic", "#0f2744")
