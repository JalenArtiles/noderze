"""Where Noderze looks for spring internships, and how it reads them.

1. The public SimplifyJobs internship list (GitHub): every listed internship marked for spring 2027, winter 2027 or
   with no term, in the Phoenix area or remote, resolved to the employer's own posting so pay and hours can be read.
2. Phoenix-area employers' own job boards (seed/intern_boards.json): Greenhouse, Lever, Ashby, SmartRecruiters and
   Workday APIs, SRP's and APS's career sites, and the State of Arizona's job site (5-second crawl delay, as its
   robots.txt asks).
3. Your watched companies' boards, for remote internships at the security companies you're targeting.
4. The Muse's public API (and Adzuna when you add a free key).
Sites that forbid automated reading (Handshake, LinkedIn, Indeed, city sites on governmentjobs.com) are never
fetched; the page links to searches you open yourself.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR, settings
from ..models import Company, Job
from ..util import now, slugify
from .ats import (RawPosting, fetch_postings, fetch_single, html_to_text, parse_ats_url, parse_azstatejobs_search,
                  parse_jsonld_posting, parse_successfactors_job, parse_successfactors_search, parse_workday_url,
                  smartrecruiters_detail, workday_detail, workday_search)
from .fetch import FetchBlocked, PoliteFetcher
from .internships import is_generic_intern, is_intern_title, track_of, where_of

INTERN_FEED = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json"
BOARDS_FILE = BACKEND_DIR / "seed" / "intern_boards.json"
WORKDAY_QUERIES = ("intern", "internship", "student")
FEED_TERMS = {"spring 2027", "winter 2027", "n/a", "fall 2026"}
WATCHED = ("priority", "strong", "monitor", "edge")


def _warn(log, msg: str) -> None:
    (getattr(log, "warn", None) or log)(msg)


def load_boards() -> list[dict]:
    if not BOARDS_FILE.exists():
        return []
    return json.loads(BOARDS_FILE.read_text(encoding="utf-8")).get("boards", [])


# ----------------------------------------------------------------------------- pre-filter

def candidate(title: str, location_text: str = "", phoenix_only_generic: bool = True) -> bool:
    """Cheap check before fetching a posting's details: an internship title in a tracked field (or general IT, or a
    generic "Intern" title), somewhere that could work."""
    if not is_intern_title(title):
        return False
    tr = track_of(title)
    w = where_of(location_text, "", title)
    if w.status in ("outside", "tucson"):
        return False
    if tr.track in ("cyber", "data", "network"):
        return True
    if tr.track != "it" and not is_generic_intern(title):
        return False
    # General IT and generic "Intern" titles only near Phoenix; the posting text then decides the field.
    near = w.status in ("phoenix", "hybrid_phoenix", "az_unknown")
    return near if phoenix_only_generic else near or w.status == "remote"


def _baseline_done(db: Session) -> bool:
    from .profile import get_profile
    return bool((get_profile(db).data or {}).get("intern_baseline_done"))


def _company(db: Session, name: str, entry: dict | None = None, postings_text: list[str] | None = None) -> Company:
    entry = entry or {}
    c = db.scalar(select(Company).where(Company.slug == slugify(name)))
    if c is None and entry.get("token"):
        c = db.scalar(select(Company).where(Company.ats_token == entry["token"]))
    if c is None:
        from .discovery import infer_category
        c = Company(name=name, slug=slugify(name), watch_note="Found by the spring internship search.",
                    ats_type=entry.get("ats_type") if entry.get("ats_type") in ("greenhouse", "lever", "ashby",
                                                                                 "smartrecruiters", "workday") else None,
                    ats_token=entry.get("token"), ats_host=entry.get("host"), ats_site=entry.get("site"),
                    category=infer_category(postings_text or []))
        db.add(c)
        db.flush()
    return c


def _store(db: Session, company: Company, p: RawPosting, label: str, stats: dict, original: bool = True) -> Job | None:
    from .discovery import upsert_posting
    from .intern_jobs import alert_new
    if track_of(p.title, p.description).track == "other" and len(p.description or "") >= 250:
        return None  # a generic "Intern" whose posting isn't data, cybersecurity or networking work
    job, is_new = upsert_posting(db, company, p, original=original, kind="intern", source_label=label)
    if (p.extra or {}).get("deadline") and not job.deadline:
        from datetime import date
        try:
            job.deadline = date.fromisoformat(p.extra["deadline"][:10])
        except ValueError:
            pass
    if not original:
        job.needs_verification = True
    stats["stored"] = stats.get("stored", 0) + 1
    if is_new:
        stats["new"] = stats.get("new", 0) + 1
        if _baseline_done(db):
            alert_new(db, job)
    db.commit()
    return job


# ----------------------------------------------------------------------------- company boards

def capture_board(db: Session, company: Company, postings: list[RawPosting], log, f: PoliteFetcher | None = None,
                  source_label: str = "Company job board", stats: dict | None = None) -> set[int]:
    """Store the internship postings in a board listing that was already fetched (Greenhouse, Lever, Ashby,
    SmartRecruiters). Returns the stored job ids."""
    stats = stats if stats is not None else {}
    ids: set[int] = set()
    for p in postings:
        if not candidate(p.title, p.location_text):
            continue
        if p.source == "smartrecruiters" and not p.description and f is not None:
            try:
                p.description = smartrecruiters_detail(f, company.ats_token or "", p.ats_job_id)
            except Exception:
                pass
        job = _store(db, company, p, source_label, stats)
        if job is not None:
            ids.add(job.id)
    return ids


def _close_missing(db: Session, company: Company, source: str, seen: set[int]) -> int:
    n = 0
    for job in db.scalars(select(Job).where(Job.company_id == company.id, Job.family == "internship",
                                            Job.source == source, Job.is_active.is_(True))):
        if job.id not in seen:
            job.is_active = False
            job.flags = list(set((job.flags or []) + ["closed_or_removed"]))
            n += 1
    if n:
        from .intern_jobs import evaluate_job
        for job in db.scalars(select(Job).where(Job.company_id == company.id, Job.family == "internship",
                                                Job.is_active.is_(False), Job.source == source)):
            evaluate_job(db, job)
    db.commit()
    return n


def _workday_board(db: Session, f: PoliteFetcher, company: Company, host: str, site: str, log, stats: dict,
                   label: str, pages: int = 2) -> set[int]:
    found: dict[str, dict] = {}
    for q in WORKDAY_QUERIES:
        try:
            for item in workday_search(f, host, site, q, pages=pages if q == "intern" else 1):
                found.setdefault(item["path"], item)
        except FetchBlocked as e:
            _warn(log, f"{company.name}: {e}")
            break
    ids: set[int] = set()
    for path, item in found.items():
        if not candidate(item["title"], item["locations"]):
            continue
        try:
            p = workday_detail(f, host, site, path)
        except Exception as e:
            log(f"{company.name}: couldn't read {item['title']} ({e.__class__.__name__})")
            continue
        p.extra = dict(p.extra or {}, workplace=None)
        job = _store(db, company, p, label, stats)
        if job is not None:
            ids.add(job.id)
    # Internships stored earlier but not found by today's searches: look each one up directly.
    for job in db.scalars(select(Job).where(Job.company_id == company.id, Job.family == "internship",
                                            Job.source == "workday", Job.is_active.is_(True))):
        if job.id in ids or not job.url:
            continue
        parsed = parse_workday_url(job.url)
        if not parsed:
            continue
        try:
            workday_detail(f, *parsed)
            job.last_verified_at = now()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 410):
                job.is_active = False
                job.flags = list(set((job.flags or []) + ["closed_or_removed"]))
                from .intern_jobs import evaluate_job
                evaluate_job(db, job)
        except Exception:
            pass
    db.commit()
    return ids


def _successfactors(db: Session, f: PoliteFetcher, entry: dict, log, stats: dict) -> set[int]:
    base = entry["base"].rstrip("/")
    company = _company(db, entry["name"], entry)
    if not company.website:
        company.website = base
    if entry.get("category") and not company.category:
        company.category = entry["category"]
    listed: dict[str, RawPosting] = {}
    for start in (0, 10, 20, 30, 40):
        try:
            html = f.get_text(f"{base}/search/?q=intern&sortColumn=referencedate&sortDirection=desc&startrow={start}")
        except FetchBlocked as e:
            _warn(log, f"{entry['name']}: {e}")
            break
        batch = [p for p in parse_successfactors_search(html, base) if p.ats_job_id not in listed]
        for p in batch:
            listed[p.ats_job_id] = p
        if not batch:
            break
    ids: set[int] = set()
    for p in listed.values():
        if not candidate(p.title, p.location_text):
            continue
        try:
            p = parse_successfactors_job(f.get_text(p.url), p)
        except Exception as e:
            log(f"{entry['name']}: couldn't read {p.title} ({e.__class__.__name__})")
            continue
        job = _store(db, company, p, f"{entry['name']} careers site", stats)
        if job is not None:
            ids.add(job.id)
    _close_missing(db, company, "successfactors", ids)
    return ids


def _az_state(db: Session, entry: dict, log, stats: dict) -> set[int]:
    base = entry["base"].rstrip("/")
    f = PoliteFetcher(min_interval=5.0)  # robots.txt asks for a 5 second crawl delay
    ids: set[int] = set()
    try:
        rows: dict[str, dict] = {}
        for page in range(1, 8):
            try:
                html = f.get_text(f"{base}/jobs/search?page={page}&query=intern")
            except FetchBlocked as e:
                _warn(log, f"State of Arizona jobs: {e}")
                break
            batch = [r for r in parse_azstatejobs_search(html) if r["url"] not in rows]
            if not batch:
                break
            for r in batch:
                rows[r["url"]] = r
        for r in rows.values():
            if "intern" not in (r["type"] or "").lower() and not is_intern_title(r["title"]):
                continue
            if not candidate(r["title"], r["location"], phoenix_only_generic=False):
                continue
            try:
                page_html = f.get_text(r["url"])
            except Exception as e:
                log(f"State of Arizona: couldn't read {r['title']} ({e.__class__.__name__})")
                continue
            p = parse_jsonld_posting(page_html, r["url"], source="azstatejobs") or RawPosting(
                title=r["title"], url=r["url"], ats_job_id="", description=html_to_text(page_html)[:20000],
                source="azstatejobs")
            p.title = r["title"].title() if r["title"].isupper() else r["title"]
            p.location_text = r["location"] or p.location_text
            dept = re.sub(r"\bDept\b", "Department", (r["department"] or "").title()).replace(" Of ", " of ").replace(
                " And ", " and ")
            name = f"Arizona {dept}" if dept and not dept.lower().startswith("arizona") else (dept or "State of Arizona")
            company = _company(db, name)
            if not company.website:
                company.website = "https://az.gov"
            company.public_sector = True
            job = _store(db, company, p, "Arizona state jobs", stats)
            if job is not None:
                ids.add(job.id)
        for job in db.scalars(select(Job).where(Job.family == "internship", Job.source == "azstatejobs",
                                                Job.is_active.is_(True))):
            if job.id not in ids and rows:
                job.is_active = False
                from .intern_jobs import evaluate_job
                evaluate_job(db, job)
        db.commit()
    finally:
        f.close()
    return ids


def scan_board(db: Session, f: PoliteFetcher, entry: dict, log, stats: dict, label: str = "Company job board") -> int:
    kind = entry.get("ats_type")
    try:
        if kind == "successfactors":
            return len(_successfactors(db, f, entry, log, stats))
        if kind == "azstatejobs":
            return len(_az_state(db, entry, log, stats))
        if kind == "workday":
            company = _company(db, entry["name"], entry)
            return len(_workday_board(db, f, company, entry["host"], entry["site"], log, stats, label))
        postings = fetch_postings(f, kind, entry.get("token"))
        company = _company(db, entry["name"], entry, [p.title + " " + (p.description or "")[:2000] for p in postings[:30]])
        ids = capture_board(db, company, postings, log, f, label, stats)
        _close_missing(db, company, kind, ids)
        return len(ids)
    except FetchBlocked as e:
        log(f"{entry['name']}: {e}")
    except Exception as e:
        log(f"{entry['name']}: couldn't read the board ({e.__class__.__name__})")
    stats["errors"] = stats.get("errors", 0) + 1
    return 0


def scan_watched(db: Session, f: PoliteFetcher, log, stats: dict) -> int:
    n = 0
    for c in db.scalars(select(Company).where(Company.watch_status.in_(WATCHED), Company.ats_type.is_not(None))):
        if c.ats_type == "workday" and c.ats_host and c.ats_site:
            try:
                n += len(_workday_board(db, f, c, c.ats_host, c.ats_site, log, stats, "Your target companies", pages=1))
            except Exception:
                stats["errors"] = stats.get("errors", 0) + 1
            continue
        if c.ats_type not in ("greenhouse", "lever", "ashby", "smartrecruiters") or not c.ats_token:
            continue
        try:
            postings = fetch_postings(f, c.ats_type, c.ats_token)
        except Exception:
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        ids = capture_board(db, c, postings, log, f, "Your target companies", stats)
        _close_missing(db, c, c.ats_type, ids)
        n += len(ids)
    return n


# ----------------------------------------------------------------------------- the SimplifyJobs internship list

def feed_candidates(listings: list[dict]) -> list[dict]:
    out = []
    for x in listings:
        if not (x.get("active") and x.get("is_visible", True)):
            continue
        terms = {t.lower() for t in x.get("terms") or []}
        if terms and not terms & FEED_TERMS:
            continue
        if terms and terms <= {"fall 2026"}:
            continue
        locs = "; ".join(x.get("locations") or [])
        if not candidate(x.get("title", ""), locs.replace("Remote in USA", "Remote, US")):
            continue
        out.append(x)
    return out


def resolve(f: PoliteFetcher, url: str, title: str, location_text: str) -> tuple[RawPosting, bool]:
    """Read the employer's own posting behind a list link. Returns (posting, is_original)."""
    parsed = parse_ats_url(url)
    try:
        if parsed and parsed[0] in ("greenhouse", "lever", "ashby") and parsed[2]:
            p = fetch_single(f, parsed[0], parsed[1], parsed[2])
            if p:
                return p, True
        wd = parse_workday_url(url)
        if wd:
            return workday_detail(f, *wd), True
        if parsed and parsed[0] == "smartrecruiters" and parsed[2]:
            desc = smartrecruiters_detail(f, parsed[1], parsed[2])
            return RawPosting(title=title, url=url, ats_job_id=parsed[2], location_text=location_text, description=desc,
                              source="smartrecruiters"), True
        page = f.get_text(url)
        p = parse_jsonld_posting(page, url, source="employer site")
        if p and len(p.description) >= 250:
            p.title = p.title or title
            p.location_text = p.location_text or location_text
            return p, True
        text = html_to_text(page)
        if len(text) >= 800 and re.search(r"intern", text, re.I):
            return RawPosting(title=title, url=url, ats_job_id="", location_text=location_text, description=text[:20000],
                              source="employer site"), True
    except Exception:
        pass
    return RawPosting(title=title, url=url, ats_job_id="", location_text=location_text, description="",
                      source="simplify"), False


