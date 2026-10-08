from __future__ import annotations

import shutil
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Base, engine, get_db
from ..models import (STAGES, Application, ApplicationEvent, Approval, Company, GeneratedDoc, InterviewStage, Job,
                      Outreach, Person, Resume, ResumeVersion)
from ..services import approvals as A
from ..services import prep
from ..services import resume as R
from ..services import writing as W
from ..services.jobs_engine import rescore_all
from ..services.llm import llm
from ..services.profile import get_profile, master_resume
from ..services.research import job_brief, person_dict
from ..util import now, slugify, today

router = APIRouter(prefix="/api")


def _404():
    raise HTTPException(404, "Not found")


# ----------------------------------------------------------------------------- resume

@router.post("/resume/upload")
def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Upload a .docx file (export from Word or Google Docs)")
    dest = settings.data_dir / "resumes" / f"master-{now():%Y%m%d%H%M%S}.docx"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return _ingest(db, str(dest), file.filename)


def _ingest(db: Session, path: str, filename: str) -> dict:
    parsed = R.parse_docx(path)
    prof = get_profile(db).data or {}
    for old in db.scalars(select(Resume).where(Resume.is_master.is_(True))):
        old.is_master = False
    res = Resume(filename=filename, path=path, parsed=parsed, ledger=R.build_ledger(parsed),
                 checks=R.consistency_checks(parsed, prof), is_master=True)
    db.add(res)
    db.commit()
    rescore_all(db)
    return resume_dict(res)


def resume_dict(r: Resume) -> dict:
    return {"id": r.id, "filename": r.filename, "uploaded_at": r.uploaded_at.isoformat(), "parsed": r.parsed,
            "ledger": r.ledger, "checks": r.checks}


@router.get("/resume")
def get_resume(db: Session = Depends(get_db)):
    r = master_resume(db)
    versions = list(db.scalars(select(ResumeVersion).order_by(ResumeVersion.created_at.desc())))
    return {"master": resume_dict(r) if r else None,
            "versions": [version_dict(db, v, brief=True) for v in versions]}


def version_dict(db: Session, v: ResumeVersion, brief: bool = False) -> dict:
    job = db.get(Job, v.job_id) if v.job_id else None
    d = {"id": v.id, "label": v.label, "job_id": v.job_id, "status": v.status, "created_at": v.created_at.isoformat(),
         "rendered_at": v.rendered_at.isoformat() if v.rendered_at else None,
         "pending": sum(1 for e in v.edits if e["status"] == "pending"),
         "used_by_application": db.scalar(select(Application.id).where(Application.resume_version_id == v.id)),
         "company": job.company.name if job else None}
    if not brief:
        d |= {"analysis": v.analysis, "edits": v.edits}
    return d


@router.post("/resume/tailor/{jid}")
def tailor(jid: int, db: Session = Depends(get_db)):
    job = db.get(Job, jid) or _404()
    v = prep.tailor(db, job)
    if not v:
        raise HTTPException(400, "Upload a master resume first")
    db.commit()
    return version_dict(db, v)


@router.get("/resume/versions/{vid}")
def get_version(vid: int, db: Session = Depends(get_db)):
    return version_dict(db, db.get(ResumeVersion, vid) or _404())


class EditDecision(BaseModel):
    decision: str  # approve | reject | reset
    acknowledge_flags: bool = False
    after: str | None = None  # user's own wording for replace_paragraph edits


@router.post("/resume/versions/{vid}/edits/{eid}")
def decide_edit(vid: int, eid: str, body: EditDecision, db: Session = Depends(get_db)):
    v = db.get(ResumeVersion, vid) or _404()
    res = db.get(Resume, v.resume_id)
    prof = get_profile(db).data or {}
    edits = [dict(e) for e in v.edits]
    e = next((x for x in edits if x["id"] == eid), None) or _404()
    if body.after is not None and e["kind"] == "replace_paragraph":
        e["after"] = body.after
        e["flags"] = R.claim_check(e["before"], body.after, res.ledger, prof)
    if body.decision == "approve":
        if e.get("flags") and not body.acknowledge_flags:
            raise HTTPException(409, "This edit has claim-check flags. Confirm each is true, then approve with "
                                     "acknowledge_flags=true, or edit the text.")
        e["status"] = "approved"
        e["acknowledged"] = bool(e.get("flags"))
    elif body.decision == "reject":
        e["status"] = "rejected"
    else:
        e["status"] = "pending"
    v.edits = edits
    db.commit()
    return version_dict(db, v)


