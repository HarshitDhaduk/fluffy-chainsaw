"""ChaosBus — an InProcessBus that misbehaves like a real distributed bus.

Production InProcessBus logs and drops handler exceptions (bus.py), which is
right for a single-process dev skeleton but hides the property we actually
ship on: Pub/Sub redelivers anything that wasn't acknowledged. ChaosBus adds
that redelivery so crash faults can be evaluated locally, and can duplicate,
delay, or drop-then-redeliver events on demand."""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from lalfita.common.bus import InProcessBus

from .faults import CrashInjected, FaultPlan

log = logging.getLogger(__name__)


@dataclass
class TraceEntry:
    seq: int
    event_type: str
    payload: dict
    kind: str  # published | duplicated | delayed | redelivered | crashed


@dataclass
class EventTrace:
    entries: list[TraceEntry] = field(default_factory=list)
    _seq: int = 0

    def add(self, event_type: str, payload: dict, kind: str) -> None:
        self._seq += 1
        self.entries.append(TraceEntry(self._seq, event_type, dict(payload), kind))

    def count(self, event_type: str, kind: str | None = None) -> int:
        return sum(
            1
            for e in self.entries
            if e.event_type == event_type and (kind is None or e.kind == kind)
        )

    @property
    def crashes(self) -> int:
        return sum(1 for e in self.entries if e.kind == "crashed")

    @property
    def redeliveries(self) -> int:
        return sum(1 for e in self.entries if e.kind == "redelivered")


class ChaosBus(InProcessBus):
    def __init__(self, plan: FaultPlan) -> None:
        super().__init__()
        self._plan = plan
        self.trace = EventTrace()
        self._publish_counts: dict[str, int] = defaultdict(int)
        self._delivery_counts: dict[tuple[str, str], int] = defaultdict(int)

    async def publish(self, event_type: str, payload: dict) -> None:
        self._publish_counts[event_type] += 1
        n = self._publish_counts[event_type]

        for fault in self._plan.bus_faults_for(event_type):
            if not self._applies(fault, n):
                continue
            if fault.action == "duplicate":
                self.trace.add(event_type, payload, "published")
                await super().publish(event_type, payload)
                self.trace.add(event_type, payload, "duplicated")
                await super().publish(event_type, payload)
                return
            if fault.action == "drop_then_redeliver":
                self.trace.add(event_type, payload, "delayed")
                self._schedule(fault.delay_s, event_type, payload, "redelivered")
                return
            if fault.action == "delay":
                self.trace.add(event_type, payload, "delayed")
                self._schedule(fault.delay_s, event_type, payload, "published")
                return

        self.trace.add(event_type, payload, "published")
        await super().publish(event_type, payload)

    @staticmethod
    def _applies(fault, n: int) -> bool:
        if fault.times == 0:
            return n >= fault.nth
        return fault.nth <= n < fault.nth + fault.times

    def _schedule(self, delay: float, event_type: str, payload: dict, kind: str) -> None:
        async def later() -> None:
            await asyncio.sleep(delay)
            self.trace.add(event_type, payload, kind)
            await super(ChaosBus, self).publish(event_type, payload)

        task = asyncio.create_task(later())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, handler, event_type: str, payload: dict) -> None:
        """Deliver one event, redelivering anything the handler failed to
        process. In production a handler that raises returns a 500 to the
        Pub/Sub push subscription, which never acks and therefore redelivers —
        so *any* exception earns a retry here, not just injected crashes.
        (The local InProcessBus logs and drops; this is the cloud behavior the
        evals need to measure.)"""
        try:
            await handler(payload)
        except Exception as exc:
            key = (event_type, str(sorted(payload.items())))
            self._delivery_counts[key] += 1
            self.trace.add(event_type, payload, "crashed")
            if not isinstance(exc, CrashInjected):
                log.info("handler for %s failed (%s); redelivering", event_type, exc)
            if self._delivery_counts[key] <= self._plan.max_redeliveries:
                self._schedule(
                    self._plan.redelivery_delay_s, event_type, payload, "redelivered"
                )
