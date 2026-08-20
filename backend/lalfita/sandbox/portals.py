"""The sandbox government: mock FoSCoS and GST portals.

Real portals are OTP/captcha-gated by design, so the demo runs against these
stand-ins, which behave like the real thing on a time-compressed clock:
acknowledgements, a mid-process clarification notice (the GST REG-03 moment),
and eventual approvals — all delivered asynchronously via a notify callback
(local: straight onto the event bus; cloud: webhook POST to the agents
service)."""

import asyncio
import json
import logging
import os
import random
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from ..common import config
from ..common.schemas import new_id, utcnow

log = logging.getLogger(__name__)

Notify = Callable[[dict], Awaitable[None]]


class SandboxGovernment:
    """One instance simulates every authority. Scenario scripts live here —
    tune them per demo take without touching agent code."""

    # Each authority's process, as due-times in bureaucratic days from
    # submission. Push notifications are best-effort; `status()` derives the
    # truth from elapsed time, which is how real portals behave — and what
    # lets an authority answer us after OUR process has died and restarted.
    SCHEDULES = {
        "gst": [(0.5, "ack"), (2.0, "notice")],
        "fssai_basic": [(0.5, "ack"), (4.0, "approved")],
    }
    DEFAULT_SCHEDULE = [(1.0, "approved")]
    APPROVAL_AFTER_REPLY_DAYS = 1.5

    def __init__(self, notify: Notify, state_path: str | None = None) -> None:
        self._notify = notify
        self._tasks: set[asyncio.Task] = set()
        self._pending_replies: dict[str, dict] = {}
        self._records: dict[str, dict] = {}  # ref -> durable application record
        # Idempotency ledger: real portals refuse a second application for the
        # same applicant+registration, so the sandbox does too. This is the
        # server-side half of exactly-once (the client half is Liaison's
        # claim-then-submit); the eval suite reads these as ground truth.
        self._applications: dict[tuple[str, str], str] = {}  # (journey, key) -> ref
        self.accepted_applications: list[tuple[str, str, str]] = []
        self.accepted_replies: list[str] = []
        path = state_path or os.environ.get("SANDBOX_STATE_PATH", "")
        self._state_path = Path(path) if path else None
        self._load()

    # -- public "portal" surface ---------------------------------------------

    async def submit(
        self, authority: str, journey_id: str, requirement_key: str, application: dict
    ) -> str:
        dedupe_key = (journey_id, requirement_key)
        if dedupe_key in self._applications:
            existing = self._applications[dedupe_key]
            log.info(
                "[sandbox:%s] duplicate application for %s ignored; returning %s",
                authority, dedupe_key, existing,
            )
            return existing

        ref = new_id("arn").upper()
        self._applications[dedupe_key] = ref
        self.accepted_applications.append((journey_id, requirement_key, ref))
        self._records[ref] = {
            "journey_id": journey_id,
            "requirement_key": requirement_key,
            "authority": authority,
            "submitted_at": utcnow().isoformat(),
            "replied_at": None,
            "registration_number": self._registration_number(requirement_key),
        }
        self._save()
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
        if ref not in self._pending_replies:  # idempotent: duplicate/late replies ignored
            log.info("[sandbox] reply for %s has no pending notice; ignored", ref)
            return
        log.info("[sandbox] received notice reply for %s", ref)
        self._pending_replies.pop(ref, None)
        self.accepted_replies.append(ref)
        if ref in self._records:
            self._records[ref]["replied_at"] = utcnow().isoformat()
            self._save()
        self._later(
            self.APPROVAL_AFTER_REPLY_DAYS,
            self._respond(journey_id, requirement_key, ref, "approved"),
        )

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
            record = self._records.get(ref, {})
            payload["registration_number"] = record.get(
                "registration_number"
            ) or self._registration_number(requirement_key)
            payload["message"] = f"Application {ref} approved."
        await self._notify(payload)

    @staticmethod
    def _registration_number(requirement_key: str) -> str:
        n = random.randint(10**9, 10**10 - 1)
        prefixes = {"gst": "24", "fssai_basic": "107", "udyam": "UDYAM-GJ-01-"}
        return f"{prefixes.get(requirement_key, 'REG-')}{n}"

    # -- status: the authority's own answer, derived from elapsed time --------

    def status(self, ref: str) -> dict | None:
        """What this application looks like to the authority right now.

        Push notifications can be missed — a service is down, a webhook retry
        budget runs out, an email lands in spam. A real portal still knows the
        answer when you go and ask, and derives it from time elapsed rather
        than from whether it managed to tell you. So does this one, which is
        what makes recovery-after-restart possible."""
        record = self._records.get(ref)
        if record is None:
            return None

        submitted = datetime.fromisoformat(record["submitted_at"])
        elapsed_days = (utcnow() - submitted).total_seconds() / config.SIM_DAY_SECONDS
        schedule = self.SCHEDULES.get(record["requirement_key"], self.DEFAULT_SCHEDULE)

        kind = "pending"
        for due_days, transition in schedule:
            if elapsed_days >= due_days:
                kind = transition

        if record.get("replied_at"):
            replied = datetime.fromisoformat(record["replied_at"])
            since_reply = (utcnow() - replied).total_seconds() / config.SIM_DAY_SECONDS
            kind = "approved" if since_reply >= self.APPROVAL_AFTER_REPLY_DAYS else "ack"

        payload = {
            "journey_id": record["journey_id"],
            "requirement_key": record["requirement_key"],
            "reference": ref,
            "kind": kind,
        }
        if kind == "notice":
            self._pending_replies.setdefault(ref, payload)
            payload["message"] = (
                "Clarification required regarding principal place of business "
                "(residential premises). Reply within 7 days or the application "
                "will be rejected."
            )
            payload["reply_deadline_days"] = 7
        elif kind == "approved":
            payload["registration_number"] = record["registration_number"]
            payload["message"] = f"Application {ref} approved."
        elif kind == "ack":
            payload["message"] = f"Application {ref} received and under review."
        return payload

    # -- durability: the authority outlives our process -----------------------

    def _load(self) -> None:
        if not self._state_path or not self._state_path.exists():
            return
        raw = json.loads(self._state_path.read_text() or "{}")
        self._records = raw.get("records", {})
        self._applications = {
            tuple(json.loads(k)): v for k, v in raw.get("applications", {}).items()
        }
        self._pending_replies = raw.get("pending_replies", {})

    def _save(self) -> None:
        if not self._state_path:
            return
        payload = {
            "records": self._records,
            "applications": {
                json.dumps(list(k)): v for k, v in self._applications.items()
            },
            "pending_replies": self._pending_replies,
        }
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self._state_path)
