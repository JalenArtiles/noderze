"""Structured candidate profile and derived views."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR
from ..models import Profile, Resume
from .scoring import DEFAULT_WEIGHTS, ProfileView
from .taxonomy import areas_in

SEED_DIR = BACKEND_DIR / "seed"
SEED_PROFILE = SEED_DIR / "profile.json"  # your real profile: gitignored, never published
EXAMPLE_PROFILE = SEED_DIR / "profile.example.json"  # a sample candidate, shipped with the code


def seed_profile_path() -> Path | None:
    """Your own profile.json if it exists, otherwise the example profile."""
    for path in (SEED_PROFILE, EXAMPLE_PROFILE):
        if path.exists():
            return path
    return None


def load_seed_profile() -> dict:
    path = seed_profile_path()
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def get_profile(db: Session) -> Profile:
    prof = db.scalar(select(Profile).limit(1))
    if prof is None:
        data = load_seed_profile()
        prof = Profile(data=data, weights=dict(DEFAULT_WEIGHTS))
        db.add(prof)
        db.commit()
    return prof


def master_resume(db: Session) -> Resume | None:
    return db.scalar(select(Resume).where(Resume.is_master.is_(True)).order_by(Resume.uploaded_at.desc()).limit(1))


def _flatten(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _flatten(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _flatten(v)]
    return []


def profile_text(db: Session) -> str:
    prof = get_profile(db)
    d = prof.data or {}
    parts = _flatten(d.get("skills", {})) + _flatten(d.get("coursework", [])) + _flatten(d.get("certifications", []))
    parts += _flatten(d.get("experience_highlights", []))
    res = master_resume(db)
    if res:
        parts += [f["text"] for f in res.ledger if f.get("section") not in ("summary", "header")]
    return "\n".join(parts)


def profile_view(db: Session) -> ProfileView:
    prof = get_profile(db)
    d = prof.data or {}
    text = profile_text(db)
    tech = set(areas_in(text, "tech"))
    sales = set(areas_in(text, "sales"))
    locs = d.get("locations", {})
    return ProfileView(
        tech_areas=tech, sales_areas=sales,
        primary_states=set(locs.get("primary_states", ["AZ"])),
        edge_states=set(locs.get("edge_states", [])),
        regions=set(locs.get("acceptable_regions", ["socal"])),
        remote_ok=bool(locs.get("remote_ok", True)),
        comp_target=float(d.get("comp_target", 75000)),
    )
