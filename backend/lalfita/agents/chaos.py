"""Chaos — the crash-recovery showpiece (F10).

Judges hear 'the journey survives crashes'; this makes them SEE it. On the
first delivery of demo.crash we record the drill in Firestore and kill the
process before acking — exactly the failure mode of the 'order two laptops'
cautionary tale. Pub/Sub redelivers the event to a fresh instance, which
finds the claim already recorded and narrates the recovery instead. State
intact, no duplicate side effects, resumed mid-journey.

Locally (one process, in-memory bus) a real exit would kill the whole
walking skeleton, so the redelivery is simulated by republishing."""

import logging
import os

from ..common import config, events
from .context import Context

log = logging.getLogger(__name__)


async def on_demo_crash(ctx: Context, payload: dict) -> None:
    journey_id = payload["journey_id"]

    def mark(j):
        drills = int(j.meta.get("crash_drills", 0)) + 1
        j.meta["crash_drills"] = drills
        return drills

    journey, drills = await ctx.store.mutate_journey(journey_id, mark)
    if journey is None:
        return

    if drills % 2 == 1:  # first delivery of this drill
        await ctx.log(
            journey_id, "chaos", "crash.simulated",
            "💥 Simulating a crash: killing the agent fleet mid-journey WITHOUT "
            "acknowledging this event. Journey state is already durable in the "
            "store; the event bus will redeliver to a fresh instance.",
        )
        if config.MODE == "cloud":
            log.warning("demo.crash: exiting process before ack (drill %s)", drills)
            os._exit(1)  # no ack ever sent -> Pub/Sub redelivers -> Cloud Run replaces us
        # Local walking skeleton: single process, so simulate the redelivery.
        await ctx.bus.publish(events.DEMO_CRASH, {"journey_id": journey_id})
        return

    await ctx.log(
        journey_id, "chaos", "crash.recovered",
        "🛡️ Fresh instance received the redelivered event. State machine and "
        "audit log intact, idempotency claims prevented duplicate side effects "
        "— resuming exactly where we left off.",
    )
