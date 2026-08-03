# --- jokes.py --- (Saige's joke collection with per-user history so jokes never repeat)
"""
Saige's joke list. When a user asks for a joke, she calls tell_joke_tool().

The tool:
  1. Loads which joke indices this user has already heard (Firestore).
  2. Picks a random UNSEEN joke.
  3. Marks it as told and saves back to Firestore.
  4. If every joke has been told, resets the user's history and starts fresh
     (with a note so it doesn't feel like a glitch).

Storage: saige_joke_history/{people_id} document in the chat-history Firestore DB.
"""
import logging
import random
from typing import List, Optional

from langchain_core.tools import tool

from config import (
    FIRESTORE_AVAILABLE,
    CHAT_HISTORY_DATABASE,
    GCP_CREDENTIALS,
    GCP_PROJECT,
)

logger = logging.getLogger("farm_advisory.jokes")

# ── Joke list ────────────────────────────────────────────────────────────────

JOKES: List[str] = [
    "Why don't ranchers ever retire? They just lose their \"drive\" and turn into \"park.\"",
    "How do you find a rancher in a crowded room? Don't worry, he'll tell you within five minutes what the rainfall was last night.",
    "A rancher's definition of a \"vacation\" is checking the fences in a different county.",
    "What's a rancher's favorite type of music? Anything with a good \"crop\" beat.",
    "Why did the rancher get a medal? For being the best at \"herd\" immunity long before it was cool.",
    "Why did the scarecrow win an award? Because he was a master of \"stalking\" his work.",
    "What do you call a rancher who is good at math? A \"count-ry\" boy.",
    "Why do ranchers make great drummers? They always have a \"beet\" going.",
    "A rancher's \"check engine\" light is usually just a piece of black electrical tape.",
    "Why do cows wear bells? Because their horns don't work.",
    "What do you call a sleeping bull? A bulldozer.",
    "Where do cows go for a first date? To the \"moo-vies.\"",
    "What do you call a cow that's just had a calf? De-calfinated.",
    "Why was the cow so popular? Because she was \"udderly\" fantastic.",
    "What do you call a grumpy cow? \"Moo-dy.\"",
    "Why do cows have hooves instead of feet? Because they \"lactose.\"",
    "What did the mama cow say to the calf? \"It's pasture bedtime.\"",
    "What happens when a cow stops shaving? It gets a \"moo-stache.\"",
    "Why did the cow cross the road? To get to the \"udder\" side.",
    "What do you call a cow that can play a musical instrument? A \"moo-sician.\"",
    "How does a rancher count his cattle? With a \"cow-culator.\"",
    "What do you get from a pampered cow? Spoiled milk.",
    "Why was the steer so smart? He went to \"moo-niversity.\"",
    "What's a cow's favorite holiday? \"Moo-year's\" Day.",
    "What do you call a cow in an earthquake? A milkshake.",
    "Why did the sheep go to the library? He was looking for a \"baaaa-k.\"",
    "What do you call a sheep with no legs? A cloud.",
    "What do you call a sheep that likes to dance? A \"baaa-llerina.\"",
    "Why are sheep such bad drivers? They always make \"ewe-turns.\"",
    "What do you call a sheep that cleans? A \"vacuum baaa-g.\"",
    "Why did the pig go to the casino? To play the \"slop\" machines.",
    "Why was the horse so happy? Because he lived in a \"stable\" environment.",
    "What do you call a horse that lives next door? A \"neigh-bor.\"",
    "Why did the horse eat with its mouth open? Because it had bad \"stable\" manners.",
    "Why did the tractor go to the doctor? It had \"exhaust-ion.\"",
    "Why did the rancher name his tractor \"Relationship\"? Because it was always \"complicated.\"",
    "How does a rancher fix a broken heart? With baling wire and a pair of pliers.",
    "What do you call a tractor that can tell time? A \"Chrono-mower.\"",
    "Why was the combine harvester so shy? It was always \"picking up\" after itself.",
    "Why did the drone join the ranch? To get a \"bird's eye view\" of the budget.",
    "What do you call a high-tech ranch? \"Silicon Valley, but with more dirt.\"",
    "What's a corn's favorite music? Pop.",
    "Why shouldn't you tell secrets in a cornfield? Because the corn has \"ears.\"",
    "What did the baby corn say to the mama corn? \"Where's Pop?\"",
    "Why did the tomato turn red? Because it saw the salad dressing.",
    "What do you call a sad strawberry? A \"blue-berry.\"",
    "What's a potato's favorite TV show? \"Starch\" Trek.",
    "Why did the mushroom go to the party? Because he was a \"fun-gi.\"",
    "What do you call a lettuce that's good at sports? \"Head\" of the team.",
    "What do you call a fake noodle? An \"im-pasta.\"",
    "Why did the gardener quit? His celery was too low.",
    "Why did the grape stop in the middle of the road? It ran out of juice.",
    "What do you call a carrot that's a detective? A \"root\" investigator.",
    "A rancher's prayer: \"Lord, give us rain, but not when I'm haying.\"",
    "Why do ranchers love the wind? Because it's the only thing on the ranch that's \"free.\"",
    "What's the difference between a rancher and a philosopher? A philosopher asks \"Why?\", a rancher asks \"Why now?\"",
    "Why did the rancher name his dog \"Tax\"? Because every time he opened the door, \"Tax\" ran away with his money.",
    "How do you know if it's been a good year? The rancher's truck is newer than his tractor.",
    "Why did the rancher carry a clock? To keep track of \"thyme.\"",
    "What do you call a cow that likes to garden? A \"lawn-mower.\"",
    "Why did the chicken join a band? Because it had the \"drumsticks.\"",
    "What do you call a goat on a mountain? A \"hill-billy.\"",
    "Why did the rancher get a new dog? Because the old one was too \"ruff\" on the sheep.",
    "What's a cow's favorite planet? \"Moo-turn.\"",
    "Why did the rooster cross the road? To prove to the chicken it could be done.",
    "What's a cow's favorite subject? \"Moo-sic.\"",
    "What do you call a cow that's an artist? \"Moo-naa.\"",
    "Why did the sheep go to the spa? To get a \"shear\" relaxation.",
    "What do you call a horse that likes to bake? A \"thorough-bread.\"",
    "Why did the rancher bring a ladder to the barn? To reach the \"high\" stakes.",
    "What's a cow's favorite spice? \"Moo-stard.\"",
    "What do you call a cow with a sense of humor? \"Laughing stock.\"",
    "Why did the rancher name his barn \"The Gym\"? Because he spent all his time \"lifting\" hay.",
    "What's a pig's favorite karate move? The \"pork\" chop.",
    "Why did the farmer get a new hat? He wanted a \"fresh\" perspective.",
    "What do you call a cow that's a detective? \"Sherlock Moos.\"",
]

