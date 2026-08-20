"""Durability: does the work survive when the process does not?

These tests read as documentation. Each one states a promise LalFita makes
about long-running journeys and then tries to break it — with a real SIGKILL,
not a simulated one. Marked `durable` because they spawn subprocesses and take
seconds rather than milliseconds; run them with `make evals-durable`."""

import os

import pytest

os.environ["LALFITA_OFFLINE"] = "1"

from evals.harness.restart import SubprocessRestart
from evals.scenarios import MEERA_GOAL, MEERA_PROFILE

pytestmark = pytest.mark.durable


@pytest.fixture
def server():
    """A LalFita process backed by a file on disk, killable at will."""
    harness = SubprocessRestart(sim_day_seconds=1.0)
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()


def _drive_to_submissions(server) -> str:
    """Start Meera's journey and get as far as filings with the authorities."""
    journey_id = server.start_journey(MEERA_GOAL, dict(MEERA_PROFILE))
    return server.wait_for(
        journey_id,
        lambda j: sum(1 for r in j["requirements"] if r["reference"]) >= 3,
        timeout_s=90,
    ) and journey_id


def test_journey_survives_a_real_process_kill(server):
    """The promise: kill the fleet outright and nothing is forgotten."""
    journey_id = _drive_to_submissions(server)
    before = server.journey(journey_id)

    server.kill()

    # Between death and rebirth, the entire state of the world is one file.
    on_disk = server.snapshot_on_disk()
    assert journey_id in on_disk["journeys"], "journey did not reach durable storage"
    assert on_disk["timelines"][journey_id], "the audit trail did not survive"

    server.start()
    after = server.journey(journey_id)

    assert after["goal"] == before["goal"]
    assert len(after["requirements"]) == len(before["requirements"])
    assert [r["reference"] for r in after["requirements"]] == [
        r["reference"] for r in before["requirements"]
    ], "application references were lost across the restart"
    assert len(after["timeline"]) >= len(before["timeline"])
    assert len(after["approvals"]) == len(before["approvals"])


def test_granted_approvals_are_never_forgotten(server):
    """A human's decision is expensive. Losing one means asking them twice."""
    journey_id = _drive_to_submissions(server)
    granted_before = [
        a for a in server.journey(journey_id)["approvals"] if a["status"] == "approved"
    ]
    assert granted_before, "expected the document fix and submissions to be approved"

    server.kill()
    server.start()

    granted_after = [
        a for a in server.journey(journey_id)["approvals"] if a["status"] == "approved"
    ]
    assert {a["id"] for a in granted_after} >= {a["id"] for a in granted_before}


def test_nothing_is_filed_twice_across_a_restart(server):
    """The authority's own records are the ground truth for exactly-once."""
    journey_id = _drive_to_submissions(server)
    refs_before = sorted(r["reference"] for r in server.journey(journey_id)["requirements"])

    server.kill()
    server.start()
    # Give the restarted fleet time to resync and act on what it finds.
    server.wait_for(journey_id, lambda j: True, timeout_s=5)

    refs_after = sorted(r["reference"] for r in server.journey(journey_id)["requirements"])
    assert refs_after == refs_before, (
        "a restart produced new application references — the journey re-filed "
        "applications the authority had already accepted"
    )


def test_a_journey_completes_after_being_killed_mid_flight(server):
    """The whole point: a restart is a pause, not an ending.

    The notifications the authorities pushed while the fleet was dead are gone
    for good — exactly as in life. The journey must notice the silence, ask
    the authorities where things stand, and carry on to completion."""
    journey_id = _drive_to_submissions(server)

    server.kill()
    server.start()

    final = server.wait_for(
        journey_id, lambda j: j["status"] == "completed", timeout_s=120
    )
    assert all(r["registration_number"] for r in final["requirements"])
    events = [t["event"] for t in final["timeline"]]
    assert "portal.resynced" in events, (
        "the journey completed without ever reconciling with the authorities — "
        "check whether the missed notifications were actually missed"
    )
