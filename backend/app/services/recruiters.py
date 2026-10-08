"""Recruiter, hiring manager, SE and ASU alumni discovery.

People come only from search results that point at a public linkedin.com/in/ profile, and the result must
mention the company. We store what the result shows, mark it unverified, and ask the user to confirm.
We never construct profile URLs, never guess names, and never fetch LinkedIn pages.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, Person
from .evidence import upsert_source
from .search import search

ROLE_QUERIES = [
    ("campus_recruiter", '("university recruiter" OR "campus recruiter" OR "early career recruiter" OR "early talent")'),
    ("se_recruiter", '("technical recruiter" OR "sales recruiter" OR "go-to-market recruiter") ("sales engineer" OR "solutions")'),
    ("talent_partner", '("talent acquisition" OR "talent partner") sales'),
    ("hiring_manager", '("sales engineering manager" OR "solutions engineering manager" OR "manager, sales engineering" OR "manager, solutions engineering")'),
    ("se", '("sales engineer" OR "solutions engineer" OR "solutions consultant")'),
    ("asu_alum", '"Arizona State University" ("sales engineer" OR "solutions engineer" OR "sales development" OR "account executive")'),
]
CATEGORY = [
    ("campus_recruiter", 1, r"university|campus|early (?:career|talent)|emerging talent|new grad"),
    ("se_recruiter", 2, r"(?:technical|sales|gtm|go-to-market).{0,20}recruit|recruit.{0,30}(?:sales|solutions)"),
    ("talent_partner", 4, r"talent acquisition|talent partner|recruit"),
    ("hiring_manager", 5, r"manager.{0,25}(?:sales|solutions) engineering|(?:sales|solutions) engineering manager|director.{0,20}(?:sales|solutions) engineering"),
    ("se", 6, r"sales engineer|solutions? engineer|solutions? consultant|pre-?sales|systems engineer|solutions architect"),
]
LABELS = {"campus_recruiter": "Campus / early-career recruiter", "se_recruiter": "Recruiter for sales or SE roles",
          "talent_partner": "Talent acquisition partner", "hiring_manager": "SE hiring manager",
          "se": "Current SE / solutions engineer", "asu_alum": "ASU alum", "other": "Other"}
PROFILE_URL = re.compile(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?$")


def parse_result(title: str, snippet: str, url: str, company: str) -> dict | None:
    clean = url.split("?")[0].rstrip("/")
    if not PROFILE_URL.match(clean + "/"):
        return None
    head = re.sub(r"\s*[|\u2013-]\s*LinkedIn\s*$", "", title).strip()
    parts = [p.strip() for p in re.split(r"\s+[-\u2013\u2014|]\s+", head) if p.strip()]
    if not parts or len(parts[0].split()) > 5:
        return None
    name = parts[0]
    role = parts[1] if len(parts) >= 2 and company.lower() not in parts[1].lower() else None
    blob = f"{head} {snippet}".lower()
    if company.lower().split()[0] not in blob:
        return None  # result does not tie this person to the company
    if role is None:
        m = re.search(r"((?:senior |associate |sr\. )?[a-z ,&-]{3,60}?) (?:at|@) " + re.escape(company.lower()), blob)
        role = m.group(1).strip().title() if m else None
    return {"name": name, "title": role, "linkedin_url": clean, "snippet": snippet[:400]}


def categorize(title: str | None, snippet: str) -> tuple[str, int]:
    blob = f"{title or ''} {snippet}".lower()
    for cat, prio, pat in CATEGORY:
        if re.search(pat, blob):
            return cat, prio
    return "other", 9


def reason_for(cat: str, company: str, title: str | None, asu: str, query_cat: str) -> str:
    base = {
        "campus_recruiter": f"Recruits early-career talent at {company}; the most likely owner of new-grad and program pipelines.",
        "se_recruiter": f"Recruits for sales or SE roles at {company}; can tell you which entry roles feed the SE team.",
        "talent_partner": f"Talent acquisition at {company}; useful if no campus recruiter is visible.",
        "hiring_manager": f"Manages sales or solutions engineers at {company}; a short, specific note can get you on their radar.",
        "se": f"Works as an SE at {company}; ask about their path and what the team looks for.",
        "other": f"Appears connected to {company}."}[cat]
    if asu in ("possible", "yes"):
        base += " Possibly an ASU alum (search result mentions Arizona State); verify before mentioning it."
    return base


def alumni_search_url(company: str) -> str:
    """LinkedIn's own alumni tool. The user opens this while logged in; we never fetch it."""
    return f"https://www.linkedin.com/school/arizona-state-university/people/?keywords={quote(company)}"


