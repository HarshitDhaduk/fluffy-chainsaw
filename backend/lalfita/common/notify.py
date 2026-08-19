"""Notification fan-out (F8): 'async' should be felt, not claimed.

Every notification is also written to the journey timeline by Context.notify;
these channels additionally push it out of the app:

- NtfyNotifier   — publishes to https://ntfy.sh/<topic>: instant push to any
                   phone with the ntfy app subscribed to the topic. Zero
                   signup, perfect for the demo video. Set NTFY_TOPIC.
- WebhookNotifier — POSTs JSON {journey_id, title, message} to any URL
                   (Slack/Discord-style incoming webhooks). Set
                   NOTIFY_WEBHOOK_URL.

Both are best-effort: a notification failure must never stall a journey."""

import logging
import os

import httpx

log = logging.getLogger(__name__)


class Notifier:
    async def send(self, journey_id: str, title: str, message: str) -> None:
        raise NotImplementedError


class NtfyNotifier(Notifier):
    def __init__(self, topic: str) -> None:
        self._url = f"https://ntfy.sh/{topic}"

    async def send(self, journey_id: str, title: str, message: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                self._url,
                content=message.encode(),
                headers={"Title": title, "Tags": "scroll", "X-Journey": journey_id},
            )


class WebhookNotifier(Notifier):
    def __init__(self, url: str) -> None:
        self._url = url

    async def send(self, journey_id: str, title: str, message: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                self._url,
                json={"journey_id": journey_id, "title": title, "message": message,
                      "text": f"*{title}* — {message}"},  # Slack-compatible field
            )


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier]) -> None:
        self._notifiers = notifiers

    async def send(self, journey_id: str, title: str, message: str) -> None:
        for notifier in self._notifiers:
            try:
                await notifier.send(journey_id, title, message)
            except Exception:
                log.exception("notifier %s failed (best-effort, continuing)", type(notifier))


def build_notifier() -> Notifier | None:
    """Assemble channels from env; None means timeline-only."""
    notifiers: list[Notifier] = []
    if os.environ.get("NTFY_TOPIC"):
        notifiers.append(NtfyNotifier(os.environ["NTFY_TOPIC"]))
    if os.environ.get("NOTIFY_WEBHOOK_URL"):
        notifiers.append(WebhookNotifier(os.environ["NOTIFY_WEBHOOK_URL"]))
    if not notifiers:
        return None
    return CompositeNotifier(notifiers) if len(notifiers) > 1 else notifiers[0]
