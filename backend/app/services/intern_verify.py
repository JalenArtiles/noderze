"""Checks each spring internship against its live posting.

For every internship on the list, Noderze opens the employer's own posting (the Greenhouse, Lever, Ashby,
SmartRecruiters or Workday API, or the career page itself) and either:

- refreshes the description, location, pay, dates and posting date from it, so what you read is what the employer
  says today, or
- marks it closed when the employer took it down, the board says it no longer exists, or its deadline passed.

Copies from other sites (The Muse, the SimplifyJobs list, Handshake) follow the employer's posting when Noderze
knows it. When a posting can't be checked automatically (Handshake needs your login), it says so instead of
guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qs, quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Application, Job
from ..util import now
from .ats import (RawPosting, fetch_postings, html_to_text, parse_ats_url, parse_greenhouse, parse_jsonld_posting,
                  parse_lever, parse_smartrecruiters_detail, parse_workday_detail, parse_workday_url,
                  workday_endpoints, workday_search)
from .classify import _dates_in
from .fetch import FetchBlocked, PoliteFetcher

LOGIN_SITES = ("joinhandshake.com", "linkedin.com", "indeed.com", "glassdoor.com")
CLOSED_TEXT = re.compile(
    r"no longer (available|accepting|open|active|posted)|position (has been|is) (filled|closed)|"
    r"job (is|has been) (closed|removed|filled|expired)|this (job|posting|position|requisition) (has )?(expired|closed)|"
    r"page (you are looking for |you requested )?(doesn't|does not|no longer) exist|job not found|posting (is|has) closed|"
    r"not accepting applications|applications? (are|is) (now )?closed|job you are trying to apply for has been filled",
    re.I)


@dataclass
class Result:
    state: str  # open | closed | unchecked
    reason: str
    posting: RawPosting | None = None
    original: bool = False
    extra: dict = field(default_factory=dict)


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _status(e: Exception) -> int | None:
    return e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None


def stated_deadline(text: str | None) -> date | None:
    """'Handshake application deadline: October 30, 2026' in a posting's text."""
    for m in re.finditer(r"(?:deadline|apply by|applications? (?:close|due)|closing date|closes?)[^.\n]{0,60}",
                         text or "", re.I):
        ds = [d for d in _dates_in(m.group(0)) if d.year >= 2025]
        if ds:
            return min(ds)
    return None


# ----------------------------------------------------------------------------- one posting

def _greenhouse_token(job: Job, url: str) -> str | None:
    parsed = parse_ats_url(url)
    if parsed and parsed[0] == "greenhouse":
        return parsed[1]
    c = job.company
    if c and c.ats_type == "greenhouse" and c.ats_token:
        return c.ats_token
    host = urlparse(url).netloc.lower().removeprefix("www.").removeprefix("careers.").removeprefix("jobs.")
    return host.split(".")[0] if host else None  # wavelifesciences.com/jobs?gh_jid=... -> "wavelifesciences"


def check_greenhouse(f: PoliteFetcher, token: str, jid: str) -> Result:
    try:
        data = f.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}")
    except httpx.HTTPStatusError as e:
        if _status(e) in (404, 410):
            return Result("closed", "The employer's Greenhouse board no longer lists it")
        raise
    p = parse_greenhouse({"jobs": [data]})[0]
    return Result("open", "Open on the employer's Greenhouse board", p, True)


def check_workday(f: PoliteFetcher, host: str, site: str, path: str) -> Result:
    api, _ = workday_endpoints(host, site)
    try:
        data = f.get_json(f"{api}{path}")
    except httpx.HTTPStatusError as e:
        if _status(e) in (400, 404, 410):
            return Result("closed", "The employer's Workday site says this job doesn't exist anymore")
        raise
    info = (data or {}).get("jobPostingInfo") or {}
    if not info or not info.get("title"):
        return Result("closed", "The employer's Workday site says this job doesn't exist anymore")
    if info.get("canApply") is False:
        return Result("closed", "Workday shows it, but no longer takes applications")
    p = parse_workday_detail(data, host, site, path)
    return Result("open", "Open on the employer's Workday site", p, True)


