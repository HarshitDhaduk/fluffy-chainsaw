"""Standalone sandbox-government service (cloud mode).

Deployed as its own Cloud Run service; responses are delivered back to the
agents service via webhook POST, which keeps the decoupling honest — the
agents never share a process with the 'government' in the cloud."""

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from ..common import config
from .portals import SandboxGovernment

app = FastAPI(title="LalFita Sandbox Government")


async def _webhook_notify(payload: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(config.AGENTS_WEBHOOK_URL, json=payload)


government = SandboxGovernment(notify=_webhook_notify)


class SubmissionIn(BaseModel):
    journey_id: str
    requirement_key: str
    application: dict = {}


class ReplyIn(BaseModel):
    journey_id: str
    requirement_key: str
    body: dict = {}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "sandbox"}


@app.post("/portals/{authority}/applications")
async def submit(authority: str, sub: SubmissionIn) -> dict:
    ref = await government.submit(authority, sub.journey_id, sub.requirement_key, sub.application)
    return {"reference": ref}


@app.post("/portals/{authority}/applications/{ref}/reply")
async def reply(authority: str, ref: str, body: ReplyIn) -> dict:
    await government.reply(ref, body.journey_id, body.requirement_key, body.body)
    return {"ok": True}
