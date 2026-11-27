"""Internship outreach: people to ask about a spring internship, whether or not their company has a posting.

A weekday Claude task (scheduled in Claude, outside Noderze) finds companies near Phoenix or remote with data,
security or network teams, finds a public contact for each (a campus recruiting or HR address, or a recruiter's
public LinkedIn profile), saves each email as a draft in your Gmail, writes the LinkedIn notes, and drops the batch
in data/outreach-imports/. Noderze lists them so you send each one yourself:

- Emails: open the draft in Gmail, read it, click Send.
- LinkedIn: one click copies the note and opens the profile; you paste and send.

Noderze never sends anything and never touches LinkedIn. data/outreach-imports/state.json tells the task who is
already on the list, so nobody is contacted twice.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Application, Company, EmailReply, Job, Prospect
from ..util import now, slugify, today

log = logging.getLogger(__name__)

STATUSES = ("ready", "drafted", "scheduled", "sent", "connected", "replied", "skipped", "bounced")
OPEN = ("drafted", "scheduled", "sent", "connected")  # waiting on them: replies from these companies are tracked
FOLLOW_UP_AFTER_DAYS = 3  # a follow-up on an internship you applied to is prepared this long after applying
NOTE_LIMIT = 200  # LinkedIn connection notes on a free account
FREE_MAIL = ("gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com",
             "aol.com")


def folder() -> Path:
    return settings.data_dir / "outreach-imports"


def _li(url: str | None) -> str | None:
    """linkedin.com/in/<handle> without tracking bits, so the same person is one row."""
    if not url:
        return None
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url, re.I)
    return f"https://www.linkedin.com/in/{m.group(1).lower()}" if m else url.strip()


def _domain(email: str | None) -> str:
    return (email or "").split("@")[-1].lower() if email and "@" in email else ""


def _company(db: Session, name: str, email: str | None) -> Company:
    c = db.scalar(select(Company).where(Company.slug == slugify(name)))
    if c is None:
        c = Company(name=name, slug=slugify(name), watch_note="Added for internship outreach.")
        db.add(c)
        db.flush()
    d = _domain(email)
    if d and not c.website and d not in FREE_MAIL and not (c.data or {}).get("logo_domain"):
        from .logos import matches
        if matches(name, d):
            c.data = dict(c.data or {}) | {"logo_domain": d}
    return c


def _parse_time(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def find(db: Session, email: str | None = None, linkedin_url: str | None = None, draft_id: str | None = None,
         company: str | None = None, name: str | None = None) -> Prospect | None:
    if draft_id:
        p = db.scalar(select(Prospect).where(Prospect.draft_id == draft_id))
        if p:
            return p
    if email:
        p = db.scalar(select(Prospect).where(Prospect.email == email.strip().lower()))
        if p:
            return p
    li = _li(linkedin_url)
    if li:
        p = db.scalar(select(Prospect).where(Prospect.linkedin_url == li))
        if p:
            return p
    if company and name:
        for p in db.scalars(select(Prospect).where(Prospect.name == name.strip())):
            if slugify(p.company_name) == slugify(company):
                return p
    return None


def import_items(db: Session, items: list[dict], batch: str | None = None) -> list[Prospect]:
    """Add the contacts in a batch. Someone already on the list is never added twice."""
    added = []
    for it in items:
        company = (it.get("company") or "").strip()
        email = (it.get("email") or "").strip().lower() or None
        li = _li(it.get("linkedin_url"))
        if not company or not (email or li):
            continue
        app_id = it.get("application_id")
        if find(db, email, li, it.get("draft_id"), company, it.get("name")):
            continue
        if app_id and db.scalar(select(Prospect.id).where(Prospect.application_id == app_id,
                                                           Prospect.channel == ("email" if email else "linkedin"))):
            continue  # one follow-up per application and channel
        c = _company(db, company, email)
        channel = "email" if email else "linkedin"
        note = (it.get("note") or "").strip() or None
        if note and len(note) > NOTE_LIMIT:
            note = note[:NOTE_LIMIT - 3].rsplit(" ", 1)[0] + "..."
        p = Prospect(campaign=it.get("campaign") or "spring_2027", company_id=c.id, company_name=company,
                     name=(it.get("name") or "").strip() or None, title=(it.get("title") or "").strip() or None,
                     email=email, linkedin_url=li, location=it.get("location"), channel=channel,
                     track=it.get("track"), why=it.get("why"), source_url=it.get("source_url"),
                     subject=it.get("subject"), email_body=it.get("body"), draft_id=it.get("draft_id"),
                     draft_url=it.get("draft_url"), note=note, followup=it.get("followup"), batch=batch,
                     status="drafted" if channel == "email" and it.get("draft_id") else "ready",
                     kind="applied" if app_id else "cold", application_id=app_id if app_id and db.get(Application, app_id) else None,
                     job_title=it.get("job_title"), posting_closed=bool(it.get("posting_closed")) or None)
        db.add(p)
        db.flush()
        drop_if_gone(p)
        added.append(p)
    return added


GONE_NOTE = "Not sent: the posting this is about is gone (its page says 404 Not found)."


def posting_gone(url: str | None) -> bool:
    """True only when the page itself says it's gone (404 or 410). A timeout or another error isn't proof, and
    search tools can show a cached copy of a page that was taken down, so Noderze checks the live page."""
    if not url or not url.lower().startswith("http"):
        return False
    import httpx
    try:
        r = httpx.get(url, follow_redirects=True, timeout=10,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
    except httpx.HTTPError:
        return False
    return r.status_code in (404, 410)


def drop_if_gone(p: Prospect) -> bool:
    """An email about a posting that no longer exists is set aside (Skipped, with the reason) instead of sent. A
    LinkedIn hello is still worth sending, so it stays, marked as about a closed listing and listed last."""
    if p.status not in ("ready", "drafted", "scheduled") or p.posting_closed or not posting_gone(p.source_url):
        return False
    if p.channel == "linkedin":
        p.posting_closed = True
        return False
    p.status, p.send_at, p.send_error = "skipped", None, GONE_NOTE
    return True


EDITABLE = {"name": "name", "title": "title", "subject": "subject", "body": "email_body", "email_body": "email_body",
            "note": "note", "followup": "followup", "why": "why", "source_url": "source_url", "linkedin_url": "linkedin_url",
            "email": "email", "draft_id": "draft_id", "draft_url": "draft_url", "posting_closed": "posting_closed"}


def _rewrite(p: Prospect, fields: dict) -> bool:
    """New wording or a named person for a message you haven't sent yet. An approved one goes back to waiting for
    your approval, since what you approved changed."""
    if p.status not in ("ready", "drafted", "scheduled"):
        return False
    changed = False
    for key, attr in EDITABLE.items():
        if key not in fields or fields[key] is None:
            continue
        v = fields[key].strip() if isinstance(fields[key], str) else fields[key]
        if attr == "linkedin_url":
            v = _li(v)
        elif attr == "email":
            v = v.lower()
        elif attr == "note" and v and len(v) > NOTE_LIMIT:
            v = v[:NOTE_LIMIT - 3].rsplit(" ", 1)[0] + "..."
        if getattr(p, attr) != v:
            setattr(p, attr, v)
            changed = True
    if changed and p.status == "scheduled":
        p.status, p.send_at, p.approved_at = ("drafted" if p.draft_id else "ready"), None, None
    return changed


def apply_updates(db: Session, updates: list[dict]) -> int:
    """What the task saw in Gmail since last time (drafts you sent, emails that bounced), plus rewrites of messages
    not sent yet: {"email" | "linkedin_url" | "draft_id" to find it, "set": {"subject", "body", "note", ...}}."""
    n = 0
    for u in updates:
        p = find(db, u.get("email"), u.get("linkedin_url"), u.get("draft_id"), u.get("company"), u.get("name"))
        if p and isinstance(u.get("set"), dict) and _rewrite(p, u["set"]):
            n += 1
        st = u.get("status")
        if not p or st not in STATUSES or p.status == st:
            continue
        if st == "sent" and p.status in ("replied", "connected"):
            continue  # don't step back
        p.status = st
        if st == "sent":
            p.sent_at = _parse_time(u.get("at")) or now()
        n += 1
    return n


def import_dropped(db: Session, path_folder: Path | None = None) -> int:
    """Read data/outreach-imports/*.json (except state.json), add the contacts, move each file to done/."""
    f = path_folder or folder()
    if not f.exists():
        return 0
    n = 0
    for path in sorted(f.glob("*.json")):
        if path.name == "state.json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raw = {}
        raw = raw if isinstance(raw, dict) else {"prospects": raw if isinstance(raw, list) else []}
        try:
            added = import_items(db, raw.get("prospects") or [], batch=raw.get("batch"))
            changed = apply_updates(db, raw.get("updates") or [])
            db.commit()
        except Exception:
            db.rollback()
            log.exception("outreach import failed for %s", path.name)
            added, changed = [], 0
        n += len(added) + changed
        done = f / "done"
        done.mkdir(exist_ok=True)
        (done / path.name).write_text(json.dumps({"added": [f"{p.company_name}: {p.name or p.email}" for p in added],
                                                  "updated": changed, "at": now().isoformat(timespec="seconds")},
                                                 indent=1), encoding="utf-8")
        path.unlink()
    if n:
        write_state(db)
    return n


def write_state(db: Session) -> Path:
    """data/outreach-imports/state.json: everyone already on the list, read by the weekday task."""
    f = folder()
    f.mkdir(parents=True, exist_ok=True)
    path = f / "state.json"
    rows = list(db.scalars(select(Prospect).order_by(Prospect.id)))
    data = {"updated": now().isoformat(timespec="seconds"),
            "contacts": [{"company": p.company_name, "name": p.name, "email": p.email, "linkedin_url": p.linkedin_url,
                          "status": p.status, "draft_id": p.draft_id, "subject": p.subject, "channel": p.channel,
                          "batch": p.batch} for p in rows],
            "companies": sorted({p.company_name for p in rows}),
            # Internships you applied to: the task prepares a follow-up for each one marked due.
            "applications": applications(db, rows),
            # When Noderze can send approved emails itself, the task writes the emails here instead of Gmail drafts.
            "noderze_sends": _sends()}
    text = json.dumps(data, indent=1)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def _sends() -> bool:
    from .mailer import configured
    return configured()


def applications(db: Session, rows: list[Prospect] | None = None) -> list[dict]:
    """Applications you submitted, with whether a follow-up is due (a few days after applying, none prepared yet)."""
    rows = rows if rows is not None else list(db.scalars(select(Prospect)))
    done = {p.application_id for p in rows if p.application_id}
    out = []
    for a in db.scalars(select(Application).where(Application.stage == "applied")):
        j: Job = db.get(Job, a.job_id)
        if j is None or j.company is None:
            continue
        applied = a.date_applied or (a.updated_at.date() if a.updated_at else None)
        due = bool(applied and (today() - applied).days >= FOLLOW_UP_AFTER_DAYS and a.id not in done)
        out.append({"application_id": a.id, "company": j.company.name, "title": j.title, "url": j.url,
                    "location": j.location_text, "internship": j.family == "internship",
                    "applied": applied.isoformat() if applied else None, "followed_up": a.id in done, "due": due})
    return out


def approve(db: Session, ids: list[int] | None = None) -> tuple[int, datetime]:
    """Approve the waiting emails (all of them, or the ones listed): each goes out at the next send time."""
    from .mailer import next_send_time
    at = next_send_time()
    q = select(Prospect).where(Prospect.channel == "email", Prospect.status.in_(("ready", "drafted")),
                               Prospect.email.is_not(None))
    if ids:
        q = q.where(Prospect.id.in_(ids))
    n = 0
    for p in db.scalars(q):
        if not (p.subject and p.email_body):
            continue
        p.status, p.send_at, p.approved_at, p.send_error = "scheduled", at, now(), None
        n += 1
    return n, at


def unschedule(db: Session, ids: list[int] | None = None) -> int:
    q = select(Prospect).where(Prospect.status == "scheduled")
    if ids:
        q = q.where(Prospect.id.in_(ids))
    n = 0
    for p in db.scalars(q):
        p.status, p.send_at, p.approved_at = ("drafted" if p.draft_id else "ready"), None, None
        n += 1
    return n


def watch(db: Session) -> list[dict]:
    """Companies you reached out to, for the replies check: their email domains and names."""
    from .replies import _name_terms
    out: dict[int, dict] = {}
    for p in db.scalars(select(Prospect).where(Prospect.status.in_(OPEN + ("replied",)), Prospect.company_id.is_not(None))):
        w = out.setdefault(p.company_id, {"company": p.company_name, "domains": set(), "terms": _name_terms(p.company_name),
                                          "emails": set()})
        d = _domain(p.email)
        if d and d not in FREE_MAIL:
            w["domains"].add(d)
        if p.email:
            w["emails"].add(p.email)
    return [{"company_id": cid, "company": w["company"], "domains": sorted(w["domains"]), "terms": w["terms"],
             "applied": True, "prospect": True, "emails": sorted(w["emails"])} for cid, w in out.items()]


def mark_replied(db: Session, r: EmailReply) -> Prospect | None:
    """A reply from someone you reached out to: from their address, or from their company's domain."""
    sender = (r.from_email or "").lower()
    rows = [p for p in db.scalars(select(Prospect).where(Prospect.status.in_(OPEN)))
            if (p.email and p.email == sender) or (p.company_id and p.company_id == r.company_id)]
    best = next((p for p in rows if p.email == sender), rows[0] if rows else None)
    if best:
        best.status, best.replied_at, best.reply_id = "replied", r.received_at or now(), r.id
    return best


PEOPLE_SEARCH = "https://www.linkedin.com/search/results/people/"
CAMPUS = '(university OR campus OR "early careers" OR "early talent" OR intern)'


def _people(company: str, keywords: str, title: str | None = None) -> str:
    """A LinkedIn people search. The title and company filters narrow it to people whose CURRENT job matches; both
    spellings LinkedIn has used are sent (it ignores the one it doesn't know), and the keywords alone still find
    the right people if the filters are ever dropped."""
    from urllib.parse import quote, urlencode
    params = {"keywords": keywords, "origin": "FACETED_SEARCH"}
    if title:
        params |= {"title": title, "titleFreeText": title, "company": company, "companyFreeText": company}
    return PEOPLE_SEARCH + "?" + urlencode(params, quote_via=quote)


def recruiter_searches(company: str) -> list[dict]:
    """Where to find the person to connect with, best first: campus recruiters there now, then any recruiter there in
    Arizona, then anyone in talent acquisition. LinkedIn orders the people within each search, usually putting
    people you share a connection or school with first."""
    c = (company or "").strip()
    return [{"label": "Campus recruiters", "url": _people(c, f"{c} {CAMPUS} recruiter", "recruiter")},
            {"label": "Any recruiter in Arizona", "url": _people(c, f"{c} recruiter Arizona", "recruiter")},
            {"label": "Talent acquisition", "url": _people(c, f'{c} ("talent acquisition" OR recruiting)')}]


def prospect_dict(p: Prospect) -> dict:
    from .logos import site
    c = p.company
    searches = recruiter_searches(p.company_name) if p.linkedin_url and "/search/results/people" in p.linkedin_url else []
    return {"id": p.id, "company": p.company_name, "company_id": p.company_id, "company_website": site(c),
            "name": p.name, "title": p.title, "email": p.email, "location": p.location,
            "linkedin_url": searches[0]["url"] if searches else p.linkedin_url, "searches": searches,
            "channel": p.channel, "track": p.track, "why": p.why, "source_url": p.source_url, "subject": p.subject,
            "body": p.email_body, "draft_url": p.draft_url, "note": p.note, "followup": p.followup, "status": p.status,
            "batch": p.batch, "sent_at": p.sent_at.isoformat() if p.sent_at else None,
            "replied_at": p.replied_at.isoformat() if p.replied_at else None, "reply_id": p.reply_id,
            "created_at": p.created_at.isoformat() if p.created_at else None, "kind": p.kind or "cold",
            "application_id": p.application_id, "job_title": p.job_title,
            "send_at": p.send_at.isoformat() if p.send_at else None, "send_error": p.send_error,
            "posting_closed": bool(p.posting_closed)}


def counts(db: Session) -> dict:
    out = {s: 0 for s in STATUSES}
    for st in db.scalars(select(Prospect.status)):
        out[st] = out.get(st, 0) + 1
    out["to_send"] = out["ready"] + out["drafted"]
    out["waiting_approval"] = len(list(db.scalars(select(Prospect.id).where(
        Prospect.channel == "email", Prospect.status.in_(("ready", "drafted")), Prospect.email.is_not(None)))))
    out["reached"] = out["sent"] + out["connected"] + out["replied"]
    return out
