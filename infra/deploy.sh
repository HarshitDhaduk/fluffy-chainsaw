#!/usr/bin/env bash
# Deploy all three backend services + wire Pub/Sub push and Cloud Scheduler.
# Usage: PROJECT_ID=my-project REGION=asia-south1 ./infra/deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
TOPIC="${PUBSUB_TOPIC:-lalfita-events}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud config set project "$PROJECT_ID"

deploy() { # name, module, extra env
  local name="$1" module="$2" extra_env="${3:-}"
  local env_vars="LALFITA_MODE=cloud,GCP_PROJECT=${PROJECT_ID},PUBSUB_TOPIC=${TOPIC},APP_MODULE=${module},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION}"
  [ -n "$extra_env" ] && env_vars="${env_vars},${extra_env}"
  gcloud run deploy "$name" \
    --source "$ROOT/backend" \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "$env_vars"
  gcloud run services describe "$name" --region "$REGION" --format 'value(status.url)'
}

echo "→ Deploying agents service…"
AGENTS_URL="$(deploy lalfita-agents lalfita.agents.service:app | tail -1)"

echo "→ Deploying sandbox government…"
SANDBOX_URL="$(deploy lalfita-sandbox lalfita.sandbox.service:app \
  "AGENTS_WEBHOOK_URL=${AGENTS_URL}/webhooks/portal,SIM_DAY_SECONDS=30" | tail -1)"

echo "→ Re-deploying agents with sandbox URL…"
gcloud run services update lalfita-agents --region "$REGION" \
  --update-env-vars "SANDBOX_BASE_URL=${SANDBOX_URL}"

echo "→ Deploying API…"
API_URL="$(deploy lalfita-api lalfita.api.service:app \
  "SANDBOX_BASE_URL=${SANDBOX_URL}" | tail -1)"

echo "→ Pub/Sub push subscription → agents service…"
gcloud pubsub subscriptions create lalfita-events-push \
  --topic "$TOPIC" \
  --push-endpoint "${AGENTS_URL}/pubsub/push" \
  --ack-deadline 60 \
  2>/dev/null || gcloud pubsub subscriptions modify-push-config lalfita-events-push \
  --push-endpoint "${AGENTS_URL}/pubsub/push"

echo "→ Cloud Scheduler: Sentinel tick every minute…"
gcloud scheduler jobs create http lalfita-sentinel-tick \
  --location "$REGION" \
  --schedule "* * * * *" \
  --uri "${AGENTS_URL}/tasks/tick" \
  --http-method POST \
  2>/dev/null || echo "  (already exists)"

echo ""
echo "✅ Deployed:"
echo "   agents:  $AGENTS_URL"
echo "   sandbox: $SANDBOX_URL"
echo "   api:     $API_URL"
echo ""
echo "Dashboard: cd dashboard && NEXT_PUBLIC_API_BASE=$API_URL npm run build"
echo "(TODO: deploy dashboard to Cloud Run / Firebase Hosting)"
