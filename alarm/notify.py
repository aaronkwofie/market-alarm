"""E-mail delivery over SMTP (Gmail app password by default).

Environment variables:
  SMTP_USER   sending address, e.g. yourbot@gmail.com
  SMTP_PASS   16-character Gmail app password (NOT the normal password)
  ALERT_TO    recipient(s), comma-separated
  SMTP_HOST   default smtp.gmail.com
  SMTP_PORT   default 465 (SSL)
  DRY_RUN=1   write e-mails to out/emails/ instead of sending
"""

import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path


def _plain(html):
    text = re.sub(r"<br\s*/?>|</p>|</tr>|</h3>|</div>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).replace("&amp;", "&").strip()


def send(subject, html, out_dir="out/emails"):
    """Returns True when the e-mail was delivered (or saved in dry-run mode)."""
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").replace(" ", "").strip()
    to = [a.strip() for a in os.environ.get("ALERT_TO", "").split(",") if a.strip()]

    if os.environ.get("DRY_RUN") == "1" or not (user and pw and to):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:50]
        path = Path(out_dir) / f"{stamp}-{slug}.html"
        path.write_text(html, encoding="utf-8")
        why = "DRY_RUN" if os.environ.get("DRY_RUN") == "1" else "SMTP settings missing"
        print(f"[email not sent: {why}] {subject} -> {path}")
        return os.environ.get("DRY_RUN") == "1"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Market Alarm", user))
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = make_msgid(domain="market-alarm.local")
    msg.set_content(_plain(html))
    msg.add_alternative(html, subtype="html")

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pw)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[email FAILED] {subject}: {type(exc).__name__}: {exc}")
        return False
    print(f"[email sent] {subject} -> {', '.join(to)}")
    return True
