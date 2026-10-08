"""Classify, enrich and score jobs. Pure functions live in classify.py and scoring.py."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Company, Job
from ..util import today
from .classify import classify_role, grad_compat, parse_comp, parse_location, parse_yoe
from .evidence import company_signals, program_is_official
from .fit import why_this_role
from .profile import get_profile, master_resume, profile_view
from .scoring import JobView, score_job


def available_start(prof_data: dict | None):
    """The month you can start full-time (profile "available_start", e.g. "2027-08"); None means a month after graduation."""
    from datetime import date
    v = str((prof_data or {}).get("available_start") or "")
    try:
        return date(int(v[:4]), int(v[5:7]), 1)
    except (ValueError, IndexError):
        return None


def enrich(job: Job, start=None) -> None:
    desc = job.description_text or ""
    rc = classify_role(job.title, desc)
    job.family = rc.family
    job.is_program = rc.is_program or job.program_id is not None
    loc = parse_location(job.location_text, desc, job.title)
    job.locations = [{"state": s} for s in loc.states]
    job.remote_type = loc.remote_type if loc.remote_type != "unknown" else job.remote_type
    job.remote_scope = loc.remote_scope
    if job.comp_min is None:
        c = parse_comp(desc)
        if c.min is not None:
            job.comp_min, job.comp_max, job.comp_period, job.comp_note = c.min, c.max, c.period, c.note
    yoe, _ = parse_yoe(desc)
    job.yoe_min = yoe
    job.grad_status, job.grad_reason = grad_compat(job.title, desc, settings.expected_graduation, today(), start)


def score(db: Session, job: Job, pview=None, weights=None, ledger=None, prof_data=None) -> None:
    company = job.company or db.get(Company, job.company_id)
    pview = pview or profile_view(db)
    prof = get_profile(db)
    weights = weights if weights is not None else prof.weights
    loc = parse_location(job.location_text, job.description_text, job.title)
    annual = None
    if job.comp_min is not None:
        mid = (job.comp_min + (job.comp_max or job.comp_min)) / 2
        annual = mid * 2080 if job.comp_period == "hour" else mid
    jv = JobView(
        title=job.title, family=job.family or "other", is_program=job.is_program,
        program_target=job.program.target_family if job.program else ("se" if job.family == "direct_se" and job.is_program else None),
        program_official=program_is_official(db, job.program), description=job.description_text or "",
        location=loc, grad_status=job.grad_status or "unclear", grad_reason=job.grad_reason or "",
        yoe_min=job.yoe_min, comp_annual_mid=annual, comp_known=annual is not None,
        source_is_original=job.source_is_original, last_verified_at=job.last_verified_at,
        company=company_signals(db, company))
    res = score_job(jv, pview, weights, today())
    job.score_total = res["total"]
    job.score_breakdown = res["breakdown"]
    job.path_class = res["path_class"]
    job.category = res["category"]
    job.flags = res["flags"]
    pdata = prof_data if prof_data is not None else (prof.data or {})
    res_m = master_resume(db)
    led = ledger if ledger is not None else (res_m.ledger if res_m else [])
    skills_text = " ".join(str(v) for v in (pdata.get("skills") or {}).values())
    certs = [c.get("name", "") if isinstance(c, dict) else str(c) for c in pdata.get("certifications", [])]
    job.analysis = why_this_role(job.title, job.description_text or "", led, skills_text, certs)


def enrich_and_score(db: Session, job: Job) -> Job:
    enrich(job, available_start(get_profile(db).data))
    score(db, job)
    return job


def rescore_all(db: Session) -> int:
    pview = profile_view(db)
    prof = get_profile(db)
    res_m = master_resume(db)
    ledger = res_m.ledger if res_m else []
    n = 0
    start = available_start(prof.data)
    for job in db.scalars(select(Job)):
        enrich(job, start)
        score(db, job, pview=pview, weights=prof.weights, ledger=ledger, prof_data=prof.data or {})
        n += 1
    db.commit()
    return n
