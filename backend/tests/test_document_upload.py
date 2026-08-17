"""B1: real document upload flow — Clerk requests documents, uploads flow
through the API into the blob store, extraction runs per upload (offline:
fixtures), and cross-validation fires once all required kinds are present.
Also covers the re-upload-replaces flow and duplicate-event idempotency."""

import asyncio
import os

import httpx
import pytest

os.environ["LALFITA_OFFLINE"] = "1"

from lalfita.common import config, events
from lalfita.common.schemas import ApprovalKind, ApprovalStatus
from lalfita.local import build_app


@pytest.fixture(autouse=True)
def fast_clock():
    original = config.SIM_DAY_SECONDS
    config.SIM_DAY_SECONDS = 0.05
    yield
    config.SIM_DAY_SECONDS = original


async def _wait_for_event(client, journey_id, event, tries=100):
    for _ in range(tries):
        await asyncio.sleep(0.05)
        journey = (await client.get(f"/journeys/{journey_id}")).json()
        if any(t["event"] == event for t in journey["timeline"]):
            return journey
    raise AssertionError(f"timeline never showed {event}")


async def test_upload_flow_requests_extracts_and_validates():
    app, ctx = build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/journeys",
            json={"goal": "Make my home food business legal", "profile": {}},
        )
        journey_id = resp.json()["journey_id"]

        # Without demo_documents, Clerk asks for uploads instead of fixtures.
        journey = await _wait_for_event(client, journey_id, "documents.requested")
        assert journey["status"] == "action_required"
        assert journey["required_documents"] == ["pan", "aadhaar", "utility_bill"]
        assert journey["documents"] == []

        for kind in ("pan", "aadhaar", "utility_bill"):
            upload = await client.post(
                f"/journeys/{journey_id}/documents",
                data={"kind": kind},
                files={"file": (f"{kind}.jpg", b"fake-image-bytes", "image/jpeg")},
            )
            assert upload.status_code == 200, upload.text

        # Extraction ran per document; validation found the fixture mismatch.
        journey = await _wait_for_event(client, journey_id, "document.issue")
        kinds = {d["kind"]: d for d in journey["documents"]}
        assert set(kinds) == {"pan", "aadhaar", "utility_bill"}
        assert kinds["pan"]["extracted"], "vision extraction did not populate fields"
        assert kinds["pan"]["blob_uri"].startswith("mem://")
        assert any(i["severity"] == "blocking" for i in kinds["utility_bill"]["issues"])

        pending = [a for a in journey["approvals"] if a["status"] == "pending"]
        assert any(a["kind"] == ApprovalKind.DOCUMENT_FIX for a in pending)

        # Unknown document kinds are rejected.
        bad = await client.post(
            f"/journeys/{journey_id}/documents",
            data={"kind": "passport"},
            files={"file": ("p.jpg", b"x", "image/jpeg")},
        )
        assert bad.status_code == 400

        # Re-upload replaces the document of the same kind (corrected bill).
        again = await client.post(
            f"/journeys/{journey_id}/documents",
            data={"kind": "utility_bill"},
            files={"file": ("bill_v2.jpg", b"better-image", "image/jpeg")},
        )
        assert again.status_code == 200
        await asyncio.sleep(0.3)
        journey = (await client.get(f"/journeys/{journey_id}")).json()
        bills = [d for d in journey["documents"] if d["kind"] == "utility_bill"]
        assert len(bills) == 1 and bills[0]["filename"] == "bill_v2.jpg"


async def test_duplicate_uploaded_event_extracts_once():
    _, ctx = build_app()
    from lalfita.common.schemas import Journey

    journey = Journey(goal="Idempotency check", profile={"demo_documents": True})
    await ctx.store.create_journey(journey)
    await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})
    await asyncio.sleep(0.5)
    await ctx.bus.drain()

    # Redeliver PLAN_READY (at-least-once bus): no duplicate submission
    # approvals may appear.
    await ctx.bus.publish(events.PLAN_READY, {"journey_id": journey.id})
    await asyncio.sleep(0.3)
    await ctx.bus.drain()

    approvals = await ctx.store.list_approvals(journey.id)
    fixes = [a for a in approvals if a.kind == ApprovalKind.DOCUMENT_FIX]
    assert len(fixes) == 1, f"expected one document_fix approval, got {len(fixes)}"

    # Resolve the fix, then redeliver the approval event: only one round of
    # submission approvals (the "second laptop" guard).
    fix = fixes[0]
    fix.status = ApprovalStatus.APPROVED
    await ctx.store.save_approval(fix)
    payload = {"journey_id": journey.id, "kind": fix.kind, **fix.payload}
    await ctx.bus.publish(events.APPROVAL_GRANTED, payload)
    await ctx.bus.publish(events.APPROVAL_GRANTED, payload)  # duplicate
    await asyncio.sleep(0.3)
    await ctx.bus.drain()

    submissions = [
        a
        for a in await ctx.store.list_approvals(journey.id)
        if a.kind == ApprovalKind.SUBMISSION
    ]
    journey_now = await ctx.store.get_journey(journey.id)
    assert len(submissions) == len(journey_now.requirements), (
        f"duplicate delivery created {len(submissions)} submission approvals "
        f"for {len(journey_now.requirements)} requirements"
    )
