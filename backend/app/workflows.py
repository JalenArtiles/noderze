"""Background workflows. Each run is a SearchRun row with a step log the UI polls."""
from __future__ import annotations

import threading
import traceback

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Alert, AlertRule, Company, Job, Person, SearchRun
from .services import discovery, prep, recruiters, research, sources
from .services import writing as W
from .services.jobs_engine import rescore_all
from .services.profile import get_profile, master_resume
from .services.search import provider_name
from .services.standout import recommendations
from .util import now


SCAN_KINDS = ("discover_jobs", "scan_alerts", "wide_scan", "import_feeds", "find_programs")
STALE_AFTER_S = 3 * 3600
_start_lock = threading.Lock()


def _running_scan(db: Session) -> SearchRun | None:
    """Only one scan at a time: a second click or a scheduled scan joins the one already running."""
    run = db.scalar(select(SearchRun).where(SearchRun.status == "running", SearchRun.kind.in_(SCAN_KINDS))
                    .order_by(SearchRun.started_at.desc()).limit(1))
    if run and (now() - run.started_at).total_seconds() > STALE_AFTER_S:
        run.status, run.error, run.finished_at = "failed", "Stopped responding; marked as interrupted.", now()
        db.commit()
        return None
    return run


def start(kind: str, subject: str | None, fn, **kwargs) -> int:
    with _start_lock:
        db = SessionLocal()
        try:
            if kind in SCAN_KINDS:
                existing = _running_scan(db)
                if existing:
                    return existing.id
            run = SearchRun(kind=kind, subject=subject, status="running", log=[])
            db.add(run)
            db.commit()
            rid = run.id
        finally:
            db.close()
    threading.Thread(target=_execute, args=(rid, fn, kwargs), daemon=True).start()
    return rid


def run_sync(kind: str, subject: str | None, fn, **kwargs) -> SearchRun:
    db = SessionLocal()
    run = SearchRun(kind=kind, subject=subject, status="running", log=[])
    db.add(run)
    db.commit()
    rid = run.id
    db.close()
    _execute(rid, fn, kwargs)
    db = SessionLocal()
    try:
        return db.get(SearchRun, rid)
    finally:
        db.close()


def mark_interrupted_runs() -> int:
    """On startup, nothing can still be running: close out runs left behind by a restart or crash."""
    db = SessionLocal()
    try:
        runs = list(db.scalars(select(SearchRun).where(SearchRun.status == "running")))
        for r in runs:
            r.status, r.error, r.finished_at = "failed", "Interrupted when Noderze restarted.", now()
        db.commit()
        return len(runs)
    finally:
        db.close()


def _execute(rid: int, fn, kwargs: dict) -> None:
    db = SessionLocal()
    run = db.get(SearchRun, rid)

    def log(msg: str) -> None:
        run.log = list(run.log or []) + [{"at": now().isoformat(timespec="seconds"), "msg": str(msg)}]
        db.commit()

    status, error, extra = "done", None, None
    try:
        result = fn(db, log, **kwargs)
        run.result = result if isinstance(result, dict) else {"value": result}
    except Exception as e:
        status, error = "failed", f"{e.__class__.__name__}: {e}"
        extra = traceback.format_exc(limit=3)[-800:]
    finally:
        # Always record the outcome, in a fresh session if the work session is broken, so a run can
        # never be left showing "running" forever.
        try:
            db.rollback() if status == "failed" else db.commit()
        except Exception:
            pass
        db.close()
        fin = SessionLocal()
        try:
            r = fin.get(SearchRun, rid)
            if r is not None:
                r.status, r.finished_at = status, now()
                if error:
                    r.error = error
                    r.log = list(r.log or []) + [{"at": now().isoformat(timespec="seconds"), "msg": extra}]
                fin.commit()
        except Exception:
            fin.rollback()
        finally:
            fin.close()


# ----------------------------------------------------------------------------- workflow functions

def wf_discover(db: Session, log, company_ids: list[int] | None = None, with_search: bool = True) -> dict:
    res = discovery.discover(db, log, company_ids)
    out = {"companies": res}
    if not company_ids:
        out["feeds"] = sources.import_feeds(db, log)
    if with_search and provider_name() != "none" and not company_ids:
        out["search"] = discovery.search_leads(db, log)
    elif with_search and not company_ids:
        log("No search provider configured; skipped web search leads (ATS scans still ran)")
    return out


def wf_find_programs(db: Session, log) -> dict:
    out = {}
    if provider_name() != "none":
        out["search"] = discovery.search_leads(db, log, discovery.default_queries(db, programs_only=True))
    ids = [c.id for c in db.scalars(select(Company).where(Company.programs.any()))]
    out["companies"] = discovery.discover(db, log, ids)
    return out


