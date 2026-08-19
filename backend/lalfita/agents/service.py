"""Agents service (cloud mode) — one Cloud Run service hosting the fleet.

Receives events via Pub/Sub push, portal webhooks from the sandbox service,
and scheduler ticks from Cloud Scheduler. All three funnel into the same
registry dispatch, so cloud and local behavior are identical."""

import base64
import json

from fastapi import FastAPI, Request

from ..common import config, events
from ..common.blobs import GcsBlobStore
from ..common.bus import PubSubBus
from ..common.gateway import HttpGateway
from ..common.notify import build_notifier
from ..common.store import FirestoreStore
from . import registry
from .context import Context

app = FastAPI(title="LalFita Agent Fleet")

_ctx: Context | None = None


def get_ctx() -> Context:
    global _ctx
    if _ctx is None:
        _ctx = Context(
            store=FirestoreStore(config.GCP_PROJECT or None),
            bus=PubSubBus(config.GCP_PROJECT, config.PUBSUB_TOPIC),
            gateway=HttpGateway(),
            blobs=GcsBlobStore(config.GCS_BUCKET) if config.GCS_BUCKET else None,
            notifier=build_notifier(),
        )
    return _ctx


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "agents"}


@app.post("/pubsub/push")
async def pubsub_push(request: Request) -> dict:
    """Pub/Sub push endpoint. Message attributes carry the event type."""
    envelope = await request.json()
    message = envelope.get("message", {})
    event_type = message.get("attributes", {}).get("type", "")
    payload = json.loads(base64.b64decode(message.get("data", b"") or b"{}"))
    await registry.dispatch(get_ctx(), event_type, payload)
    return {"ok": True}


@app.post("/webhooks/portal")
async def portal_webhook(request: Request) -> dict:
    """Sandbox government delivers responses here."""
    payload = await request.json()
    await registry.dispatch(get_ctx(), events.PORTAL_RESPONSE, payload)
    return {"ok": True}


@app.post("/tasks/tick")
async def scheduler_tick() -> dict:
    """Cloud Scheduler wakes the Sentinel here."""
    await registry.dispatch(get_ctx(), events.DEADLINE_TICK, {})
    return {"ok": True}
