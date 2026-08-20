"""Live-model quality evals — the half of correctness fault injection can't
reach: is the model's judgement actually good?

Skipped unless LIVE_EVALS=1 and credentials are present. Budgeted: one call
per task by default (LIVE_EVAL_SAMPLES to raise it, majority wins)."""

import asyncio
import os

import pytest

from evals.live.goldens import (
    FREELANCE_FORBIDDEN_KEYWORDS,
    FREELANCE_PROMPT,
    MEERA_ADVISORY_KEYWORDS,
    MEERA_PROMPT,
    MEERA_REQUIRED_KEYWORDS,
    NOTICE_TEXT,
    NoticeParse,
    covers,
    determination_keys,
    wellformed,
)
from lalfita.agents import clerk, liaison, pathfinder
from lalfita.common import config, llm
from lalfita.common.fixtures import CLERK_EXTRACTIONS

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("LIVE_EVALS") != "1",
        reason="live evals are opt-in: set LIVE_EVALS=1",
    ),
]

SAMPLES = int(os.environ.get("LIVE_EVAL_SAMPLES", "1"))
UNREACHABLE = {"__live_call_failed__": True}
RETRIES = int(os.environ.get("LIVE_EVAL_RETRIES", "2"))
PACING_S = float(os.environ.get("LIVE_EVAL_PACING_S", "4"))


@pytest.fixture(autouse=True)
def require_credentials():
    os.environ.pop("LALFITA_OFFLINE", None)
    if config.offline():
        pytest.skip("no Gemini credentials configured")


async def _sample(build_agent, prompt, **kwargs):
    """Run a prompt N times, returning only genuine model answers.

    run_agent degrades to its fixture when a live call fails, so an
    unreachable model would otherwise read as a quality regression. Here the
    fixture is a sentinel: if it comes back, the call failed, and the eval
    retries and finally *skips* rather than reporting a false failure. Quota
    exhaustion is an infrastructure fact, not a judgement about the model."""
    results = []
    for _ in range(SAMPLES):
        for attempt in range(RETRIES + 1):
            result = await llm.run_agent(
                build_agent, prompt, offline_fixture=dict(UNREACHABLE), **kwargs
            )
            if not result.get("__live_call_failed__"):
                results.append(result)
                break
            if attempt < RETRIES:
                await asyncio.sleep(PACING_S * (attempt + 1))
        await asyncio.sleep(PACING_S)  # stay under per-minute limits

    if not results:
        pytest.skip(
            "model unreachable (quota or transient API failure) — no quality "
            "signal from this run"
        )
    return results


def _majority(flags: list[bool]) -> bool:
    return sum(flags) * 2 > len(flags)


async def test_pathfinder_finds_the_food_registrations():
    results = await _sample(pathfinder.build_agent, MEERA_PROMPT)
    outcomes, misses, structural = [], [], []
    advisory_hits = 0
    for result in results:
        keys = determination_keys(result)
        missing = covers(keys, MEERA_REQUIRED_KEYWORDS)
        problems = wellformed(result)
        outcomes.append(not missing and not problems)
        misses.append(missing)
        structural.extend(problems)
        if not covers(keys, MEERA_ADVISORY_KEYWORDS):
            advisory_hits += 1

    assert _majority(outcomes), (
        f"determination missed a required registration {misses} "
        f"or was malformed {structural}"
    )
    if advisory_hits < len(results):
        print(
            f"\nADVISORY: GST appeared in {advisory_hits}/{len(results)} samples. "
            "Defensible (small suppliers via e-commerce operators have an "
            "exemption), but worth watching if it trends to zero."
        )


async def test_pathfinder_does_not_demand_a_food_license_for_a_design_studio():
    results = await _sample(pathfinder.build_agent, FREELANCE_PROMPT)
    outcomes = []
    for result in results:
        keys = determination_keys(result)
        no_food = not any(
            word in key for key in keys for word in FREELANCE_FORBIDDEN_KEYWORDS
        )
        outcomes.append(no_food and not wellformed(result))
    assert _majority(outcomes), (
        "a design studio was told it needs a food licence (or the "
        "determination was malformed)"
    )


async def test_clerk_catches_the_name_mismatch():
    prompt = f"Cross-validate these documents: {CLERK_EXTRACTIONS}"
    results = await _sample(clerk.build_agent, prompt)
    outcomes = []
    for result in results:
        issues = result.get("issues", [])
        outcomes.append(
            any(
                i.get("severity") == "blocking"
                and "name" in str(i.get("field", "")).lower()
                for i in issues
            )
        )
    assert _majority(outcomes), (
        "Clerk failed to flag the PAN/utility-bill name mismatch as blocking — "
        "this is the rejection trap the product exists to catch"
    )


async def test_liaison_notice_parse_matches_the_contract():
    results = await _sample(liaison.build_agent, NOTICE_TEXT)
    outcomes, errors = [], []
    for result in results:
        try:
            NoticeParse.model_validate(result)
            outcomes.append(True)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            outcomes.append(False)
            errors.append(str(exc))
    assert _majority(outcomes), f"notice parse violated the downstream contract: {errors}"
