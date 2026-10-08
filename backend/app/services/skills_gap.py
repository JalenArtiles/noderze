"""Skill-gap analysis across the user's high-fit opportunities, turned into an ordered roadmap."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Job, LearningResource
from .profile import profile_view
from .taxonomy import AREA_LABELS, areas_in

NOT_SKILLS = {"quota", "ae_partnership", "customer_facing"}  # experiences, not things to study
ORDER = ["networking", "network_security", "security", "linux", "cloud", "apis", "programming", "demo", "presentation",
         "discovery", "objection_handling", "value_selling", "databases", "ai", "iot_hardware", "rfp"]
WHY = {
    "networking": "Almost every SE screen for security and infrastructure products starts with networking fundamentals.",
    "network_security": "Firewalls, VPNs and zero trust are the vocabulary of most security buyers.",
    "security": "Lets you explain risk in business terms, the core of selling security.",
    "linux": "Trials and POCs often happen on Linux hosts; basic comfort avoids stalls.",
    "cloud": "Most products you're targeting are cloud-delivered; buyers ask how it fits their AWS or Azure setup.",
    "apis": "Integrations come up in nearly every technical evaluation.",
    "programming": "A small script during a POC earns technical credibility fast.",
    "demo": "Demos are the most visible part of the SE job and a common interview round.",
    "presentation": "SE interviews almost always include a presentation or mock call.",
    "discovery": "Good discovery is what separates SEs from product experts.",
    "objection_handling": "Interviewers test it directly with role plays.",
    "value_selling": "Connecting features to outcomes is how SEs help AEs close.",
}


def roadmap(db: Session, min_score: float = 55) -> dict:
    pv = profile_view(db)
    have = pv.tech_areas | pv.sales_areas
    counts: Counter[str] = Counter()
    jobs = list(db.scalars(select(Job).where(Job.is_active.is_(True), Job.hidden.is_(False),
                                             Job.score_total >= min_score)))
    for j in jobs:
        text = f"{j.title}\n{j.description_text or ''}"
        for a in list(areas_in(text, "tech")) + list(areas_in(text, "sales")):
            if a not in have and a not in NOT_SKILLS:
                counts[a] += 1
    if "demo" not in have:
        counts["demo"] += 1  # always relevant for SE, even when postings don't say it
    if "presentation" not in have:
        counts["presentation"] += 1
    ranked = sorted(counts, key=lambda a: (ORDER.index(a) if a in ORDER else 99, -counts[a]))
    stages = []
    for i, area in enumerate(ranked[:6]):
        res = list(db.scalars(select(LearningResource).where(LearningResource.skill_area == area)))
        stages.append({"stage": "Now" if i == 0 else "Next", "area": AREA_LABELS.get(area, area), "key": area,
                       "postings": counts[area], "why": WHY.get(area, "Requested by your target postings."),
                       "resources": [{"title": r.title, "provider": r.provider, "url": r.url, "cost": r.cost,
                                      "kind": r.kind, "why": r.why} for r in res]})
    stages.append({"stage": "Then", "area": "Apply to SE development programs", "key": "apply", "postings": 0,
                   "why": "Use the projects above as talking points in applications and interviews.", "resources": []})
    return {"jobs_considered": len(jobs), "have": sorted(AREA_LABELS.get(a, a) for a in have), "stages": stages}
