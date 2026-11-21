"""Stores and re-checks internship postings (Job rows with family "internship" plus an InternDetail)."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Application, InternDetail, Job
from ..util import now
from .classify import parse_comp, parse_location
from .fit import why_this_role
from .internships import TRACK_LABELS, InternInput, evaluate
from .profile import get_profile, master_resume

FAMILY = "internship"
QUALIFY = "spring_intern"
OUT = "intern_out"
HINT_KEYS = ("time_type", "commitment", "employment_type", "feed_terms", "workplace")


def ensure_detail(db: Session, job: Job) -> InternDetail:
    d = job.intern or (db.scalar(select(InternDetail).where(InternDetail.job_id == job.id)) if job.id else None)
    if d is None:
        d = InternDetail(job=job, hints={}, overrides={}, sources=[], checks=[])
        db.add(d)
    return d


def absorb(d: InternDetail, extra: dict | None, source_label: str | None = None, readable: bool | None = None) -> None:
    """Keep the hints a source gave (Workday time type, Lever commitment, feed terms) and where it was found."""
    hints = dict(d.hints or {})
    for k in HINT_KEYS:
        v = (extra or {}).get(k)
        if v:
            hints[k] = v
    d.hints = hints
    if source_label and source_label not in (d.sources or []):
        d.sources = list(d.sources or []) + [source_label]
    if readable is not None:
        d.readable = readable


def evaluate_job(db: Session, job: Job, prof_data: dict | None = None, ledger: list | None = None) -> InternDetail:
    d = ensure_detail(db, job)
    prof = prof_data if prof_data is not None else (get_profile(db).data or {})
    company = job.company
    x = InternInput(
        title=job.title, description=job.description_text or "", location_text=job.location_text or "",
        workplace=(d.hints or {}).get("workplace"), comp_min=job.comp_min, comp_max=job.comp_max,
        comp_period=job.comp_period, hints=dict(d.hints or {}), is_active=job.is_active, readable=bool(d.readable),
        company_category=company.category if company else None, company_watch=company.watch_status if company else None,
        source_is_original=job.source_is_original, overrides=dict(d.overrides or {}))
    r = evaluate(x, prof.get("internship") or {})
    d.track, d.status, d.checks = r["track"], r["status"], r["checks"]
    d.pay, d.hours, d.term = r["pay"], r["hours"], r["term"]
    d.where = r["where"] | {"note": r["note"], "reasons_out": r["reasons_out"], "track_reason": r["track_reason"],
                            "track_strength": r["track_strength"]}
    d.evaluated_at = now()
    job.family = FAMILY
    job.category = QUALIFY if r["status"] != "out" else OUT
    job.score_total, job.score_breakdown, job.flags = r["score"], r["breakdown"], r["flags"]
    job.path_class, job.grad_status, job.grad_reason, job.is_program, job.yoe_min = None, None, None, False, None
    job.remote_type = {"remote": "remote", "hybrid_phoenix": "hybrid", "phoenix": "onsite"}.get(r["where"]["status"],
                                                                                                 "unknown")
    job.remote_scope = None
    job.locations = [{"state": s} for s in parse_location(job.location_text, "", job.title).states]
    if job.comp_min is None:
        c = parse_comp(job.description_text or "")
        if c.min is not None:
            job.comp_min, job.comp_max, job.comp_period, job.comp_note = c.min, c.max, c.period, c.note
    if ledger is None:
        res = master_resume(db)
        ledger = res.ledger if res else []
    skills = " ".join(str(v) for v in (prof.get("skills") or {}).values())
    certs = [c.get("name", "") if isinstance(c, dict) else str(c) for c in prof.get("certifications", [])]
    job.analysis = why_this_role(job.title, job.description_text or "", ledger, skills, certs)
    return d


def is_intern(job: Job | None) -> bool:
    return bool(job) and job.family == FAMILY


def intern_summary(job: Job) -> dict | None:
    """The internship fields shown on cards and the job page."""
    d = job.intern
    if not d:
        return None
    w = d.where or {}
    return {"track": d.track, "track_label": TRACK_LABELS.get(d.track, d.track), "status": d.status,
            "checks": d.checks or [], "pay": d.pay or {}, "hours": d.hours or {}, "term": d.term or {},
            "where": {k: w.get(k) for k in ("status", "label", "city", "tier")}, "note": w.get("note"),
            "reasons_out": w.get("reasons_out") or [], "track_reason": w.get("track_reason"),
            "track_strength": w.get("track_strength"), "sources": d.sources or [], "overrides": d.overrides or {},
            "readable": d.readable, "evaluated_at": d.evaluated_at.isoformat() if d.evaluated_at else None,
            "verify": (d.hints or {}).get("verify"), "gist": (sections(job.description_text).get("do") or [None])[0]}


# ----------------------------------------------------------------------------- what the posting says

_DO_HEAD = re.compile(r"^(?:primary |key |core |main |essential )?(?:responsibilities|duties|what you(?:'|’)?ll do|"
                      r"what you will do|your role|the role|the position|in this role|day[- ]to[- ]day|job duties|"
                      r"what you(?:'|’)?ll work on|projects|your impact|the impact you will make|about the (?:role|job)|"
                      r"job description|position summary|the opportunity|what we need from you|you will)\b", re.I)
_NEED_HEAD = re.compile(r"^(?:minimum |basic |required |preferred |desired |additional )?(?:qualifications|requirements|"
                        r"what you(?:'|’)?ll (?:need|bring)|what you bring|what we(?:'|’)?re looking for|who you are|"
                        r"skills|experience(?: and education)?|education|you have|must haves?|nice to have|"
                        r"the candidate|eligibility|about you|experience that matters)\b", re.I)
_BULLET = re.compile(r"^\s*(?:[-•*·▪●◦]|\d{1,2}[.)])\s+")


def sections(text: str | None, limit: int = 6) -> dict:
    """The posting's own bullet lists: what you'd do and what they ask for, in its words."""
    out: dict[str, list[str]] = {"do": [], "need": []}
    cur, lead = None, None  # lead: "Pursuing a degree in:" waiting for its short sub-bullets

    def add(item: str) -> None:
        if cur and len(out[cur]) < limit and 12 <= len(item) <= 600:
            out[cur].append(item if len(item) <= 230 else item[:227].rsplit(" ", 1)[0] + "...")

    def flush() -> None:
        nonlocal lead
        if lead and lead[1]:
            add(f"{lead[0]} {', '.join(lead[1])}")
        lead = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        head = line.rstrip(":").strip("*# ").strip()
        is_bullet = bool(_BULLET.match(line))
        item = _BULLET.sub("", line).strip()
        if not is_bullet and len(head) <= 70:
            kind = "do" if _DO_HEAD.match(head) else "need" if _NEED_HEAD.match(head) else None
            if kind or line.endswith(":") or (head.istitle() and len(head.split()) <= 6):
                flush()
                cur = kind
                continue
        if not cur:
            continue
        if is_bullet:
            if lead is not None and len(item) <= 45 and not item.endswith((".", ":")):
                lead[1].append(item)  # "Computer Science" under "Pursuing a degree in:"
                continue
            flush()
            if item.endswith(":"):
                lead = (item, [])
                continue
            if len(item.split()) <= 5 and not item.endswith(".") and item.replace("&", "And").istitle():
                continue  # a sub-heading written as a bullet ("Presales & Client Engagement")
            add(item)
        elif cur == "do" and not out["do"] and len(line) >= 80:
            add(line)  # a role described in a paragraph instead of bullets
    flush()
    return out


def _long(d) -> str:
    """'November 9, 2026' on every system (Windows strftime has no day-without-zero code)."""
    return f"{d:%B} {d.day}, {d.year}"


def details(job: Job) -> dict:
    """The facts shown at the top of an internship's page, each from the posting or marked as not stated."""
    d = job.intern
    pay, hours, term, where = (d.pay or {}), (d.hours or {}), (d.term or {}), (d.where or {}) if d else ({},) * 4
    v = (d.hints or {}).get("verify") if d else None
    sec = sections(job.description_text)
    source = ("The employer's own posting" if job.source_is_original else
              "Added by you" if job.source == "manual" else
              "A copy on The Muse" if job.source == "themuse" else
              "A copy on the SimplifyJobs list" if job.source == "simplify" else "Another job site")
    return {
        "facts": [
            {"key": "pay", "label": "Pay", "value": pay.get("label") or "Not stated", "evidence": pay.get("evidence")},
            {"key": "hours", "label": "Hours", "value": hours.get("label") or "Not stated", "evidence": hours.get("evidence")},
            {"key": "term", "label": "Dates", "value": term.get("label") or "Not stated", "evidence": term.get("evidence")},
            {"key": "where", "label": "Where", "value": where.get("label") or job.location_text or "Not stated",
             "evidence": job.location_text},
            {"key": "deadline", "label": "Apply by", "value": _long(job.deadline) if job.deadline else
             "No deadline listed"},
            {"key": "posted", "label": "Posted", "value": _long(job.posted_at) if job.posted_at else
             "Not stated"},
        ],
        "do": sec["do"], "need": sec["need"], "source": source, "url": job.url, "original": job.source_is_original,
        "verify": v, "open": job.is_active,
        "checked": job.last_verified_at.isoformat() if job.last_verified_at else None,
    }


