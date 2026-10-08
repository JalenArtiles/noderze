"""Scheduled scans from AlertRule rows (cron syntax, evaluated in the configured time zone)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import AlertRule

log = logging.getLogger(__name__)
_scheduler = None


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
                trigger = CronTrigger.from_crontab(rule.cron, timezone=settings.timezone)
            except ValueError:
                log.warning("Bad cron for rule %s: %s", rule.id, rule.cron)
                continue
            wf = (rule.params or {}).get("workflow", "scan_alerts")
            kwargs = {"rule_id": rule.id} if wf == "scan_alerts" else {}
            _scheduler.add_job(start, trigger, args=[wf, rule.name, WORKFLOWS[wf]], kwargs=kwargs,
                               id=f"rule-{rule.id}", replace_existing=True)
    finally:
        db.close()


def shutdown() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
