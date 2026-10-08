"""Company and program research.

Pipeline: search -> classify each source (official / employee_reported / third_party) -> fetch pages we are
allowed to fetch -> extract facts -> store as Evidence.

Anti-hallucination guard: an LLM-extracted fact must include a short quote that is found verbatim (after
whitespace normalization) in the fetched text. If the quote is missing, the fact is stored as low confidence
with a note, or dropped when it would be the only support for a high-impact field.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, Evidence, Job, Person, Program, CareerPath
from ..util import now
from .ats import html_to_text
from .classify import _dates_in, parse_comp, parse_location
from .classify import sales_level as _sales_level
from .evidence import add_evidence, classify_source, evidence_for, grouped, serialize_evidence
from .fetch import FetchBlocked, PoliteFetcher
from .llm import llm
from .search import search

FIELDS = {
    "program.name": "Official program name", "program.role_title": "Exact role title",
    "program.description": "Program description", "program.eligibility": "Eligibility requirements",
    "program.grad_window": "Graduation-year requirements", "program.degree_req": "Degree requirements",
    "program.technical_req": "Technical requirements", "program.sales_req": "Sales requirements",
    "program.yoe": "Years of experience requested", "program.location": "Location",
    "program.work_mode": "Remote / hybrid / onsite", "comp.base": "Salary", "comp.variable": "Bonus or commission",
    "comp.equity": "Equity", "program.benefits": "Benefits", "program.duration": "Program duration",
    "program.training_content": "What happens during training", "program.technologies": "Technologies and products learned",
    "program.certifications": "Certifications offered", "program.mentorship": "Mentorship and coaching",
    "program.shadowing": "Shadowing", "program.customer_exposure": "Customer exposure",
    "program.rotations": "Rotations", "program.conversion": "Conversion into a full-time SE role",
    "program.next_role": "Typical next role", "path.promotion_timeline": "Typical timeline to promotion",
    "path.internal_to_se": "Internal path into SE", "program.outcomes": "Alumni outcomes",
    "program.start_date": "Program start date", "program.deadline": "Application deadline",
    "program.open_window": "When applications typically open", "program.rolling": "Rolling applications",
    "interview.process": "Interview process", "interview.stages": "Interview stages",
    "interview.technical": "Technical interview requirements", "interview.presentation": "Presentation or demo requirement",
    "travel.percent": "Expected travel", "intern.conversion": "Internship to full-time conversion",
    "org.se_team": "Sales / solutions engineering organization", "review.sentiment": "What participants and employees say",
    "company.products": "Products", "company.market": "Target market", "company.locations": "Office locations",
    "company.remote_policy": "Remote policy",
}
EXTRACT_SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "object", "properties": {
    "field": {"type": "string", "enum": list(FIELDS)},
    "value": {"type": "string", "description": "Concise paraphrase of the fact, under 40 words."},
    "quote": {"type": "string", "description": "Exact supporting text copied from the page, under 25 words."},
    "observed_on": {"type": "string", "description": "Date of the information if stated (YYYY-MM or YYYY-MM-DD), else empty."},
}, "required": ["field", "value", "quote"]}}}, "required": ["facts"]}
EXTRACT_SYSTEM = ("Extract facts about a company's early-career and sales engineering paths from one web page. Only "
                  "extract what the page states. Every fact needs an exact quote from the page. If the page is about a "
                  "different company or is not informative, return an empty list. Do not infer salaries, durations or "
                  "outcomes that are not written down.")


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def queries_for(company: Company, job: Job | None = None) -> list[str]:
    n = company.name
    qs = [f"{n} early career sales engineer program", f"{n} associate solutions engineer program",
          f'"{n}" "solutions engineer" OR "sales engineer" new grad', f"{n} sales development representative to sales engineer",
          f"{n} sales engineer interview process", f"{n} sales engineering academy reddit"]
    if job:
        qs.insert(0, f'"{job.title}" {n}')
    return qs


def regex_facts(text: str) -> list[dict]:
    """Deterministic extraction used when no LLM is configured. Conservative by design."""
    facts = []
    for m in re.finditer(r"(\d{1,2}|three|six|twelve|nine|five|eight)[- ]month(?:s)?(?: long)? (?:program|academy|"
                         r"training|rotation|cohort|bootcamp)", text, re.I):
        facts.append({"field": "program.duration", "value": m.group(0), "quote": m.group(0)})
    c = parse_comp(text)
    if c.min:
        rng = f"${c.min:,.0f}" + (f" to ${c.max:,.0f}" if c.max and c.max != c.min else "") + f" per {c.period}"
        facts.append({"field": "comp.base", "value": rng + (f" ({c.note})" if c.note else ""), "quote": rng})
    for sent in re.split(r"(?<=[.!?\n])\s+", text):
        s = sent.strip()
        if len(s) < 25 or len(s) > 400:
            continue
        low = s.lower()
        if re.search(r"\bstart(?:s|ing)? date|\bstarts? in\b|cohort start", low) and _dates_in(s):
            facts.append({"field": "program.start_date", "value": s[:200], "quote": s[:120]})
        elif re.search(r"\bmentor", low):
            facts.append({"field": "program.mentorship", "value": s[:200], "quote": s[:120]})
        elif re.search(r"\bcertif", low) and re.search(r"program|training|earn|complete|prepare", low):
            facts.append({"field": "program.certifications", "value": s[:200], "quote": s[:120]})
        elif re.search(r"\brotation", low):
            facts.append({"field": "program.rotations", "value": s[:200], "quote": s[:120]})
        elif re.search(r"upon (?:successful )?completion|after completing|graduates? (?:will|of the program)|transition into",
                       low) and re.search(r"engineer|consultant|architect|executive|role", low):
            facts.append({"field": "program.next_role", "value": s[:200], "quote": s[:120]})
        elif re.search(r"\bshadow", low):
            facts.append({"field": "program.shadowing", "value": s[:200], "quote": s[:120]})
        elif re.search(r"travel", low) and re.search(r"\d{1,3}\s?%", low):
            facts.append({"field": "travel.percent", "value": s[:200], "quote": s[:120]})
        elif re.search(r"interview", low) and re.search(r"stage|round|process|panel|presentation", low):
            facts.append({"field": "interview.process", "value": s[:200], "quote": s[:120]})
    return facts[:25]


def _store(db: Session, company: Company, facts: list[dict], url: str, title: str, page_text: str, stype: str,
           program: Program | None, log) -> int:
    n = 0
    norm_page = _norm(page_text)
    for f in facts:
        field = f.get("field")
        if field not in FIELDS or not f.get("value"):
            continue
        quote_ok = bool(f.get("quote")) and _norm(f["quote"]) in norm_page
        conf = {"official": "high", "employee_reported": "medium", "third_party": "medium"}[stype]
        note = None
        if not quote_ok:
            conf, note = "low", "Supporting quote not found on the page; verify manually."
            if field in ("comp.base", "program.duration", "program.conversion") and stype != "official":
                continue
        obs = None
        if f.get("observed_on"):
            try:
                parts = [int(x) for x in f["observed_on"].split("-")]
                obs = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
            except (ValueError, IndexError):
                obs = None
        subject = ("program", program.id) if program and (field.startswith(("program.", "comp.", "interview.", "intern."))) \
            else ("company", company.id)
        add_evidence(db, subject[0], subject[1], field, f["value"].replace("\u2014", ", ")[:600], url=url,
                     source_title=title, source_type=stype, confidence=conf, observed_on=obs, note=note, company=company)
        n += 1
    return n


def _program_for(db: Session, company: Company, facts: list[dict]) -> Program | None:
    names = [f["value"] for f in facts if f.get("field") == "program.name"]
    titles = [f["value"] for f in facts if f.get("field") == "program.role_title"]
    if not names and not titles:
        return company.programs[0] if len(company.programs) == 1 else None
    label = (names or titles)[0][:280]
    for p in company.programs:
        if _norm(p.name) in _norm(label) or _norm(label) in _norm(p.name) or (
                p.role_title and titles and _norm(p.role_title) == _norm(titles[0])):
            return p
    target = "se" if re.search(r"engineer|consultant|architect|advisor|presales|pre-sales", label + " ".join(titles), re.I) \
        else "ae" if re.search(r"account executive|sales rep|sdr|bdr|development rep", label, re.I) else "mixed"
    p = Program(company_id=company.id, name=label, role_title=titles[0][:280] if titles else None,
                target_family=target, status="unknown")
    db.add(p)
    db.flush()
    return p


def deep_research(db: Session, company: Company, log, job: Job | None = None, max_pages: int = 8) -> dict:
    stats = {"queries": 0, "results": 0, "pages": 0, "facts": 0, "snippet_facts": 0}
    f = PoliteFetcher()
    seen: set[str] = set()
    pages = 0
    try:
        for q in queries_for(company, job):
            stats["queries"] += 1
            results = search(q, n=6)
            if not results:
                log(f"No search results for: {q} (is a search provider configured?)")
            for r in results:
                if r.url in seen:
                    continue
                seen.add(r.url)
                stats["results"] += 1
                if company.name.lower().split()[0] not in f"{r.title} {r.snippet} {r.url}".lower():
                    continue
                stype = classify_source(r.url, company)
                ok, why = f.check(r.url)
                if not ok or pages >= max_pages:
                    if r.snippet and stype == "employee_reported":
                        add_evidence(db, "company", company.id, "review.sentiment", r.snippet[:400], url=r.url,
                                     source_title=r.title, source_type=stype, confidence="low",
                                     note="From a search snippet; page not fetched (" + why + ").", company=company)
                        stats["snippet_facts"] += 1
                    continue
                try:
                    text = html_to_text(f.get_text(r.url))[:20000]
                except (FetchBlocked, Exception) as e:
                    log(f"skip {r.url}: {e}")
                    continue
                pages += 1
                stats["pages"] += 1
                if llm.available:
                    out = llm.structured(EXTRACT_SYSTEM, f"Company: {company.name}\nURL: {r.url}\n\n{text}",
                                         EXTRACT_SCHEMA, fast=True) or {}
                    facts = out.get("facts", [])
                else:
                    facts = regex_facts(text)
                program = _program_for(db, company, facts)
                stats["facts"] += _store(db, company, facts, r.url, r.title, text, stype, program, log)
                db.commit()
            if pages >= max_pages:
                break
    finally:
        f.close()
    log(f"{company.name}: {stats['facts']} facts from {stats['pages']} pages, {stats['snippet_facts']} snippet notes")
    return stats


# ----------------------------------------------------------------------------- reports

def confidence_summary(facts: list[dict]) -> dict:
    total = len(facts)
    official = sum(1 for f in facts if f["source_type"] == "official")
    high = sum(1 for f in facts if f["confidence"] == "high")
    level = "high" if total and official / total >= 0.5 and high >= 3 else "medium" if total >= 4 else "low"
    return {"facts": total, "official": official, "high_confidence": high, "overall": level}


def company_report(db: Session, company: Company) -> dict:
    cev = [serialize_evidence(e) for e in evidence_for(db, "company", company.id)]
    programs = []
    for p in company.programs:
        pev = evidence_for(db, "program", p.id)
        programs.append({"id": p.id, "name": p.name, "role_title": p.role_title, "target_family": p.target_family,
                         "status": p.status, "typical_open_window": p.typical_open_window, "summary": p.summary,
                         "facts": grouped(pev), "confidence": confidence_summary([serialize_evidence(e) for e in pev])})
    paths = list(db.scalars(select(CareerPath).where(CareerPath.company_id == company.id)))
    people = list(db.scalars(select(Person).where(Person.company_id == company.id).order_by(Person.priority)))
    jobs = list(db.scalars(select(Job).where(Job.company_id == company.id, Job.hidden.is_(False))
                           .order_by(Job.score_total.desc())))
    allfacts = cev + [f for p in programs for items in p["facts"].values() for f in items]
    return {
        "company": company_dict(company), "facts": grouped(evidence_for(db, "company", company.id)),
        "programs": programs, "career_paths": [path_dict(p) for p in paths],
        "people": [person_dict(p) for p in people], "jobs": [job_brief(j) for j in jobs],
        "standout": company.data.get("standout", []), "interview_notes": company.data.get("interview_notes", []),
        "confidence": confidence_summary(allfacts), "field_labels": FIELDS,
    }


def job_report(db: Session, job: Job) -> dict:
    comp = company_report(db, job.company)
    program = next((p for p in comp["programs"] if p["id"] == job.program_id), None)
    pf = (program or {}).get("facts", {})
    cf = comp["facts"]

    def pick(*fields):
        return [x for fld in fields for x in (pf.get(fld, []) + cf.get(fld, []))]

    sections = {
        "Company": [{"value": job.company.summary or "", "source_type": "inferred", "confidence": "medium"}] if job.company.summary else [],
        "Role": [{"value": job.title, "source_type": "official" if job.source_is_original else "third_party",
                  "confidence": "high" if job.source_is_original else "medium", "source": {"url": job.url}}],
        "Location": [{"value": f"{job.location_text or 'unknown'} ({job.remote_type})", "source_type": "official"
                      if job.source_is_original else "third_party", "confidence": "high" if job.source_is_original else "medium"}]
        + pick("program.location", "program.work_mode", "company.remote_policy"),
        "Compensation": ([{"value": f"${job.comp_min:,.0f} to ${job.comp_max:,.0f} per {job.comp_period}",
                           "source_type": "official" if job.source_is_original else "third_party", "confidence": "high"
                           if job.source_is_original else "medium", "note": job.comp_note}] if job.comp_min else [])
        + pick("comp.base", "comp.variable", "comp.equity"),
        "Career path": [{"value": f"{job.path_class}: " + (job.score_breakdown.get("career_path", {}).get("reasons", [""])[0]),
                         "source_type": "inferred", "confidence": "medium"}] + pick("path.internal_to_se", "program.next_role"),
        "Training": pick("program.duration", "program.training_content", "program.mentorship", "program.shadowing",
                         "program.rotations", "program.certifications"),
        "Technical requirements": pick("program.technical_req", "program.degree_req"),
        "Sales requirements": pick("program.sales_req", "program.yoe"),
        "Program information": pick("program.name", "program.description", "program.eligibility", "program.grad_window",
                                    "program.start_date", "program.open_window", "program.rolling"),
        "Promotion timeline": pick("path.promotion_timeline", "program.conversion", "program.outcomes"),
        "Employee examples": [{"value": " > ".join(s["title"] for s in p["steps"]), "source_type": "employee_reported",
                               "confidence": p["confidence"]} for p in comp["career_paths"]],
        "Recruiters": [{"value": f"{p['name']}, {p['title'] or ''}", "note": p["reason"], "source_type": "employee_reported",
                        "confidence": "high" if p["verified"] else "low", "source": {"url": p["linkedin_url"]}}
                       for p in comp["people"] if p["role_category"] not in ("se", "asu_alum")][:5],
        "ASU alumni": [{"value": f"{p['name']}, {p['title'] or ''}", "source_type": "employee_reported",
                        "confidence": "high" if p["verified"] else "low", "source": {"url": p["linkedin_url"]}}
                       for p in comp["people"] if p["is_asu_alum"] in ("yes", "possible")][:5],
        "Interview process": pick("interview.process", "interview.stages", "interview.technical", "interview.presentation"),
        "Resume match": [{"value": f"Fits: {x['requirement']} ({x['evidence'][:80]})", "source_type": "inferred",
                          "confidence": "medium"} for x in job.analysis.get("fits", [])],
        "Missing qualifications": [{"value": x["requirement"] + (f" ({x['severity']})" if x.get("severity") else ""),
                                    "source_type": "inferred", "confidence": "medium"} for x in job.analysis.get("missing", [])],
        "How to stand out": [{"value": s.get("action", ""), "note": s.get("why"), "source_type": "inferred",
                              "confidence": "medium"} for s in comp["standout"]],
        "Application deadline": ([{"value": job.deadline.isoformat(), "source_type": "official", "confidence": "high"}]
                                 if job.deadline else []) + pick("program.deadline"),
    }
    sources = sorted({(f.get("source") or {}).get("url") for items in sections.values() for f in items
                      if (f.get("source") or {}).get("url")})
    facts = [f for items in sections.values() for f in items]
    return {"job": job_brief(job), "sections": sections, "sources": sources, "confidence": confidence_summary(facts),
            "freshness": {"discovered": job.discovered_at.isoformat() if job.discovered_at else None,
                          "last_verified": job.last_verified_at.isoformat() if job.last_verified_at else None,
                          "posted": job.posted_at.isoformat() if job.posted_at else None, "active": job.is_active}}


# ----------------------------------------------------------------------------- serializers (shared with routers)

def company_dict(c: Company) -> dict:
    return {k: getattr(c, k) for k in ("id", "name", "slug", "website", "careers_url", "industry", "category",
                                       "subcategory", "size", "hq", "az_presence", "ca_presence", "remote_policy",
                                       "public_sector", "ats_type", "ats_token", "ats_host", "ats_site", "ats_verified",
                                       "watch_status", "watch_note", "summary")} | {"data": c.data or {}}


def job_brief(j: Job) -> dict:
    return {
        "id": j.id, "company_id": j.company_id, "company": j.company.name if j.company else None, "title": j.title,
        "url": j.url, "apply_url": j.apply_url, "source": j.source, "source_is_original": j.source_is_original,
        "location_text": j.location_text, "remote_type": j.remote_type, "remote_scope": j.remote_scope,
        "family": j.family, "is_program": j.is_program, "program_id": j.program_id, "category": j.category,
        "path_class": j.path_class, "grad_status": j.grad_status, "grad_reason": j.grad_reason, "yoe_min": j.yoe_min,
        "comp_min": j.comp_min, "comp_max": j.comp_max, "comp_period": j.comp_period, "comp_note": j.comp_note,
        "score_total": j.score_total, "score_breakdown": j.score_breakdown, "analysis": j.analysis, "flags": j.flags,
        "deadline": j.deadline.isoformat() if j.deadline else None, "is_active": j.is_active,
        "needs_verification": j.needs_verification, "hidden": j.hidden,
        "discovered_at": j.discovered_at.isoformat() if j.discovered_at else None,
        "last_verified_at": j.last_verified_at.isoformat() if j.last_verified_at else None,
        "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        "company_category": j.company.category if j.company else None,
        "company_website": j.company.website if j.company else None,
        "sales_level": _sales_level(j.title),
        "se_roles_seen": int((((j.company.data or {}) if j.company else {}).get("se_team") or {}).get("open_se_roles") or 0),
        "program_name": j.program.name if j.program else None,
    }


def path_dict(p: CareerPath) -> dict:
    return {"id": p.id, "label": p.label, "steps": p.steps, "entry_family": p.entry_family, "reaches_se": p.reaches_se,
            "months_to_se": p.months_to_se, "asu": p.asu, "confidence": p.confidence}


def person_dict(p: Person) -> dict:
    return {k: getattr(p, k) for k in ("id", "company_id", "name", "title", "linkedin_url", "location", "role_category",
                                       "priority", "reason", "is_asu_alum", "verified", "do_not_contact", "snippet")}
