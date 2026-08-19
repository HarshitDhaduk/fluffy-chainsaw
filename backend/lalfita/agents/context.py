"""Shared dependencies handed to every agent handler. Agents hold no private
state — everything flows through the store and the bus."""

import logging
from dataclasses import dataclass

from ..common.blobs import BlobStore
from ..common.bus import EventBus
from ..common.gateway import PortalGateway
from ..common.notify import Notifier
from ..common.schemas import Journey, JourneyStatus, TimelineEntry
from ..common.store import Store

log = logging.getLogger(__name__)


@dataclass
class Context:
    store: Store
    bus: EventBus
    gateway: PortalGateway
    blobs: BlobStore | None = None
    notifier: Notifier | None = None

    async def log(self, journey_id: str, actor: str, event: str, detail: str) -> None:
        await self.store.append_timeline(
            journey_id, TimelineEntry(actor=actor, event=event, detail=detail)
        )

    async def set_status(self, journey_id: str, status: JourneyStatus) -> None:
        """Atomic status transition — never clobbers concurrent field writes."""

        def apply(journey: Journey) -> None:
            journey.status = status

        await self.store.mutate_journey(journey_id, apply)

    async def notify(self, journey_id: str, title: str, message: str) -> None:
        """Reach the human wherever they are: timeline always, plus any
        configured push/webhook channels (best-effort)."""
        await self.log(journey_id, "notifier", "notification.sent", f"📱 {title} — {message}")
        if self.notifier is not None:
            try:
                await self.notifier.send(journey_id, title, message)
            except Exception:
                log.exception("notification channel failed (best-effort, continuing)")
