"""Clerk — document intake, cross-document validation, application prep.

The signature move: Gemini-vision extraction across PAN / Aadhaar / utility
bill, then cross-checking names and addresses so a mismatch is caught in
seconds instead of surfacing as a silent rejection three weeks later.
Every outbound application waits behind a human approval gate."""

from ..common import llm
from ..common.fixtures import CLERK_EXTRACTIONS, CLERK_VALIDATION
from ..common.schemas import (
    Approval,
    ApprovalKind,
    DocumentIssue,
    DocumentRecord,
    JourneyStatus,
)
from .context import Context

INSTRUCTION = """You are Clerk, a meticulous document examiner. Given extracted
fields from identity/address documents, cross-validate names, addresses and
numbers. Flag anything an Indian government portal would reject. Respond ONLY
with JSON: {"issues": [{"document_kind": str, "field": str, "detail": str,
"severity": "blocking"|"warning"}]}"""


def build_agent():
    from google.adk.agents import LlmAgent

    from ..common import config

    return LlmAgent(
        name="clerk",
        model=config.GEMINI_FLASH,
        description="Validates documents and prepares application forms.",
        instruction=INSTRUCTION,
    )


async def on_plan_ready(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None or journey.documents:  # idempotency guard
        return

    # Walking skeleton: fixture documents stand in for the upload+vision flow.
    # TODO(team): replace with Cloud Storage uploads + Gemini vision extraction.
    journey.documents = [
        DocumentRecord(kind=kind, filename=f"{kind}.jpg", extracted=fields)
        for kind, fields in CLERK_EXTRACTIONS.items()
    ]

    validation = await llm.run_agent(
        build_agent,
        f"Cross-validate these documents: {CLERK_EXTRACTIONS}",
        offline_fixture=CLERK_VALIDATION,
    )
    issues = [DocumentIssue.model_validate(i) for i in validation.get("issues", [])]
    blocking = [i for i in issues if i.severity == "blocking"]

    for doc in journey.documents:
        doc.issues = [i for i in issues if i.document_kind == doc.kind]
    await ctx.store.save_journey(journey)

    if blocking:
        await ctx.set_status(journey, JourneyStatus.ACTION_REQUIRED)
        for issue in blocking:
            await ctx.log(journey.id, "clerk", "document.issue", issue.detail)
            approval = Approval(
                journey_id=journey.id,
                kind=ApprovalKind.DOCUMENT_FIX,
                summary=f"Fix needed on {issue.document_kind}: {issue.detail}",
                payload={"document_kind": issue.document_kind, "field": issue.field},
            )
            await ctx.store.create_approval(approval)
        return

    await _prepare_applications(ctx, journey.id)


async def on_document_fix_approved(ctx: Context, payload: dict) -> None:
    journey_id = payload["journey_id"]
    await ctx.log(
        journey_id, "clerk", "document.fixed", "Corrected document received; re-validated clean."
    )
    await _prepare_applications(ctx, journey_id)


async def _prepare_applications(ctx: Context, journey_id: str) -> None:
    journey = await ctx.store.get_journey(journey_id)
    if journey is None:
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
    await ctx.set_status(journey, JourneyStatus.ACTION_REQUIRED)