def set_override(db: Session, job: Job, key: str, value: bool) -> InternDetail:
    d = ensure_detail(db, job)
    ov = dict(d.overrides or {})
    if value:
        ov[key] = True
    else:
        ov.pop(key, None)
    d.overrides = ov
    evaluate_job(db, job)
    return d


def alert_new(db: Session, job: Job) -> None:
    if job.category == QUALIFY and not db.scalar(select(Alert.id).where(Alert.job_id == job.id)):
        pay = (job.intern.pay or {}).get("label") if job.intern else ""
        db.add(Alert(job_id=job.id, message=f"Spring internship: {job.company.name}, {job.title}"
                                            + (f" ({pay})" if pay and "$" in pay else "")))


def posting_key(job: Job) -> str:
    """One key per real posting, however it reached Noderze: the Greenhouse job id, the Workday path, or the link
    without tracking parameters. 'U-Haul' and 'Uhaul' with the same Workday link are one internship."""
    import re
    from urllib.parse import parse_qs, urlparse

    from .ats import parse_ats_url, parse_workday_url
    url = (job.url or job.apply_url or "").strip()
    if not url:
        return f"title:{job.company_id}:{(job.title or '').lower()}"
    wd = parse_workday_url(url)
    if wd:
        host = re.sub(r"^wd\d+\.", "", wd[0])
        return f"workday:{host}:{wd[1].lower()}:{wd[2].rstrip('/').lower()}"
    u = urlparse(url)
    q = parse_qs(u.query)
    if q.get("gh_jid"):
        return f"greenhouse:{q['gh_jid'][0]}"
    parsed = parse_ats_url(url)
    if parsed and parsed[2]:
        if parsed[0] == "greenhouse":
            return f"greenhouse:{parsed[2]}"  # job ids are unique across Greenhouse boards
        return f"{parsed[0]}:{parsed[1].lower()}:{parsed[2].lower()}"
    keep = sorted((k, v[0]) for k, v in q.items() if not re.match(r"utm_|gh_src|source|ref|mobile|needsredirect|lang",
                                                                    k, re.I))
    return f"url:{u.netloc.lower().removeprefix('www.')}{u.path.rstrip('/').lower()}?{keep}"


