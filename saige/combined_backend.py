"""
Unified launcher that serves Saige + CropMonitor in one FastAPI process.

  /saige/*   -> Saige (chat, threads, precision-ag, chef, pairsley, rosemarie, ...)
  /api/*     -> CropMonitor (fields, analyses, weather, dashboard, ...)
  /static/*  -> CropMonitor static files
  /          -> CropMonitor SPA index
  /<other>   -> CropMonitor SPA fallback (serves static/index.html)

Run from Backend/saige/:
    uvicorn combined_backend:app --reload --port 8001
"""
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# CURRENT_DIR = .../Backend/oatmealfarmnetworkbackend/saige  →  walk up 3 to repo root
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".."))
CROP_DIR = os.path.join(REPO_ROOT, "CropMonitoringBackend")
if not os.path.isdir(CROP_DIR):
    raise RuntimeError(
        f"CropMonitoringBackend not found at {CROP_DIR}. "
        f"Set CROP_MONITOR_PATH env var to override or check the repo layout."
    )
CROP_DIR = os.getenv("CROP_MONITOR_PATH", CROP_DIR)

# Load both .env files explicitly (cwd-based lookup is unreliable after chdir).
# Saige's .env takes priority for overlapping keys — it has the LLM/Redis/Firestore creds.
# Saige's .env historically lives at Backend/saige/.env (sibling of oatmealfarmnetworkbackend/),
# not next to this file — try both locations.
load_dotenv(os.path.join(CROP_DIR, ".env"))
SAIGE_ENV_CANDIDATES = [
    os.path.join(CURRENT_DIR, ".env"),
    os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", "saige", ".env")),  # Backend/saige/.env
    os.path.abspath(os.path.join(CURRENT_DIR, "..", "saige", ".env")),         # extra fallback
]
for _env in SAIGE_ENV_CANDIDATES:
    if os.path.isfile(_env):
        load_dotenv(_env, override=True)
        print(f"[combined_backend] loaded saige env from {_env}")
        break
else:
    print(f"[combined_backend] WARNING: no saige .env found in {SAIGE_ENV_CANDIDATES}")

sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, CROP_DIR)

# CropMonitor uses relative paths ("static/index.html") inside its route handlers,
# so the process cwd must stay at CROP_DIR for those FileResponse calls to resolve.
os.chdir(CROP_DIR)

import backend as crop_module  # noqa: E402
crop_app = crop_module.app

from api import app as saige_app, app_lifespan as saige_lifespan  # noqa: E402


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        for handler in crop_app.router.on_startup:
            result = handler()
            if result is not None:
                await result

        await stack.enter_async_context(saige_lifespan(saige_app))

        try:
            yield
        finally:
            for handler in crop_app.router.on_shutdown:
                result = handler()
                if result is not None:
                    await result


app = FastAPI(title="Saige + CropMonitor Combined", lifespan=combined_lifespan)

# Mount order matters: more-specific mount FIRST so /saige/* wins over the root mount.
app.mount("/saige", saige_app)
app.mount("/", crop_app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8001")))
