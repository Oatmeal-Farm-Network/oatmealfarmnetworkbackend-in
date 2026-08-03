"""
upload_local_animal_photos.py
------------------------------
Scans the Photos table, finds animal photos that already exist in
public/images/ (the frontend's Vite public folder), uploads them to
GCS oatmeal-farm-network-images/Animals/, then updates the Photos table.

Usage:
    python scripts/upload_local_animal_photos.py             # full run
    python scripts/upload_local_animal_photos.py --dry-run   # report only
"""

import os
import sys
import argparse
from urllib.parse import quote, unquote

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import engine
from sqlalchemy import text
from google.cloud import storage as gcs

GCS_BUCKET   = "oatmeal-farm-network-images"
GCS_PREFIX   = "Animals"
GCS_BASE     = f"https://storage.googleapis.com/{GCS_BUCKET}/{GCS_PREFIX}"
LOCAL_IMAGES = os.path.abspath(
    os.path.join(_ROOT, "..", "OatmealFarmNetwork", "public", "images")
)

PHOTO_COLS = [f"Photo{i}" for i in range(1, 17)] + ["ListPageImage"]


def build_gcs_url(fname: str) -> str:
    return f"{GCS_BASE}/{quote(fname, safe='')}"


def is_gcs_url(s: str) -> bool:
    return s.startswith("https://storage.googleapis.com/oatmeal-farm-network-images/")


def fname_from_raw(raw: str) -> str:
    """Extract and URL-decode the bare filename."""
    return unquote(raw.strip().split("?")[0].split("/")[-1])


def upload_to_gcs(client, fname: str, filepath: str) -> str:
    bucket = client.bucket(GCS_BUCKET)
    blob   = bucket.blob(f"{GCS_PREFIX}/{fname}")
    ct = "image/jpeg"
    fl = fname.lower()
    if fl.endswith(".webp"): ct = "image/webp"
    elif fl.endswith(".png"): ct = "image/png"
    elif fl.endswith(".gif"): ct = "image/gif"
    blob.upload_from_filename(filepath, content_type=ct)
    return build_gcs_url(fname)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    print(f"Local images dir: {LOCAL_IMAGES}")
    if not os.path.isdir(LOCAL_IMAGES):
        sys.exit(f"ERROR: {LOCAL_IMAGES} not found")

    local_files = set(os.listdir(LOCAL_IMAGES))
    print(f"Local image files available: {len(local_files)}")

    client = gcs.Client()

    # Build GCS index to skip already-uploaded files
    print("Building GCS index...", flush=True)
    all_blobs = list(client.list_blobs(GCS_BUCKET, prefix=f"{GCS_PREFIX}/"))
    gcs_names = set(b.name.replace(f"{GCS_PREFIX}/", "")
                    for b in all_blobs if not b.name.endswith("/"))
    print(f"  Already in GCS: {len(gcs_names)} files", flush=True)

    # Fetch all Photos rows
    with engine.connect() as conn:
        col_list = ", ".join(f"p.{c}" for c in PHOTO_COLS)
        rows = conn.execute(text(f"""
            SELECT p.PhotoID, p.AnimalID, {col_list}
            FROM Photos p
        """)).fetchall()

    print(f"  Photos rows to check: {len(rows)}", flush=True)

    uploaded  = 0
    skipped   = 0
    already   = 0
    not_found = 0
    errors    = 0

    for row in rows:
        mapping  = dict(row._mapping)
        photo_id = mapping["PhotoID"]
        animal_id = mapping["AnimalID"]

        for col in PHOTO_COLS:
            val = mapping.get(col)
            if not val or str(val).strip() in ("", "0"):
                continue
            s = str(val).strip()

            if is_gcs_url(s):
                already += 1
                continue

            fname = fname_from_raw(s)
            if not fname or len(fname) < 4:
                continue

            # Already uploaded?
            if fname in gcs_names:
                skipped += 1
                # Still update the DB if not already pointing to GCS
                new_url = build_gcs_url(fname)
                if not dry:
                    with engine.begin() as c2:
                        c2.execute(text(
                            f"UPDATE Photos SET [{col}] = :url WHERE PhotoID = :pid"
                        ), {"url": new_url, "pid": photo_id})
                continue

            # File exists locally?
            local_path = os.path.join(LOCAL_IMAGES, fname)
            if not os.path.exists(local_path):
                not_found += 1
                continue

            # Upload
            try:
                if not dry:
                    new_url = upload_to_gcs(client, fname, local_path)
                    gcs_names.add(fname)  # update index
                    with engine.begin() as c2:
                        c2.execute(text(
                            f"UPDATE Photos SET [{col}] = :url WHERE PhotoID = :pid"
                        ), {"url": new_url, "pid": photo_id})
                uploaded += 1
                print(f"  [UP] Animal {animal_id} {col}: {fname}", flush=True)
            except Exception as e:
                errors += 1
                print(f"  [ERR] Animal {animal_id} {col}: {fname} -- {e}", flush=True)

    print(flush=True)
    print(f"Done.")
    print(f"  Uploaded to GCS:      {uploaded}")
    print(f"  Already in GCS (DB updated): {skipped}")
    print(f"  Already correct GCS URL:     {already}")
    print(f"  Not found locally:    {not_found}")
    print(f"  Errors:               {errors}")
    if dry:
        print("  (dry-run -- no writes made)")


if __name__ == "__main__":
    main()