def _rank(j: Job, stage: str | None) -> tuple:
    return (stage is not None, bool(j.source_is_original), len(j.description_text or "") >= 250, j.score_total or 0)


def board(db: Session) -> tuple[list[Job], dict]:
    """The Spring internships list: open postings you haven't acted on, one per real posting.

    Left out: anything you removed (Not for me), anything you opened the application for, applied to, heard back
    from or were turned down for (those live on the Applications board), and postings that closed. Duplicates of
    the same posting (from two lists, or under two spellings of the company) show once."""
    from ..models import PRE_APPLY
    stages = dict(db.execute(select(Application.job_id, Application.stage)).all())
    import re
    groups: dict[str, list[Job]] = {}
    originals: dict[tuple[str, str], list[Job]] = {}
    norm = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())
    for j in db.scalars(select(Job).where(Job.family == FAMILY)):
        groups.setdefault(posting_key(j), []).append(j)
        if j.source_is_original:
            originals.setdefault((norm(j.company.name if j.company else ""), norm(j.title)), []).append(j)
    # A copy (The Muse, the SimplifyJobs list) of a posting Noderze reads from the employer joins that posting.
    for key, members in list(groups.items()):
        if any(j.source_is_original for j in members):
            continue
        j0 = members[0]
        twin = originals.get((norm(j0.company.name if j0.company else ""), norm(j0.title)))
        if twin:
            groups.pop(key)
            groups[posting_key(twin[0])] = list(dict.fromkeys(groups.get(posting_key(twin[0]), []) + members))
    shown: list[Job] = []
    moved = {"started": 0, "applied": 0, "closed_out": 0, "removed": 0, "closed": 0}
    for members in groups.values():
        acted = [stages[j.id] for j in members if j.id in stages and stages[j.id] not in PRE_APPLY]
        if acted:
            st = acted[0]
            moved["started" if st == "started" else "closed_out" if st in ("rejected", "withdrawn") else "applied"] += 1
            continue
        if any(j.hidden for j in members):
            moved["removed"] += 1
            continue
        # A posting the employer's own site says is gone takes its copies on other lists with it.
        if any(not j.is_active and j.source_is_original for j in members):
            moved["closed"] += 1 if any(j.is_active for j in members) else 0
            continue
        live = [j for j in members if j.is_active]
        if not live:
            continue
        shown.append(max(live, key=lambda j: _rank(j, stages.get(j.id))))
    shown.sort(key=lambda j: -(j.score_total or 0))
    return shown, moved


