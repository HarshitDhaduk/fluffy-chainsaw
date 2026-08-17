# One-time GCP project setup for LalFita (Windows PowerShell port of setup.sh).
# Idempotent — safe to re-run. Usage:
#   ./infra/setup.ps1 -ProjectId my-project            (Region defaults to us-central1)
param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Topic = "lalfita-events"
)

$InvokerSaName = "lalfita-invoker"

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    Write-Host "-> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "FAILED: $Description (exit $LASTEXITCODE)" }
}

function Invoke-Idempotent([string]$Description, [scriptblock]$Command) {
    # For create commands where "already exists" is fine.
    Write-Host "-> $Description"
    & $Command 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "   (already exists - skipping)" }
}

Invoke-Checked "Selecting project $ProjectId" { gcloud config set project $ProjectId --quiet }

Invoke-Checked "Enabling APIs" {
    gcloud services enable run.googleapis.com pubsub.googleapis.com firestore.googleapis.com `
        cloudscheduler.googleapis.com storage.googleapis.com aiplatform.googleapis.com `
        cloudbuild.googleapis.com artifactregistry.googleapis.com iamcredentials.googleapis.com
}

Invoke-Idempotent "Firestore (native mode)" { gcloud firestore databases create --location=$Region }
Invoke-Idempotent "Pub/Sub topic" { gcloud pubsub topics create $Topic }
Invoke-Idempotent "Document vault bucket" {
    gcloud storage buckets create "gs://$ProjectId-lalfita-vault" --location=$Region
}
Invoke-Idempotent "Artifact Registry repo" {
    gcloud artifacts repositories create lalfita --repository-format=docker --location=$Region
}
Invoke-Idempotent "Invoker service account" {
    gcloud iam service-accounts create $InvokerSaName `
        --display-name="LalFita invoker (authenticates calls to the agents service)"
}

Write-Host "-> Runtime IAM for the default compute service account"
$ProjectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
if ($LASTEXITCODE -ne 0) { throw "could not read project number" }
$ComputeSa = "$ProjectNumber-compute@developer.gserviceaccount.com"
foreach ($Role in @("roles/aiplatform.user", "roles/datastore.user",
        "roles/pubsub.publisher", "roles/storage.objectAdmin")) {
    gcloud projects add-iam-policy-binding $ProjectId `
        --member="serviceAccount:$ComputeSa" --role=$Role --condition=None --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "IAM grant failed: $Role" }
}

Write-Host ""
Write-Host "OK - setup complete. Next: ./infra/deploy.ps1 -ProjectId $ProjectId"
