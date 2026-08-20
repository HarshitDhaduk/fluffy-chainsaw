"""Sentinel — the deadline watchdog. Woken by Cloud Scheduler (cloud) or a
loop (local), it scans active deadlines and escalates as clocks run down.
No LLM: a watchdog must be boring and reliable."""

from datetime import datetime

from ..common import config, events
from ..common.schemas import ApprovalKind, ApprovalStatus, JourneyStatus, StepStatus, utcnow
from .context import Context

# Escalation thresholds as fraction of the window remaining.
THRESHOLDS = [0.5, 0.25, 0.0]


# How long a filing may sit with no word from the authority before we stop
# waiting politely and go ask. Expressed in bureaucratic days, so it scales
# with the demo clock.
RESYNC_AFTER_DAYS = 2.5


# After this many sweeps with no progress, stop retrying quietly and tell the
# human we are stuck. Retrying forever in silence is its own kind of failure.
STALL_SWEEPS_BEFORE_ESCALATION = 4


async def on_deadline_tick(ctx: Context, payload: dict) -> None:
    await _watch_deadlines(ctx)
    await _reconcile_stalled_journeys(ctx)


async def _reconcile_stalled_journeys(ctx: Context) -> None:
    """Re-drive journeys that have gone quiet.

    Events get lost, retries get exhausted, a claim outlives the worker that
    took it. Rather than trusting that every message will eventually arrive,
    compare each journey against where it ought to be and re-emit whatever
    would move it forward — the same reconciliation habit a control loop has.
    Every re-emitted event lands on handlers that are already idempotent, so
    re-driving is safe even when the original did arrive."""
    now = utcnow()
    for journey in await ctx.store.list_journeys():
        if journey.status == JourneyStatus.COMPLETED:
            continue
        if now - journey.updated_at < config.days(RESYNC_AFTER_DAYS):
            continue
        # Back off between attempts: a stalled journey is retried
        # periodically, not on every tick of the clock.
        last_sweep = journey.meta.get("last_sweep_at")
        if last_sweep and now - datetime.fromisoformat(last_sweep) < config.days(
            RESYNC_AFTER_DAYS
        ):
            continue

        event, payload = await _next_expected_step(ctx, journey)
        if event is None:
            continue

        def count(j):
            sweeps = int(j.meta.get("stall_sweeps", 0)) + 1
            j.meta["stall_sweeps"] = sweeps
            j.meta["last_sweep_at"] = utcnow().isoformat()
            return sweeps

        _, sweeps = await ctx.store.mutate_journey(journey.id, count)
        await ctx.bus.publish(event, payload)

        if sweeps == STALL_SWEEPS_BEFORE_ESCALATION:
            await ctx.log(
                journey.id, "sentinel", "journey.stalled",
                "⚠️ This journey has not moved despite repeated attempts to "
                "resume it. Flagging for a human rather than retrying in "
                "silence.",
            )
            await ctx.notify(
                journey.id, "A journey is stuck",
                "I have retried without progress and need you to take a look.",
            )


async def _next_expected_step(ctx: Context, journey) -> tuple[str | None, dict]:
    """The one event that would unblock this journey, given its stored state."""
    if not journey.requirements:
        return events.JOURNEY_CREATED, {"journey_id": journey.id}
    if not journey.required_documents:
        return events.REQUIREMENTS_DETERMINED, {"journey_id": journey.id}

    approvals = await ctx.store.list_approvals(journey.id, ApprovalStatus.APPROVED)

    # An approval the human granted whose effect never landed.
    for approval in approvals:
        if approval.kind == ApprovalKind.SUBMISSION:
            req = journey.requirement(approval.payload.get("requirement_id", ""))
            if req is not None and not req.reference:
                return events.APPROVAL_GRANTED, {
                    "journey_id": journey.id,
                    "approval_id": approval.id,
                    "kind": approval.kind,
                    **approval.payload,
                }
        if approval.kind == ApprovalKind.DOCUMENT_FIX and not any(
            a.kind == ApprovalKind.SUBMISSION for a in approvals
        ):
            pending = await ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING)
            if not any(a.kind == ApprovalKind.SUBMISSION for a in pending):
                return events.APPROVAL_GRANTED, {
                    "journey_id": journey.id,
                    "approval_id": approval.id,
                    "kind": approval.kind,
                    **approval.payload,
                }

    # A registration with no gate at all: either validation never produced
    # one, or the write that would have created it failed.
    all_approvals = await ctx.store.list_approvals(journey.id)
    covered = {
        a.payload.get("requirement_id")
        for a in all_approvals
        if a.kind == ApprovalKind.SUBMISSION
    }
    ungated = [
        r for r in journey.requirements
        if r.id not in covered and r.status == StepStatus.PENDING
    ]
    if journey.documents and (not all_approvals or ungated):
        return events.PLAN_READY, {"journey_id": journey.id}

    # Filed and waiting: ask the authority where it stands.
    if any(
        r.status == StepStatus.WAITING_EXTERNAL and r.reference for r in journey.requirements
    ):
        return events.RESYNC_REQUESTED, {"journey_id": journey.id}
    return None, {}


async def _watch_deadlines(ctx: Context) -> None:
    now = utcnow()
    for deadline in await ctx.store.list_active_deadlines():
        total = (deadline.due_at - deadline.created_at).total_seconds()
        remaining = (deadline.due_at - now).total_seconds()
        if total <= 0:
            continue
        fraction = remaining / total

        level = sum(1 for t in THRESHOLDS if fraction <= t)
        if level <= deadline.escalations_sent:
            continue

        deadline.escalations_sent = level
        await ctx.store.save_deadline(deadline)

        if remaining <= 0:
            detail = f"⛔ OVERDUE: “{deadline.label}”. Immediate action required."
        else:
            detail = (
                f"⏰ Deadline approaching: “{deadline.label}” — "
                f"{fraction:.0%} of the reply window remains."
            )
        await ctx.log(deadline.journey_id, "sentinel", "deadline.escalation", detail)
        await ctx.notify(deadline.journey_id, "Deadline warning", detail)