def import_feed(db: Session, f: PoliteFetcher, log, stats: dict) -> int:
    try:
        r = httpx.get(INTERN_FEED, timeout=90, headers={"User-Agent": settings.http_user_agent}, follow_redirects=True)
        r.raise_for_status()
        listings = r.json()
    except Exception as e:
        _warn(log, f"Internship list unavailable: {e.__class__.__name__}")
        return 0
    picks = feed_candidates(listings)
    log(f"Internship list: {len(listings)} listings, {len(picks)} possible spring internships near you or remote")
    n = 0
    for x in picks:
        name = x["company_name"].strip()
        locs = "; ".join(x.get("locations") or []).replace("Remote in USA", "Remote, US")
        p, original = resolve(f, x["url"], x["title"].strip(), locs)
        p.location_text = locs or p.location_text  # the list's locations are cleaner than many career pages
        p.extra = dict(p.extra or {}, feed_terms=x.get("terms") or [])
        parsed = parse_ats_url(x["url"])
        entry = {"ats_type": parsed[0], "token": parsed[1]} if parsed and parsed[0] != "workday" else {}
        company = _company(db, name, entry)
        if _store(db, company, p, "SimplifyJobs internship list", stats, original=original):
            n += 1
    # Listings the list now marks closed
    closed = {x["url"] for x in listings if not x.get("active")}
    for job in db.scalars(select(Job).where(Job.family == "internship", Job.is_active.is_(True), Job.url.in_(closed))):
        job.is_active = False
        from .intern_jobs import evaluate_job
        evaluate_job(db, job)
    db.commit()
    return n


