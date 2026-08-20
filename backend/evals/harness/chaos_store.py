"""ChaosStore — the store is the one dependency Round 1 never faulted.

Firestore does fail in production: transactions abort under contention, reads
and writes hit transient unavailability, and — worst of all — a write can
succeed at the server while the client sees an error. That last case is the
one that breaks naive retry logic, so it gets its own action here."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lalfita.common.schemas import Approval, Deadline, Journey, TimelineEntry
from lalfita.common.store import Store


class StoreUnavailable(Exception):
    """The store refused the operation (transient backend failure)."""


@dataclass
class StoreFault:
    method: str  # get_journey | mutate_journey | append_timeline | save_approval | ...
    action: str  # fail | abort | ambiguous | slow
    times: int = 1
    nth: int = 1  # start failing at the nth call of this method
    delay_s: float = 0.0


@dataclass
class StorePlan:
    faults: list[StoreFault] = field(default_factory=list)


class ChaosStore(Store):
    """Delegating wrapper. Every Store method is forwarded; the ones named in
    the plan misbehave first."""

    def __init__(self, inner: Store, plan: StorePlan) -> None:
        self._inner = inner
        self._plan = plan
        self._counts: dict[str, int] = {}
        self.injected: list[str] = []

    def _fault_for(self, method: str) -> StoreFault | None:
        self._counts[method] = self._counts.get(method, 0) + 1
        n = self._counts[method]
        for fault in self._plan.faults:
            if fault.method != method:
                continue
            unlimited = fault.times == 0
            if unlimited and n >= fault.nth or (fault.nth <= n < fault.nth + fault.times):
                self.injected.append(f"{method}:{fault.action}")
                return fault
        return None

    async def _maybe_fail(self, method: str) -> StoreFault | None:
        import asyncio

        fault = self._fault_for(method)
        if fault is None:
            return None
        if fault.delay_s:
            await asyncio.sleep(fault.delay_s)
        if fault.action in ("fail", "abort"):
            raise StoreUnavailable(f"injected {fault.action} on {method}")
        return fault  # "ambiguous" and "slow" are handled by the caller

    # -- journeys ------------------------------------------------------------

    async def create_journey(self, journey: Journey) -> None:
        await self._maybe_fail("create_journey")
        await self._inner.create_journey(journey)

    async def get_journey(self, journey_id: str) -> Journey | None:
        await self._maybe_fail("get_journey")
        return await self._inner.get_journey(journey_id)

    async def save_journey(self, journey: Journey) -> None:
        fault = await self._maybe_fail("save_journey")
        await self._inner.save_journey(journey)
        if fault and fault.action == "ambiguous":
            raise StoreUnavailable("injected ambiguous write on save_journey")

    async def mutate_journey(
        self, journey_id: str, fn: Callable[[Journey], Any]
    ) -> tuple[Journey | None, Any]:
        fault = await self._maybe_fail("mutate_journey")
        result = await self._inner.mutate_journey(journey_id, fn)
        if fault and fault.action == "ambiguous":
            # The mutation IS committed, but the caller is told it failed —
            # the nastiest real-world case, and the one a claim must survive.
            raise StoreUnavailable("injected ambiguous write on mutate_journey")
        return result

    async def list_journeys(self) -> list[Journey]:
        await self._maybe_fail("list_journeys")
        return await self._inner.list_journeys()

    # -- timeline ------------------------------------------------------------

    async def append_timeline(self, journey_id: str, entry: TimelineEntry) -> None:
        await self._maybe_fail("append_timeline")
        await self._inner.append_timeline(journey_id, entry)

    async def get_timeline(self, journey_id: str) -> list[TimelineEntry]:
        await self._maybe_fail("get_timeline")
        return await self._inner.get_timeline(journey_id)

    # -- approvals -----------------------------------------------------------

    async def create_approval(self, approval: Approval) -> None:
        await self._maybe_fail("create_approval")
        await self._inner.create_approval(approval)

    async def get_approval(self, approval_id: str) -> Approval | None:
        await self._maybe_fail("get_approval")
        return await self._inner.get_approval(approval_id)

    async def save_approval(self, approval: Approval) -> None:
        await self._maybe_fail("save_approval")
        await self._inner.save_approval(approval)

    async def list_approvals(self, journey_id: str, status=None) -> list[Approval]:
        await self._maybe_fail("list_approvals")
        return await self._inner.list_approvals(journey_id, status)

    # -- deadlines -----------------------------------------------------------

    async def create_deadline(self, deadline: Deadline) -> None:
        await self._maybe_fail("create_deadline")
        await self._inner.create_deadline(deadline)

    async def save_deadline(self, deadline: Deadline) -> None:
        await self._maybe_fail("save_deadline")
        await self._inner.save_deadline(deadline)

    async def list_active_deadlines(self) -> list[Deadline]:
        await self._maybe_fail("list_active_deadlines")
        return await self._inner.list_active_deadlines()

    async def list_deadlines(self, journey_id: str) -> list[Deadline]:
        await self._maybe_fail("list_deadlines")
        return await self._inner.list_deadlines(journey_id)
