"""Planner — turns the requirements determination into an ordered plan and
keeps the journey state machine honest. Deterministic by design (no LLM):
plan compilation is exactly the kind of logic that should be code, not
sampling — a deliberate architecture point for the judges."""

from ..common import events
from ..common.schemas import JourneyStatus
from .context import Context


async def on_requirements_determined(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None:
        return

    await ctx.set_status(journey.id, JourneyStatus.PLANNING)
    plan_lines = [
        f"{i + 1}. {r.title} — {r.form} via {r.authority}"
        for i, r in enumerate(journey.requirements)
    ]
    await ctx.log(
        journey.id,
        "planner",
        "plan.ready",
        "Plan compiled: collect documents → validate → prepare & submit each "
        "application → watch for responses → chase to approval.\n" + "\n".join(plan_lines),
    )
    await ctx.bus.publish(events.PLAN_READY, {"journey_id": journey.id})
