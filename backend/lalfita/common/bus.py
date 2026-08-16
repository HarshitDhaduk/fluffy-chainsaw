"""Event bus abstraction.

InProcessBus  — local dev/tests: dispatches to registered handlers in-process.
PubSubBus     — cloud: publishes to a single Pub/Sub topic with a `type`
                attribute; a push subscription delivers to the agents service,
                which routes through the same handler registry. Handlers must
                stay idempotent (Pub/Sub is at-least-once).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class EventBus:
    async def publish(self, event_type: str, payload: dict) -> None:
        raise NotImplementedError


class InProcessBus(EventBus):
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: dict) -> None:
        for handler in self._handlers.get(event_type, []):
            task = asyncio.create_task(self._run(handler, event_type, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, handler: Handler, event_type: str, payload: dict) -> None:
        try:
            await handler(payload)
        except Exception:
            log.exception("handler for %s failed (payload=%s)", event_type, payload)

    async def drain(self) -> None:
        """Wait for in-flight handlers (tests/demo)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


class PubSubBus(EventBus):
    def __init__(self, project: str, topic: str) -> None:
        from google.cloud import pubsub_v1

        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(project, topic)

    async def publish(self, event_type: str, payload: dict) -> None:
        data = json.dumps(payload).encode()
        future = self._publisher.publish(self._topic_path, data, type=event_type)
        await asyncio.get_event_loop().run_in_executor(None, future.result)
