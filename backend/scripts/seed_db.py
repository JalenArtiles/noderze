"""Load researched seed data into the database.

    python scripts/seed_db.py                      # seed companies, programs, facts, jobs, profile, resources
    python scripts/seed_db.py --resume path.docx   # also ingest your master resume
    python scripts/seed_db.py --reset              # wipe the database first
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import BACKEND_DIR, settings  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import AlertRule, Company, Job, LearningResource, Program  # noqa: E402
from app.services.evidence import add_evidence  # noqa: E402
from app.services.jobs_engine import rescore_all  # noqa: E402
from app.services.profile import get_profile, load_seed_profile  # noqa: E402
from app.util import fingerprint, now, slugify  # noqa: E402

SEED = BACKEND_DIR / "seed"


def _date(s):
    return date.fromisoformat(s) if s else None


def _merge(base: dict, extra: dict) -> dict:
    """Deep-merge dicts; lists and plain values in `extra` replace the base value."""
    out = dict(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_companies() -> list[dict]:
    """The public research in companies.json, with your private notes from personal.json (if any) on top."""
    companies = json.loads((SEED / "companies.json").read_text(encoding="utf-8"))
    path = SEED / "personal.json"
    if not path.exists():
        return companies
    overlay = json.loads(path.read_text(encoding="utf-8")).get("companies", {})
    out = []
    for c in companies:
        extra = dict(overlay.get(c["name"], {}))
        progs = extra.pop("programs", {})
        c = _merge(c, extra)
        if progs:
            c["programs"] = [_merge(p, progs.get(p["name"], {})) for p in c.get("programs", [])]
        out.append(c)
    return out


def seed(db) -> dict:
    prof = get_profile(db)
    seed_prof = load_seed_profile()
    if (prof.data or {}).get("profile_version", 1) < seed_prof.get("profile_version", 1):
        data = dict(prof.data or {})
        for k in ("locations", "focus", "comp_target", "profile_version"):
            if k in seed_prof:
                data[k] = seed_prof[k]
        data.setdefault("verified_claims", [])
        prof.data = data
        db.commit()
    counts = {"companies": 0, "programs": 0, "facts": 0, "jobs": 0}
    for c in load_companies():
        comp = db.scalar(select(Company).where(Company.slug == slugify(c["name"])))
        fields = {k: v for k, v in c.items() if k not in ("evidence", "programs", "jobs")}
        if comp is None:
            comp = Company(slug=slugify(c["name"]), **fields)
            db.add(comp)
            counts["companies"] += 1
        else:
            for k, v in fields.items():
                if k in ("watch_status", "watch_note") and getattr(comp, k):
                    continue  # keep your own watchlist choices on re-seed
                setattr(comp, k, v)
        db.flush()
        for e in c.get("evidence", []):
            add_evidence(db, "company", comp.id, e["field"], e["value"], url=e["url"], source_title=e.get("title"),
                         source_type=e["source_type"], confidence=e.get("confidence"), observed_on=_date(e.get("observed_on")),
                         note=e.get("note"), company=comp)
            counts["facts"] += 1
        programs = {}
        for p in c.get("programs", []):
            prog = db.scalar(select(Program).where(Program.company_id == comp.id, Program.name == p["name"]))
            pf = {k: v for k, v in p.items() if k != "evidence"}
            if prog is None:
                prog = Program(company_id=comp.id, **pf)
                db.add(prog)
                counts["programs"] += 1
            else:
                for k, v in pf.items():
                    setattr(prog, k, v)
            db.flush()
            programs[p["name"]] = prog
            for e in p.get("evidence", []):
                add_evidence(db, "program", prog.id, e["field"], e["value"], url=e["url"], source_title=e.get("title"),
                             source_type=e["source_type"], confidence=e.get("confidence"),
                             observed_on=_date(e.get("observed_on")), note=e.get("note"), company=comp)
                counts["facts"] += 1
        for j in c.get("jobs", []):
            fp = fingerprint(comp.name, j["title"], None, j["url"])
            job = db.scalar(select(Job).where(Job.fingerprint == fp)) or Job(fingerprint=fp, company_id=comp.id,
                                                                             title=j["title"], discovered_at=now())
            job.company = comp
            job.url, job.location_text, job.description_text = j["url"], j["location_text"], j["description"]
            job.source, job.source_is_original = "seed", j.get("source_is_original", False)
            job.needs_verification = True  # seed facts were researched, but each posting must be re-verified live
            job.program = programs.get(j.get("program"))
            if j.get("posted"):
                job.posted_at = datetime.fromisoformat(j["posted"])
            if job.id is None:
                db.add(job)
                counts["jobs"] += 1
    for r in json.loads((SEED / "learning.json").read_text(encoding="utf-8")):
        if not db.scalar(select(LearningResource).where(LearningResource.title == r["title"])):
            db.add(LearningResource(**r))
    for r in json.loads((SEED / "alert_rules.json").read_text(encoding="utf-8")):
        existing = db.scalar(select(AlertRule).where(AlertRule.name == r["name"]))
        if existing is None:
            db.add(AlertRule(**r))
        elif r.get("enabled") is False:
            existing.enabled = False
    db.commit()
    rescore_all(db)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", help="path to your master resume (.docx)")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if args.reset:
        Base.metadata.drop_all(engine)
    init_db()
    db = SessionLocal()
    try:
        print("Seeded:", seed(db))
        if args.resume:
            from app.routers.apply import _ingest
            dest = settings.data_dir / "resumes" / "master.docx"
            shutil.copy(args.resume, dest)
            r = _ingest(db, str(dest), Path(args.resume).name)
            print(f"Resume: {len(r['ledger'])} facts, {len(r['checks'])} checks")
    finally:
        db.close()


if __name__ == "__main__":
    main()
