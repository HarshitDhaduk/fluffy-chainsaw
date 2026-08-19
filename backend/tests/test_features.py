"""B6/B7/B8 + remaining B4: notifications, crash drill, second journey
preset, and duplicate-notice idempotency."""

import asyncio
import os

import pytest

os.environ["LALFITA_OFFLINE"] = "1"

from lalfita.common import config, events
from lalfita.common.schemas import ApprovalKind, ApprovalStatus, Journey
from lalfita.local import build_app


@pytest.fixture(autouse=True)
def fast_clock():
    original = config.SIM_DAY_SECONDS
    config.SIM_DAY_SECONDS = 0.05
    yield
    config.SIM_DAY_SECONDS = original


async def _drive(ctx, journey_id, until_event, tries=200, approve=True):
    for _ in range(tries):
        await asyncio.sleep(0.05)
        if approve:
            for a in await ctx.store.list_approvals(journey_id, ApprovalStatus.PENDING):
                a.status = ApprovalStatus.APPROVED
                await ctx.store.save_approval(a)
                await ctx.bus.publish(
                    events.APPROVAL_GRANTED,
                    {"journey_id": a.journey_id, "approval_id": a.id, "kind": a.kind, **a.payload},
                )
        timeline = await ctx.store.get_timeline(journey_id)
        if any(t.event == until_event for t in timeline):
            return timeline
    raise AssertionError(f"never saw {until_event}")


async def test_freelance_preset_yields_different_requirements():
    _, ctx = build_app()
    journey = Journey(
        goal="Register my freelance design studio",
        profile={"demo_documents": True},
    )
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})
    await asyncio.sleep(0.5)
    await ctx.bus.drain()

    current = await ctx.store.get_journey(journey.id)
    keys = {r.key for r in current.requirements}
    assert "shop_establishment" in keys
    assert "fssai_basic" not in keys, "freelance preset must not require a food license"


async def test_notifications_land_on_timeline():
    _, ctx = build_app()
    journey = Journey(goal="Legalize my home food business", profile={"demo_documents": True})
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})

    timeline = await _drive(ctx, journey.id, "journey.completed", tries=400)
    notifications = [t.detail for t in timeline if t.event == "notification.sent"]
    assert any("Document problem" in n for n in notifications)
    assert any("notice" in n.lower() for n in notifications)
    assert any("Journey complete" in n for n in notifications)


async def test_crash_drill_records_crash_and_recovery():
    _, ctx = build_app()
    journey = Journey(goal="Legalize my home food business", profile={"demo_documents": True})
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})
    await asyncio.sleep(0.3)

    await ctx.bus.publish(events.DEMO_CRASH, {"journey_id": journey.id})
    await asyncio.sleep(0.3)
    await ctx.bus.drain()

    timeline_events = [t.event for t in await ctx.store.get_timeline(journey.id)]
    assert "crash.simulated" in timeline_events
    assert "crash.recovered" in timeline_events

    current = await ctx.store.get_journey(journey.id)
    assert current.meta.get("crash_drills") == 2  # first delivery + redelivery


async def test_duplicate_notice_creates_one_deadline_and_one_reply():
    _, ctx = build_app()
    journey = Journey(goal="Legalize my home food business", profile={"demo_documents": True})
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})

    # Drive until the GST notice has been handled once (reply drafted), but
    # do NOT approve the reply.
    for _ in range(400):
        await asyncio.sleep(0.05)
        for a in await ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING):
            if a.kind == ApprovalKind.NOTICE_REPLY:
                continue
            a.status = ApprovalStatus.APPROVED
            await ctx.store.save_approval(a)
            await ctx.bus.publish(
                events.APPROVAL_GRANTED,
                {"journey_id": a.journey_id, "approval_id": a.id, "kind": a.kind, **a.payload},
            )
        timeline = await ctx.store.get_timeline(journey.id)
        if any(t.event == "reply.drafted" for t in timeline):
            break
    else:
        raise AssertionError("notice never arrived")

    current = await ctx.store.get_journey(journey.id)
    gst = next(r for r in current.requirements if r.key == "gst")

    # Redeliver the same notice event (at-least-once bus).
    await ctx.bus.publish(
        events.PORTAL_RESPONSE,
        {
            "journey_id": journey.id,
            "requirement_key": "gst",
            "reference": gst.reference,
            "kind": "notice",
            "message": "duplicate delivery of the same notice",
            "reply_deadline_days": 7,
        },
    )
    await asyncio.sleep(0.3)
    await ctx.bus.drain()

    replies = [
        a
        for a in await ctx.store.list_approvals(journey.id)
        if a.kind == ApprovalKind.NOTICE_REPLY
    ]
    deadlines = await ctx.store.list_deadlines(journey.id)
    assert len(replies) == 1, f"duplicate notice created {len(replies)} reply approvals"
    assert len(deadlines) == 1, f"duplicate notice created {len(deadlines)} deadlines"
