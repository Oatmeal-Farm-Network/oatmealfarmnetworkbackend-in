#!/usr/bin/env bash
# Create Cloud SQL SQL Server in INDIA (asia-south1) for oatmealindia.
# Run in Google Cloud Shell (logged into project oatmealindia):
#   bash scripts/create-india-sql.sh
#
# Does NOT use us-central1. Existing us-central1 instance oatmealaiindia
# can be deleted later after you cut over.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oatmealindia}"
REGION="${REGION:-asia-south1}"
INSTANCE_ID="${INSTANCE_ID:-oatmealaiindia-in}"
TIER="${TIER:-db-custom-2-7680}"   # 2 vCPU, 7.5 GB — adjust as needed
ROOT_PASSWORD="${ROOT_PASSWORD:-}"  # required
DB_NAME="${DB_NAME:-oatmealailivedb}"
AUTH_NET="${AUTH_NET:-0.0.0.0/0}"   # tighten after bring-up

if [[ -z "$ROOT_PASSWORD" ]]; then
  echo "Set ROOT_PASSWORD first, e.g.:"
  echo "  export ROOT_PASSWORD='YourStrongPassword!'"
  echo "  bash scripts/create-india-sql.sh"
  exit 1
fi

echo "==> Project=$PROJECT_ID Region=$REGION Instance=$INSTANCE_ID"
gcloud config set project "$PROJECT_ID"

echo "==> Enable sqladmin API"
gcloud services enable sqladmin.googleapis.com --project="$PROJECT_ID"

if gcloud sql instances describe "$INSTANCE_ID" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "==> Instance $INSTANCE_ID already exists"
else
  echo "==> Creating SQL Server 2022 in $REGION (this takes several minutes)..."
  gcloud sql instances create "$INSTANCE_ID" \
    --project="$PROJECT_ID" \
    --database-version=SQLSERVER_2022_STANDARD \
    --tier="$TIER" \
    --region="$REGION" \
    --root-password="$ROOT_PASSWORD" \
    --assign-ip \
    --authorized-networks="$AUTH_NET" \
    --storage-size=50GB \
    --storage-auto-increase \
    --availability-type=ZONAL
fi

echo "==> Ensure database $DB_NAME exists"
gcloud sql databases create "$DB_NAME" \
  --instance="$INSTANCE_ID" \
  --project="$PROJECT_ID" \
  2>/dev/null || echo "(database may already exist)"

IP="$(gcloud sql instances describe "$INSTANCE_ID" \
  --project="$PROJECT_ID" \
  --format='value(ipAddresses[0].ipAddress)')"

echo
echo "============================================"
echo "INDIA SQL READY — use these GitHub secrets"
echo "============================================"
echo "DB_TYPE=sqlserver"
echo "DB_SERVER=$IP"
echo "DB_PORT=1433"
echo "DB_USER=sqlserver"
echo "DB_PASSWORD=<same as ROOT_PASSWORD / sqlserver user password>"
echo "DB_NAME=$DB_NAME"
echo
echo "Connection name: ${PROJECT_ID}:${REGION}:${INSTANCE_ID}"
echo "Cloud Run region must stay: asia-south1"
echo
echo "Next:"
echo "  1) Set/update backend repo secrets (especially DB_SERVER=$IP)"
echo "  2) Re-run Deploy Main Backend (India)"
echo "  3) Import BAK / migrate data from old us-central1 instance if needed"
echo "  4) Delete old us-central1 instance oatmealaiindia when cutover is done"
echo "============================================"
