#!/usr/bin/env bash
# One-time India Cloud Run + Artifact Registry bootstrap.
# Requires: gcloud authenticated with access to PROJECT_ID.
#
# Usage:
#   chmod +x scripts/setup-india-cloud.sh
#   ./scripts/setup-india-cloud.sh
#
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-animated-flare-421518}"
REGION="${REGION:-asia-south1}"
AR_REPO="${AR_REPO:-cloud-run-source-deploy}"
SAIGE_AR_REPO="${SAIGE_AR_REPO:-docker-repo}"

FRONTEND_SERVICE="oatmealfarmnetwork-in"
BACKEND_SERVICE="oatmealfarmnetworkbackend-in"
SAIGE_SERVICE="saige-backend-in"

echo "==> Using project=$PROJECT_ID region=$REGION"
gcloud config set project "$PROJECT_ID"

echo "==> Enable required APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com

echo "==> Create Artifact Registry repos (ignore if already exist)"
gcloud artifacts repositories create "$AR_REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="India Cloud Run images" \
  || true

gcloud artifacts repositories create "$SAIGE_AR_REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="India Saige images" \
  || true

echo "==> Placeholder Cloud Run services (nginx hello / can be replaced by first CI deploy)"
# Create empty-ish services only if missing, using a public hello image so URLs exist.
create_if_missing() {
  local name="$1"
  local port="$2"
  if gcloud run services describe "$name" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Service $name already exists"
  else
    gcloud run deploy "$name" \
      --image="us-docker.pkg.dev/cloudrun/container/hello" \
      --region="$REGION" \
      --platform=managed \
      --allow-unauthenticated \
      --port="$port" \
      --memory=512Mi \
      --cpu=1 \
      --min-instances=0 \
      --max-instances=2
  fi
}

create_if_missing "$FRONTEND_SERVICE" 8080
create_if_missing "$BACKEND_SERVICE" 8080
create_if_missing "$SAIGE_SERVICE" 8080

echo
echo "==> India service URLs"
for svc in "$FRONTEND_SERVICE" "$BACKEND_SERVICE" "$SAIGE_SERVICE"; do
  url=$(gcloud run services describe "$svc" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
  echo "$svc => $url"
done

echo
echo "Next:"
echo "1) Put real DB/SECRET_KEY/API keys on $BACKEND_SERVICE and $SAIGE_SERVICE"
echo "2) Add GitHub secrets GCP_PROJECT_ID + GCP_SA_KEY (+ SECRET_KEY, GOOGLE_API_KEY for Saige)"
echo "3) Push to India repos main branch to trigger deploy workflows"
echo "4) If Cloud Run URL host differs from *.asia-south1.run.app assumed in env files, update .env.production and workflow FRONTEND_URL/API_URL"
