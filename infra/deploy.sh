#!/usr/bin/env bash
# Deploy LalFita: three backend Cloud Run services + dashboard, with the
# agents service locked behind IAM (OIDC everywhere it is called).
# Idempotent — safe to re-run. Usage:
#   PROJECT_ID=my-project ./infra/deploy.sh        (REGION defaults to us-central1)
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
TOPIC="${PUBSUB_TOPIC:-lalfita-events}"
INVOKER_SA="lalfita-invoker@${PROJECT_ID}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud config set project "$PROJECT_ID"

COMMON_ENV="LALFITA_MODE=cloud,GCP_PROJECT=${PROJECT_ID},PUBSUB_TOPIC=${TOPIC},GCS_BUCKET=${PROJECT_ID}-lalfita-vault,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION}"
# Optional push notifications: export NTFY_TOPIC=<your-topic> before deploying
# and subscribe to it in the ntfy app.
if [ -n "${NTFY_TOPIC:-}" ]; then COMMON_ENV="${COMMON_ENV},NTFY_TOPIC=${NTFY_TOPIC}"; fi
if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then COMMON_ENV="${COMMON_ENV},NOTIFY_WEBHOOK_URL=${NOTIFY_WEBHOOK_URL}"; fi

url_of() { gcloud run services describe "$1" --region "$REGION" --format 'value(status.url)'; }

echo "→ Deploying agents service (locked: IAM-authenticated callers only)…"
gcloud run deploy lalfita-agents \
  --source "$ROOT/backend" --region "$REGION" \
  --no-allow-unauthenticated \
  --set-env-vars "${COMMON_ENV},APP_MODULE=lalfita.agents.service:app"
AGENTS_URL="$(url_of lalfita-agents)"

echo "→ Granting the invoker SA permission to call the agents service…"
gcloud run services add-iam-policy-binding lalfita-agents --region "$REGION" \
  --member="serviceAccount:${INVOKER_SA}" --role="roles/run.invoker" --quiet >/dev/null

echo "→ Deploying sandbox government (runs as the invoker SA; webhooks carry OIDC)…"
# SIM_DAY_SECONDS=30: one bureaucratic day = 30s, so a full journey plays out
# in a few minutes of demo time.
gcloud run deploy lalfita-sandbox \
  --source "$ROOT/backend" --region "$REGION" \
  --allow-unauthenticated \
  --service-account "$INVOKER_SA" \
  --set-env-vars "${COMMON_ENV},APP_MODULE=lalfita.sandbox.service:app,AGENTS_WEBHOOK_URL=${AGENTS_URL}/webhooks/portal,SIM_DAY_SECONDS=30"
SANDBOX_URL="$(url_of lalfita-sandbox)"

echo "→ Pointing agents at the sandbox…"
gcloud run services update lalfita-agents --region "$REGION" \
  --update-env-vars "SANDBOX_BASE_URL=${SANDBOX_URL}" >/dev/null

echo "→ Deploying API (public: the dashboard's browser calls land here)…"
gcloud run deploy lalfita-api \
  --source "$ROOT/backend" --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "${COMMON_ENV},APP_MODULE=lalfita.api.service:app,SANDBOX_BASE_URL=${SANDBOX_URL}"
API_URL="$(url_of lalfita-api)"

echo "→ Pub/Sub push subscription → agents service (authenticated push)…"
gcloud pubsub subscriptions create lalfita-events-push \
  --topic "$TOPIC" \
  --push-endpoint "${AGENTS_URL}/pubsub/push" \
  --push-auth-service-account "$INVOKER_SA" \
  --ack-deadline 30 2>/dev/null \
  || gcloud pubsub subscriptions modify-push-config lalfita-events-push \
    --push-endpoint "${AGENTS_URL}/pubsub/push" \
    --push-auth-service-account "$INVOKER_SA"

echo "→ Cloud Scheduler: Sentinel tick every minute (authenticated)…"
gcloud scheduler jobs create http lalfita-sentinel-tick \
  --location "$REGION" --schedule "* * * * *" \
  --uri "${AGENTS_URL}/tasks/tick" --http-method POST \
  --oidc-service-account-email "$INVOKER_SA" \
  --oidc-token-audience "$AGENTS_URL" 2>/dev/null \
  || gcloud scheduler jobs update http lalfita-sentinel-tick \
    --location "$REGION" --uri "${AGENTS_URL}/tasks/tick" \
    --oidc-service-account-email "$INVOKER_SA" \
    --oidc-token-audience "$AGENTS_URL"

echo "→ Building dashboard image (API base is baked in at build time)…"
DASH_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/lalfita/dashboard:latest"
gcloud builds submit "$ROOT/dashboard" \
  --config "$ROOT/dashboard/cloudbuild.yaml" \
  --substitutions "_API_BASE=${API_URL},_IMAGE=${DASH_IMAGE}"

echo "→ Deploying dashboard…"
gcloud run deploy lalfita-dashboard \
  --image "$DASH_IMAGE" --region "$REGION" --allow-unauthenticated
DASHBOARD_URL="$(url_of lalfita-dashboard)"

echo ""
echo "✅ Deployed:"
echo "   dashboard: $DASHBOARD_URL   <-- open this"
echo "   api:       $API_URL"
echo "   agents:    $AGENTS_URL   (IAM-locked: Pub/Sub, Scheduler, sandbox only)"
echo "   sandbox:   $SANDBOX_URL"
echo ""
echo "Smoke check:  curl ${API_URL}/health && curl ${SANDBOX_URL}/health"
echo "Then open the dashboard, start a journey in demo mode, and watch the"
echo "timeline. Console proof lives in: Cloud Run services list, Pub/Sub"
echo "subscription lalfita-events-push, Firestore 'journeys' collection,"
echo "Cloud Scheduler lalfita-sentinel-tick."
