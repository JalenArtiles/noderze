"""Company-first workflow: browse companies, one-click apply with keyword tailoring, recruiter outreach, live updates."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Application, Company, Evidence, Job, Person, ResumeVersion, SearchRun
from ..services import prep
from ..services import resume as R
from ..services import writing as W
from ..services.classify import parse_location, sales_level
from ..services.profile import get_profile, master_resume
from ..services.recruiters import import_connections, linkedin_links
from ..services.research import job_brief, person_dict
from ..util import now

router = APIRouter(prefix="/api")
ENTRY = ("entry_sales", "other_sales")


def _presence(c: Company, jobs: list[Job]) -> dict:
    states, regions, remote = set(), set(), False
    for j in jobs:
        li = parse_location(j.location_text, "", j.title)
        states |= set(li.states)
        regions |= set(li.regions)
        remote |= li.remote_type == "remote"
    return {"az": "AZ" in states or bool(c.az_presence), "remote": remote, "socal": "socal" in regions}


@router.get("/company-board")
def company_board(cyber: bool = True, db: Session = Depends(get_db)):
    out = []
    for c in db.scalars(select(Company).where(Company.watch_status.is_not(None), Company.watch_status != "not_relevant")):
        if cyber and c.category != "cybersecurity":
            continue
        jobs = [j for j in c.jobs if j.is_active and not j.hidden]
        entry = sorted([j for j in jobs if j.category in ENTRY], key=lambda j: -(j.score_total or 0))
        se = (c.data or {}).get("se_team") or {}
        n_se = int(se.get("open_se_roles") or 0)
        has_se = n_se > 0 or bool(c.programs) or any(j.family == "direct_se" for j in jobs) or bool(db.scalar(
            select(Evidence.id).where(Evidence.subject_type == "company", Evidence.subject_id == c.id,
                                      Evidence.field.in_(["org.se_team", "org.se_team_live"])).limit(1)))
        pres = _presence(c, jobs)
        focus = 3 * bool(entry) + 2 * has_se + 2 * pres["az"] + pres["remote"] + pres["socal"] + (c.watch_status == "priority")
        out.append({
            "id": c.id, "name": c.name, "website": c.website, "category": c.category, "subcategory": c.subcategory,
            "watch_status": c.watch_status, "az_presence": c.az_presence, "presence": pres,
            "se_team": {"known": has_se, "open_roles": n_se, "sample": se.get("sample", []), "seen": se.get("seen")},
            "entry_roles": [{"id": j.id, "title": j.title, "score": j.score_total, "location": j.location_text,
                             "level": sales_level(j.title), "needs_verification": j.needs_verification} for j in entry[:4]],
            "entry_count": len(entry), "programs": sum(1 for j in jobs if j.category == "program"),
            "goal_roles": sum(1 for j in jobs if j.category == "goal_se"),
            "best": {"id": entry[0].id, "title": entry[0].title, "score": entry[0].score_total} if entry else None,
            "people": db.scalar(select(func.count(Person.id)).where(Person.company_id == c.id)) or 0,
            "focus": focus,
        })
    out.sort(key=lambda x: (-x["focus"], -((x["best"] or {}).get("score") or 0), x["name"]))
    return out


@router.post("/apply/{jid}")
def apply(jid: int, fresh: bool = False, db: Session = Depends(get_db)):
    """One click: tailor the resume to this company's keywords (safe edits pre-approved), render it, and gather
    everything needed to apply and reach a recruiter."""
    job = db.get(Job, jid) or _404()
    res = master_resume(db)
    if not res:
        raise HTTPException(400, "Upload your resume first (Resume page), then click Apply again.")
    prof = get_profile(db).data or {}
    app = prep.ensure_application(db, job)
    claims = sorted(prof.get("verified_claims") or [])
    v = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    reuse = v and not fresh and v.resume_id == res.id and (v.analysis or {}).get("claims") == claims and "ats" in (v.analysis or {})
    if not reuse:
        texts = [j.description_text for j in db.scalars(select(Job).where(Job.company_id == job.company_id, Job.family == "pipeline",
                                                                           Job.id != job.id)) if j.description_text]
        t = R.ats_tailor(res.parsed, res.ledger, prof, res.checks, job.title, job.description_text or "", job.company.name,
                         texts, sales_level(job.title))
        v = ResumeVersion(resume_id=res.id, job_id=job.id, label=f"{job.company.name} - {job.title}"[:290],
                          analysis={"ats": {k: t[k] for k in ("terms", "before", "after")}, "claims": claims},
                          edits=t["edits"])
        db.add(v)
        db.flush()
        app.resume_version_id = v.id
    from ..services import keywords as K
    resume_text = " ".join(f["text"] for f in res.ledger)
    approved = " ".join(e.get("text") or e.get("after") or "" for e in v.edits if e["status"] == "approved")
    ats = dict(v.analysis["ats"])
    ats["after"] = K.coverage(ats["terms"], resume_text + " " + approved)
    out_path = R.render(res.path, v.edits, f"{v.label}-v{v.id}")
    v.output_path, v.status, v.rendered_at = str(out_path), "rendered", now()
    db.commit()
    ctx = prep._ctx(db, job)
    drafts = {}
    for kind in ("recruiter_connect", "sdr_manager", "alumni", "recruiter_followup"):
        msg, _ = W.outreach(kind, {"name": "{first}", "title": None}, ctx)
        drafts[kind] = W.style_check(msg, kind)[0]
    people = [person_dict(p) | {"connection": p.snippet == "linkedin_connection"} for p in db.scalars(
        select(Person).where(Person.company_id == job.company_id, Person.do_not_contact.is_(False)).order_by(Person.priority))]
    return {"job": job_brief(job) | {"description_text": job.description_text}, "application_id": app.id,
            "stage": app.stage, "version_id": v.id, "ats": ats,
            "edits": [{k: e.get(k) for k in ("id", "kind", "category", "status", "flags", "rationale", "find", "replace",
                                             "before", "after", "text", "preview", "auto")} for e in v.edits],
            "drafts": drafts, "people": people, "links": linkedin_links(job.company.name),
            "apply_url": job.apply_url or job.url, "se_team": (job.company.data or {}).get("se_team")}


@router.post("/profile/claims")
def set_claim(body: dict, db: Session = Depends(get_db)):
    """'I have this': you confirm a skill or tool is true for you. Recorded as your own claim, never added silently."""
    term = (body.get("term") or "").strip()
    if not term:
        raise HTTPException(400, "term is required")
    prof = get_profile(db)
    data = dict(prof.data or {})
    claims = [c for c in data.get("verified_claims", []) if c.lower() != term.lower()]
    if body.get("have", True):
        claims.append(term)
    data["verified_claims"] = claims
    prof.data = data
    db.commit()
    return {"verified_claims": claims}


@router.get("/updates")
def updates(since: str | None = None, db: Session = Depends(get_db)):
    t = datetime.fromisoformat(since.replace("Z", "")) if since else None
    q = select(func.count(Job.id)).where(Job.hidden.is_(False))
    new_jobs = db.scalar(q.where(Job.discovered_at > t)) if t else 0
    last = db.scalar(select(SearchRun).where(SearchRun.status != "running").order_by(SearchRun.finished_at.desc()).limit(1))
    running = db.scalar(select(func.count(SearchRun.id)).where(SearchRun.status == "running")) or 0
    alerts = list(db.scalars(select(Alert).where(Alert.seen.is_(False)).order_by(Alert.created_at.desc()).limit(5)))
    from .. import selfupdate
    upd = selfupdate.status()
    return {"now": now().isoformat(), "new_jobs": new_jobs or 0, "running": running,
            "app_update": {"state": upd.get("state"), "step": upd.get("step"), "build_id": upd.get("build_id"),
                           "error": (upd.get("error") or "")[-600:] or None},
            "unseen": db.scalar(select(func.count(Alert.id)).where(Alert.seen.is_(False))) or 0,
            "alerts": [{"id": a.id, "message": a.message, "job_id": a.job_id} for a in alerts],
            "last_run": {"kind": last.kind, "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                         "status": last.status} if last else None}


@router.post("/linkedin/connections")
async def connections(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = (await file.read()).decode("utf-8-sig", errors="ignore")
    result = import_connections(db, text)
    if not result["connections"]:
        raise HTTPException(400, "That doesn't look like LinkedIn's Connections.csv export.")
    return result


@router.get("/companies/{cid}/linkedin")
def company_links(cid: int, db: Session = Depends(get_db)):
    return linkedin_links((db.get(Company, cid) or _404()).name)


def _404():
    raise HTTPException(404, "Not found")
