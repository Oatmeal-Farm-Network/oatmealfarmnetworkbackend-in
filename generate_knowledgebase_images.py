"""
generate_knowledgebase_images.py

Generates hero header images for the three knowledgebase pages
(Plant, Livestock, Ingredient) and species/category card images
for any entries that are missing them, using Google Vertex AI Imagen.

Images are saved to public/images/ in the frontend repo so they can
be committed and deployed.  Update OUTPUT_DIR to match your local path.

Usage:
    python generate_knowledgebase_images.py
    python generate_knowledgebase_images.py --only heroes
    python generate_knowledgebase_images.py --only plant_categories
    python generate_knowledgebase_images.py --only livestock_species
    python generate_knowledgebase_images.py --only ingredient_categories

Requirements:
    pip install google-auth google-cloud-storage
    GOOGLE_APPLICATION_CREDENTIALS must point to your service-account JSON.
"""

import os
import sys
import time
import uuid
import base64
import json
import argparse
import urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

GCS_PROJECT  = "animated-flare-421518"
GCS_LOCATION = "us-central1"
GCS_BUCKET   = "oatmeal-farm-network-images"
GCS_PREFIX   = "knowledgebase-headers"

# Path to the frontend public/images directory — adjust if needed
OUTPUT_DIR = Path(__file__).parent.parent / "OatmealFarmNetwork" / "public" / "images"

ASPECT_RATIO = "16:9"   # landscape for hero banners
CARD_RATIO   = "1:1"    # square for category/species cards


# ── Vertex AI Imagen helper ───────────────────────────────────────────────────

def _credentials():
    import google.auth
    import google.auth.transport.requests
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials


