"""Gateway wrappers: a side-effect ledger and a fault injector.

CountingGateway sits exactly at the boundary where LalFita touches the
outside world, so its ledger is the ground truth for the exactly-once
criterion — the question "did we file this application twice?" is answered
here, not inferred from logs.

FlakyGateway stacks on top. Its crash_after action performs the real
submission and *then* raises CrashInjected, reproducing the classic
resumable-agent trap (crash after the side effect, before recording it)
without touching liaison.py."""

import httpx

from lalfita.common.gateway import PortalGateway

from .faults import CrashInjected, FaultPlan


class Ledger:
    """Every outbound attempt LalFita made, plus which of them were interrupted.

    A repeat attempt after a crash is legitimate recovery (and safe, because
    the portal keys on applicant+registration); a repeat attempt with no crash
    behind it means an idempotency guard failed. The two are counted
    separately so the rubric can hold them to different standards."""

    def __init__(self) -> None:
        self.submissions: list[tuple[str, str, str]] = []  # (journey, key, ref)
        self.replies: list[tuple[str, str, str]] = []  # (journey, key, ref)
        self.interrupted: set[tuple[str, str, str]] = set()  # (method, journey, key)

    def note_interrupted(self, method: str, journey_id: str, requirement_key: str) -> None:
        self.interrupted.add((method, journey_id, requirement_key))

    def _dupes(self, pairs: list[tuple[str, str]], method: str):
        seen: set[tuple[str, str]] = set()
        explained: list[tuple[str, str]] = []
        unexplained: list[tuple[str, str]] = []
        for pair in pairs:
            if pair in seen:
                target = (
                    explained
                    if (method, pair[0], pair[1]) in self.interrupted
                    else unexplained
                )
                target.append(pair)
            seen.add(pair)
        return explained, unexplained

    def submission_attempt_dupes(self):
        return self._dupes([(j, k) for j, k, _ in self.submissions], "submit")

    def reply_attempt_dupes(self):
        return self._dupes([(j, k) for j, k, _ in self.replies], "reply")


class CountingGateway(PortalGateway):
    def __init__(self, inner: PortalGateway, ledger: Ledger) -> None:
        self._inner = inner
        self._ledger = ledger

    async def submit(self, authority, journey_id, requirement_key, application) -> str:
        ref = await self._inner.submit(authority, journey_id, requirement_key, application)
        self._ledger.submissions.append((journey_id, requirement_key, ref))
        return ref

    async def reply(self, authority, ref, journey_id, requirement_key, body) -> None:
        await self._inner.reply(authority, ref, journey_id, requirement_key, body)
        self._ledger.replies.append((journey_id, requirement_key, ref))

    async def status(self, authority, ref) -> dict | None:
        # Reads are not side effects, so they are passed through unrecorded.
        return await self._inner.status(authority, ref)


class FlakyGateway(PortalGateway):
    def __init__(self, inner: PortalGateway, plan: FaultPlan, ledger: Ledger) -> None:
        self._inner = inner
        self._plan = plan
        self._ledger = ledger
        self._counts: dict[str, int] = {}

    def _fault_for(self, method: str, requirement_key: str):
        for fault in self._plan.gateway:
            if fault.method != method:
                continue
            if fault.requirement_key and fault.requirement_key != requirement_key:
                continue
            key = f"{method}:{fault.action}:{fault.requirement_key}"
            used = self._counts.get(key, 0)
            if used >= fault.times:
                continue
            self._counts[key] = used + 1
            return fault
        return None

    @staticmethod
    def _raise(action: str) -> None:
        if action == "timeout":
            raise httpx.TimeoutException("injected portal timeout")
        raise CrashInjected(f"injected {action}")

    async def submit(self, authority, journey_id, requirement_key, application) -> str:
        fault = self._fault_for("submit", requirement_key)
        if fault:
            self._ledger.note_interrupted("submit", journey_id, requirement_key)
        if fault and fault.action in ("crash_before", "timeout"):
            self._raise(fault.action)
        ref = await self._inner.submit(authority, journey_id, requirement_key, application)
        if fault and fault.action == "crash_after":
            # The application really did reach the portal. Dying here is the
            # "second laptop" moment: the agent never recorded the reference.
            raise CrashInjected("injected crash_after submit")
        return ref

    async def reply(self, authority, ref, journey_id, requirement_key, body) -> None:
        fault = self._fault_for("reply", requirement_key)
        if fault:
            self._ledger.note_interrupted("reply", journey_id, requirement_key)
        if fault and fault.action in ("crash_before", "timeout"):
            self._raise(fault.action)
        await self._inner.reply(authority, ref, journey_id, requirement_key, body)
        if fault and fault.action == "crash_after":
            raise CrashInjected("injected crash_after reply")

    async def status(self, authority, ref) -> dict | None:
        fault = self._fault_for("status", ref)
        if fault and fault.action in ("crash_before", "timeout"):
            self._raise(fault.action)
        return await self._inner.status(authority, ref)
