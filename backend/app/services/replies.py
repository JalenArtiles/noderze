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

OFFER = r"\boffer letter\b|pleased to (extend|offer)|offer of employment|(extend|extending) (you )?an offer"
REJECTION = (r"unfortunately|not (be )?moving forward|(move|moving|proceed|go) forward with other|other candidates|"
             r"not selected|position has been filled|will not be proceeding|regret to inform|no longer under consideration|"
             r"after careful (consideration|review)|while your (skills|background|experience|qualifications)|"
             r"(decided|chosen|chose) (not )?to (move|pursue|proceed)|pursue other|not (a )?match for|decided not to")
ASSESSMENT = (r"assessment|coding challenge|hackerrank|codesignal|online test|take[- ]home|skills test|hirevue|"
              r"video interview link")
INTERVIEW = (r"\binterview\b(?! process)|schedule (a|some) (time|call)|phone screen|your availability|availability for|"
             r"calendly|invite you to|set up a (call|time)|meet with (you|our)")
CONFIRMATION = (r"thanks? (you )?for (applying|your application|your interest)|application (has been )?received|"
                r"(we )?(have )?received your application|successfully submitted|application submitted")
SOFT_INTERVIEW = r"next steps|speak with you|chat with you"
# Checked in this order: an offer or a rejection can open with "thank you for applying", and a confirmation often
# promises "next steps" without being an interview invite.
KINDS = [("offer", OFFER), ("rejection", REJECTION), ("assessment", ASSESSMENT), ("interview", INTERVIEW),
         ("confirmation", CONFIRMATION), ("interview", SOFT_INTERVIEW)]
KIND_LABEL = {"offer": "Offer", "rejection": "Not moving forward", "assessment": "Assessment", "interview": "Interview",
              "confirmation": "Application received", "other": "Reply"}
# A company's newsletters, promotions and campus mail aren't replies: an email must be about hiring.
RECRUITING = re.compile(r"\bapplica|\bappl(y|ied|ying)\b|interview|candida|position|\brole\b|recruit|hiring|\boffer\b|"
                        r"assessment|internship|\bjob\b|requisition|onboarding|next steps|your resume|talent", re.I)
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


ROLE_WORDS = re.compile(r"intern|engineer|representative|analyst|associate|specialist|manager|developer|assistant|"
                        r"consultant|coordinator|director|executive|technician|administrator|scientist|designer|"
                        r"program|sales|security|data|spring|summer|fall|winter|20\d\d|remote|hybrid", re.I)


def _title_org(title: str | None) -> str | None:
    """A team or brand named first in a job title ("Y Analytics, Data Analytics ...") is how its emails are signed."""
    head = (title or "").split(",")[0].split(" - ")[0].strip()
    if "," not in (title or "") or not (5 <= len(head) <= 40) or ROLE_WORDS.search(head):
        return None
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]", " ", head.lower())).strip()


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
        org = _title_org(j.title)
        if org and org not in w["terms"]:
            w["terms"].append(org)  # "Y Analytics, Data Analytics and Reporting ..." posted under TPG
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
    # Workday and similar send from the company's own tenant: workiva@myworkday.com is Workiva.
    tenant = re.sub(r"[^a-z0-9]", "", addr.split("@")[0]) if via_ats and "@" in addr else ""
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
            elif tenant and len(tenant) > 2 and tenant == re.sub(r"[^a-z0-9]", "", t):
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
        if not RECRUITING.search(f"{subject} {snippet}"):
            continue  # newsletters, promotions, campus mail
        w = match(it, watch)
        kind = classify(subject, snippet)
        if not w:
            # An application you made outside Noderze ("Thank you for applying to Workiva", or an interview invite from
            # its Workday). Kept so you can track it; interviews, assessments and offers still notify you.
            if kind != "other" and parse_confirmation(subject, name, addr):
                r = EmailReply(message_id=mid, thread_id=it.get("thread_id"), account=it.get("account") or account,
                               from_name=name or None, from_email=addr or None, subject=subject[:2000],
                               snippet=snippet[:2000], url=it.get("url"), received_at=_parse_date(it.get("date")),
                               kind=kind)
                db.add(r)
                db.flush()
                added.append(r)
            continue
        app = _application_for(db, w["company_id"], subject, snippet)
        r = EmailReply(message_id=mid, thread_id=it.get("thread_id"), account=it.get("account") or account,
                       from_name=name or None, from_email=addr or None, subject=subject[:2000], snippet=snippet[:2000],
                       url=it.get("url"), received_at=_parse_date(it.get("date")), company_id=w["company_id"],
                       application_id=app.id if app else None, kind=kind)
        db.add(r)
        db.flush()
        added.append(r)
    return added


