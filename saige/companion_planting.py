"""
Companion planting advisor — curated database + LangChain tool.

Sources: Old Farmer's Almanac, Louise Riotte's "Carrots Love Tomatoes",
Three Sisters / traditional polyculture guides, permaculture references.

Data is intentionally conservative: only well-documented pairings are
included. Each entry lists friends (good companions) with the reason,
foes (antagonists) with the reason, and general notes.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from langchain_core.tools import tool


# ─────────────────────────────────────────────────────────────────────
# Crop database
# ─────────────────────────────────────────────────────────────────────
# Each key is the canonical crop name (singular). `aliases` is a list
# of other ways a farmer might refer to the crop (incl. plurals, common
# varietals, regional names).
COMPANION_DATA: Dict[str, dict] = {
    "tomato": {
        "aliases": ["tomatoes", "tomato plant"],
        "friends": [
            ("basil",         "repels thrips and whitefly; said to improve flavor"),
            ("carrot",        "loosen soil around tomato roots"),
            ("parsley",       "attracts hoverflies that eat aphids"),
            ("marigold",      "suppresses root-knot nematodes"),
            ("nasturtium",    "trap crop for aphids and whitefly"),
            ("onion",         "deters many tomato pests"),
            ("garlic",        "fungal suppression"),
            ("borage",        "attracts pollinators, repels tomato hornworm"),
            ("chives",        "repels aphids"),
            ("asparagus",     "mutual — tomato repels asparagus beetle, asparagus repels nematodes"),
        ],
        "foes": [
            ("brassicas",     "stunt each other (includes cabbage, broccoli, kale, cauliflower)"),
            ("corn",          "share the corn earworm / tomato fruitworm"),
            ("potato",        "share blight pathogens"),
            ("fennel",        "inhibits tomato growth"),
            ("kohlrabi",      "brassica — stunts tomato"),
            ("walnut",        "juglone toxicity — keep 50+ ft"),
        ],
        "notes": "Heavy feeder. Rotate on a 3-year cycle with non-solanaceous crops.",
    },
    "corn": {
        "aliases": ["maize", "sweet corn"],
        "friends": [
            ("pole bean",     "beans fix nitrogen corn needs; Three Sisters"),
            ("winter squash", "squash vines shade soil, deter raccoons; Three Sisters"),
            ("pumpkin",       "same role as winter squash"),
            ("cucumber",      "corn acts as trellis; mutual pest confusion"),
            ("melon",         "benefits from shade of corn in hot climates"),
            ("sunflower",     "mutually support, attract pollinators"),
            ("pea",           "nitrogen fixer (spring corn)"),
            ("potato",        "different root depths, little competition"),
        ],
        "foes": [
            ("tomato",        "share corn earworm / tomato fruitworm"),
            ("celery",        "heavy feeders compete"),
        ],
        "notes": "Plant in blocks, not rows, for wind pollination. Heavy nitrogen feeder.",
    },
    "bean": {
        "aliases": ["beans", "pole bean", "bush bean", "green bean", "snap bean"],
        "friends": [
            ("corn",          "trellis; beans fix nitrogen (Three Sisters)"),
            ("carrot",        "carrots loosen soil for beans"),
            ("cucumber",      "mutual pest deterrence"),
            ("cabbage",       "beans attract beneficial insects"),
            ("cauliflower",   "brassicas benefit from fixed nitrogen"),
            ("eggplant",      "beans provide nitrogen"),
            ("radish",        "loosens soil, deters bean beetles"),
            ("rosemary",      "deters Mexican bean beetle"),
            ("summer savory", "improves flavor, deters bean beetles"),
            ("squash",        "Three Sisters"),
        ],
        "foes": [
            ("onion",         "onion family stunts bean growth (also garlic, leek, shallot)"),
            ("garlic",        "stunts bean growth"),
            ("fennel",        "inhibits most crops"),
            ("beet",          "pole beans stunt beets (bush beans are fine)"),
        ],
        "notes": "Nitrogen fixer. Don't over-fertilize with nitrogen.",
    },
    "squash": {
        "aliases": ["winter squash", "summer squash", "zucchini", "courgette", "butternut", "acorn squash"],
        "friends": [
            ("corn",          "Three Sisters: corn gives shade and structure"),
            ("bean",          "Three Sisters: fixes nitrogen"),
            ("nasturtium",    "trap crop for squash bugs"),
            ("marigold",      "deters nematodes and beetles"),
            ("radish",        "deters squash vine borers"),
            ("mint",          "deters aphids and squash bugs (plant in pots — invasive)"),
            ("borage",        "attracts pollinators"),
        ],
        "foes": [
            ("potato",        "compete for soil nutrients; share some diseases"),
        ],
        "notes": "Needs pollinators — plant flowers nearby. Heavy feeder.",
    },
    "pumpkin": {
        "aliases": ["pumpkins"],
        "friends": [
            ("corn",          "Three Sisters"),
            ("bean",          "Three Sisters — nitrogen fixer"),
            ("marigold",      "deters nematodes"),
            ("nasturtium",    "trap crop for aphids and squash bugs"),
            ("oregano",       "general pest deterrent"),
        ],
        "foes": [
            ("potato",        "compete for nutrients"),
        ],
        "notes": "Needs room — vines spread 10–20 ft. Heavy feeder.",
    },
    "carrot": {
        "aliases": ["carrots"],
        "friends": [
            ("onion",         "onion scent masks carrot fly"),
            ("leek",          "mutual — confuses onion fly AND carrot fly"),
            ("rosemary",      "deters carrot fly"),
            ("sage",          "deters carrot fly"),
            ("tomato",        "tomato shades carrot in heat"),
            ("lettuce",       "different root depths"),
            ("pea",           "adds nitrogen, different root depth"),
            ("radish",        "harvested early, loosens soil"),
        ],
        "foes": [
            ("dill",          "mature dill stunts carrots"),
            ("parsnip",       "share pests (carrot fly, celery fly)"),
            ("celery",        "share pests"),
        ],
        "notes": "Loose, stone-free soil essential. Thin early.",
    },
    "onion": {
        "aliases": ["onions", "shallot", "shallots"],
        "friends": [
            ("carrot",        "mutual fly confusion"),
            ("beet",          "onion deters pests; different root depth"),
            ("lettuce",       "no competition"),
            ("strawberry",    "deters strawberry pests"),
            ("tomato",        "deters tomato pests"),
            ("chamomile",     "improves onion flavor"),
            ("brassicas",     "deters cabbage loopers, cabbage worms"),
        ],
        "foes": [
            ("bean",          "onion inhibits bean growth"),
            ("pea",           "onion inhibits pea growth"),
            ("asparagus",     "compete"),
            ("sage",          "stunts onion growth"),
        ],
        "notes": "Long season — plan bed carefully.",
    },
    "garlic": {
        "aliases": ["garlic bulb"],
        "friends": [
            ("tomato",        "fungal suppression"),
            ("rose",          "deters aphids, adds fungal protection"),
            ("brassicas",     "deters cabbage worms, aphids"),
            ("fruit tree",    "deters borers, aphids (underplant)"),
            ("carrot",        "deters carrot fly"),
            ("strawberry",    "pest deterrent"),
        ],
        "foes": [
            ("bean",          "stunts bean growth"),
            ("pea",           "stunts pea growth"),
            ("asparagus",     "compete"),
        ],
        "notes": "Plant in fall for larger summer heads.",
    },
    "lettuce": {
        "aliases": ["lettuces", "leaf lettuce", "romaine", "butterhead"],
        "friends": [
            ("carrot",        "no root competition"),
            ("radish",        "loosens soil, harvested early"),
            ("strawberry",    "mutual bed-mates"),
            ("cucumber",      "different root zones"),
            ("onion",         "deters pests"),
            ("chive",         "deters aphids"),
            ("mint",          "deters slugs (plant in pots)"),
        ],
        "foes": [
            ("parsley",       "parsley bolts and shades out lettuce"),
            ("celery",        "compete"),
            ("cabbage",       "bitter the lettuce"),
        ],
        "notes": "Bolts in heat — interplant with taller crops for shade.",
    },
    "cabbage": {
        "aliases": ["cabbages", "brassica"],
        "friends": [
            ("dill",          "attracts wasps that parasitize cabbage worms"),
            ("mint",          "deters cabbage moth (plant in pots)"),
            ("rosemary",      "deters cabbage moth, cabbage fly"),
            ("sage",          "deters cabbage moth"),
            ("thyme",         "deters cabbage worm"),
            ("nasturtium",    "trap crop for aphids, cabbage moth"),
            ("onion",         "deters cabbage loopers"),
            ("celery",        "mutual — celery benefits from cabbage"),
            ("beet",          "different nutrient needs"),
        ],
        "foes": [
            ("tomato",        "stunt each other"),
            ("strawberry",    "strawberry attracts pests that damage cabbage"),
            ("pole bean",     "compete"),
            ("dill",          "mature dill — fine when young, remove before flowering"),
        ],
        "notes": "Heavy feeder. Cover with row fabric until pest pressure drops.",
    },
    "broccoli": {
        "aliases": ["broccolis"],
        "friends": [
            ("dill",          "attracts beneficial wasps"),
            ("nasturtium",    "trap crop"),
            ("onion",         "deters cabbage moth"),
            ("rosemary",      "deters pests"),
            ("celery",        "mutual — improves broccoli"),
            ("chamomile",     "improves flavor, attracts predators"),
        ],
        "foes": [
            ("tomato",        "stunt each other"),
            ("strawberry",    "attract cabbage pests"),
            ("pole bean",     "compete"),
        ],
        "notes": "Cool-season. Harvest before bolting.",
    },
    "kale": {
        "aliases": ["kales"],
        "friends": [
            ("beet",          "different nutrients"),
            ("celery",        "mutual"),
            ("dill",          "beneficial insects"),
            ("nasturtium",    "trap crop"),
            ("onion",         "deters cabbage pests"),
            ("thyme",         "deters cabbage worm"),
        ],
        "foes": [
            ("tomato",        "stunt each other"),
            ("pole bean",     "compete"),
        ],
        "notes": "Cold-hardy. Frost improves flavor.",
    },
    "cauliflower": {
        "aliases": ["cauliflowers"],
        "friends": [
            ("celery",        "mutual"),
            ("dill",          "beneficial insects"),
            ("nasturtium",    "trap crop"),
            ("bean",          "nitrogen"),
            ("onion",         "deters cabbage pests"),
        ],
        "foes": [
            ("tomato",        "stunt each other"),
            ("strawberry",    "attract cabbage pests"),
        ],
        "notes": "Blanch heads by tying outer leaves over them.",
    },
    "cucumber": {
        "aliases": ["cucumbers", "cuke"],
        "friends": [
            ("bean",          "nitrogen"),
            ("corn",          "trellis; mutual pest confusion"),
            ("dill",          "attracts predators of cucumber beetle"),
            ("nasturtium",    "deters cucumber beetle"),
            ("radish",        "deters cucumber beetle"),
            ("sunflower",     "trellis, shade"),
            ("marigold",      "deters beetles"),
            ("lettuce",       "no competition"),
        ],
        "foes": [
            ("potato",        "share blight risk"),
            ("sage",          "inhibits cucumber growth"),
            ("mint",          "too vigorous; competes"),
        ],
        "notes": "Trellis vertical to save space and reduce disease.",
    },
    "potato": {
        "aliases": ["potatoes", "spud"],
        "friends": [
            ("bean",          "deters Colorado potato beetle; fixes nitrogen"),
            ("corn",          "different root depths"),
            ("cabbage",       "mutual"),
            ("horseradish",   "planted at corners — deters potato bugs"),
            ("marigold",      "nematode control"),
            ("basil",         "deters pests"),
        ],
        "foes": [
            ("tomato",        "share blight"),
            ("pepper",        "share blight"),
            ("eggplant",      "share blight"),
            ("cucumber",      "share blight"),
            ("pumpkin",       "attract same pests"),
            ("squash",        "compete, attract same pests"),
            ("raspberry",     "share blight"),
        ],
        "notes": "Rotate on 4-year cycle due to disease pressure.",
    },
    "pepper": {
        "aliases": ["peppers", "bell pepper", "hot pepper", "chili"],
        "friends": [
            ("basil",         "repels thrips, aphids"),
            ("onion",         "deters pests"),
            ("carrot",        "no competition"),
            ("marjoram",      "general pest deterrent"),
            ("oregano",       "attracts predators"),
            ("parsley",       "beneficial insects"),
            ("tomato",        "similar care, similar pests — group for rotation"),
        ],
        "foes": [
            ("bean",          "pepper inhibits bean"),
            ("brassicas",     "compete"),
            ("fennel",        "inhibits"),
        ],
        "notes": "Warm season. Support branches under fruit load.",
    },
    "eggplant": {
        "aliases": ["aubergine", "eggplants"],
        "friends": [
            ("bean",          "deters Colorado potato beetle; fixes nitrogen"),
            ("marigold",      "nematode control"),
            ("pepper",        "similar conditions"),
            ("basil",         "repels thrips"),
            ("thyme",         "general pest deterrent"),
        ],
        "foes": [
            ("fennel",        "inhibits"),
            ("potato",        "same pest family"),
        ],
        "notes": "Solanaceae — rotate with non-solanaceous crops.",
    },
    "strawberry": {
        "aliases": ["strawberries"],
        "friends": [
            ("borage",        "improves flavor, repels pests"),
            ("spinach",       "mutual"),
            ("lettuce",       "shades soil"),
            ("onion",         "deters pests"),
            ("thyme",         "deters worms"),
            ("bean",          "nitrogen"),
        ],
        "foes": [
            ("cabbage",       "attracts slugs"),
            ("broccoli",      "attracts slugs"),
            ("tomato",        "share verticillium wilt"),
            ("potato",        "share verticillium wilt"),
        ],
        "notes": "Replace beds every 3–4 years due to disease.",
    },
    "pea": {
        "aliases": ["peas", "snow pea", "snap pea", "sugar pea"],
        "friends": [
            ("carrot",        "mutual, different root depths"),
            ("cucumber",      "mutual nitrogen"),
            ("corn",          "corn as trellis"),
            ("turnip",        "mutual"),
            ("radish",        "loosens soil"),
            ("bean",          "both fix nitrogen"),
            ("lettuce",       "different roots"),
        ],
        "foes": [
            ("onion",         "inhibits pea growth"),
            ("garlic",        "inhibits pea growth"),
            ("chive",         "inhibits"),
        ],
        "notes": "Cool season. Nitrogen fixer.",
    },
    "spinach": {
        "aliases": ["spinaches"],
        "friends": [
            ("strawberry",    "mutual bed-mates"),
            ("pea",           "nitrogen"),
            ("bean",          "nitrogen"),
            ("lettuce",       "same conditions"),
            ("cauliflower",   "mutual"),
        ],
        "foes": [
            ("potato",        "minor competition"),
        ],
        "notes": "Bolts quickly in heat. Succession plant.",
    },
    "beet": {
        "aliases": ["beets", "beetroot"],
        "friends": [
            ("onion",         "different roots"),
            ("brassicas",     "mutual nutrients"),
            ("lettuce",       "no competition"),
            ("garlic",        "pest deterrent"),
            ("bush bean",     "nitrogen — avoid pole beans"),
        ],
        "foes": [
            ("pole bean",     "stunts beets"),
            ("mustard",       "competes"),
        ],
        "notes": "Thin seedlings early. Greens are edible.",
    },
    "radish": {
        "aliases": ["radishes", "daikon"],
        "friends": [
            ("lettuce",       "mutual"),
            ("cucumber",      "deters cucumber beetle"),
            ("pea",           "loosens soil"),
            ("carrot",        "succession in same row"),
            ("squash",        "deters squash bugs"),
            ("spinach",       "mutual"),
            ("nasturtium",    "deters pests"),
        ],
        "foes": [
            ("hyssop",        "inhibits"),
            ("grape",         "mutual inhibition"),
        ],
        "notes": "Fast crop — great for marking slow rows.",
    },
    "basil": {
        "aliases": ["basils"],
        "friends": [
            ("tomato",        "repels thrips, aphids, whitefly"),
            ("pepper",        "pest deterrent"),
            ("asparagus",     "deters asparagus beetle"),
            ("marigold",      "mutual insect attraction"),
        ],
        "foes": [
            ("rue",           "inhibits"),
            ("sage",          "poor mix"),
        ],
        "notes": "Pinch flowers for more leaves. Frost-sensitive.",
    },
    "sunflower": {
        "aliases": ["sunflowers"],
        "friends": [
            ("corn",          "mutual pollinator attraction"),
            ("cucumber",      "trellis, shade"),
            ("squash",        "pollinator attraction"),
            ("melon",         "shade"),
            ("bean",          "trellis"),
        ],
        "foes": [
            ("potato",        "allelopathic — inhibits potato"),
        ],
        "notes": "Allelopathic compounds in hulls — clean up fallen seeds.",
    },
    "marigold": {
        "aliases": ["marigolds", "tagetes"],
        "friends": [
            ("tomato",        "nematode control"),
            ("pepper",        "pest deterrent"),
            ("potato",        "deters Colorado potato beetle"),
            ("squash",        "deters squash bugs"),
            ("bean",          "deters Mexican bean beetle"),
            ("cucumber",      "deters cucumber beetle"),
            ("brassicas",     "deters cabbage worm"),
        ],
        "foes": [
            ("bean",          "French marigold is fine; African marigold can inhibit"),
        ],
        "notes": "French marigolds (T. patula) are the best nematode suppressor.",
    },
    "nasturtium": {
        "aliases": ["nasturtiums"],
        "friends": [
            ("cucumber",      "trap for cucumber beetle, deters aphids"),
            ("squash",        "trap for squash bug"),
            ("tomato",        "trap for aphids"),
            ("brassicas",     "trap for cabbage pests"),
            ("radish",        "mutual"),
            ("fruit tree",    "deters woolly aphids (underplant)"),
        ],
        "foes": [],
        "notes": "Trap crop — expect pest damage on nasturtiums to protect main crop.",
    },
    "mint": {
        "aliases": ["mints", "spearmint", "peppermint"],
        "friends": [
            ("cabbage",       "deters cabbage moth, flea beetle"),
            ("tomato",        "deters aphids, whitefly"),
            ("broccoli",      "deters pests"),
            ("kale",          "deters pests"),
        ],
        "foes": [
            ("parsley",       "mint takes over"),
            ("chamomile",     "compete"),
        ],
        "notes": "ALWAYS plant in pots or sunken containers — extremely invasive.",
    },
}


# ─────────────────────────────────────────────────────────────────────
# Lookup helpers
# ─────────────────────────────────────────────────────────────────────
def _normalize(name: str) -> str:
    s = re.sub(r"[^a-z\s]", "", (name or "").lower()).strip()
    # Trim common plural / filler
    s = re.sub(r"\s+", " ", s)
    return s


# Build an alias index once at import time
_ALIAS_INDEX: Dict[str, str] = {}
for canonical, data in COMPANION_DATA.items():
    _ALIAS_INDEX[canonical] = canonical
    for alias in data.get("aliases", []):
        _ALIAS_INDEX[_normalize(alias)] = canonical


def resolve_crop(name: str) -> Optional[str]:
    """Map a user-supplied crop name to the canonical key, or None."""
    if not name:
        return None
    key = _normalize(name)
    if key in _ALIAS_INDEX:
        return _ALIAS_INDEX[key]
    # Try removing trailing 's' (simple pluralization)
    if key.endswith("s") and key[:-1] in _ALIAS_INDEX:
        return _ALIAS_INDEX[key[:-1]]
    # Substring match as last resort
    for alias_key, canonical in _ALIAS_INDEX.items():
        if alias_key and (alias_key in key or key in alias_key):
            return canonical
    return None


def lookup(crop: str) -> Optional[dict]:
    """Return the full record for a crop (by any alias) or None."""
    canonical = resolve_crop(crop)
    if not canonical:
        return None
    record = COMPANION_DATA[canonical]
    return {
        "crop":        canonical,
        "friends":     record.get("friends", []),
        "foes":        record.get("foes", []),
        "notes":       record.get("notes", ""),
    }


def check_pair(crop_a: str, crop_b: str) -> dict:
    """Return a compatibility assessment for two crops."""
    a = resolve_crop(crop_a)
    b = resolve_crop(crop_b)
    if not a:
        return {"verdict": "unknown", "reason": f"'{crop_a}' not in companion database"}
    if not b:
        return {"verdict": "unknown", "reason": f"'{crop_b}' not in companion database"}
    if a == b:
        return {"verdict": "same", "reason": "Same crop — spacing and rotation rules apply."}

    a_rec = COMPANION_DATA[a]
    b_rec = COMPANION_DATA[b]

    def matches(pair_list, target_canonical):
        for name, reason in pair_list:
            if resolve_crop(name) == target_canonical:
                return reason
        return None

    friend_reason = matches(a_rec.get("friends", []), b) or matches(b_rec.get("friends", []), a)
    foe_reason    = matches(a_rec.get("foes",    []), b) or matches(b_rec.get("foes",    []), a)

    if foe_reason:
        return {"verdict": "avoid", "crop_a": a, "crop_b": b, "reason": foe_reason}
    if friend_reason:
        return {"verdict": "good",  "crop_a": a, "crop_b": b, "reason": friend_reason}
    return {"verdict": "neutral", "crop_a": a, "crop_b": b, "reason": "No documented interaction — likely neutral."}


def format_for_llm(crop: str) -> str:
    """Human-readable companion summary suitable for LLM context."""
    rec = lookup(crop)
    if not rec:
        return f"No companion-planting data available for '{crop}'."
    lines = [f"Companion planting — {rec['crop']}"]
    if rec["friends"]:
        lines.append("\nGood companions (plant nearby):")
        for name, why in rec["friends"]:
            lines.append(f"  • {name} — {why}")
    if rec["foes"]:
        lines.append("\nAvoid planting near:")
        for name, why in rec["foes"]:
            lines.append(f"  • {name} — {why}")
    if rec["notes"]:
        lines.append(f"\nNotes: {rec['notes']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# LangChain tools
# ─────────────────────────────────────────────────────────────────────
@tool
def companion_planting_tool(crop: str) -> str:
    """Look up companion-planting recommendations for a single crop.

    Returns the crop's good companions (with reasons) and crops to avoid
    planting nearby (with reasons). Use when a farmer asks what to plant
    with, alongside, or next to a specific crop.

    Args:
        crop: The crop name (e.g., "tomato", "corn", "three sisters").
              Accepts common aliases and plurals.

    Returns:
        A formatted summary of companions and antagonists.
    """
    return format_for_llm(crop)


@tool
def check_companion_pair_tool(crop_a: str, crop_b: str) -> str:
    """Check whether two specific crops are good or bad companions.

    Use when a farmer asks something like "Can I plant X next to Y?"
    or "Do X and Y grow well together?"

    Args:
        crop_a: First crop name.
        crop_b: Second crop name.

    Returns:
        'good', 'avoid', 'neutral', or 'unknown' with a brief reason.
    """
    result = check_pair(crop_a, crop_b)
    verdict = result["verdict"]
    reason  = result.get("reason", "")
    label = {
        "good":    "GOOD companions",
        "avoid":   "AVOID planting together",
        "neutral": "Neutral — no strong interaction",
        "same":    "Same crop",
        "unknown": "Unknown — not in database",
    }.get(verdict, verdict)
    return f"{label}. {reason}"


companion_tools = [companion_planting_tool, check_companion_pair_tool]


# ─────────────────────────────────────────────────────────────────────
# Public helpers for API routes
# ─────────────────────────────────────────────────────────────────────
def list_known_crops() -> List[str]:
    """All canonical crop names in the database, sorted."""
    return sorted(COMPANION_DATA.keys())


def full_record(crop: str) -> Optional[dict]:
    """Structured record (for REST endpoints / UI)."""
    rec = lookup(crop)
    if not rec:
        return None
    return {
        "crop":    rec["crop"],
        "friends": [{"name": n, "reason": r} for n, r in rec["friends"]],
        "foes":    [{"name": n, "reason": r} for n, r in rec["foes"]],
        "notes":   rec["notes"],
    }
