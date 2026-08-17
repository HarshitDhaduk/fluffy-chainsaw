"""Pathfinder — determines which registrations actually apply.

Rules are researched with Gemini + Google Search grounding, not hardcoded:
that's what makes the engine generalize beyond GST/FSSAI."""

import json

from ..common import events, llm
from ..common.fixtures import PATHFINDER_DETERMINATION
from ..common.schemas import JourneyStatus, Requirement
from .context import Context

INSTRUCTION = """You are Pathfinder, a compliance-research agent for Indian small
businesses. Given a business goal and profile, determine the minimal set of
registrations/licenses required. Use Google Search to verify current rules and
thresholds; cite sources. Respond ONLY with JSON:
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


async def on_journey_created(ctx: Context, payload: dict) -> None:
    journey = await ctx.store.get_journey(payload["journey_id"])
    if journey is None or journey.requirements:  # idempotency guard
        return

    await ctx.set_status(journey.id, JourneyStatus.RESEARCHING)
    await ctx.log(journey.id, "pathfinder", "research.started", f"Researching: “{journey.goal}”")

    prompt = f"Goal: {journey.goal}\nProfile: {json.dumps(journey.profile)}"
    result = await llm.run_agent(build_agent, prompt, offline_fixture=PATHFINDER_DETERMINATION)
    requirements = [Requirement.model_validate(r) for r in result["requirements"]]

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
