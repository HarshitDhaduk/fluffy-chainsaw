"""Standalone dashboard API service (cloud mode)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.context import Context
from ..common import config
from ..common.bus import PubSubBus
from ..common.gateway import HttpGateway
from ..common.store import FirestoreStore
from .routes import build_router

app = FastAPI(title="LalFita API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

ctx = Context(
    store=FirestoreStore(config.GCP_PROJECT or None),
    bus=PubSubBus(config.GCP_PROJECT, config.PUBSUB_TOPIC),
    gateway=HttpGateway(),
)
app.include_router(build_router(ctx))
