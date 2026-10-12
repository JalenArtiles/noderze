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


class RunLog:
    """The step log of one run. Calling it records a detail line under the current step; workflows declare
    their plan, move between steps, and close each step with a one-line result the interface shows."""

    def __init__(self, run: SearchRun, db: Session):
        self.run, self.db, self.current = run, db, None

    def _add(self, entry: dict) -> None:
        entry = {"at": now().isoformat(timespec="seconds"), **entry}
        if self.current is not None:
            entry.setdefault("step", self.current)
        self.run.log = list(self.run.log or []) + [entry]
        self.db.commit()

    def __call__(self, msg, level: str = "info") -> None:
        self._add({"msg": str(msg), "level": level})

    def warn(self, msg) -> None:
        self(msg, "warn")

    def plan(self, titles: list[str]) -> None:
        self._add({"type": "plan", "steps": list(titles)})

    def step(self, i: int) -> None:
        self.current = i
        self._add({"type": "step", "step": i})

    def done(self, summary: str) -> None:
        self._add({"type": "result", "msg": summary})

    def skip(self, reason: str) -> None:
        self._add({"type": "skip", "msg": reason})


def _execute(rid: int, fn, kwargs: dict) -> None:
    db = SessionLocal()
    run = db.get(SearchRun, rid)
    log = RunLog(run, db)

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
                    r.log = list(r.log or []) + [{"at": now().isoformat(timespec="seconds"), "msg": extra,
                                                  "level": "error"}]
                fin.commit()
        except Exception:
            fin.rollback()
        finally:
            fin.close()


TITLES = {"full_company_analysis": "Full company analysis", "deep_research": "Deep research", "discover_jobs": "Job scan",
          "find_recruiters": "People search", "prepare_application": "Application package", "scan_alerts": "Scheduled scan",
          "find_programs": "Program search", "wide_scan": "Wide scan", "import_feeds": "Job feeds"}


def run_view(r: SearchRun) -> dict:
    """Turn a run's log into steps for the interface: each planned step with a status (pending, running, done,
    skipped, failed), a one-line result, warnings, and the detail lines kept for an optional "details" view."""
    entries = list(r.log or [])
    plan = next((e["steps"] for e in entries if e.get("type") == "plan"), None)
    structured = plan is not None
    steps = [{"title": t, "status": "pending", "summary": None, "warnings": [], "lines": [], "started": None,
              "finished": None} for t in (plan or [TITLES.get(r.kind, r.kind.replace("_", " ").capitalize())])]
    current = None
    for e in entries:
        kind = e.get("type")
        if kind == "plan":
            continue
        if kind == "step":
            if current is not None and steps[current]["status"] == "running":
                steps[current]["status"], steps[current]["finished"] = "done", e.get("at")
            current = e["step"]
            steps[current].update(status="running", started=e.get("at"))
            continue
        i = e.get("step", current if current is not None else 0)
        if not 0 <= i < len(steps):
            i = len(steps) - 1
        st = steps[i]
        if kind == "skip":
            st.update(status="skipped", summary=e["msg"], finished=e.get("at"))
        elif kind == "result":
            st.update(status="done", summary=e["msg"], finished=e.get("at"))
        elif e.get("level") == "warn":
            st["warnings"].append(e["msg"])
            st["lines"].append(e["msg"])
        elif e.get("level") == "error":
            st["lines"].append(e["msg"])
        else:
            st["lines"].append(e["msg"])
    if not structured:  # runs logged before steps existed: one step holding every line
        steps[0]["status"] = "running" if r.status == "running" else ("failed" if r.status == "failed" else "done")
        steps[0]["summary"] = steps[0]["lines"][-1] if steps[0]["lines"] and r.status != "running" else None
    elif r.status != "running":
        for st in steps:
            if st["status"] == "running":
                st["status"] = "failed" if r.status == "failed" else "done"
            elif st["status"] == "pending":
                st["status"] = "not_run" if r.status == "failed" else "skipped"
    if r.status == "failed":
        bad = next((st for st in steps if st["status"] == "failed"), steps[-1])
        bad["status"], bad["summary"] = "failed", r.error
    result = r.result or {}
    done_n = sum(st["status"] in ("done", "skipped", "failed") for st in steps)
    return {"title": TITLES.get(r.kind, r.kind.replace("_", " ").capitalize()), "steps": steps,
            "progress": {"done": done_n, "total": len(steps)},
            "highlights": result.get("highlights", []), "notices": result.get("notices", [])}


# ----------------------------------------------------------------------------- workflow functions

