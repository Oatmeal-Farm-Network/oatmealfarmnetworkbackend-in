"""
migrate_animal_photos.py
------------------------
Migrates animal photo URLs so all Photos table entries point to GCS.

Pass 1 — filename-match:
  For each Photos row whose filename already exists in GCS Animals/, update
  the cell to the canonical GCS URL.

Pass 2 — fetch & upload:
  For each remaining Photos row whose Photo* value starts with http but is
  NOT already a GCS URL, attempt to download it and upload to GCS Animals/.
  Then update the cell.

Usage:
    python migrate_animal_photos.py              # both passes
    python migrate_animal_photos.py --pass1      # filename-match only
    python migrate_animal_photos.py --pass2      # fetch-and-upload only
    python migrate_animal_photos.py --dry-run    # report only, no writes
"""

import sys
import os
import time
import argparse
from urllib.parse import quote, unquote

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import engine
from sqlalchemy import text
from google.cloud import storage as gcs

GCS_BUCKET  = "oatmeal-farm-network-images"
GCS_PREFIX  = "Animals"
GCS_BASE    = f"https://storage.googleapis.com/{GCS_BUCKET}/{GCS_PREFIX}"
PHOTO_COLS  = [f"Photo{i}" for i in range(1, 17)] + ["ListPageImage", "Histogram", "FiberAnalysis"]

# ── helpers ───────────────────────────────────────────────────────────────────

def gcs_client():
    return gcs.Client()

def build_gcs_url(fname: str) -> str:
    return f"{GCS_BASE}/{quote(fname, safe='')}"

def fname_from_url(url: str) -> str:
    """Extract bare filename from a URL or path, URL-decoded."""
    from urllib.parse import unquote
    raw = url.strip().split("?")[0].split("/")[-1]
    return unquote(raw)


def fname_variants(fname: str):
    """Yield the filename and common variations to try against GCS."""
    import re
    yield fname
    # strip (small), (medium), (large) suffixes before extension
    base, ext = (fname.rsplit(".", 1) + [""])[:2] if "." in fname else (fname, "")
    cleaned = re.sub(r'\s*\((small|medium|large)\)\s*$', '', base, flags=re.I)
    if cleaned != base:
        yield f"{cleaned}.{ext}" if ext else cleaned
    # webp → jpg fallback
    if ext.lower() == "webp":
        yield f"{base}.jpg"
        yield f"{base}.JPG"
        yield f"{base}.jpeg"

def is_gcs_url(url: str) -> bool:
    return url.startswith("https://storage.googleapis.com/oatmeal-farm-network-images/")

def fetch_bytes(url: str) -> bytes | None:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception:
        pass
    return None

def upload_to_gcs(client, fname: str, data: bytes) -> str:
    bucket = client.bucket(GCS_BUCKET)
    blob   = bucket.blob(f"{GCS_PREFIX}/{fname}")
    # detect content type
    ct = "image/jpeg"
    fl = fname.lower()
    if fl.endswith(".webp"): ct = "image/webp"
    elif fl.endswith(".png"): ct = "image/png"
    elif fl.endswith(".gif"): ct = "image/gif"
    blob.upload_from_string(data, content_type=ct)
    return build_gcs_url(fname)

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass1",   action="store_true")
    ap.add_argument("--pass2",   action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    run_pass1 = args.pass1 or not (args.pass1 or args.pass2)
    run_pass2 = args.pass2 or not (args.pass1 or args.pass2)
    dry = args.dry_run

    client = gcs_client()

    # Build GCS filename index
    print("Building GCS index...", flush=True)
    all_blobs  = list(client.list_blobs(GCS_BUCKET, prefix=f"{GCS_PREFIX}/"))
    gcs_names  = {b.name.replace(f"{GCS_PREFIX}/", ""): b.name
                  for b in all_blobs if not b.name.endswith("/")}
    print(f"  {len(gcs_names)} files in GCS {GCS_PREFIX}/", flush=True)

    # Fetch all Photos rows with at least one non-null, non-GCS value
    with engine.connect() as conn:
        col_list = ", ".join(f"p.{c}" for c in PHOTO_COLS)
        rows = conn.execute(text(f"""
            SELECT p.PhotoID, p.AnimalID, {col_list}
            FROM Photos p
        """)).fetchall()

    print(f"  {len(rows)} Photos rows to check", flush=True)

    updates_pass1 = 0
    updates_pass2 = 0
    errors        = 0

    for row in rows:
        mapping = dict(row._mapping)
        photo_id  = mapping["PhotoID"]
        animal_id = mapping["AnimalID"]

        for col in PHOTO_COLS:
            val = mapping.get(col)
            if not val or str(val).strip() in ("", "0"):
                continue
            s = str(val).strip()

            # Already a GCS URL — nothing to do
            if is_gcs_url(s):
                continue

            fname = fname_from_url(s)
            if not fname or len(fname) < 4:
                continue

            new_url = None

            # ── Pass 1: filename-match ──────────────────────────────────────
            if run_pass1:
                matched_fname = next((v for v in fname_variants(fname) if v in gcs_names), None)
                if matched_fname:
                    new_url = build_gcs_url(matched_fname)
                    updates_pass1 += 1
                    print(f"  [P1] Animal {animal_id} {col}: {fname} -> {matched_fname}", flush=True)

            # ── Pass 2: fetch & upload ──────────────────────────────────────
            already_matched = new_url is not None
            if run_pass2 and not already_matched and s.startswith("http"):
                data = fetch_bytes(s)
                if data:
                    try:
                        if not dry:
                            upload_to_gcs(client, fname, data)
                        new_url = build_gcs_url(fname)
                        updates_pass2 += 1
                        print(f"  [P2] Animal {animal_id} {col}: fetched+uploaded {fname}", flush=True)
                    except Exception as e:
                        errors += 1
                        print(f"  [ERR] Animal {animal_id} {col}: upload failed — {e}", flush=True)
                # else: URL is not fetchable, skip

            # ── Write back ──────────────────────────────────────────────────
            if new_url and not dry:
                with engine.begin() as conn2:
                    conn2.execute(text(
                        f"UPDATE Photos SET [{col}] = :url WHERE PhotoID = :pid"
                    ), {"url": new_url, "pid": photo_id})

    print(flush=True)
    print(f"Done. Pass-1 (filename match): {updates_pass1}, "
          f"Pass-2 (fetch+upload): {updates_pass2}, Errors: {errors}")
    if dry:
        print("(dry-run — no writes made)")


if __name__ == "__main__":
    main()
