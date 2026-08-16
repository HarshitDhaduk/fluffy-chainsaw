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

- **[docs/CONCEPT.md](docs/CONCEPT.md)** — full concept: flagship demo
  journey, agent fleet design, architecture, judging-criteria mapping,
  demo video script, and the two-week build plan.
- **[backend/README.md](backend/README.md)** — backend dev guide.

## Status

🚧 Walking skeleton complete — the full journey runs end-to-end offline
(`make demo`, tests green). Next: live Gemini prompts, document upload +
vision validation, dashboard polish, GCP deploy. Submission deadline:
**August 31, 2026**.
