"""The sandbox government: mock FoSCoS and GST portals.

Real portals are OTP/captcha-gated by design, so the demo runs against these
stand-ins, which behave like the real thing on a time-compressed clock:
acknowledgements, a mid-process clarification notice (the GST REG-03 moment),
and eventual approvals — all delivered asynchronously via a notify callback
(local: straight onto the event bus; cloud: webhook POST to the agents
service)."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from ..common import config
from ..common.schemas import new_id

log = logging.getLogger(__name__)

Notify = Callable[[dict], Awaitable[None]]


class SandboxGovernment:
    """One instance simulates every authority. Scenario scripts live here —
    tune them per demo take without touching agent code."""

    def __init__(self, notify: Notify) -> None:
        self._notify = notify
        self._tasks: set[asyncio.Task] = set()
        self._pending_replies: dict[str, dict] = {}

    # -- public "portal" surface ---------------------------------------------

    async def submit(
        self, authority: str, journey_id: str, requirement_key: str, application: dict
    ) -> str:
        ref = new_id("arn").upper()
        log.info("[sandbox:%s] received application %s", authority, ref)
        if requirement_key == "gst":
            self._later(0.5, self._respond(journey_id, requirement_key, ref, "ack"))
            self._later(2.0, self._respond(journey_id, requirement_key, ref, "notice"))
        elif requirement_key == "fssai_basic":
            self._later(0.5, self._respond(journey_id, requirement_key, ref, "ack"))
            self._later(4.0, self._respond(journey_id, requirement_key, ref, "approved"))
        else:  # udyam and anything else: fast lane
            self._later(1.0, self._respond(journey_id, requirement_key, ref, "approved"))
        return ref

    async def reply(self, ref: str, journey_id: str, requirement_key: str, body: dict) -> None:
        log.info("[sandbox] received notice reply for %s", ref)
        self._pending_replies.pop(ref, None)
        self._later(1.5, self._respond(journey_id, requirement_key, ref, "approved"))

    # -- internals -------------------------------------------------------------

    def _later(self, sim_days: float, coro: Awaitable[None]) -> None:
        async def runner() -> None:
            await asyncio.sleep(config.days(sim_days).total_seconds())
            await coro

        task = asyncio.create_task(runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _respond(self, journey_id: str, requirement_key: str, ref: str, kind: str) -> None:
        payload: dict = {
            "journey_id": journey_id,
            "requirement_key": requirement_key,
            "reference": ref,
            "kind": kind,
        }
        if kind == "ack":
            payload["message"] = f"Application {ref} received and under review."
        elif kind == "notice":
            self._pending_replies[ref] = payload
            payload["message"] = (
                "Clarification required regarding principal place of business "
                "(residential premises). Reply within 7 days or the application "
                "will be rejected."
            )
            payload["reply_deadline_days"] = 7
        elif kind == "approved":
            payload["registration_number"] = self._registration_number(requirement_key)
            payload["message"] = f"Application {ref} approved."
        await self._notify(payload)

    @staticmethod
    def _registration_number(requirement_key: str) -> str:
        n = random.randint(10**9, 10**10 - 1)
        prefixes = {"gst": "24", "fssai_basic": "107", "udyam": "UDYAM-GJ-01-"}
        return f"{prefixes.get(requirement_key, 'REG-')}{n}"
