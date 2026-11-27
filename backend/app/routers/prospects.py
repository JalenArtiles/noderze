"""Internship outreach: the contacts the weekday task prepared, and what you did with each."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Prospect
from ..services import outreach as O
from ..util import now

router = APIRouter(prefix="/api")

SEARCH_ROLES = ("Data Analyst Intern", "Cybersecurity Intern", "Network Intern", "IT Intern")
SEARCH_PLACES = ("Phoenix, Arizona", "Remote")


def search_links() -> list[dict]:
    """The Google and LinkedIn searches from the post you saw: postings on LinkedIn found through Google, and
    LinkedIn's own search limited to the last hour or day. They open in your browser; Noderze never logs in."""
    from urllib.parse import quote_plus
    out = []
    for role in SEARCH_ROLES:
        for place in SEARCH_PLACES:
            g = f'site:linkedin.com/jobs "{role}" "{place.split(",")[0]}" spring 2027'
            base = (f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(role)}"
                    f"&location={quote_plus('United States' if place == 'Remote' else place)}")
            if place == "Remote":
                base += "&f_WT=2"
            out.append({"role": role, "place": place, "google": f"https://www.google.com/search?q={quote_plus(g)}",
                        "linkedin_hour": base + "&f_TPR=r3600", "linkedin_day": base + "&f_TPR=r86400"})
    return out


@router.get("/prospects")
def list_prospects(db: Session = Depends(get_db)):
    from ..services import mailer
    rows = list(db.scalars(select(Prospect).order_by(Prospect.created_at.desc(), Prospect.id)))
    batches = sorted({p.batch for p in rows if p.batch}, reverse=True)
    return {"items": [O.prospect_dict(p) for p in rows], "counts": O.counts(db), "last_batch": batches[0] if batches else None,
            "searches": search_links(), "sending": {"ready": mailer.configured(), "address": mailer.settings.gmail_address,
                                                    "next_send_at": mailer.next_send_time().isoformat(),
                                                    "timezone": mailer.settings.timezone},
            "applications": O.applications(db, rows)}


class ApproveIn(BaseModel):
    ids: list[int] | None = None


@router.post("/prospects/approve")
def approve_batch(body: ApproveIn, db: Session = Depends(get_db)):
    """You approve the day's emails: each goes out from your Gmail at the next send time. Until then you can still
    edit or cancel any of them."""
    from ..services import mailer
    if not mailer.configured():
        raise HTTPException(409, "Connect Gmail sending in Settings first.")
    n, at = O.approve(db, body.ids)
    db.commit()
    O.write_state(db)
    return {"scheduled": n, "send_at": at.isoformat()}


@router.post("/prospects/unschedule")
def unschedule_batch(body: ApproveIn, db: Session = Depends(get_db)):
    n = O.unschedule(db, body.ids)
    db.commit()
    O.write_state(db)
    return {"unscheduled": n}


class GmailIn(BaseModel):
    address: str | None = None
    app_password: str | None = None


@router.post("/settings/gmail-send")
def set_gmail_send(body: GmailIn):
    """Connect Gmail sending with an app password (checked with Gmail first, saved to backend/.env, never shown again).
    Sending an empty password disconnects it."""
    from ..config import save_env, settings
    from ..services import mailer
    address = (body.address or "").strip().lower()
    pw = (body.app_password or "").replace(" ", "").strip()
    if not pw:
        save_env("GMAIL_APP_PASSWORD", None)
        settings.gmail_app_password = None
        return {"ready": False, "address": settings.gmail_address}
    if not address.endswith("@gmail.com") or "@" not in address:
        raise HTTPException(400, "Use your Gmail address.")
    if len(pw) != 16:
        raise HTTPException(400, "A Gmail app password is 16 letters. Copy it from Google's App passwords page.")
    err = mailer.check_login(address, pw)
    if err:
        raise HTTPException(400, err)
    save_env("GMAIL_ADDRESS", address)
    save_env("GMAIL_APP_PASSWORD", pw)
    settings.gmail_address, settings.gmail_app_password = address, pw
    return {"ready": True, "address": address}


@router.patch("/prospects/{pid}")
def patch_prospect(pid: int, body: dict, db: Session = Depends(get_db)):
    p = db.get(Prospect, pid)
    if not p:
        raise HTTPException(404, "Not found")
    st = body.get("status")
    if st:
        if st not in O.STATUSES:
            raise HTTPException(400, "Unknown status")
        if st == "scheduled":
            raise HTTPException(400, "Use Approve batch to schedule emails.")
        p.status = st
        if st in ("sent", "connected") and not p.sent_at:
            p.sent_at = now()
    for k in ("note", "followup", "subject"):
        if k in body:
            setattr(p, k, (body[k] or "").strip() or None)
    if "body" in body:
        p.email_body = (body["body"] or "").strip() or None
    if st in ("ready", "drafted", "skipped"):
        p.send_at, p.approved_at = None, None
    if p.note and len(p.note) > O.NOTE_LIMIT:
        raise HTTPException(400, f"LinkedIn notes can be {O.NOTE_LIMIT} characters at most.")
    db.commit()
    O.write_state(db)
    return O.prospect_dict(p)
