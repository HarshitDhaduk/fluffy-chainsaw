"""Shared domain models. Every fact agents exchange lives in these shapes,
persisted in the Store — agents never hold private state."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class JourneyStatus(StrEnum):
    INTAKE = "intake"
    RESEARCHING = "researching"
    PLANNING = "planning"
    ACTION_REQUIRED = "action_required"  # waiting on the human (approval / fix)
    AWAITING_AUTHORITY = "awaiting_authority"  # waiting on the government
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_EXTERNAL = "waiting_external"
    DONE = "done"
    FAILED = "failed"


class Requirement(BaseModel):
    """One registration/license the Pathfinder determined applies."""

    id: str = Field(default_factory=lambda: new_id("req"))
    key: str  # e.g. "fssai_basic", "gst", "udyam"
    title: str
    authority: str  # e.g. "FoSCoS", "GST Network"
    form: str  # e.g. "Form A", "GST REG-01"
    why: str  # plain-language rationale shown to the user
    citations: list[str] = []
    status: StepStatus = StepStatus.PENDING
    reference: str | None = None  # ARN / application ref once submitted
    registration_number: str | None = None  # the prize, once granted


class DocumentIssue(BaseModel):
    document_kind: str
    field: str
    detail: str
    severity: str = "blocking"  # blocking | warning


class DocumentRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    kind: str  # pan | aadhaar | utility_bill | photo | ...
    filename: str
    content_type: str | None = None
    blob_uri: str | None = None  # mem:// locally, gs:// in cloud
    extracted: dict = {}
    issues: list[DocumentIssue] = []


class ApprovalKind(StrEnum):
    DOCUMENT_FIX = "document_fix"
    SUBMISSION = "submission"
    NOTICE_REPLY = "notice_reply"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Approval(BaseModel):
    """Human-in-the-loop gate. Nothing leaves LalFita without one of these."""

    id: str = Field(default_factory=lambda: new_id("apr"))
    journey_id: str
    kind: ApprovalKind
    summary: str
    payload: dict = {}
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class Deadline(BaseModel):
    """A ticking clock the Sentinel watches (e.g. 7 days to answer a notice)."""

    id: str = Field(default_factory=lambda: new_id("ddl"))
    journey_id: str
    label: str
    due_at: datetime
    created_at: datetime = Field(default_factory=utcnow)
    resolved: bool = False
    escalations_sent: int = 0


class TimelineEntry(BaseModel):
    ts: datetime = Field(default_factory=utcnow)
    actor: str  # pathfinder | planner | clerk | liaison | sentinel | user | portal
    event: str
    detail: str


class Journey(BaseModel):
    id: str = Field(default_factory=lambda: new_id("jrn"))
    goal: str
    profile: dict = {}  # intake answers: turnover, premises, channels, ...
    status: JourneyStatus = JourneyStatus.INTAKE
    requirements: list[Requirement] = []
    required_documents: list[str] = []  # kinds Clerk is waiting for
    documents: list[DocumentRecord] = []
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def requirement(self, req_id: str) -> Requirement | None:
        return next((r for r in self.requirements if r.id == req_id), None)