@router.post("/resume/versions/{vid}/render")
def render(vid: int, db: Session = Depends(get_db)):
    v = db.get(ResumeVersion, vid) or _404()
    res = db.get(Resume, v.resume_id)
    out = R.render(res.path, v.edits, f"{v.label}-v{v.id}")
    v.output_path, v.status, v.rendered_at = str(out), "rendered", now()
    db.commit()
    return version_dict(db, v)


@router.get("/resume/versions/{vid}/download")
def download(vid: int, db: Session = Depends(get_db)):
    v = db.get(ResumeVersion, vid) or _404()
    if not v.output_path:
        raise HTTPException(400, "Render the version first")
    return FileResponse(v.output_path, filename=f"{slugify(v.label)}.docx")


# ----------------------------------------------------------------------------- tracker

@router.get("/applications")
def board(db: Session = Depends(get_db)):
    cols = {s: [] for s in STAGES}
    for a in db.scalars(select(Application).order_by(Application.updated_at.desc())):
        cols.setdefault(a.stage, []).append(app_card(db, a))
    return {"stages": STAGES, "columns": cols}


def app_card(db: Session, a: Application) -> dict:
    j = db.get(Job, a.job_id)
    return {"id": a.id, "stage": a.stage, "company": j.company.name, "title": j.title, "job_id": j.id, "url": j.url,
            "score": j.score_total, "path_class": j.path_class, "deadline": a.deadline.isoformat() if a.deadline else None,
            "follow_up_date": a.follow_up_date.isoformat() if a.follow_up_date else None, "next_action": a.next_action,
            "readiness": (a.readiness or {}).get("overall"), "date_applied": a.date_applied.isoformat() if a.date_applied else None,
            "location": j.location_text, "salary": f"${j.comp_min:,.0f}-{j.comp_max:,.0f}/{j.comp_period}" if j.comp_min else None}


@router.post("/applications")
def add_application(body: dict, db: Session = Depends(get_db)):
    job = db.get(Job, body.get("job_id")) or _404()
    a = db.scalar(select(Application).where(Application.job_id == job.id))
    if not a:
        a = Application(job_id=job.id, stage=body.get("stage", "target"), date_found=today(), deadline=job.deadline)
        db.add(a)
        db.flush()
        db.add(ApplicationEvent(application_id=a.id, kind="stage", to_stage=a.stage))
        db.commit()
    return app_card(db, a)


@router.get("/applications/{aid}")
def application_page(aid: int, db: Session = Depends(get_db)):
    a = db.get(Application, aid) or _404()
    j = db.get(Job, a.job_id)
    docs = list(db.scalars(select(GeneratedDoc).where(GeneratedDoc.application_id == a.id)))
    outreach = list(db.scalars(select(Outreach).where(Outreach.application_id == a.id)))
    events = list(db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == a.id)
                             .order_by(ApplicationEvent.at)))
    stages = list(db.scalars(select(InterviewStage).where(InterviewStage.application_id == a.id)))
    v = db.get(ResumeVersion, a.resume_version_id) if a.resume_version_id else None
    return {"application": app_card(db, a) | {"notes": a.notes, "salary_note": a.salary_note, "package": a.package,
                                             "readiness": a.readiness, "recruiter_id": a.recruiter_id},
            "job": job_brief(j), "docs": [doc_dict(d) for d in docs], "outreach": [outreach_dict(o) for o in outreach],
            "events": [{"kind": e.kind, "from": e.from_stage, "to": e.to_stage, "note": e.note, "at": e.at.isoformat()}
                       for e in events],
            "interviews": [{"id": s.id, "name": s.name, "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
                            "questions": s.questions, "notes": s.notes, "outcome": s.outcome} for s in stages],
            "resume_version": version_dict(db, v) if v else None}