# ----------------------------------------------------------------------------- job sites with public APIs

MUSE_LOCATIONS = ("Phoenix, AZ", "Tempe, AZ", "Scottsdale, AZ", "Chandler, AZ", "Mesa, AZ", "Flexible / Remote")


def import_job_sites(db: Session, log, stats: dict) -> int:
    from .sources import parse_adzuna, parse_muse
    n = 0
    for loc in MUSE_LOCATIONS:
        for page in range(3):
            try:
                r = httpx.get(f"https://www.themuse.com/api/public/jobs?page={page}&level=Internship&location={quote(loc)}",
                              timeout=30, headers={"User-Agent": settings.http_user_agent})
                if r.status_code != 200:
                    break
                data = r.json()
            except Exception:
                break
            for name, p in parse_muse(data):
                if name and candidate(p.title, p.location_text):
                    if _store(db, _company(db, name), p, "The Muse", stats, original=False):
                        n += 1
            if page + 1 >= int(data.get("page_count") or 1):
                break
    if settings.adzuna_app_id and settings.adzuna_app_key:
        for what in ("cybersecurity intern", "data analyst intern", "network intern", "security intern part time"):
            for where in ("Phoenix", "Arizona"):
                try:
                    r = httpx.get("https://api.adzuna.com/v1/api/jobs/us/search/1", timeout=30, params={
                        "app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key, "what": what,
                        "where": where, "results_per_page": 50, "max_days_old": 60})
                    if r.status_code != 200:
                        continue
                except Exception:
                    continue
                for name, p in parse_adzuna(r.json()):
                    if name and candidate(p.title, p.location_text):
                        if _store(db, _company(db, name), p, "Adzuna", stats, original=False):
                            n += 1
    return n


