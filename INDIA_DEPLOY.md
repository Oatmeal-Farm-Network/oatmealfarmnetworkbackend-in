# India CI/CD — OatmealIndia project

## Region policy (required)

Everything for India must stay in **`asia-south1`**:

| Resource | Region |
|----------|--------|
| Cloud Run (frontend + backend + Saige) | `asia-south1` |
| Cloud SQL (SQL Server) | `asia-south1` |
| Artifact Registry | `asia-south1` |

**Do not** point India Cloud Run at a `us-central1` SQL instance.

If you still have `oatmealindia:us-central1:oatmealaiindia`, that is legacy — create a new India SQL instance and cut over:

```bash
export ROOT_PASSWORD='YourStrongPassword!'
bash scripts/create-india-sql.sh
```

Then set GitHub `DB_SERVER` to the new public IP and redeploy.

## GitHub secrets — backend repo

| Secret | Value |
|--------|--------|
| `GOOGLE_CLOUD_PROJECT` | `oatmealindia` |
| `GOOGLE_CLOUD_LOCATION` | `asia-south1` |
| `GOOGLE_SERVICE_ACCOUNT` | `github-deploy-india@oatmealindia.iam.gserviceaccount.com` |
| `WORKLOAD_IDENTITY_PROVIDER` | `projects/151683070823/locations/global/workloadIdentityPools/github-actions-india/providers/github-oidc-india` |
| `FRONTEND_URL` | India frontend Cloud Run URL (after first frontend deploy) |
| `GOOGLE_API_KEY` | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` |
| `VERTEX_AI_MODEL` | `gemini-2.5-flash-lite` |
| `FIRESTORE_DATABASE` | India Firestore DB id |
| `DB_TYPE` / `DB_SERVER` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | India SQL **in asia-south1** |
| `SECRET_KEY` | JWT secret |
| `CLOUD_SQL_INSTANCE` | optional, e.g. `oatmealaiindia-in` (for deploy network checks) |