@router.patch("/applications/{aid}")
def patch_application(aid: int, body: dict, db: Session = Depends(get_db)):
    a = db.get(Application, aid) or _404()
    if "stage" in body and body["stage"] != a.stage:
        if body["stage"] not in STAGES:
            raise HTTPException(400, "Unknown stage")
        if body["stage"] in ("applied",) and a.stage in ("target", "preparing", "researching"):
            a.date_applied = a.date_applied or today()
            a.follow_up_date = a.follow_up_date or today() + timedelta(days=prep.FOLLOW_UP_DAYS[0])
        db.add(ApplicationEvent(application_id=a.id, kind="stage", from_stage=a.stage, to_stage=body["stage"],
                                note=body.get("note")))
        a.stage = body["stage"]
    for k in ("notes", "next_action", "salary_note", "location_note", "recruiter_id", "hiring_manager_id"):
        if k in body:
            setattr(a, k, body[k])
    for k in ("follow_up_date", "deadline", "date_applied"):
        if k in body:
            setattr(a, k, date.fromisoformat(body[k]) if body[k] else None)
    if "checklist_done" in body or "practiced" in body:
        pkg = dict(a.package or {})
        if "checklist_done" in body:
            pkg["checklist_done"] = {**pkg.get("checklist_done", {}), **body["checklist_done"]}
        if "practiced" in body:
            pkg["practiced"] = list(dict.fromkeys(pkg.get("practiced", []) + body["practiced"]))
        a.package = pkg
    a.readiness = prep.readiness(db, a)
    db.commit()
    return app_card(db, a)


@router.post("/applications/{aid}/readiness")
def recompute_readiness(aid: int, db: Session = Depends(get_db)):
    a = db.get(Application, aid) or _404()
    a.readiness = prep.readiness(db, a)
    db.commit()
    return a.readiness


@router.post("/applications/{aid}/request")
def request_action(aid: int, body: dict, db: Session = Depends(get_db)):
    """Request approval for submit_application / accept_interview / reject_opportunity."""
    a = db.get(Application, aid) or _404()
    j = db.get(Job, a.job_id)
    action = body.get("action")
    if action == "submit_application":
        v = db.get(ResumeVersion, a.resume_version_id) if a.resume_version_id else None
        flagged = [e for e in (v.edits if v else []) if e.get("status") == "approved" and e.get("flags")]
        unfilled = [d.title for d in db.scalars(select(GeneratedDoc).where(GeneratedDoc.application_id == a.id))
                    if "[" in d.content and d.kind in ("cover_letter", "why_company", "why_role")]
        summary = f"Submit application to {j.company.name}: {j.title}"
        payload = {"application_id": a.id, "job_url": j.apply_url or j.url,
                   "resume_path": v.output_path if v else None, "cover_letter_id": a.cover_letter_id,
                   "unverified_claims": len(flagged), "unfilled_drafts": unfilled}
        if unfilled:
            raise HTTPException(409, f"Fill the [bracketed] prompts first: {', '.join(unfilled)}")
    else:
        summary = {"accept_interview": f"Accept interview with {j.company.name}",
                   "reject_opportunity": f"Withdraw from {j.company.name}: {j.title}"}.get(action) or _404()
        payload = {"application_id": a.id}
    ap = A.request(db, action, summary, payload)
    return {"approval_id": ap.id}


class InterviewIn(BaseModel):
    name: str
    scheduled_at: str | None = None
    questions: list[str] = []
    notes: str | None = None
    outcome: str | None = None


@router.post("/applications/{aid}/interviews")
def add_interview(aid: int, body: InterviewIn, db: Session = Depends(get_db)):
    from datetime import datetime
    s = InterviewStage(application_id=aid, name=body.name, questions=body.questions, notes=body.notes,
                       outcome=body.outcome, scheduled_at=datetime.fromisoformat(body.scheduled_at) if body.scheduled_at else None)
    db.add(s)
    db.commit()
    return {"id": s.id}


class MockIn(BaseModel):
    question: str
    answer: str


