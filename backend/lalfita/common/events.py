"""Event vocabulary. Agents communicate ONLY through these events on the bus;
payloads are plain dicts carrying ids, never object references."""

JOURNEY_CREATED = "journey.created"  # api -> pathfinder
REQUIREMENTS_DETERMINED = "requirements.determined"  # pathfinder -> planner
PLAN_READY = "plan.ready"  # planner -> clerk
DOCUMENT_UPLOADED = "document.uploaded"  # api -> clerk (vision extraction)
APPROVAL_GRANTED = "approval.granted"  # api -> clerk/liaison (payload.kind routes)
SUBMISSION_SENT = "submission.sent"  # liaison -> (timeline)
PORTAL_RESPONSE = "portal.response"  # sandbox/webhook -> liaison
DEADLINE_TICK = "deadline.tick"  # scheduler -> sentinel
RESYNC_REQUESTED = "resync.requested"  # sentinel -> liaison (missed notification)
DEMO_CRASH = "demo.crash"  # api -> chaos (crash-recovery showpiece, F10)
JOURNEY_COMPLETED = "journey.completed"  # liaison -> (timeline)