_TOTAL = len(JOKES)

# ── Firestore persistence ────────────────────────────────────────────────────

_JOKE_HISTORY_COLLECTION = "saige_joke_history"


def _get_db():
    if not FIRESTORE_AVAILABLE or not GCP_PROJECT:
        return None
    credentials = None
    if GCP_CREDENTIALS:
        try:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                GCP_CREDENTIALS,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except Exception as e:
            logger.debug("[jokes] credentials error: %s", e)
    try:
        from google.cloud import firestore
        kwargs = {"project": GCP_PROJECT, "database": CHAT_HISTORY_DATABASE}
        if credentials:
            kwargs["credentials"] = credentials
        return firestore.Client(**kwargs)
    except Exception as e:
        logger.debug("[jokes] Firestore unavailable: %s", e)
        return None


def _load_told(people_id: str) -> List[int]:
    """Return the list of joke indices already told to this user."""
    db = _get_db()
    if db is None:
        return []
    try:
        doc = db.collection(_JOKE_HISTORY_COLLECTION).document(str(people_id)).get()
        if doc.exists:
            return list(doc.to_dict().get("told_indices", []))
    except Exception as e:
        logger.debug("[jokes] load_told error: %s", e)
    return []


def _save_told(people_id: str, told_indices: List[int]) -> None:
    """Persist the updated told-indices list for this user."""
    db = _get_db()
    if db is None:
        return
    try:
        db.collection(_JOKE_HISTORY_COLLECTION).document(str(people_id)).set(
            {"told_indices": told_indices}, merge=True
        )
    except Exception as e:
        logger.debug("[jokes] save_told error: %s", e)


# ── In-memory fallback when Firestore is unavailable ────────────────────────
# Keyed by people_id; survives the process lifetime only.
_memory_fallback: dict = {}


def _pick_joke(people_id: str):
    """Pick an unseen joke for this user. Returns (joke_text, reset_flag)."""
    told: List[int] = _load_told(people_id)
    if not told and people_id in _memory_fallback:
        told = list(_memory_fallback.get(people_id, []))

    unseen = [i for i in range(_TOTAL) if i not in told]
    reset = False

    if not unseen:
        # All jokes told — reset and start over
        told = []
        unseen = list(range(_TOTAL))
        reset = True

    idx = random.choice(unseen)
    told.append(idx)

    _save_told(people_id, told)
    _memory_fallback[people_id] = told  # keep in-memory copy as backup

    return JOKES[idx], reset


# ── LangChain tool ────────────────────────────────────────────────────────────

@tool
def tell_joke_tool(people_id: str = "") -> str:
    """Tell the user a random farm/ranch joke they haven't heard before.
    Tracks joke history per user so the same joke is never repeated until
    all jokes have been told, at which point the cycle resets.
    people_id is injected from session state — do not guess it."""
    if not people_id:
        # Fallback: pick randomly with no history tracking
        return random.choice(JOKES)

    joke, reset = _pick_joke(people_id)

    prefix = ""
    if reset:
        prefix = "Looks like I've run through my whole repertoire — starting the rotation fresh! Here's one:\n\n"

    return f"{prefix}{joke}"


joke_tools = [tell_joke_tool]
