# Deploy Saige backend to Cloud Run.
# Run from this directory: .\deploy.ps1
# Env-only update (no rebuild): .\deploy.ps1 -EnvOnly
# Requires: gcloud CLI authenticated.

param(
    [switch]$EnvOnly
)

$PROJECT   = "animated-flare-421518"
$REGION    = "us-central1"
$SERVICE   = "saige-backend"
$MAIN_SVC  = "oatmealfarmnewtorkbackend"
$IMAGE_TAG = "us-central1-docker.pkg.dev/$PROJECT/cloud-run-source-deploy/saige-backend:latest"

# SECRET_KEY must match the main backend's SECRET_KEY so JWTs can be verified.
$SECRET_KEY = $env:SECRET_KEY
if (-not $SECRET_KEY) {
    Write-Host "Fetching SECRET_KEY from main backend Cloud Run service..."
    $SECRET_KEY = gcloud run services describe $MAIN_SVC `
        --region=$REGION --project=$PROJECT `
        --format="value(spec.template.spec.containers[0].env.filter(name=SECRET_KEY).extract(value).flatten())" 2>$null
}
if (-not $SECRET_KEY) {
    Write-Error "SECRET_KEY not found. Set `$env:SECRET_KEY or ensure main backend has it configured."
    exit 1
}

function Get-MainEnv($Name) {
    return gcloud run services describe $MAIN_SVC `
        --region=$REGION --project=$PROJECT `
        --format="value(spec.template.spec.containers[0].env.filter(name=$Name).extract(value).flatten())" 2>$null
}

# DB credentials must match the main backend so Saige can read user/business profiles.
$DB_HOST     = Get-MainEnv "DB_HOST"
$DB_NAME     = Get-MainEnv "DB_NAME"
$DB_USER     = Get-MainEnv "DB_USER"
$DB_PASSWORD = Get-MainEnv "DB_PASSWORD"
if (-not $DB_HOST -or -not $DB_NAME -or -not $DB_USER -or -not $DB_PASSWORD) {
    Write-Error "DB_* env vars not found on main backend. Ensure DB_HOST, DB_NAME, DB_USER, DB_PASSWORD are configured."
    exit 1
}

$REDIS_URL = Get-MainEnv "REDIS_URL"
$CRON_SECRET = Get-MainEnv "CRON_SECRET"
if (-not $CRON_SECRET) { $CRON_SECRET = $env:CRON_SECRET }
$REDIS_ENABLED = if ($REDIS_URL) { "true" } else { "false" }
if (-not $REDIS_URL) {
    Write-Warning "REDIS_URL not found on main backend - Redis stays disabled. Add Memorystore URL to main backend for rate limiting and shared checkpoints."
}

$envFile = Join-Path $env:TEMP "saige-backend-env.yaml"
$envLines = @(
    "SECRET_KEY: `"$SECRET_KEY`"",
    "DB_HOST: `"$DB_HOST`"",
    "DB_PORT: `"1433`"",
    "DB_NAME: `"$DB_NAME`"",
    "DB_USER: `"$DB_USER`"",
    "DB_PASSWORD: `"$DB_PASSWORD`"",
    "GOOGLE_CLOUD_PROJECT: `"$PROJECT`"",
    "GOOGLE_CLOUD_LOCATION: `"$REGION`"",
    "FIRESTORE_DATABASE: `"charlie`"",
    "CHAT_HISTORY_DATABASE: `"chat-history`"",
    "FRONTEND_URL: `"https://www.oatmealfarmnetwork.com,https://oatmealfarmnetwork.com`"",
    "GEMINI_MODEL: `"gemini-2.5-flash-lite`"",
    "GOOGLE_GENAI_USE_VERTEXAI: `"true`"",
    "OFN_BACKEND_URL: `"https://oatmealfarmnewtorkbackend-802455386518.us-central1.run.app`"",
    "WEATHER_API_PROVIDER: `"openmeteo`"",
    "ALLOW_ALL_ORIGINS: `"true`"",
    "REDIS_ENABLED: `"$REDIS_ENABLED`"",
    "RAG_TOP_K: `"3`"",
    "ADVISORY_MAX_ITERATIONS: `"2`"",
    "ASSESSMENT_USE_LLM_CLASSIFIER: `"false`"",
    "COMMUNITY_LEARNINGS_ENABLED: `"false`""
)
if ($REDIS_URL) { $envLines += "REDIS_URL: `"$REDIS_URL`"" }
if ($CRON_SECRET) { $envLines += "CRON_SECRET: `"$CRON_SECRET`"" }
$envLines | Set-Content -Path $envFile -Encoding UTF8

if ($EnvOnly) {
    Write-Host "Updating Cloud Run env vars only (no rebuild)..."
    gcloud run services update $SERVICE `
        --region $REGION `
        --project $PROJECT `
        --env-vars-file $envFile
    if (-not $?) { Write-Error "Env update failed"; exit 1 }
} else {
    Write-Host "Building image via Cloud Build..."
    gcloud builds submit --tag $IMAGE_TAG --project=$PROJECT
    if (-not $?) { Write-Error "Build failed"; exit 1 }

    Write-Host "Deploying to Cloud Run..."
    gcloud run deploy $SERVICE `
        --image $IMAGE_TAG `
        --region $REGION `
        --project $PROJECT `
        --env-vars-file $envFile `
        --allow-unauthenticated

    if (-not $?) { Write-Error "Deploy failed"; exit 1 }
}

Remove-Item $envFile -Force -ErrorAction SilentlyContinue

Write-Host "Done. Testing health..."
Start-Sleep -Seconds 8
Invoke-RestMethod "https://$SERVICE-802455386518.$REGION.run.app/health"
