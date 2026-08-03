#!/usr/bin/env bash
# One-time WIF + Artifact Registry bootstrap for oatmealindia.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:-oatmealindia}"
REGION="${REGION:-asia-south1}"
POOL_ID=github-actions-india
PROVIDER_ID=github-oidc-india
SA_ID=github-deploy-india
SA_EMAIL="${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
GITHUB_ORG=Oatmeal-Farm-Network

gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
echo "PROJECT_NUMBER=$PROJECT_NUMBER"

gcloud services enable iam.googleapis.com iamcredentials.googleapis.com cloudresourcemanager.googleapis.com sts.googleapis.com run.googleapis.com artifactregistry.googleapis.com

gcloud artifacts repositories create cloud-run-source-deploy --repository-format=docker --location="$REGION" --description="India Cloud Run images" || true
gcloud artifacts repositories create docker-repo --repository-format=docker --location="$REGION" --description="India Saige images" || true

gcloud iam service-accounts create "$SA_ID" --display-name="GitHub Actions Deploy (India)" || true
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="$ROLE" --condition=None >/dev/null
done

gcloud iam workload-identity-pools create "$POOL_ID" --location=global --display-name="GitHub Actions India" || true
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" --location=global --workload-identity-pool="$POOL_ID" --display-name="GitHub OIDC India" --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" --attribute-condition="assertion.repository_owner == '${GITHUB_ORG}'" || true

for REPO in oatmealfarmnetwork-in oatmealfarmnetworkbackend-in; do
  gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" --project="$PROJECT_ID" --role="roles/iam.workloadIdentityUser" --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_ORG}/${REPO}" || true
done

echo "WORKLOAD_IDENTITY_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
echo "GOOGLE_SERVICE_ACCOUNT=${SA_EMAIL}"
echo "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
echo "GOOGLE_CLOUD_LOCATION=${REGION}"