def find_people(db: Session, company: Company, log, per_query: int = 8) -> dict:
    stats = {"queries": 0, "found": 0, "new": 0}
    for qcat, clause in ROLE_QUERIES:
        q = f'site:linkedin.com/in "{company.name}" {clause}'
        stats["queries"] += 1
        for r in search(q, n=per_query):
            parsed = parse_result(r.title, r.snippet, r.url, company.name)
            if not parsed:
                continue
            stats["found"] += 1
            cat, prio = categorize(parsed["title"], parsed["snippet"])
            if cat == "other" and qcat == "asu_alum":
                cat, prio = "asu_alum", 3
            asu = "possible" if re.search(r"arizona state|\basu\b", f"{r.title} {r.snippet}", re.I) else "unknown"
            if asu == "possible" and cat in ("se", "other"):
                prio = min(prio, 3)
            person = db.scalar(select(Person).where(Person.linkedin_url == parsed["linkedin_url"]))
            if person is None:
                src = upsert_source(db, parsed["linkedin_url"], r.title, "employee_reported")
                person = Person(company_id=company.id, name=parsed["name"], title=parsed["title"],
                                linkedin_url=parsed["linkedin_url"], snippet=parsed["snippet"], source_id=src.id)
                db.add(person)
                stats["new"] += 1
            person.role_category, person.priority, person.is_asu_alum = cat, prio, (
                person.is_asu_alum if person.is_asu_alum == "yes" else asu)
            person.reason = reason_for(cat, company.name, parsed["title"], person.is_asu_alum, qcat)
        db.commit()
    log(f"{company.name}: {stats['new']} new people from {stats['found']} matching results (all unverified until you confirm)")
    stats["alumni_tool_url"] = alumni_search_url(company.name)
    return stats


def linkedin_links(company: str) -> list[dict]:
    """Searches you open in your own logged-in browser. Noderze never automates LinkedIn."""
    q = lambda t: quote(t)
    return [
        {"label": "Recruiters", "why": "Usually own entry sales hiring", "url": f"https://www.linkedin.com/search/results/people/?keywords={q(company + ' recruiter')}"},
        {"label": "Talent acquisition", "why": "Bigger companies use this title", "url": f"https://www.linkedin.com/search/results/people/?keywords={q(company + ' talent acquisition')}"},
        {"label": "SDR managers", "why": "The hiring manager for SDR and BDR roles", "url": f"https://www.linkedin.com/search/results/people/?keywords={q(company + ' sales development manager')}"},
        {"label": "Sales engineers", "why": "Your future team; ask how they got there", "url": f"https://www.linkedin.com/search/results/people/?keywords={q(company + ' sales engineer')}"},
        {"label": "ASU alumni", "why": "Warmest cold outreach you can send", "url": alumni_search_url(company)},
        {"label": "Company page (Follow)", "why": "Follow to see their posts and jobs", "url": f"https://www.linkedin.com/search/results/companies/?keywords={q(company)}"},
        {"label": "Their jobs on LinkedIn", "why": "Includes Easy Apply postings", "url": f"https://www.linkedin.com/jobs/search/?keywords={q(company + ' sales development')}&location=Arizona"},
    ]


def parse_connections_csv(text: str) -> list[dict]:
    """LinkedIn's own data export (Settings > Data privacy > Get a copy of your data > Connections).
    Email addresses are dropped; only name, profile URL, company, position and date are kept."""
    import csv
    import io
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("first name")), None)
    if start is None:
        return []
    out = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        name = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}".strip()
        if name:
            out.append({"name": name, "url": (row.get("URL") or "").strip() or None, "company": (row.get("Company") or "").strip(),
                        "position": (row.get("Position") or "").strip(), "connected_on": (row.get("Connected On") or "").strip()})
    return out


def import_connections(db: Session, text: str) -> dict:
    from ..util import slugify
    rows = parse_connections_csv(text)
    companies = {c.slug: c for c in db.scalars(select(Company))}
    matched = 0
    for r in rows:
        c = companies.get(slugify(r["company"])) if r["company"] else None
        if c is None and r["company"]:
            c = next((x for s, x in companies.items() if len(s) > 3 and (s in slugify(r["company"]) or slugify(r["company"]) in s)), None)
        if c is None:
            continue
        matched += 1
        person = db.scalar(select(Person).where(Person.linkedin_url == r["url"])) if r["url"] else None
        if person is None:
            person = Person(company_id=c.id, name=r["name"], linkedin_url=r["url"])
            db.add(person)
        cat, _ = categorize(r["position"], "")
        person.title, person.verified, person.priority = r["position"], True, 0
        person.role_category = cat if cat != "other" else "connection"
        person.snippet = "linkedin_connection"
        person.reason = (f"Your 1st-degree LinkedIn connection{' since ' + r['connected_on'] if r['connected_on'] else ''}. "
                         f"A warm message to someone you know beats any cold outreach.")
    db.commit()
    return {"connections": len(rows), "at_tracked_companies": matched}
