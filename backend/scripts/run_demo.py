"""End-to-end walking-skeleton demo: Meera's journey, fully offline.

    cd backend && python scripts/run_demo.py

Plays the entire choreography — research → plan → document mismatch caught →
approvals → submissions → '2 AM' clarification notice → drafted reply →
deadline countdown → approvals granted — on the time-compressed sim clock,
printing the audit timeline live. The human's taps are auto-approved here;
on the dashboard they're real buttons."""

import asyncio
import os
import sys

os.environ.setdefault("LALFITA_OFFLINE", "1")
os.environ.setdefault("SIM_DAY_SECONDS", "1.5")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lalfita.common import events  # noqa: E402
from lalfita.common.schemas import ApprovalStatus, JourneyStatus  # noqa: E402
from lalfita.local import build_app  # noqa: E402

MEERA = {
    "goal": "Make my home food business legal so I can sell on delivery platforms",
    "profile": {
        "applicant_name": "Meera Shah",
        "city": "Ahmedabad",
        "business": "Home kitchen — Gujarati snacks",
        "annual_turnover_inr": 800000,
        "premises": "residential",
        "channels": ["delivery platforms", "direct orders"],
        # Terminal demo runs unattended: load fixture documents instead of
        # waiting for uploads (the dashboard flow uses real uploads).
        "demo_documents": True,
    },
}


async def main() -> None:
    app, ctx = build_app()
    from lalfita.api.routes import JourneyIn, build_router  # noqa: F401  (router already mounted)

    print("🪔 LalFita walking skeleton — Meera's journey\n" + "=" * 60)

    # Create the journey the same way the dashboard would.
    from lalfita.common.schemas import Journey

    journey = Journey(goal=MEERA["goal"], profile=MEERA["profile"])
    await ctx.store.create_journey(journey)
    await ctx.log(journey.id, "user", "journey.created", f"Goal: “{journey.goal}”")
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})

    printed = 0
    for _ in range(600):  # hard stop ≈ 60s
        await asyncio.sleep(0.1)
        await ctx.bus.publish(events.DEADLINE_TICK, {})

        timeline = await ctx.store.get_timeline(journey.id)
        for entry in timeline[printed:]:
            print(f"  [{entry.actor:^10}] {entry.event:<24} {entry.detail}")
        printed = len(timeline)

        # Auto-tap the human approval gates after a beat.
        for approval in await ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING):
            await asyncio.sleep(0.3)
            approval.status = ApprovalStatus.APPROVED
            await ctx.store.save_approval(approval)
            await ctx.log(
                journey.id, "user", "approval.approved", f"✅ Approved: {approval.summary}"
            )
            await ctx.bus.publish(
                events.APPROVAL_GRANTED,
                {
                    "journey_id": approval.journey_id,
                    "approval_id": approval.id,
                    "kind": approval.kind,
                    **approval.payload,
                },
            )

        current = await ctx.store.get_journey(journey.id)
        if current and current.status == JourneyStatus.COMPLETED:
            break

    final = await ctx.store.get_journey(journey.id)
    print("=" * 60)
    print(f"Final status: {final.status.value}")
    for req in final.requirements:
        print(f"  • {req.title}: {req.status.value}  →  {req.registration_number or '—'}")


if __name__ == "__main__":
    asyncio.run(main())