def check_lever(f: PoliteFetcher, token: str, jid: str) -> Result:
    try:
        data = f.get_json(f"https://api.lever.co/v0/postings/{token}/{jid}?mode=json")
    except httpx.HTTPStatusError as e:
        if _status(e) in (404, 410):
            return Result("closed", "The employer's Lever board no longer lists it")
        raise
    p = (parse_lever([data]) or [None])[0]
    return Result("open", "Open on the employer's Lever board", p, True) if p else Result("closed", "Not on Lever anymore")


def check_ashby(f: PoliteFetcher, token: str, jid: str, title: str) -> Result:
    postings = fetch_postings(f, "ashby", token)
    if not postings:
        return Result("unchecked", "The employer's Ashby board returned nothing; try again later")
    for p in postings:
        if p.ats_job_id == jid or jid in (p.url or ""):
            return Result("open", "Open on the employer's Ashby board", p, True)
    return Result("closed", "The employer's Ashby board no longer lists it")


def check_smartrecruiters(f: PoliteFetcher, company: str, jid: str, job: Job) -> Result:
    try:
        data = f.get_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{jid}")
    except httpx.HTTPStatusError as e:
        if _status(e) in (404, 410):
            return Result("closed", "The employer's SmartRecruiters board no longer lists it")
        raise
    if data.get("active") is False:
        return Result("closed", "SmartRecruiters marks it inactive")
    p = RawPosting(title=data.get("name") or job.title, url=job.url, ats_job_id=jid,
                   location_text=job.location_text or "", description=parse_smartrecruiters_detail(data),
                   source="smartrecruiters")
    return Result("open", "Open on the employer's SmartRecruiters board", p, True)


def check_muse(f: PoliteFetcher, job: Job) -> Result:
    """The Muse copies postings from employers. Its API lists what it still shows; a job it dropped is gone."""
    name = job.company.name if job.company else ""
    found = None
    for page in range(3):
        data = f.get_json(f"https://www.themuse.com/api/public/jobs?company={quote(name)}&level=Internship&page={page}")
        for j in data.get("results", []):
            if norm(j.get("name")) == norm(job.title):
                found = j
                break
        if found or page + 1 >= int(data.get("page_count") or 1):
            break
    if not found:
        return Result("closed", "The Muse no longer lists it, so the employer took it down")
    from .sources import parse_muse
    p = parse_muse({"results": [found]})[0][1]
    return Result("open", "Still listed on The Muse (a copy of the employer's posting)", p, False)


def check_page(f: PoliteFetcher, job: Job, url: str) -> Result:
    """Any other career page: a 404 or 'no longer available' means closed; schema.org markup refreshes the details."""
    try:
        r = f.request("GET", url)
    except FetchBlocked as e:
        return Result("unchecked", f"Couldn't open the page ({e})")
    if r.status_code in (404, 410):
        return Result("closed", "The employer's page for it is gone")
    if r.status_code >= 400:
        return Result("unchecked", f"The page returned an error ({r.status_code}); try again later")
    page = r.text[:2_000_000]
    p = parse_jsonld_posting(page, url, source=job.source or "employer site")
    text = html_to_text(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page))
    if CLOSED_TEXT.search(text[:6000]) and not p:
        return Result("closed", "The employer's page says it's no longer available")
    moved = urlparse(str(r.url)).path.rstrip("/") != urlparse(url).path.rstrip("/")
    words = [w for w in re.findall(r"[a-z]{4,}", (job.title or "").lower())][:4]
    shows_title = all(w in text.lower() for w in words) if words else True
    if moved and not shows_title and not p:
        return Result("closed", "The link now goes to a general careers page, without this job")
    if p and len(p.description or "") >= 250:
        p.title = p.title or job.title
        return Result("open", "Open on the employer's site", p, True)
    if shows_title and len(text) >= 600:
        return Result("open", "Open on the employer's site", None, True)
    return Result("unchecked", "The page didn't show the job clearly; open it to check")


