"""Database schema.

Design rules:
- Every research-derived fact is an Evidence row tied to a Source, with a source_type
  (official / employee_reported / third_party / inferred), a confidence (high / medium / low)
  and timestamps. Pages render facts from Evidence, so nothing appears without provenance.
- Jobs are deduplicated by a fingerprint (posting id, else URL, else company+title).
- External actions (submit, send, change a resume fact, claim a qualification...) only run
  through an Approval row that the user has approved.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .util import now


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # structured profile (see seed/profile.json)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)  # scoring weights, editable in the UI
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    careers_url: Mapped[str | None] = mapped_column(String(500))
    industry: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50))  # cybersecurity | software | ai | cloud_networking | it_solutions | public_safety
    subcategory: Mapped[str | None] = mapped_column(String(200))
    size: Mapped[str | None] = mapped_column(String(100))
    hq: Mapped[str | None] = mapped_column(String(200))
    az_presence: Mapped[str | None] = mapped_column(Text)
    ca_presence: Mapped[str | None] = mapped_column(Text)
    remote_policy: Mapped[str | None] = mapped_column(Text)
    public_sector: Mapped[bool] = mapped_column(Boolean, default=False)
    ats_type: Mapped[str | None] = mapped_column(String(50))  # greenhouse | lever | ashby | smartrecruiters | workday | amazon
    ats_token: Mapped[str | None] = mapped_column(String(200))
    ats_host: Mapped[str | None] = mapped_column(String(300))  # workday host
    ats_site: Mapped[str | None] = mapped_column(String(200))  # workday site
    ats_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    watch_status: Mapped[str | None] = mapped_column(String(30))  # priority | strong | monitor | edge | not_relevant
    watch_note: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # standout ideas, interview notes, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    jobs: Mapped[list[Job]] = relationship(back_populates="company")
    programs: Mapped[list[Program]] = relationship(back_populates="company")


class Program(Base):
    """An early-career program (academy, rotational, associate SE track, sales academy)."""

    __tablename__ = "programs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    role_title: Mapped[str | None] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(50), default="academy")  # academy | rotational | new_grad | internship | sales_academy
    target_family: Mapped[str] = mapped_column(String(30), default="se")  # se | ae | mixed
    official_url: Mapped[str | None] = mapped_column(String(800))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="unknown")  # open | closed | rolling | unknown
    typical_open_window: Mapped[str | None] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    company: Mapped[Company] = relationship(back_populates="programs")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id"))
    title: Mapped[str] = mapped_column(String(400))
    url: Mapped[str | None] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(50), default="manual")  # greenhouse | lever | ashby | workday | search | seed | manual
    source_is_original: Mapped[bool] = mapped_column(Boolean, default=False)
    ats_job_id: Mapped[str | None] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    location_text: Mapped[str | None] = mapped_column(Text)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    remote_type: Mapped[str] = mapped_column(String(20), default="unknown")  # onsite | hybrid | remote | unknown
    remote_scope: Mapped[str | None] = mapped_column(Text)  # e.g. "US", "must reside in Charlotte, NC"
    description_text: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    family: Mapped[str | None] = mapped_column(String(30))  # direct_se | pipeline | technical_entry | other
    is_program: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str | None] = mapped_column(String(30))  # direct_se | program | pipeline | technical_entry | long_shot
    path_class: Mapped[str | None] = mapped_column(String(20))  # DIRECT | LIKELY | POSSIBLE | WEAK
    grad_status: Mapped[str | None] = mapped_column(String(40))
    grad_reason: Mapped[str | None] = mapped_column(Text)
    yoe_min: Mapped[float | None] = mapped_column(Float)
    comp_min: Mapped[float | None] = mapped_column(Float)
    comp_max: Mapped[float | None] = mapped_column(Float)
    comp_period: Mapped[str | None] = mapped_column(String(20))  # year | hour
    comp_note: Mapped[str | None] = mapped_column(Text)
    score_total: Mapped[float | None] = mapped_column(Float)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)  # why it fits / missing / compensate
    flags: Mapped[list] = mapped_column(JSON, default=list)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Company] = relationship(back_populates="jobs")
    program: Mapped[Program | None] = relationship()


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1500), unique=True)
    title: Mapped[str | None] = mapped_column(String(500))
    publisher: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(30))  # official | employee_reported | third_party | inferred
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)  # company | program | job | person
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(100), index=True)  # e.g. program.duration, comp.base, path.transition
    value: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    source_type: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[str] = mapped_column(String(10))  # high | medium | low
    observed_on: Mapped[date | None] = mapped_column(Date)  # date of the underlying info (e.g. posting date)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    source: Mapped[Source | None] = relationship()


class Person(Base):
    """Recruiters, hiring managers, SEs and alumni found in public sources. Never fabricated."""

    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(400))
    linkedin_url: Mapped[str | None] = mapped_column(String(500), unique=True)
    location: Mapped[str | None] = mapped_column(String(200))
    role_category: Mapped[str] = mapped_column(String(40), default="other")
    priority: Mapped[int] = mapped_column(Integer, default=99)
    reason: Mapped[str | None] = mapped_column(Text)
    is_asu_alum: Mapped[str] = mapped_column(String(20), default="unknown")  # yes | possible | unknown | no
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    snippet: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CareerPath(Base):
    """An observed employee progression (from a pasted public profile or a cited source)."""

    __tablename__ = "career_paths"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    label: Mapped[str] = mapped_column(String(100))  # "Employee A"
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{title, company, start, end, family}]
    entry_family: Mapped[str | None] = mapped_column(String(30))
    reaches_se: Mapped[bool] = mapped_column(Boolean, default=False)
    months_to_se: Mapped[int | None] = mapped_column(Integer)
    asu: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    confidence: Mapped[str] = mapped_column(String(10), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(800))
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    ledger: Mapped[list] = mapped_column(JSON, default=list)  # facts the engine may draw on
    checks: Mapped[list] = mapped_column(JSON, default=list)  # consistency / overclaim findings
    is_master: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    label: Mapped[str] = mapped_column(String(300))
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)  # demonstrated / emphasize / missing / should_not_claim
    edits: Mapped[list] = mapped_column(JSON, default=list)  # proposed edits with status + claim-check flags
    output_path: Mapped[str | None] = mapped_column(String(800))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | rendered
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime)


class GeneratedDoc(Base):
    """Cover letters, application answers, interview prep, study guides."""

    __tablename__ = "generated_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved
    generated_by: Mapped[str] = mapped_column(String(20), default="template")  # llm | template
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


STAGES = [
    "researching", "target", "preparing", "applied", "recruiter_contacted", "recruiter_response",
    "interview", "technical_interview", "final_interview", "offer", "rejected", "withdrawn",
]


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    stage: Mapped[str] = mapped_column(String(30), default="target")
    date_found: Mapped[date | None] = mapped_column(Date)
    date_applied: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id"))
    cover_letter_id: Mapped[int | None] = mapped_column(ForeignKey("generated_docs.id"))
    recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    hiring_manager_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    salary_note: Mapped[str | None] = mapped_column(Text)
    location_note: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    readiness: Mapped[dict] = mapped_column(JSON, default=dict)
    package: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    job: Mapped[Job] = relationship()


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # stage | note | outcome
    from_stage: Mapped[str | None] = mapped_column(String(30))
    to_stage: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=now)


class InterviewStage(Base):
    __tablename__ = "interview_stages"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    questions: Mapped[list] = mapped_column(JSON, default=list)  # questions actually asked (feedback loop)
    notes: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(50))


class Outreach(Base):
    __tablename__ = "outreach"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    kind: Mapped[str] = mapped_column(String(40))  # recruiter_connect | recruiter_followup | employee_info | alumni | hiring_manager
    reason: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | sent | replied | no_response
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    response: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    person: Mapped[Person] = relationship()


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected | executed | failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class SearchRun(Base):
    """Every workflow run, with a step log. Doubles as an audit trail."""

    __tablename__ = "search_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    subject: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    log: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # {watch_statuses, categories, min_score, require_program}
    cron: Mapped[str] = mapped_column(String(100), default="0 7 * * *")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    message: Mapped[str] = mapped_column(Text)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LearningResource(Base):
    __tablename__ = "learning_resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    skill_area: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(800))
    cost: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30), default="course")  # course | cert | project | lab
    why: Mapped[str] = mapped_column(Text)  # why it raises the odds of being useful as an SE
