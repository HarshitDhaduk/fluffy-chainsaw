"""Sentinel — the deadline watchdog. Woken by Cloud Scheduler (cloud) or a
loop (local), it scans active deadlines and escalates as clocks run down.
No LLM: a watchdog must be boring and reliable."""

from ..common.schemas import utcnow
from .context import Context

# Escalation thresholds as fraction of the window remaining.
THRESHOLDS = [0.5, 0.25, 0.0]


async def on_deadline_tick(ctx: Context, payload: dict) -> None:
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
        # TODO(team): fan out to email / push notification channels here.
        await ctx.log(deadline.journey_id, "sentinel", "deadline.escalation", detail)
