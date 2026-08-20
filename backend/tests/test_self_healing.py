"""CI bridge for the self-healing eval matrix, plus harness self-tests and a
negative control.

An evaluation that cannot fail measures nothing, so `test_negative_control`
removes the idempotency guard and asserts the duplicate-delivery scenario
turns red."""

import asyncio
import dataclasses
import os

import pytest

os.environ["LALFITA_OFFLINE"] = "1"

from evals.harness.app import build_eval_app
from evals.harness.driver import EvalDriver
from evals.harness.faults import BusFault, FaultPlan
from evals.harness.probes import collect
from evals.rubric import score_run
from evals.runner import run_scenario
from evals.scenarios import SCENARIOS, SCENARIOS_BY_ID
from lalfita.common import config, events


@pytest.fixture(autouse=True)
def eval_clock():
    sim, lease = config.SIM_DAY_SECONDS, config.SUBMIT_LEASE_SECONDS
    config.SIM_DAY_SECONDS = 0.05
    config.SUBMIT_LEASE_SECONDS = 0.5
    yield
    config.SIM_DAY_SECONDS, config.SUBMIT_LEASE_SECONDS = sim, lease


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
async def test_scenario(scenario):
    if scenario.expected_fail:
        pytest.xfail(f"{scenario.id}: known gap — {scenario.note}")
    result = await run_scenario(scenario, seed=0)
    failed = [cid for cid, ok in result["criteria"].items() if ok is False]
    assert result["passed"], (
        f"{scenario.id} failed {failed}; metrics={result['metrics']}"
    )


async def test_chaos_bus_really_duplicates():
    plan = FaultPlan(bus=[BusFault(events.JOURNEY_CREATED, "duplicate")])
    with build_eval_app(plan) as app:
        await app.ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": "x"})
        await asyncio.sleep(0.1)
        await app.ctx.bus.drain()
    assert app.trace.count(events.JOURNEY_CREATED, "duplicated") == 1
    assert app.trace.count(events.JOURNEY_CREATED) == 2


async def test_ledger_records_every_outbound_attempt():
    scenario = SCENARIOS_BY_ID["S0"]
    with build_eval_app(FaultPlan()) as app:
        run = await EvalDriver(app).run(scenario.goal, dict(scenario.profile))
        assert run.completed
        # Three registrations filed, one notice answered.
        assert len({(j, k) for j, k, _ in app.ledger.submissions}) == 3
        assert len(app.ledger.replies) == 1


async def test_flaky_llm_targets_one_agent_only():
    from evals.harness.faults import LlmFault

    plan = FaultPlan(llm=[LlmFault("pathfinder", "malformed", times=1, payload={"x": 1})])
    with build_eval_app(plan) as app:
        run = await EvalDriver(app).run(
            SCENARIOS_BY_ID["S0"].goal, dict(SCENARIOS_BY_ID["S0"].profile)
        )
    # Clerk and liaison still ran normally, so the journey completed.
    assert run.completed
    assert any("pathfinder" in c for c in app.llm.calls)
    assert any("clerk" in c for c in app.llm.calls)


async def test_negative_control_duplicate_delivery_is_actually_detected():
    """Disable Liaison's claim guard: the duplicate-approval scenario must go
    red. This proves the exactly-once criterion has teeth."""
    from lalfita.agents import liaison
    from lalfita.common.schemas import StepStatus

    scenario = SCENARIOS_BY_ID["S3"]
    original = liaison.on_submission_approved

    async def unguarded(ctx, payload):
        """The pre-hardening implementation: submit without claiming."""
        journey = await ctx.store.get_journey(payload["journey_id"])
        req = journey.requirement(payload["requirement_id"]) if journey else None
        if journey is None or req is None:
            return
        ref = await ctx.gateway.submit(
            req.authority, journey.id, req.key, payload.get("application", {})
        )

        def record(j):
            r = j.requirement(payload["requirement_id"])
            if r is not None:
                r.reference = ref
                r.status = StepStatus.WAITING_EXTERNAL

        await ctx.store.mutate_journey(journey.id, record)

    liaison.on_submission_approved = unguarded
    try:
        from lalfita.agents import registry

        plan = dataclasses.replace(scenario.plan, seed=0)
        with build_eval_app(plan) as app:
            # Rebind the routing table so the unguarded handler is used.
            registry.bind(app.bus, app.ctx)
            run = await EvalDriver(
                app, policy=scenario.policy, duplicate_approvals=True
            ).run(scenario.goal, dict(scenario.profile))
            metrics = await collect(app, run, faults_injected=True)
    finally:
        liaison.on_submission_approved = original

    scores = score_run(metrics, {"faults_injected": True})
    assert metrics.duplicate_side_effects > 0, (
        "removing the claim guard must produce duplicate filings — otherwise "
        "the exactly-once criterion is not measuring anything"
    )
    assert scores["C3"] is False
