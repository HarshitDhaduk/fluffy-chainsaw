"""Chaos monkey — the faults nobody thought to write down.

The hand-written matrix tests the failures we imagined. Real journeys hit
combinations: a duplicate arrives while the store is slow and the model is
returning nonsense. Each iteration composes a random fault cocktail from a
seed, so any failure reproduces exactly with `--only-seed`."""

import argparse
import asyncio
import logging
import os
import random

os.environ.setdefault("LALFITA_OFFLINE", "1")
if os.environ.get("EVALS_VERBOSE") != "1":
    logging.disable(logging.ERROR)

from lalfita.common import config, events  # noqa: E402

from .harness.app import build_eval_app  # noqa: E402
from .harness.chaos_store import StoreFault  # noqa: E402
from .harness.driver import EvalDriver  # noqa: E402
from .harness.faults import BusFault, FaultPlan, GatewayFault, LlmFault  # noqa: E402
from .harness.probes import collect  # noqa: E402
from .scenarios import MEERA_GOAL, MEERA_PROFILE  # noqa: E402

BUS_EVENTS = [
    events.JOURNEY_CREATED, events.REQUIREMENTS_DETERMINED, events.PLAN_READY,
    events.APPROVAL_GRANTED, events.PORTAL_RESPONSE,
]
STORE_METHODS = ["mutate_journey", "get_journey", "append_timeline", "create_approval"]
AGENTS = ["pathfinder", "clerk", "liaison"]


def random_plan(seed: int) -> FaultPlan:
    rng = random.Random(seed)
    plan = FaultPlan(seed=seed)
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(["bus", "store", "llm", "gateway"])
        if kind == "bus":
            plan.bus.append(BusFault(
                rng.choice(BUS_EVENTS),
                rng.choice(["duplicate", "drop_then_redeliver", "delay"]),
                nth=rng.randint(1, 3), times=rng.choice([1, 1, 0]),
                delay_s=rng.choice([0.1, 0.3]),
            ))
        elif kind == "store":
            plan.store.append(StoreFault(
                rng.choice(STORE_METHODS),
                rng.choice(["fail", "abort", "ambiguous", "slow"]),
                times=rng.randint(1, 3), nth=rng.randint(1, 6),
                delay_s=0.1,
            ))
        elif kind == "llm":
            plan.llm.append(LlmFault(
                rng.choice(AGENTS), rng.choice(["raise", "malformed"]),
                times=1, payload={},
            ))
        else:
            plan.gateway.append(GatewayFault(
                rng.choice(["submit", "reply"]),
                rng.choice(["crash_after", "crash_before", "timeout"]),
                requirement_key=rng.choice([None, "gst", "fssai_basic"]),
                times=1,
            ))
    return plan


async def run_one(seed: int) -> dict:
    plan = random_plan(seed)
    with build_eval_app(plan) as app:
        # Multi-fault recovery legitimately takes longer than single-fault.
        driver = EvalDriver(app, max_ticks=900, duplicate_approvals=bool(seed % 3 == 0))
        run = await driver.run(MEERA_GOAL, dict(MEERA_PROFILE))
        metrics = await collect(app, run, faults_injected=True)
    return {
        "seed": seed,
        "completed": metrics.completed,
        "duplicates": metrics.duplicate_side_effects,
        "violations": metrics.invariant_violations,
        "unauthorized": metrics.unauthorized_side_effects,
        "faults": _describe(plan),
    }


def _describe(plan: FaultPlan) -> str:
    parts = []
    parts += [f"bus:{f.event_type.split('.')[-1]}/{f.action}" for f in plan.bus]
    parts += [f"store:{f.method}/{f.action}" for f in plan.store]
    parts += [f"llm:{f.agent_module}/{f.action}" for f in plan.llm]
    parts += [f"gw:{f.method}/{f.action}" for f in plan.gateway]
    return " + ".join(parts)


def _judge(result: dict) -> list[str]:
    """Invariants that must hold no matter what was injected."""
    broken = []
    if result["duplicates"]:
        broken.append(f"{result['duplicates']} duplicate side effects")
    if result["violations"]:
        broken.append(f"invariants: {result['violations']}")
    if result["unauthorized"]:
        broken.append(f"{result['unauthorized']} unauthorized filings")
    if not result["completed"]:
        broken.append("journey never completed")
    return broken


async def main_async(args) -> int:
    config.SIM_DAY_SECONDS = 0.05
    config.SUBMIT_LEASE_SECONDS = 0.5
    seeds = [args.only_seed] if args.only_seed is not None else list(range(args.iterations))

    print(
        f"Chaos soak: {len(seeds)} journeys with random fault cocktails "
        f"({args.jobs} in parallel)\n",
        flush=True,
    )
    # Journeys are sleep-dominated (tick pacing), so running several at once
    # multiplies throughput — and the concurrency itself stresses the store
    # locks and idempotency claims harder than any sequential run.
    gate = asyncio.Semaphore(max(args.jobs, 1))
    done_count = 0

    async def run_gated(seed: int) -> tuple[int, dict]:
        nonlocal done_count
        async with gate:
            result = await run_one(seed)
        done_count += 1
        if done_count % 50 == 0:
            print(f"  … {done_count}/{len(seeds)} journeys finished", flush=True)
        return seed, result

    outcomes = await asyncio.gather(*(run_gated(seed) for seed in seeds))

    failures = []
    for seed, result in sorted(outcomes):
        broken = _judge(result)
        if broken:
            failures.append((seed, broken, result["faults"]))
            print(f"  ❌ seed {seed:<4} {result['faults']}\n       {'; '.join(broken)}")
        elif args.verbose:
            print(f"  ✅ seed {seed:<4} {result['faults']}")

    print(f"\n{len(seeds) - len(failures)}/{len(seeds)} journeys healed themselves.")
    if failures:
        print("\nReproduce any failure with:")
        for seed, _, _ in failures[:5]:
            print(f"  python -m evals.soak --only-seed {seed} --verbose")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Random-fault soak test")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--jobs", type=int, default=8,
                        help="journeys to run concurrently (default 8)")
    parser.add_argument("--only-seed", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