NO_SEARCH = {"level": "warn", "text": "Web research and people search were skipped because no search provider is set up.",
             "action": {"label": "Set it up", "href": "/settings#connections"}}


def _scan_summary(results: list[dict]) -> str:
    relevant = sum(r.get("relevant", 0) for r in results)
    new = sum(r.get("new", 0) for r in results)
    return f"{relevant} roles that fit, {new} new since the last scan"


def wf_discover(db: Session, log, company_ids: list[int] | None = None, with_search: bool = True) -> dict:
    whole = not company_ids
    log.plan(["Scan company job boards", "Check new-grad feeds and job sites", "Search the web for leads"] if whole
             else ["Scan the job board"])
    log.step(0)
    res = discovery.discover(db, log, company_ids)
    unread = sum(1 for r in res if r.get("board") in ("unreadable", "blocked"))
    log.done(_scan_summary(res) + (f". {unread} boards couldn't be read this time" if unread else ""))
    out = {"companies": res}
    new = sum(r.get("new", 0) for r in res)
    if whole:
        log.step(1)
        out["feeds"] = sources.import_feeds(db, log)
        new += out["feeds"].get("new", 0)
        log.done(f"{out['feeds'].get('leads', 0)} relevant roles, {out['feeds'].get('new', 0)} new")
        log.step(2)
        if with_search and provider_name() != "none":
            out["search"] = discovery.search_leads(db, log)
            log.done(f"{out['search'].get('leads', 0)} new leads")
        else:
            log.skip("Skipped: needs a search provider")
    out["highlights"] = [{"label": "New roles", "value": new, "href": "/opportunities?new=1"},
                         {"label": "Roles that fit", "value": sum(r.get("relevant", 0) for r in res)}]
    if company_ids and len(res) == 1 and res[0].get("board"):
        out["notices"] = [{"level": "warn", "text": "No public job board was found for this company." if res[0]["board"] == "missing"
                           else "The job board couldn't be read this time. The next scan tries again.",
                           "action": {"label": "Check its job board", "href": f"/companies/{company_ids[0]}?tab=settings"}}]
    return out


def wf_find_programs(db: Session, log) -> dict:
    log.plan(["Search for new programs", "Scan companies with programs"])
    out = {}
    log.step(0)
    if provider_name() != "none":
        out["search"] = discovery.search_leads(db, log, discovery.default_queries(db, programs_only=True))
        log.done(f"{out['search'].get('leads', 0)} new leads")
    else:
        log.skip("Skipped: needs a search provider")
    log.step(1)
    ids = [c.id for c in db.scalars(select(Company).where(Company.programs.any()))]
    out["companies"] = discovery.discover(db, log, ids)
    log.done(_scan_summary(out["companies"]))
    return out


def wf_deep_research(db: Session, log, company_id: int, job_id: int | None = None) -> dict:
    company = db.get(Company, company_id)
    log.plan(["Research the company on the web", "Update scores"])
    log.step(0)
    if provider_name() == "none":
        log.skip("Skipped: needs a search provider")
        stats = {"skipped": "no search provider", "notices": [NO_SEARCH]}
    else:
        stats = research.deep_research(db, company, log, db.get(Job, job_id) if job_id else None)
        log.done(f"{stats['facts']} sourced facts from {stats['pages']} pages")
        stats["highlights"] = [{"label": "Sourced facts", "value": stats["facts"], "href": f"/companies/{company_id}"}]
    log.step(1)
    rescore_all(db)
    log.done("Scores updated")
    return stats


def wf_find_recruiters(db: Session, log, company_id: int) -> dict:
    log.plan(["Find recruiters, SEs and alumni"])
    log.step(0)
    if provider_name() == "none":
        log.skip("Skipped: needs a search provider")
        return {"skipped": "no search provider", "notices": [NO_SEARCH]}
    out = recruiters.find_people(db, db.get(Company, company_id), log)
    log.done(f"{out['new']} new people, all unverified until you check them")
    out["highlights"] = [{"label": "New people", "value": out["new"], "href": f"/companies/{company_id}?tab=people"}]
    return out


def wf_prepare(db: Session, log, job_id: int) -> dict:
    log.plan(["Prepare your application package"])
    log.step(0)
    app = prep.prepare(db, db.get(Job, job_id), log)
    log.done(f"Ready to review, readiness {app.readiness['overall']}%")
    return {"application_id": app.id, "readiness": app.readiness,
            "highlights": [{"label": "Readiness", "value": f"{app.readiness['overall']}%", "href": f"/applications/{app.id}"}]}


