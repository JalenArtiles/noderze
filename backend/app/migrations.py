"""One-time data fixes, applied in the background at startup and recorded in the profile."""
from __future__ import annotations

import logging

from sqlalchemy import select, update

from .db import SessionLocal
from .models import Alert, Company, Job
from .services.jobs_engine import rescore_all
from .services.profile import get_profile, load_seed_profile

log = logging.getLogger("noderze.migrations")


def _baseline_alerts(db) -> None:
    # The first scan of each company created an alert for every posting; those are a baseline, not news.
    db.execute(update(Alert).values(seen=True))


def _start_month(db) -> None:
    # Older databases predate "available_start"; copy it from the seed profile when it has one.
    start = load_seed_profile().get("available_start")
    if not start:
        return
    prof = get_profile(db)
    data = dict(prof.data or {})
    data.setdefault("available_start", start)
    prof.data = data


def _rescore(db) -> None:
    rescore_all(db)


GENERIC_NOTE = "Cybersecurity company (curated)."


def _clear_generic_notes(db) -> None:
    # Boilerplate seed notes repeated on every curated company; a note should only say something specific.
    db.execute(update(Company).where(Company.watch_note.like(GENERIC_NOTE + "%")).values(watch_note=None))


def _refresh_resume_checks(db) -> None:
    from .services import resume as R
    from .services.profile import master_resume
    res = master_resume(db)
    if res:
        res.checks = R.consistency_checks(res.parsed, get_profile(db).data or {})


INTERN_RULE = "Daily: spring internships (Phoenix area and remote)"


def _intern_rule(db) -> None:
    from sqlalchemy import select

    from .models import AlertRule
    if not db.scalar(select(AlertRule.id).where(AlertRule.name == INTERN_RULE)):
        db.add(AlertRule(name=INTERN_RULE, cron="40 6 * * *", params={"workflow": "find_internships"}, enabled=True))
        db.commit()
        from . import scheduler
        scheduler.reload()


def _first_intern_scan(db) -> None:
    """Fill the Spring internships page right after the update. Checked at every start until one search has
    finished, because an update can restart the backend in the middle of the first search."""
    from .config import settings
    if not settings.enable_scheduler or (get_profile(db).data or {}).get("intern_last_scan"):
        return  # tests and offline runs, or already done
    from .workflows import WORKFLOWS, start
    start("find_internships", "First spring internship search", WORKFLOWS["find_internships"])


def _rewrite_cover_letters(db) -> None:
    """Redraft cover letters you haven't approved in the new pattern. Approved letters are never touched."""
    from sqlalchemy import select

    from .models import GeneratedDoc, Job
    from .services import prep
    from .services import writing as W
    for d in db.scalars(select(GeneratedDoc).where(GeneratedDoc.kind == "cover_letter", GeneratedDoc.status != "approved")):
        job = db.get(Job, d.job_id) if d.job_id else None
        if not job:
            continue
        text, by = W.cover_letter(prep._ctx(db, job))
        d.content, flags = W.style_check(text, "cover_letter")
        d.flags, d.generated_by = flags, by


def _next_action_v2(db) -> None:
    """Stock answers with [bracketed] prompts are gone; so is the reminder to fill them."""
    from sqlalchemy import select

    from .models import Application
    from .services.prep import NEXT_ACTION
    for a in db.scalars(select(Application).where(Application.next_action == "Review resume edits and fill the [bracketed] prompts")):
        a.next_action = NEXT_ACTION


def _refilter_replies(db) -> None:
    """Stricter email rules: meeting reports, calendar notices and class mail that mention interviews are dropped."""
    from .services import replies
    n = replies.refilter(db)
    if n:
        log.info("removed %s emails that weren't about an application", n)


def _intern_details(db) -> None:
    """Newer date and hours reading (explicit date ranges, benefits boilerplate), then a live check of every
    listed internship right after the update."""
    from sqlalchemy import select

    from .config import settings
    from .models import Job
    from .services.intern_jobs import evaluate_job
    for job in db.scalars(select(Job).where(Job.family == "internship")):
        evaluate_job(db, job)
    db.commit()
    if settings.enable_scheduler:
        from .workflows import WORKFLOWS, start
        start("verify_internships", "Check every internship posting", WORKFLOWS["verify_internships"])


def _first_verify(db) -> None:
    """Check every listed internship against its live posting until one full check has finished. Checked at every
    start, because an update restarts the backend and can cut a check short."""
    from .config import settings
    prof = (get_profile(db).data or {})
    if not settings.enable_scheduler or prof.get("intern_last_verify") or not prof.get("intern_last_scan"):
        return
    from .workflows import WORKFLOWS, start
    start("verify_internships", "Check every internship posting", WORKFLOWS["verify_internships"])


