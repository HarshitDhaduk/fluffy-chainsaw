# LalFita — Product Requirements Document

**Version:** 1.0 · **Date:** 2026-08-17 · **Owner:** Team LalFita
**Status of build:** walking skeleton complete & live on Gemini; this PRD
governs what ships by the Aug 31 hackathon submission.

---

## 1. Problem

Making a small business legal in India means running a gauntlet of
disconnected authorities — FSSAI (food license), GSTN (tax registration),
Udyam (MSME), municipal bodies — each with its own portal, forms, document
rules, and silent failure modes. The process punishes ordinary people three
ways:

1. **Applicability confusion.** Which registrations, which tiers, which
   forms? Rules shift; advice online is stale; owners guess wrong.
2. **Document rejections.** A name spelled `MIRA SHAH` on an electricity
   bill vs `MEERA R SHAH` on a PAN card kills an application weeks after
   submission, with no explanation a layperson can act on.
3. **Deadline chains.** Clarification notices (e.g. GST REG-03) arrive
   mid-process with ~7-working-day reply windows. Miss one, start over.

The journey spans **weeks of calendar time but only minutes of real
decision-making**. Everything else is vigilance and paperwork — exactly what
an autonomous agent should own.

## 2. Product vision

> Tell LalFita your goal. Photograph your documents. Approve with one tap
> when it asks. It handles everything else — for weeks if needed — and hands
> you your registration numbers.

LalFita is a **long-running, human-supervised agent fleet**: it researches,
plans, validates, files, watches, and chases, surfacing to the user only at
genuine decision points. The flagship journey is an Indian home-food
business going legal (FSSAI + GST + Udyam); the engine is process-agnostic
by design.

**Hackathon framing:** All Things Agentic Hackathon, *Taskmaster* track —
"build a complete workflow, not just a chatbot."

## 3. Users

| Persona | Situation | What they need |
|---|---|---|
| **Meera** (primary; demo persona) | Home-kitchen owner in Ahmedabad going legit to sell on delivery platforms | The whole journey handled; plain-language explanations; certainty nothing is silently expiring |
| **First-time founder** | Registering a services startup | Applicability determination + filing chores off their plate |
| **CA / compliance agent** (future) | Runs 40 clients' filings | Fleet dashboard, per-client audit trails |

## 4. Goals & non-goals

**Goals (judged demo, Aug 31):**

- G1. A user states a goal in plain language and receives a researched,
  cited determination of required registrations.
- G2. Document problems are caught **before** submission, not after
  rejection.
- G3. The journey survives days of waiting, process restarts, and duplicate
  event delivery — visibly.
- G4. No action leaves the system without explicit human approval.
- G5. Every agent action is auditable on a live timeline.
- G6. Deployed on Google Cloud with reproducible one-command setup.

**Non-goals (say no in the demo, roadmap later):**

- Real submission to live government portals (OTP/captcha-gated by design;
  we prepare everything and stop at the human gate — sandbox portals stand
  in for the demo).
- Payments/fee handling, legal advice, multi-language UI, mobile apps.
- Any country beyond India for the flagship (the generalization is shown,
  not shipped).

## 5. Features

Priority: **P0** = must demo · **P1** = strong differentiator, build if on
schedule · **P2** = mention in roadmap.

### F1 — Goal intake & applicability research (P0) — *Pathfinder*
Plain-language goal + short profile interview → Gemini (with Google Search
grounding on Vertex) determines the minimal registration set, each with
authority, form, rationale in plain language, and citations. Rules are
researched at runtime, never hardcoded.
*Acceptance:* Meera's profile yields FSSAI Basic + GST + Udyam with correct
tier reasoning (turnover < ₹12L ⇒ Basic, platform selling ⇒ GST).

### F2 — Plan compilation & live timeline (P0) — *Planner*
Requirements compile deterministically into a dependency-ordered plan; the
journey is an explicit state machine in Firestore; the dashboard renders the
audit timeline live ("what your agents have been doing").
*Acceptance:* every agent/portal/user action appears on the timeline within
2s; state survives service restart.

### F3 — Document vault & cross-validation (P0) — *Clerk*
Upload PAN / Aadhaar / utility bill photos → Gemini vision extracts fields →
Clerk cross-validates names, addresses, numbers **across** documents and
flags blocking issues with a plain-language fix.
*Acceptance:* the MIRA/MEERA mismatch is caught in the demo with a
one-paragraph explanation; corrected upload clears it.
*(Walking skeleton uses fixture documents; real upload+vision is the P0 gap
to close — build item B1.)*

