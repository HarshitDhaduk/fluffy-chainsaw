#!/usr/bin/env bash
# One-time GCP project setup for LalFita. Idempotent — safe to re-run.
# Usage: PROJECT_ID=my-project ./infra/setup.sh   (REGION defaults to us-central1)
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
TOPIC="${PUBSUB_TOPIC:-lalfita-events}"
INVOKER_SA_NAME="lalfita-invoker"
INVOKER_SA="${INVOKER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"

echo "→ Enabling APIs…"
gcloud services enable \
  run.googleapis.com \
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

echo "→ Invoker service account (Pub/Sub push, Scheduler, sandbox webhooks)…"
gcloud iam service-accounts create "$INVOKER_SA_NAME" \
  --display-name="LalFita invoker (authenticates calls to the agents service)" \
  2>/dev/null || echo "  (already exists)"

echo "→ Runtime IAM for the default compute service account…"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher \
            roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${COMPUTE_SA}" --role="$role" --condition=None --quiet \
    >/dev/null
done

echo ""
echo "✅ Setup complete. Next: PROJECT_ID=$PROJECT_ID REGION=$REGION ./infra/deploy.sh"
