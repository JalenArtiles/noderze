"""Human-in-the-loop gate. External or high-impact actions run only from an approved Approval row."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Application, ApplicationEvent, Approval, Job, Outreach
from ..util import now
from .profile import get_profile

ACTIONS = {
    "submit_application": "Submit an application",
    "send_message": "Send a LinkedIn message or email",
    "change_resume_fact": "Change a factual item in your profile or resume",
    "claim_qualification": "Claim a qualification",
    "accept_interview": "Accept an interview invitation",
    "reject_opportunity": "Reject or withdraw from an opportunity",
}


def request(db: Session, action: str, summary: str, payload: dict) -> Approval:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action}")
    a = Approval(action=action, summary=summary, payload=payload)
    db.add(a)
    db.commit()
    return a


def decide(db: Session, approval: Approval, approve: bool, note: str | None = None) -> Approval:
    if approval.status != "pending":
        raise ValueError(f"Approval is already {approval.status}")
    approval.status = "approved" if approve else "rejected"
    approval.decided_at, approval.note = now(), note
    db.commit()
    if approve:
        execute(db, approval)
    return approval


def execute(db: Session, a: Approval) -> None:
    """Executors for actions the app performs itself. Submission is executed by the browser runner, which polls."""
    p = a.payload
    try:
        if a.action == "send_message":
            o = db.get(Outreach, p["outreach_id"])
            o.status = "approved"  # the user sends it from LinkedIn or email, then marks it sent
            a.result = {"next": "Copy the approved message, send it yourself, then click Mark sent."}
        elif a.action in ("change_resume_fact", "claim_qualification"):
            prof = get_profile(db)
            data = dict(prof.data or {})
            if a.action == "claim_qualification":
                data.setdefault("verified_claims", []).append(p["claim"])
            else:
                data[p["key"]] = p["value"]
            prof.data = data
            a.status, a.executed_at = "executed", now()
        elif a.action in ("reject_opportunity", "accept_interview"):
            app = db.get(Application, p["application_id"])
            to = "withdrawn" if a.action == "reject_opportunity" else "interview"
            db.add(ApplicationEvent(application_id=app.id, kind="stage", from_stage=app.stage, to_stage=to,
                                    note=a.summary))
            app.stage = to
            if to == "withdrawn":
                db.get(Job, app.job_id).hidden = True
            a.status, a.executed_at = "executed", now()
        db.commit()
    except Exception as e:  # keep the audit trail even when execution fails
        a.status, a.result = "failed", {"error": str(e)}
        db.commit()
