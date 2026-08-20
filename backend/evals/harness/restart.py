"""Restart harnesses — the strict durability question.

Round 1 proved the fleet survives faults inside a living process. These
harnesses kill the process (or the whole object graph) and rebuild it on the
persisted state alone, which is the only honest way to test the PRD's claim
of "durable state, not durable processes"."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from lalfita.common.store import JsonFileStore
from lalfita.local import build_app

from .chaos_bus import ChaosBus
from .faults import FaultPlan
from .flaky_gateway import CountingGateway, FlakyGateway, Ledger


@dataclass
class InProcessRestart:
    """Discard the whole object graph — bus, agents, sandbox, every in-flight
    task — and rebuild on the same store. Fast, deterministic, and enough to
    catch anything that secretly lived in memory."""

    store: object
    plan: FaultPlan
    ledger: Ledger
    app: object = None
    ctx: object = None
    bus: ChaosBus = None

    def boot(self):
        bus = ChaosBus(self.plan)

        def wrap_gateway(inner):
            return FlakyGateway(CountingGateway(inner, self.ledger), self.plan, self.ledger)

        app, ctx = build_app(store=self.store, bus=bus, wrap_gateway=wrap_gateway, notifier=None)
        self.app, self.ctx, self.bus = app, ctx, bus
        return ctx

    async def kill_and_reboot(self):
        """Simulate process death: cancel everything in flight, drop the
        references, and boot a brand-new world on the same store."""
        for task in list(getattr(self.bus, "_tasks", [])):
            task.cancel()
        government = getattr(self.app.state, "government", None)
        for task in list(getattr(government, "_tasks", [])):
            task.cancel()
        await asyncio.sleep(0.05)
        self.app = self.ctx = self.bus = None
        return self.boot()


class SubprocessRestart:
    """The real thing: uvicorn in its own process, SIGKILLed mid-journey.

    Nothing survives a SIGKILL — no atexit hook, no flush, no graceful
    shutdown. Whatever the restarted process knows, it learned from disk."""

    def __init__(self, port: int = 8099, sim_day_seconds: float = 1.0) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        workdir = tempfile.mkdtemp(prefix="lalfita-durability-")
        self.store_path = os.path.join(workdir, "store.json")
        self.sandbox_path = os.path.join(workdir, "sandbox.json")
        self.sim_day_seconds = sim_day_seconds
        self.process: subprocess.Popen | None = None

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update(
            LALFITA_OFFLINE="1",
            LALFITA_STORE_PATH=self.store_path,
            SANDBOX_STATE_PATH=self.sandbox_path,
            SIM_DAY_SECONDS=str(self.sim_day_seconds),
            SUBMIT_LEASE_SECONDS="5",
            PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        )
        return env

    def start(self, timeout_s: float = 30) -> None:
        self.process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "evals.harness.durable_app:app",
                "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning",
            ],
            env=self._env(),
            cwd=str(Path(__file__).resolve().parents[2]),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base}/healthz", timeout=1).status_code == 200:
                    return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("durable app never became healthy")

    def kill(self) -> None:
        """SIGKILL: no cleanup, no flush, no goodbye."""
        if self.process:
            os.kill(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=10)
            self.process = None

    def restart(self) -> None:
        self.kill()
        self.start()

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    # -- what a human could see between the kill and the restart -------------

    def snapshot_on_disk(self) -> dict:
        return json.loads(Path(self.store_path).read_text() or "{}")

    def store_view(self) -> JsonFileStore:
        return JsonFileStore(self.store_path)

    # -- driving over HTTP, exactly as the dashboard does ---------------------

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base, timeout=10)

    def start_journey(self, goal: str, profile: dict) -> str:
        with self.client() as c:
            return c.post("/journeys", json={"goal": goal, "profile": profile}).json()[
                "journey_id"
            ]

    def journey(self, journey_id: str) -> dict:
        with self.client() as c:
            return c.get(f"/journeys/{journey_id}").json()

    def approve_pending(self, journey_id: str, skip_kinds: tuple[str, ...] = ()) -> int:
        granted = 0
        with self.client() as c:
            for approval in self.journey(journey_id).get("approvals", []):
                if approval["status"] != "pending" or approval["kind"] in skip_kinds:
                    continue
                c.post(f"/approvals/{approval['id']}/decision", json={"approve": True})
                granted += 1
        return granted

    def wait_for(self, journey_id: str, predicate, timeout_s: float = 60, poll_s: float = 0.5):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            journey = self.journey(journey_id)
            if predicate(journey):
                return journey
            self.approve_pending(journey_id, skip_kinds=())
            time.sleep(poll_s)
        raise AssertionError(f"condition never met for {journey_id}")
