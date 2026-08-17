# Oatmeal Farm Network — System Overview

This is the **single source of truth** for how the Oatmeal Farm Network (OFN) pieces fit together and how to run the full stack locally. Repo-specific setup lives in each repo's README; this document covers cross-cutting architecture only.

| Repo | GitHub | README |
|------|--------|--------|
| Backend (this repo) | [oatmealfarmnetworkbackend](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetworkbackend) | [README](../README.md) |
| Frontend | [oatmealfarmnetwork](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetwork) | [README](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetwork/blob/main/README.md) |
| Crop Monitor *(separate checkout)* | Ask the team for access | — |

---

## What OFN Is

This is the **India** OFN stack (`oatmealindia` / `asia-south1`). USA OFN remains a separate product.

The **frontend** is a React SPA. The **backend** is a FastAPI application that handles authentication, marketplace, events, supply chain, livestock, accounting, and dozens of other domain APIs backed by Cloud SQL (SQL Server) in **asia-south1**.

India-specific data layers (vs the USA fork):

| Domain | India source |
|--------|----------------|
| Commodity / mandi prices | farmer.in / Agmarknet (`COMMODITY_MARKET=india`) |
| Weather | Open-Meteo, metric (°C / km/h / mm) + monsoon outlook |
| Crop calendar | Kharif / Rabi / Zaid (`/api/crop-planning/india-calendar`) |
| Schemes | PM-KISAN, PMFBY, KCC, FPO (`/api/grants`) |

Two specialized backends live inside the backend repo and are typically mounted under the main API:

| Mount | Service | Responsibility |
|-------|---------|----------------|
| `/` | Main backend (`main.py`) | Auth, marketplace, events, supply chain, HR, accounting, website builder, … |
| `/saige/*` | [Saige](../saige/README.md) | AI advisory chat (LangGraph + Gemini), push notifications, precision-ag agents |
| `/cm/*` | Crop Monitor *(external repo)* | Field mapping, satellite analyses, vegetation rasters, crop dashboards |

In **production**, these three are often deployed as separate Cloud Run services. In **local full-stack dev**, `server_all.py` combines them into one process on port 8000.

A legacy **Node/Express** service (`src/index.js`, port 3001) serves a small set of OTF admin/nav endpoints used by the frontend via `VITE_OTF_API_URL`. It is optional for most feature work.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend — React + Vite  (port 5173)                           │
│  https://github.com/Oatmeal-Farm-Network/oatmealfarmnetwork     │
└────────────┬────────────────────────────────────────────────────┘
             │  VITE_API_URL, VITE_SAIGE_API_URL, VITE_CROP_API_URL
             │  (dev: Vite proxies /auth, /api, /saige, /cm → :8000)
             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend — FastAPI  (port 8000)                                 │
│  ┌──────────────┬─────────────────┬──────────────────────────┐  │
│  │  /           │  /saige/*       │  /cm/*                   │  │
│  │  main.py     │  saige/api.py   │  CropMonitoringBackend   │  │
│  └──────┬───────┴────────┬────────┴──────────┬───────────────┘  │
└─────────┼────────────────┼─────────────────────┼──────────────────┘
          │                │                     │
          ▼                ▼                     ▼
    Azure SQL         Firestore +          Azure SQL /
    (primary DB)      Redis + Gemini       GCS / Earth Engine
```

**Authentication flow:** The main backend issues JWTs (`SECRET_KEY`, HS256). Saige and protected frontend routes verify the same token. `SECRET_KEY` must match across every service that validates auth.

---

## Local Ports

| Service | Port | Notes |
|---------|------|-------|
| Frontend (Vite) | 5173 | `npm run dev` |
| Unified backend (`server_all.py`) | 8000 | Main + Saige + Crop Monitor |
| Main backend only (`main.py`) | 8000 | No Saige or Crop Monitor |
| Saige only (`saige/api.py`) | 8000 | AI chat in isolation |
| Redis (Saige) | 6379 | `docker compose up` in `saige/` |
| OTF Node API *(optional)* | 3001 | `src/index.js` |

---

## Run Everything Together Locally

### 1. Prerequisites

- Python 3.11+
- Node.js 18+
- Access to the shared Azure SQL database (credentials from the team)
- For AI features: Google API key or GCP service account, Redis
- For crop-monitor routes: a local clone of **CropMonitoringBackend** (see layout below)

### 2. Directory layout

`server_all.py` expects Crop Monitor as a **sibling directory** of the backend repo:

```
your-workspace/
├── oatmealfarmnetworkbackend/    ← this repo
│   ├── main.py
│   ├── server_all.py
│   └── saige/
├── oatmealfarmnetwork/           ← frontend repo
└── CropMonitoringBackend/        ← separate repo (required for /cm routes)
```

Override the crop-monitor path with the `CROP_MONITOR_PATH` environment variable if your layout differs.

### 3. Backend

```powershell
cd oatmealfarmnetworkbackend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Create .env at repo root (see backend README for variables)
# Create saige/.env for AI/Redis/Firestore vars (see saige/README.md)

# Optional: start Redis for Saige
cd saige
docker compose up -d redis
cd ..

# Unified stack (main + Saige + Crop Monitor)
python -m uvicorn server_all:app --reload --port 8000
```

**Without Crop Monitor:** run the main API only:

```powershell
python -m uvicorn main:app --reload --port 8000
```

Most marketplace, auth, and event features work without `/cm`. Precision-ag raster views and Saige field tools need Crop Monitor or `server_all.py`.

### 4. Frontend

```powershell
cd oatmealfarmnetwork
npm install
npm run dev
```

Open http://localhost:5173. `.env.development` points API calls at `http://localhost:8000`; Vite proxies `/auth`, `/api`, `/saige`, and `/cm` to the backend so cookies and CORS stay simple.

### 5. Verify

| Check | URL |
|-------|-----|
| Main API health | http://localhost:8000/health |
| Saige health | http://localhost:8000/saige/health |
| API docs | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |

---

## Production Deployment (overview)

Services run on **Google Cloud Run** (project `animated-flare-421518`, region `us-central1`):

| Service | Typical URL pattern |
|---------|---------------------|
| Main backend | `oatmealfarmnewtorkbackend-*.us-central1.run.app` |
| Saige | `saige-backend-*.us-central1.run.app` |
| Crop Monitor | `oatmealfarmnetworkcropmonitorbackend-*.us-central1.run.app` |
| Frontend | `oatmealfarmnetwork-*.us-central1.run.app` / `oatmealfarmnetwork.com` |
| OTF Node API | `oatmeal-main-*.us-central1.run.app` |

The frontend `.env.production` maps `VITE_*` variables to these URLs. Deployment scripts and service-specific notes live in each repo's README — not duplicated here.

---

## Shared Secrets & Configuration

These values must stay **consistent** across services:

| Variable | Used by |
|----------|---------|
| `SECRET_KEY` | Main backend (JWT signing), Saige (JWT verification) |
| `DB_SERVER`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Main backend, Saige (optional SQL), Node API |
| `FRONTEND_URL` | CORS on backend and Saige |

Saige-specific variables (`GOOGLE_API_KEY`, Redis, Firestore) are documented in [saige/README.md](../saige/README.md). Frontend `VITE_*` variables are documented in the [frontend README](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetwork/blob/main/README.md).

---

## Where to Look Next

- **Backend setup, env vars, tests, deployment** → [backend README](../README.md)
- **Saige API, graph design, RAG, Redis** → [saige/README.md](../saige/README.md)
- **Frontend setup, build, env vars** → [frontend README](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetwork/blob/main/README.md)
