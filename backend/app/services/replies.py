"""Replies: emails from companies you applied to.

Noderze never logs into your email. A scheduled Claude task reads your Gmail through your Claude account's Gmail
connection, and drops recruiting emails as JSON files in data/reply-imports/. Noderze keeps only the ones that match a
company you have an application with, sorts each into a kind (interview, rejection, and so on), and shows them on the
Replies page. Everything else is thrown away.

Noderze also writes data/reply-imports/watch.json: the companies to look for and their email domains, so the task
can search for exactly those.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PRE_APPLY, Application, Company, EmailReply, Job
from ..util import now

log = logging.getLogger("noderze.replies")

# Applicant tracking systems that send mail on a company's behalf: the company name is then in the subject or body.
ATS_SENDERS = ("greenhouse-mail.io", "greenhouse.io", "myworkday.com", "myworkdayjobs.com", "workday.com", "lever.co",
               "hire.lever.co", "icims.com", "smartrecruiters.com", "ashbyhq.com", "jobvite.com", "workablemail.com",
               "successfactors.com", "taleo.net", "breezy.hr", "recruitee.com", "bamboohr.com", "paylocity.com",
               "ultipro.com", "ukg.com", "adp.com", "dayforcehcm.com", "joinhandshake.com", "hirevue.com",
               "codesignal.com", "hackerrank.com", "modernhire.com", "paradox.ai", "phenom.com")
# Generic words that are not a company: a match on these alone would pull in unrelated mail.
GENERIC = {"inc", "llc", "corp", "corporation", "company", "group", "the", "technologies", "technology", "solutions",
           "systems", "security", "networks", "labs", "software", "services", "global", "international", "us", "usa"}

KINDS = [
    ("offer", r"\boffer letter\b|pleased to (extend|offer)|offer of employment|(extend|extending) (you )?an offer"),
    ("rejection", r"unfortunately|not (be )?moving forward|decided to (move|proceed) (forward )?with other|other candidates|"
                  r"not selected|position has been filled|will not be proceeding|regret to inform|no longer under consideration"),
    ("assessment", r"assessment|coding challenge|hackerrank|codesignal|online test|take[- ]home|skills test|hirevue|"
                   r"video interview link|complete the following"),
    ("interview", r"\binterview|schedule (a|some) time|phone screen|availability for|next steps|speak with you|"
                  r"chat with you|set up a (call|time)|calendly|meet with"),
    ("confirmation", r"thank you for (applying|your application|your interest)|application (has been )?received|"
                     r"we (have )?received your application|received your application|successfully submitted"),
]
KIND_LABEL = {"offer": "Offer", "rejection": "Not moving forward", "assessment": "Assessment", "interview": "Interview",
              "confirmation": "Application received", "other": "Reply"}
# Job alerts and newsletters from Handshake and job boards are not replies.
NOISE = re.compile(r"\bjob alert|jobs? (you might|for you|recommended)|new jobs?\b|recommended for you|"
                   r"top (jobs|picks)|weekly digest|is hiring|apply now|events? (near|for) you|webinar|newsletter", re.I)


def folder() -> Path:
    return settings.data_dir / "reply-imports"


def domain_of(url_or_email: str | None) -> str:
    """'https://www.foxcareers.com/x' -> 'foxcareers.com', 'a@mail.fox.com' -> 'fox.com'."""
    if not url_or_email:
        return ""
    host = url_or_email.split("@")[-1] if "@" in url_or_email else (urlparse(url_or_email if "//" in url_or_email
                                                                              else f"//{url_or_email}").hostname or "")
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


# A company's first word alone is only a good search term when it's distinctive: "GuidePoint" is, "Arizona" isn't.
COMMON_FIRST = set("""alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho
illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri
montana nebraska nevada hampshire jersey mexico york carolina dakota ohio oklahoma oregon pennsylvania rhode tennessee
texas utah vermont virginia washington wisconsin wyoming phoenix tempe mesa chandler scottsdale american america united
national general first new global north south east west pacific atlantic digital data cloud smart blue red green black
white golden best city state university college bank capital central western eastern southern northern advanced
applied integrated premier united""".split())


def _name_terms(name: str) -> list[str]:
    """Ways a company is written in mail: 'GuidePoint Security' -> ['guidepoint security', 'guidepoint']."""
    full = re.sub(r"[^a-z0-9& ]", " ", name.lower()).strip()
    full = re.sub(r"\s+", " ", full)
    words = [w for w in full.split() if w not in GENERIC]
    terms = [full] if full else []
    if words and words[0] != full and words[0] not in COMMON_FIRST and (len(words[0]) >= 4 or name.isupper()):
        terms.append(words[0])
    return terms


def watch_list(db: Session) -> list[dict]:
    """Companies with an application, and the email domains they write from."""
    out: dict[int, dict] = {}
    for a in db.scalars(select(Application)):
        j: Job = db.get(Job, a.job_id)
        if j is None or j.company is None:
            continue
        c: Company = j.company
        w = out.setdefault(c.id, {"company": c.name, "domains": set(), "terms": _name_terms(c.name), "stages": set()})
        w["stages"].add(a.stage)
        for d in (domain_of(c.website), domain_of(c.careers_url)):
            if d and not any(d.endswith(s) for s in ATS_SENDERS):
                w["domains"].add(d)
    return [{"company_id": cid, "company": w["company"], "domains": sorted(w["domains"]), "terms": w["terms"],
             "applied": any(s not in PRE_APPLY for s in w["stages"])} for cid, w in out.items()]


def write_watch(db: Session) -> Path:
    """data/reply-imports/watch.json, read by the scheduled Gmail task."""
    f = folder()
    f.mkdir(parents=True, exist_ok=True)
    path = f / "watch.json"
    data = {"updated": now().isoformat(timespec="seconds"), "ats_senders": list(ATS_SENDERS),
            "companies": [{k: w[k] for k in ("company", "domains", "terms", "applied")} for w in watch_list(db)]}
    text = json.dumps(data, indent=1)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def classify(subject: str, snippet: str) -> str:
    text = f"{subject} {snippet}"
    for kind, rx in KINDS:
        if re.search(rx, text, re.I):
            return kind
    return "other"


def _parse_from(value: str | None) -> tuple[str, str]:
    """'FOX Careers <fox_workday_notification@fox.com>' -> ('FOX Careers', 'fox_workday_notification@fox.com')."""
    value = (value or "").strip()
    m = re.match(r'\s*"?([^"<]*?)"?\s*<([^>]+)>', value)
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    return ("", value.lower()) if "@" in value else (value, "")


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return _utc(value / 1000 if value > 1e11 else value)
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        d = parsedate_to_datetime(s)
        return d.replace(tzinfo=None) if d.tzinfo is None else _utc(d.timestamp())
    except (TypeError, ValueError):
        return None


def match(item: dict, watch: list[dict]) -> dict | None:
    """The watched company an email is from, or None. A company's own domain is the strongest sign; mail from an
    applicant tracking system counts only when it names the company; a name in the subject or sender counts too."""
    name, addr = _parse_from(item.get("from"))
    sender_domain = domain_of(addr)
    subject, snippet = item.get("subject") or "", item.get("snippet") or ""
    via_ats = any(sender_domain.endswith(s) or addr.endswith(s) for s in ATS_SENDERS)
    head = f"{name} {subject}".lower()
    body = f"{subject} {snippet}".lower()
    best, score = None, 0
    for w in watch:
        s = 0
        if sender_domain and sender_domain in w["domains"]:
            s = 3
        for t in w["terms"]:
            rx = re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
            if rx.search(head):
                s = max(s, 2)
            elif via_ats and rx.search(body):
                s = max(s, 1)
            elif sender_domain and t.replace(" ", "") in sender_domain.replace("-", ""):
                s = max(s, 2)
        if s > score:
            best, score = w, s
    return best if score >= 1 else None


def import_items(db: Session, items: list[dict], account: str | None = None) -> list[EmailReply]:
    """Keep the emails that match one of your applications. Returns the new replies."""
    watch = watch_list(db)
    added = []
    for it in items:
        mid = str(it.get("id") or it.get("message_id") or "").strip()
        if not mid or db.scalar(select(EmailReply.id).where(EmailReply.message_id == mid)):
            continue
        subject, snippet = (it.get("subject") or "").strip(), (it.get("snippet") or "").strip()
        name, addr = _parse_from(it.get("from"))
        if "joinhandshake.com" in addr and NOISE.search(subject):
            continue  # Handshake job alerts, not a reply
        if NOISE.search(subject) and classify(subject, snippet) == "other":
            continue
        w = match(it, watch)
        if not w:
            continue
        app = _application_for(db, w["company_id"], subject, snippet)
        r = EmailReply(message_id=mid, thread_id=it.get("thread_id"), account=it.get("account") or account,
                       from_name=name or None, from_email=addr or None, subject=subject[:2000], snippet=snippet[:2000],
                       url=it.get("url"), received_at=_parse_date(it.get("date")), company_id=w["company_id"],
                       application_id=app.id if app else None, kind=classify(subject, snippet))
        db.add(r)
        db.flush()
        added.append(r)
    return added


def _application_for(db: Session, company_id: int, subject: str, snippet: str) -> Application | None:
    """The application this email is about: the one whose job title it names, else the furthest along."""
    apps = [a for a in db.scalars(select(Application).join(Job, Job.id == Application.job_id)
                                  .where(Job.company_id == company_id))]
    if not apps:
        return None
    text = f"{subject} {snippet}".lower()
    named = [a for a in apps if a.job and a.job.title and a.job.title.lower()[:40] in text]
    if named:
        return named[0]
    from ..models import STAGES
    return max(apps, key=lambda a: (STAGES.index(a.stage) if a.stage in STAGES else 0, a.updated_at or a.created_at))


def import_dropped(db: Session, path_folder: Path | None = None) -> int:
    """Read data/reply-imports/*.json (except watch.json), keep the matches, move each file to done/."""
    f = path_folder or folder()
    if not f.exists():
        return 0
    n = 0
    for path in sorted(f.glob("*.json")):
        if path.name == "watch.json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raw = {}
        items = raw.get("emails", []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        try:
            added = import_items(db, items, account=raw.get("account") if isinstance(raw, dict) else None)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("reply import failed for %s", path.name)
            added = []
        n += len(added)
        done = f / "done"
        done.mkdir(exist_ok=True)
        # Keep a record of what was checked, without the emails that didn't match anything.
        (done / path.name).write_text(json.dumps({"checked": len(items), "kept": [r.subject for r in added],
                                                  "at": now().isoformat(timespec="seconds"),
                                                  "account": raw.get("account") if isinstance(raw, dict) else None},
                                                 indent=1), encoding="utf-8")
        path.unlink()
    if n:
        log.info("kept %s new replies", n)
    return n


def last_check() -> str | None:
    """When the scheduled task last dropped a file, from the done/ folder."""
    d = folder() / "done"
    if not d.exists():
        return None
    times = [p.stat().st_mtime for p in d.glob("*.json")]
    return _utc(max(times)).isoformat(timespec="seconds") if times else None


def reply_dict(db: Session, r: EmailReply) -> dict:
    c = db.get(Company, r.company_id) if r.company_id else None
    a = db.get(Application, r.application_id) if r.application_id else None
    return {"id": r.id, "company": c.name if c else None, "company_id": r.company_id, "application_id": r.application_id,
            "job_title": a.job.title if a and a.job else None, "stage": a.stage if a else None,
            "from_name": r.from_name, "from_email": r.from_email, "subject": r.subject, "snippet": r.snippet,
            "url": r.url, "account": r.account, "kind": r.kind, "kind_label": KIND_LABEL.get(r.kind, "Reply"),
            "received_at": r.received_at.isoformat() if r.received_at else None, "seen": r.seen,
            "suggest": _suggest(r.kind, a.stage if a else None)}


def _suggest(kind: str, stage: str | None) -> dict | None:
    """One-click stage change that fits the email, if any."""
    if stage is None:
        return None
    if kind == "confirmation" and stage in PRE_APPLY + ("started",):
        return {"stage": "applied", "label": "Mark as applied"}
    if kind in ("interview", "assessment") and stage in PRE_APPLY + ("started", "applied", "recruiter_contacted",
                                                                       "recruiter_response"):
        return {"stage": "interview", "label": "Move to Interviewing"}
    if kind == "rejection" and stage not in ("rejected", "withdrawn"):
        return {"stage": "rejected", "label": "Mark as closed"}
    if kind == "offer" and stage != "offer":
        return {"stage": "offer", "label": "Move to Offer"}
    return None


def needs_you(db: Session, r: EmailReply) -> bool:
    """A reply worth a notification: anything but a plain 'we got your application', unless Noderze doesn't know yet
    that you applied."""
    if r.kind != "confirmation":
        return True
    a = db.get(Application, r.application_id) if r.application_id else None
    return bool(a and a.stage in PRE_APPLY + ("started",))


def unseen(db: Session) -> list[EmailReply]:
    rows = db.scalars(select(EmailReply).where(EmailReply.seen.is_(False), EmailReply.dismissed.is_(False))
                      .order_by(EmailReply.received_at.desc()))
    return [r for r in rows if needs_you(db, r)]
