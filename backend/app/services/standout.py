"""'How do I stand out?' recommendations. Company-specific ideas are stored on the company (seeded from
research and editable); category templates and the job's own gaps fill in the rest."""
from __future__ import annotations

from ..models import Company, Job
from .fit import COMPENSATE

CATEGORY_IDEAS = {
    "cybersecurity": [
        ("Build a two-page threat-to-product brief: one realistic attack, how {company}'s product detects or blocks it, "
         "and what a buyer would ask.", "Shows you can translate security into business risk, which is the core SE skill.", "3-4 hours"),
        ("Set up a small home lab (a VM firewall or a free-tier cloud VPC) and write a one-page lab note.",
         "Gives you a hands-on story for technical screens.", "1 weekend")],
    "cloud_networking": [
        ("Diagram a customer deployment of {company}'s product (network path, ports, identity) and walk through it out loud.",
         "Whiteboarding a deployment is a common SE interview exercise.", "2-3 hours")],
    "software": [
        ("Pick one workflow {company}'s product automates and record a 3-minute walkthrough for a specific buyer.",
         "A demo artifact separates you from applicants who only send a resume.", "3 hours")],
    "ai": [
        ("Write a one-page note on how a buyer should evaluate {company}'s AI output quality.",
         "Turns hands-on AI evaluation or prompt work into something a customer would actually use.", "2 hours")],
    "it_solutions": [
        ("Learn the top three vendors {company} resells for security and networking, and how they're positioned.",
         "Solution providers hire people who can talk across vendors.", "2-3 hours")],
    "public_safety": [
        ("Research how a city or campus police department buys technology (budget cycles, grants, procurement).",
         "Public-sector sales has its own rules; knowing them is rare for new grads.",
         "2 hours")],
}
GENERIC = [
    ("Message one current SE and one recruiter at {company} using the drafts on the Contacts page.",
     "Referrals and recruiter awareness raise response rates more than another application.", "30 minutes"),
    ("Prepare a five-minute walkthrough: customer problem, how {company} solves it, two likely objections and your answers.",
     "Mirrors the presentation round many SE interviews include.", "2-3 hours"),
]


INTERN_IDEAS = {
    "cyber": [("Finish TryHackMe's free Pre Security or SOC Level 1 rooms and list what you practiced (log analysis, "
               "phishing triage) on your resume.", "Gives you hands-on answers for the 'what would you do with this alert' "
               "questions security interviews ask.", "1-2 weeks"),
              ("Set up a small home lab: a Linux VM sending logs to a free SIEM (Splunk Free or Wazuh) and write up one "
               "alert you investigated.", "A concrete lab story stands out among student applicants.", "1 weekend")],
    "data": [("Build a one-page Tableau Public or Power BI dashboard from an Arizona open dataset (data.az.gov or "
              "Phoenix open data) and link it on your resume.", "Data internships screen for a portfolio piece more than "
              "coursework.", "1 weekend"),
             ("Practice SQL joins and GROUP BY on a free dataset (SQLBolt or Mode's SQL tutorial) until you can write "
              "a top-five query from memory.", "Most data intern interviews include a live SQL question.", "3-4 hours")],
    "network": [("Build a small Cisco Packet Tracer lab (two VLANs, a router, DHCP) and save screenshots with a "
                 "short write-up.", "Packet Tracer is free through Cisco Networking Academy, and a finished lab is easy proof for networking roles.",
                 "1 weekend"),
                ("Drill subnetting until a /26 takes you under a minute (subnettingpractice.com).",
                 "Subnetting and troubleshooting questions are standard in networking intern interviews.", "2-3 hours")],
}
INTERN_GENERIC = [
    ("Message the recruiter with the short draft on the Apply page, and ask whether {hours} works for the role.",
     "Confirms the hours and puts your name in front of them before they screen.", "15 minutes"),
    ("Ask your internship coordinator now whether a {company} internship would count for credit.",
     "Credit approval can take time; starting early keeps a January start possible.", "15 minutes"),
]


def intern_recommendations(company: Company, job: Job) -> list[dict]:
    track = job.intern.track if job.intern else None
    hours = "10 to 30 hours a week"
    out = [{"action": a.format(company=company.name, hours=hours), "why": w, "effort": e, "source": "template"}
           for a, w, e in INTERN_IDEAS.get(track, []) + INTERN_GENERIC]
    for c in (job.analysis or {}).get("compensate", [])[:2]:
        out.append({"action": c["action"], "why": f"Closes the {c['for']} gap in this posting.", "effort": "varies",
                    "source": "gap"})
    return out


def recommendations(company: Company, job: Job | None = None) -> list[dict]:
    if job is not None and job.family == "internship":
        return intern_recommendations(company, job)
    out = [dict(x, source="research") for x in (company.data or {}).get("standout", [])]
    for action, why, effort in CATEGORY_IDEAS.get(company.category or "", []) + GENERIC:
        out.append({"action": action.format(company=company.name), "why": why, "effort": effort, "source": "template"})
    if job:
        for c in (job.analysis or {}).get("compensate", [])[:3]:
            out.append({"action": c["action"], "why": f"Closes the {c['for']} gap in this posting.", "effort": "varies",
                        "source": "gap"})
    seen, unique = set(), []
    for r in out:
        if r["action"] not in seen:
            seen.add(r["action"])
            unique.append(r)
    return unique
