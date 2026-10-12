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
    from .workflows import WORKFLOWS, start

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
            kwargs = {"rule_id": rule.id} if wf == "scan_alerts" else {}
            # A laptop that was asleep, or a restart at the wrong second, used to skip the scan entirely
            # (the default grace period is one second). Now a missed scan runs once, late, when Noderze is back.
            _scheduler.add_job(start, trigger, args=[wf, rule.name, WORKFLOWS[wf]], kwargs=kwargs,
                               id=f"rule-{rule.id}", replace_existing=True, misfire_grace_time=12 * 3600,
                               coalesce=True)
    finally:
        db.close()


def shutdown() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
