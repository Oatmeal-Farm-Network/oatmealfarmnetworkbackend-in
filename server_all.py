"""
Unified launcher — runs main backend + Saige + CropMonitor in one FastAPI process.

Routes:
  /             -> main backend (auth, marketplace, events, notifications, ...)
  /saige/*      -> Saige (LangGraph chat + push + agent endpoints)
  /cm/*         -> CropMonitor (fields, analyses, weather, raster, zones, ...)

Run from Backend/oatmealfarmnetworkbackend/:
    ../venv/Scripts/python.exe -m uvicorn server_all:app --reload --port 8000

Tricky bit: saige and the main backend each have their own top-level Python
files with overlapping names (`database.py`, `models.py`, `main.py`, `events.py`,
`auth.py`, `jwt_auth.py`). Once one of them lands in sys.modules under the
generic name, the other backend's `from database import …` finds the wrong
module. The fix is to load each backend in its own phase and evict the
conflicting names from sys.modules between phases. Already-resolved references
inside each backend remain valid (Python keeps the module object alive via the
references holding it); we're only freeing the *name slot* so the next backend
can import its own version cleanly.
"""
import os
import sys
import importlib.util
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI


# ── Path resolution ─────────────────────────────────────────────────────────
HERE        = Path(__file__).resolve().parent                  # .../Backend/oatmealfarmnetworkbackend
BACKEND_DIR = HERE.parent                                       # .../Backend  (or oatmeal/)
REPO_ROOT   = BACKEND_DIR.parent                                # .../OatmealFarmNetwork Repo
SAIGE_CODE_DIR = HERE / "saige"
SAIGE_ENV_DIR  = BACKEND_DIR / "saige"                          # legacy env location
# Prefer sibling of this backend (oatmeal/CropMonitoringBackend), then repo-root layout.
CROP_DIR = next(
    (
        p
        for p in (
            BACKEND_DIR / "CropMonitoringBackend",
            REPO_ROOT / "CropMonitoringBackend",
        )
        if p.is_dir()
    ),
    None,
)

if CROP_DIR is None:
    raise RuntimeError(
        "CropMonitoringBackend not found at "
        f"{BACKEND_DIR / 'CropMonitoringBackend'} or {REPO_ROOT / 'CropMonitoringBackend'}"
    )

print("[serve_all] paths:")
print(f"  HERE       = {HERE}")
print(f"  CROP_DIR   = {CROP_DIR}")
print(f"  SAIGE_CODE = {SAIGE_CODE_DIR}")


# ── Load all .env files (later overrides) ───────────────────────────────────
for env_path in [CROP_DIR / ".env", SAIGE_ENV_DIR / ".env", BACKEND_DIR / ".env", HERE / ".env"]:
    if env_path.is_file():
        load_dotenv(env_path, override=True)
        print(f"[serve_all] loaded env: {env_path}")
    else:
        print(f"[serve_all] (skipped, missing): {env_path}")


# ── Module-isolation helpers ────────────────────────────────────────────────

def _evict_from_dir(dir_path: Path, rename_prefix: str, keep: set[str]) -> int:
    """For every module in sys.modules whose file lives under dir_path (and
    whose name is NOT in `keep`), move its sys.modules entry to a prefixed
    name. The module object stays alive via existing references — only the
    import-resolution slot is freed."""
    target = str(dir_path.resolve())
    moved = 0
    for name in list(sys.modules.keys()):
        if name in keep:
            continue
        mod = sys.modules.get(name)
        if mod is None:
            continue
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        try:
            absf = os.path.abspath(f)
        except Exception:
            continue
        try:
            common = os.path.commonpath([target, absf])
        except ValueError:
            continue  # different drives on Windows
        if common != target:
            continue
        sys.modules[rename_prefix + name] = mod
        del sys.modules[name]
        moved += 1
    return moved


def _add_path_front(p: Path) -> None:
    s = str(p)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)


def _remove_path(p: Path) -> None:
    s = str(p)
    while s in sys.path:
        sys.path.remove(s)


# ── Phase 1: load main backend ──────────────────────────────────────────────
# Main backend is cwd-independent, so we can load it before chdir-ing for crop.
# Use an explicit file-path import to avoid colliding with saige/main.py.
_add_path_front(HERE)

print("[serve_all] phase 1: loading main backend")
_main_spec = importlib.util.spec_from_file_location("oatmeal_main_app", str(HERE / "main.py"))
_main_module = importlib.util.module_from_spec(_main_spec)
sys.modules["oatmeal_main_app"] = _main_module
_main_spec.loader.exec_module(_main_module)
main_app = _main_module.app
print("[serve_all] main backend loaded")


