from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import scheduler
from ..db import get_db
from ..models import (Alert, AlertRule, Application, CareerPath, Company, Job, Person, Program, SearchRun)
from ..services import careerpath, research
from ..services.actions import best_next_moves, today_actions
from ..services.ats import RawPosting, fetch_single, parse_ats_url
from ..services.classify import GRAD_LABELS, parse_location
from ..services.discovery import upsert_posting, vocabulary
from ..services.evidence import add_evidence, grouped, evidence_for
from ..services.fetch import PoliteFetcher
from ..services.jobs_engine import enrich_and_score, rescore_all
from ..services.llm import llm
from ..services.profile import get_profile
from ..services.scoring import CATEGORY_LABELS, COMPONENT_LABELS, DEFAULT_WEIGHTS, PATH_LABELS
from ..services.search import provider_name
from ..services.similar import similar
from ..services.skills_gap import roadmap
from ..services.standout import recommendations
from ..services.recruiters import alumni_search_url
from ..util import slugify, today
from ..workflows import WORKFLOWS, start

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------------- meta / profile

@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    return {"llm": llm.available, "search_provider": provider_name(), "categories": CATEGORY_LABELS,
            "components": COMPONENT_LABELS, "default_weights": DEFAULT_WEIGHTS, "path_labels": PATH_LABELS,
            "grad_labels": GRAD_LABELS, "vocabulary": vocabulary(db)}


class ProfileIn(BaseModel):
    data: dict | None = None
    weights: dict | None = None


@router.get("/profile")
def read_profile(db: Session = Depends(get_db)):
    p = get_profile(db)
    return {"data": p.data, "weights": p.weights or DEFAULT_WEIGHTS}


@router.put("/profile")
def update_profile(body: ProfileIn, db: Session = Depends(get_db)):
    p = get_profile(db)
    if body.data is not None:
        p.data = body.data
    if body.weights is not None:
        p.weights = {k: float(v) for k, v in body.weights.items() if k in DEFAULT_WEIGHTS}
    db.commit()
    n = rescore_all(db)
    return {"ok": True, "rescored": n}


# ----------------------------------------------------------------------------- dashboard

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    active = select(Job).where(Job.is_active.is_(True), Job.hidden.is_(False))
    jobs = list(db.scalars(active))
    t = today()
    stages = dict(db.execute(select(Application.stage, func.count(Application.id)).group_by(Application.stage)).all())
    runs = list(db.scalars(select(SearchRun).order_by(SearchRun.started_at.desc()).limit(6)))
    return {
        "stats": {
            "target_jobs": sum(1 for j in jobs if j.category != "long_shot"),
            "high_fit": sum(1 for j in jobs if (j.score_total or 0) >= 70),
            "new_today": sum(1 for j in jobs if j.discovered_at and j.discovered_at.date() == t),
            "programs": db.scalar(select(func.count(Program.id))),
            "applications": sum(v for k, v in stages.items() if k not in ("target", "researching")),
            "interviews": sum(v for k, v in stages.items() if "interview" in k),
        },
        "today": today_actions(db), "next_moves": best_next_moves(db),
        "runs": [run_dict(r) for r in runs],
        "alerts": db.scalar(select(func.count(Alert.id)).where(Alert.seen.is_(False))),
        "status": {"llm": llm.available, "search_provider": provider_name()},
    }


# ----------------------------------------------------------------------------- companies & programs

class CompanyIn(BaseModel):
    name: str
    website: str | None = None
    careers_url: str | None = None
    category: str | None = None
    subcategory: str | None = None
    watch_status: str | None = "monitor"
    ats_type: str | None = None
    ats_token: str | None = None


@router.get("/companies")
def list_companies(watch: str | None = None, db: Session = Depends(get_db)):
    q = select(Company).order_by(Company.name)
    if watch:
        q = q.where(Company.watch_status == watch)
    out = []
    for c in db.scalars(q):
        jobs = [j for j in c.jobs if j.is_active and not j.hidden]
        best = max(jobs, key=lambda j: j.score_total or 0, default=None)
        out.append(research.company_dict(c) | {
            "programs": [{"id": p.id, "name": p.name, "target_family": p.target_family, "status": p.status} for p in c.programs],
            "active_jobs": len(jobs), "best_score": best.score_total if best else None,
            "best_path": best.path_class if best else None})
    return out


