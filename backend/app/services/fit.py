"""'Why this role?' analysis: what fits, what is missing, and how to compensate.

Fits are only claimed when a resume or profile fact supports them, and that fact is quoted.
"""
from __future__ import annotations

import re

from .classify import parse_yoe
from .taxonomy import AREA_LABELS, areas_in, certs_in, certs_required, _area_regex

COMPENSATE = {
    "networking": "Refresh TCP/IP, DNS, DHCP, subnetting and VLANs, then explain how this company's product talks to the "
                  "network (ports, outbound connections, failure modes). A CCNA or Network+ study plan makes it concrete.",
    "network_security": "Build a small home lab (pfSense or a cloud VPC) with a firewall policy and write up what you "
                        "blocked and why. It gives you a story for discovery calls.",
    "security": "Map the product to the problem it solves (threat, buyer, alternative) in a one-page brief; "
                "Security+ is the common baseline credential if the role lists it.",
    "cloud": "Take AWS Cloud Practitioner Essentials (free on AWS Skill Builder), then deploy something small "
             "(a static site plus a Lambda) so you can talk about it from experience.",
    "linux": "Spend a weekend on Linux basics (permissions, services, logs, networking commands) in a VM; "
             "note what you troubleshot.",
    "programming": "Write a short Python script that calls the company's public API or a sample API and put it on GitHub "
                   "with a README aimed at a customer.",
    "apis": "Build a tiny integration (REST call, auth header, JSON parsing, error handling) and demo it in two minutes.",
    "databases": "Practice SQL joins and aggregations on a public dataset; one query you can explain is enough.",
    "ai": "Use your AI evaluation work: prepare a two-minute explanation of how you judged model quality.",
    "operating_systems": "Review Windows and macOS management basics (users, updates, endpoint agents).",
    "iot_hardware": "Learn the basics of the company's devices (power, PoE, connectivity) from their public docs.",
    "packet_analysis": "Capture and annotate a Wireshark trace of a TLS handshake or DNS lookup.",
    "demo": "Record a 2 to 5 minute product walkthrough of this company's product for a specific buyer, including one "
            "objection and how you'd answer it.",
    "presentation": "Practice a 5-minute technical explanation to a non-technical audience and ask a classmate for feedback.",
    "discovery": "Write 10 discovery questions for this company's buyer and practice them out loud.",
    "objection_handling": "List the three most likely objections for this product and prepare answers.",
    "value_selling": "Turn one product feature into a business outcome statement with a rough ROI argument.",
    "rfp": "Read a public RFP for this product category and draft answers to three technical questions.",
    "quota": "Be ready to describe your activity metrics from your AE internship honestly (calls, meetings, outcomes).",
    "crm": "Get hands-on with a CRM (HubSpot's free tools or Salesforce Trailhead) and log a mock pipeline.",
    "prospecting": "Get a few weeks of real prospecting reps (club sponsorships or a part-time SDR role) and track results.",
    "customer_facing": "Find a customer-facing project, even unpaid, where you own the relationship end to end.",
    "ae_partnership": "Ask an AE or SE for a ride-along or shadow session to learn how the two roles split a deal.",
}


def _supporting_fact(area: str, kind: str, ledger: list[dict], profile_skills: str) -> str | None:
    rx = _area_regex(kind, area)
    for f in ledger:
        if f.get("section") in ("summary", "header"):
            continue  # a stated interest in the summary is not evidence of the skill
        if rx.search(f["text"]):
            return f["text"]
    if rx.search(profile_skills):
        return "Listed in your profile skills"
    return None


def why_this_role(title: str, description: str, ledger: list[dict], profile_skills: str,
                  profile_certs: list[str], yoe_years: float = 0.5) -> dict:
    text = f"{title}\n{description or ''}"
    fits, missing, compensate = [], [], []
    for kind in ("tech", "sales"):
        for area in areas_in(text, kind):
            fact = _supporting_fact(area, kind, ledger, profile_skills)
            if fact:
                fits.append({"requirement": AREA_LABELS[area], "evidence": fact[:220]})
            else:
                missing.append({"requirement": AREA_LABELS[area], "severity": "gap"})
                if area in COMPENSATE:
                    compensate.append({"for": AREA_LABELS[area], "action": COMPENSATE[area]})
    held = {c.lower() for c in profile_certs}
    for cert in certs_in(text):
        if cert.lower() not in held:
            required = cert in certs_required(text)
            missing.append({"requirement": cert, "severity": "required" if required else "preferred"})
    yoe, preferred = parse_yoe(description)
    if yoe and yoe > yoe_years:
        missing.append({"requirement": f"{yoe:g}+ years of experience", "severity": "preferred" if preferred else "required"})
    if re.search(r"\b(sales engineer|solutions? engineer|pre-?sales)\b", text, re.I):
        missing.append({"requirement": "Direct SE title", "severity": "context",
                        "note": "Expected for entry roles; address it with a demo and a clear 'why SE' story."})
    return {"fits": fits, "missing": missing, "compensate": compensate}
