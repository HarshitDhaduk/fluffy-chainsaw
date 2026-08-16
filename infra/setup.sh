#!/usr/bin/env bash
# One-time GCP project setup for LalFita.
# Usage: PROJECT_ID=my-project REGION=asia-south1 ./infra/setup.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
TOPIC="${PUBSUB_TOPIC:-lalfita-events}"

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
  artifactregistry.googleapis.com

echo "→ Firestore (native mode)…"
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "  (already exists)"

echo "→ Pub/Sub topic…"
gcloud pubsub topics create "$TOPIC" 2>/dev/null || echo "  (already exists)"

echo "→ Document vault bucket…"
gcloud storage buckets create "gs://${PROJECT_ID}-lalfita-vault" --location="$REGION" \
  2>/dev/null || echo "  (already exists)"

echo "✅ Setup complete. Next: ./infra/deploy.sh"
