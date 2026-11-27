"""Sends the outreach emails you approved, from your own Gmail.

Nothing goes out unless you approved its batch on the Outreach page; each approved email waits until its send time
(9:00 AM on the next weekday by default), so you can still edit or cancel it. Gmail is reached with an app password
you entered in Settings (never your real password). Sent mail lands in your Gmail Sent folder as usual, and if the
same email was also waiting as a Gmail draft, that draft is removed so it can't go out twice.
"""
from __future__ import annotations

import imaplib
import logging
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Prospect
from ..util import now

log = logging.getLogger(__name__)
SENDER_NAME = "Jalen Artiles"
PER_RUN = 3  # at most this many a minute, so a batch trickles out like a person sending it


def configured() -> bool:
    return bool(settings.gmail_address and settings.gmail_app_password)


def resume_file():
    """Where the resume attached to outreach emails lives (a PDF dropped in data/resume-imports/ replaces it)."""
    return settings.data_dir / "outreach-imports" / "resume" / "Jalen_Artiles_Resume.pdf"


def resume_path():
    p = resume_file()
    return p if p.exists() else None


def next_send_time(after: datetime | None = None) -> datetime:
    """The next weekday at the send hour, in your time zone, at least 30 minutes from now. Returned as naive UTC."""
    tz = ZoneInfo(settings.timezone)
    start = (after or now()).replace(tzinfo=ZoneInfo("UTC")).astimezone(tz) + timedelta(minutes=30)
    t = start.replace(hour=settings.outreach_send_hour, minute=0, second=0, microsecond=0)
    if t < start:
        t += timedelta(days=1)
    while t.weekday() >= 5:
        t += timedelta(days=1)
    return t.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def check_login(address: str, app_password: str) -> str | None:
    """None when Gmail accepts the app password, else a plain reason."""
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as s:
            s.login(address, app_password)
        return None
    except smtplib.SMTPAuthenticationError:
        return ("Gmail didn't accept that app password. Make sure it's the 16-letter app password (not your Gmail "
                "password) and that 2-Step Verification is on.")
    except (OSError, smtplib.SMTPException) as e:
        return f"Couldn't reach Gmail ({e.__class__.__name__}). Check your connection and try again."


def build(p: Prospect) -> EmailMessage:
    m = EmailMessage()
    m["From"] = formataddr((SENDER_NAME, settings.gmail_address))
    m["To"] = p.email
    m["Subject"] = p.subject or "Spring 2027 internship inquiry"
    m["Message-ID"] = make_msgid(domain=settings.gmail_address.split("@")[-1])
    m.set_content(p.email_body or "")
    r = resume_path()
    if r and "attached" in (p.email_body or "").lower():
        m.add_attachment(r.read_bytes(), maintype="application", subtype="pdf", filename=r.stem.replace("_", " ") + r.suffix)
    return m


def _remove_gmail_draft(p: Prospect) -> None:
    """Best effort: the weekday task may also have saved this email as a Gmail draft."""
    if not p.draft_id:
        return
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=20) as im:
            im.login(settings.gmail_address, settings.gmail_app_password)
            im.select('"[Gmail]/Drafts"')
            subject = re.sub(r'["\\\r\n]', " ", p.subject or "")[:120]
            typ, data = im.search(None, "TO", f'"{p.email}"', "SUBJECT", f'"{subject}"')
            for num in (data[0].split() if typ == "OK" and data and data[0] else []):
                im.store(num, "+FLAGS", "\\Deleted")
            im.expunge()
    except Exception:
        log.info("couldn't remove the Gmail draft for %s", p.email)


def send_one(p: Prospect) -> bool:
    msg = build(p)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(settings.gmail_address, settings.gmail_app_password)
            s.send_message(msg)
    except smtplib.SMTPRecipientsRefused:
        p.status, p.send_error = "bounced", "Gmail refused the address."
        return False
    except (OSError, smtplib.SMTPException) as e:
        p.send_error = f"Not sent yet: {e.__class__.__name__}. Noderze will try again in a few minutes."
        p.send_at = now() + timedelta(minutes=10)
        return False
    p.status, p.sent_at, p.send_error, p.message_id = "sent", now(), None, msg["Message-ID"]
    _remove_gmail_draft(p)
    return True


def send_due(db: Session) -> int:
    """Every minute: send approved emails whose time has come."""
    if not configured():
        return 0
    due = list(db.scalars(select(Prospect).where(Prospect.status == "scheduled", Prospect.send_at <= now(),
                                                 Prospect.email.is_not(None)).order_by(Prospect.send_at, Prospect.id)
                          .limit(PER_RUN)))
    sent = 0
    for p in due:
        sent += send_one(p)
        db.commit()
    if due:
        from .outreach import write_state
        write_state(db)
    return sent