def counts(db: Session) -> dict:
    from ..models import PRE_APPLY
    jobs, moved = board(db)
    stages = dict(db.execute(select(Application.job_id, Application.stage)).all())
    out = {"qualifies": 0, "check": 0, "out": 0, "saved": sum(1 for j in jobs if j.id in stages),
           "applied": moved["applied"] + moved["started"], "closed_out": moved["closed_out"]}
    for j in jobs:
        st = j.intern.status if j.intern else "out"
        out[st] = out.get(st, 0) + 1
    out["total_ok"] = out["qualifies"] + out["check"]
    return out


# ----------------------------------------------------------------------------- internships you found yourself

LOGIN_SITES = ("joinhandshake.com", "linkedin.com", "indeed.com")


class AddError(ValueError):
    """Shown to you as is: what to fix before the internship can be added."""


def add_found(db: Session, data: dict, fetcher=None) -> Job:
    """Add an internship you found (Handshake, LinkedIn, a career fair): a link Noderze can read, or pasted text.
    Links to sites that need you logged in are never fetched; their pasted text is used as is."""
    from ..models import Company
    from ..util import slugify
    from .ats import RawPosting
    from .discovery import upsert_posting
    from .fetch import PoliteFetcher
    from .intern_sources import resolve

    url, title = (data.get("url") or "").strip(), (data.get("title") or "").strip()
    location, desc = (data.get("location") or "").strip(), (data.get("description") or "").strip()
    p, original = None, False
    if url and not any(s in url.lower() for s in LOGIN_SITES):
        f = fetcher or PoliteFetcher(min_interval=0.5)
        try:
            p, original = resolve(f, url, title, location)
        finally:
            if fetcher is None:
                f.close()
        if not original:
            p = None
    if p is None:
        if not title or not desc:
            raise AddError("Noderze couldn't read that link (Handshake and LinkedIn need you logged in). "
                           "Paste the title and the posting text instead.")
        p = RawPosting(title=title, url=url, ats_job_id="", location_text=location, description=desc,
                       source="manual", extra={"full_text": True})
    if title:
        p.title = title
    if location:
        p.location_text = location
    name = (data.get("company_name") or (p.extra or {}).get("hiring_org") or "").strip()
    if not name:
        raise AddError("Add the company name.")
    company = db.scalar(select(Company).where(Company.slug == slugify(name)))
    if company is None:
        company = Company(name=name, slug=slugify(name), watch_note="Added with an internship you found.")
        db.add(company)
        db.flush()
    job, _ = upsert_posting(db, company, p, original=original, kind="intern", source_label=data.get("found_on") or "You added it")
    job.needs_verification = not original
    return job


def import_dropped(db: Session, folder=None) -> int:
    """Internships dropped as JSON files in data/intern-imports/ (one object or a list of them, with the same fields
    as Add one you found). Each file is added once, then moved to done/ with what happened to each internship."""
    import json
    import logging

    from ..config import settings
    log = logging.getLogger("noderze.intern_imports")
    folder = folder or settings.data_dir / "intern-imports"
    if not folder.exists():
        return 0
    added = 0
    for path in sorted(folder.glob("*.json")):
        results = []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            results.append({"error": "not valid JSON"})
            raw = []
        for item in raw if isinstance(raw, list) else [raw]:
            try:
                job = add_found(db, item)
                db.commit()
                d = evaluate_job(db, job)
                db.commit()
                results.append({"title": job.title, "company": job.company.name, "job_id": job.id, "status": d.status})
                added += 1
            except AddError as e:
                db.rollback()
                results.append({"title": item.get("title"), "error": str(e)})
            except Exception as e:  # one bad entry never blocks the rest
                db.rollback()
                log.exception("intern import failed for %s", item.get("title"))
                results.append({"title": item.get("title"), "error": type(e).__name__})
        done = folder / "done"
        done.mkdir(exist_ok=True)
        (done / path.name).write_text(json.dumps({"items": raw, "results": results}, indent=1), encoding="utf-8")
        path.unlink()
        log.info("imported %s from %s", len(results), path.name)
    return added
