"""The scenario matrix: which fault, injected where, with what expectations."""

from dataclasses import dataclass, field

from lalfita.common import events

from ..harness.driver import APPROVE_ALL, APPROVE_NONE, HOLD_NOTICE_REPLY
from ..harness.faults import BusFault, FaultPlan, GatewayFault, LlmFault

MEERA_GOAL = "Make my home food business legal so I can sell on delivery platforms"
MEERA_PROFILE = {
    "applicant_name": "Meera Shah",
    "city": "Ahmedabad",
    "annual_turnover_inr": 800000,
    "premises": "residential",
    "channels": ["delivery platforms"],
    "demo_documents": True,
}


@dataclass
class Scenario:
    id: str
    title: str
    fault: str  # human-readable description of what is injected
    plan: FaultPlan
    policy: str = APPROVE_ALL
    duplicate_approvals: bool = False
    max_ticks: int = 400
    expected_escalations: int | None = None
    degradation_expected: bool = False
    goal: str = MEERA_GOAL
    profile: dict = field(default_factory=lambda: dict(MEERA_PROFILE))
    expected_fail: bool = False
    note: str = ""
    # Some scenarios deliberately withhold approvals, so completion is not the
    # expected outcome; `milestones` then narrows what the audit must contain.
    expect_completion: bool = True
    milestones: list[str] | None = None

    @property
    def faults_injected(self) -> bool:
        p = self.plan
        return bool(p.bus or p.llm or p.gateway or p.notifier_raises or self.duplicate_approvals)


def _plan(**kwargs) -> FaultPlan:
    return FaultPlan(**kwargs)


