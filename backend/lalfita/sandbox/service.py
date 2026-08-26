"""Standalone sandbox-government service (cloud mode).

Deployed as its own Cloud Run service; responses are delivered back to the
agents service via webhook POST, which keeps the decoupling honest — the
agents never share a process with the 'government' in the cloud. The agents
service requires authentication, so webhooks carry an OIDC identity token
minted for this service's runtime service account."""

import asyncio
import os
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..common import config
from .portals import SandboxGovernment

app = FastAPI(title="LalFita Sandbox Government")


def _id_token() -> str:
    """Mint an OIDC token for the agents service (audience = service root)."""
    import google.auth.transport.requests
    from google.oauth2 import id_token

    url = urlparse(config.AGENTS_WEBHOOK_URL)
    audience = f"{url.scheme}://{url.netloc}"
    return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)


async def _webhook_notify(payload: dict) -> None:
    headers = {}
    if os.environ.get("K_SERVICE"):  # on Cloud Run, authenticate to the locked agents service
        headers["Authorization"] = f"Bearer {await asyncio.to_thread(_id_token)}"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(config.AGENTS_WEBHOOK_URL, json=payload, headers=headers)


government = SandboxGovernment(notify=_webhook_notify)


class SubmissionIn(BaseModel):
    journey_id: str
    requirement_key: str
    application: dict = {}


class ReplyIn(BaseModel):
    journey_id: str
    requirement_key: str
    body: dict = {}


# See the note in agents/service.py: /healthz is shadowed by Google's frontend.
@app.get("/health")
@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "sandbox"}


@app.post("/portals/{authority}/applications")
async def submit(authority: str, sub: SubmissionIn) -> dict:
    ref = await government.submit(authority, sub.journey_id, sub.requirement_key, sub.application)
    return {"reference": ref}


@app.get("/portals/{authority}/applications/{ref}")
async def status(authority: str, ref: str) -> dict:
    """Where does this application stand? Answers even if the push
    notification never reached the agent fleet."""
    result = government.status(ref)
    if result is None:
        raise HTTPException(404, "unknown application reference")
    return result


@app.post("/portals/{authority}/applications/{ref}/reply")
async def reply(authority: str, ref: str, body: ReplyIn) -> dict:
    await government.reply(ref, body.journey_id, body.requirement_key, body.body)
    return {"ok": True}
