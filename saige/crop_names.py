"""
Traditional / local / regional crop names.

Maps a canonical English crop name to the other names farmers around the
world actually use — scientific (Latin), Spanish, French, Hindi, Swahili,
Yoruba, Kiswahili, Chinese, Indigenous-American, Portuguese, etc.

Also supports REVERSE lookup: "kinana" → "corn", "brinjal" → "eggplant".

Used by Saige so a farmer typing "courgette" or "melongene" gets the same
advice as one typing "zucchini" or "eggplant".
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from langchain_core.tools import tool


# Each entry: canonical name → { scientific, names: {region/language: [names]} }
CROP_NAMES: Dict[str, dict] = {
    "tomato": {
        "scientific": "Solanum lycopersicum",
        "names": {
            "Spanish":        ["tomate", "jitomate"],
            "French":         ["tomate"],
            "Italian":        ["pomodoro"],
            "Portuguese":     ["tomate"],
            "Hindi":          ["tamatar", "टमाटर"],
            "Swahili":        ["nyanya"],
            "Yoruba":         ["tomati"],
            "Chinese":        ["番茄 (fānqié)", "西红柿 (xīhóngshì)"],
            "Japanese":       ["トマト (tomato)"],
            "Nahuatl":        ["tomatl"],
            "Tagalog":        ["kamatis"],
        },
    },
    "corn": {
        "scientific": "Zea mays",
        "names": {
            "English (UK)":   ["maize"],
            "Spanish":        ["maíz", "elote (young)", "choclo (S. America)"],
            "French":         ["maïs"],
            "Portuguese":     ["milho"],
            "Swahili":        ["mahindi"],
            "Yoruba":         ["agbado"],
            "Zulu":           ["ummbila"],
            "Shona":          ["chibage"],
            "Hindi":          ["makka", "मक्का"],
            "Navajo":         ["naadą́ą́'"],
            "Lakota":         ["wagmíza"],
            "Cherokee":       ["selu"],
            "Hopi":           ["qa'ö"],
            "Nahuatl":        ["cintli", "centli"],
            "Quechua":        ["sara"],
        },
    },
    "bean": {
        "scientific": "Phaseolus vulgaris",
        "names": {
            "Spanish":        ["frijol", "judía", "habichuela", "poroto"],
            "French":         ["haricot"],
            "Portuguese":     ["feijão"],
            "Swahili":        ["maharagwe"],
            "Yoruba":         ["ewa"],
            "Hindi":          ["rajma (kidney)", "राजमा"],
            "Cherokee":       ["tuya"],
            "Navajo":         ["naa'ołí"],
            "Quechua":        ["purutu"],
            "Nahuatl":        ["etl"],
        },
    },
    "squash": {
        "scientific": "Cucurbita spp.",
        "names": {
            "English (UK)":   ["marrow", "courgette (young)"],
            "Spanish":        ["calabaza", "zapallo", "auyama"],
            "French":         ["courge", "courgette (young)"],
            "Italian":        ["zucca", "zucchina (young)"],
            "Portuguese":     ["abóbora"],
            "Swahili":        ["boga"],
            "Cherokee":       ["iya"],
            "Navajo":         ["naayízí"],
            "Nahuatl":        ["ayotli"],
            "Tamil":          ["poosanikai"],
        },
    },
    "eggplant": {
        "scientific": "Solanum melongena",
        "names": {
            "English (UK)":   ["aubergine"],
            "Caribbean":      ["melongene"],
            "Indian English": ["brinjal"],
            "Spanish":        ["berenjena"],
            "French":         ["aubergine"],
            "Italian":        ["melanzana"],
            "Hindi":          ["baingan", "बैंगन"],
            "Bengali":        ["begun"],
            "Tamil":          ["kathirikai"],
            "Swahili":        ["biringanya"],
            "Arabic":         ["باذنجان (bādhinjān)"],
        },
    },
    "zucchini": {
        "scientific": "Cucurbita pepo",
        "names": {
            "English (UK)":   ["courgette"],
            "Spanish":        ["calabacín"],
            "French":         ["courgette"],
            "Italian":        ["zucchina", "zucchine"],
            "German":         ["Zucchini"],
        },
    },
    "potato": {
        "scientific": "Solanum tuberosum",
        "names": {
            "Spanish":        ["papa", "patata (Spain)"],
            "French":         ["pomme de terre"],
            "Italian":        ["patata"],
            "Portuguese":     ["batata"],
            "Swahili":        ["kiazi"],
            "Hindi":          ["aloo", "आलू"],
            "Quechua":        ["papa"],
            "Aymara":         ["ch'uqi"],
            "Irish":          ["práta"],
            "German":         ["Kartoffel"],
        },
    },
    "sweet potato": {
        "scientific": "Ipomoea batatas",
        "names": {
            "Spanish":        ["batata", "boniato", "camote"],
            "French":         ["patate douce"],
            "Portuguese":     ["batata-doce"],
            "Swahili":        ["viazi vitamu"],
            "Yoruba":         ["ànámọ́"],
            "Hindi":          ["shakarkand", "शकरकंद"],
            "Nahuatl":        ["camohtli"],
            "Tagalog":        ["kamote"],
        },
    },
    "cassava": {
        "scientific": "Manihot esculenta",
        "names": {
            "English":        ["yuca", "manioc", "tapioca root"],
            "Spanish":        ["yuca", "mandioca"],
            "Portuguese":     ["mandioca", "aipim", "macaxeira"],
            "French":         ["manioc"],
            "Swahili":        ["muhogo", "mihogo"],
            "Yoruba":         ["gbaguda", "ege"],
            "Igbo":           ["akpụ", "abacha"],
            "Hindi":          ["sabudana (pearl form)"],
        },
    },
    "rice": {
        "scientific": "Oryza sativa",
        "names": {
            "Spanish":        ["arroz"],
            "French":         ["riz"],
            "Italian":        ["riso"],
            "Portuguese":     ["arroz"],
            "Swahili":        ["mchele (raw)", "wali (cooked)"],
            "Yoruba":         ["irẹsi"],
            "Hindi":          ["chawal", "चावल"],
            "Chinese":        ["米 (mǐ)", "稻 (dào)"],
            "Japanese":       ["米 (kome)", "ご飯 (gohan)"],
            "Tagalog":        ["bigas (raw)", "kanin (cooked)"],
        },
    },
    "wheat": {
        "scientific": "Triticum spp.",
        "names": {
            "Spanish":        ["trigo"],
            "French":         ["blé", "froment"],
            "Italian":        ["grano", "frumento"],
            "Portuguese":     ["trigo"],
            "Swahili":        ["ngano"],
            "Hindi":          ["gehun", "गेहूं"],
            "Russian":        ["пшеница (pshenitsa)"],
            "Chinese":        ["小麦 (xiǎomài)"],
        },
    },
    "sorghum": {
        "scientific": "Sorghum bicolor",
        "names": {
            "English":        ["milo", "great millet", "guinea corn"],
            "Spanish":        ["sorgo"],
            "Swahili":        ["mtama"],
            "Yoruba":         ["oka-baba"],
            "Hindi":          ["jowar", "ज्वार"],
            "Ethiopian":      ["mashela"],
        },
    },
    "millet": {
        "scientific": "Panicum miliaceum / Pennisetum glaucum / Eleusine coracana",
        "names": {
            "Swahili":        ["ulezi (finger)", "mawele (pearl)"],
            "Hindi":          ["bajra (pearl)", "ragi (finger)"],
            "Yoruba":         ["okababa"],
            "French":         ["mil"],
            "Spanish":        ["mijo"],
        },
    },
    "okra": {
        "scientific": "Abelmoschus esculentus",
        "names": {
            "English":        ["ladies' fingers", "gumbo"],
            "Hindi":          ["bhindi", "भिंडी"],
            "Spanish":        ["quimbombó"],
            "Portuguese":     ["quiabo"],
            "Swahili":        ["bamia"],
            "Yoruba":         ["ila"],
            "Arabic":         ["بامية (bāmiya)"],
        },
    },
    "cilantro": {
        "scientific": "Coriandrum sativum",
        "names": {
            "English (UK)":   ["coriander leaf"],
            "Spanish":        ["cilantro", "culantro (Caribbean thick-leaf is different)"],
            "Hindi":          ["dhania", "धनिया"],
            "Chinese":        ["香菜 (xiāngcài)", "芫荽 (yánsuī)"],
            "Thai":           ["phak chi"],
        },
    },
    "scallion": {
        "scientific": "Allium fistulosum",
        "names": {
            "English (UK)":   ["spring onion", "green onion"],
            "Spanish":        ["cebolleta", "cebollín"],
            "Chinese":        ["葱 (cōng)"],
            "Japanese":       ["ねぎ (negi)"],
            "Caribbean":      ["sybies"],
        },
    },
    "cabbage": {
        "scientific": "Brassica oleracea var. capitata",
        "names": {
            "Spanish":        ["repollo", "col"],
            "French":         ["chou"],
            "Portuguese":     ["repolho"],
            "Swahili":        ["kabichi"],
            "Hindi":          ["patta gobhi", "पत्ता गोभी"],
            "Chinese":        ["卷心菜 (juǎnxīncài)", "白菜 (báicài — napa)"],
        },
    },
    "chili pepper": {
        "scientific": "Capsicum annuum / C. frutescens / C. chinense",
        "names": {
            "English":        ["hot pepper", "chile"],
            "Spanish":        ["chile", "ají", "guindilla"],
            "Hindi":          ["mirch", "मिर्च"],
            "Thai":           ["phrik"],
            "Swahili":        ["pilipili"],
            "Yoruba":         ["ata"],
            "Nahuatl":        ["chīlli"],
        },
    },
    "peanut": {
        "scientific": "Arachis hypogaea",
        "names": {
            "English":        ["groundnut", "goober"],
            "Spanish":        ["maní", "cacahuate", "cacahuete"],
            "Portuguese":     ["amendoim"],
            "Swahili":        ["karanga"],
            "Hindi":          ["moongphali", "मूंगफली"],
            "Nahuatl":        ["tlālcacahuatl"],
        },
    },
    "cowpea": {
        "scientific": "Vigna unguiculata",
        "names": {
            "English":        ["black-eyed pea", "crowder pea", "southern pea"],
            "Yoruba":         ["ewa"],
            "Hausa":          ["wake"],
            "Swahili":        ["kunde"],
            "Portuguese":     ["feijão-frade"],
            "Spanish":        ["caupí", "frijol de costa"],
        },
    },
    "pigeon pea": {
        "scientific": "Cajanus cajan",
        "names": {
            "English":        ["gungo pea (Caribbean)", "red gram", "congo pea"],
            "Hindi":          ["arhar", "toor dal", "तूर दाल"],
            "Swahili":        ["mbaazi"],
            "Spanish":        ["gandul", "guandú"],
        },
    },
    "taro": {
        "scientific": "Colocasia esculenta",
        "names": {
            "English":        ["dasheen", "eddo", "cocoyam"],
            "Hawaiian":       ["kalo"],
            "Fijian":         ["dalo"],
            "Japanese":       ["里芋 (satoimo)"],
            "Swahili":        ["magimbi"],
            "Spanish":        ["malanga", "ocumo (Venezuela)"],
        },
    },
    "yam": {
        "scientific": "Dioscorea spp.",
        "names": {
            "Spanish":        ["ñame"],
            "Yoruba":         ["isu"],
            "Igbo":           ["ji"],
            "Swahili":        ["kiazi kikuu"],
            "Hindi":          ["ratalu"],
        },
    },
    "oat": {
        "scientific": "Avena sativa",
        "names": {
            "English":        ["oats"],
            "Spanish":        ["avena"],
            "French":         ["avoine"],
            "German":         ["Hafer"],
            "Russian":        ["овёс (ovyos)"],
            "Hindi":          ["jai"],
        },
    },
    "barley": {
        "scientific": "Hordeum vulgare",
        "names": {
            "Spanish":        ["cebada"],
            "French":         ["orge"],
            "German":         ["Gerste"],
            "Hindi":          ["jau", "जौ"],
            "Arabic":         ["شعير (shaʿīr)"],
        },
    },
    "sugarcane": {
        "scientific": "Saccharum officinarum",
        "names": {
            "Spanish":        ["caña de azúcar"],
            "Portuguese":     ["cana-de-açúcar"],
            "Hindi":          ["ganna", "गन्ना"],
            "Swahili":        ["muwa"],
            "Chinese":        ["甘蔗 (gānzhè)"],
        },
    },
    "onion": {
        "scientific": "Allium cepa",
        "names": {
            "Spanish":        ["cebolla"],
            "French":         ["oignon"],
            "Hindi":          ["pyaz", "प्याज"],
            "Swahili":        ["kitunguu"],
        },
    },
    "garlic": {
        "scientific": "Allium sativum",
        "names": {
            "Spanish":        ["ajo"],
            "French":         ["ail"],
            "Hindi":          ["lehsun", "लहसुन"],
            "Swahili":        ["kitunguu saumu"],
        },
    },
    "carrot": {
        "scientific": "Daucus carota",
        "names": {
            "Spanish":        ["zanahoria"],
            "French":         ["carotte"],
            "Hindi":          ["gajar", "गाजर"],
            "Swahili":        ["karoti"],
        },
    },
    "cucumber": {
        "scientific": "Cucumis sativus",
        "names": {
            "Spanish":        ["pepino"],
            "French":         ["concombre"],
            "Hindi":          ["kheera", "खीरा"],
            "Swahili":        ["tango"],
        },
    },
    "lettuce": {
        "scientific": "Lactuca sativa",
        "names": {
            "Spanish":        ["lechuga"],
            "French":         ["laitue"],
            "Hindi":          ["salad patta"],
            "Japanese":       ["レタス (retasu)"],
        },
    },
}


# ──────────────────────────────────────────────────────────────────
# Indexing
# ──────────────────────────────────────────────────────────────────
_NORMALIZE_RE = re.compile(r"[^a-z0-9 ]+")


def _normalize(name: str) -> str:
    return _NORMALIZE_RE.sub("", name.lower().strip())


def _build_reverse_index() -> Dict[str, str]:
    idx: Dict[str, str] = {}
    for canonical, entry in CROP_NAMES.items():
        idx[_normalize(canonical)] = canonical
        for _region, variants in entry.get("names", {}).items():
            for v in variants:
                # strip parenthetical annotations: "choclo (S. America)" → "choclo"
                base = re.sub(r"\s*\(.*?\)", "", v).strip()
                idx[_normalize(base)] = canonical
    return idx


_REVERSE = _build_reverse_index()


def resolve(name: str) -> Optional[str]:
    """Given any name (canonical, alias, or local-language variant), return canonical."""
    if not name:
        return None
    return _REVERSE.get(_normalize(name))


def lookup(name: str) -> Optional[dict]:
    canonical = resolve(name)
    if not canonical:
        return None
    entry = dict(CROP_NAMES[canonical])
    entry["canonical"] = canonical
    return entry


def list_all() -> List[str]:
    return sorted(CROP_NAMES.keys())


def format_for_llm(name: str) -> str:
    rec = lookup(name)
    if not rec:
        return (
            f"I don't have traditional-name data for '{name}'. "
            f"Known crops: {', '.join(list_all()[:20])}…"
        )
    lines = [f"'{name}' → canonical: {rec['canonical']} ({rec.get('scientific', '')})"]
    for region, variants in rec.get("names", {}).items():
        lines.append(f"• {region}: {', '.join(variants)}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# LangChain tool
# ──────────────────────────────────────────────────────────────────
@tool
def crop_name_tool(name: str) -> str:
    """Translate a crop name across languages and regions. Accepts a canonical English
    name (e.g., 'tomato'), a local name ('brinjal', 'melongene', 'courgette'), or a
    scientific name ('Solanum lycopersicum') and returns all known regional/traditional
    variants. Use when a farmer refers to a crop by an unfamiliar name or asks what a
    crop is called somewhere else."""
    return format_for_llm(name)


crop_name_tools = [crop_name_tool]