SCENARIOS: list[Scenario] = [
    Scenario(
        id="S0", title="Control (no faults)",
        fault="none",
        plan=_plan(),
        note="Baseline: proves the matrix measures a healthy system correctly.",
    ),
    Scenario(
        id="S1", title="Duplicate journey.created",
        fault="bus duplicates the first journey.created",
        plan=_plan(bus=[BusFault(events.JOURNEY_CREATED, "duplicate")]),
        note="Pathfinder's requirements guard must absorb the redelivery.",
    ),
    Scenario(
        id="S2", title="Duplicate plan.ready",
        fault="bus duplicates plan.ready",
        plan=_plan(bus=[BusFault(events.PLAN_READY, "duplicate")]),
        note="Clerk must request documents once and prepare one set of applications.",
    ),
    Scenario(
        id="S3", title="Duplicate submission approvals",
        fault="every approval.granted is delivered twice",
        plan=_plan(),
        duplicate_approvals=True,
        note="Headline exactly-once test: claim-then-submit under double delivery.",
    ),
    Scenario(
        id="S4", title="Duplicate clarification notice",
        fault="bus duplicates the portal notice",
        plan=_plan(bus=[BusFault(events.PORTAL_RESPONSE, "duplicate", nth=3, times=0)]),
        note="One deadline and one drafted reply, however often the notice arrives.",
    ),
    Scenario(
        id="S5", title="Duplicate portal approvals",
        fault="bus duplicates every portal.response",
        plan=_plan(bus=[BusFault(events.PORTAL_RESPONSE, "duplicate", nth=1, times=0)]),
        note="Completion must fire once; no double registration numbers.",
    ),
    Scenario(
        id="S6", title="Lost-then-redelivered plan event",
        fault="requirements.determined dropped, redelivered after a delay",
        plan=_plan(bus=[BusFault(events.REQUIREMENTS_DETERMINED, "drop_then_redeliver",
                                 delay_s=0.3)]),
        note="Models a delayed Pub/Sub redelivery: slower, still correct.",
    ),
    Scenario(
        id="S7", title="Racing portal responses",
        fault="portal responses delayed so approvals and the notice interleave",
        plan=_plan(bus=[BusFault(events.PORTAL_RESPONSE, "delay", nth=2, times=0, delay_s=0.1)]),
        note="Atomic mutate_journey must prevent lost updates across authorities.",
    ),
    Scenario(
        id="S8", title="Approval storm",
        fault="duplicate approvals plus duplicated approval events on the bus",
        plan=_plan(bus=[BusFault(events.APPROVAL_GRANTED, "duplicate", nth=1, times=0)]),
        duplicate_approvals=True,
        note="Four deliveries per approval; still exactly one filing each.",
    ),
    Scenario(
        id="S9", title="Chaos drill mid-journey",
        fault="operator triggers the crash drill",
        plan=_plan(),
        note="The shipped demo control, measured: crash and recovery both narrated.",
    ),
    Scenario(
        id="S10", title="Second laptop (crash after filing)",
        fault="crash after gateway.submit for GST, before the reference is recorded",
        plan=_plan(gateway=[GatewayFault("submit", "crash_after", requirement_key="gst")]),
        note="The classic resumable-agent trap: the redelivery must not file twice.",
    ),
    Scenario(
        id="S11", title="Crash before filing (stuck claim)",
        fault="crash after claiming GST but before the portal call",
        plan=_plan(gateway=[GatewayFault("submit", "crash_before", requirement_key="gst")]),
        note="Lease on the claim must expire so a redelivery can retry.",
    ),
    Scenario(
        id="S12", title="Model failure at research",
        fault="Pathfinder's model call raises once",
        plan=_plan(llm=[LlmFault("pathfinder", "raise", times=1)]),
        degradation_expected=False,
        note="Handler dies at the call site; redelivery retries and succeeds.",
    ),
    Scenario(
        id="S13", title="Malformed notice parse",
        fault="Liaison's model returns an empty object",
        plan=_plan(llm=[LlmFault("liaison", "malformed", times=1, payload={})]),
        degradation_expected=True,
        note="Defaults (7-day window, empty draft) keep the notice loop alive.",
    ),
    Scenario(
        id="S14", title="Malformed determination",
        fault="Pathfinder's model returns a wrong-shaped object",
        plan=_plan(llm=[LlmFault("pathfinder", "malformed", times=1,
                                 payload={"answer": "no idea"})]),
        degradation_expected=True,
        note="Shape validation must fall back to the built-in determination.",
    ),
    Scenario(
        id="S15", title="Portal timeout on the notice reply",
        fault="gateway.reply times out once",
        plan=_plan(gateway=[GatewayFault("reply", "timeout", times=1)]),
        max_ticks=500,
        note="Reply is lost; the Sentinel keeps the deadline visible and the "
             "redelivered approval retries it.",
    ),
    Scenario(
        id="S16", title="Human never answers the notice",
        fault="none; the notice reply is never approved",
        plan=_plan(),
        policy=HOLD_NOTICE_REPLY,
        max_ticks=260,
        expected_escalations=3,
        expect_completion=False,
        milestones=["research.started", "plan.ready", "submission.sent", "portal.notice",
                    "reply.drafted", "deadline.escalation"],
        note="Escalation ladder must fire 50% / 25% / overdue, in order.",
    ),
    Scenario(
        id="S17", title="Notification channels down",
        fault="every notifier send raises",
        plan=_plan(notifier_raises=True),
        note="Best-effort delivery: the timeline still records what was sent.",
    ),
    Scenario(
        id="S18", title="Second preset under duplicate delivery",
        fault="freelance journey with duplicated approvals",
        plan=_plan(),
        duplicate_approvals=True,
        goal="Register my freelance design studio",
        profile={"applicant_name": "Meera Shah", "demo_documents": True},
        note="Self-healing is a property of the engine, not of one script.",
    ),
    Scenario(
        id="S19", title="Nothing is approved",
        fault="none; the human never responds at all",
        plan=_plan(),
        policy=APPROVE_NONE,
        max_ticks=120,
        expect_completion=False,
        # Without the document-fix approval the journey legitimately stops at
        # Clerk's gate, so applications are never even prepared.
        milestones=["research.started", "plan.ready", "document.issue"],
        note="Bounded autonomy: with no approvals, nothing is ever filed.",
    ),
]

SCENARIOS_BY_ID = {s.id: s for s in SCENARIOS}
