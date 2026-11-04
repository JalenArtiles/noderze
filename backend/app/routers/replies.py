"""Replies: emails from companies you applied to (see services/replies.py for how they arrive)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import STAGES, Application, ApplicationEvent, EmailReply
from ..services import prep
from ..services import replies as RP
from ..util import today

router = APIRouter(prefix="/api")


@router.get("/replies")
def list_replies(include_dismissed: bool = False, db: Session = Depends(get_db)):
    q = select(EmailReply).order_by(EmailReply.received_at.desc(), EmailReply.id.desc())
    if not include_dismissed:
        q = q.where(EmailReply.dismissed.is_(False))
    rows = list(db.scalars(q))
    watch = RP.watch_list(db)
    accounts = sorted({r.account for r in rows if r.account})
    return {"items": [RP.reply_dict(db, r) | {"needs_you": RP.needs_you(db, r)} for r in rows],
            "unseen": len(RP.unseen(db)), "last_check": RP.last_check(), "accounts": accounts,
            "watching": len(watch), "watching_applied": sum(1 for w in watch if w["applied"])}


@router.patch("/replies/{rid}")
def patch_reply(rid: int, body: dict, db: Session = Depends(get_db)):
    r = db.get(EmailReply, rid)
    if r is None:
        raise HTTPException(404)
    for k in ("seen", "dismissed"):
        if k in body:
            setattr(r, k, bool(body[k]))
    db.commit()
    return RP.reply_dict(db, r)


@router.post("/replies/seen")
def mark_all_seen(db: Session = Depends(get_db)):
    n = 0
    for r in db.scalars(select(EmailReply).where(EmailReply.seen.is_(False))):
        r.seen = True
        n += 1
    db.commit()
    return {"seen": n}


@router.post("/replies/{rid}/apply")
def apply_suggestion(rid: int, db: Session = Depends(get_db)):
    """Make the stage change the email suggests (Mark as applied, Move to Interviewing, ...)."""
    r = db.get(EmailReply, rid)
    if r is None:
        raise HTTPException(404)
    a = db.get(Application, r.application_id) if r.application_id else None
    sug = RP.reply_dict(db, r)["suggest"]
    if not a or not sug or sug["stage"] not in STAGES:
        raise HTTPException(400, "Nothing to change for this email.")
    if sug["stage"] == "applied":
        a.date_applied = a.date_applied or (r.received_at.date() if r.received_at else today())
        a.follow_up_date = a.follow_up_date or a.date_applied + timedelta(days=prep.FOLLOW_UP_DAYS[0])
    db.add(ApplicationEvent(application_id=a.id, kind="stage", from_stage=a.stage, to_stage=sug["stage"],
                            note=f"From an email: {r.subject[:200]}"))
    a.stage = sug["stage"]
    a.readiness = prep.readiness(db, a)
    r.seen = True
    db.commit()
    return RP.reply_dict(db, r)
