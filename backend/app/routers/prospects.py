"""Internship outreach: the contacts the weekday task prepared, and what you did with each."""
from fastapi import APIRouter, Depends, HTTPException
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
    rows = list(db.scalars(select(Prospect).order_by(Prospect.created_at.desc(), Prospect.id)))
    batches = sorted({p.batch for p in rows if p.batch}, reverse=True)
    return {"items": [O.prospect_dict(p) for p in rows], "counts": O.counts(db), "last_batch": batches[0] if batches else None,
            "searches": search_links()}


@router.patch("/prospects/{pid}")
def patch_prospect(pid: int, body: dict, db: Session = Depends(get_db)):
    p = db.get(Prospect, pid)
    if not p:
        raise HTTPException(404, "Not found")
    st = body.get("status")
    if st:
        if st not in O.STATUSES:
            raise HTTPException(400, "Unknown status")
        p.status = st
        if st in ("sent", "connected") and not p.sent_at:
            p.sent_at = now()
    for k in ("note", "followup"):
        if k in body:
            setattr(p, k, (body[k] or "").strip() or None)
    db.commit()
    O.write_state(db)
    return O.prospect_dict(p)
