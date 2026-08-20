"""EvalDriver — plays the human and the clock.

Ported from the polling loop the existing tests use: pump deadline ticks,
approve whatever the policy allows, and stop when the journey completes or
the budget runs out. A budget exhaustion is not a harness failure; it is the
finding (the journey stalled and no one was coming to rescue it)."""

import asyncio
from dataclasses import dataclass, field

from lalfita.common import events
from lalfita.common.schemas import ApprovalKind, ApprovalStatus, Journey, JourneyStatus

from .chaos_store import StoreUnavailable

# Approval policies
APPROVE_ALL = "approve_all"
HOLD_NOTICE_REPLY = "hold_notice_reply"  # let the deadline run down
APPROVE_NONE = "approve_none"


@dataclass
class RunResult:
    journey_id: str
    completed: bool
    ticks: int
    approvals_granted: int
    approval_kinds: list[str] = field(default_factory=list)
    duplicate_approval_events: int = 0


class EvalDriver:
    def __init__(
        self,
        app,
        *,
        policy: str = APPROVE_ALL,
        max_ticks: int = 400,
        tick_s: float = 0.05,
        duplicate_approvals: bool = False,
        tick_outage: tuple[int, int] | None = None,
    ) -> None:
        self._app = app
        self._policy = policy
        self._max_ticks = max_ticks
        self._tick_s = tick_s
        self._duplicate_approvals = duplicate_approvals
        self._tick_outage = tick_outage

    def _may_approve(self, kind: str) -> bool:
        if self._policy == APPROVE_NONE:
            return False
        if self._policy == HOLD_NOTICE_REPLY and kind == ApprovalKind.NOTICE_REPLY:
            return False
        return True

    @staticmethod
    async def _tolerant(coro, default):
        """The driver stands in for a human and a scheduler, neither of which
        is under test. A store outage that hits *their* reads just means a
        refresh failed — retry next tick rather than aborting the run."""
        try:
            return await coro
        except StoreUnavailable:
            return default

    async def run(self, goal: str, profile: dict) -> RunResult:
        ctx = self._app.ctx
        journey = Journey(goal=goal, profile=profile)
        for _ in range(20):  # the human retries the "start" button
            try:
                await ctx.store.create_journey(journey)
                break
            except StoreUnavailable:
                await asyncio.sleep(self._tick_s)
        await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})

        result = RunResult(journey_id=journey.id, completed=False, ticks=0, approvals_granted=0)

        for tick in range(1, self._max_ticks + 1):
            result.ticks = tick
            await asyncio.sleep(self._tick_s)
            # A scheduler outage means nobody is pumping the watchdog.
            in_outage = (
                self._tick_outage is not None
                and self._tick_outage[0] <= tick <= self._tick_outage[1]
            )
            if not in_outage:
                await ctx.bus.publish(events.DEADLINE_TICK, {})

            pending = await self._tolerant(
                ctx.store.list_approvals(journey.id, ApprovalStatus.PENDING), []
            )
            for approval in pending:
                if not self._may_approve(approval.kind):
                    continue
                approval.status = ApprovalStatus.APPROVED
                if await self._tolerant(ctx.store.save_approval(approval), "failed") == "failed":
                    continue
                payload = {
                    "journey_id": approval.journey_id,
                    "approval_id": approval.id,
                    "kind": approval.kind,
                    **approval.payload,
                }
                await ctx.bus.publish(events.APPROVAL_GRANTED, payload)
                result.approvals_granted += 1
                result.approval_kinds.append(str(approval.kind))
                if self._duplicate_approvals:
                    # The human double-taps / the bus redelivers.
                    await ctx.bus.publish(events.APPROVAL_GRANTED, payload)
                    result.duplicate_approval_events += 1

            current = await self._tolerant(ctx.store.get_journey(journey.id), None)
            if current and current.status == JourneyStatus.COMPLETED:
                result.completed = True
                break

        await asyncio.sleep(self._tick_s * 2)
        await ctx.bus.drain()
        return result