@router.post("/applications/{aid}/mock")
def mock(aid: int, body: MockIn, db: Session = Depends(get_db)):
    a = db.get(Application, aid) or _404()
    j = db.get(Job, a.job_id)
    pkg = dict(a.package or {})
    pkg["practiced"] = list(dict.fromkeys(pkg.get("practiced", []) + [body.question]))
    a.package = pkg
    a.readiness = prep.readiness(db, a)
    db.commit()
    style = (get_profile(db).data or {}).get("interview_style", "")
    if llm.available:
        fb = llm.text("You are an SE hiring manager running a mock interview. Give specific, honest feedback in under "
                      "150 words: what worked, what was missing, and a stronger structure. No em dashes.",
                      f"Company: {j.company.name}\nRole: {j.title}\nCandidate's preferred style: {style}\n"
                      f"Question: {body.question}\nAnswer: {body.answer}")
        if fb:
            return {"feedback": fb, "by": "llm"}
    words = len(body.answer.split())
    tips = []
    if words < 60:
        tips.append("Too short for most interview answers; aim for 60 to 150 words or about one minute.")
    if words > 220:
        tips.append("Long; tighten to the situation, what you did, and the result.")
    if not any(w in body.answer.lower() for w in ("i ", "i'", "my ")):
        tips.append("Say what you did, in first person.")
    if not any(ch.isdigit() for ch in body.answer):
        tips.append("If you have a real number (calls, meetings, floors scanned), use it.")
    if j.company.name.lower() not in body.answer.lower() and "why" in body.question.lower():
        tips.append(f"Tie it back to {j.company.name} specifically.")
    if style:
        tips.append(f"Your stated style: {style}")
    return {"feedback": " ".join(tips) or "Solid structure. Practice it out loud once more.", "by": "rubric"}


# ----------------------------------------------------------------------------- documents

def doc_dict(d: GeneratedDoc) -> dict:
    return {"id": d.id, "kind": d.kind, "title": d.title, "content": d.content, "flags": d.flags, "status": d.status,
            "generated_by": d.generated_by, "updated_at": d.updated_at.isoformat()}


@router.patch("/docs/{did}")
def patch_doc(did: int, body: dict, db: Session = Depends(get_db)):
    d = db.get(GeneratedDoc, did) or _404()
    if "content" in body:
        res = master_resume(db)
        prof = get_profile(db).data or {}
        corpus = " ".join(f["text"] for f in (res.ledger if res else [])) + " " + " ".join(
            str(v) for v in (prof.get("skills") or {}).values())
        held = {(c.get("name") if isinstance(c, dict) else str(c)).lower() for c in prof.get("certifications", [])}
        d.content, flags = W.style_check(body["content"], "answer")
        d.flags = [f for f in flags if "characters" not in f or d.kind != "cover_letter"] + W.prose_claim_check(
            d.content, corpus, held)
        d.status = "draft"
    if body.get("status") == "approved":
        if any("[" in d.content for _ in [0]):
            raise HTTPException(409, "Fill the [bracketed] prompts before approving")
        d.status = "approved"
    db.commit()
    return doc_dict(d)


# ----------------------------------------------------------------------------- outreach

def outreach_dict(o: Outreach) -> dict:
    return {"id": o.id, "person": person_dict(o.person), "kind": o.kind, "reason": o.reason, "message": o.message,
            "flags": o.flags, "status": o.status, "approval_id": o.approval_id, "application_id": o.application_id,
            "sent_at": o.sent_at.isoformat() if o.sent_at else None, "response": o.response, "outcome": o.outcome,
            "follow_up_date": o.follow_up_date.isoformat() if o.follow_up_date else None}


@router.get("/outreach")
def list_outreach(db: Session = Depends(get_db)):
    return [outreach_dict(o) for o in db.scalars(select(Outreach).order_by(Outreach.created_at.desc()))]


class OutreachIn(BaseModel):
    person_id: int
    kind: str
    job_id: int | None = None