# ----------------------------------------------------------------------------- the workflow

def run(db: Session, log) -> dict:
    from .intern_jobs import counts, evaluate_job
    from .profile import get_profile
    log.plan(["Read the internship lists", "Scan Phoenix-area employers", "Check Arizona public employers",
              "Scan your target companies", "Check pay, hours, dates and location"])
    stats: dict = {}
    f = PoliteFetcher(min_interval=1.0)
    boards = load_boards()
    try:
        log.step(0)
        a = import_feed(db, f, log, stats)
        b = import_job_sites(db, log, stats)
        log.done(f"{a + b} possible internships from the lists and job sites")

        log.step(1)
        n = 0
        company_boards = [e for e in boards if e.get("ats_type") not in ("successfactors", "azstatejobs")]
        for i, e in enumerate(company_boards):
            n += scan_board(db, f, e, log, stats)
            if (i + 1) % 15 == 0:
                log(f"{i + 1} of {len(company_boards)} employers scanned")
        log.done(f"{len(company_boards)} employers scanned, {n} internships in your fields")

        log.step(2)
        m = 0
        for e in [e for e in boards if e.get("ats_type") in ("successfactors", "azstatejobs")]:
            m += scan_board(db, f, e, log, stats)
        log.done(f"SRP, APS and State of Arizona: {m} internships in your fields")

        log.step(3)
        w = scan_watched(db, f, log, stats)
        log.done(f"{w} internships at companies you're watching")
    finally:
        f.close()

    log.step(4)
    prof = get_profile(db)
    for job in db.scalars(select(Job).where(Job.family == "internship")):
        evaluate_job(db, job, prof_data=prof.data or {})
    data = dict(prof.data or {})
    first = not data.get("intern_baseline_done")
    data["intern_baseline_done"] = True
    data["intern_last_scan"] = now().isoformat(timespec="seconds")
    prof.data = data
    db.commit()
    c = counts(db)
    log.done(f"{c['qualifies']} qualify, {c['check']} qualify with one thing to confirm, {c['out']} filtered out")
    return {"counts": c, "stats": stats, "first_scan": first,
            "highlights": [{"label": "Qualify", "value": c["qualifies"] + c["check"], "href": "/internships"},
                           {"label": "New this scan", "value": stats.get("new", 0), "href": "/internships?new=1"},
                           {"label": "Filtered out", "value": c["out"], "href": "/internships?tab=out"}]}
