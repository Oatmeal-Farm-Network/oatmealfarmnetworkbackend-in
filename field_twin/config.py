"""India Crop Monitor URL — never fall back to the USA us-central1 service."""
from __future__ import annotations

import os

INDIA_CROP_MONITOR_PROD = (
    "https://oatmealfarmnetworkcropmonitorbackend-in-151683070823.asia-south1.run.app"
)
LOCAL_CROP_MONITOR = "http://127.0.0.1:8000/cm"


def crop_monitor_url() -> str:
    env = (os.getenv("CROP_MONITOR_URL") or "").strip().rstrip("/")
    if env:
        return env
    if os.getenv("K_SERVICE") or os.getenv("GAE_ENV"):
        return INDIA_CROP_MONITOR_PROD
    return LOCAL_CROP_MONITOR
