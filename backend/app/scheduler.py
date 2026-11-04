"""Scheduled scans from AlertRule rows (cron syntax, evaluated in the configured time zone)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import AlertRule

log = logging.getLogger(__name__)
_scheduler = None


_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def crontab_days(expr: str) -> str:
    """Standard crontab counts days from Sunday = 0, but APScheduler counts from Monday = 0, so "0 2 * * 0"
    would run on Mondays. Day numbers are rewritten as names, which both read the same way."""
    import re
    parts = expr.split()
    if len(parts) == 5:
        parts[4] = re.sub(r"(?<![/\d])([0-7])(?!\d)", lambda m: _DAYS[int(m.group(1))], parts[4])
    return " ".join(parts)


def reload() -> None:
    global _scheduler
    if not settings.enable_scheduler:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        log.warning("APScheduler not installed; scheduled scans disabled")
        return
    from .workflows import WORKFLOWS

    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=settings.timezone)
        _scheduler.start()
    _scheduler.remove_all_jobs()
    db = SessionLocal()
    try:
        for rule in db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))):
            try:
                trigger = CronTrigger.from_crontab(crontab_days(rule.cron), timezone=settings.timezone)
            except ValueError:
                log.warning("Bad cron for rule %s: %s", rule.id, rule.cron)
                continue
            wf = (rule.params or {}).get("workflow", "scan_alerts")
            if wf not in WORKFLOWS:
                log.warning("Rule %s names an unknown workflow: %s", rule.id, wf)
                continue
            kwargs = {"rule_id": rule.id} if wf == "scan_alerts" else {}
            # A laptop that was asleep, or a restart at the wrong second, used to skip the scan entirely
            # (the default grace period is one second). Now a missed scan runs once, late, when Noderze is back.
            _scheduler.add_job(_run_rule, trigger, args=[rule.id, wf, rule.name], kwargs=kwargs,
                               id=f"rule-{rule.id}", replace_existing=True, misfire_grace_time=12 * 3600,
                               coalesce=True)
    finally:
        db.close()
    _scheduler.add_job(drop_folders, "interval", minutes=1, id="intern-imports", replace_existing=True,
                       coalesce=True, max_instances=1)


def _run_rule(alert_rule: int, wf: str, name: str, **kwargs) -> None:
    """Start a scheduled workflow and note when it ran, so Settings shows the real last run.
    (scan_alerts also gets rule_id in kwargs, so this parameter must not be called rule_id.)"""
    from .util import now
    from .workflows import WORKFLOWS, start
    db = SessionLocal()
    try:
        rule = db.get(AlertRule, alert_rule)
        if rule is not None:
            rule.last_run_at = now()
            db.commit()
    finally:
        db.close()
    start(wf, name, WORKFLOWS[wf], **kwargs)


def drop_folders() -> None:
    """Every minute: internships dropped in data/intern-imports/ and emails dropped in data/reply-imports/ are added,
    and data/reply-imports/watch.json is kept current for the scheduled Gmail check."""
    from .services import intern_jobs, replies
    for name, fn in (("intern imports", intern_jobs.import_dropped), ("reply imports", replies.import_dropped),
                     ("reply watch list", replies.write_watch)):
        db = SessionLocal()
        try:
            fn(db)
        except Exception:
            log.exception("%s failed", name)
        finally:
            db.close()


def shutdown() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