CONFIRM_PATTERNS = [
    r"application received for (?P<title>.+?) at (?P<co>.+)$",
    r"your application for (?P<title>.+?) (?:with|at) (?P<co>.+)$",
    r"(?:applying|application|applied) (?:to|with|at) (?P<co>[^,!]+?)(?:,\s*(?P<title>.+?))?[.!]*$",
    r"thank you for applying for (?P<title>.+?) (?:at|with) (?P<co>.+)$",
    r"(?:invitation|invite|message|update|news|note) from (?P<co>.+)$",
]
GENERIC_SENDER = re.compile(r"no-?reply|workday|careers?|recruit|talent|\bhr\b|team|notification|jobs|hiring|"
                            r"people|admin|support|info|greenhouse|lever|icims", re.I)
FREE_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "asu.edu")


def parse_confirmation(subject: str, from_name: str = "", from_email: str = "") -> dict | None:
    """'Thank you for applying to GuidePoint Security, GPSU Internship' -> {company, title}."""
    text = re.sub(r"\s+", " ", subject or "").strip().rstrip("!.")
    for rx in CONFIRM_PATTERNS:
        m = re.search(rx, text, re.I)
        if m and m.group("co").strip():
            co = re.sub(r"^(the)\s+", "", m.group("co").strip(" -:!.,"), flags=re.I)
            title = (m.groupdict().get("title") or "").strip(" -:!.,") or None
            if 1 < len(co) <= 80:
                return {"company": co, "title": title}
    if from_name and not GENERIC_SENDER.search(from_name) and len(from_name) <= 60:
        return {"company": from_name.strip(), "title": None}  # "Kimball Electronics <kei@myworkday.com>"
    if from_email:
        local, _, host = from_email.partition("@")
        if (any(host.endswith(s) for s in ("myworkday.com", "workday.com")) and local.isalpha() and len(local) > 2
                and not GENERIC_SENDER.search(local)):
            return {"company": local.upper() if len(local) <= 5 else local.title(), "title": None}  # oneok@myworkday.com
        d = domain_of(from_email)
        if d and not any(d.endswith(x) for x in ATS_SENDERS + FREE_MAIL):
            return {"company": d.split(".")[0].title(), "title": None}  # talent@acmerobotics.com
    return None


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


def rematch(db: Session) -> int:
    """Emails kept as 'not tracked yet' are matched again whenever the companies you applied to change, so a reply
    joins its application once you track it (or once Noderze learns the brand it's signed with)."""
    watch = watch_list(db)
    n = 0
    for r in db.scalars(select(EmailReply).where(EmailReply.company_id.is_(None), EmailReply.dismissed.is_(False))):
        w = match({"from": f"{r.from_name or ''} <{r.from_email or ''}>", "subject": r.subject, "snippet": r.snippet}, watch)
        if w:
            app = _application_for(db, w["company_id"], r.subject, r.snippet)
            r.company_id, r.application_id = w["company_id"], app.id if app else None
            n += 1
    return n


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
    if rematch(db):
        db.commit()
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


