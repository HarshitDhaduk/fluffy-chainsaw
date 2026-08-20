"""Portal gateway — how the Liaison talks to the (sandbox) government.

LocalGateway wraps an in-process SandboxGovernment (dev/tests/demo);
HttpGateway calls the deployed sandbox service. Swapping in a real-world
integration later (email, an actual API) means writing one more gateway,
touching zero agent code."""

import httpx

from . import config


class PortalGateway:
    async def submit(
        self, authority: str, journey_id: str, requirement_key: str, application: dict
    ) -> str:
        raise NotImplementedError

    async def reply(
        self, authority: str, ref: str, journey_id: str, requirement_key: str, body: dict
    ) -> None:
        raise NotImplementedError

    async def status(self, authority: str, ref: str) -> dict | None:
        """Ask the authority where an application stands. Used when a pushed
        notification never arrived — see Liaison's resync path."""
        raise NotImplementedError


class LocalGateway(PortalGateway):
    def __init__(self, government) -> None:  # SandboxGovernment
        self._government = government

    async def submit(self, authority, journey_id, requirement_key, application) -> str:
        return await self._government.submit(authority, journey_id, requirement_key, application)

    async def reply(self, authority, ref, journey_id, requirement_key, body) -> None:
        await self._government.reply(ref, journey_id, requirement_key, body)

    async def status(self, authority, ref) -> dict | None:
        return self._government.status(ref)


class HttpGateway(PortalGateway):
    def __init__(self, base_url: str | None = None) -> None:
        self._base = (base_url or config.SANDBOX_BASE_URL).rstrip("/")

    async def submit(self, authority, journey_id, requirement_key, application) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base}/portals/{authority}/applications",
                json={
                    "journey_id": journey_id,
                    "requirement_key": requirement_key,
                    "application": application,
                },
            )
            resp.raise_for_status()
            return resp.json()["reference"]

    async def reply(self, authority, ref, journey_id, requirement_key, body) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._base}/portals/{authority}/applications/{ref}/reply",
                json={"journey_id": journey_id, "requirement_key": requirement_key, "body": body},
            )
            resp.raise_for_status()

    async def status(self, authority, ref) -> dict | None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self._base}/portals/{authority}/applications/{ref}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
