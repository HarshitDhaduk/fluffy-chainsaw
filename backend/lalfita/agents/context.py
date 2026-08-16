"""Shared dependencies handed to every agent handler. Agents hold no private
state — everything flows through the store and the bus."""

from dataclasses import dataclass

from ..common.bus import EventBus
from ..common.gateway import PortalGateway
from ..common.schemas import Journey, JourneyStatus, TimelineEntry
from ..common.store import Store


@dataclass
class Context:
    store: Store
    bus: EventBus
    gateway: PortalGateway

    async def log(self, journey_id: str, actor: str, event: str, detail: str) -> None:
        await self.store.append_timeline(
            journey_id, TimelineEntry(actor=actor, event=event, detail=detail)
        )

    async def set_status(self, journey: Journey, status: JourneyStatus) -> None:
        journey.status = status
        await self.store.save_journey(journey)