### F4 — Application preparation + approval gates (P0) — *Clerk*
Forms filled from validated data; queued behind a one-tap approval. **No
outbound action ever bypasses a gate** (see §8 security).
*Acceptance:* rejecting an approval halts that branch; nothing is submitted
without an `approval.granted` audit event.

### F5 — Submission, watching & correspondence (P0) — *Liaison*
Approved applications are submitted via the portal gateway; asynchronous
responses (acks, clarification notices, approvals) arrive by webhook; notices
are parsed by Gemini, replies drafted with attachments, gated for approval.
*Acceptance:* the "2 AM notice" scenario runs end-to-end: notice → parsed
summary → drafted reply → deadline registered → one-tap approve → reply sent.

### F6 — Deadline sentinel (P0) — *Sentinel*
Every reply window becomes a tracked deadline; Cloud Scheduler-driven scans
escalate at 50% / 25% / overdue thresholds.
*Acceptance:* an unapproved notice reply visibly escalates on the timeline
before expiry.

### F7 — Sandbox government (P0, demo infrastructure)
Mock FoSCoS/GST portals as an independent Cloud Run service on a
time-compressed clock (`SIM_DAY_SECONDS`), scripted per-authority scenarios.
Judges can run the whole journey themselves.

### F8 — Notification fan-out (P1) — email/push when a gate opens or a
deadline escalates, so "async" is felt, not claimed.

### F9 — Second journey preset (P1) — one more goal template (e.g. "register
my freelance design studio": GST + Udyam + Shop & Establishment) proving the
engine isn't hardcoded to one script.

### F10 — Crash-recovery showpiece (P1) — a demo control that kills the
agents service mid-journey and shows it resume from Firestore state
untouched. (The architecture already supports this; the feature is making it
*visible*.)

### F11 — Fleet dashboard, real portal integrations, vernacular UI (P2 —
roadmap slide only.)

## 6. How it works — journey lifecycle

```
intake → researching → planning → action_required ⇄ awaiting_authority → completed
                                   (human gates)     (government clock)
```

One journey = one state-machine document in Firestore + an append-only
timeline. Agents are stateless workers: everything they know is read from
the store, everything they decide is written back and announced on the bus.
The full event choreography lives in `backend/lalfita/agents/registry.py`
and is deliberately small enough to read in one screen.

## 7. Architecture & the ADK 2 orchestration patterns

*(This section encodes the two Cloud OnAir sessions — "Architecting
Multi-Agent Teams: the Three Orchestration Patterns of ADK 2" and "Build a
Long-Running Agent" — as they apply to LalFita. API names verified against
google-adk 2.7.0.)*

ADK 2 offers three orchestration patterns; LalFita deliberately uses each
where it fits, and says so to the judges:

**Pattern 1 — Deterministic workflow agents** (`SequentialAgent`,
`ParallelAgent`, `LoopAgent`): for flows where the *structure* is known in
advance. We use this shape *inside* Clerk's document pass — extraction of
the three documents fans out in parallel, validation joins the results —
and in Planner, which is deliberately pure code: plan compilation is logic,
not sampling.

**Pattern 2 — LLM-driven delegation** (dynamic transfer between
`sub_agents`): for when the model must decide who acts next. We use it
sparingly and at the edges — Liaison classifying an inbound notice and
deciding whether it needs a drafted reply, an escalation, or a simple
acknowledgement. Rule of thumb from the session, which we follow: *don't
let the LLM route what an event type already routes.*

**Pattern 3 — Graph workflows** (`google.adk.workflow`: `Workflow`, `Node`,
`FunctionNode`, `JoinNode`, `Edge`, `RetryConfig`): ADK 2's durable graph
engine. Our top-level choreography is this pattern expressed over
infrastructure: Pub/Sub events are the edges, agent handlers are the nodes,
Firestore is the graph state. We chose the infrastructure expression over
the in-process one because our nodes must sleep for *days* between
transitions at zero cost — a Cloud Run instance can scale to zero while the
journey waits; an in-process graph cannot. `RetryConfig`-style
backoff-with-jitter applies at the handler level.

**Why not one big agent?** The session's core warning: a single agent with
twenty tools becomes non-deterministic mush. Five narrow agents with typed
events give us testability (each handler unit-tests in isolation), model
economics (only Pathfinder needs Pro), and a security perimeter per agent.

## 8. Long-running discipline (crash recovery, HITL, idempotency)

