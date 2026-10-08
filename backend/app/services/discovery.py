"""Job discovery.

Order of preference:
1. Company ATS APIs for watched companies (original postings, verified active on each scan).
2. Web search leads, resolved to the original ATS posting whenever the URL allows it.
Search broadly, filter aggressively: only target role families are stored.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Company, Job, Program
from ..util import fingerprint, norm_title, now, slugify
from .ats import RawPosting, detect_ats, fetch_postings, fetch_single, parse_ats_url, smartrecruiters_detail, workday_detail
from .classify import classify_role
from .fetch import FetchBlocked, PoliteFetcher
from .jobs_engine import enrich_and_score
from .profile import get_profile
from .search import search

BASE_VOCAB = [
    "Sales Engineer", "Associate Sales Engineer", "Junior Sales Engineer", "Entry Level Sales Engineer",
    "Solutions Engineer", "Associate Solutions Engineer", "Junior Solutions Engineer", "Solutions Consultant",
    "Associate Solutions Consultant", "Pre-Sales Engineer", "Technical Sales Engineer", "Technical Solutions Consultant",
    "Sales Engineering", "Technical Sales", "Customer Engineer", "Technical Account Associate",
    "Solutions Architect Entry Level", "Associate Solutions Architect", "Sales Academy", "Sales Engineering Academy",
    "Solutions Engineering Academy", "Technical Sales Academy", "Graduate Sales Engineer", "New Grad Sales Engineer",
    "Early Career Solutions Engineer", "University Solutions Engineer", "Rotational Sales Engineering Program",
    "Associate Systems Engineer", "Solution Advisor Associate", "Sales Development Representative",
]
WATCHED = ("priority", "strong", "monitor", "edge")


def vocabulary(db: Session) -> list[str]:
    extra = (get_profile(db).data or {}).get("vocab_extra", [])
    return list(dict.fromkeys(BASE_VOCAB + extra))


def is_relevant(title: str, description: str = "") -> bool:
    rc = classify_role(title, description)
    return rc.family in ("direct_se", "pipeline", "technical_entry") and not rc.is_senior


def _link_program(db: Session, company: Company, job: Job) -> None:
    if job.program_id or not company.programs:
        return
    text = f"{job.title} {job.description_text or ''}".lower()
    for p in company.programs:
        keys = [k for k in [p.name, p.role_title] if k]
        if any(k.lower() in text for k in keys):
            job.program_id = p.id
            return
    se_programs = [p for p in company.programs if p.target_family == "se"]
    rc = classify_role(job.title, job.description_text)
    if len(se_programs) == 1 and rc.family == "direct_se" and rc.is_program:
        job.program_id = se_programs[0].id


def upsert_posting(db: Session, company: Company, p: RawPosting, *, original: bool, log=None) -> tuple[Job, bool]:
    fp = fingerprint(company.name, p.title, p.ats_job_id if original else None, p.url)
    job = db.scalar(select(Job).where(Job.fingerprint == fp))
    is_new = job is None
    if is_new:
        # Same role reached through a different route (lead first, ATS later): merge instead of duplicating.
        job = db.scalar(select(Job).where(Job.company_id == company.id, Job.is_active.is_(True),
                                          Job.source_is_original.is_(False)).where(Job.title == p.title))
        if job is not None:
            job.fingerprint, is_new = fp, False
        else:
            job = Job(company_id=company.id, fingerprint=fp, title=p.title, discovered_at=now())
            db.add(job)
    job.company = company
    job.title = p.title
    job.url = p.url or job.url
    job.apply_url = p.apply_url or job.apply_url
    job.source = p.source or job.source
    job.ats_job_id = p.ats_job_id if original else job.ats_job_id
    job.location_text = p.location_text or job.location_text
    if p.description:
        job.description_text = p.description
    job.posted_at = p.posted_at or job.posted_at
    if p.comp_min is not None:
        job.comp_min, job.comp_max, job.comp_period = p.comp_min, p.comp_max, p.comp_period
    if p.workplace:
        job.remote_type = p.workplace
    if original:
        job.source_is_original = True
        job.needs_verification = False
        job.last_verified_at = now()
        job.is_active = True
    db.flush()
    _link_program(db, company, job)
    enrich_and_score(db, job)
    return job, is_new


SE_TITLE = re.compile(r"sales engineer|solutions? engineer|solutions? consultant|solutions? architect|pre-?sales|"
                      r"systems engineer|customer engineer|technical sales|field engineer", re.I)
CYBER_WORDS = re.compile(r"cyber|security|threat|endpoint|identity|zero trust|siem|\bsoc\b|vulnerab|firewall|ransomware|"
                         r"phishing|data protection|encryption|\bxdr\b|\bedr\b|sase|malware|fraud", re.I)


def infer_category(texts: list[str]) -> str | None:
    hits = Counter(m.group(0).lower() for t in texts for m in CYBER_WORDS.finditer(t or ""))
    return "cybersecurity" if len(hits) >= 3 and sum(hits.values()) >= 6 else None


def record_se_team(db: Session, company: Company, postings: list[RawPosting], board_url: str | None) -> int:
    se = [p.title for p in postings if SE_TITLE.search(p.title or "")]
    data = dict(company.data or {})
    data["se_team"] = {"open_se_roles": len(se), "sample": se[:6], "seen": now().date().isoformat(), "board": board_url}
    company.data = data
    if se:
        from ..models import Evidence
        from .evidence import add_evidence
        for old in db.scalars(select(Evidence).where(Evidence.subject_type == "company", Evidence.subject_id == company.id,
                                                     Evidence.field == "org.se_team_live")):
            db.delete(old)
        db.flush()
        add_evidence(db, "company", company.id, "org.se_team_live",
                     f"{len(se)} open sales or solutions engineering roles on the company's job board, for example: "
                     f"{'; '.join(se[:3])}.", url=board_url, source_title=f"{company.name} job board",
                     source_type="official", confidence="high", company=company)
    return len(se)


BOARD_URL = {"greenhouse": "https://job-boards.greenhouse.io/{t}", "lever": "https://jobs.lever.co/{t}",
             "ashby": "https://jobs.ashbyhq.com/{t}", "smartrecruiters": "https://jobs.smartrecruiters.com/{t}",
             "jobvite": "https://jobs.jobvite.com/{t}/jobs"}


def ensure_ats(db: Session, f: PoliteFetcher, company: Company, log) -> bool:
    if company.ats_type and (company.ats_token or company.ats_host):
        return True
    failed = (company.data or {}).get("ats_detect_failed")
    if failed and (now().date() - date.fromisoformat(failed)).days < 7:
        return False  # retried weekly, not on every scan
    found = detect_ats(f, company.name, company.slug)
    if found:
        company.ats_type, company.ats_token = found
        company.ats_verified = True
        log(f"{company.name}: detected {found[0]} board '{found[1]}'")
        return True
    data = dict(company.data or {})
    data["ats_detect_failed"] = now().date().isoformat()
    company.data = data
    db.commit()
    log(f"{company.name}: no public Greenhouse, Lever or Ashby board found; set it on the company page (Job board tab)")
    return False


def discover_company(db: Session, f: PoliteFetcher, company: Company, log) -> dict:
    stats = {"company": company.name, "company_id": company.id, "fetched": 0, "relevant": 0, "new": 0, "updated": 0,
             "closed": 0, "first_scan": False}
    if not ensure_ats(db, f, company, log):
        return stats
    try:
        postings = fetch_postings(f, company.ats_type, company.ats_token, company.ats_host, company.ats_site, log)
    except FetchBlocked as e:
        log(f"{company.name}: {e}")
        return stats
    except Exception as e:  # bad token, network
        log(f"{company.name}: could not read {company.ats_type} board ({e.__class__.__name__}: {e})")
        return stats
    stats["first_scan"] = first = not db.scalar(
        select(Job.id).where(Job.company_id == company.id, Job.source == company.ats_type).limit(1))
    company.ats_verified = True
    stats["fetched"] = len(postings)
    board = (f"https://{company.ats_host}/{company.ats_site}" if company.ats_type == "workday"
             else BOARD_URL.get(company.ats_type, "").format(t=company.ats_token) or None)
    stats["se_roles"] = record_se_team(db, company, postings, board)
    if not company.category:
        company.category = infer_category([p.title + " " + (p.description or "")[:3000] for p in postings[:40]])
    seen = set()
    for p in postings:
        if not is_relevant(p.title, p.description):
            continue
        if company.ats_type == "workday" and not p.description:
            try:
                p = workday_detail(f, company.ats_host, company.ats_site, p.extra.get("workday_path", p.ats_job_id))
            except Exception as e:
                log(f"{company.name}: detail fetch failed for {p.title}: {e}")
        if company.ats_type == "smartrecruiters" and not p.description:
            try:
                p.description = smartrecruiters_detail(f, company.ats_token, p.ats_job_id)
            except Exception:
                pass
        if not is_relevant(p.title, p.description):
            continue
        stats["relevant"] += 1
        job, is_new = upsert_posting(db, company, p, original=True)
        seen.add(job.id)
        if is_new:
            stats["new"] += 1
            if not first and job.category != "long_shot":
                db.add(Alert(job_id=job.id, message=f"New at {company.name}: {job.title} ({job.score_total:.0f}/100)"))
        else:
            stats["updated"] += 1
        db.commit()  # keep write transactions short so the interface never waits on a scan
    for job in db.scalars(select(Job).where(Job.company_id == company.id, Job.source == company.ats_type,
                                            Job.is_active.is_(True))):
        if job.id not in seen:
            job.is_active = False
            job.flags = list(set((job.flags or []) + ["closed_or_removed"]))
            stats["closed"] += 1
    db.commit()
    log(f"{company.name}: {stats['relevant']} relevant of {stats['fetched']} postings "
        f"({stats['new']} new, {stats['closed']} closed, {stats['se_roles']} SE roles seen)")
    return stats


def discover(db: Session, log, company_ids: list[int] | None = None) -> list[dict]:
    f = PoliteFetcher()
    try:
        q = select(Company)
        q = q.where(Company.id.in_(company_ids)) if company_ids else q.where(Company.watch_status.in_(WATCHED))
        results = [discover_company(db, f, c, log) for c in db.scalars(q).all()]
    finally:
        f.close()
    learn_vocabulary(db)
    return results


# ----------------------------------------------------------------------------- search leads

def default_queries(db: Session, programs_only: bool = False) -> list[str]:
    prof = get_profile(db).data or {}
    year = str(prof.get("expected_graduation", "2027-05"))[:4]
    if programs_only:
        return [f'"sales engineering academy" {year}', f'"solutions engineer" academy new grad {year}',
                f'"associate solutions engineer" program {year}', f'"associate sales engineer" graduate program',
                f'"solution consultant academy"', f'"presales academy" early career',
                f'"associate systems engineer" academy cybersecurity']
    return [f'"associate sales engineer" Arizona', f'"associate solutions engineer" California {year}',
            f'"solutions engineer" new grad {year} remote', f'"sales engineer" "early career" cybersecurity',
            f'"solutions consultant" associate new grad {year}', f'"pre-sales" "new grad" {year}']


def search_leads(db: Session, log, queries: list[str] | None = None) -> dict:
    stats = {"queries": 0, "results": 0, "leads": 0, "resolved": 0}
    f = PoliteFetcher()
    try:
        for q in queries or default_queries(db):
            stats["queries"] += 1
            for r in search(q, n=8):
                stats["results"] += 1
                if not is_relevant(r.title.split(" - ")[0].split(" | ")[0], r.snippet):
                    continue
                parsed = parse_ats_url(r.url)
                company = _company_for_result(db, r.title, r.url, parsed)
                if company is None:
                    continue
                if parsed and parsed[0] in ("greenhouse", "lever", "ashby") and parsed[2]:
                    try:
                        p = fetch_single(f, parsed[0], parsed[1], parsed[2])
                        if p:
                            upsert_posting(db, company, p, original=True)
                            stats["resolved"] += 1
                            continue
                    except Exception as e:
                        log(f"could not resolve {r.url}: {e}")
                title = re.split(r"\s[-|@]\s", r.title)[0].strip()
                lead = RawPosting(title=title, url=r.url, ats_job_id="", description=r.snippet, source="search")
                job, is_new = upsert_posting(db, company, lead, original=False)
                job.needs_verification = True
                stats["leads"] += int(is_new)
            db.commit()
    finally:
        f.close()
    log(f"Search: {stats['leads']} new leads, {stats['resolved']} resolved to original postings "
        f"from {stats['results']} results")
    return stats


def _company_for_result(db: Session, title: str, url: str, parsed) -> Company | None:
    if parsed and parsed[0] in ("greenhouse", "lever", "ashby", "smartrecruiters"):
        token = parsed[1]
        c = db.scalar(select(Company).where(Company.ats_token == token))
        if c:
            return c
        name = token.replace("-", " ").title()
        c = db.scalar(select(Company).where(Company.slug == slugify(name)))
        if c:
            return c
        c = Company(name=name, slug=slugify(name), ats_type=parsed[0], ats_token=token,
                    watch_status=None, watch_note="Discovered through search; review before watching.")
        db.add(c)
        db.flush()
        return c
    for c in db.scalars(select(Company)):
        if re.search(r"(?<![a-z])" + re.escape(c.name.lower()) + r"(?![a-z])", title.lower()):
            return c
    return None


# ----------------------------------------------------------------------------- vocabulary learning

def learn_vocabulary(db: Session) -> list[str]:
    """Suggest new title phrases seen on high-fit SE jobs. Suggestions need user approval."""
    known = {norm_title(v) for v in vocabulary(db)}
    counter: Counter[str] = Counter()
    for job in db.scalars(select(Job).where(Job.family.in_(["direct_se", "technical_entry"]),
                                            Job.score_total >= 55)):
        core = norm_title(re.split(r"[,(|\-\u2013]", job.title)[0])
        if core and core not in known and 2 <= len(core.split()) <= 5:
            counter[core] += 1
    prof = get_profile(db)
    data = dict(prof.data or {})
    data["vocab_suggestions"] = [t for t, _ in counter.most_common(20)]
    prof.data = data
    db.commit()
    return data["vocab_suggestions"]


def programs_for(db: Session) -> list[Program]:
    return list(db.scalars(select(Program)))
