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
    # compute.googleapis.com looks out of place in a serverless stack, but
    # enabling it is what creates the default compute service account - which is
    # both Cloud Run's default runtime identity and the build identity for
    # `run deploy --source`.
    gcloud services enable run.googleapis.com compute.googleapis.com pubsub.googleapis.com `
        firestore.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com `
        aiplatform.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
        iamcredentials.googleapis.com
}

Invoke-Idempotent "Firestore (native mode)" { gcloud firestore databases create --location=$Region }
Invoke-Idempotent "Pub/Sub topic" { gcloud pubsub topics create $Topic }
Invoke-Idempotent "Document vault bucket" {
    gcloud storage buckets create "gs://$ProjectId-lalfita-vault" --location=$Region
}
Invoke-Idempotent "Artifact Registry repo" {
    gcloud artifacts repositories create lalfita --repository-format=docker --location=$Region
}
Invoke-Idempotent "Artifact Registry repo (source-deploy images)" {
    # `run deploy --source` otherwise prompts to create this on first use.
    gcloud artifacts repositories create cloud-run-source-deploy `
        --repository-format=docker --location=$Region
}
Invoke-Idempotent "Invoker service account" {
    gcloud iam service-accounts create $InvokerSaName `
        --display-name="LalFita invoker (authenticates calls to the agents service)"
}

Write-Host "-> Runtime IAM for the default compute service account"
$ProjectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
if ($LASTEXITCODE -ne 0) { throw "could not read project number" }
$ComputeSa = "$ProjectNumber-compute@developer.gserviceaccount.com"

# Enabling compute.googleapis.com returns before the default SA is visible to
# IAM, so give it a moment rather than failing the whole script on a race.
foreach ($Attempt in 1..30) {
    gcloud iam service-accounts describe $ComputeSa 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 4
}

# aiplatform.user -> Gemini via Vertex; datastore.user -> Firestore;
# pubsub.publisher -> the event bus; storage.objectAdmin -> the document vault.
# cloudbuild.builds.builder -> `run deploy --source` builds run AS this SA and
# need to write build logs and push to Artifact Registry.
foreach ($Role in @("roles/aiplatform.user", "roles/datastore.user",
        "roles/pubsub.publisher", "roles/storage.objectAdmin",
        "roles/cloudbuild.builds.builder")) {
    gcloud projects add-iam-policy-binding $ProjectId `
        --member="serviceAccount:$ComputeSa" --role=$Role --condition=None --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "IAM grant failed: $Role" }
}

Write-Host "-> Letting Pub/Sub and Scheduler mint OIDC tokens as the invoker SA"
# A push subscription with --push-auth-service-account is rejected unless the
# Pub/Sub service agent can impersonate that SA. Same story for Scheduler's
# --oidc-service-account-email. Service agents are created lazily, so force them.
$InvokerSa = "$InvokerSaName@$ProjectId.iam.gserviceaccount.com"
foreach ($Svc in @("pubsub", "cloudscheduler")) {
    gcloud beta services identity create --service="$Svc.googleapis.com" `
        --project=$ProjectId 2>$null | Out-Null
}
foreach ($Agent in @("service-$ProjectNumber@gcp-sa-pubsub.iam.gserviceaccount.com",
        "service-$ProjectNumber@gcp-sa-cloudscheduler.iam.gserviceaccount.com")) {
    gcloud iam service-accounts add-iam-policy-binding $InvokerSa `
        --member="serviceAccount:$Agent" `
        --role="roles/iam.serviceAccountTokenCreator" --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "token-creator grant failed for $Agent" }
}

Write-Host ""
Write-Host "OK - setup complete. Next: ./infra/deploy.ps1 -ProjectId $ProjectId"
