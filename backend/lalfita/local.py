"""Local composition root — the walking skeleton.

One process, zero GCP dependencies: in-memory store, in-process event bus,
in-process sandbox government, and a background Sentinel ticker. Run it:

    uvicorn lalfita.local:app --port 8080

Then create a journey and watch the whole choreography unfold. In the cloud
the exact same handlers run split across three Cloud Run services."""

import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents import registry
from .agents.context import Context
from .api.routes import build_router
from .common import config, events
from .common.blobs import InMemoryBlobStore
from .common.bus import InProcessBus
from .common.gateway import LocalGateway
from .common.notify import build_notifier
from .common.store import InMemoryStore
from .sandbox.portals import SandboxGovernment

_UNSET = object()


def build_app(
    *,
    bus=None,
    store=None,
    wrap_gateway=None,
    notifier=_UNSET,
) -> tuple[FastAPI, Context]:
    """Compose the walking skeleton. The keyword seams exist for the eval
    harness (backend/evals) to inject faulty implementations without touching
    agent code; default behavior is unchanged."""
    bus = bus or InProcessBus()
    store = store or InMemoryStore()

    async def portal_notify(payload: dict) -> None:
        await bus.publish(events.PORTAL_RESPONSE, payload)

    government = SandboxGovernment(notify=portal_notify)
    gateway = LocalGateway(government)
    if wrap_gateway is not None:
        gateway = wrap_gateway(gateway)

    ctx = Context(
        store=store,
        bus=bus,
        gateway=gateway,
        blobs=InMemoryBlobStore(),
        notifier=build_notifier() if notifier is _UNSET else notifier,
    )
    registry.bind(bus, ctx)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async def ticker() -> None:
            while True:
                await asyncio.sleep(max(config.days(0.25).total_seconds(), 0.05))
                await bus.publish(events.DEADLINE_TICK, {})

        task = asyncio.create_task(ticker())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="LalFita (local walking skeleton)", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(build_router(ctx))
    app.state.government = government  # exposed for evals (side-effect ground truth)

    return app, ctx


app, ctx = build_app()
