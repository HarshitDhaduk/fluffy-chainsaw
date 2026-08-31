"""Pathfinder — determines which registrations actually apply.

Rules are researched with Gemini + Google Search grounding, not hardcoded:
that's what makes the engine generalize beyond GST/FSSAI."""

import json

from ..common import events, llm
from ..common.fixtures import FREELANCE_DETERMINATION, PATHFINDER_DETERMINATION
from ..common.schemas import JourneyStatus, Requirement
from .context import Context

INSTRUCTION = """You are Pathfinder, a compliance-research agent for Indian small
businesses. Given a business goal and profile, determine the minimal set of
registrations/licenses required. If search grounding is enabled, you may use
Google Search to verify current rules and thresholds; cite sources.
Respond ONLY with JSON - no markdown formatting, no code fences:
{"requirements": [{"key": str, "title": str, "authority": str, "form": str,
  "why": str, "citations": [str]}]}
Keys must be stable slugs (e.g. "gst", "fssai_basic", "udyam")."""


def build_agent():
    from google.adk.agents import LlmAgent

    from ..common import config

    tools = []
    if config.SEARCH_GROUNDING:
        from google.adk.tools import google_search

        tools.append(google_search)

    return LlmAgent(
        name="pathfinder",
        model=config.GEMINI_PRO,
        description="Researches which government registrations apply to a business.",
        instruction=INSTRUCTION,
        tools=tools,
    )


def _fixture_for(goal: str) -> dict:
    """Offline-mode determination, keyed on the goal so both demo presets work
    without credentials. Live mode researches for real and ignores this."""
    lowered = goal.lower()
    if any(k in lowered for k in ("freelance", "studio", "design", "consult", "agency")):
        return FREELANCE_DETERMINATION
    return PATHFINDER_DETERMINATION


async def on_journey_created(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None or journey.requirements:  # idempotency guard
        return

    await ctx.set_status(journey.id, JourneyStatus.RESEARCHING)
    await ctx.log(journey.id, "pathfinder", "research.started", f"Researching: “{journey.goal}”")

    prompt = f"Goal: {journey.goal}\nProfile: {json.dumps(journey.profile)}"
    result = await llm.run_agent(build_agent, prompt, offline_fixture=_fixture_for(journey.goal))

    # Never let a malformed model reply stall the journey: validate the shape
    # and degrade to the built-in determination if it doesn't hold.
    try:
        requirements = [Requirement.model_validate(r) for r in result["requirements"]]
        if not requirements:
            raise ValueError("empty requirements list")
    except Exception:
        requirements = [
            Requirement.model_validate(r)
            for r in _fixture_for(journey.goal)["requirements"]
        ]
        await ctx.log(
            journey.id, "pathfinder", "research.degraded",
            "⚠️ Research output was malformed; fell back to the built-in "
            "determination for this goal so the journey keeps moving.",
        )

    def apply(j):
        if not j.requirements:  # idempotency under redelivery
            j.requirements = requirements

    updated, _ = await ctx.store.mutate_journey(journey.id, apply)
    if updated is None:
        return
    await ctx.log(
        journey.id,
        "pathfinder",
        "requirements.determined",
        "Applicable: " + ", ".join(r.title for r in updated.requirements),
    )
    await ctx.bus.publish(events.REQUIREMENTS_DETERMINED, {"journey_id": journey.id})