The second session's themes are LalFita's *reason to exist*, so they're
product requirements, not implementation details:

**R1 — Durable state, not durable processes.** A journey must survive any
service dying between events. All state lives in Firestore
(`DatabaseSessionService` / `VertexAiSessionService` being the in-agent
equivalents); an agent instance holds nothing a crash could lose. Handlers
re-derive everything from the store on each event.
*Test:* kill the agents service mid-journey; the journey completes after
restart (F10 makes this a demo moment).

**R2 — Human approval as pause, not poll.** The approval gate is ADK's
`LongRunningFunctionTool` / `ToolConfirmation` concept expressed at system
level: the journey *hibernates* (status `action_required`, zero compute)
until the human's decision arrives as an event — hours or days later. No
loop ever waits on a human.

**R3 — The idempotency trap.** The session's cautionary tale: a resumable
agent that crashed after ordering a laptop but before recording it —
resumed, and ordered a second one. Our contract: **at-least-once delivery
everywhere** (Pub/Sub redelivers, webhooks retry, humans double-tap), so
every side-effecting handler carries an idempotency guard keyed on stored
state, not memory:
- Pathfinder skips if requirements already exist;
- Clerk skips if documents already ingested;
- Liaison **checks `requirement.reference` before submitting** — the
  "second laptop" guard: a redelivered approval event cannot double-file an
  application;
- approval endpoints resolve exactly once (`PENDING → APPROVED` transitions
  are one-way; repeats are acknowledged no-ops).
*Test (exists):* duplicate `approval.granted` events produce exactly one
submission. Extend to every handler as B4.

**R4 — Escalating vigilance.** Waiting is active: deadlines are first-class
stored objects scanned by Sentinel on an external clock (Cloud Scheduler),
so vigilance survives restarts too.

## 9. Judging-criteria alignment

| Criterion (weight) | Where this PRD delivers |
|---|---|
| Innovation & operational utility (40%) | §1–§2: weeks of real friction removed autonomously; F5/F6 async loop is the differentiator |
| Architectural discipline (30%) | §7 patterns-by-design, §8 R1–R4, per-agent least privilege, HITL security gates |
| Demo & production readiness (30%) | F7 reproducible sandbox, F10 crash showpiece, one-command deploy, architecture diagram in CONCEPT.md |

## 10. Build plan to Aug 31 (owners = 4 workstreams)

| # | Item | Feature | Owner lane | Target |
|---|---|---|---|---|
| B1 | Real document upload + Gemini vision extraction | F3 | Agents | Aug 20 |
| B2 | Vertex switch (credits) + grounded Pathfinder + Pro model | F1 | Infra | Aug 20 |
| B3 | First cloud deploy; GCP console screenshots start | F7/G6 | Infra | Aug 21 |
| B4 | Idempotency guards on all handlers + duplicate-delivery tests | §8 R3 | Agents | Aug 22 |
| B5 | Dashboard polish: intake wizard, document upload UI, deadline countdown | F2/F4 | Dashboard | Aug 24 |
| B6 | Notification fan-out (email or push) | F8 | Sandbox/Integrations | Aug 25 |
| B7 | Crash-recovery demo control | F10 | Agents | Aug 26 |
| B8 | Second journey preset | F9 | Agents | Aug 26 |
| B9 | Lock demo script; freeze features | — | All | **Aug 27** |
| B10 | Video shoot + edit; Devpost draft; architecture diagram final | — | All | Aug 28–29 |
| B11 | Submit | — | All | **Aug 30** (buffer: 31st) |

## 11. Risks

| Risk | Mitigation |
|---|---|
| Free-tier quota blips during development | Already handled: graceful fixture degradation; move demo runs to Vertex (B2) |
| Judges read sandbox as fake | Transparent framing (real portals are OTP-gated *by design*); Clerk validates *real* documents regardless |
| Scope creep with 4+ builders | This PRD's P0 line is the contract; B9 freeze date is hard |
| "It's a form filler" dismissal | Demo leads with the async notice loop and crash recovery, which no form filler has |

## 12. Open questions

1. Notification channel for F8: email (simplest, demoable) vs FCM push —
   decide by B5.
2. Second preset (F9): freelance-services journey vs boutique/e-commerce —
   pick whichever Pathfinder handles best ungrounded.
3. Do we show the Gujarat *Gumastadhara* requirement live Pathfinder keeps
   finding? (It's correct and impressive — but adds a 4th thread to the
   demo narrative. Lean: mention, don't demo.)
