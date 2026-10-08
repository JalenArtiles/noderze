"""ATS keyword engine for entry sales roles.

Applicant tracking systems rank resumes by how many of the posting's terms appear. This module:
1. extracts the terms a posting (and the company's other sales postings) screens for,
2. checks which terms your resume or confirmed profile actually support,
3. reports coverage before and after tailoring.
A term is only ever added to a resume when it is supported; unsupported terms are shown as missing, and you
can confirm one with "I have this", which records it in your profile as a claim you made.
"""
from __future__ import annotations

import re
from collections import Counter

# canonical term -> (group, weight, patterns)
TERMS: dict[str, tuple[str, float, list[str]]] = {
    "Cold calling": ("sales", 2, [r"cold[- ]call(?:s|ing)?", r"outbound calls?", r"phone (?:and email )?outreach",
                                  r"high[- ]volume (?:of )?(?:calls|calling|phone)", r"dial(?:s|ing)\b"]),
    "Prospecting": ("sales", 2, [r"prospect(?:ing|s)?\b", r"prospective (?:customers|clients|accounts)"]),
    "Lead generation": ("sales", 2, [r"lead gen(?:eration)?", r"generat\w* (?:new )?(?:leads|pipeline|business|opportunit)", r"pipeline generation"]),
    "Lead qualification": ("sales", 2, [r"qualif(?:y|ying|ication)", r"\bbant\b", r"meddp?icc?"]),
    "Discovery": ("sales", 2, [r"discovery", r"needs analysis", r"uncover (?:needs|pain)"]),
    "Outbound prospecting": ("sales", 1.5, [r"outbound"]),
    "Inbound leads": ("sales", 1, [r"inbound"]),
    "Email outreach": ("sales", 1.5, [r"email (?:outreach|campaigns?|sequences?|prospecting)", r"cadences?", r"sequences?"]),
    "Social selling": ("sales", 1, [r"social selling", r"linkedin (?:outreach|prospecting)"]),
    "Booking meetings": ("sales", 2, [r"(?:book|set|schedul)\w* (?:\w+ )?(?:meetings|appointments|demos)", r"appointment setting", r"sales[- ]ready meetings"]),
    "Pipeline development": ("sales", 1.5, [r"pipeline"]),
    "Quota attainment": ("sales", 1.5, [r"quota", r"\bkpis?\b", r"activity (?:metrics|goals|targets)"]),
    "B2B sales": ("sales", 1.5, [r"\bb2b\b", r"business[- ]to[- ]business"]),
    "Partnering with account executives": ("sales", 1, [r"account executives?", r"\baes?\b", r"account managers?"]),
    "Objection handling": ("sales", 1.5, [r"objection"]),
    "Negotiation": ("sales", 1, [r"negotiat"]),
    "Product demos": ("sales", 1, [r"\bdemos?\b", r"demonstrat"]),
    "Presentation skills": ("sales", 1, [r"present(?:ation|ing)s?\b"]),
    "Value selling": ("sales", 1, [r"business value", r"value proposition", r"\broi\b"]),
    "CRM": ("tools", 2, [r"\bcrm\b"]),
    "Salesforce": ("tools", 2, [r"salesforce", r"\bsfdc\b"]),
    "HubSpot": ("tools", 1.5, [r"hubspot"]),
    "Outreach": ("tools", 1.5, [r"outreach\.io", r"\boutreach\b(?= ?(?:and|or|,|/)? ?(?:salesloft|gong|zoominfo|salesforce))"]),
    "Salesloft": ("tools", 1.5, [r"salesloft"]),
    "Gong": ("tools", 1, [r"\bgong\b"]),
    "ZoomInfo": ("tools", 1.5, [r"zoominfo"]),
    "LinkedIn Sales Navigator": ("tools", 1.5, [r"sales navigator"]),
    "Apollo": ("tools", 1, [r"apollo\.io", r"\bapollo\b"]),
    "Microsoft Office": ("tools", 0.5, [r"microsoft office", r"\bexcel\b", r"office 365"]),
    "Cybersecurity": ("domain", 2, [r"cyber ?security", r"information security", r"\bsecurity\b"]),
    "Data security": ("domain", 1.5, [r"data security", r"data protection"]),
    "Network security": ("domain", 1.5, [r"network security"]),
    "Cloud security": ("domain", 1.5, [r"cloud security"]),
    "Identity and access": ("domain", 1.5, [r"identity", r"\biam\b", r"access management"]),
    "Endpoint security": ("domain", 1.5, [r"endpoint"]),
    "Zero trust": ("domain", 1.5, [r"zero trust"]),
    "Threat detection": ("domain", 1, [r"threats?\b", r"ransomware", r"phishing", r"malware"]),
    "Compliance": ("domain", 1, [r"compliance", r"\bsoc ?2\b", r"hipaa", r"gdpr"]),
    "SaaS": ("domain", 1.5, [r"\bsaas\b", r"software[- ]as[- ]a[- ]service"]),
    "Cloud": ("domain", 1, [r"\bcloud\b"]),
    "Communication skills": ("soft", 1, [r"communicat"]),
    "Coachable": ("soft", 1, [r"coachab", r"receptive to (?:feedback|coaching)"]),
    "Resilience": ("soft", 1, [r"resilien", r"rejection", r"\bgrit\b", r"persisten"]),
    "Self-motivated": ("soft", 1, [r"self[- ]?(?:motivated|starter|driven)", r"\bdriven\b"]),
    "Teamwork": ("soft", 0.5, [r"team player", r"collaborat"]),
    "Time management": ("soft", 0.5, [r"time management", r"organiz(?:ed|ational)", r"prioritiz"]),
    "Competitive": ("soft", 0.5, [r"competitive"]),
    "Bachelor's degree": ("education", 1, [r"bachelor", r"\bba\b|\bbs\b|b\.s\.|b\.a\."]),
}
# Terms a resume can support with different wording.
SUPPORT = {
    "CRM": [r"\bcrm\b", r"hubspot", r"salesforce"],
    "Lead generation": [r"lead generation", r"new business"],
    "Outbound prospecting": [r"cold call", r"prospecting", r"outbound"],
    "Partnering with account executives": [r"account executives?"],
    "Value selling": [r"business value"],
    "Communication skills": [r"communicat", r"stakeholder", r"point of contact", r"instruct"],
    "Teamwork": [r"partnered", r"collaborat", r"team"],
    "Bachelor's degree": [r"b\.s\.|bachelor"],
    "Cybersecurity": [r"cyber ?security"],
    "Network security": [r"network security"],
    "B2B sales": [r"\bb2b\b", r"new business", r"account executive intern"],
    "Customer relationships": [r"client relationship"],
    "Presentation skills": [r"present", r"instructed"],
}
# Typical asks for entry sales roles, used only when a posting's text is too short to read.
TYPICAL_ENTRY_SALES = ["Prospecting", "Cold calling", "Lead qualification", "Booking meetings", "CRM", "Salesforce",
                       "Email outreach", "Quota attainment", "Communication skills", "Coachable", "Resilience", "B2B sales"]