@router.post("/outreach/generate")
def generate_outreach(body: OutreachIn, db: Session = Depends(get_db)):
    person = db.get(Person, body.person_id) or _404()
    if person.do_not_contact:
        raise HTTPException(409, "Marked do-not-contact")
    prior = list(db.scalars(select(Outreach).where(Outreach.person_id == person.id, Outreach.status.in_(("sent", "replied")))))
    if prior and body.kind not in ("recruiter_followup",):
        raise HTTPException(409, f"You already messaged {person.name} on {prior[-1].sent_at:%b %d}. "
                                 f"Generate a follow-up instead, or log their reply.")
    company = db.get(Company, person.company_id)
    job = db.get(Job, body.job_id) if body.job_id else db.scalar(
        select(Job).where(Job.company_id == company.id, Job.is_active.is_(True)).order_by(Job.score_total.desc()))
    ctx = prep._ctx(db, job) if job else {"profile": get_profile(db).data or {}, "ledger": (master_resume(db).ledger
                                         if master_resume(db) else []), "company": company.name, "job_title": None,
                                         "job_text": "", "program": None, "company_facts": []}
    msg, _ = W.outreach(body.kind, {"name": person.name, "title": person.title}, ctx)
    msg, flags = W.style_check(msg, body.kind)
    app_id = db.scalar(select(Application.id).where(Application.job_id == job.id)) if job else None
    o = Outreach(person_id=person.id, application_id=app_id, kind=body.kind, message=msg, flags=flags, reason=person.reason)
    db.add(o)
    db.commit()
    return outreach_dict(o)


@router.patch("/outreach/{oid}")
def patch_outreach(oid: int, body: dict, db: Session = Depends(get_db)):
    o = db.get(Outreach, oid) or _404()
    if "message" in body:
        o.message, o.flags = W.style_check(body["message"], o.kind)
        o.status = "draft"
    if body.get("request_send"):
        ap = A.request(db, "send_message", f"Send {o.kind.replace('_', ' ')} to {o.person.name}",
                       {"outreach_id": o.id, "message": o.message})
        o.approval_id = ap.id
    if body.get("mark_sent"):
        if o.status != "approved":
            raise HTTPException(409, "Approve the message first (Approvals page)")
        o.status, o.sent_at = "sent", now()
        o.follow_up_date = today() + timedelta(days=7)
        if o.application_id:
            a = db.get(Application, o.application_id)
            if a.stage in ("target", "preparing", "applied"):
                db.add(ApplicationEvent(application_id=a.id, kind="stage", from_stage=a.stage, to_stage="recruiter_contacted"))
                a.stage = "recruiter_contacted"
    for k in ("response", "outcome"):
        if k in body:
            setattr(o, k, body[k])
            if k == "response" and body[k]:
                o.status = "replied"
    db.commit()
    return outreach_dict(o)


# ----------------------------------------------------------------------------- approvals

@router.get("/approvals")
def list_approvals(status: str | None = None, db: Session = Depends(get_db)):
    q = select(Approval).order_by(Approval.created_at.desc())
    if status:
        q = q.where(Approval.status == status)
    return [{"id": a.id, "action": a.action, "label": A.ACTIONS.get(a.action), "summary": a.summary, "payload": a.payload,
             "status": a.status, "created_at": a.created_at.isoformat(), "note": a.note, "result": a.result}
            for a in db.scalars(q)]


@router.post("/approvals/{apid}/decide")
def decide(apid: int, body: dict, db: Session = Depends(get_db)):
    ap = db.get(Approval, apid) or _404()
    try:
        A.decide(db, ap, bool(body.get("approve")), body.get("note"))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"status": ap.status, "result": ap.result}


# ----------------------------------------------------------------------------- data control

@router.get("/export")
def export(db: Session = Depends(get_db)):
    out = {}
    for table in Base.metadata.sorted_tables:
        rows = db.execute(table.select()).mappings().all()
        out[table.name] = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]
    return out


@router.delete("/data")
def wipe(confirm: str = "", db: Session = Depends(get_db)):
    if confirm != "DELETE EVERYTHING":
        raise HTTPException(400, "Pass confirm=DELETE EVERYTHING")
    db.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    shutil.rmtree(settings.data_dir / "resumes", ignore_errors=True)
    (settings.data_dir / "resumes").mkdir(exist_ok=True)
    return {"ok": True}