def generate_image_bytes(prompt: str, aspect_ratio: str = "1:1") -> bytes:
    """Call Vertex AI Imagen and return raw PNG bytes."""
    credentials = _credentials()
    endpoint = (
        f"https://{GCS_LOCATION}-aiplatform.googleapis.com/v1/projects/"
        f"{GCS_PROJECT}/locations/{GCS_LOCATION}/publishers/google/models/"
        f"imagen-3.0-generate-001:predict"
    )
    payload = json.dumps({
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
            "safetyFilterLevel": "block_few",
            "personGeneration": "dont_allow",
            "outputMimeType": "image/png",
        },
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

    return base64.b64decode(result["predictions"][0]["bytesBase64Encoded"])


def save_image(image_bytes: bytes, filename: str) -> Path:
    """Write PNG bytes to OUTPUT_DIR/<filename>."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUTPUT_DIR / filename
    dest.write_bytes(image_bytes)
    print(f"  ✓ Saved  → {dest}")
    return dest


def generate_and_save(prompt: str, filename: str, aspect_ratio: str = "1:1", delay: float = 1.5):
    """Generate one image and save it; skip if file already exists."""
    dest = OUTPUT_DIR / filename
    if dest.exists():
        print(f"  – Skipped (exists): {filename}")
        return
    print(f"  Generating: {filename}")
    print(f"    Prompt: {prompt[:90]}…" if len(prompt) > 90 else f"    Prompt: {prompt}")
    try:
        image_bytes = generate_image_bytes(prompt, aspect_ratio)
        save_image(image_bytes, filename)
    except Exception as e:
        print(f"  ✗ FAILED for {filename}: {e}")
    time.sleep(delay)


# ── Hero / header images ──────────────────────────────────────────────────────

HERO_IMAGES = [
    {
        "filename": "PlantDBHeader.webp",
        "prompt": (
            "Wide panoramic banner photograph of a lush market garden overflowing with "
            "colorful food plants — rainbow chard, heirloom tomatoes, fresh herbs, edible "
            "flowers, and climbing beans. Golden morning light, photorealistic, 4k, no text."
        ),
    },
    {
        "filename": "HomepageLivestockDB.webp",
        "prompt": (
            "Wide panoramic banner photograph of a peaceful mixed livestock farm at golden "
            "hour — cattle, sheep, goats, and chickens on green pasture with a red barn in "
            "the background. Photorealistic, 4k, no text, no labels."
        ),
    },
    {
        "filename": "FruitsIngredientHeader.webp",
        "prompt": (
            "Wide panoramic banner photograph of an abundant harvest table covered with "
            "colorful fresh fruits, vegetables, herbs, spices, grains, and nuts arranged "
            "artfully on rustic wood. Studio food photography, bright natural light, "
            "photorealistic, 4k, no text."
        ),
    },
]


# ── Plant knowledgebase category card images ──────────────────────────────────

PLANT_CATEGORIES = [
    ("Algae.webp",          "Close-up of glossy green and dark-purple seaweed varieties — wakame, nori, kelp — arranged on white marble. Food photography, studio lighting, photorealistic."),
    ("Berries.webp",        "Abundance of fresh mixed berries — blueberries, raspberries, strawberries, blackberries — scattered on a white marble surface. Vibrant colors, food photography, 4k."),
    ("Bulbs.webp",          "Fresh onions, garlic bulbs, shallots, and leeks arranged on rustic wood. Natural light, food photography, earthy tones, photorealistic."),
    ("Corms.webp",          "Fresh taro roots, water chestnuts, and konjac corms on a wooden surface. Natural light, food photography, earthy textures, photorealistic."),
    ("CulinaryHerbs.webp",  "Lush fresh culinary herbs — basil, rosemary, thyme, parsley, cilantro — arranged on white marble with water droplets. Studio lighting, food photography, photorealistic."),
    ("EdibleFlowers.webp",  "Beautiful edible flowers — nasturtiums, lavender, rose petals, borage — arranged artfully on white background. Macro photography, vibrant colors, photorealistic."),
    ("Fruit.webp",          "Colorful assortment of fresh fruits — mangoes, peaches, figs, citrus, apples — arranged on rustic wood. Natural light, food photography, photorealistic."),
    ("Ginko.webp",          "Fan-shaped ginkgo leaves in golden autumn colors with pale ginkgo nuts on a dark surface. Macro nature photography, photorealistic."),
    ("Grains.webp",         "Beautiful arrangement of raw grains — wheat, rice, barley, oats, rye — in wooden bowls and scattered on burlap. Natural light, food photography, photorealistic."),
    ("Grasses.webp",        "Rolling wheat fields with golden grain heads at sunset, close-up detail of grass seed heads. Nature photography, photorealistic."),
    ("LeafyGreens.webp",    "Fresh leafy greens — kale, spinach, arugula, Swiss chard, lettuce — arranged on white marble with water droplets. Food photography, vibrant greens, photorealistic."),
    ("Legumes.webp",        "Colorful variety of legumes — black beans, lentils, chickpeas, split peas — in small wooden bowls arranged on burlap. Food photography, natural light, photorealistic."),
    ("MedicinalHerbs.webp", "Dried and fresh medicinal herbs — chamomile, echinacea, valerian, lavender — arranged with small apothecary bottles on weathered wood. Warm light, photorealistic."),
    ("Mushrooms.webp",      "Fresh gourmet mushrooms — chanterelles, shiitake, oyster, porcini — on dark wood. Dramatic studio lighting, photorealistic, food photography."),
    ("Nuts.webp",           "Assortment of shelled and whole nuts — walnuts, almonds, pecans, cashews, hazelnuts — in wooden bowls on rustic wood. Natural light, food photography, photorealistic."),
    ("Palms.webp",          "Fresh coconuts, medjool dates, and heart of palm arranged on a bright tropical background. Natural light, food photography, photorealistic."),
    ("Psuodcereals.webp",   "Colorful ancient pseudocereals — quinoa, amaranth, buckwheat — in terracotta bowls on rustic wood. Natural light, food photography, photorealistic."),
    ("Rhizomes.webp",       "Fresh rhizomes — ginger root, turmeric, galangal — arranged on dark slate. Natural light, warm golden tones, food photography, photorealistic."),
    ("RootVegetables.webp", "Fresh root vegetables — carrots, parsnips, beets, turnips, radishes — with soil still attached, arranged on burlap. Natural light, food photography, photorealistic."),
    ("Spices.webp",         "Colorful ground and whole spices — cinnamon, cardamom, paprika, turmeric, star anise — in small ceramic bowls on dark stone. Studio lighting, food photography, photorealistic."),
    ("Tubers.webp",         "Assortment of fresh tubers — potatoes, sweet potatoes, yams, cassava — on rustic wood. Natural light, earthy tones, food photography, photorealistic."),
    ("Vegetables.webp",     "Colorful fresh vegetables — asparagus, corn, squash, bell peppers, zucchini — arranged on white marble. Natural light, food photography, vibrant colors, photorealistic."),
]


# ── Livestock species card images ─────────────────────────────────────────────

LIVESTOCK_SPECIES = [
    ("Alpaca.webp",       "Portrait of a fluffy alpaca with a curious expression in a green pasture. Natural light, photorealistic, animal photography."),
    ("Bison.webp",        "Majestic American bison standing in an open grassland with dramatic sky. Nature photography, photorealistic."),
    ("Buffalo.webp",      "Water buffalo in a lush green field. Natural light, animal photography, photorealistic."),
    ("Camels.webp",       "Camel in a desert landscape at golden hour. Natural light, photorealistic, animal photography."),
    ("Cattle.webp",       "Beautiful Angus cattle grazing on green pasture with blue sky background. Natural light, photorealistic, farm photography."),
    ("Chicken.webp",      "Colorful free-range chickens on a green farm pasture. Natural light, photorealistic, farm photography."),
    ("Alligator.webp",    "American alligator resting on a riverbank in natural habitat. Nature photography, photorealistic."),
    ("deer.webp",         "White-tailed deer in a sunlit meadow. Nature photography, natural light, photorealistic."),
    ("Dogs.webp",         "Working herding dog on a farm with livestock in the background. Natural light, photorealistic."),
    ("Donkeys.webp",      "Friendly donkeys in a farm paddock. Natural light, photorealistic, animal photography."),
    ("Duck.webp",         "Colorful Muscovy and Pekin ducks on a farm pond. Natural light, photorealistic, animal photography."),
    ("Emu.webp",          "Large emu close-up portrait in Australian outback setting. Natural light, photorealistic."),
    ("Geese.webp",        "White geese on a green farm pasture. Natural light, photorealistic, farm photography."),
    ("Goats.webp",        "Playful goats on a green hillside farm. Natural light, photorealistic, animal photography."),
    ("Guineafowl.webp",   "Spotted guinea fowl foraging on a farm. Natural light, photorealistic, animal photography."),
    ("HoneyBees.webp",    "Honey bees on a honeycomb frame. Macro photography, natural light, photorealistic."),
    ("cowboy2.webp",      "Beautiful horses galloping in a green pasture at golden hour. Nature photography, photorealistic."),
    ("Llama2.webp",       "Llama portrait in Andean mountain landscape. Natural light, photorealistic, animal photography."),
    ("muskox.webp",       "Musk ox in Arctic tundra landscape with dramatic sky. Nature photography, photorealistic."),
    ("Ostrich.webp",      "Ostrich in African savanna landscape. Natural light, photorealistic, animal photography."),
    ("Pheasant.webp",     "Colorful ring-necked pheasant in natural habitat. Nature photography, photorealistic."),
    ("Pig.webp",          "Happy heritage breed pigs on a green farm pasture. Natural light, photorealistic, farm photography."),
    ("Pigeon.webp",       "White and grey pigeons in a dovecote. Natural light, photorealistic, animal photography."),
    ("Quail.webp",        "California quail in natural habitat with ground cover. Nature photography, photorealistic."),
    ("Rabitts.webp",      "Fluffy rabbits in a green farm setting. Natural light, photorealistic, animal photography."),
    ("Sheepbreeds.webp",  "Sheep with thick wool coats grazing on green hillside pasture. Natural light, photorealistic, farm photography."),
    ("Snail.webp",        "Land snails on fresh green leaves with dew drops. Macro photography, natural light, photorealistic."),
    ("Turkey.webp",       "Heritage breed turkeys on a green farm. Natural light, photorealistic, farm photography."),
    ("Yak.webp",          "Yak with thick shaggy coat in Himalayan mountain landscape. Nature photography, photorealistic."),
]


# ── Ingredient knowledgebase category card images ─────────────────────────────

INGREDIENT_CATEGORIES = [
    ("AlgaeIngredientHeader.webp",          "Bowl of fresh and dried culinary algae — nori, wakame, kombu — on white marble. Food photography, natural light, photorealistic."),
    ("BeansIngredientHeader.webp",           "Variety of dried beans — black beans, pinto, cannellini, kidney — in small ceramic bowls. Food photography, natural light, photorealistic."),
    ("BerriesIngredientHeader.webp",         "Fresh mixed berries in a white ceramic bowl. Food photography, natural light, vibrant, photorealistic."),
    ("BreadsIngredientHeader.webp",          "Artisan sourdough bread loaves and baguettes on rustic wooden board. Food photography, natural light, photorealistic."),
    ("CandyIngredientHeader.webp",           "Colorful artisan candies and chocolates on a white marble surface. Food photography, studio lighting, photorealistic."),
    ("CheesesIngredientHeader.webp",         "Assortment of artisan cheeses with grapes and honey on a wooden board. Food photography, natural light, photorealistic."),
    ("ChemicalsIngredientHeader.webp",       "Food-safe leavening agents, pectin, and natural food additives in small glass jars. Clean, studio lighting, photorealistic."),
    ("EdibleflowersIngredientHeader.webp",   "Edible flowers — nasturtiums, borage, pansies — in a white ceramic bowl. Macro food photography, natural light, photorealistic."),
    ("FishIngredientHeader.webp",            "Fresh whole fish — salmon, sea bass, sardines — on ice at a fish market. Food photography, natural light, photorealistic."),
    ("FruitIngredientHeader.webp",           "Colorful tropical and stone fruits arranged on white marble. Food photography, natural light, vibrant colors, photorealistic."),
    ("GrainIngredientHeader.webp",           "Assortment of whole grains in small wooden bowls — farro, barley, wheat berries. Food photography, natural light, photorealistic."),
    ("GrainsIngredientHeader.webp",          "Golden wheat grains and diverse cereal grains on burlap. Food photography, warm tones, photorealistic."),
    ("HerbsIngredientHeader.webp",           "Fresh culinary herbs in small terracotta pots on a rustic wooden table. Food photography, natural light, photorealistic."),
    ("JuicesIngredientHeader.webp",          "Colorful fresh-pressed juices in glass bottles — green, orange, red, purple. Studio lighting, food photography, photorealistic."),
    ("LegumesIngredientHeader.webp",         "Colorful legumes — lentils, chickpeas, split peas — in white ceramic bowls on marble. Food photography, natural light, photorealistic."),
    ("MeatsIngredientHeader.webp",           "Artisan butcher shop display with various fresh cuts of meat on white marble. Food photography, natural light, photorealistic."),
    ("MelonsIngredientHeader.webp",          "Fresh sliced watermelon, cantaloupe, and honeydew on white marble. Food photography, vibrant colors, photorealistic."),
    ("MilksIngredientHeader.webp",           "Glass bottles of whole milk, cream, and oat milk on a bright kitchen counter. Food photography, natural light, photorealistic."),
    ("MollusksIngredientHeader.webp",        "Fresh oysters, clams, and mussels on crushed ice with lemon. Food photography, natural light, photorealistic."),
    ("NutsIngredientHeader.webp",            "Mixed nuts in rustic wooden bowls on dark slate. Food photography, natural light, photorealistic."),
    ("OilsIngredientHeader.webp",            "Olive oil, sesame oil, and herb-infused oils in glass bottles. Studio lighting, food photography, photorealistic."),
    ("PastasIngredientHeader.webp",          "Fresh and dried pasta varieties — tagliatelle, penne, tortellini — on rustic wood. Food photography, natural light, photorealistic."),
    ("PeppersIngredientHeader.webp",         "Colorful fresh peppers — bell, jalapeño, Thai chili, habanero — on white marble. Food photography, vibrant colors, photorealistic."),
    ("PowdersIngredientHeader.webp",         "Colorful spice powders — matcha, paprika, turmeric, cocoa — in small ceramic spoons on dark slate. Food photography, photorealistic."),
    ("RiceIngredientHeader.webp",            "Variety of rice — jasmine, brown, wild, Arborio — in small ceramic bowls on white marble. Food photography, natural light, photorealistic."),
    ("RootsIngredientHeader.webp",           "Fresh root vegetables — carrots, parsnips, ginger, turmeric — on rustic wood. Food photography, earthy tones, photorealistic."),
    ("SaltsIngredientHeader.webp",           "Artisan salts — flaky Maldon, pink Himalayan, black lava — in small ceramic bowls on dark slate. Food photography, photorealistic."),
    ("SeedsIngredientHeader.webp",           "Assortment of seeds — sesame, chia, sunflower, pumpkin — in small wooden spoons on white marble. Food photography, photorealistic."),
    ("SpicesIngredientHeader.webp",          "Colorful whole and ground spices in small terracotta bowls on dark background. Food photography, warm dramatic lighting, photorealistic."),
    ("SugarsIngredientHeader.webp",          "Golden caramel, brown sugar, honey, and molasses in glass bowls on white marble. Food photography, warm tones, photorealistic."),
    ("TeasIngredientHeader.webp",            "Loose-leaf teas — green, black, white, herbal — in small ceramic bowls with dried flowers. Food photography, natural light, photorealistic."),
    ("TubersIngredientHeader.webp",          "Fresh tubers — purple potatoes, sweet potatoes, cassava — on rustic wood. Food photography, earthy tones, photorealistic."),
    ("VegetablesIngredientHeader.webp",      "Colorful seasonal vegetables — broccolini, rainbow carrots, heirloom tomatoes — on white marble. Food photography, natural light, photorealistic."),
    ("MushroomsIngredientHeader.webp",       "Gourmet mushrooms — chanterelles, oyster, shiitake — on dark wood. Dramatic food photography, photorealistic."),
    ("GourdIngredientHeader.webp",           "Fresh gourds — butternut squash, pumpkin, delicata — on rustic wood. Natural light, food photography, photorealistic."),
]


# ── CLI runner ────────────────────────────────────────────────────────────────

def run_heroes():
    print("\n── Hero / Header Images ──────────────────────────────────────────")
    for item in HERO_IMAGES:
        generate_and_save(item["prompt"], item["filename"], aspect_ratio=ASPECT_RATIO)


def run_plant_categories():
    print("\n── Plant Category Card Images ────────────────────────────────────")
    for filename, prompt in PLANT_CATEGORIES:
        generate_and_save(prompt, filename, aspect_ratio=CARD_RATIO)


def run_livestock_species():
    print("\n── Livestock Species Card Images ─────────────────────────────────")
    for filename, prompt in LIVESTOCK_SPECIES:
        generate_and_save(prompt, filename, aspect_ratio=CARD_RATIO)


def run_ingredient_categories():
    print("\n── Ingredient Category Card Images ───────────────────────────────")
    for filename, prompt in INGREDIENT_CATEGORIES:
        generate_and_save(prompt, filename, aspect_ratio=CARD_RATIO)


def main():
    parser = argparse.ArgumentParser(description="Generate knowledgebase images via Vertex AI Imagen")
    parser.add_argument(
        "--only",
        choices=["heroes", "plant_categories", "livestock_species", "ingredient_categories"],
        help="Run only one section instead of all",
    )
    args = parser.parse_args()

    print(f"Output directory: {OUTPUT_DIR}")
    print("Images that already exist will be skipped automatically.\n")

    if args.only == "heroes":
        run_heroes()
    elif args.only == "plant_categories":
        run_plant_categories()
    elif args.only == "livestock_species":
        run_livestock_species()
    elif args.only == "ingredient_categories":
        run_ingredient_categories()
    else:
        run_heroes()
        run_plant_categories()
        run_livestock_species()
        run_ingredient_categories()

    print("\nDone. Commit the new images in OatmealFarmNetwork/public/images/ to deploy them.")


if __name__ == "__main__":
    main()
