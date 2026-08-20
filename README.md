# LalFita — the agent that cuts through red tape

> **लाल फीता** (*lāl fītā*) — Hindi for "red tape."

LalFita is an autonomous bureaucracy navigator built for the
[All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/)
(**Taskmaster track**). Give it a real-world goal — *"make my home food
business legal so I can sell on delivery platforms"* — and it figures out
which registrations you actually need, collects and validates your documents,
prepares the applications, tracks every deadline, and chases the process
forward **for days or weeks, asynchronously, while you live your life**.

Built with **Gemini**, Google's **Agent Development Kit (ADK)**, and
**Google Cloud** (Cloud Run, Pub/Sub, Firestore, Cloud Storage, Cloud
Scheduler).

## Why this exists

India's small-business compliance journey (GST registration, FSSAI food
license, Udyam/MSME, municipal trade licenses) is a maze of portals, forms,
document requirements, clarification notices, and silent deadlines. Millions
of home food businesses operate unregistered — not because owners don't want
to comply, but because the process is opaque and unforgiving: a single name
mismatch between your PAN and your utility bill, or a clarification notice
you didn't answer within 7 working days, and your application dies.

That is exactly the kind of messy, multi-step, long-running chore agents
should own.

## Quickstart — see it work in 60 seconds, no GCP needed

```bash
make install   # or: cd backend && pip install -e ".[dev]"
make demo      # Meera's full journey plays out in your terminal
```

Offline mode uses canned Gemini fixtures with the same JSON shapes as the
live prompts, so the entire agent choreography — research → plan → document
mismatch caught → approvals → submissions → clarification notice → drafted
reply → registrations granted — runs end-to-end with zero credentials.

To drive it from the dashboard instead:

```bash
make dev        # walking-skeleton API on :8080
make dashboard  # Next.js UI on :3000 (separate terminal)
```

To prove it heals itself:

```bash
make evals          # 28 fault-injection scenarios × 3 seeds → docs/EVALS.md
make evals-durable  # SIGKILL a real process mid-journey; it resumes from disk
make evals-soak     # 50 journeys with random multi-fault cocktails
```

## Repository map

```
backend/          Python monopackage — three deployable services, one image
  lalfita/common/   schemas · event vocabulary · bus (InProcess/PubSub)
                    store (InMemory/Firestore) · ADK/Gemini runner · sim clock
  lalfita/agents/   pathfinder · planner · clerk · liaison · sentinel
                    registry (event routing) · Cloud Run entrypoint
  lalfita/api/      dashboard API (journeys, approvals, timeline)
  lalfita/sandbox/  mock FoSCoS/GST portals on a time-compressed clock
  lalfita/local.py  everything in one process — the walking skeleton
  scripts/run_demo.py  terminal demo of the full journey
  tests/            end-to-end walking-skeleton tests
dashboard/        Next.js dashboard (timeline, one-tap approval gates)
infra/            setup.sh (APIs, Firestore, Pub/Sub) · deploy.sh (3× Cloud Run)
docs/CONCEPT.md   concept, architecture, judging map, video script, build plan
```

## Documents

- **[docs/PRD.md](docs/PRD.md)** — product requirements: features (F1–F12
  with priorities), ADK 2 orchestration patterns as applied here,
  long-running/idempotency discipline, build plan to Aug 31.
- **[docs/EVALS.md](docs/EVALS.md)** — self-healing evaluation report: the
  rubric, the fault-injection scenario matrix, and what building it fixed.
- **[docs/CONCEPT.md](docs/CONCEPT.md)** — full concept: flagship demo
  journey, agent fleet design, architecture, judging-criteria mapping,
  demo video script, and the two-week build plan.
- **[backend/README.md](backend/README.md)** — backend dev guide.

## Status

✅ Feature-complete for the P0+P1 scope: live Gemini agents (vision document
validation included), intake wizard + live deadline countdowns, notification
fan-out (ntfy push / webhook), crash-recovery chaos drill, two journey
presets, and self-healing verified by evaluation rather than assertion —
28 fault-injection scenarios × 3 seeds, a real SIGKILL restart test, and a
50-journey random-fault soak, all green (44 tests). Cloud deploy is turnkey
(`infra/deploy.ps1` / `deploy.sh`) — pending billing activation on the GCP
project. Submission deadline: **August 31, 2026**.