@router.post("/companies")
def create_company(body: CompanyIn, db: Session = Depends(get_db)):
    if db.scalar(select(Company).where(Company.slug == slugify(body.name))):
        raise HTTPException(409, "Company already exists")
    c = Company(name=body.name, slug=slugify(body.name), **body.model_dump(exclude={"name"}))
    db.add(c)
    db.commit()
    return research.company_dict(c)


@router.patch("/companies/{cid}")
def patch_company(cid: int, body: dict, db: Session = Depends(get_db)):
    c = db.get(Company, cid) or _404()
    allowed = {"watch_status", "watch_note", "ats_type", "ats_token", "ats_host", "ats_site", "careers_url", "website",
               "category", "subcategory", "summary", "data"}
    for k, v in body.items():
        if k in allowed:
            setattr(c, k, v)
    if {"ats_type", "ats_token", "ats_host", "ats_site"} & body.keys():
        c.ats_verified = False
    db.commit()
    return research.company_dict(c)


@router.get("/companies/{cid}")
def company_page(cid: int, db: Session = Depends(get_db)):
    c = db.get(Company, cid) or _404()
    rep = research.company_report(db, c)
    rep["path_summary"] = careerpath.summarize_paths(list(db.scalars(select(CareerPath).where(CareerPath.company_id == c.id))))
    rep["standout"] = recommendations(c)
    rep["alumni_tool_url"] = alumni_search_url(c.name)
    return rep


@router.get("/companies/{cid}/similar")
def company_similar(cid: int, db: Session = Depends(get_db)):
    return similar(db, db.get(Company, cid) or _404())


class FactIn(BaseModel):
    subject_type: str = "company"
    subject_id: int
    field: str
    value: str
    url: str | None = None
    source_type: str | None = None
    confidence: str | None = None


@router.post("/evidence")
def add_fact(body: FactIn, db: Session = Depends(get_db)):
    company = None
    if body.subject_type == "company":
        company = db.get(Company, body.subject_id)
    elif body.subject_type == "program":
        p = db.get(Program, body.subject_id)
        company = p.company if p else None
    ev = add_evidence(db, body.subject_type, body.subject_id, body.field, body.value, url=body.url,
                      source_type=body.source_type or (None if body.url else "inferred"), confidence=body.confidence,
                      company=company, note="Added manually")
    db.commit()
    return {"id": ev.id}


@router.get("/programs")
def list_programs(db: Session = Depends(get_db)):
    out = []
    for p in db.scalars(select(Program).order_by(Program.target_family, Program.name)):
        facts = grouped(evidence_for(db, "program", p.id))
        out.append({"id": p.id, "name": p.name, "company": p.company.name, "company_id": p.company_id,
                    "role_title": p.role_title, "kind": p.kind, "target_family": p.target_family, "status": p.status,
                    "typical_open_window": p.typical_open_window, "summary": p.summary,
                    "watch_status": p.company.watch_status,
                    "headline": {k: (facts.get(k) or [{}])[0].get("value") for k in
                                 ("program.duration", "program.location", "comp.base", "program.next_role")}})
    return out


@router.get("/programs/{pid}")
def program_page(pid: int, db: Session = Depends(get_db)):
    p = db.get(Program, pid) or _404()
    rep = research.company_report(db, p.company)
    prog = next(x for x in rep["programs"] if x["id"] == p.id)
    jobs = [j for j in rep["jobs"] if j["program_id"] == p.id]
    paths = rep["career_paths"]
    return {"program": prog, "company": rep["company"], "jobs": jobs, "career_paths": paths,
            "path_summary": careerpath.summarize_paths(list(db.scalars(select(CareerPath).where(
                CareerPath.company_id == p.company_id)))),
            "standout": recommendations(p.company), "concerns": (p.data or {}).get("concerns", []),
            "field_labels": research.FIELDS, "company_facts": rep["facts"]}


# ----------------------------------------------------------------------------- people & career paths

@router.get("/people")
def list_people(company_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Person).order_by(Person.priority)
    if company_id:
        q = q.where(Person.company_id == company_id)
    out = []
    for p in db.scalars(q):
        d = research.person_dict(p)
        d["company"] = db.get(Company, p.company_id).name if p.company_id else None
        out.append(d)
    return out


class PersonIn(BaseModel):
    company_id: int
    name: str
    title: str | None = None
    linkedin_url: str | None = None
    role_category: str = "other"
    reason: str | None = None


@router.post("/people")
def add_person(body: PersonIn, db: Session = Depends(get_db)):
    if body.linkedin_url and db.scalar(select(Person).where(Person.linkedin_url == body.linkedin_url)):
        raise HTTPException(409, "Already saved")
    p = Person(**body.model_dump(), verified=True, priority={"campus_recruiter": 1, "se_recruiter": 2, "asu_alum": 3}
               .get(body.role_category, 6))
    db.add(p)
    db.commit()
    return research.person_dict(p)


