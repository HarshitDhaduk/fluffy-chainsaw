"""Liaison — everything that crosses the boundary to the government.

Submits approved applications through the portal gateway, watches responses,
parses notices with Gemini, drafts replies, and marks the journey complete
when every registration lands. The 2 AM clarification-notice moment lives
here."""

from datetime import datetime

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
    journey_id = payload["journey_id"]
    req_id = payload["requirement_id"]
    lease_key = f"submit_lease_{req_id}"

    # Claim-then-submit: atomically claim the requirement so a redelivered
    # approval event can never file the same application twice — the
    # "second laptop" guard. The claim carries a lease timestamp: if the
    # holder crashes between claim and record, a redelivery after the lease
    # window reclaims and retries (the portal's own idempotency key makes
    # that retry safe even when the first submit did land).
    def claim(j):
        r = j.requirement(req_id)
        if r is None or r.reference is not None:
            return False
        if r.status == StepStatus.IN_PROGRESS:
            lease = j.meta.get(lease_key)
            if lease and (utcnow() - datetime.fromisoformat(lease)) < config.submit_lease():
                return False  # a live worker holds the claim
            # Stale lease: the holder died mid-submit — reclaim.
        r.status = StepStatus.IN_PROGRESS
        j.meta[lease_key] = utcnow().isoformat()
        return True

    journey, claimed = await ctx.store.mutate_journey(journey_id, claim)
    if journey is None or not claimed:
        return
    req = journey.requirement(req_id)

    ref = await ctx.gateway.submit(
        req.authority, journey_id, req.key, payload.get("application", {})
    )

    def record(j):
        r = j.requirement(req_id)
        if r is not None:
            r.reference = ref
            r.status = StepStatus.WAITING_EXTERNAL

    await ctx.store.mutate_journey(journey_id, record)
    await ctx.set_status(journey_id, JourneyStatus.AWAITING_AUTHORITY)
    await ctx.log(
        journey_id, "liaison", "submission.sent",
        f"{req.title} submitted to {req.authority}. Reference: {ref}.",
    )
    await ctx.bus.publish(
        events.SUBMISSION_SENT, {"journey_id": journey_id, "requirement_id": req_id}
    )


async def on_portal_response(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None:
        return
    req = next((r for r in journey.requirements if r.key == payload["requirement_key"]), None)
    if req is None:
        return

    # Reconcile from external truth: if a crash lost our record of the
    # application reference, the authority's own message carries it. Adopting
    # it here is what lets a journey heal instead of stalling on a filing we
    # can no longer name.
    if not req.reference and payload.get("reference"):
        adopted = payload["reference"]

        def adopt(j):
            r = next((x for x in j.requirements if x.key == payload["requirement_key"]), None)
            if r is not None and not r.reference:
                r.reference = adopted
                r.status = StepStatus.WAITING_EXTERNAL
                return True
            return False

        journey, healed = await ctx.store.mutate_journey(journey.id, adopt)
        if journey is None:
            return
        req = next((r for r in journey.requirements if r.key == payload["requirement_key"]), None)
        if healed:
            await ctx.log(
                journey.id, "liaison", "reference.reconciled",
                f"🛡️ Recovered the {req.authority} reference {adopted} from their own "
                "message — our record was lost mid-filing.",
            )

    kind = payload["kind"]
    if kind == "ack":
        await ctx.log(journey.id, "portal", "portal.ack", f"{req.authority}: {payload['message']}")

    elif kind == "notice":
        # Idempotency claim: at-least-once delivery must not create a second
        # deadline + drafted reply for the same notice.
        notice_key = f"notice_handled_{payload.get('reference', '')}"

        def claim(j):
            if j.meta.get(notice_key):
                return False
            j.meta[notice_key] = True
            return True

        journey, fresh = await ctx.store.mutate_journey(journey.id, claim)
        if journey is None or not fresh:
            return

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
        await ctx.set_status(journey.id, JourneyStatus.ACTION_REQUIRED)
        await ctx.log(
            journey.id, "liaison", "reply.drafted",
            "Reply drafted with supporting documents attached; waiting for your one-tap approval.",
        )
        await ctx.notify(
            journey.id, f"{req.authority} sent a notice — reply drafted",
            f"{parsed.get('summary', payload['message'])} Reply due in "
            f"{deadline_days:.0f} days; one tap to send.",
        )

    elif kind == "approved":
        registration_number = payload.get("registration_number")

        # Concurrent approvals from different authorities race on the same
        # journey document: complete this requirement atomically.
        def complete(j):
            r = next((x for x in j.requirements if x.key == payload["requirement_key"]), None)
            if r is None or r.status == StepStatus.DONE:  # duplicate delivery
                return None
            r.status = StepStatus.DONE
            r.registration_number = registration_number
            return all(x.status == StepStatus.DONE for x in j.requirements)

        journey, all_done = await ctx.store.mutate_journey(journey.id, complete)
        if journey is None or all_done is None:
            return
        await ctx.log(
            journey.id, "portal", "portal.approved",
            f"{req.title} APPROVED. Registration number: {registration_number}.",
        )
        if all_done:
            await ctx.set_status(journey.id, JourneyStatus.COMPLETED)
            await ctx.log(
                journey.id, "liaison", "journey.completed",
                "Every registration granted. Documents archived in the vault. 🎉",
            )
            await ctx.notify(
                journey.id, "Journey complete 🎉",
                "Every registration granted — the numbers are in your vault.",
            )
            await ctx.bus.publish(events.JOURNEY_COMPLETED, {"journey_id": journey.id})


async def on_notice_reply_approved(ctx: Context, payload: dict) -> None:
    journey_id = payload["journey_id"]
    req_id = payload["requirement_id"]

    # Same claim-then-act discipline as submissions: a redelivered approval
    # must not send the authority a second reply.
    def claim(j):
        r = j.requirement(req_id)
        if r is None:
            return None
        key = f"reply_lease_{r.reference or req_id}"
        lease = j.meta.get(key)
        if lease and (utcnow() - datetime.fromisoformat(lease)) < config.submit_lease():
            return None
        j.meta[key] = utcnow().isoformat()
        return r.id

    journey, claimed = await ctx.store.mutate_journey(journey_id, claim)
    if journey is None or claimed is None:
        return
    req = journey.requirement(req_id)

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
    await ctx.set_status(journey.id, JourneyStatus.AWAITING_AUTHORITY)
    await ctx.log(
        journey.id, "liaison", "reply.sent",
        f"Reply sent to {req.authority} well before the deadline.",
    )