def _rx(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


def extract(text: str) -> dict[str, int]:
    """canonical term -> number of mentions in the text"""
    out = {}
    for term, (_, _, pats) in TERMS.items():
        n = len(_rx(pats).findall(text or ""))
        if n:
            out[term] = n
    return out


def screened_terms(posting_text: str, company_texts: list[str] | None = None) -> list[dict]:
    """Rank the terms this posting (and the company's other sales postings) screen for."""
    mine = extract(posting_text)
    company = Counter()
    for t in company_texts or []:
        company.update(set(extract(t)))
    terms = set(mine) | {t for t, c in company.items() if c >= 2}
    typical = False
    if len(posting_text or "") < 400 and len(terms) < 6:
        terms |= set(TYPICAL_ENTRY_SALES)
        typical = True
    ranked = []
    for t in terms:
        group, weight, _ = TERMS[t]
        ranked.append({"term": t, "group": group, "weight": weight, "mentions": mine.get(t, 0),
                       "company_postings": company.get(t, 0), "typical": typical and t not in mine})
    ranked.sort(key=lambda r: (-(r["mentions"] > 0), -r["weight"], -r["mentions"], -r["company_postings"], r["term"]))
    return ranked


def supported(term: str, evidence_text: str, claims: list[str]) -> bool:
    if any(term.lower() == c.lower() for c in claims or []):
        return True
    pats = SUPPORT.get(term) or TERMS[term][2]
    return bool(_rx(pats).search(evidence_text or ""))


def present(term: str, text: str) -> bool:
    """What an ATS sees: the posting's own wording, literally."""
    return bool(_rx(TERMS[term][2]).search(text or ""))


CORE_ENTRY_SALES = ["Cold calling", "Prospecting", "Lead generation", "Discovery", "Booking meetings", "Email outreach",
                    "Lead qualification", "CRM"]


def coverage(terms: list[dict], text: str) -> int:
    total = sum(t["weight"] for t in terms) or 1
    return round(100 * sum(t["weight"] for t in terms if present(t["term"], text)) / total)
