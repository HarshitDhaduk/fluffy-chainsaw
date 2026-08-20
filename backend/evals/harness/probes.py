"""Probes — turn a finished run into rubric metrics.

Pure functions over (store state, ledger, trace) so they can be reasoned
about independently of the scenario that produced them."""

from dataclasses import dataclass, field

from lalfita.common.schemas import ApprovalKind, ApprovalStatus, StepStatus

# The milestones a complete journey must narrate, in order.
MILESTONES = [
    "research.started",
    "requirements.determined",
    "plan.ready",
    "application.prepared",
    "submission.sent",
    "portal.approved",
    "journey.completed",
]

FAULT_MARKERS = {
    "crash.simulated",
    "crash.recovered",
    "research.degraded",
    "deadline.escalation",
    "document.issue",
    "notification.sent",
}


@dataclass
class Metrics:
    completed: bool = False
    ticks: int = 0
    duplicate_side_effects: int = 0
    duplicate_submissions: list = field(default_factory=list)
    duplicate_replies: list = field(default_factory=list)
    invariant_violations: list[str] = field(default_factory=list)
    milestone_coverage: float = 0.0
    missing_milestones: list[str] = field(default_factory=list)
    escalations: int = 0
    escalation_order_ok: bool = True
    unauthorized_side_effects: int = 0
    extra_human_asks: int = 0
    fault_visible: bool = False
    crashes: int = 0
    redeliveries: int = 0
    recovery_retries: int = 0
    recovery_ticks: int | None = None

    def as_dict(self) -> dict:
        return {
            "completed": self.completed,
            "ticks": self.ticks,
            "duplicate_side_effects": self.duplicate_side_effects,
            "invariant_violations": self.invariant_violations,
            "milestone_coverage": round(self.milestone_coverage, 3),
            "missing_milestones": self.missing_milestones,
            "escalations": self.escalations,
            "escalation_order_ok": self.escalation_order_ok,
            "unauthorized_side_effects": self.unauthorized_side_effects,
            "extra_human_asks": self.extra_human_asks,
            "fault_visible": self.fault_visible,
            "crashes": self.crashes,
            "redeliveries": self.redeliveries,
            "recovery_retries": self.recovery_retries,
        }


# Baseline human interactions for the Meera journey: one document fix, three
# submissions, one notice reply.
BASELINE_APPROVALS = 5


async def collect(
    app, run, *, faults_injected: bool, milestones: list[str] | None = None
) -> Metrics:
    ctx = app.ctx
    journey = await ctx.store.get_journey(run.journey_id)
    timeline = await ctx.store.get_timeline(run.journey_id)
    approvals = await ctx.store.list_approvals(run.journey_id)
    deadlines = await ctx.store.list_deadlines(run.journey_id)
    events_seen = [t.event for t in timeline]

    m = Metrics(completed=run.completed, ticks=run.ticks)

    # C3 — exactly-once side effects. Two distinct measurements:
    #   * effects that actually landed at the authority (the "two laptops"
    #     question) — the portal's own ledger is ground truth;
    #   * repeat attempts with no crash to explain them, which mean a client
    #     side idempotency guard failed even if the portal absorbed it.
    # A repeat attempt *after* a crash is legitimate recovery and is reported
    # separately rather than counted against the system.
    sub_explained, sub_unexplained = app.ledger.submission_attempt_dupes()
    rep_explained, rep_unexplained = app.ledger.reply_attempt_dupes()
    portal_apps = getattr(app.government, "accepted_applications", [])
    portal_replies = getattr(app.government, "accepted_replies", [])
    portal_dupes = max(len(portal_apps) - len({(j, k) for j, k, _ in portal_apps}), 0)
    portal_dupes += max(len(portal_replies) - len(set(portal_replies)), 0)

    m.duplicate_submissions = sub_unexplained
    m.duplicate_replies = rep_unexplained
    m.duplicate_side_effects = len(sub_unexplained) + len(rep_unexplained) + portal_dupes
    m.recovery_retries = len(sub_explained) + len(rep_explained)

    # C4 — state integrity.
    if journey is not None:
        for req in journey.requirements:
            if req.status == StepStatus.DONE and not req.registration_number:
                m.invariant_violations.append(f"{req.key}: DONE without a registration number")
        open_replies = [
            a
            for a in approvals
            if a.kind == ApprovalKind.NOTICE_REPLY and a.status == ApprovalStatus.PENDING
        ]
        if len(open_replies) > 1:
            m.invariant_violations.append(
                f"{len(open_replies)} notice-reply gates open at once"
            )
        # A retired deadline from a reopened notice is history, not a bug —
        # what must never happen is two live countdowns for one notice.
        live_deadlines = [d for d in deadlines if not d.resolved]
        if len(live_deadlines) > 1:
            m.invariant_violations.append(
                f"{len(live_deadlines)} live deadlines for one notice"
            )
        if run.completed and any(r.status != StepStatus.DONE for r in journey.requirements):
            m.invariant_violations.append("completed with unfinished requirements")

    # C8 — audit completeness.
    expected = milestones if milestones is not None else MILESTONES
    applicable = [ms for ms in expected if run.completed or ms != "journey.completed"]
    missing = [ms for ms in applicable if ms not in events_seen]
    m.missing_milestones = missing
    m.milestone_coverage = (len(applicable) - len(missing)) / len(applicable) if applicable else 1.0

    # C6 — deadline safety.
    escalation_entries = [t for t in timeline if t.event == "deadline.escalation"]
    m.escalations = len(escalation_entries)
    percents = []
    for entry in escalation_entries:
        if "OVERDUE" in entry.detail:
            percents.append(0)
        else:
            token = [w for w in entry.detail.split() if w.endswith("%")]
            if token:
                percents.append(int(token[0].rstrip("%")))
    m.escalation_order_ok = percents == sorted(percents, reverse=True)

    # C7 — no side effect without an approval; count extra human asks.
    approved_submissions = sum(
        1
        for a in approvals
        if a.kind == ApprovalKind.SUBMISSION and a.status == ApprovalStatus.APPROVED
    )
    # Count distinct filings, not attempts: a retry after a crash is still
    # covered by the original approval.
    distinct_filings = len({(j, k) for j, k, _ in app.ledger.submissions})
    m.unauthorized_side_effects = max(distinct_filings - approved_submissions, 0)
    m.extra_human_asks = max(len(approvals) - BASELINE_APPROVALS, 0)

    # C1 — was the fault visible to a human?
    m.crashes = app.trace.crashes
    m.redeliveries = app.trace.redeliveries
    m.fault_visible = (not faults_injected) or any(e in FAULT_MARKERS for e in events_seen)

    return m
