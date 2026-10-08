"""Career-path reconstruction from public profile text the user pastes (LinkedIn 'Experience' section,
a PDF export, or a bio). We never scrape LinkedIn; the user brings the text, the engine structures it."""
from __future__ import annotations

import re
import string
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CareerPath, Company
from .classify import MONTHS, classify_role
from .evidence import upsert_source
from .llm import llm

DATE_LINE = re.compile(r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\b\d{4})\s*[-\u2013\u2014]\s*"
                       r"(present|current|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{4})", re.I)
EMPLOYMENT = re.compile(r"\u00b7\s*(full-time|part-time|internship|contract|self-employed|freelance|seasonal|apprenticeship)",
                        re.I)
DURATION_ONLY = re.compile(r"^\d+\s+yrs?(\s+\d+\s+mos?)?$|^\d+\s+mos?$", re.I)
LOCATION = re.compile(r"^[A-Z][A-Za-z .'-]+,\s*[A-Z][A-Za-z .]+(,\s*[A-Za-z .]+)?(\s*\u00b7.*)?$")


def _month(token: str) -> date | None:
    token = token.strip().lower()
    if token in ("present", "current"):
        return date.today()
    m = re.match(r"([a-z]+)\.?\s+(\d{4})", token)
    if m and m.group(1)[:3] in MONTHS:
        return date(int(m.group(2)), MONTHS[m.group(1)[:3]], 1)
    if re.fullmatch(r"\d{4}", token):
        return date(int(token), 1, 1)
    return None


def parse_profile_text(text: str) -> list[dict]:
    """Best-effort parse of pasted experience text into [{title, company, start, end}] (newest first)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    steps: list[dict] = []
    group_company = None
    for i, line in enumerate(lines):
        if DURATION_ONLY.match(line) and i > 0:
            group_company = lines[i - 1]
            continue
        m = DATE_LINE.search(line)
        if not m:
            continue
        j, company, title = i - 1, None, None
        while j >= 0 and (LOCATION.match(lines[j]) or DURATION_ONLY.match(lines[j])):
            j -= 1
        if j >= 0 and EMPLOYMENT.search(lines[j]):
            company = EMPLOYMENT.split(lines[j])[0].strip(" \u00b7")
            j -= 1
        if j >= 0:
            title = lines[j]
        if not company:
            company = group_company
        if title and not DATE_LINE.search(title):
            steps.append({"title": title, "company": company or "", "start": m.group(1), "end": m.group(2)})
    return steps


def llm_parse(text: str) -> list[dict]:
    schema = {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "company": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
        "required": ["title", "company"]}}}, "required": ["steps"]}
    out = llm.structured("Extract the work history from this profile text exactly as written, newest first. "
                         "Do not add roles that are not present.", text[:12000], schema, fast=True) or {}
    return out.get("steps", [])


def build_path(steps: list[dict], company_name: str) -> dict:
    """Annotate steps (oldest first) and compute whether/when the person reached SE at the company."""
    ordered = list(reversed(steps))
    for s in ordered:
        s["family"] = classify_role(s.get("title", "")).family
    at_company = [s for s in ordered if company_name.lower().split()[0] in (s.get("company") or "").lower()]
    entry = at_company[0] if at_company else (ordered[0] if ordered else None)
    se_steps = [s for s in at_company if s["family"] == "direct_se"]
    months = None
    if entry and se_steps:
        a, b = _month(entry.get("start", "")), _month(se_steps[0].get("start", ""))
        if a and b:
            months = (b.year - a.year) * 12 + (b.month - a.month)
    return {"steps": ordered, "entry_family": entry["family"] if entry else None, "reaches_se": bool(se_steps),
            "months_to_se": months}


def import_profile(db: Session, company: Company, text: str, url: str | None = None) -> CareerPath:
    steps = llm_parse(text) if llm.available else []
    if not steps:
        steps = parse_profile_text(text)
    info = build_path(steps, company.name)
    n = db.scalar(select(func.count(CareerPath.id)).where(CareerPath.company_id == company.id)) or 0
    src = upsert_source(db, url, "Public profile", "employee_reported") if url else None
    cp = CareerPath(company_id=company.id, label=f"Employee {string.ascii_uppercase[n % 26]}{'' if n < 26 else n // 26}",
                    steps=info["steps"], entry_family=info["entry_family"], reaches_se=info["reaches_se"],
                    months_to_se=info["months_to_se"], asu=bool(re.search(r"arizona state|\basu\b", text, re.I)),
                    source_id=src.id if src else None, confidence="medium" if len(steps) >= 2 else "low")
    db.add(cp)
    db.commit()
    return cp


def summarize_paths(paths: list[CareerPath]) -> dict:
    transitions = [p for p in paths if p.reaches_se and p.entry_family in ("pipeline", "technical_entry")]
    months = sorted(p.months_to_se for p in transitions if p.months_to_se is not None)
    return {"profiles": len(paths), "reached_se": sum(p.reaches_se for p in paths), "transitions": len(transitions),
            "median_months_to_se": months[len(months) // 2] if months else None,
            "asu_profiles": sum(p.asu for p in paths)}