@router.patch("/people/{pid}")
def patch_person(pid: int, body: dict, db: Session = Depends(get_db)):
    p = db.get(Person, pid) or _404()
    for k in ("verified", "do_not_contact", "is_asu_alum", "title", "reason", "role_category"):
        if k in body:
            setattr(p, k, body[k])
    db.commit()
    return research.person_dict(p)


class ProfileTextIn(BaseModel):
    company_id: int
    text: str
    url: str | None = None


@router.post("/career-paths/import")
def import_path(body: ProfileTextIn, db: Session = Depends(get_db)):
    c = db.get(Company, body.company_id) or _404()
    cp = careerpath.import_profile(db, c, body.text, body.url)
    rescore_all(db)
    return research.path_dict(cp)


@router.delete("/career-paths/{pid}")
def delete_path(pid: int, db: Session = Depends(get_db)):
    db.delete(db.get(CareerPath, pid) or _404())
    db.commit()
    rescore_all(db)
    return {"ok": True}


# ----------------------------------------------------------------------------- jobs

def _job_matches(j: Job, state: str | None, remote: bool, industry: str | None, q: str | None, fits: bool) -> bool:
    if fits and j.grad_status in ("too_early", "too_late"):
        return False
    if industry and (j.company.category if j.company else None) != industry:
        return False
    if q and q.lower() not in f"{j.title} {j.company.name if j.company else ''} {j.location_text or ''}".lower():
        return False
    states = {l.get("state") for l in (j.locations or [])}
    if remote and j.remote_type != "remote":
        return False
    if state:
        wanted = set(state.upper().split(","))
        if "SOCAL" in wanted:
            if "socal" not in parse_location(j.location_text, "", j.title).regions:
                return False
        elif not states & wanted:
            return False
    return True


@router.get("/jobs")
def list_jobs(category: str | None = None, company_id: int | None = None, min_score: float = 0,
              include_inactive: bool = False, include_hidden: bool = False, new: bool = False,
              state: str | None = None, remote: bool = False, industry: str | None = None, q: str | None = None,
              fits: bool = False, limit: int = 300, db: Session = Depends(get_db)):
    query = select(Job).where(Job.score_total >= min_score).order_by(Job.score_total.desc())
    if category:
        query = query.where(Job.category.in_(category.split(",")))
    if company_id:
        query = query.where(Job.company_id == company_id)
    if not include_inactive:
        query = query.where(Job.is_active.is_(True))
    if not include_hidden:
        query = query.where(Job.hidden.is_(False))
    if new:
        query = query.where(Job.id.in_(select(Alert.job_id).where(Alert.seen.is_(False))))
    apps = dict(db.execute(select(Application.job_id, Application.stage)).all())
    out = [research.job_brief(j) | {"application_stage": apps.get(j.id), "company_website": j.company.website if j.company else None}
           for j in db.scalars(query) if _job_matches(j, state, remote, industry, q, fits)]
    return out[:limit]