def _verify_again(db) -> None:
    """The first live check stopped on Windows at a date format; run it once more."""
    from .config import settings
    if settings.enable_scheduler:
        from .workflows import WORKFLOWS, start
        start("verify_internships", "Check every internship posting", WORKFLOWS["verify_internships"])


def _logos(db) -> None:
    """Logos for companies that arrived without a website (Workday and Greenhouse links, Muse copies, emails)."""
    from .services import logos
    log.info("found logos for %s companies", logos.fill(db))


def _sales_track(db) -> None:
    """Spring Sales Internships: re-check every stored internship under the new rules (sales titles get their own list),
    then search once so the new list fills in without waiting for tomorrow morning."""
    from .config import settings
    from .services.intern_jobs import FAMILY, evaluate_job, write_report
    data = get_profile(db).data or {}
    for job in list(db.scalars(select(Job).where(Job.family == FAMILY))):
        evaluate_job(db, job, prof_data=data)
    db.commit()
    write_report(db)
    if settings.enable_scheduler:
        from .services.intern_jobs import request_search
        request_search()


def _search_soon(db) -> None:
    """The searches started by sales_track_v1 and v2 were cut short by the update's restarts: ask again, this time
    as a request that survives restarts."""
    from .config import settings
    from .services.intern_jobs import request_search
    if settings.enable_scheduler:
        request_search()


def _sales_track_v2(db) -> None:
    """"Sales Data Analytics Intern" and the like are analytics work: back to Applied Computing Spring Internships.
    Searches again too (the first search was cut short by the update)."""
    _sales_track(db)


# rescore_v3_2: enterprise/strategic AE roles, foreign postings and state-limited remote roles left the entry list.
STEPS = [("alerts_baseline_v1", _baseline_alerts), ("available_start_v1", _start_month), ("rescore_v3_1", _rescore),
         ("rescore_v3_2", _rescore), ("generic_notes_v1", _clear_generic_notes),
         ("resume_checks_v1", _refresh_resume_checks), ("intern_rule_v1", _intern_rule),
         ("rescore_interns_v1", _rescore),  # internship checks after the first live search
         ("cover_letters_v2", _rewrite_cover_letters), ("next_action_v2", _next_action_v2),
         ("replies_refilter_v1", _refilter_replies), ("intern_verify_v1", _intern_details),
         ("logos_v1", _logos), ("intern_verify_v2", _verify_again), ("sales_track_v1", _sales_track),
         ("sales_track_v2", _sales_track_v2), ("sales_search_v1", _search_soon)]


def apply_profile_updates(db) -> int:
    """Small edits to your saved profile, dropped as JSON files in data/profile-updates/ (private, never published).
    Each file is applied once: {"id": "...", "remove_skills": ["Go", ...], "set": {"key": value}}."""
    import json

    from .config import settings
    folder = settings.data_dir / "profile-updates"
    if not folder.exists():
        return 0
    prof = get_profile(db)
    data = dict(prof.data or {})
    applied = set(data.get("profile_updates_applied", []))
    n = 0
    for path in sorted(folder.glob("*.json")):
        try:
            upd = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("profile update %s is not valid JSON", path.name)
            continue
        uid = upd.get("id") or path.stem
        if uid in applied:
            continue
        drop = {x.strip().lower() for x in upd.get("remove_skills", [])}
        if drop:
            skills = dict(data.get("skills") or {})
            for k, v in skills.items():
                if isinstance(v, str):
                    skills[k] = ", ".join(x for x in (y.strip() for y in v.split(",")) if x and x.lower() not in drop)
            data["skills"] = skills
            data["verified_claims"] = [c for c in data.get("verified_claims", []) if c.strip().lower() not in drop]
        for k, v in (upd.get("set") or {}).items():
            data[k] = v
        applied.add(uid)
        n += 1
    if n:
        data["profile_updates_applied"] = sorted(applied)
        prof.data = data
        db.commit()
        _refresh_resume_checks(db)
        db.commit()
        rescore_all(db)
        log.info("applied %s profile update(s)", n)
    return n


def run() -> None:
    db = SessionLocal()
    try:
        for name, fn in STEPS:
            db.expire_all()  # this runs beside the app: always read the profile fresh so a change made meanwhile stays
            prof = get_profile(db)
            done = set((prof.data or {}).get("migrations", []))
            if name in done:
                continue
            fn(db)
            db.commit()
            db.expire_all()
            prof = get_profile(db)
            data = dict(prof.data or {})
            data["migrations"] = sorted(done | {name})
            prof.data = data
            db.commit()
            log.info("migration %s applied", name)
        apply_profile_updates(db)
        _first_intern_scan(db)
        _first_verify(db)
    except Exception:
        db.rollback()
        log.exception("migration failed")
    finally:
        db.close()