def track(db: Session, r: EmailReply, company: str | None = None, title: str | None = None) -> Application:
    """Turn an application you made outside Noderze into a tracked one (Applied), so its replies are watched."""
    from ..util import slugify
    from .ats import RawPosting
    from .discovery import upsert_posting
    from .jobs_engine import enrich_and_score
    from .prep import FOLLOW_UP_DAYS
    from ..models import ApplicationEvent
    from datetime import timedelta
    parsed = parse_confirmation(r.subject, r.from_name or "", r.from_email or "") or {}
    company = (company or parsed.get("company") or "").strip()
    title = (title or parsed.get("title") or "Application").strip()
    if not company:
        raise ValueError("Add the company name.")
    c = db.scalar(select(Company).where(Company.slug == slugify(company)))
    if c is None:
        sender = domain_of(r.from_email)
        c = Company(name=company, slug=slugify(company), watch_note="Added from an application confirmation email.",
                    website=f"https://{sender}" if sender and not any(sender.endswith(s) for s in ATS_SENDERS) else None)
        db.add(c)
        db.flush()
    job = db.scalar(select(Job).where(Job.company_id == c.id, Job.title == title))
    if job is None:
        p = RawPosting(title=title, url=r.url or "", ats_job_id="", location_text="", description=r.snippet or "",
                       source="manual")
        job, _ = upsert_posting(db, c, p, original=False)
        job.needs_verification = True
        enrich_and_score(db, job)
    a = db.scalar(select(Application).where(Application.job_id == job.id))
    when = r.received_at.date() if r.received_at else None
    if a is None:
        a = Application(job_id=job.id, stage="applied", date_found=when, date_applied=when)
        db.add(a)
        db.flush()
        db.add(ApplicationEvent(application_id=a.id, kind="stage", to_stage="applied", note=f"From an email: {r.subject[:200]}"))
    elif a.stage in PRE_APPLY + ("started",):
        db.add(ApplicationEvent(application_id=a.id, kind="stage", from_stage=a.stage, to_stage="applied"))
        a.stage = "applied"
        a.date_applied = a.date_applied or when
    if a.date_applied and not a.follow_up_date:
        a.follow_up_date = a.date_applied + timedelta(days=FOLLOW_UP_DAYS[0])
    r.company_id, r.application_id, r.seen = c.id, a.id, True
    return a


def reply_dict(db: Session, r: EmailReply) -> dict:
    c = db.get(Company, r.company_id) if r.company_id else None
    a = db.get(Application, r.application_id) if r.application_id else None
    if c is None:  # an application you made outside Noderze
        guess = parse_confirmation(r.subject, r.from_name or "", r.from_email or "") or {}
        return {"id": r.id, "untracked": True, "guess_company": guess.get("company"), "guess_title": guess.get("title"),
                "from_name": r.from_name, "from_email": r.from_email, "subject": r.subject, "snippet": r.snippet,
                "url": r.url, "account": r.account, "kind": r.kind, "kind_label": KIND_LABEL.get(r.kind, "Reply"),
                "received_at": r.received_at.isoformat() if r.received_at else None, "seen": r.seen,
                "company": None, "company_id": None, "application_id": None, "suggest": None}
    return {"untracked": False, "id": r.id, "company": c.name if c else None, "company_id": r.company_id, "application_id": r.application_id,
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
    that you applied. Applications made outside Noderze are listed separately, without a notification."""
    if r.company_id is None:
        return r.kind in ("interview", "assessment", "offer")
    if r.kind != "confirmation":
        return True
    a = db.get(Application, r.application_id) if r.application_id else None
    return bool(a and a.stage in PRE_APPLY + ("started",))


def unseen(db: Session) -> list[EmailReply]:
    rows = db.scalars(select(EmailReply).where(EmailReply.seen.is_(False), EmailReply.dismissed.is_(False))
                      .order_by(EmailReply.received_at.desc()))
    return [r for r in rows if needs_you(db, r)]
