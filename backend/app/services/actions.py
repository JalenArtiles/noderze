"""Prioritized daily actions and the 'best next move' list."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Alert, Application, Approval, Company, InterviewStage, Job, Outreach, Person, Program
from ..util import now, today
from .evidence import evidence_for
from .profile import master_resume
from .skills_gap import roadmap

ACTIVE = ("target", "preparing", "applied", "recruiter_contacted", "recruiter_response", "interview",
          "technical_interview", "final_interview")


def today_actions(db: Session, limit: int = 8) -> list[dict]:
    t = today()
    acts: list[dict] = []

    def add(prio, text, why, link):
        acts.append({"priority": prio, "text": text, "why": why, "link": link})

    for app in db.scalars(select(Application).where(Application.stage.in_(("target", "preparing")),
                                                    Application.deadline.is_not(None))):
        days = (app.deadline - t).days
        if 0 <= days <= 7:
            add(100 - days, f"Apply to {app.job.company.name}: {app.job.title}", f"Closes in {days} day(s).",
                f"/applications/{app.id}")
    for st in db.scalars(select(InterviewStage).where(InterviewStage.scheduled_at.is_not(None),
                                                      InterviewStage.scheduled_at <= now() + timedelta(days=3),
                                                      InterviewStage.scheduled_at >= now())):
        app = db.get(Application, st.application_id)
        add(95, f"Prepare for {st.name} with {app.job.company.name}", "Interview within 3 days.", f"/applications/{app.id}")
    n_appr = db.scalar(select(func.count(Approval.id)).where(Approval.status == "pending")) or 0
    if n_appr:
        add(90, f"Review {n_appr} pending approval(s)", "Nothing external happens until you approve.", "/approvals")
    for app in db.scalars(select(Application).where(Application.follow_up_date.is_not(None),
                                                    Application.follow_up_date <= t, Application.stage.in_(ACTIVE))):
        add(85, f"Follow up on {app.job.company.name}", "Follow-up date reached.", f"/applications/{app.id}")
    for o in db.scalars(select(Outreach).where(Outreach.status == "sent", Outreach.follow_up_date.is_not(None),
                                               Outreach.follow_up_date <= t)):
        add(80, f"Follow up with {o.person.name}", "No reply logged yet.", "/contacts")
    res = master_resume(db)
    if res is None:
        add(88, "Upload your master resume", "Tailoring, readiness and drafts depend on it.", "/resume")
    else:
        for c in res.checks:
            if c["severity"] == "high":
                add(87, "Fix resume: " + c["kind"].replace("_", " "), c["message"][:140], "/resume")
    for p in db.scalars(select(Program).where(Program.status == "open", Program.target_family == "se")):
        has_app = db.scalar(select(Application.id).join(Job).where(Job.program_id == p.id))
        fits = [j for j in db.scalars(select(Job).where(Job.program_id == p.id, Job.is_active.is_(True)))
                if j.grad_status in ("eligible_now", "likely_may_2027", "eligible_closer")]
        if not has_app and fits:  # never say "apply now" to a program whose start date doesn't fit graduation
            add(78, f"Apply now: {p.company.name} {p.name}", fits[0].grad_reason or "Open, and timing fits your graduation.",
                f"/jobs/{fits[0].id}")
    for p in db.scalars(select(Program).where(Program.status != "open", Program.typical_open_window.is_not(None))):
        if any(e.field == "program.open_window" for e in evidence_for(db, "program", p.id)):
            add(40, f"Wait on {p.company.name} {p.name}", f"Typically opens {p.typical_open_window} (sourced).",
                f"/programs/{p.id}")
    unseen = db.scalar(select(func.count(Alert.id)).where(Alert.seen.is_(False))) or 0
    if unseen:
        add(70, f"Review {unseen} new job alert(s)", "From your scheduled scans.", "/opportunities?new=1")
    for job in db.scalars(select(Job).where(Job.is_active.is_(True), Job.hidden.is_(False), Job.score_total >= 65,
                                            Job.category != "long_shot").order_by(Job.score_total.desc()).limit(6)):
        if not db.scalar(select(Application.id).where(Application.job_id == job.id)):
            add(60 + (job.score_total or 0) / 10, f"Prepare application: {job.company.name}, {job.title}",
                f"{job.score_total:.0f}/100 fit, {job.path_class} path.", f"/jobs/{job.id}")
    acts.sort(key=lambda a: -a["priority"])
    return acts[:limit]


def best_next_moves(db: Session) -> list[dict]:
    moves = []
    for c in db.scalars(select(Company).where(Company.watch_status == "priority")):
        people = list(db.scalars(select(Person).where(Person.company_id == c.id).order_by(Person.priority)))
        contacted = db.scalar(select(Outreach.id).join(Person).where(Person.company_id == c.id, Outreach.status.in_(
            ("sent", "replied"))))
        if not people:
            moves.append({"kind": "contact", "text": f"Find recruiters and ASU alumni at {c.name}",
                          "why": "Priority company with no contacts yet.", "link": f"/companies/{c.id}"})
        elif not contacted:
            moves.append({"kind": "contact", "text": f"Message {people[0].name} at {c.name}", "why": people[0].reason or "",
                          "link": "/contacts"})
    rm = roadmap(db)
    if rm["stages"]:
        s = rm["stages"][0]
        moves.append({"kind": "learn", "text": f"{s['stage']}: {s['area']}", "why": s["why"], "link": "/skills"})
    return moves[:6]