def _on_company_board(f: PoliteFetcher, job: Job) -> Result | None:
    """A copy whose employer board Noderze knows: look for the same title there."""
    c = job.company
    if not c or not c.ats_type:
        return None
    try:
        if c.ats_type == "workday" and c.ats_host and c.ats_site:
            for hit in workday_search(f, c.ats_host, c.ats_site, job.title):
                if norm(hit["title"]) == norm(job.title):
                    return check_workday(f, c.ats_host, c.ats_site, hit["path"])
            return None
        if c.ats_type in ("greenhouse", "lever", "ashby", "smartrecruiters") and c.ats_token:
            for p in fetch_postings(f, c.ats_type, c.ats_token):
                if norm(p.title) == norm(job.title):
                    return Result("open", "Open on the employer's own job board", p, True)
    except Exception:
        return None
    return None


def check(f: PoliteFetcher, job: Job, twins: list[Job] | None = None) -> Result:
    today = date.today()
    deadline = job.deadline or stated_deadline(job.description_text)
    if deadline and deadline < today:
        return Result("closed", f"The application deadline ({deadline:%B %-d, %Y}) passed", extra={"deadline": deadline})
    url = (job.url or job.apply_url or "").strip()
    host = urlparse(url).netloc.lower()
    # A copy of a posting Noderze already reads from the employer follows that posting.
    for t in twins or []:
        if t.source_is_original and t.id != job.id:
            if not t.is_active:
                return Result("closed", "The employer's own posting closed")
            if t.last_verified_at and (now() - t.last_verified_at).days < 2:
                return Result("open", "Open on the employer's site (same posting)", None, False)
    try:
        if not url:
            found = _on_company_board(f, job)
            return found or Result("unchecked", "No link to check; open the employer's career page")
        if any(host == h or host.endswith("." + h) for h in LOGIN_SITES):
            found = _on_company_board(f, job)
            return found or Result("unchecked", "Listed on a site you log into (Handshake or LinkedIn); check it there")
        wd = parse_workday_url(url)
        if wd:
            return check_workday(f, *wd)
        q = parse_qs(urlparse(url).query)
        parsed = parse_ats_url(url)
        if parsed and parsed[0] == "greenhouse" and parsed[2]:
            return check_greenhouse(f, parsed[1], parsed[2])
        if q.get("gh_jid"):
            token = _greenhouse_token(job, url)
            if token:
                return check_greenhouse(f, token, q["gh_jid"][0])
        if parsed and parsed[0] == "lever" and parsed[2]:
            return check_lever(f, parsed[1], parsed[2])
        if parsed and parsed[0] == "ashby" and parsed[2]:
            return check_ashby(f, parsed[1], parsed[2], job.title)
        if parsed and parsed[0] == "smartrecruiters" and parsed[2]:
            return check_smartrecruiters(f, parsed[1], parsed[2], job)
        if "themuse.com" in host:
            found = _on_company_board(f, job)
            return found or check_muse(f, job)
        return check_page(f, job, url)
    except FetchBlocked as e:
        return Result("unchecked", f"The site didn't allow an automatic check ({e})")
    except (httpx.HTTPError, ValueError) as e:
        return Result("unchecked", f"Couldn't reach the posting ({e.__class__.__name__}); it'll be tried again tomorrow")


# ----------------------------------------------------------------------------- applying a result

