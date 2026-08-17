# Deploy LalFita to Cloud Run (Windows PowerShell port of deploy.sh).
# Idempotent — safe to re-run. Usage:
#   ./infra/deploy.ps1 -ProjectId my-project           (Region defaults to us-central1)
param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Topic = "lalfita-events"
)

$InvokerSa = "lalfita-invoker@$ProjectId.iam.gserviceaccount.com"
$Root = Split-Path -Parent $PSScriptRoot
$CommonEnv = "LALFITA_MODE=cloud,GCP_PROJECT=$ProjectId,PUBSUB_TOPIC=$Topic," +
    "GCS_BUCKET=$ProjectId-lalfita-vault,GOOGLE_GENAI_USE_VERTEXAI=true," +
    "GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region"

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    Write-Host "-> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "FAILED: $Description (exit $LASTEXITCODE)" }
}

function Get-ServiceUrl([string]$Name) {
    $ServiceUrl = gcloud run services describe $Name --region $Region --format "value(status.url)"
    if ($LASTEXITCODE -ne 0 -or -not $ServiceUrl) { throw "could not read URL of $Name" }
    return $ServiceUrl
}

Invoke-Checked "Selecting project $ProjectId" { gcloud config set project $ProjectId --quiet }

Invoke-Checked "Deploying agents service (locked: IAM-authenticated callers only)" {
    gcloud run deploy lalfita-agents --source "$Root\backend" --region $Region `
        --no-allow-unauthenticated `
        --set-env-vars "$CommonEnv,APP_MODULE=lalfita.agents.service:app"
}
$AgentsUrl = Get-ServiceUrl "lalfita-agents"

Invoke-Checked "Granting the invoker SA permission to call the agents service" {
    gcloud run services add-iam-policy-binding lalfita-agents --region $Region `
        --member="serviceAccount:$InvokerSa" --role="roles/run.invoker" --quiet | Out-Null
}

# SIM_DAY_SECONDS=30: one bureaucratic day = 30s, so a full journey plays out
# in a few minutes of demo time.
Invoke-Checked "Deploying sandbox government (runs as the invoker SA; webhooks carry OIDC)" {
    gcloud run deploy lalfita-sandbox --source "$Root\backend" --region $Region `
        --allow-unauthenticated --service-account $InvokerSa `
        --set-env-vars "$CommonEnv,APP_MODULE=lalfita.sandbox.service:app,AGENTS_WEBHOOK_URL=$AgentsUrl/webhooks/portal,SIM_DAY_SECONDS=30"
}
$SandboxUrl = Get-ServiceUrl "lalfita-sandbox"

Invoke-Checked "Pointing agents at the sandbox" {
    gcloud run services update lalfita-agents --region $Region `
        --update-env-vars "SANDBOX_BASE_URL=$SandboxUrl" | Out-Null
}

Invoke-Checked "Deploying API (public: the dashboard's browser calls land here)" {
    gcloud run deploy lalfita-api --source "$Root\backend" --region $Region `
        --allow-unauthenticated `
        --set-env-vars "$CommonEnv,APP_MODULE=lalfita.api.service:app,SANDBOX_BASE_URL=$SandboxUrl"
}
$ApiUrl = Get-ServiceUrl "lalfita-api"

Write-Host "-> Pub/Sub push subscription -> agents service (authenticated push)"
gcloud pubsub subscriptions create lalfita-events-push --topic $Topic `
    --push-endpoint "$AgentsUrl/pubsub/push" `
    --push-auth-service-account $InvokerSa --ack-deadline 60 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked "  (exists - updating push config)" {
        gcloud pubsub subscriptions modify-push-config lalfita-events-push `
            --push-endpoint "$AgentsUrl/pubsub/push" `
            --push-auth-service-account $InvokerSa
    }
}

Write-Host "-> Cloud Scheduler: Sentinel tick every minute (authenticated)"
gcloud scheduler jobs create http lalfita-sentinel-tick --location $Region `
    --schedule "* * * * *" --uri "$AgentsUrl/tasks/tick" --http-method POST `
    --oidc-service-account-email $InvokerSa --oidc-token-audience $AgentsUrl 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked "  (exists - updating job)" {
        gcloud scheduler jobs update http lalfita-sentinel-tick --location $Region `
            --uri "$AgentsUrl/tasks/tick" `
            --oidc-service-account-email $InvokerSa --oidc-token-audience $AgentsUrl
    }
}

$DashImage = "$Region-docker.pkg.dev/$ProjectId/lalfita/dashboard:latest"
Invoke-Checked "Building dashboard image (API base is baked in at build time)" {
    gcloud builds submit "$Root\dashboard" --config "$Root\dashboard\cloudbuild.yaml" `
        --substitutions "_API_BASE=$ApiUrl,_IMAGE=$DashImage"
}
Invoke-Checked "Deploying dashboard" {
    gcloud run deploy lalfita-dashboard --image $DashImage --region $Region --allow-unauthenticated
}
$DashboardUrl = Get-ServiceUrl "lalfita-dashboard"

Write-Host ""
Write-Host "OK - deployed:"
Write-Host "   dashboard: $DashboardUrl   <-- open this"
Write-Host "   api:       $ApiUrl"
Write-Host "   agents:    $AgentsUrl   (IAM-locked: Pub/Sub, Scheduler, sandbox only)"
Write-Host "   sandbox:   $SandboxUrl"
Write-Host ""
Write-Host "Smoke check:  curl.exe $ApiUrl/healthz ; curl.exe $SandboxUrl/healthz"
Write-Host "An unauthenticated call to $AgentsUrl/healthz should return 403 - that's the lock."