def wf_full_company_analysis(db: Session, log, company_id: int) -> dict:
    c = db.get(Company, company_id)
    if not c.watch_status:
        c.watch_status = "monitor"
        db.commit()
    log.plan(["Research the company", "Scan its job board", "Check career paths", "Find recruiters and alumni",
              "Score every role", "Tailor your resume", "Plan how to stand out"])
    searching = provider_name() != "none"
    notices = [] if searching else [NO_SEARCH]

    log.step(0)
    if searching:
        r = research.deep_research(db, c, log)
        log.done(f"{r['facts']} sourced facts from {r['pages']} pages")
    else:
        r = {"skipped": "no search provider"}
        log.skip("Skipped: needs a search provider")

    log.step(1)
    from .services.fetch import PoliteFetcher
    f = PoliteFetcher()
    try:
        d = discovery.discover_company(db, f, c, log)
    finally:
        f.close()
    board = d.get("board")
    if board == "missing":
        log.skip("No public job board found")
        notices.append({"level": "warn", "text": f"No public job board was found for {c.name}.",
                        "action": {"label": "Set its job board", "href": f"/companies/{c.id}?tab=settings"}})
    elif board in ("unreadable", "blocked"):
        log.skip("Couldn't read the job board this time. Roles already saved are kept.")
        notices.append({"level": "warn", "text": f"{c.name}'s job board couldn't be read this time, so its roles weren't refreshed. "
                        "The next scan tries again.", "action": {"label": "Check the board settings", "href": f"/companies/{c.id}?tab=settings"}})
    else:
        log.done(f"{d['relevant']} roles that fit, {d['new']} new, {d.get('se_roles', 0)} open SE roles")

    log.step(2)
    from .models import CareerPath
    n_paths = len(list(db.scalars(select(CareerPath.id).where(CareerPath.company_id == c.id))))
    log.done(f"{n_paths} employee paths saved" if n_paths else
             "No employee paths yet. Paste public profiles on the Career paths tab to show SDR-to-SE moves.")

    log.step(3)
    if searching:
        p = recruiters.find_people(db, c, log)
        log.done(f"{p['new']} new people, all unverified until you check them")
    else:
        p = {"skipped": "no search provider"}
        log.skip("Skipped: needs a search provider")

    log.step(4)
    rescore_all(db)
    top = db.scalar(select(Job).where(Job.company_id == c.id, Job.is_active.is_(True), Job.hidden.is_(False))
                    .order_by(Job.score_total.desc()).limit(1))
    log.done(f"Best match: {top.title} ({round(top.score_total or 0)}/100)" if top else "No open roles to score")
    out = {"research": r, "jobs": d, "people": p, "top_job_id": top.id if top else None}

    log.step(5)
    v = None
    if not top:
        log.skip("Skipped: no open role to tailor for")
    elif not master_resume(db):
        log.skip("Skipped: upload your resume first")
        notices.append({"level": "info", "text": "Upload your resume to get a version tailored to each role.",
                        "action": {"label": "Upload resume", "href": "/resume"}})
    else:
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
        log.done(f"Tailored for {top.title}: {len(v.edits) if v else 0} suggested changes"
                 + (f", {len(drafts)} outreach drafts" if drafts else ""))

    log.step(6)
    out["standout"] = recommendations(c, top)[:5]
    log.done(f"{len(out['standout'])} ways to stand out, on the Stand out tab")

    for_you = sum(1 for j in db.scalars(select(Job).where(
        Job.company_id == c.id, Job.is_active.is_(True), Job.hidden.is_(False),
        Job.category.in_(("entry_sales", "other_sales", "program")))) if "outside_area" not in (j.flags or []))
    se_open = ((c.data or {}).get("se_team") or {}).get("open_se_roles")
    hl = [{"label": "Roles for you", "value": for_you, "href": f"/companies/{c.id}?tab=roles"},
          {"label": "New since last scan", "value": d.get("new", 0)},
          {"label": "Open SE roles", "value": se_open if se_open is not None else "?"}]
    if top:
        hl.append({"label": "Best match", "value": top.title, "detail": f"{round(top.score_total or 0)}/100",
                   "href": f"/apply/{top.id}"})
    out["highlights"], out["notices"] = hl, notices
    return out


def wf_scan_alerts(db: Session, log, rule_id: int | None = None) -> dict:
    rules = [db.get(AlertRule, rule_id)] if rule_id else list(db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))))
    log.plan(["Scan watched companies for new roles"])
    log.step(0)
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
    log.done(f"{created} new alerts")
    return {"alerts": created, "highlights": [{"label": "New alerts", "value": created, "href": "/opportunities?new=1"}]}


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
