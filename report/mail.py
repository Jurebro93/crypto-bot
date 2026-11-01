"""Send the HTML report: Resend (RESEND_API_KEY) or SMTP (SMTP_USER + SMTP_PASSWORD, default Gmail).

    REPORT_EMAIL_TO      recipients, comma separated (required)
    REPORT_EMAIL_FROM    sender; Resend default "Crypto bot <onboarding@resend.dev>" (only delivers to the Resend
                         account's own address until a domain is verified), SMTP default SMTP_USER
    SMTP_HOST / SMTP_PORT default smtp.gmail.com / 465 (SSL); 587 uses STARTTLS
"""
import json
import os
import re
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage


def recipients():
    """REPORT_EMAIL_TO plus players who ticked "šalji mi jutarnji izvještaj" in ⚙️ Postavke."""
    env = [x.strip() for x in (os.environ.get("REPORT_EMAIL_TO") or "").split(",") if x.strip()]
    return env + [e for e in player_emails() if e.lower() not in {x.lower() for x in env}]


def player_emails():
    """Read-only look at league.db (the dashboard is its only writer)."""
    import sqlite3
    try:
        from league import store
        con = sqlite3.connect(f"file:{store.DB}?mode=ro", uri=True, timeout=5)
        try:
            return [r[0] for r in con.execute(
                "SELECT email FROM profiles WHERE email_report=1 AND email IS NOT NULL AND email!=''")]
        finally:
            con.close()
    except Exception:
        return []


def method():
    if os.environ.get("RESEND_API_KEY"):
        return "resend"
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"):
        return "smtp"
    return None


def missing():
    """Env vars still needed before the report can be emailed (for the dashboard page and the log)."""
    out = []
    if not [x for x in (os.environ.get("REPORT_EMAIL_TO") or "").split(",") if x.strip()] and not recipients():
        out.append("REPORT_EMAIL_TO")
    if not method():
        out.append("SMTP_USER + SMTP_PASSWORD (ili RESEND_API_KEY)")
    return out


def plain(html):
    txt = re.sub(r"<(br|/tr|/div|/li|/p)[^>]*>", "\n", html)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n\n", txt).strip()


def send(subject, html, to=None):
    to = to or recipients()
    m = method()
    if not to or not m:
        raise RuntimeError("e-mail nije podešen: nedostaje " + ", ".join(missing()))
    if m == "resend":
        body = json.dumps({"from": os.environ.get("REPORT_EMAIL_FROM") or "Crypto bot <onboarding@resend.dev>",
                           "to": to, "subject": subject, "html": html, "text": plain(html)}).encode()
        req = urllib.request.Request("https://api.resend.com/emails", data=body, method="POST", headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return f"resend {json.loads(r.read() or b'{}').get('id', '')}"
    user = os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, ", ".join(to)
    msg["From"] = os.environ.get("REPORT_EMAIL_FROM") or f"Crypto bot <{user}>"
    msg.set_content(plain(html))
    msg.add_alternative(html, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, os.environ["SMTP_PASSWORD"].replace(" ", ""))
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(user, os.environ["SMTP_PASSWORD"].replace(" ", ""))
            s.send_message(msg)
    return f"smtp {host}"
