"""Event → handler routing table. One place to see the whole choreography."""

from collections.abc import Awaitable, Callable

from ..common import events
from ..common.schemas import ApprovalKind
from . import chaos, clerk, liaison, pathfinder, planner, sentinel
from .context import Context

Handler = Callable[[Context, dict], Awaitable[None]]


async def _route_approval(ctx: Context, payload: dict) -> None:
    kind = payload.get("kind")
    if kind == ApprovalKind.DOCUMENT_FIX:
        await clerk.on_document_fix_approved(ctx, payload)
    elif kind == ApprovalKind.SUBMISSION:
        await liaison.on_submission_approved(ctx, payload)
    elif kind == ApprovalKind.NOTICE_REPLY:
        await liaison.on_notice_reply_approved(ctx, payload)


ROUTES: dict[str, list[Handler]] = {
    events.JOURNEY_CREATED: [pathfinder.on_journey_created],
    events.REQUIREMENTS_DETERMINED: [planner.on_requirements_determined],
    events.PLAN_READY: [clerk.on_plan_ready],
    events.DOCUMENT_UPLOADED: [clerk.on_document_uploaded],
    events.APPROVAL_GRANTED: [_route_approval],
    events.PORTAL_RESPONSE: [liaison.on_portal_response],
    events.DEADLINE_TICK: [sentinel.on_deadline_tick],
    events.RESYNC_REQUESTED: [liaison.on_resync_requested],
    events.DEMO_CRASH: [chaos.on_demo_crash],
}


def bind(bus, ctx: Context) -> None:
    """Attach all routes to an InProcessBus (local mode)."""
    for event_type, handlers in ROUTES.items():
        for handler in handlers:
            async def bound(payload: dict, _h: Handler = handler) -> None:
                await _h(ctx, payload)

            bus.subscribe(event_type, bound)


async def dispatch(ctx: Context, event_type: str, payload: dict) -> None:
    """Dispatch one event (cloud mode: called from the Pub/Sub push endpoint)."""
    for handler in ROUTES.get(event_type, []):
        await handler(ctx, payload)