@router.get("/home")
def home(db: Session = Depends(get_db)):
    """Everything the home page needs in one call: best move, interest tiles, top matches, pipeline."""
    prof = get_profile(db).data or {}
    jobs = list(db.scalars(select(Job).where(Job.is_active.is_(True), Job.hidden.is_(False)).order_by(Job.score_total.desc())))
    ok = [j for j in jobs if j.grad_status not in ("too_early", "too_late")]
    states = lambda j: {l.get("state") for l in (j.locations or [])}
    entry = [j for j in ok if j.category == "entry_sales"]
    best = entry[0] if entry else next((j for j in ok if j.category not in ("long_shot", "goal_se")), None)
    regions = lambda j: set(parse_location(j.location_text, "", j.title).regions)
    cyber_cos = [c for c in db.scalars(select(Company).where(Company.category == "cybersecurity", Company.watch_status.is_not(None),
                                                              Company.watch_status != "not_relevant"))]
    with_se = sum(1 for c in cyber_cos if ((c.data or {}).get("se_team") or {}).get("open_se_roles") or c.programs)
    tiles = [
        {"key": "az", "label": "Entry sales in Arizona", "hint": "SDR, BDR, ADR and AE roles near you", "count": sum(1 for j in entry if "AZ" in states(j)), "href": "/opportunities?category=entry_sales&state=AZ", "tone": "maroon"},
        {"key": "remote", "label": "Remote entry sales", "hint": "Work from Arizona", "count": sum(1 for j in entry if j.remote_type == "remote"), "href": "/opportunities?category=entry_sales&remote=1", "tone": "gold"},
        {"key": "socal", "label": "Southern California", "hint": "San Diego, LA, Orange County", "count": sum(1 for j in entry if "socal" in regions(j)), "href": "/opportunities?category=entry_sales&state=SOCAL", "tone": "blue"},
        {"key": "cyber", "label": "Cyber companies with SE teams", "hint": "Where you can grow into SE", "count": with_se, "href": "/companies", "tone": "violet"},
        {"key": "programs", "label": "ASE roles and SE programs", "hint": "Like Verkada's ASE program", "count": sum(1 for j in ok if j.category == "program"), "href": "/opportunities?category=program&fits=0", "tone": "teal"},
        {"key": "goal", "label": "SE roles to grow into", "hint": "Your goal in a year or two", "count": sum(1 for j in jobs if j.category == "goal_se"), "href": "/opportunities?category=goal_se&fits=0", "tone": "slate"},
    ]
    stages = dict(db.execute(select(Application.stage, func.count(Application.id)).group_by(Application.stage)).all())
    return {
        "name": (prof.get("name") or "").split(" ")[0], "best": research.job_brief(best) | {"company_website": best.company.website} if best else None,
        "tiles": tiles, "top": [research.job_brief(j) for j in (entry + [j for j in ok if j.category == "program"])][:6],
        "today": today_actions(db, limit=5), "next_moves": best_next_moves(db)[:3],
        "pipeline": {"Target": stages.get("target", 0) + stages.get("researching", 0), "Preparing": stages.get("preparing", 0),
                     "Applied": stages.get("applied", 0) + stages.get("recruiter_contacted", 0) + stages.get("recruiter_response", 0),
                     "Interviewing": sum(v for k, v in stages.items() if "interview" in k), "Offers": stages.get("offer", 0)},
        "totals": {"jobs": len(ok), "companies": db.scalar(select(func.count(Company.id)).where(Company.watch_status.is_not(None))),
                   "programs": db.scalar(select(func.count(Program.id))), "new": db.scalar(select(func.count(Alert.id)).where(Alert.seen.is_(False)))},
        "status": {"llm": llm.available, "search_provider": provider_name()},
    }


@router.get("/jobs/{jid}")
def job_page(jid: int, db: Session = Depends(get_db)):
    j = db.get(Job, jid) or _404()
    j.seen = True
    for a in db.scalars(select(Alert).where(Alert.job_id == jid)):
        a.seen = True
    db.commit()
    app = db.scalar(select(Application).where(Application.job_id == jid))
    return research.job_brief(j) | {"description_text": j.description_text, "application_id": app.id if app else None,
                                    "standout": recommendations(j.company, j)[:6]}


@router.get("/jobs/{jid}/report")
def job_report(jid: int, db: Session = Depends(get_db)):
    return research.job_report(db, db.get(Job, jid) or _404())


class ManualJobIn(BaseModel):
    company_id: int | None = None
    company_name: str | None = None
    title: str | None = None
    url: str | None = None
    description: str | None = None
    location: str | None = None
    deadline: date | None = None


@router.post("/jobs")
def add_job(body: ManualJobIn, db: Session = Depends(get_db)):
    """Add a job by URL (resolved through the ATS API when possible) or by pasting the posting text."""
    company = db.get(Company, body.company_id) if body.company_id else None
    if company is None and body.company_name:
        company = db.scalar(select(Company).where(Company.slug == slugify(body.company_name)))
        if company is None:
            company = Company(name=body.company_name, slug=slugify(body.company_name), watch_status="monitor")
            db.add(company)
            db.flush()
    if company is None:
        raise HTTPException(400, "company_id or company_name is required")
    parsed = parse_ats_url(body.url) if body.url else None
    if parsed and parsed[0] in ("greenhouse", "lever", "ashby") and parsed[2]:
        f = PoliteFetcher(min_interval=0.5)
        try:
            p = fetch_single(f, parsed[0], parsed[1], parsed[2])
        except Exception:
            p = None
        finally:
            f.close()
        if p:
            job, _ = upsert_posting(db, company, p, original=True)
            if body.deadline:
                job.deadline = body.deadline
            db.commit()
            return research.job_brief(job)
    if not body.title:
        raise HTTPException(400, "Could not read that URL automatically; paste the title and description instead")
    p = RawPosting(title=body.title, url=body.url or "", ats_job_id="", description=body.description or "",
                   location_text=body.location or "", source="manual")
    job, _ = upsert_posting(db, company, p, original=False)
    job.needs_verification = not body.url
    job.deadline = body.deadline
    enrich_and_score(db, job)
    db.commit()
    return research.job_brief(job)


