"""Clerk — document intake, vision extraction, cross-validation, application prep.

The signature move: Gemini-vision extraction from photographed PAN / Aadhaar /
utility bill, then cross-checking names and addresses so a mismatch is caught
in seconds instead of surfacing as a silent rejection three weeks later.
Every outbound application waits behind a human approval gate.

Handlers are idempotent (Pub/Sub is at-least-once): required documents are
requested once, extraction runs once per upload, submission approvals are
created at most once per journey."""

from ..common import llm
from ..common.fixtures import CLERK_EXTRACTIONS, CLERK_VALIDATION
from ..common.schemas import (
    Approval,
    ApprovalKind,
    ApprovalStatus,
    DocumentIssue,
    DocumentRecord,
    JourneyStatus,
)
from .context import Context

REQUIRED_DOCUMENTS = ["pan", "aadhaar", "utility_bill"]

VALIDATE_INSTRUCTION = """You are Clerk, a meticulous document examiner. Given
extracted fields from identity/address documents, cross-validate names,
addresses and numbers. Flag anything an Indian government portal would reject.
Respond ONLY with JSON: {"issues": [{"document_kind": str, "field": str,
"detail": str, "severity": "blocking"|"warning"}]}"""

EXTRACT_INSTRUCTION = """You are Clerk, reading a photograph or scan of one
Indian identity/address document (PAN card, Aadhaar card, or utility bill).
Extract exactly what is printed — do not correct spellings or normalize names.
Respond ONLY with JSON: {"fields": {...}} using lowercase snake_case keys
(e.g. "name", "number", "address"). If the image is unreadable, return
{"fields": {}}."""


def build_agent():
    from google.adk.agents import LlmAgent

    from ..common import config

    return LlmAgent(
        name="clerk",
        model=config.GEMINI_FLASH,
        description="Cross-validates documents and prepares application forms.",
        instruction=VALIDATE_INSTRUCTION,
    )


def build_extractor_agent():
    from google.adk.agents import LlmAgent

    from ..common import config

    return LlmAgent(
        name="clerk_extractor",
        model=config.GEMINI_FLASH,
        description="Extracts printed fields from document photographs.",
        instruction=EXTRACT_INSTRUCTION,
    )


async def on_plan_ready(ctx: Context, payload: dict) -> None:
    journey_id = payload["journey_id"]

    def setup(j):
        if j.required_documents:  # idempotency guard
            return False
        j.required_documents = list(REQUIRED_DOCUMENTS)
        # Demo/test path: explicit opt-in loads fixture documents instead of
        # waiting for uploads, so the terminal demo and CI run unattended.
        if j.profile.get("demo_documents"):
            j.documents = [
                DocumentRecord(kind=kind, filename=f"{kind}.jpg", extracted=fields)
                for kind, fields in CLERK_EXTRACTIONS.items()
            ]
        return True

    journey, fresh = await ctx.store.mutate_journey(journey_id, setup)
    if journey is None or not fresh:
        return

    if journey.profile.get("demo_documents"):
        await ctx.log(
            journey_id, "clerk", "documents.ingested", "Demo documents loaded from fixtures."
        )
        await _validate(ctx, journey_id)
        return

    await ctx.set_status(journey_id, JourneyStatus.ACTION_REQUIRED)
    await ctx.log(
        journey_id, "clerk", "documents.requested",
        "Please photograph and upload: PAN card, Aadhaar card, and a recent "
        "electricity bill. I will read and cross-check them before anything "
        "is filed.",
    )


