"""Evidence and source helpers. Every fact shown in the UI comes through here."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CareerPath, Company, Evidence, Job, Program, Source
from ..util import now
from .scoring import CompanySignals

EMPLOYEE_REPORTED_HOSTS = ("glassdoor.", "reddit.", "repvue.", "teamblind.", "blind.", "levels.fyi", "indeed.com/cmp",
                           "linkedin.com/in/", "fishbowlapp.", "comparably.")
THIRD_PARTY_JOB_HOSTS = ("builtin", "wayup.", "simplify.jobs", "ziprecruiter.", "prosple.", "zapply.", "freehire.",
                         "dreamworkhq.", "tealhq.", "themuse.", "jointaro.", "indeed.com", "linkedin.com/jobs",
                         "startup.jobs", "huntr.", "career.com", "handshake")
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "amazon.jobs")
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def classify_source(url: str, company: Company | None = None) -> str:
    """official | employee_reported | third_party, decided by host."""
    u = url.lower()
    host = urlparse(u).netloc
    if company is not None:
        own = [d for d in [company.website, company.careers_url] if d]
        for d in own:
            h = urlparse(d.lower()).netloc.replace("www.", "")
            if h and h in host:
                return "official"
        if company.slug and (company.slug.replace("-", "") in host.replace("-", "").replace(".", "")):
            if not any(t in u for t in THIRD_PARTY_JOB_HOSTS + EMPLOYEE_REPORTED_HOSTS):
                return "official"
        if any(h in host for h in ATS_HOSTS):
            token = (company.ats_token or company.slug or "").lower()
            if token and token in u:
                return "official"
    if any(h in u for h in EMPLOYEE_REPORTED_HOSTS):
        return "employee_reported"
    return "third_party"


def default_confidence(source_type: str) -> str:
    return {"official": "high", "employee_reported": "medium", "third_party": "medium", "inferred": "low"}[source_type]


def upsert_source(db: Session, url: str, title: str | None, source_type: str, publisher: str | None = None) -> Source:
    src = db.scalar(select(Source).where(Source.url == url))
    if src:
        src.retrieved_at = now()
        if title and not src.title:
            src.title = title
        return src
    src = Source(url=url, title=title, source_type=source_type, publisher=publisher or urlparse(url).netloc)
    db.add(src)
    db.flush()
    return src


def add_evidence(db: Session, subject_type: str, subject_id: int, field: str, value: str, *, url: str | None,
                 source_title: str | None = None, source_type: str | None = None, confidence: str | None = None,
                 observed_on: date | None = None, note: str | None = None, company: Company | None = None) -> Evidence:
    """Insert a fact unless an identical (subject, field, value, source) fact already exists."""
    stype = source_type or (classify_source(url, company) if url else "inferred")
    src = upsert_source(db, url, source_title, stype) if url else None
    existing = db.scalar(select(Evidence).where(
        Evidence.subject_type == subject_type, Evidence.subject_id == subject_id, Evidence.field == field,
        Evidence.value == value, Evidence.source_id == (src.id if src else None)))
    if existing:
        existing.verified_at = now()
        return existing
    ev = Evidence(subject_type=subject_type, subject_id=subject_id, field=field, value=value,
                  source_id=src.id if src else None, source_type=stype,
                  confidence=confidence or default_confidence(stype), observed_on=observed_on, note=note,
                  verified_at=now())
    db.add(ev)
    db.flush()
    return ev


def evidence_for(db: Session, subject_type: str, subject_id: int) -> list[Evidence]:
    return list(db.scalars(select(Evidence).where(Evidence.subject_type == subject_type,
                                                  Evidence.subject_id == subject_id).order_by(Evidence.field)))


def grouped(evs: list[Evidence]) -> dict[str, list[dict]]:
    """field -> facts sorted by confidence, official first. Agreement across sources raises confidence."""
    out: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        out[e.field].append(serialize_evidence(e))
    for f, items in out.items():
        items.sort(key=lambda x: (-CONFIDENCE_RANK.get(x["confidence"], 0), x["source_type"] != "official"))
        values = [re.sub(r"\W+", " ", i["value"].lower()).strip() for i in items]
        for i, v in zip(items, values):
            i["corroborated_by"] = sum(1 for o in values if o == v) - 1
    return dict(out)


def serialize_evidence(e: Evidence) -> dict:
    return {
        "id": e.id, "field": e.field, "value": e.value, "source_type": e.source_type, "confidence": e.confidence,
        "observed_on": e.observed_on.isoformat() if e.observed_on else None, "note": e.note,
        "source": ({"url": e.source.url, "title": e.source.title, "publisher": e.source.publisher}
                   if e.source else None),
        "verified_at": e.verified_at.isoformat() if e.verified_at else None,
    }


def company_signals(db: Session, company: Company) -> CompanySignals:
    evs = evidence_for(db, "company", company.id)
    program_ids = [p.id for p in company.programs]
    prog_evs = [e for pid in program_ids for e in evidence_for(db, "program", pid)]
    se_programs = [p for p in company.programs if p.target_family == "se"]
    has_official_program = any(
        any(e.source_type == "official" for e in evidence_for(db, "program", p.id)) for p in se_programs)
    paths = list(db.scalars(select(CareerPath).where(CareerPath.company_id == company.id)))
    transitions = sum(1 for p in paths if p.reaches_se and p.entry_family in ("pipeline", "technical_entry"))
    has_se_org = bool(se_programs) or any(e.field in ("org.se_team", "org.se_role") for e in evs) or bool(
        db.scalar(select(Job.id).where(Job.company_id == company.id, Job.family == "direct_se").limit(1)))
    official_path = any(e.field == "path.internal_to_se" and e.source_type == "official" for e in evs)
    se_seen = int(((company.data or {}).get("se_team") or {}).get("open_se_roles") or 0)
    has_se_org = has_se_org or se_seen > 0
    return CompanySignals(
        has_se_program=bool(se_programs) and (has_official_program or bool(prog_evs)),
        se_transitions=transitions, has_se_org=has_se_org, official_internal_path=official_path,
        category=company.category, public_sector=company.public_sector, evidence_count=len(evs) + len(prog_evs),
        se_roles_seen=se_seen)


def program_is_official(db: Session, program: Program | None) -> bool:
    if not program:
        return False
    return any(e.source_type == "official" for e in evidence_for(db, "program", program.id))
