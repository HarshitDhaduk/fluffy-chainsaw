"""Liaison — everything that crosses the boundary to the government.

Submits approved applications through the portal gateway, watches responses,
parses notices with Gemini, drafts replies, and marks the journey complete
when every registration lands. The 2 AM clarification-notice moment lives
here."""

from ..common import config, events, llm
from ..common.fixtures import LIAISON_NOTICE_PARSE
from ..common.schemas import (
    Approval,
    ApprovalKind,
    Deadline,
    JourneyStatus,
    StepStatus,
    utcnow,
)
from .context import Context

INSTRUCTION = """You are Liaison, handling correspondence with Indian government
portals. Given a notice from an authority, classify it and draft a reply.
Respond ONLY with JSON: {"notice_type": str, "summary": str,
"reply_deadline_days": int, "draft_reply": str, "attachments": [str]}"""


def build_agent():
    from google.adk.agents import LlmAgent

    return LlmAgent(
        name="liaison",
        model=config.GEMINI_FLASH,
        description="Submits applications and handles authority correspondence.",
        instruction=INSTRUCTION,
    )


async def on_submission_approved(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    req = journey.requirement(payload["requirement_id"]) if journey else None
    if journey is None or req is None or req.reference:  # idempotency guard
        return

    ref = await ctx.gateway.submit(
        req.authority, journey.id, req.key, payload.get("application", {})
    )
    req.reference = ref
    req.status = StepStatus.WAITING_EXTERNAL
    await ctx.store.save_journey(journey)
    await ctx.set_status(journey, JourneyStatus.AWAITING_AUTHORITY)
    await ctx.log(
        journey.id, "liaison", "submission.sent",
        f"{req.title} submitted to {req.authority}. Reference: {ref}.",
    )
    await ctx.bus.publish(
        events.SUBMISSION_SENT, {"journey_id": journey.id, "requirement_id": req.id}
    )


async def on_portal_response(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None:
        return
    req = next((r for r in journey.requirements if r.key == payload["requirement_key"]), None)
    if req is None:
        return

    kind = payload["kind"]
    if kind == "ack":
        await ctx.log(journey.id, "portal", "portal.ack", f"{req.authority}: {payload['message']}")

    elif kind == "notice":
        await ctx.log(
            journey.id, "portal", "portal.notice",
            f"{req.authority} clarification notice on {req.reference}: {payload['message']}",
        )
        parsed = await llm.run_agent(
            build_agent,
            f"Notice from {req.authority} re {req.reference}: {payload['message']}",
            offline_fixture=LIAISON_NOTICE_PARSE,
        )
        deadline_days = float(parsed.get("reply_deadline_days", 7))
        deadline = Deadline(
            journey_id=journey.id,
            label=f"Reply to {req.authority} notice on {req.reference}",
            due_at=utcnow() + config.days(deadline_days),
        )
        await ctx.store.create_deadline(deadline)

        draft = parsed.get("draft_reply", "").replace("{ref}", req.reference or "")
        approval = Approval(
            journey_id=journey.id,
            kind=ApprovalKind.NOTICE_REPLY,
            summary=(
                f"Drafted reply to {req.authority} notice ({parsed.get('summary', '')}) — "
                f"due in {deadline_days:.0f} days."
            ),
            payload={
                "requirement_id": req.id,
                "deadline_id": deadline.id,
                "reply": draft,
                "attachments": parsed.get("attachments", []),
            },
        )
        await ctx.store.create_approval(approval)
        await ctx.set_status(journey, JourneyStatus.ACTION_REQUIRED)
        await ctx.log(
            journey.id, "liaison", "reply.drafted",
            "Reply drafted with supporting documents attached; waiting for your one-tap approval.",
        )

    elif kind == "approved":
        req.status = StepStatus.DONE
        req.registration_number = payload.get("registration_number")
        await ctx.store.save_journey(journey)
        await ctx.log(
            journey.id, "portal", "portal.approved",
            f"{req.title} APPROVED. Registration number: {req.registration_number}.",
        )
        if all(r.status == StepStatus.DONE for r in journey.requirements):
            await ctx.set_status(journey, JourneyStatus.COMPLETED)
            await ctx.log(
                journey.id, "liaison", "journey.completed",
                "Every registration granted. Documents archived in the vault. 🎉",
            )
            await ctx.bus.publish(events.JOURNEY_COMPLETED, {"journey_id": journey.id})


async def on_notice_reply_approved(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    req = journey.requirement(payload["requirement_id"]) if journey else None
    if journey is None or req is None:
        return

    await ctx.gateway.reply(
        req.authority, req.reference or "", journey.id, req.key,
        {"reply": payload.get("reply", ""), "attachments": payload.get("attachments", [])},
    )
    if payload.get("deadline_id"):
        deadlines = await ctx.store.list_active_deadlines()
        for d in deadlines:
            if d.id == payload["deadline_id"]:
                d.resolved = True
                await ctx.store.save_deadline(d)
    await ctx.set_status(journey, JourneyStatus.AWAITING_AUTHORITY)
    await ctx.log(
        journey.id, "liaison", "reply.sent",
        f"Reply sent to {req.authority} well before the deadline.",
    )
