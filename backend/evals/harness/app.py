"""Compose a faulted LalFita instance from a FaultPlan."""

import contextlib
import random
from dataclasses import dataclass
from unittest import mock

from lalfita.agents.context import Context
from lalfita.common.notify import Notifier
from lalfita.common.store import InMemoryStore
from lalfita.local import build_app

from .chaos_bus import ChaosBus, EventTrace
from .chaos_store import ChaosStore, StorePlan
from .faults import FaultPlan
from .flaky_gateway import CountingGateway, FlakyGateway, Ledger
from .flaky_llm import FlakyLLM


class ExplodingNotifier(Notifier):
    """Every channel is down. Context.notify must absorb this."""

    async def send(self, journey_id: str, title: str, message: str) -> None:
        raise RuntimeError("injected notifier outage")


@dataclass
class EvalApp:
    ctx: Context
    bus: ChaosBus
    store: object
    ledger: Ledger
    trace: EventTrace
    llm: FlakyLLM
    government: object


@contextlib.contextmanager
def build_eval_app(plan: FaultPlan):
    """Yield an EvalApp with every injector installed. Patches are reverted
    on exit so scenarios can't leak into one another."""
    random.seed(plan.seed)

    bus = ChaosBus(plan)
    ledger = Ledger()
    store = InMemoryStore()
    if plan.store:
        store = ChaosStore(store, StorePlan(faults=list(plan.store)))

    def wrap_gateway(inner):
        # Order matters: the ledger records what actually reached the portal,
        # so it must sit inside the fault injector.
        return FlakyGateway(CountingGateway(inner, ledger), plan, ledger)

    flaky_llm = FlakyLLM(plan)
    with mock.patch("lalfita.common.llm.run_agent", flaky_llm):
        app, ctx = build_app(
            bus=bus,
            store=store,
            wrap_gateway=wrap_gateway,
            notifier=ExplodingNotifier() if plan.notifier_raises else None,
        )
        yield EvalApp(
            ctx=ctx,
            bus=bus,
            store=store,
            ledger=ledger,
            trace=bus.trace,
            llm=flaky_llm,
            government=app.state.government,
        )