def apply(db: Session, job: Job, r: Result) -> str:
    """Store what the check found and re-run the internship rules. Returns the state."""
    from .intern_jobs import absorb, ensure_detail, evaluate_job
    d = ensure_detail(db, job)
    hints = dict(d.hints or {})
    hints["verify"] = {"state": r.state, "reason": r.reason, "at": now().isoformat(timespec="seconds"),
                       "original": r.original}
    d.hints = hints
    flags = [x for x in (job.flags or []) if x != "closed_or_removed"]
    if r.extra.get("deadline") and not job.deadline:
        job.deadline = r.extra["deadline"]
    if r.state == "closed":
        job.is_active = False
        job.flags = flags + ["closed_or_removed"]
    elif r.state == "open":
        job.is_active = True
        job.flags = flags
        p = r.posting
        if p is not None:
            if p.description and (len(p.description) >= 250 or not job.description_text):
                job.description_text = p.description
            if p.location_text and (r.original or not job.location_text):
                job.location_text = p.location_text
            if p.comp_min is not None:
                job.comp_min, job.comp_max, job.comp_period = p.comp_min, p.comp_max, p.comp_period
            elif r.original and p.description and len(p.description) >= 250:
                # The employer's text is the truth: pay is read from it again, not kept from an older copy.
                from .classify import parse_comp
                c = parse_comp(p.description)
                job.comp_min, job.comp_max, job.comp_period = c.min, c.max, c.period
            if p.posted_at:
                job.posted_at = p.posted_at
            if p.workplace:
                job.remote_type = p.workplace
            if (p.extra or {}).get("deadline") and not job.deadline:
                try:
                    job.deadline = date.fromisoformat(str(p.extra["deadline"])[:10])
                except ValueError:
                    pass
            if r.original and not job.source_is_original:
                # A list copy now read from the employer: it becomes the employer's posting.
                job.url = p.url or job.url
                job.source = p.source or job.source
                job.ats_job_id = p.ats_job_id or job.ats_job_id
            absorb(d, dict(p.extra or {}, workplace=p.workplace), None,
                   readable=bool(r.original or len(job.description_text or "") >= 250))
        if r.original:
            job.source_is_original = True
            job.needs_verification = False
            job.last_verified_at = now()
        if not job.deadline and job.source == "manual":
            job.deadline = stated_deadline(job.description_text)
    evaluate_job(db, job)
    return r.state


def verify_job(db: Session, job: Job, f: PoliteFetcher | None = None) -> Result:
    from .intern_jobs import posting_key
    own = f is None
    f = f or PoliteFetcher(min_interval=1.0)
    try:
        key = posting_key(job)
        twins = [j for j in db.scalars(select(Job).where(Job.family == "internship", Job.company_id == job.company_id))
                 if j.id != job.id and (posting_key(j) == key or norm(j.title) == norm(job.title))]
        r = check(f, job, twins)
        apply(db, job, r)
        return r
    finally:
        if own:
            f.close()


def run(db: Session, log, only_listed: bool = True) -> dict:
    """Check every internship on the list (and the ones saved but not applied to) against its live posting."""
    from ..models import PRE_APPLY
    from .intern_jobs import FAMILY, board, counts
    from .profile import get_profile
    log.plan(["Open each internship's live posting", "Refresh the details and close the ones that are gone"])
    log.step(0)
    shown, _ = board(db)
    stages = dict(db.execute(select(Application.job_id, Application.stage)).all())
    jobs = list(shown) if only_listed else list(db.scalars(select(Job).where(Job.family == FAMILY, Job.is_active.is_(True))))
    # Saved ones are on the list already; started or applied ones keep their details fresh too.
    for j in db.scalars(select(Job).where(Job.family == FAMILY, Job.is_active.is_(True))):
        if j not in jobs and j.id in stages and stages[j.id] in PRE_APPLY:
            jobs.append(j)
    # Employers' own postings first, so copies can follow them.
    jobs.sort(key=lambda j: (not j.source_is_original, j.id))
    tally = {"open": 0, "closed": 0, "unchecked": 0}
    closed: list[str] = []
    f = PoliteFetcher(min_interval=1.0)
    try:
        for i, job in enumerate(jobs):
            r = verify_job(db, job, f)
            tally[r.state] += 1
            if r.state == "closed":
                closed.append(f"{job.company.name if job.company else ''}, {job.title}: {r.reason}")
            db.commit()
            if (i + 1) % 10 == 0:
                log(f"{i + 1} of {len(jobs)} checked")
    finally:
        f.close()
    for line in closed[:12]:
        log(f"Closed: {line}")
    log.done(f"{tally['open']} still open, {tally['closed']} closed, {tally['unchecked']} couldn't be checked")
    log.step(1)
    prof = get_profile(db)
    data = dict(prof.data or {})
    data["intern_last_verify"] = now().isoformat(timespec="seconds")
    prof.data = data
    db.commit()
    c = counts(db)
    log.done(f"{c['total_ok']} qualify after the check")
    return {"checked": len(jobs), **tally, "counts": c,
            "highlights": [{"label": "Still open", "value": tally["open"], "href": "/internships"},
                           {"label": "Closed", "value": tally["closed"], "href": "/internships"},
                           {"label": "Check yourself", "value": tally["unchecked"], "href": "/internships"}]}
