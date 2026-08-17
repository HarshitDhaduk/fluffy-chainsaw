"""The whole Meera journey, end-to-end, offline, in a few seconds.

If this test is green the choreography works: pathfinder → planner → clerk
(mismatch caught) → approvals → liaison submissions → sandbox notice →
drafted reply → deadline resolved → all registrations granted."""

import asyncio
import os

import pytest

os.environ["LALFITA_OFFLINE"] = "1"

from lalfita.common import config, events
from lalfita.common.schemas import ApprovalStatus, Journey, JourneyStatus, StepStatus
from lalfita.local import build_app


@pytest.fixture(autouse=True)
def fast_clock():
    original = config.SIM_DAY_SECONDS
    config.SIM_DAY_SECONDS = 0.05
    yield
    config.SIM_DAY_SECONDS = original


async def test_meera_journey_completes():
    _, ctx = build_app()

    journey = Journey(
        goal="Make my home food business legal",
        profile={
            "applicant_name": "Meera Shah",
            "annual_turnover_inr": 800000,
            "demo_documents": True,
        },
    )
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})

    async def auto_approve() -> None:
        for approval in await ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING):
            approval.status = ApprovalStatus.APPROVED
            await ctx.store.save_approval(approval)
            await ctx.bus.publish(
                events.APPROVAL_GRANTED,
                {
                    "journey_id": approval.journey_id,
                    "approval_id": approval.id,
                    "kind": approval.kind,
                    **approval.payload,
                },
            )

    completed = False
    for _ in range(400):  # ≈ 20s ceiling
        await asyncio.sleep(0.05)
        await ctx.bus.publish(events.DEADLINE_TICK, {})
        await auto_approve()
        current = await ctx.store.get_journey(journey.id)
        if current and current.status == JourneyStatus.COMPLETED:
            completed = True
            break

    assert completed, "journey did not reach COMPLETED"

    final = await ctx.store.get_journey(journey.id)
    assert len(final.requirements) == 3
    assert all(r.status == StepStatus.DONE for r in final.requirements)
    assert all(r.registration_number for r in final.requirements)

    timeline = await ctx.store.get_timeline(journey.id)
    timeline_events = [t.event for t in timeline]
    assert "document.issue" in timeline_events, "name mismatch was not caught"
    assert "portal.notice" in timeline_events, "clarification notice never arrived"
    assert "reply.drafted" in timeline_events
    assert "reply.sent" in timeline_events


async def test_approval_gate_blocks_until_human_acts():
    _, ctx = build_app()

    journey = Journey(goal="Test gating", profile={"demo_documents": True})
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})
    await asyncio.sleep(0.5)
    await ctx.bus.drain()

    current = await ctx.store.get_journey(journey.id)
    assert current.status == JourneyStatus.ACTION_REQUIRED
    # Nothing was submitted: no requirement has a portal reference yet.
    assert all(r.reference is None for r in current.requirements)
    pending = await ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING)
    assert pending, "expected a pending human approval"
