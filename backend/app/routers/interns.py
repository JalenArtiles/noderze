"""Spring internships: the list, its filters' data, manual adds and your own confirmations."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Application, Company, Job, SearchRun
from ..services import intern_jobs as IJ
from ..services.ats import RawPosting
from ..services.fetch import PoliteFetcher
from ..services.internships import DEFAULT_PREFS, TRACK_LABELS, prefs
from ..services.profile import get_profile
from ..services.research import job_brief
from ..util import slugify

router = APIRouter(prefix="/api")
HEAVY = ("score_breakdown", "analysis", "comp_note")


def _item(j: Job, apps: dict, unseen: set) -> dict:
    b = job_brief(j)
    return {k: v for k, v in b.items() if k not in HEAVY} | {"application_stage": apps.get(j.id), "new": j.id in unseen}


SEARCH_SITES = [
    ("Handshake", "ASU's main internship board. Log in with your ASU account.",
     "https://app.joinhandshake.com/stu/postings?query={q}"),
    ("LinkedIn, Phoenix", "Internship level, Phoenix area. Opens in your own browser.",
     "https://www.linkedin.com/jobs/search/?keywords={q}&location=Phoenix%2C%20Arizona%2C%20United%20States&f_E=1"),
    ("LinkedIn, remote", "Remote internships in the US.",
     "https://www.linkedin.com/jobs/search/?keywords={q}&location=United%20States&f_E=1&f_WT=2"),
    ("Indeed", "Part-time internships near Phoenix.", "https://www.indeed.com/jobs?q={q}+part+time&l=Phoenix%2C+AZ"),
    ("USAJOBS", "Federal student internships (Pathways) in the Phoenix area.",
     "https://www.usajobs.gov/search/results/?k={q}&l=Phoenix%2C%20Arizona&hp=student"),
]
FIXED_LINKS = [
    {"label": "State of Arizona jobs", "why": "Includes the Department of Homeland Security's cyber interns. Noderze scans "
                                             "this one too.", "url": "https://www.azstatejobs.gov/jobs/search?query=intern"},
    {"label": "City of Phoenix internships", "why": "The city posts its internships here; its job site doesn't allow "
                                                    "automated reading, so check it yourself.",
     "url": "https://www.phoenix.gov/administration/departments/hr/careers/internships.html"},
    {"label": "ASU student jobs", "why": "Paid campus jobs in IT and security; ask your coordinator if one can count.",
     "url": "https://students.asu.edu/employment/search"},
]
TRACK_QUERY = {"cyber": "cybersecurity intern", "data": "data analyst intern", "network": "network intern"}


def search_links() -> list[dict]:
    out = []
    for label, why, url in SEARCH_SITES:
        out.append({"label": label, "why": why,
                    "searches": [{"track": t, "label": TRACK_LABELS[t], "url": url.format(q=quote(q))}
                                 for t, q in TRACK_QUERY.items()]})
    return out


@router.get("/internships")
def internships(db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).where(Job.family == IJ.FAMILY, Job.hidden.is_(False), Job.is_active.is_(True))
                           .order_by(Job.score_total.desc())))
    apps = dict(db.execute(select(Application.job_id, Application.stage)).all())
    unseen = set(db.scalars(select(Alert.job_id).where(Alert.seen.is_(False), Alert.job_id.is_not(None))))
    prof = get_profile(db).data or {}
    run = db.scalar(select(SearchRun).where(SearchRun.kind == "find_internships").order_by(SearchRun.started_at.desc())
                    .limit(1))
    hidden = db.scalar(select(Job.id).where(Job.family == IJ.FAMILY, Job.hidden.is_(True)).limit(1))
    return {
        "items": [_item(j, apps, unseen) for j in jobs],
        "counts": IJ.counts(db),
        "prefs": prefs(prof),
        "last_scan": prof.get("intern_last_scan"),
        "running": bool(run and run.status == "running"),
        "has_hidden": bool(hidden),
        "links": search_links(), "fixed_links": FIXED_LINKS,
    }


class InternIn(BaseModel):
    url: str | None = None
    company_name: str | None = None
    title: str | None = None
    location: str | None = None
    description: str | None = None


@router.post("/internships")
def add_internship(body: InternIn, db: Session = Depends(get_db)):
    """Add one you found (Handshake, LinkedIn, a career fair): a link Noderze can read, or pasted text."""
    from ..services.discovery import upsert_posting
    from ..services.intern_sources import resolve
    p, original = None, False
    if body.url:
        f = PoliteFetcher(min_interval=0.5)
        try:
            p, original = resolve(f, body.url, body.title or "", body.location or "")
        finally:
            f.close()
        if not original:
            p = None
    if p is None:
        if not body.title or not body.description:
            raise HTTPException(400, "Noderze couldn't read that link (Handshake and LinkedIn need you logged in). "
                                     "Paste the title and the posting text instead.")
        p = RawPosting(title=body.title, url=body.url or "", ats_job_id="", location_text=body.location or "",
                       description=body.description, source="manual", extra={"full_text": True})
    if body.title:
        p.title = body.title
    if body.location:
        p.location_text = body.location
    name = (body.company_name or (p.extra or {}).get("hiring_org") or "").strip()
    if not name:
        raise HTTPException(400, "Add the company name.")
    company = db.scalar(select(Company).where(Company.slug == slugify(name)))
    if company is None:
        company = Company(name=name, slug=slugify(name), watch_note="Added with an internship you found.")
        db.add(company)
        db.flush()
    job, _ = upsert_posting(db, company, p, original=original, kind="intern", source_label="You added it")
    job.needs_verification = not original
    db.commit()
    apps = dict(db.execute(select(Application.job_id, Application.stage)).all())
    return _item(job, apps, set())


class InternPatch(BaseModel):
    paid: bool | None = None
    hours_ok: bool | None = None
    include: bool | None = None
    hidden: bool | None = None


@router.patch("/internships/{jid}")
def patch_internship(jid: int, body: InternPatch, db: Session = Depends(get_db)):
    """Your own confirmations: 'I confirmed it's paid', 'The hours work', 'Count it anyway', or hide it."""
    job = db.get(Job, jid)
    if not job or job.family != IJ.FAMILY:
        raise HTTPException(404, "Not an internship")
    for key in ("paid", "hours_ok", "include"):
        v = getattr(body, key)
        if v is not None:
            IJ.set_override(db, job, key, v)
    if body.hidden is not None:
        job.hidden = body.hidden
    db.commit()
    apps = dict(db.execute(select(Application.job_id, Application.stage)).all())
    return _item(job, apps, set())


@router.post("/internships/unhide")
def unhide(db: Session = Depends(get_db)):
    n = 0
    for j in db.scalars(select(Job).where(Job.family == IJ.FAMILY, Job.hidden.is_(True))):
        j.hidden = False
        n += 1
    db.commit()
    return {"unhidden": n}


@router.get("/internships/defaults")
def defaults():
    return DEFAULT_PREFS
