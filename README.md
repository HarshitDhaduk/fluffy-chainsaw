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

## Documents

- **[docs/CONCEPT.md](docs/CONCEPT.md)** — full concept: flagship demo
  journey, agent fleet design, architecture, judging-criteria mapping,
  demo video script, and the two-week build plan.

## Status

🚧 Concept phase — architecture and build plan finalized, implementation
starting. Submission deadline: **August 31, 2026**.
