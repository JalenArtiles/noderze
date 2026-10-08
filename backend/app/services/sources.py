"""Wide coverage sources, all of which permit programmatic access.

1. Board directory: 2,700+ company job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) whose tokens
   were taken from real posting links in the public SimplifyJobs new-grad feed. Scanning a board returns every
   role that company posts, so sales and SE roles are covered even though the feed itself is engineering-heavy.
2. Public new-grad feed (SimplifyJobs on GitHub): imported as leads that link to the original postings.
3. The Muse public jobs API (no key) and Adzuna (free key): aggregator search results, stored as leads.
LinkedIn, Indeed, Glassdoor and Handshake are deliberately not scraped (terms of service and bot blocking).
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR, settings
from ..models import Alert, Company, Job
from ..util import now, slugify
from .ats import RawPosting, fetch_postings, html_to_text, parse_ats_url, smartrecruiters_detail, workday_detail
from .classify import classify_role, parse_location
from .discovery import infer_category, record_se_team, upsert_posting
from .fetch import FetchBlocked, PoliteFetcher

SIMPLIFY_FEED = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
DIRECTORY_FILE = BACKEND_DIR / "seed" / "board_directory.json"
WIDE_WORKDAY_QUERIES = ["sales engineer", "solutions engineer", "solutions consultant", "sales development"]
TARGET_STATES = {"AZ", "CA", "TX", "FL"}


def location_ok(location_text: str, title: str = "") -> bool:
    """Keep US roles in target states, remote US roles, and roles with no parseable location."""
    li = parse_location(location_text, "", title)
    if li.international_only:
        return False
    if li.remote_type == "remote" and (li.allowed_states is None or set(li.allowed_states) & {"AZ", "CA"}):
        return True
    return not li.states or bool(set(li.states) & TARGET_STATES)


def relevant(title: str, desc: str = "") -> bool:
    rc = classify_role(title, desc)
    return rc.family in ("direct_se", "pipeline", "technical_entry") and not rc.is_senior


# ----------------------------------------------------------------------------- directory

def build_directory(listings: list[dict]) -> list[dict]:
    """One board per company, chosen by how many feed postings point at it."""
    per_company: dict[str, Counter] = {}
    for x in listings:
        p = parse_ats_url(x.get("url", ""))
        if not p or p[0] == "jobvite":
            continue
        key = (p[0], p[1] if p[0] != "workday" else p[1], p[2] if p[0] == "workday" else None)
        per_company.setdefault(x["company_name"].strip(), Counter())[key] += 1
    out = []
    for name, c in per_company.items():
        (kind, token, site), _ = c.most_common(1)[0]
        entry = {"name": name, "ats_type": kind, "token": token if kind != "workday" else None}
        if kind == "workday":
            entry.update({"host": token, "site": site})
        out.append(entry)
    return sorted(out, key=lambda e: e["name"].lower())


def load_directory() -> list[dict]:
    return json.loads(DIRECTORY_FILE.read_text()) if DIRECTORY_FILE.exists() else []


def _company_for(db: Session, entry: dict) -> Company | None:
    c = db.scalar(select(Company).where(Company.slug == slugify(entry["name"])))
    if c is None and entry.get("token"):
        c = db.scalar(select(Company).where(Company.ats_token == entry["token"]))
    return c


def wide_scan(db: Session, log, include_workday: bool = False, limit: int | None = None,
              kinds: tuple = ("greenhouse", "lever", "ashby", "smartrecruiters")) -> dict:
    """Scan the whole board directory. Creates a company only when it has a relevant role in your geography."""
    directory = [e for e in load_directory() if e["ats_type"] in kinds or (include_workday and e["ats_type"] == "workday")]
    if limit:
        directory = directory[:limit]
    stats = {"boards": 0, "relevant": 0, "new_jobs": 0, "new_companies": 0, "errors": 0}
    f = PoliteFetcher(min_interval=1.0)
    started = time.monotonic()
    try:
        for i, e in enumerate(directory):
            existing = _company_for(db, e)
            if existing is not None and existing.watch_status in ("priority", "strong", "monitor", "edge"):
                continue  # watched companies are covered by the daily scan
            stats["boards"] += 1
            try:
                if e["ats_type"] == "workday":
                    postings = _workday_titles(f, e["host"], e["site"])
                else:
                    postings = fetch_postings(f, e["ats_type"], e["token"])
            except FetchBlocked as ex:
                stats["errors"] += 1
                if "403" in str(ex) or "429" in str(ex):
                    log(f"{e['name']}: {ex}")
                continue
            except Exception:
                stats["errors"] += 1
                continue
            keep = [p for p in postings if relevant(p.title, p.description) and location_ok(p.location_text, p.title)]
            if keep:
                company = existing or Company(name=e["name"], slug=slugify(e["name"]), ats_type=e["ats_type"],
                                              ats_token=e.get("token"), ats_host=e.get("host"), ats_site=e.get("site"),
                                              ats_verified=True, watch_note="Found by the wide board scan.")
                if existing is None:
                    company.category = infer_category([p.title + " " + (p.description or "")[:3000] for p in postings[:40]])
                    db.add(company)
                    db.flush()
                    stats["new_companies"] += 1
                record_se_team(db, company, postings, None)
                hits_home = False
                for p in keep:
                    if e["ats_type"] == "workday" and not p.description:
                        try:
                            p = workday_detail(f, e["host"], e["site"], p.extra.get("workday_path", p.ats_job_id))
                        except Exception:
                            pass
                    if e["ats_type"] == "smartrecruiters" and not p.description:
                        try:
                            p.description = smartrecruiters_detail(f, e["token"], p.ats_job_id)
                        except Exception:
                            pass
                    job, is_new = upsert_posting(db, company, p, original=True)
                    stats["relevant"] += 1
                    if is_new:
                        stats["new_jobs"] += 1
                        if job.category in ("entry_sales", "program", "other_sales"):
                            db.add(Alert(job_id=job.id, message=f"Wide scan: {company.name}, {job.title} ({job.score_total:.0f}/100)"))
                    db.commit()
                    li = parse_location(job.location_text, job.description_text, job.title)
                    hits_home |= bool(set(li.states) & {"AZ", "CA"}) or li.remote_type == "remote"
                if hits_home and not company.watch_status:
                    company.watch_status = "monitor"
                db.commit()
            if (i + 1) % 50 == 0:
                log(f"{i + 1}/{len(directory)} boards scanned, {stats['relevant']} relevant roles, "
                    f"{stats['new_companies']} new companies ({int(time.monotonic() - started)}s)")
    finally:
        f.close()
    log(f"Wide scan done: {stats}")
    return stats


def _workday_titles(f: PoliteFetcher, host: str, site: str) -> list[RawPosting]:
    tenant = host.split(".")[0]
    seen: dict[str, RawPosting] = {}
    for q in WIDE_WORKDAY_QUERIES:
        data = f.post_json(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                           {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q})
        for p in data.get("jobPostings", []):
            path = p.get("externalPath", "")
            seen.setdefault(path, RawPosting(title=p.get("title", ""), url=f"https://{host}/{site}{path}",
                                             ats_job_id=path, location_text=p.get("locationsText", ""),
                                             source="workday", extra={"workday_path": path}))
    return list(seen.values())


# ----------------------------------------------------------------------------- feeds and aggregator APIs

def parse_simplify(listings: list[dict], max_age_days: int = 120) -> list[tuple[str, RawPosting]]:
    cutoff = time.time() - max_age_days * 86400
    out = []
    for x in listings:
        if not (x.get("active") and x.get("is_visible")) or x.get("date_posted", 0) < cutoff:
            continue
        loc = "; ".join(x.get("locations") or [])
        if not relevant(x["title"]) or not location_ok(loc, x["title"]):
            continue
        out.append((x["company_name"].strip(), RawPosting(
            title=x["title"].strip(), url=re.sub(r"[?&]utm_source=Simplify.*$", "", x["url"]), ats_job_id="",
            location_text=loc, posted_at=datetime.fromtimestamp(x["date_posted"], tz=timezone.utc).replace(tzinfo=None),
            description=f"Listed in the SimplifyJobs new-grad feed. Sponsorship: {x.get('sponsorship', 'unknown')}. "
                        f"Degrees: {', '.join(x.get('degrees') or [])}.", source="simplify")))
    return out


def parse_muse(payload: dict) -> list[tuple[str, RawPosting]]:
    out = []
    for j in payload.get("results", []):
        out.append(((j.get("company") or {}).get("name", "").strip(), RawPosting(
            title=j.get("name", "").strip(), url=(j.get("refs") or {}).get("landing_page", ""), ats_job_id="",
            location_text="; ".join(l.get("name", "") for l in j.get("locations", [])),
            description=html_to_text(j.get("contents")),
            posted_at=datetime.fromisoformat(j["publication_date"].replace("Z", "+00:00")).replace(tzinfo=None)
            if j.get("publication_date") else None, source="themuse")))
    return out


def parse_adzuna(payload: dict) -> list[tuple[str, RawPosting]]:
    out = []
    for j in payload.get("results", []):
        out.append(((j.get("company") or {}).get("display_name", "").strip(), RawPosting(
            title=html_to_text(j.get("title", "")).strip(), url=j.get("redirect_url", ""), ats_job_id="",
            location_text=(j.get("location") or {}).get("display_name", ""), description=html_to_text(j.get("description")),
            comp_min=j.get("salary_min"), comp_max=j.get("salary_max"), comp_period="year" if j.get("salary_min") else None,
            posted_at=datetime.fromisoformat(j["created"].replace("Z", "+00:00")).replace(tzinfo=None)
            if j.get("created") else None, source="adzuna")))
    return out


def parse_remotive(payload: dict) -> list[tuple[str, RawPosting]]:
    out = []
    for j in payload.get("jobs", []):
        where = (j.get("candidate_required_location") or "").lower()
        if where and not re.search(r"usa|united states|\bus\b|americas|north america|worldwide|anywhere", where):
            continue
        out.append(((j.get("company_name") or "").strip(), RawPosting(
            title=(j.get("title") or "").strip(), url=j.get("url", ""), ats_job_id="", location_text="Remote, US",
            description=html_to_text(j.get("description")),
            posted_at=datetime.fromisoformat(j["publication_date"]) if j.get("publication_date") else None,
            source="remotive")))
    return out


def _store_leads(db: Session, items: list[tuple[str, RawPosting]], stats: dict) -> None:
    for company_name, p in items:
        if not company_name or not relevant(p.title, p.description) or not location_ok(p.location_text, p.title):
            continue
        c = db.scalar(select(Company).where(Company.slug == slugify(company_name)))
        parsed = parse_ats_url(p.url)
        if c is None:
            c = Company(name=company_name, slug=slugify(company_name), watch_note=f"Found through {p.source}.",
                        category=infer_category([p.title, p.description or ""]),
                        ats_type=parsed[0] if parsed and parsed[0] != "workday" else None,
                        ats_token=parsed[1] if parsed and parsed[0] not in ("workday",) else None)
            db.add(c)
            db.flush()
            stats["new_companies"] += 1
        job, is_new = upsert_posting(db, c, p, original=False)
        job.needs_verification = True
        stats["leads"] += 1
        stats["new"] += int(is_new)
    db.commit()


def import_feeds(db: Session, log) -> dict:
    stats = {"leads": 0, "new": 0, "new_companies": 0}
    try:
        r = httpx.get(SIMPLIFY_FEED, timeout=60, headers={"User-Agent": settings.http_user_agent})
        r.raise_for_status()
        items = parse_simplify(r.json())
        _store_leads(db, items, stats)
        log(f"New-grad feed: {len(items)} relevant active roles")
    except Exception as e:
        log(f"New-grad feed unavailable: {e}")
    queries = [("Sales", "Phoenix, AZ"), ("Sales", "Flexible / Remote"), ("Sales", "San Francisco, CA"),
               ("Sales", "Los Angeles, CA"), ("Sales", "San Diego, CA")]
    for cat, loc in queries:
        try:
            r = httpx.get(f"https://www.themuse.com/api/public/jobs?page=0&category={quote(cat)}&location={quote(loc)}"
                          f"&level=Entry%20Level", timeout=30, headers={"User-Agent": settings.http_user_agent})
            if r.status_code == 200:
                _store_leads(db, parse_muse(r.json()), stats)
        except Exception as e:
            log(f"The Muse ({loc}) unavailable: {e}")
    try:
        r = httpx.get("https://remotive.com/api/remote-jobs?category=sales&limit=150", timeout=30,
                      headers={"User-Agent": settings.http_user_agent})
        if r.status_code == 200:
            _store_leads(db, parse_remotive(r.json()), stats)
    except Exception as e:
        log(f"Remotive unavailable: {e}")
    if settings.adzuna_app_id and settings.adzuna_app_key:
        for what, where in [("sales development representative cybersecurity", "Arizona"),
                            ("business development representative security", "Arizona"),
                            ("sales development representative", "Phoenix"), ("account executive cybersecurity", "Arizona"),
                            ("sales development representative cybersecurity", "San Diego"),
                            ("sales development representative security", "Irvine"), ("associate sales engineer", "Arizona")]:
            try:
                r = httpx.get("https://api.adzuna.com/v1/api/jobs/us/search/1", timeout=30, params={
                    "app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key, "what": what, "where": where,
                    "results_per_page": 50, "max_days_old": 45})
                if r.status_code == 200:
                    _store_leads(db, parse_adzuna(r.json()), stats)
            except Exception as e:
                log(f"Adzuna unavailable: {e}")
    else:
        log("Adzuna skipped (add ADZUNA_APP_ID and ADZUNA_APP_KEY to backend/.env for much wider coverage)")
    log(f"Feeds and APIs: {stats['leads']} relevant leads, {stats['new']} new, {stats['new_companies']} new companies")
    return stats
