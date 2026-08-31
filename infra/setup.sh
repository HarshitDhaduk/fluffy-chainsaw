#!/usr/bin/env bash
# One-time GCP project setup for LalFita. Idempotent — safe to re-run.
# Usage: PROJECT_ID=my-project ./infra/setup.sh   (REGION defaults to us-central1)
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: Set PROJECT_ID or GOOGLE_CLOUD_PROJECT environment variable"
  exit 1
fi
TOPIC="${PUBSUB_TOPIC:-lalfita-events}"
INVOKER_SA_NAME="lalfita-invoker"
INVOKER_SA="${INVOKER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"

echo "→ Enabling APIs…"
# compute.googleapis.com looks out of place in a serverless stack, but enabling
# it is what creates the default compute service account — which is both Cloud
# Run's default runtime identity and the build identity for `run deploy --source`.
gcloud services enable \
  run.googleapis.com \
  compute.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com

echo "→ Firestore (native mode)…"
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "  (already exists)"

echo "→ Pub/Sub topic…"
gcloud pubsub topics create "$TOPIC" 2>/dev/null || echo "  (already exists)"

echo "→ Document vault bucket…"
gcloud storage buckets create "gs://${PROJECT_ID}-lalfita-vault" --location="$REGION" \
  2>/dev/null || echo "  (already exists)"

echo "→ Artifact Registry repo (dashboard image)…"
gcloud artifacts repositories create lalfita --repository-format=docker \
  --location="$REGION" 2>/dev/null || echo "  (already exists)"

echo "→ Artifact Registry repo (source-deploy images)…"
# `run deploy --source` otherwise prompts to create this on first use, which
# would hang a non-interactive deploy.
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker --location="$REGION" 2>/dev/null || echo "  (already exists)"

echo "→ Invoker service account (Pub/Sub push, Scheduler, sandbox webhooks)…"
gcloud iam service-accounts create "$INVOKER_SA_NAME" \
  --display-name="LalFita invoker (authenticates calls to the agents service)" \
  2>/dev/null || echo "  (already exists)"

echo "→ Runtime IAM for the default compute service account…"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Enabling compute.googleapis.com returns before the default SA is visible to
# IAM, so give it a moment rather than failing the whole script on a race.
for _ in $(seq 1 30); do
  gcloud iam service-accounts describe "$COMPUTE_SA" >/dev/null 2>&1 && break
  sleep 4
done

# aiplatform.user → Gemini via Vertex; datastore.user → Firestore;
# pubsub.publisher → the event bus; storage.objectAdmin → the document vault.
# cloudbuild.builds.builder → `run deploy --source` builds run AS this SA and
# need to write build logs and push to Artifact Registry.
for role in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher \
            roles/storage.objectAdmin roles/cloudbuild.builds.builder; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${COMPUTE_SA}" --role="$role" --condition=None --quiet \
    >/dev/null
done

echo "→ Letting Pub/Sub and Scheduler mint OIDC tokens as the invoker SA…"
# A push subscription with --push-auth-service-account is rejected unless the
# Pub/Sub service agent can impersonate that SA. Same story for Scheduler's
# --oidc-service-account-email. Service agents are created lazily, so force them.
for svc in pubsub cloudscheduler; do
  gcloud beta services identity create --service="${svc}.googleapis.com" \
    --project "$PROJECT_ID" >/dev/null 2>&1 || true
done
for agent in "service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
             "service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"; do
  gcloud iam service-accounts add-iam-policy-binding "$INVOKER_SA" \
    --member="serviceAccount:${agent}" \
    --role="roles/iam.serviceAccountTokenCreator" --quiet >/dev/null
done

echo ""
echo "✅ Setup complete. Next: PROJECT_ID=$PROJECT_ID REGION=$REGION ./infra/deploy.sh"
