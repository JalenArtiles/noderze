"""'Find similar companies': ranks known companies by shared traits, and (when search is configured) proposes
new candidates as suggestions the user must accept."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company
from .llm import llm
from .search import search


def similar(db: Session, company: Company, web: bool = True) -> dict:
    known = []
    for c in db.scalars(select(Company).where(Company.id != company.id)):
        score, why = 0, []
        if c.category and c.category == company.category:
            score += 3
            why.append(f"same category ({c.category})")
        if c.subcategory and company.subcategory and set(c.subcategory.lower().split()) & set(company.subcategory.lower().split()):
            score += 2
            why.append("overlapping product area")
        if c.programs and company.programs:
            score += 2
            why.append("also runs an early-career program")
        if c.az_presence and company.az_presence:
            score += 1
            why.append("Arizona presence")
        if c.ca_presence and company.ca_presence:
            score += 1
            why.append("California presence")
        if score:
            known.append({"id": c.id, "name": c.name, "score": score, "why": ", ".join(why), "watch_status": c.watch_status})
    known.sort(key=lambda x: -x["score"])
    suggestions = []
    if web and llm.available:
        results = search(f"companies like {company.name} {company.subcategory or company.category or ''} "
                         f"associate sales engineer program", n=8)
        if results:
            schema = {"type": "object", "properties": {"companies": {"type": "array", "items": {"type": "object",
                      "properties": {"name": {"type": "string"}, "why": {"type": "string"}, "source_url": {"type": "string"}},
                      "required": ["name", "why", "source_url"]}}}, "required": ["companies"]}
            text = "\n".join(f"{r.title} | {r.url} | {r.snippet}" for r in results)
            out = llm.structured("List companies named in these search results that are similar to the target and "
                                 "plausibly hire early-career sales or solutions engineers. Only use names that appear "
                                 "in the results, and cite the result URL.", f"Target: {company.name}\n\n{text}",
                                 schema, fast=True) or {}
            names = {c["name"].lower() for c in known} | {company.name.lower()}
            suggestions = [s for s in out.get("companies", []) if s["name"].lower() not in names
                           and any(s["source_url"] == r.url for r in results)]
    return {"known": known[:10], "suggestions": suggestions[:10]}