# ── Phase 2: evict main backend's top-level modules ────────────────────────
# After this, saige's `from database import Database` and `from models import …`
# will not find main's database/models in sys.modules and will fall through
# to the file system (which we'll point at saige in a moment).
# Keep server_all (this file — uvicorn needs to find it) + the explicitly-
# named main app module so unified_lifespan can still reach it.
_KEEP = {__name__, "server_all", "oatmeal_main_app"}
_evicted = _evict_from_dir(HERE, rename_prefix="_oatmeal_", keep=_KEEP)
print(f"[serve_all] phase 2: evicted {_evicted} main-backend modules from sys.modules")
# Remove HERE from sys.path so saige imports don't accidentally find main's files
_remove_path(HERE)


# ── Phase 3: chdir + load CropMonitor ──────────────────────────────────
# CropMonitor uses cwd-relative paths (`StaticFiles(directory="static")` and
# `FileResponse("static/index.html")`). We chdir into its dir and stay there
# for the rest of the process lifetime — main backend has no cwd dependencies.
# Soft-fail so a broken local Python/stdlib (or missing CropMonitor deps)
# does not take down the main backend + Saige.
crop_app = None
_add_path_front(CROP_DIR)
os.chdir(CROP_DIR)
print(f"[serve_all] phase 3: chdir -> {CROP_DIR}, loading CropMonitor")
try:
    import backend as _crop_module                                # noqa: E402
    crop_app = _crop_module.app
    print("[serve_all] CropMonitor loaded")
except Exception as e:
    print(f"[serve_all] CropMonitor FAILED to load ({type(e).__name__}: {e})")
    print("[serve_all] continuing without /cm mount")
    _remove_path(CROP_DIR)


# ── Phase 4: load Saige ────────────────────────────────────────────────────
# Saige is cwd-independent. Add saige to sys.path; its `from database import …`
# will now find saige/database.py (no main-backend `database` in sys.modules).
_add_path_front(SAIGE_CODE_DIR)
print("[serve_all] phase 4: loading Saige")
from api import app as saige_app, app_lifespan as saige_lifespan  # noqa: E402
print("[serve_all] Saige loaded")


# ── Phase 5: restore main-backend 'database' and 'models' for hot-reload safety
# Saige is fully loaded — all its imports have already resolved and bound into
# each module's namespace.  We re-point sys.modules for the names that the main
# backend uses lazily at request time so those `import models` / `import database`
# calls inside request handlers find the SQLAlchemy versions, not saige's.
_main_db_mod = sys.modules.get("_oatmeal_database")
if _main_db_mod is not None:
    sys.modules["database"] = _main_db_mod
    print("[serve_all] phase 5: sys.modules['database'] restored -> main backend")
else:
    print("[serve_all] phase 5: WARNING _oatmeal_database not in sys.modules — skipping restore")

_main_models_mod = sys.modules.get("_oatmeal_models")
if _main_models_mod is not None:
    sys.modules["models"] = _main_models_mod
    print("[serve_all] phase 5: sys.modules['models'] restored -> main backend")
else:
    print("[serve_all] phase 5: WARNING _oatmeal_models not in sys.modules — skipping restore")


# ── Unified lifespan ───────────────────────────────────────────────────────
@asynccontextmanager
async def unified_lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        subs = [("main", main_app)]
        if crop_app is not None:
            subs.append(("crop", crop_app))
        for label, sub in subs:
            for handler in sub.router.on_startup:
                try:
                    result = handler()
                    if result is not None:
                        await result
                except Exception as e:
                    print(f"[serve_all] {label} startup '{getattr(handler, '__name__', '?')}' failed: {e}")
        try:
            await stack.enter_async_context(saige_lifespan(saige_app))
        except Exception as e:
            print(f"[serve_all] saige lifespan failed: {e}")

        try:
            yield
        finally:
            shutdown_subs = []
            if crop_app is not None:
                shutdown_subs.append(("crop", crop_app))
            shutdown_subs.append(("main", main_app))
            for label, sub in shutdown_subs:
                for handler in sub.router.on_shutdown:
                    try:
                        result = handler()
                        if result is not None:
                            await result
                    except Exception as e:
                        print(f"[serve_all] {label} shutdown '{getattr(handler, '__name__', '?')}' failed: {e}")


# ── Build the unified app ──────────────────────────────────────────────────
app = main_app
app.router.lifespan_context = unified_lifespan
app.mount("/saige", saige_app)
if crop_app is not None:
    app.mount("/cm", crop_app)
    print("[serve_all] mounted: /saige (Saige), /cm (CropMonitor)")
else:
    print("[serve_all] mounted: /saige (Saige); /cm skipped (CropMonitor unavailable)")
print("[serve_all] main backend at root with all original routes")
print("[serve_all] ready.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