def wf_deep_research(db: Session, log, company_id: int, job_id: int | None = None) -> dict:
    company = db.get(Company, company_id)
    stats = research.deep_research(db, company, log, db.get(Job, job_id) if job_id else None)
    rescore_all(db)
    return stats


def wf_find_recruiters(db: Session, log, company_id: int) -> dict:
    return recruiters.find_people(db, db.get(Company, company_id), log)


def wf_prepare(db: Session, log, job_id: int) -> dict:
    app = prep.prepare(db, db.get(Job, job_id), log)
    return {"application_id": app.id, "readiness": app.readiness}


def wf_full_company_analysis(db: Session, log, company_id: int) -> dict:
    c = db.get(Company, company_id)
    if not c.watch_status:
        c.watch_status = "monitor"
        db.commit()
    log("Step 1/7: research company and programs")
    r = research.deep_research(db, c, log)
    log("Step 2/7: find jobs on the company's own board")
    from .services.fetch import PoliteFetcher
    f = PoliteFetcher()
    try:
        d = discovery.discover_company(db, f, c, log)
    finally:
        f.close()
    log("Step 3/7: career paths. Paste public profiles on the company page to add evidence of SDR-to-SE moves.")
    log("Step 4/7: recruiters, SEs and ASU alumni")
    p = recruiters.find_people(db, c, log) if provider_name() != "none" else {"skipped": "no search provider"}
    log("Step 5/7: score fit")
    rescore_all(db)
    top = db.scalar(select(Job).where(Job.company_id == c.id, Job.is_active.is_(True), Job.hidden.is_(False))
                    .order_by(Job.score_total.desc()).limit(1))
    out = {"research": r, "jobs": d, "people": p, "top_job_id": top.id if top else None}
    if top and master_resume(db):
        log(f"Step 6/7: resume recommendations for {top.title}")
        v = prep.tailor(db, top)
        out["resume_version_id"] = v.id if v else None
        ctx = prep._ctx(db, top)
        drafts = []
        for person in db.scalars(select(Person).where(Person.company_id == c.id).order_by(Person.priority).limit(2)):
            kind = "recruiter_connect" if "recruit" in person.role_category else (
                "alumni" if person.role_category == "asu_alum" else "employee_info")
            msg, _ = W.outreach(kind, {"name": person.name, "title": person.title}, ctx)
            drafts.append({"person": person.name, "kind": kind, "message": W.style_check(msg, kind)[0]})
        out["outreach_drafts"] = drafts
        db.commit()
    log("Step 7/7: stand-out plan")
    out["standout"] = recommendations(c, top)[:5]
    return out


def wf_scan_alerts(db: Session, log, rule_id: int | None = None) -> dict:
    rules = [db.get(AlertRule, rule_id)] if rule_id else list(db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))))
    created = 0
    for rule in rules:
        params = rule.params or {}
        statuses = params.get("watch_statuses") or list(discovery.WATCHED)
        ids = [c.id for c in db.scalars(select(Company).where(Company.watch_status.in_(statuses)))]
        before = now()
        results = discovery.discover(db, log, ids)
        baseline = {r["company_id"] for r in results if r.get("first_scan")}
        if params.get("search"):
            discovery.search_leads(db, log, discovery.default_queries(db, programs_only=bool(params.get("require_program"))))
        q = select(Job).where(Job.discovered_at >= before, Job.hidden.is_(False))
        for job in db.scalars(q):
            if job.company_id in baseline:
                continue  # a company's first scan is its baseline, not news
            if job.category == "long_shot" and not params.get("include_long_shots"):
                continue
            if (job.score_total or 0) < params.get("min_score", 0):
                continue
            if params.get("categories") and job.category not in params["categories"]:
                continue
            if params.get("require_program") and not job.is_program:
                continue
            states = set(params.get("states") or [])
            if states and not ({l.get("state") for l in job.locations or []} & states) and job.remote_type != "remote":
                continue
            if not db.scalar(select(Alert.id).where(Alert.job_id == job.id)):
                db.add(Alert(rule_id=rule.id, job_id=job.id,
                             message=f"{rule.name}: {job.company.name}, {job.title} ({job.score_total:.0f}/100)"))
                created += 1
        rule.last_run_at = now()
        db.commit()
    log(f"{created} new alerts")
    return {"alerts": created}


def wf_wide_scan(db: Session, log, include_workday: bool = False) -> dict:
    return sources.wide_scan(db, log, include_workday=include_workday)


def wf_import_feeds(db: Session, log) -> dict:
    return sources.import_feeds(db, log)


WORKFLOWS = {
    "wide_scan": wf_wide_scan, "import_feeds": wf_import_feeds,
    "discover_jobs": wf_discover, "find_programs": wf_find_programs, "deep_research": wf_deep_research,
    "find_recruiters": wf_find_recruiters, "prepare_application": wf_prepare,
    "full_company_analysis": wf_full_company_analysis, "scan_alerts": wf_scan_alerts,
}
