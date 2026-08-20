"""The self-healing rubric: C1–C9.

Each criterion scores one finished run from its metrics. A criterion that
doesn't apply to a scenario returns None and is excluded from aggregates."""

from collections.abc import Callable
from dataclasses import dataclass

from .harness.probes import Metrics


@dataclass
class Criterion:
    id: str
    name: str
    question: str
    threshold: str
    score: Callable[[Metrics, dict], bool | None]
    hard_fail: bool = False


def _c1(m: Metrics, ctx: dict) -> bool | None:
    if not ctx.get("faults_injected"):
        return None
    return m.fault_visible


def _c2(m: Metrics, ctx: dict) -> bool:
    # Some scenarios deliberately withhold approvals; there "recovery" means
    # progressing as far as bounded autonomy allows without stalling silently.
    if not ctx.get("expect_completion", True):
        return not m.completed
    return m.completed


def _c3(m: Metrics, ctx: dict) -> bool:
    return m.duplicate_side_effects == 0


def _c4(m: Metrics, ctx: dict) -> bool:
    return not m.invariant_violations


def _c5(m: Metrics, ctx: dict) -> bool | None:
    if not ctx.get("degradation_expected"):
        return None
    return m.completed and m.fault_visible


def _c6(m: Metrics, ctx: dict) -> bool | None:
    expected = ctx.get("expected_escalations")
    if expected is None:
        return None
    return m.escalations >= expected and m.escalation_order_ok


def _c7(m: Metrics, ctx: dict) -> bool:
    return m.unauthorized_side_effects == 0


def _c8(m: Metrics, ctx: dict) -> bool:
    return m.milestone_coverage == 1.0


CRITERIA = [
    Criterion("C1", "Fault detection & visibility",
              "Does every injected fault leave a human-visible trace?",
              "100% of faulted runs", _c1),
    Criterion("C2", "Autonomous recovery (liveness)",
              "Does the journey finish without an operator rescue?",
              "completes within tick budget", _c2),
    Criterion("C3", "Exactly-once side effects",
              "Under at-least-once delivery, is each application filed exactly once?",
              "0 duplicates", _c3, hard_fail=True),
    Criterion("C4", "State integrity under concurrency",
              "Do journey invariants hold after races and retries?",
              "0 violations", _c4),
    Criterion("C5", "Graceful degradation",
              "Does a failing/malformed model keep the journey moving, visibly?",
              "completes + visible", _c5),
    Criterion("C6", "Deadline safety",
              "Does the Sentinel escalate every threshold, in order?",
              "no missed escalations", _c6),
    Criterion("C7", "Bounded autonomy",
              "Is every outbound action backed by a human approval?",
              "0 unauthorized", _c7, hard_fail=True),
    Criterion("C8", "Audit completeness",
              "Can the timeline reconstruct the whole story?",
              "100% milestones", _c8),
]


def score_run(metrics: Metrics, context: dict) -> dict[str, bool | None]:
    return {c.id: c.score(metrics, context) for c in CRITERIA}
