#!/usr/bin/env bash
# One-time Workload Identity Federation setup for India GitHub Actions deploys.
# Run on a machine with gcloud admin access to the project.
#
# Usage:
#   chmod +x scripts/setup-india-wif.sh
#   ./scripts/setup-india-wif.sh
#
# After it finishes, add the printed values as GitHub Actions secrets.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-animated-flare-421518}"
PROJECT_NUMBER="${PROJECT_NUMBER:-802455386518}"
REGION="${REGION:-asia-south1}"

# WIF resources (India-specific names)
POOL_ID="${POOL_ID:-github-actions-india}"
PROVIDER_ID="${PROVIDER_ID:-github-oidc-india}"
SA_ID="${SA_ID:-github-deploy-india}"
SA_EMAIL="${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

# GitHub org/repos allowed to impersonate this SA
GITHUB_ORG="${GITHUB_ORG:-Oatmeal-Farm-Network}"
FRONTEND_REPO="${FRONTEND_REPO:-oatmealfarmnetwork-in}"
BACKEND_REPO="${BACKEND_REPO:-oatmealfarmnetworkbackend-in}"

echo "==> Project: $PROJECT_ID ($PROJECT_NUMBER) region=$REGION"
gcloud config set project "$PROJECT_ID"

echo "==> Enable APIs"
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  sts.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

echo "==> Create deploy service account (ignore if exists)"
gcloud iam service-accounts create "$SA_ID" \
  --display-name="GitHub Actions Deploy (India)" \
  || true

echo "==> Grant deploy roles to $SA_EMAIL"
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/iam.serviceAccountUser \
  roles/storage.admin
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE" \
    --condition=None \
    >/dev/null
done

echo "==> Create Workload Identity Pool (ignore if exists)"
gcloud iam workload-identity-pools create "$POOL_ID" \
  --location="global" \
  --display-name="GitHub Actions India" \
  || true

echo "==> Create GitHub OIDC provider (ignore if exists)"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --location="global" \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub OIDC India" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository_owner == '${GITHUB_ORG}'" \
  || true

PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

echo "==> Allow both India repos to impersonate $SA_EMAIL"
for REPO in "$FRONTEND_REPO" "$BACKEND_REPO"; do
  gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_ORG}/${REPO}"
done

echo
echo "============================================"
echo "Add these GitHub Actions secrets to BOTH India repos"
echo "============================================"
echo "WORKLOAD_IDENTITY_PROVIDER = ${PROVIDER_RESOURCE}"
echo "GOOGLE_SERVICE_ACCOUNT     = ${SA_EMAIL}"
echo "GOOGLE_CLOUD_PROJECT       = ${PROJECT_ID}"
echo "GOOGLE_CLOUD_LOCATION      = ${REGION}"
echo
echo "Backend repo also needs app secrets:"
echo "  GOOGLE_API_KEY, GEMINI_MODEL, VERTEX_AI_MODEL, FIRESTORE_DATABASE,"
echo "  DB_TYPE, DB_SERVER, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, SECRET_KEY"
echo
echo "Do NOT add GOOGLE_APPLICATION_CREDENTIALS JSON key anymore (WIF replaces it)."
echo "============================================"
