"""Declarative fault specifications.

One FaultPlan drives every injector, so a scenario reads as data rather than
as setup code."""

from dataclasses import dataclass, field


class CrashInjected(Exception):
    """Simulated process death mid-handler.

    Agent code never catches this, so raising it from a wrapped dependency
    aborts the handler at exactly that line — the same observable outcome as
    a Cloud Run instance dying before it acknowledged the event."""


@dataclass
class BusFault:
    event_type: str
    action: str  # duplicate | drop_then_redeliver | delay
    nth: int = 1  # apply to the nth publish of this event type (1-based)
    delay_s: float = 0.2
    times: int = 1  # how many occurrences to affect (0 = all)


@dataclass
class LlmFault:
    agent_module: str  # substring of build_agent.__module__, e.g. "pathfinder"
    action: str  # raise | malformed
    times: int = 1
    payload: dict = field(default_factory=dict)  # for malformed


@dataclass
class GatewayFault:
    method: str  # submit | reply
    action: str  # crash_after | crash_before | timeout
    requirement_key: str | None = None  # limit to one authority/registration
    times: int = 1


@dataclass
class FaultPlan:
    seed: int = 0
    bus: list[BusFault] = field(default_factory=list)
    llm: list[LlmFault] = field(default_factory=list)
    gateway: list[GatewayFault] = field(default_factory=list)
    store: list = field(default_factory=list)  # list[StoreFault]
    notifier_raises: bool = False
    max_redeliveries: int = 3
    # Redelivery backoff models Pub/Sub's ack deadline: it must exceed the
    # submission lease, or every retry arrives while the dead worker's claim
    # still looks alive and recovery can never happen.
    redelivery_delay_s: float = 0.7

    def bus_faults_for(self, event_type: str) -> list[BusFault]:
        return [f for f in self.bus if f.event_type == event_type]
