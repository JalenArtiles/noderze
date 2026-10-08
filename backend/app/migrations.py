"""One-time data fixes, applied in the background at startup and recorded in the profile."""
from __future__ import annotations

import logging

from sqlalchemy import update

from .db import SessionLocal
from .models import Alert
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


# rescore_v3_2: enterprise/strategic AE roles, foreign postings and state-limited remote roles left the entry list.
STEPS = [("alerts_baseline_v1", _baseline_alerts), ("available_start_v1", _start_month), ("rescore_v3_1", _rescore),
         ("rescore_v3_2", _rescore)]


def run() -> None:
    db = SessionLocal()
    try:
        for name, fn in STEPS:
            prof = get_profile(db)
            done = set((prof.data or {}).get("migrations", []))
            if name in done:
                continue
            fn(db)
            prof = get_profile(db)
            data = dict(prof.data or {})
            data["migrations"] = sorted(done | {name})
            prof.data = data
            db.commit()
            log.info("migration %s applied", name)
    except Exception:
        db.rollback()
        log.exception("migration failed")
    finally:
        db.close()
