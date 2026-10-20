"""Stores and re-checks internship postings (Job rows with family "internship" plus an InternDetail)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Application, InternDetail, Job
from ..util import now
from .classify import parse_comp, parse_location
from .fit import why_this_role
from .internships import TRACK_LABELS, InternInput, evaluate
from .profile import get_profile, master_resume

FAMILY = "internship"
QUALIFY = "spring_intern"
OUT = "intern_out"
HINT_KEYS = ("time_type", "commitment", "employment_type", "feed_terms", "workplace")


def ensure_detail(db: Session, job: Job) -> InternDetail:
    d = job.intern or (db.scalar(select(InternDetail).where(InternDetail.job_id == job.id)) if job.id else None)
    if d is None:
        d = InternDetail(job=job, hints={}, overrides={}, sources=[], checks=[])
        db.add(d)
    return d


def absorb(d: InternDetail, extra: dict | None, source_label: str | None = None, readable: bool | None = None) -> None:
    """Keep the hints a source gave (Workday time type, Lever commitment, feed terms) and where it was found."""
    hints = dict(d.hints or {})
    for k in HINT_KEYS:
        v = (extra or {}).get(k)
        if v:
            hints[k] = v
    d.hints = hints
    if source_label and source_label not in (d.sources or []):
        d.sources = list(d.sources or []) + [source_label]
    if readable is not None:
        d.readable = readable


def evaluate_job(db: Session, job: Job, prof_data: dict | None = None, ledger: list | None = None) -> InternDetail:
    d = ensure_detail(db, job)
    prof = prof_data if prof_data is not None else (get_profile(db).data or {})
    company = job.company
    x = InternInput(
        title=job.title, description=job.description_text or "", location_text=job.location_text or "",
        workplace=(d.hints or {}).get("workplace"), comp_min=job.comp_min, comp_max=job.comp_max,
        comp_period=job.comp_period, hints=dict(d.hints or {}), is_active=job.is_active, readable=bool(d.readable),
        company_category=company.category if company else None, company_watch=company.watch_status if company else None,
        source_is_original=job.source_is_original, overrides=dict(d.overrides or {}))
    r = evaluate(x, prof.get("internship") or {})
    d.track, d.status, d.checks = r["track"], r["status"], r["checks"]
    d.pay, d.hours, d.term = r["pay"], r["hours"], r["term"]
    d.where = r["where"] | {"note": r["note"], "reasons_out": r["reasons_out"], "track_reason": r["track_reason"],
                            "track_strength": r["track_strength"]}
    d.evaluated_at = now()
    job.family = FAMILY
    job.category = QUALIFY if r["status"] != "out" else OUT
    job.score_total, job.score_breakdown, job.flags = r["score"], r["breakdown"], r["flags"]
    job.path_class, job.grad_status, job.grad_reason, job.is_program, job.yoe_min = None, None, None, False, None
    job.remote_type = {"remote": "remote", "hybrid_phoenix": "hybrid", "phoenix": "onsite"}.get(r["where"]["status"],
                                                                                                 "unknown")
    job.remote_scope = None
    job.locations = [{"state": s} for s in parse_location(job.location_text, "", job.title).states]
    if job.comp_min is None:
        c = parse_comp(job.description_text or "")
        if c.min is not None:
            job.comp_min, job.comp_max, job.comp_period, job.comp_note = c.min, c.max, c.period, c.note
    if ledger is None:
        res = master_resume(db)
        ledger = res.ledger if res else []
    skills = " ".join(str(v) for v in (prof.get("skills") or {}).values())
    certs = [c.get("name", "") if isinstance(c, dict) else str(c) for c in prof.get("certifications", [])]
    job.analysis = why_this_role(job.title, job.description_text or "", ledger, skills, certs)
    return d


def is_intern(job: Job | None) -> bool:
    return bool(job) and job.family == FAMILY


def intern_summary(job: Job) -> dict | None:
    """The internship fields shown on cards and the job page."""
    d = job.intern
    if not d:
        return None
    w = d.where or {}
    return {"track": d.track, "track_label": TRACK_LABELS.get(d.track, d.track), "status": d.status,
            "checks": d.checks or [], "pay": d.pay or {}, "hours": d.hours or {}, "term": d.term or {},
            "where": {k: w.get(k) for k in ("status", "label", "city", "tier")}, "note": w.get("note"),
            "reasons_out": w.get("reasons_out") or [], "track_reason": w.get("track_reason"),
            "track_strength": w.get("track_strength"), "sources": d.sources or [], "overrides": d.overrides or {},
            "readable": d.readable, "evaluated_at": d.evaluated_at.isoformat() if d.evaluated_at else None}


def set_override(db: Session, job: Job, key: str, value: bool) -> InternDetail:
    d = ensure_detail(db, job)
    ov = dict(d.overrides or {})
    if value:
        ov[key] = True
    else:
        ov.pop(key, None)
    d.overrides = ov
    evaluate_job(db, job)
    return d


def alert_new(db: Session, job: Job) -> None:
    if job.category == QUALIFY and not db.scalar(select(Alert.id).where(Alert.job_id == job.id)):
        pay = (job.intern.pay or {}).get("label") if job.intern else ""
        db.add(Alert(job_id=job.id, message=f"Spring internship: {job.company.name}, {job.title}"
                                            + (f" ({pay})" if pay and "$" in pay else "")))


def counts(db: Session) -> dict:
    jobs = list(db.scalars(select(Job).where(Job.family == FAMILY, Job.is_active.is_(True), Job.hidden.is_(False))))
    applied = set(db.scalars(select(Application.job_id).where(Application.job_id.in_([j.id for j in jobs])))) if jobs else set()
    out = {"qualifies": 0, "check": 0, "out": 0, "applied": len(applied)}
    for j in jobs:
        st = j.intern.status if j.intern else "out"
        out[st] = out.get(st, 0) + 1
    out["total_ok"] = out["qualifies"] + out["check"]
    return out


# ----------------------------------------------------------------------------- internships you found yourself

LOGIN_SITES = ("joinhandshake.com", "linkedin.com", "indeed.com")


class AddError(ValueError):
    """Shown to you as is: what to fix before the internship can be added."""


def add_found(db: Session, data: dict, fetcher=None) -> Job:
    """Add an internship you found (Handshake, LinkedIn, a career fair): a link Noderze can read, or pasted text.
    Links to sites that need you logged in are never fetched; their pasted text is used as is."""
    from ..models import Company
    from ..util import slugify
    from .ats import RawPosting
    from .discovery import upsert_posting
    from .fetch import PoliteFetcher
    from .intern_sources import resolve

    url, title = (data.get("url") or "").strip(), (data.get("title") or "").strip()
    location, desc = (data.get("location") or "").strip(), (data.get("description") or "").strip()
    p, original = None, False
    if url and not any(s in url.lower() for s in LOGIN_SITES):
        f = fetcher or PoliteFetcher(min_interval=0.5)
        try:
            p, original = resolve(f, url, title, location)
        finally:
            if fetcher is None:
                f.close()
        if not original:
            p = None
    if p is None:
        if not title or not desc:
            raise AddError("Noderze couldn't read that link (Handshake and LinkedIn need you logged in). "
                           "Paste the title and the posting text instead.")
        p = RawPosting(title=title, url=url, ats_job_id="", location_text=location, description=desc,
                       source="manual", extra={"full_text": True})
    if title:
        p.title = title
    if location:
        p.location_text = location
    name = (data.get("company_name") or (p.extra or {}).get("hiring_org") or "").strip()
    if not name:
        raise AddError("Add the company name.")
    company = db.scalar(select(Company).where(Company.slug == slugify(name)))
    if company is None:
        company = Company(name=name, slug=slugify(name), watch_note="Added with an internship you found.")
        db.add(company)
        db.flush()
    job, _ = upsert_posting(db, company, p, original=original, kind="intern", source_label=data.get("found_on") or "You added it")
    job.needs_verification = not original
    return job


def import_dropped(db: Session, folder=None) -> int:
    """Internships dropped as JSON files in data/intern-imports/ (one object or a list of them, with the same fields
    as Add one you found). Each file is added once, then moved to done/ with what happened to each internship."""
    import json
    import logging

    from ..config import settings
    log = logging.getLogger("noderze.intern_imports")
    folder = folder or settings.data_dir / "intern-imports"
    if not folder.exists():
        return 0
    added = 0
    for path in sorted(folder.glob("*.json")):
        results = []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            results.append({"error": "not valid JSON"})
            raw = []
        for item in raw if isinstance(raw, list) else [raw]:
            try:
                job = add_found(db, item)
                db.commit()
                d = evaluate_job(db, job)
                db.commit()
                results.append({"title": job.title, "company": job.company.name, "job_id": job.id, "status": d.status})
                added += 1
            except AddError as e:
                db.rollback()
                results.append({"title": item.get("title"), "error": str(e)})
            except Exception as e:  # one bad entry never blocks the rest
                db.rollback()
                log.exception("intern import failed for %s", item.get("title"))
                results.append({"title": item.get("title"), "error": type(e).__name__})
        done = folder / "done"
        done.mkdir(exist_ok=True)
        (done / path.name).write_text(json.dumps({"items": raw, "results": results}, indent=1), encoding="utf-8")
        path.unlink()
        log.info("imported %s from %s", len(results), path.name)
    return added
