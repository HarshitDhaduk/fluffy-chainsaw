"""Dashboard API routes. Built as a factory so local mode (in-memory) and
cloud mode (Firestore + Pub/Sub) mount the identical surface."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..agents.context import Context
from ..common import events
from ..common.schemas import ApprovalStatus, DocumentRecord, Journey, utcnow


class JourneyIn(BaseModel):
    goal: str
    profile: dict = {}


class DecisionIn(BaseModel):
    approve: bool = True


def build_router(ctx: Context) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "service": "api"}

    @router.post("/journeys")
    async def create_journey(body: JourneyIn) -> dict:
        journey = Journey(goal=body.goal, profile=body.profile)
        await ctx.store.create_journey(journey)
        await ctx.log(journey.id, "user", "journey.created", f"Goal: “{journey.goal}”")
        await ctx.bus.publish(events.JOURNEY_CREATED, {"journey_id": journey.id})
        return {"journey_id": journey.id}

    @router.get("/journeys")
    async def list_journeys() -> list[dict]:
        journeys = await ctx.store.list_journeys()
        return [j.model_dump(mode="json") for j in sorted(journeys, key=lambda j: j.created_at)]

    @router.get("/journeys/{journey_id}")
    async def get_journey(journey_id: str) -> dict:
        journey = await ctx.store.get_journey(journey_id)
        if journey is None:
            raise HTTPException(404, "journey not found")
        timeline = await ctx.store.get_timeline(journey_id)
        approvals = await ctx.store.list_approvals(journey_id)
        deadlines = await ctx.store.list_deadlines(journey_id)
        return {
            **journey.model_dump(mode="json"),
            "timeline": [t.model_dump(mode="json") for t in sorted(timeline, key=lambda t: t.ts)],
            "approvals": [a.model_dump(mode="json") for a in approvals],
            "deadlines": [
                d.model_dump(mode="json") for d in sorted(deadlines, key=lambda d: d.due_at)
            ],
        }

    @router.post("/journeys/{journey_id}/documents")
    async def upload_document(
        journey_id: str,
        kind: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict:
        journey = await ctx.store.get_journey(journey_id)
        if journey is None:
            raise HTTPException(404, "journey not found")
        if journey.required_documents and kind not in journey.required_documents:
            raise HTTPException(400, f"unexpected document kind '{kind}'")

        content = await file.read()
        doc = DocumentRecord(
            kind=kind,
            filename=file.filename or kind,
            content_type=file.content_type,
        )
        if ctx.blobs is not None:
            doc.blob_uri = await ctx.blobs.put(
                journey_id, doc.id, doc.filename, content,
                doc.content_type or "application/octet-stream",
            )
        # A re-upload of the same kind replaces the old document (the
        # corrected-utility-bill flow).
        journey.documents = [d for d in journey.documents if d.kind != kind] + [doc]
        await ctx.store.save_journey(journey)
        await ctx.log(journey_id, "user", "document.uploaded", f"Uploaded {kind}: {doc.filename}")
        await ctx.bus.publish(
            events.DOCUMENT_UPLOADED, {"journey_id": journey_id, "document_id": doc.id}
        )
        return {"document_id": doc.id}

    @router.post("/approvals/{approval_id}/decision")
    async def decide(approval_id: str, body: DecisionIn) -> dict:
        approval = await ctx.store.get_approval(approval_id)
        if approval is None:
            raise HTTPException(404, "approval not found")
        if approval.status != ApprovalStatus.PENDING:
            return {"status": approval.status}  # idempotent double-tap

        approval.status = ApprovalStatus.APPROVED if body.approve else ApprovalStatus.REJECTED
        approval.resolved_at = utcnow()
        await ctx.store.save_approval(approval)
        await ctx.log(
            approval.journey_id, "user",
            f"approval.{approval.status.value}", approval.summary,
        )
        if body.approve:
            await ctx.bus.publish(
                events.APPROVAL_GRANTED,
                {
                    "journey_id": approval.journey_id,
                    "approval_id": approval.id,
                    "kind": approval.kind,
                    **approval.payload,
                },
            )
        return {"status": approval.status}

    return router
