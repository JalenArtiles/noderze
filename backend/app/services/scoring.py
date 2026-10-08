"""Opportunity scoring.

Principles
- Every point is explained: each component returns (score, max, reasons).
- Weights are user-configurable; components are computed on a 0..1 scale and multiplied by weight.
- Path strength comes from evidence. A company having Sales Engineers does not make an SDR role a
  likely path into SE; that needs observed transitions or an official internal path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .classify import GRAD_LABELS, LocationInfo, is_senior_title
from .taxonomy import AREA_LABELS, areas_in

DEFAULT_WEIGHTS: dict[str, float] = {
    "career_path": 25, "technical_fit": 20, "geography": 15, "development": 10,
    "eligibility": 10, "sales_leverage": 10, "compensation": 5, "evidence": 5,
}
COMPONENT_LABELS = {
    "career_path": "Career path", "technical_fit": "Technical fit", "geography": "Geography",
    "development": "Development program", "eligibility": "Eligibility and timing",
    "sales_leverage": "Sales experience leverage", "compensation": "Compensation", "evidence": "Evidence strength",
}
PATH_LABELS = {
    "DIRECT": "A formal program or the role itself trains you into SE",
    "LIKELY": "Strong evidence of internal transitions into SE",
    "POSSIBLE": "Company supports mobility and has SEs, but little transition evidence",
    "WEAK": "No meaningful evidence of a path into SE",
}
PRIMARY_STATES = {"AZ", "CA"}
EDGE_STATES = {"TX", "FL"}
DOMAIN_RELEVANCE = {"cybersecurity": 1.0, "cloud_networking": 0.9, "ai": 0.9, "software": 0.8,
                    "it_solutions": 0.7, "public_safety": 0.75, None: 0.5}


@dataclass
class CompanySignals:
    has_se_program: bool = False
    se_transitions: int = 0
    has_se_org: bool = False
    official_internal_path: bool = False
    se_roles_seen: int = 0  # SE / SA openings counted on the company's own job board at the last scan
    category: str | None = None
    public_sector: bool = False
    evidence_count: int = 0


@dataclass
class JobView:
    title: str
    family: str
    is_program: bool
    program_target: str | None  # se | ae | mixed | None
    program_official: bool
    description: str
    location: LocationInfo
    grad_status: str
    grad_reason: str
    yoe_min: float | None
    comp_annual_mid: float | None
    comp_known: bool
    source_is_original: bool
    last_verified_at: datetime | None
    company: CompanySignals = field(default_factory=CompanySignals)


@dataclass
class ProfileView:
    tech_areas: set[str]
    sales_areas: set[str]
    primary_states: set[str] = field(default_factory=lambda: {"AZ"})
    edge_states: set[str] = field(default_factory=set)
    regions: set[str] = field(default_factory=lambda: {"socal"})  # acceptable regions outside primary states
    remote_ok: bool = True
    comp_target: float = 75000


def normalize_weights(weights: dict | None) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    for k, v in (weights or {}).items():
        if k in w:
            try:
                w[k] = max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    total = sum(w.values()) or 1.0
    return {k: v * 100.0 / total for k, v in w.items()}


def path_class_for(job: JobView) -> tuple[str, str]:
    c = job.company
    if job.family == "direct_se":
        return "DIRECT", "The role itself is a sales or solutions engineering role."
    if job.is_program and job.program_target == "se":
        return "DIRECT", "Formal program that trains participants into an SE role."
    if job.family in ("pipeline", "technical_entry"):
        if c.se_transitions >= 2 or c.official_internal_path:
            why = (f"{c.se_transitions} observed employee transitions into SE" if c.se_transitions >= 2
                   else "Official source describes an internal path into SE")
            return "LIKELY", why + "."
        if c.has_se_org or c.has_se_program:
            return "POSSIBLE", ("Company has an SE organization" + (" and an SE program" if c.has_se_program else "")
                                + ", but no observed transitions from this entry role yet.")
        return "WEAK", "No evidence yet that this entry role leads to SE here."
    return "WEAK", "Role family is not on a path to SE."


def _geo(job: JobView, prof: ProfileView, strong: bool) -> tuple[float, list[str], bool]:
    """Arizona first, then remote US, then acceptable regions (Southern California). Everything else is a long shot."""
    loc = job.location
    states, regions = set(loc.states), set(getattr(loc, "regions", []) or [])
    if loc.international_only:
        return 0.0, ["Posting is outside the US."], False
    if states & prof.primary_states:
        return 1.0, [f"In {', '.join(sorted(states & prof.primary_states))}, your home base ({loc.remote_type})."], False
    if loc.remote_type == "remote" and prof.remote_ok:
        if loc.allowed_states is not None:
            if set(loc.allowed_states) & prof.primary_states:
                return 0.95, [f"Remote, limited to {loc.remote_scope}, which includes Arizona."], False
            return 0.25, [f"Remote but limited to {loc.remote_scope}, which excludes Arizona. Verify before applying."], False
        if loc.remote_scope == "US":
            return 0.92, ["Remote within the US, so you can stay in Arizona. Confirm there's no state restriction."], False
        return 0.75, ["Marked remote, but the allowed locations aren't stated. Verify you can work from Arizona."], False
    if regions & prof.regions:
        return 0.8, ["Southern California, which you said works for you."], False
    if "ca_unknown" in regions:
        return 0.5, ["California, but the city isn't stated. Only Southern California fits your plan; check the posting."], False
    if states & prof.edge_states:
        return (0.6 if strong else 0.35), [f"{', '.join(sorted(states & prof.edge_states))} is an edge-case location."], True
    if states:
        where = "Northern California" if "norcal" in regions else ", ".join(sorted(states))
        return (0.3 if strong else 0.15), [f"In {where}, outside Arizona, remote and Southern California."], strong
    return 0.4, ["Location not parsed; verify."], False


def score_job(job: JobView, prof: ProfileView, weights: dict | None = None, today: date | None = None) -> dict:
    w = normalize_weights(weights)
    today = today or date.today()
    comps: dict[str, dict] = {}

    # Career path ---------------------------------------------------------
    pclass, preason = path_class_for(job)
    cp = {"DIRECT": 1.0, "LIKELY": 0.68, "POSSIBLE": 0.42, "WEAK": 0.15}[pclass]
    reasons = [f"{pclass}: {preason}"]
    if pclass == "POSSIBLE" and job.company.se_roles_seen:
        cp += min(0.2, 0.02 * job.company.se_roles_seen)
        reasons.append(f"The company's own job board shows {job.company.se_roles_seen} open SE or solutions roles, "
                       f"so there is a real SE team to grow into.")
    if job.family == "technical_entry" and pclass != "DIRECT":
        cp -= 0.05
        reasons.append("Technical entry roles usually take longer to convert into SE than pipeline roles with SE exposure.")
    if job.yoe_min and job.yoe_min >= 3 and job.family == "direct_se":
        cp = min(cp, 0.75)
        reasons.append("Mid-level SE role; strong path but not an entry point.")
    comps["career_path"] = {"raw": max(cp, 0.0), "reasons": reasons}

    # Technical fit ------------------------------------------------------
    jd_tech = areas_in(f"{job.title}\n{job.description}", "tech")
    domain = DOMAIN_RELEVANCE.get(job.company.category, 0.5)
    reasons = [f"Company domain relevance: {job.company.category or 'unknown'} ({domain:.0%})."]
    if jd_tech:
        have = [a for a in jd_tech if a in prof.tech_areas]
        miss = [a for a in jd_tech if a not in prof.tech_areas]
        overlap = len(have) / max(len(jd_tech), 3)
        if have:
            reasons.append("You cover: " + ", ".join(AREA_LABELS[a] for a in have) + ".")
        if miss:
            reasons.append("Gaps vs posting: " + ", ".join(AREA_LABELS[a] for a in miss) + ".")
        tf = 0.4 * domain + 0.6 * min(1.0, overlap)
    else:
        reasons.append("Posting text has no technical requirements parsed yet (fetch the original posting).")
        tf = 0.4 * domain + 0.6 * 0.5
    comps["technical_fit"] = {"raw": tf, "reasons": reasons}

    # Geography ----------------------------------------------------------
    strong = pclass == "DIRECT" and (job.is_program or job.family == "direct_se")
    g, reasons, edge = _geo(job, prof, strong)
    comps["geography"] = {"raw": g, "reasons": reasons}

    # Development --------------------------------------------------------
    d_low = (job.description or "").lower()
    dev_hits = [k for k, pat in {
        "formal training": r"training|bootcamp|curriculum|instruction|enablement",
        "mentorship": r"mentor",
        "certifications": r"certif",
        "shadowing": r"shadow",
        "cohort": r"cohort|academy|program",
        "rotations": r"rotation",
    }.items() if re.search(pat, d_low)]
    if job.is_program and job.program_official:
        dv, reasons = 1.0, ["Official development program."] + ([f"Mentions {', '.join(dev_hits)}."] if dev_hits else [])
    elif job.is_program:
        dv, reasons = 0.8, ["Program structure mentioned (not yet confirmed by an official source)."]
    elif dev_hits:
        dv = min(0.75, 0.2 + 0.12 * len(dev_hits))
        reasons = [f"Posting mentions {', '.join(dev_hits)}."]
    else:
        dv, reasons = 0.2, ["No training or mentorship described."]
    comps["development"] = {"raw": dv, "reasons": reasons}

    # Eligibility and timing ---------------------------------------------
    el = {"eligible_now": 1.0, "likely_may_2027": 1.0, "eligible_closer": 0.8, "internship_convert": 0.6,
          "unclear": 0.55, "requires_experience": 0.25, "too_early": 0.0, "too_late": 0.0}.get(job.grad_status, 0.5)
    reasons = [f"{GRAD_LABELS.get(job.grad_status, job.grad_status)}: {job.grad_reason}"]
    if job.yoe_min and job.grad_status not in ("too_early", "too_late"):
        if job.yoe_min >= 2:
            el = min(el, 0.35)
            reasons.append(f"Asks for {job.yoe_min:g}+ years.")
        elif job.yoe_min >= 1:
            reasons.append("Asks for about a year; internships and sales roles usually count.")
    comps["eligibility"] = {"raw": el, "reasons": reasons}

    # Sales leverage -----------------------------------------------------
    jd_sales = areas_in(f"{job.title}\n{job.description}", "sales")
    if jd_sales:
        have = [a for a in jd_sales if a in prof.sales_areas]
        sl = 0.3 + 0.7 * len(have) / max(len(jd_sales), 3)
        reasons = (["Your sales background maps to: " + ", ".join(AREA_LABELS[a] for a in have) + "."] if have
                   else ["Posting's sales asks are not yet in your profile."])
        missing = [AREA_LABELS[a] for a in jd_sales if a not in prof.sales_areas]
        if missing:
            reasons.append("Not yet demonstrated: " + ", ".join(missing) + ".")
    else:
        sl, reasons = 0.4, ["Posting text does not describe sales activities."]
    if job.family in ("pipeline", "direct_se"):
        sl = min(1.0, sl + 0.15)
    comps["sales_leverage"] = {"raw": min(sl, 1.0), "reasons": reasons}

    # Compensation -------------------------------------------------------
    mid = job.comp_annual_mid
    if mid is None:
        cv, reasons = 0.5, ["No pay data in the posting."]
    else:
        cv = 1.0 if mid >= 100_000 else 0.85 if mid >= 85_000 else 0.7 if mid >= prof.comp_target else (
            0.5 if mid >= 55_000 else 0.3)
        reasons = [f"About ${mid:,.0f} per year at the midpoint (base or base plus target, per posting)."]
    comps["compensation"] = {"raw": cv, "reasons": reasons}

    # Evidence strength --------------------------------------------------
    ev, reasons = 0.0, []
    if job.source_is_original:
        ev += 0.4
        reasons.append("Original company or ATS posting.")
    else:
        reasons.append("Not yet confirmed on the company's own posting.")
    if job.last_verified_at:
        age = (today - job.last_verified_at.date()).days
        if age <= 7:
            ev += 0.4
            reasons.append(f"Verified {age} day(s) ago.")
        elif age <= 30:
            ev += 0.2
            reasons.append(f"Verified {age} days ago.")
        else:
            reasons.append(f"Stale: last verified {age} days ago.")
    else:
        reasons.append("Never verified as active.")
    if job.company.evidence_count >= 3:
        ev += 0.2
        reasons.append(f"{job.company.evidence_count} sourced facts about the company.")
    comps["evidence"] = {"raw": min(ev, 1.0), "reasons": reasons}

    breakdown = {}
    total = 0.0
    for k, c in comps.items():
        pts = round(c["raw"] * w[k], 1)
        breakdown[k] = {"label": COMPONENT_LABELS[k], "score": pts, "max": round(w[k], 1), "reasons": c["reasons"]}
        total += pts

    category = category_for(job, pclass, g, el, edge, job.company.category == "cybersecurity")
    flags = []
    if edge or (category == "program" and g <= 0.3):
        flags.append("outside_area" if g <= 0.3 else "edge_location")
    if job.grad_status in ("too_early", "too_late"):
        flags.append("timing_mismatch")
    if not job.source_is_original:
        flags.append("needs_original_posting")
    return {"total": round(total, 1), "breakdown": breakdown, "path_class": pclass, "category": category,
            "flags": flags}


_JUNIOR_SE = re.compile(r"\b(associate|junior|jr\.?|early[- ]career|new grad|graduate|entry[- ]level|university|academy|apprentice)\b", re.I)


def category_for(job: JobView, pclass: str, geo: float, elig: float, edge: bool, is_cyber: bool = False) -> str:
    """Top priority: entry sales roles at cybersecurity companies. ASE roles and SE programs are a smaller
    high-priority section shown regardless of location (flagged when outside your area)."""
    if job.family == "direct_se" and (job.is_program or _JUNIOR_SE.search(job.title)) or (
            job.is_program and job.program_target == "se"):
        return "program"
    if elig == 0.0 or geo <= 0.3:
        return "long_shot"
    if job.family == "pipeline":
        if (job.yoe_min or 0) >= 3 or is_senior_title(job.title):
            return "long_shot"
        return "entry_sales" if is_cyber else "other_sales"
    if job.family == "direct_se":
        return "goal_se"
    if job.family == "technical_entry":
        return "technical_entry"
    return "long_shot"


CATEGORY_LABELS = {
    "entry_sales": "Entry sales at cybersecurity companies",
    "program": "ASE roles and SE programs",
    "other_sales": "Entry sales at other tech companies",
    "goal_se": "SE roles to grow into",
    "technical_entry": "Technical entry roles",
    "long_shot": "Long shot or outside your area",
    "direct_se": "Direct SE roles", "pipeline": "Sales roles toward SE",
}