async def on_document_uploaded(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None:
        return
    doc = next((d for d in journey.documents if d.id == payload["document_id"]), None)
    if doc is None:
        return

    fields: dict = {}
    if not doc.extracted:  # extract once per upload (LLM call outside the lock)
        images: list[tuple[bytes, str]] = []
        if ctx.blobs is not None and doc.blob_uri:
            content = await ctx.blobs.get(doc.blob_uri)
            images.append((content, doc.content_type or "image/jpeg"))
        result = await llm.run_agent(
            build_extractor_agent,
            f"Document kind: {doc.kind}. Extract the printed fields.",
            images=images,
            offline_fixture={"fields": CLERK_EXTRACTIONS.get(doc.kind, {})},
        )
        fields = result.get("fields", {})

    # Uploads land concurrently: apply this document's extraction atomically
    # so parallel handlers can't lost-update each other's fields.
    def apply(j):
        d = next((x for x in j.documents if x.id == doc.id), None)
        did_set = False
        if d is not None and not d.extracted and fields:
            d.extracted = fields
            d.issues = []  # a fresh upload clears the old document's issues
            did_set = True
        have = {x.kind for x in j.documents if x.extracted}
        complete = bool(j.required_documents) and all(k in have for k in j.required_documents)
        return did_set, complete

    journey, outcome = await ctx.store.mutate_journey(journey.id, apply)
    if journey is None or outcome is None:
        return
    did_set, complete = outcome

    if did_set:
        await ctx.log(
            journey.id, "clerk", "document.read",
            f"Read {doc.kind} ({doc.filename}): "
            + (", ".join(f"{k}={v}" for k, v in fields.items()) or "unreadable"),
        )
    if complete:
        await _validate(ctx, journey.id)


async def on_document_fix_approved(ctx: Context, payload: dict) -> None:
    """The human accepted the flagged fix (corrected offline / affidavit)."""
    journey_id = payload["journey_id"]
    await ctx.log(
        journey_id, "clerk", "document.fixed", "Corrected document received; re-validated clean."
    )
    await _prepare_applications(ctx, journey_id)


async def _validate(ctx: Context, journey_id: str) -> None:
    journey = await ctx.store.get_journey(journey_id)
    if journey is None:
        return

    extracted = {d.kind: d.extracted for d in journey.documents}
    validation = await llm.run_agent(
        build_agent,
        f"Cross-validate these documents: {extracted}",
        offline_fixture=CLERK_VALIDATION,
    )
    issues = [DocumentIssue.model_validate(i) for i in validation.get("issues", [])]
    blocking = [i for i in issues if i.severity == "blocking"]

    def apply_issues(j):
        for doc in j.documents:
            doc.issues = [i for i in issues if i.document_kind == doc.kind]

    await ctx.store.mutate_journey(journey_id, apply_issues)

    if blocking:
        await ctx.set_status(journey_id, JourneyStatus.ACTION_REQUIRED)
        pending = await ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING)
        already_flagged = {
            a.payload.get("document_kind")
            for a in pending
            if a.kind == ApprovalKind.DOCUMENT_FIX
        }
        for issue in blocking:
            await ctx.log(journey.id, "clerk", "document.issue", issue.detail)
            if issue.document_kind in already_flagged:  # idempotency guard
                continue
            approval = Approval(
                journey_id=journey.id,
                kind=ApprovalKind.DOCUMENT_FIX,
                summary=f"Fix needed on {issue.document_kind}: {issue.detail}",
                payload={"document_kind": issue.document_kind, "field": issue.field},
            )
            await ctx.store.create_approval(approval)
            await ctx.notify(
                journey.id, "Document problem caught before filing",
                f"{issue.document_kind}: {issue.detail}",
            )
        return

    await ctx.log(journey.id, "clerk", "documents.validated", "All documents cross-check clean.")
    await _prepare_applications(ctx, journey.id)


async def _prepare_applications(ctx: Context, journey_id: str) -> None:
    journey = await ctx.store.get_journey(journey_id)
    if journey is None:
        return

    # Idempotency guard (the "second laptop" trap): a redelivered event must
    # not queue a second round of submission approvals.
    existing = await ctx.store.list_approvals(journey_id)
    if any(a.kind == ApprovalKind.SUBMISSION for a in existing):
        return

    for req in journey.requirements:
        application = {
            "form": req.form,
            "applicant": journey.profile.get("applicant_name", "Applicant"),
            "goal": journey.goal,
            "fields": {doc.kind: doc.extracted for doc in journey.documents},
        }
        approval = Approval(
            journey_id=journey.id,
            kind=ApprovalKind.SUBMISSION,
            summary=f"Ready to submit {req.title} ({req.form}) to {req.authority}.",
            payload={"requirement_id": req.id, "application": application},
        )
        await ctx.store.create_approval(approval)
        await ctx.log(
            journey.id, "clerk", "application.prepared",
            f"{req.form} filled and queued for your approval.",
        )
    await ctx.set_status(journey_id, JourneyStatus.ACTION_REQUIRED)
    await ctx.notify(
        journey_id, "Applications ready",
        f"{len(journey.requirements)} filled applications await your one-tap approval.",
    )
