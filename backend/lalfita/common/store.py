"""State store abstraction. The journey state machine + audit timeline are the
single source of truth; the dashboard renders straight from here.

InMemoryStore — local dev/tests.
FirestoreStore — cloud (collections: journeys, journeys/{id}/timeline,
                 approvals, deadlines).
"""

from .schemas import Approval, ApprovalStatus, Deadline, Journey, TimelineEntry, utcnow


class Store:
    async def create_journey(self, journey: Journey) -> None: ...
    async def get_journey(self, journey_id: str) -> Journey | None: ...
    async def save_journey(self, journey: Journey) -> None: ...
    async def list_journeys(self) -> list[Journey]: ...
    async def append_timeline(self, journey_id: str, entry: TimelineEntry) -> None: ...
    async def get_timeline(self, journey_id: str) -> list[TimelineEntry]: ...
    async def create_approval(self, approval: Approval) -> None: ...
    async def get_approval(self, approval_id: str) -> Approval | None: ...
    async def save_approval(self, approval: Approval) -> None: ...
    async def list_approvals(
        self, journey_id: str, status: ApprovalStatus | None = None
    ) -> list[Approval]: ...
    async def create_deadline(self, deadline: Deadline) -> None: ...
    async def save_deadline(self, deadline: Deadline) -> None: ...
    async def list_active_deadlines(self) -> list[Deadline]: ...


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._journeys: dict[str, Journey] = {}
        self._timelines: dict[str, list[TimelineEntry]] = {}
        self._approvals: dict[str, Approval] = {}
        self._deadlines: dict[str, Deadline] = {}

    async def create_journey(self, journey: Journey) -> None:
        self._journeys[journey.id] = journey

    async def get_journey(self, journey_id: str) -> Journey | None:
        j = self._journeys.get(journey_id)
        return j.model_copy(deep=True) if j else None

    async def save_journey(self, journey: Journey) -> None:
        journey.updated_at = utcnow()
        self._journeys[journey.id] = journey.model_copy(deep=True)

    async def list_journeys(self) -> list[Journey]:
        return [j.model_copy(deep=True) for j in self._journeys.values()]

    async def append_timeline(self, journey_id: str, entry: TimelineEntry) -> None:
        self._timelines.setdefault(journey_id, []).append(entry)

    async def get_timeline(self, journey_id: str) -> list[TimelineEntry]:
        return list(self._timelines.get(journey_id, []))

    async def create_approval(self, approval: Approval) -> None:
        self._approvals[approval.id] = approval

    async def get_approval(self, approval_id: str) -> Approval | None:
        a = self._approvals.get(approval_id)
        return a.model_copy(deep=True) if a else None

    async def save_approval(self, approval: Approval) -> None:
        self._approvals[approval.id] = approval.model_copy(deep=True)

    async def list_approvals(
        self, journey_id: str, status: ApprovalStatus | None = None
    ) -> list[Approval]:
        return [
            a.model_copy(deep=True)
            for a in self._approvals.values()
            if a.journey_id == journey_id and (status is None or a.status == status)
        ]

    async def create_deadline(self, deadline: Deadline) -> None:
        self._deadlines[deadline.id] = deadline

    async def save_deadline(self, deadline: Deadline) -> None:
        self._deadlines[deadline.id] = deadline.model_copy(deep=True)

    async def list_active_deadlines(self) -> list[Deadline]:
        return [d.model_copy(deep=True) for d in self._deadlines.values() if not d.resolved]


class FirestoreStore(Store):
    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore

        self._db = firestore.AsyncClient(project=project or None)

    async def create_journey(self, journey: Journey) -> None:
        await self._db.collection("journeys").document(journey.id).set(
            journey.model_dump(mode="json")
        )

    async def get_journey(self, journey_id: str) -> Journey | None:
        snap = await self._db.collection("journeys").document(journey_id).get()
        return Journey.model_validate(snap.to_dict()) if snap.exists else None

    async def save_journey(self, journey: Journey) -> None:
        journey.updated_at = utcnow()
        await self._db.collection("journeys").document(journey.id).set(
            journey.model_dump(mode="json")
        )

    async def list_journeys(self) -> list[Journey]:
        return [
            Journey.model_validate(s.to_dict())
            async for s in self._db.collection("journeys").stream()
        ]

    async def append_timeline(self, journey_id: str, entry: TimelineEntry) -> None:
        await (
            self._db.collection("journeys")
            .document(journey_id)
            .collection("timeline")
            .add(entry.model_dump(mode="json"))
        )

    async def get_timeline(self, journey_id: str) -> list[TimelineEntry]:
        query = (
            self._db.collection("journeys")
            .document(journey_id)
            .collection("timeline")
            .order_by("ts")
        )
        return [TimelineEntry.model_validate(s.to_dict()) async for s in query.stream()]

    async def create_approval(self, approval: Approval) -> None:
        await self._db.collection("approvals").document(approval.id).set(
            approval.model_dump(mode="json")
        )

    async def get_approval(self, approval_id: str) -> Approval | None:
        snap = await self._db.collection("approvals").document(approval_id).get()
        return Approval.model_validate(snap.to_dict()) if snap.exists else None

    async def save_approval(self, approval: Approval) -> None:
        await self._db.collection("approvals").document(approval.id).set(
            approval.model_dump(mode="json")
        )

    async def list_approvals(
        self, journey_id: str, status: ApprovalStatus | None = None
    ) -> list[Approval]:
        query = self._db.collection("approvals").where("journey_id", "==", journey_id)
        if status is not None:
            query = query.where("status", "==", status.value)
        return [Approval.model_validate(s.to_dict()) async for s in query.stream()]

    async def create_deadline(self, deadline: Deadline) -> None:
        await self._db.collection("deadlines").document(deadline.id).set(
            deadline.model_dump(mode="json")
        )

    async def save_deadline(self, deadline: Deadline) -> None:
        await self._db.collection("deadlines").document(deadline.id).set(
            deadline.model_dump(mode="json")
        )

    async def list_active_deadlines(self) -> list[Deadline]:
        query = self._db.collection("deadlines").where("resolved", "==", False)
        return [Deadline.model_validate(s.to_dict()) async for s in query.stream()]
