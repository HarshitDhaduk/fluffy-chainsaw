"""Gemini access via Google's Agent Development Kit (ADK).

Each agent module supplies a `build_agent()` returning an ADK LlmAgent; this
runner executes one prompt through it. In offline mode (no credentials) we
return the canned fixture instead so the whole system runs end-to-end without
GCP — same JSON shapes, zero downstream branching.
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from . import config

log = logging.getLogger(__name__)


async def run_agent(build_agent: Callable[[], Any], prompt: str, *, offline_fixture: dict) -> dict:
    """Run one prompt through an ADK agent and parse its JSON reply."""
    if config.offline():
        log.info("LLM offline mode: returning fixture for %s", build_agent.__module__)
        return offline_fixture

    from google.adk.runners import InMemoryRunner
    from google.genai import types

    agent = build_agent()
    runner = InMemoryRunner(agent=agent, app_name="lalfita")
    session = await runner.session_service.create_session(app_name="lalfita", user_id="lalfita")
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    final_text = ""
    async for event in runner.run_async(
        user_id="lalfita", session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)

    return _parse_json(final_text, fallback=offline_fixture)


def _parse_json(text: str, *, fallback: dict) -> dict:
    """Leniently pull a JSON object out of a model reply (handles ``` fences)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            log.warning("LLM reply was not valid JSON; falling back to fixture")
    return fallback
