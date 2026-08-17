# Deploying LalFita to Google Cloud

Two scripts, run from the repo root on any machine with the
[gcloud CLI](https://cloud.google.com/sdk/docs/install) authenticated
(`gcloud auth login`).

**Windows (PowerShell)** — `.sh` files don't run in PowerShell; use the
native ports:

```powershell
./infra/setup.ps1 -ProjectId <your-project>    # one-time: APIs, Firestore, Pub/Sub, bucket, IAM
./infra/deploy.ps1 -ProjectId <your-project>   # every deploy: 4 Cloud Run services + wiring
```

**macOS / Linux / WSL / Git Bash / Cloud Shell:**

```bash
PROJECT_ID=<your-project> ./infra/setup.sh
PROJECT_ID=<your-project> ./infra/deploy.sh
```

`REGION` defaults to `us-central1` (newest Gemini models arrive there first).
Re-running either script is safe — both are idempotent.

## What gets deployed

| Service | Access | Purpose |
|---|---|---|
| `lalfita-dashboard` | public | Next.js UI (API base baked in at build time) |
| `lalfita-api` | public | Dashboard API (journeys, uploads, approvals) |
| `lalfita-agents` | **IAM-locked** | The five-agent fleet |
| `lalfita-sandbox` | public | Mock government portals (`SIM_DAY_SECONDS=30`) |

Security posture (worth 30 seconds in the demo video): the agents service
accepts **no unauthenticated calls**. Its three inbound paths each carry an
OIDC identity token for the `lalfita-invoker` service account — Pub/Sub push
(`--push-auth-service-account`), Cloud Scheduler (`--oidc-service-account-email`),
and the sandbox's webhooks (minted in code via the metadata server). Cloud
Run's IAM layer verifies the tokens; the application never sees an
unauthenticated event.

## Smoke test after deploy

1. `curl <API_URL>/healthz` and `curl <SANDBOX_URL>/healthz` → `{"ok": true}`.
2. Open the dashboard → start a journey (tick **demo mode** for fixture
   documents) → approve the gates as they appear → journey completes in a few
   minutes on the 30s/day sim clock.
3. `curl <AGENTS_URL>/healthz` **without** auth → 403. That's the lock
   working.

## Submission proof checklist (Devpost requires "built on Google Cloud")

Screenshot each once a journey has run:

- [ ] Cloud Run services list (4 services, region, revisions)
- [ ] Pub/Sub subscription `lalfita-events-push` with its push endpoint + auth SA
- [ ] Firestore Data view: a `journeys` document mid-state + its `timeline` subcollection
- [ ] Cloud Scheduler `lalfita-sentinel-tick` run history
- [ ] Cloud Storage vault bucket with an uploaded document under `journeys/…`
- [ ] Vertex AI → Gemini API metrics page showing calls
- [ ] Cloud Run logs of `lalfita-agents` during a journey (agents narrating)

## Cost guard

Everything here idles at ~zero (Cloud Run scales to zero; Scheduler is one
call/minute). The spend is Gemini calls. Set a budget alert at ₹/$
50/100/130: Billing → Budgets & alerts → your credits budget.

## Local dev unchanged

`make demo` / `make dev` keep working offline — cloud mode is selected purely
by env vars (`LALFITA_MODE=cloud`, `GOOGLE_GENAI_USE_VERTEXAI=true`, …), which
the deploy script sets on each service.
