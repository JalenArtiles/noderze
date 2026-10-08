"""One-click Prepare Application and the readiness score."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Application, ApplicationEvent, Company, GeneratedDoc, Job, Outreach, Person, ResumeVersion
from ..util import today
from . import resume as R
from . import writing as W
from .evidence import evidence_for
from .profile import get_profile, master_resume
from .standout import recommendations
from .taxonomy import AREA_LABELS, areas_in

FOLLOW_UP_DAYS = (5, 12)


def ensure_application(db: Session, job: Job) -> Application:
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    if not app:
        app = Application(job_id=job.id, stage="preparing", date_found=job.discovered_at.date()
                          if job.discovered_at else today(), deadline=job.deadline)
        db.add(app)
        db.flush()
        db.add(ApplicationEvent(application_id=app.id, kind="stage", to_stage="preparing", note="Prepare application"))
    elif app.stage in ("researching", "target"):
        db.add(ApplicationEvent(application_id=app.id, kind="stage", from_stage=app.stage, to_stage="preparing"))
        app.stage = "preparing"
    return app


def tailor(db: Session, job: Job) -> ResumeVersion | None:
    res = master_resume(db)
    if not res:
        return None
    prof = get_profile(db).data or {}
    analysis = R.analyze(res.ledger, prof, job.title, job.description_text or "", res.checks)
    edits = R.propose_edits(res.parsed, res.ledger, prof, res.checks, job.title, job.description_text or "",
                            job.company.name)
    v = ResumeVersion(resume_id=res.id, job_id=job.id, label=f"{job.company.name} - {job.title}"[:290],
                      analysis=analysis, edits=edits)
    db.add(v)
    db.flush()
    return v


def _ctx(db: Session, job: Job) -> dict:
    res = master_resume(db)
    prof = get_profile(db).data or {}
    company: Company = job.company
    cfacts = [f"{e.field}: {e.value}" for e in evidence_for(db, "company", company.id)]
    if job.program_id:
        cfacts += [f"{e.field}: {e.value}" for e in evidence_for(db, "program", job.program_id)]
    return {"profile": prof, "ledger": res.ledger if res else [], "company": company.name, "company_facts": cfacts,
            "job_title": job.title, "job_text": job.description_text or "", "program": job.program.name if job.program else None,
            "program_line": f"the {job.program.name}" if job.program else None, "analysis": job.analysis,
            "family": job.family, "why_company_fact": (company.data or {}).get("why_line"),
            "product": (company.data or {}).get("product"), "story_hook": prof.get("story_hook")}


def _doc(db: Session, app: Application, job: Job, kind: str, title: str, content: str, by: str, style_kind="answer",
         corpus: str = "", held: set | None = None) -> GeneratedDoc:
    text, flags = W.style_check(content, style_kind)
    flags += W.prose_claim_check(text, corpus, held or set())
    old = db.scalar(select(GeneratedDoc).where(GeneratedDoc.application_id == app.id, GeneratedDoc.kind == kind))
    if old and old.status == "approved":
        return old  # never overwrite something the user approved
    if old:
        old.content, old.flags, old.generated_by, old.title = text, flags, by, title
        return old
    d = GeneratedDoc(kind=kind, job_id=job.id, application_id=app.id, title=title, content=text, flags=flags,
                     generated_by=by)
    db.add(d)
    db.flush()
    return d


def prepare(db: Session, job: Job, log) -> Application:
    app = ensure_application(db, job)
    ctx = _ctx(db, job)
    prof = ctx["profile"]
    corpus = " ".join(f["text"] for f in ctx["ledger"]) + " " + " ".join(str(v) for v in (prof.get("skills") or {}).values())
    held = {(c.get("name") if isinstance(c, dict) else str(c)).lower() for c in prof.get("certifications", [])}
    pkg: dict = {"docs": {}, "outreach": [], "checklist": []}

    v = tailor(db, job)
    if v:
        app.resume_version_id = v.id
        pkg["resume_version_id"] = v.id
        log(f"Resume: {len(v.edits)} proposed edits, {len(v.analysis['missing'])} gaps")
    else:
        log("No master resume uploaded yet; skipped tailoring")

    text, by = W.cover_letter(ctx)
    cl = _doc(db, app, job, "cover_letter", f"Cover letter: {job.company.name}", text, by, "answer", corpus, held)
    cl.flags = [f for f in cl.flags if "characters" not in f]
    app.cover_letter_id = cl.id
    pkg["docs"]["cover_letter"] = cl.id
    for key, q in W.QUESTIONS.items():
        if key == "why_solutions_engineering":
            continue
        text, by = W.answer(key, ctx)
        pkg["docs"][key] = _doc(db, app, job, key, q, text, by, "answer", corpus, held).id

    iq = W.interview_questions(ctx)
    md = "\n\n".join(f"{k.replace('_', ' ').title()}\n" + "\n".join(f"- {q}" for q in qs) for k, qs in iq.items())
    pkg["docs"]["interview_prep"] = _doc(db, app, job, "interview_prep", "Interview preparation", md, "template").id
    pkg["interview_questions"] = iq

    jt = f"{job.title}\n{job.description_text or ''}"
    topics = [AREA_LABELS[a] for a in areas_in(jt, "tech")]
    gaps = [m["requirement"] for m in (job.analysis or {}).get("missing", [])]
    pkg["technical_topics"] = [{"topic": t, "priority": "high" if t in gaps else "review"} for t in topics]

    facts = evidence_for(db, "company", job.company_id) + (evidence_for(db, "program", job.program_id) if job.program_id else [])
    guide = [f"{job.company.name}: {job.company.summary or ''}".strip()]
    guide += [f"- {e.value} ({e.source_type}, {e.confidence})" for e in facts[:30]]
    guide += ["", "Topics to study:"] + [f"- {t['topic']} ({t['priority']})" for t in pkg["technical_topics"]]
    pkg["docs"]["study_guide"] = _doc(db, app, job, "study_guide", f"{job.company.name} study guide", "\n".join(guide),
                                      "template").id

    people = list(db.scalars(select(Person).where(Person.company_id == job.company_id, Person.do_not_contact.is_(False))
                             .order_by(Person.priority).limit(3)))
    for person in people:
        kind = {"campus_recruiter": "recruiter_connect", "se_recruiter": "recruiter_connect", "talent_partner":
                "recruiter_connect", "hiring_manager": "hiring_manager", "asu_alum": "alumni"}.get(person.role_category,
                                                                                              "employee_info")
        if db.scalar(select(Outreach).where(Outreach.person_id == person.id, Outreach.kind == kind)):
            continue
        msg, by = W.outreach(kind, {"name": person.name, "title": person.title}, ctx)
        msg, flags = W.style_check(msg, kind)
        o = Outreach(person_id=person.id, application_id=app.id, kind=kind, message=msg, flags=flags,
                     reason=person.reason)
        db.add(o)
        db.flush()
        pkg["outreach"].append(o.id)

    base = app.date_applied or today()
    pkg["follow_up_schedule"] = [
        {"when": (base + timedelta(days=d)).isoformat(), "what": w} for d, w in
        zip(FOLLOW_UP_DAYS, ["Follow up with the recruiter (short note, one new fact about you)",
                             "Second follow-up or ask an SE contact for advice"])]
    if job.deadline:
        pkg["follow_up_schedule"].insert(0, {"when": (job.deadline - timedelta(days=3)).isoformat(),
                                             "what": "Submit at least 3 days before the deadline"})
    pkg["standout"] = recommendations(job.company, job)[:5]
    app.package = pkg
    app.next_action = app.next_action or "Review resume edits and fill the [bracketed] prompts"
    db.flush()
    app.readiness = readiness(db, app)
    db.commit()
    log(f"Prepared package for {job.company.name}: readiness {app.readiness['overall']}%")
    return app


def readiness(db: Session, app: Application) -> dict:
    job: Job = db.get(Job, app.job_id)
    bd = job.score_breakdown or {}

    def ratio(k):
        c = bd.get(k) or {}
        return round(100 * c.get("score", 0) / c["max"]) if c.get("max") else 50

    v = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    if v:
        a = v.analysis
        total = len(a["demonstrated"]) + len(a["emphasize"]) + len(a["missing"])
        resume_match = round(100 * (len(a["demonstrated"]) + 0.6 * len(a["emphasize"])) / total) if total else 60
        pending_fixes = [e for e in v.edits if e.get("category") == "fix" and e.get("status") == "pending"]
        resume_match = max(0, resume_match - 10 * len(pending_fixes))
    else:
        resume_match, pending_fixes = 0, []
    outreach = list(db.scalars(select(Outreach).join(Person).where(Person.company_id == job.company_id)))
    recruiter = 100 if any(o.status in ("sent", "replied") for o in outreach) else 50 if outreach else 0
    docs = list(db.scalars(select(GeneratedDoc).where(GeneratedDoc.application_id == app.id)))
    unfilled = [d for d in docs if "[" in d.content and d.kind not in ("interview_prep", "study_guide")]
    checklist_state = (app.package or {}).get("checklist_done", {})
    practiced = len((app.package or {}).get("practiced", []))
    interview = min(100, practiced * 20)
    knowledge = min(100, 40 * bool(checklist_state.get("study_guide")) + 30 * bool(checklist_state.get("standout"))
                    + 30 * bool(checklist_state.get("product_walkthrough")))
    req_missing = [m for m in (job.analysis or {}).get("missing", []) if m.get("severity") == "required"]
    missing_score = max(0, 100 - 35 * len(req_missing))
    comps = {"Resume match": resume_match, "Interview readiness": interview, "Technical match": ratio("technical_fit"),
             "Sales match": ratio("sales_leverage"), "Experience match": ratio("eligibility"),
             "Geographic match": ratio("geography"), "Recruiter contact": recruiter, "Company knowledge": knowledge,
             "Missing requirements": missing_score}
    weights = {"Resume match": 0.2, "Interview readiness": 0.1, "Technical match": 0.12, "Sales match": 0.08,
               "Experience match": 0.12, "Geographic match": 0.08, "Recruiter contact": 0.1, "Company knowledge": 0.1,
               "Missing requirements": 0.1}
    overall = round(sum(comps[k] * w for k, w in weights.items()))
    checklist = []
    if not v:
        checklist.append({"key": "upload_resume", "text": "Upload your master resume on the Resume page."})
    if pending_fixes:
        checklist.append({"key": "resume_fixes", "text": f"Approve or reject {len(pending_fixes)} resume fixes (dates, typos, overclaims)."})
    if v and any(e.get("status") == "pending" for e in v.edits):
        checklist.append({"key": "resume_edits", "text": "Review the tailored resume edits and render the version."})
    if unfilled:
        checklist.append({"key": "fill_prompts", "text": f"Fill the [bracketed] prompts in {len(unfilled)} drafts."})
    if recruiter < 100:
        checklist.append({"key": "contact", "text": "Send one recruiter or SE message (drafts are on the Contacts page)."})
    for k, label in [("study_guide", "Read the study guide and note three facts about the product."),
                     ("standout", "Do the top stand-out action for this company."),
                     ("product_walkthrough", "Practice a five-minute product walkthrough out loud.")]:
        if not checklist_state.get(k):
            checklist.append({"key": k, "text": label})
    if practiced < 5:
        checklist.append({"key": "practice", "text": f"Practice {5 - practiced} more interview questions (mock mode)."})
    for m in req_missing:
        checklist.append({"key": "req", "text": f"Required: {m['requirement']}. Decide whether to apply anyway."})
    if not job.is_active or job.needs_verification:
        checklist.append({"key": "verify", "text": "Confirm the posting is still open on the company site."})
    return {"overall": overall, "components": comps, "checklist": checklist}
