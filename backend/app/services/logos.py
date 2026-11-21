"""The website a company's logo is drawn from.

Many internship employers arrive without a website (a Workday or Greenhouse link, a Muse copy, an email). Their logo
domain is worked out from what Noderze already has, strongest sign first:

1. the company's own email domain, from a reply it sent you (fox_workday_notification@fox.com -> fox.com)
2. a domain named in its posting that matches its name ("Visit www.azmag.gov" for MAG, "risepoint.com")
3. the job board's tenant when it is the company's name (uhaul.wd1.myworkdayjobs.com for U-Haul -> uhaul.com)
4. a one-word name (Labcorp -> labcorp.com), or a university's initials (Arizona State University -> asu.edu)

The result is kept in company.data["logo_domain"], separate from the website used for research, so a guess never
counts as an official source.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, EmailReply, Job

NOT_COMPANY = ("linkedin", "glassdoor", "indeed", "workday", "myworkdayjobs", "greenhouse", "lever", "ashbyhq", "google",
               "facebook", "twitter", "youtube", "instagram", "uscis", "eeoc", "dol", "everify", "e-verify", "themuse",
               "simplify", "builtin", "handshake", "joinhandshake", "smartrecruiters", "icims", "successfactors",
               "taleo", "jobvite", "adp", "paylocity", "ultipro", "ukg", "bamboohr", "workable", "gmail", "outlook",
               "yahoo", "hotmail", "icloud", "w3", "schema", "transparency-in-coverage", "uhc", "github", "x",
               "apple", "microsoft", "adobe", "wikipedia", "glassdoor", "ziprecruiter", "monster", "careerbuilder")
DOMAIN = re.compile(r"\b(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+(?:com|org|net|gov|edu|io|ai|co|us))\b", re.I)
CO_WORDS = {"inc", "llc", "corp", "corporation", "company", "co", "group", "the", "holdings", "usa", "us", "na", "ltd",
            "plc", "international", "of", "and", "&"}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _words(name: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9& ]", " ", (name or "").lower()).split() if w not in CO_WORDS]


def _base(domain: str) -> str:
    parts = domain.lower().split(".")
    return parts[-3] if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "ac") else parts[-2] if len(parts) >= 2 else domain


def _root(domain: str) -> str:
    parts = domain.lower().removeprefix("www.").split(".")
    keep = 3 if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "ac") else 2
    return ".".join(parts[-keep:])


def matches(name: str, domain: str) -> bool:
    """'risepoint.com' for Risepoint, 'azmag.gov' for Maricopa Association of Governments (MAG), 'fox.com' for FOX."""
    b = _norm(_base(domain))
    if not b or b in NOT_COMPANY or len(b) < 2:
        return False
    full = _norm(" ".join(_words(name)))
    words = _words(name)
    initials = "".join(w[0] for w in words if w not in ("of", "and"))
    if b == full or (len(b) >= 4 and (b in full or full in b)):
        return True
    if words and len(words[0]) >= 4 and b.startswith(_norm(words[0])):
        return True
    if len(initials) >= 2 and (b == initials or b.endswith(initials) or b.startswith(initials)):
        return True  # azmag -> MAG, asu -> ASU
    return False


def _from_replies(db: Session, c: Company) -> str | None:
    from .replies import ATS_SENDERS, FREE_MAIL, domain_of
    for addr in db.scalars(select(EmailReply.from_email).where(EmailReply.company_id == c.id)):
        d = domain_of(addr)
        if d and not any(d.endswith(s) for s in ATS_SENDERS + FREE_MAIL) and matches(c.name, d):
            return d
    return None


def _from_postings(jobs: list[Job], name: str) -> str | None:
    seen: dict[str, int] = {}
    for j in jobs:
        for m in DOMAIN.finditer((j.description_text or "")[:30000]):
            d = _root(m.group(1))
            if matches(name, d):
                seen[d] = seen.get(d, 0) + 1
    return max(seen, key=seen.get) if seen else None


def _from_boards(jobs: list[Job], c: Company) -> str | None:
    tenants = []
    if c.ats_token:
        tenants.append(c.ats_token)
    for j in jobs:
        host = urlparse(j.url or "").netloc.lower()
        if "myworkdayjobs.com" in host:
            tenants.append(host.split(".")[0])
        parts = [p for p in urlparse(j.url or "").path.split("/") if p]
        if ("greenhouse.io" in host or "lever.co" in host or "ashbyhq.com" in host) and parts:
            tenants.append(parts[0] if parts[0] != "embed" else "")
    for t in tenants:
        t = re.sub(r"(careers?|jobs|external|hr|talent)$", "", _norm(t))
        if t and _norm(" ".join(_words(c.name))) == t:
            return f"{t}.com"
    return None


INDUSTRY = {"semiconductors", "technologies", "technology", "systems", "solutions", "security", "software",
            "electronics", "health", "healthcare", "financial", "bank", "services", "sciences", "labs", "networks",
            "energy", "partners", "consulting", "research", "analytics", "media", "foods", "motors", "insurance"}


def _from_name(name: str) -> str | None:
    words = _words(name)
    if "university" in words and len(words) >= 3:
        return "".join(w[0] for w in words if w not in ("of", "and")) + ".edu"
    if len(words) == 1 and len(words[0]) >= 5 and words[0].isalnum():
        return f"{words[0]}.com"
    if len(words) == 2 and words[1] not in INDUSTRY and all(w.isalnum() for w in words):
        return f"{words[0]}{words[1]}.com"  # Wells Fargo -> wellsfargo.com, TD Synnex -> tdsynnex.com
    return None


def find(db: Session, c: Company) -> str | None:
    jobs = list(db.scalars(select(Job).where(Job.company_id == c.id).limit(20)))
    return _from_replies(db, c) or _from_postings(jobs, c.name) or _from_boards(jobs, c) or _from_name(c.name)


def site(c: Company | None) -> str | None:
    """What the logo is drawn from: the company's website, else the domain worked out for it."""
    if c is None:
        return None
    return c.website or ((c.data or {}).get("logo_domain") if isinstance(c.data, dict) else None)


def fill(db: Session, only_missing: bool = True) -> int:
    """Work out logo domains for companies without a website. Returns how many were found."""
    n = 0
    for c in db.scalars(select(Company).where(Company.website.is_(None))):
        data = dict(c.data or {})
        if only_missing and data.get("logo_domain"):
            continue
        d = find(db, c)
        if d:
            data["logo_domain"] = d
            c.data = data
            n += 1
    db.flush()
    return n
