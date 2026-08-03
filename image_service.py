# image_service.py
# Handles AI image generation via Google Vertex AI Imagen
# and storage in Google Cloud Storage.
# Called as a FastAPI BackgroundTask after catalog responses.

import os
import time
import uuid
import base64
from sqlalchemy.orm import Session
from sqlalchemy import text

GCS_BUCKET      = "oatmeal-farm-network-images"
GCS_PREFIX      = "ingredients"
GCS_PROJECT     = "animated-flare-421518"
GCS_LOCATION    = "us-central1"

# ── GCS client ────────────────────────────────────────────────────────────────

def _gcs_client():
    from google.cloud import storage
    return storage.Client()


def upload_image_to_gcs(image_bytes: bytes, filename: str, content_type: str = "image/png") -> str:
    """Upload bytes to GCS and return the public URL."""
    client  = _gcs_client()
    bucket  = client.bucket(GCS_BUCKET)
    blob    = bucket.blob(f"{GCS_PREFIX}/{filename}")
    blob.upload_from_string(image_bytes, content_type=content_type)
    # With uniform bucket-level access, public access is set at bucket level
    # Return the public URL directly (bucket must have allUsers storage.objectViewer)
    return f"https://storage.googleapis.com/{GCS_BUCKET}/{GCS_PREFIX}/{filename}"


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(ingredient_name: str, product_type: str, cut_name: str = None) -> str:
    base = (
        "Professional food photography, studio lighting, white background, "
        "sharp focus, highly detailed, photorealistic, 4k, no text, no labels"
    )

    if product_type == "meat" and cut_name:
        subject = f"a fresh raw {ingredient_name} {cut_name} cut of meat, butcher shop quality"
    elif product_type == "meat":
        subject = f"fresh raw {ingredient_name} meat, butcher shop quality"
    elif product_type == "produce":
        subject = f"fresh {ingredient_name}, farm fresh, vibrant color, whole and cut"
    elif product_type == "processed_food":
        subject = f"{ingredient_name}, artisan food product, appetizing presentation"
    else:
        subject = f"fresh {ingredient_name}, food photography"

    return f"{subject}, {base}"


# ── Vertex AI Imagen generation ───────────────────────────────────────────────

def generate_image_bytes(prompt: str) -> bytes:
    """
    Generate an image using Google Vertex AI Imagen.
    Returns raw PNG bytes.
    """
    import google.auth
    import google.auth.transport.requests
    import urllib.request
    import json

    # Get credentials from GOOGLE_APPLICATION_CREDENTIALS env var
    credentials, project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)

    endpoint = (
        f"https://{GCS_LOCATION}-aiplatform.googleapis.com/v1/projects/"
        f"{GCS_PROJECT}/locations/{GCS_LOCATION}/publishers/google/models/"
        f"imagen-3.0-generate-001:predict"
    )

    payload = json.dumps({
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1",
            "safetyFilterLevel": "block_few",
            "personGeneration": "dont_allow",
            "outputMimeType": "image/png",
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    # Response contains base64-encoded PNG
    b64_image = result["predictions"][0]["bytesBase64Encoded"]
    return base64.b64decode(b64_image)


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_and_store_ingredient_image(
    ingredient_id: int,
    ingredient_name: str,
    product_type: str,
    db: Session,
    cut_name: str = None,
) -> str | None:
    """
    1. Generate image via Vertex AI Imagen
    2. Upload to GCS under ingredients/
    3. Update Ingredients.IngredientImage with the public URL
    4. Return the public URL (or None on failure)
    """
    try:
        prompt      = build_prompt(ingredient_name, product_type, cut_name)
        print(f"[image_service] Generating image for '{ingredient_name}' ({product_type})")

        image_bytes = generate_image_bytes(prompt)
        filename    = f"{ingredient_id}_{uuid.uuid4().hex[:8]}.png"
        public_url  = upload_image_to_gcs(image_bytes, filename, content_type="image/png")

        # Update Ingredients table
        db.execute(text("""
            UPDATE Ingredients
            SET IngredientImage = :url
            WHERE IngredientID = :iid
        """), {"url": public_url, "iid": ingredient_id})
        db.commit()

        print(f"[image_service] ✓ Stored image for IngredientID={ingredient_id}: {public_url}")
        return public_url

    except Exception as e:
        print(f"[image_service] ✗ Failed for IngredientID={ingredient_id}: {e}")
        return None


# ── Background task entry point ───────────────────────────────────────────────

def ensure_images_for_catalog(items: list[dict], get_db_factory):
    """
    Background task: find catalog items missing images, generate sequentially.
    Creates its own DB session to avoid blocking the request session.
    """
    db_gen = get_db_factory()
    db = next(db_gen)
    try:
        seen_ingredient_ids = set()

        for item in items:
            if item.get("ImageURL"):
                continue

            ingredient_id = item.get("IngredientID")
            if not ingredient_id or ingredient_id in seen_ingredient_ids:
                continue

            seen_ingredient_ids.add(ingredient_id)

            # Check DB — may have been generated since catalog was fetched
            row = db.execute(text("""
                SELECT IngredientImage FROM Ingredients WHERE IngredientID = :iid
            """), {"iid": ingredient_id}).fetchone()

            if row and row[0]:
                continue

            generate_and_store_ingredient_image(
                ingredient_id=ingredient_id,
                ingredient_name=item.get("Title", "food item"),
                product_type=item.get("ProductType", "produce"),
                db=db,
                cut_name=item.get("CategoryName"),
            )

            # Small delay between generations
            time.sleep(1)

    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass