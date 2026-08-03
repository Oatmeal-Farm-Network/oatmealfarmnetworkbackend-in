# India CI/CD — OatmealIndia project

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
| `DB_TYPE` / `DB_SERVER` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | India SQL |
| `SECRET_KEY` | JWT secret |
