# LalFita backend

One Python package, three deployable services (same image, different
`APP_MODULE`):

| Service | Module | Role |
|---|---|---|
| agents | `lalfita.agents.service:app` | The five-agent fleet; consumes Pub/Sub push, portal webhooks, scheduler ticks |
| api | `lalfita.api.service:app` | Dashboard API (journeys, approvals, timeline) |
| sandbox | `lalfita.sandbox.service:app` | Mock FoSCoS/GST portals on the sim clock |

## Quickstart (no GCP needed)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Watch the whole journey play out in your terminal:
python scripts/run_demo.py

# Or serve the walking skeleton for the dashboard:
uvicorn lalfita.local:app --port 8080
```

Offline mode (no `GOOGLE_API_KEY`) uses canned Gemini fixtures with the same
JSON shapes as the live prompts — the choreography is identical.

## Live Gemini

```bash
pip install -e ".[cloud]"
cp .env.example .env   # then paste your key into backend/.env (gitignored)
python scripts/smoke_live.py   # verifies all three LLM agents answer live
```

Either `GOOGLE_API_KEY` or `GEMINI_API_KEY` works (AI Studio issues the
latter; we alias it). Vertex AI works too: set `GOOGLE_GENAI_USE_VERTEXAI=true`
plus `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION`. With credentials present
every run (demo, tests, server) automatically switches from fixtures to real
Gemini; force fixtures back with `LALFITA_OFFLINE=1`.

## Tests & lint

```bash
pytest
ruff check .
```

## Layout

```
lalfita/
  common/      schemas, event vocabulary, bus (InProcess/PubSub),
               store (InMemory/Firestore), llm (ADK runner + fixtures),
               gateway (Local/Http), config & sim clock
  agents/      pathfinder, planner, clerk, liaison, sentinel,
               registry (event routing), service (cloud entrypoint)
  api/         dashboard API routes + cloud entrypoint
  sandbox/     mock government portals + cloud entrypoint
  local.py     walking skeleton: everything in one process
```