@router.patch("/jobs/{jid}")
def patch_job(jid: int, body: dict, db: Session = Depends(get_db)):
    j = db.get(Job, jid) or _404()
    for k in ("hidden", "deadline", "is_active", "program_id"):
        if k in body:
            setattr(j, k, date.fromisoformat(body[k]) if k == "deadline" and body[k] else body[k])
    enrich_and_score(db, j)
    db.commit()
    return research.job_brief(j)


@router.post("/jobs/rescore")
def rescore(db: Session = Depends(get_db)):
    return {"rescored": rescore_all(db)}


# ----------------------------------------------------------------------------- workflows & runs

class WorkflowIn(BaseModel):
    company_id: int | None = None
    job_id: int | None = None
    company_ids: list[int] | None = None
    rule_id: int | None = None


@router.post("/workflows/{kind}")
def run_workflow(kind: str, body: WorkflowIn, db: Session = Depends(get_db)):
    if kind not in WORKFLOWS:
        raise HTTPException(404, f"Unknown workflow {kind}")
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    needs = {"deep_research": "company_id", "find_recruiters": "company_id", "full_company_analysis": "company_id",
             "prepare_application": "job_id"}
    if kind in needs and needs[kind] not in kwargs:
        raise HTTPException(400, f"{kind} needs {needs[kind]}")
    if kind == "deep_research" and "job_id" in kwargs and "company_id" not in kwargs:
        kwargs["company_id"] = db.get(Job, kwargs["job_id"]).company_id
    allowed = WORKFLOWS[kind].__code__.co_varnames
    kwargs = {k: v for k, v in kwargs.items() if k in allowed}
    subject = None
    if "company_id" in kwargs:
        subject = db.get(Company, kwargs["company_id"]).name
    elif "job_id" in kwargs:
        j = db.get(Job, kwargs["job_id"])
        subject = f"{j.company.name}: {j.title}"
    return {"run_id": start(kind, subject, WORKFLOWS[kind], **kwargs)}


def run_dict(r: SearchRun) -> dict:
    return {"id": r.id, "kind": r.kind, "subject": r.subject, "status": r.status, "error": r.error, "log": r.log,
            "result": r.result, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


@router.get("/runs/{rid}")
def get_run(rid: int, db: Session = Depends(get_db)):
    return run_dict(db.get(SearchRun, rid) or _404())


@router.get("/runs")
def list_runs(limit: int = 30, db: Session = Depends(get_db)):
    return [run_dict(r) for r in db.scalars(select(SearchRun).order_by(SearchRun.started_at.desc()).limit(limit))]


# ----------------------------------------------------------------------------- skills, alerts

@router.get("/skills/roadmap")
def skills(db: Session = Depends(get_db)):
    return roadmap(db)


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)):
    return [{"id": a.id, "message": a.message, "job_id": a.job_id, "seen": a.seen, "created_at": a.created_at.isoformat()}
            for a in db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(100))]


@router.post("/alerts/seen")
def alerts_seen(db: Session = Depends(get_db)):
    for a in db.scalars(select(Alert).where(Alert.seen.is_(False))):
        a.seen = True
    db.commit()
    return {"ok": True}


class RuleIn(BaseModel):
    name: str
    cron: str = "0 7 * * *"
    params: dict = {}
    enabled: bool = True


@router.get("/alert-rules")
def rules(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name, "cron": r.cron, "params": r.params, "enabled": r.enabled,
             "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None} for r in db.scalars(select(AlertRule))]


@router.post("/alert-rules")
def add_rule(body: RuleIn, db: Session = Depends(get_db)):
    r = AlertRule(**body.model_dump())
    db.add(r)
    db.commit()
    scheduler.reload()
    return {"id": r.id}


@router.patch("/alert-rules/{rid}")
def patch_rule(rid: int, body: dict, db: Session = Depends(get_db)):
    r = db.get(AlertRule, rid) or _404()
    for k in ("name", "cron", "params", "enabled"):
        if k in body:
            setattr(r, k, body[k])
    db.commit()
    scheduler.reload()
    return {"ok": True}


def _404():
    raise HTTPException(404, "Not found")
