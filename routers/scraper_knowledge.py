"""
Scraper Knowledge — the learning flywheel shared by Chearvil (Node) and Lavendir (Python).

Three tables:
  ScraperPlatformSignatures — CMS fingerprint rules (how to detect Wix, WordPress, etc.)
  ScraperPlatformPatterns   — learned (platform, field, selector) triples with success/failure counters
  ScraperLearningLog        — audit trail of every successful/failed extraction

Both scrapers:
  1. call /detect to identify the CMS/platform from the HTML
  2. call /lookup to fetch known-good selectors for that platform
  3. after extraction call /record-success or /record-failure so patterns evolve over time
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import re, json, datetime

router = APIRouter(prefix="/api/scraper-knowledge", tags=["scraper-knowledge"])


# ─────────────────────────────────────────────────────────────────────────────
# Schema bootstrap — runs once on import
# ─────────────────────────────────────────────────────────────────────────────

_SCHEMA_READY = False

_SEED_SIGNATURES = [
    # (platform_key, display_name, rule_type, rule_value, confidence_weight, notes)
    ("wix",          "Wix",             "meta_generator",  "Wix.com",                      90, "meta[name=generator]=Wix.com"),
    ("wix",          "Wix",             "script_src",      "static.parastorage.com",       70, "Wix static CDN"),
    ("wix",          "Wix",             "script_src",      "_wix/",                        60, "Wix runtime"),
    ("squarespace",  "Squarespace",     "meta_generator",  "Squarespace",                  90, "meta[name=generator]"),
    ("squarespace",  "Squarespace",     "script_src",      "squarespace.com/universal",    70, "Squarespace assets"),
    ("squarespace",  "Squarespace",     "body_class",      "squarespace-",                 60, "body class prefix"),
    ("wordpress",    "WordPress",       "meta_generator",  "WordPress",                    90, "meta[name=generator]=WordPress"),
    ("wordpress",    "WordPress",       "link_href",       "/wp-content/",                 70, "wp-content path"),
    ("wordpress",    "WordPress",       "link_href",       "/wp-includes/",                70, "wp-includes path"),
    ("shopify",      "Shopify",         "meta_generator",  "Shopify",                      90, "meta[name=generator]"),
    ("shopify",      "Shopify",         "script_src",      "cdn.shopify.com",              80, "Shopify CDN"),
    ("shopify",      "Shopify",         "script_content",  "Shopify.shop",                 60, "shopify global"),
    ("webflow",      "Webflow",         "meta_generator",  "Webflow",                      90, "meta[name=generator]"),
    ("webflow",      "Webflow",         "html_attr",       "data-wf-site",                 80, "html data-wf-site attr"),
    ("duda",         "Duda",            "meta_generator",  "Duda",                         90, "meta[name=generator]"),
    ("duda",         "Duda",            "script_src",      "static.wixstatic.com/duda",    70, "Duda CDN"),
    ("weebly",       "Weebly",          "meta_generator",  "Weebly",                       90, "meta[name=generator]"),
    ("weebly",       "Weebly",          "script_src",      "editmysite.com",               70, "Weebly CDN"),
    ("jimdo",        "Jimdo",           "meta_generator",  "Jimdo",                        90, "meta[name=generator]"),
    ("ghost",        "Ghost",           "meta_generator",  "Ghost",                        90, "meta[name=generator]"),
    ("hubspot",      "HubSpot CMS",     "script_src",      "hsforms.net",                  70, "HubSpot forms"),
    ("hubspot",      "HubSpot CMS",     "script_src",      "hs-scripts.com",               80, "HubSpot tracking"),
    ("godaddy",      "GoDaddy Builder", "script_src",      "img1.wsimg.com",               70, "GoDaddy CDN"),
    ("godaddy",      "GoDaddy Builder", "body_class",      "site-body",                    30, "weak signal, combine with others"),
    ("react_spa",    "React (generic)", "script_src",      "react",                        30, "low-confidence hint"),
    ("react_spa",    "React (generic)", "html_comment",    "React",                        20, "low-confidence"),
    ("next_js",      "Next.js",         "script_src",      "/_next/",                      80, "Next.js build output"),
    ("next_js",      "Next.js",         "meta_generator",  "Next.js",                      90, "meta[name=generator]"),
    ("gatsby",       "Gatsby",          "meta_generator",  "Gatsby",                       90, "meta[name=generator]"),
    ("hugo",         "Hugo",            "meta_generator",  "Hugo",                         90, "meta[name=generator]"),
    ("jekyll",       "Jekyll",          "meta_generator",  "Jekyll",                       90, "meta[name=generator]"),
    ("vue_spa",      "Vue.js",          "html_attr",       "data-v-app",                   70, "vue build"),
    ("shopify",      "Shopify",         "link_href",       "cdn.shopify.com",              70, "stylesheet link"),
]

_SEED_PATTERNS = [
    # Platform-specific known-good selectors. field_name → selector_type ('css' or 'attr') + selector_value.
    # seed_score is the initial success_count so these are preferred over unseen selectors.
    # (platform_key, field_name, selector_type, selector_value, seed_score)
    # ── Wix ──
    ("wix", "hero_headline",     "css", "[data-hook='title']",                     50),
    ("wix", "hero_image",        "css", "wow-image img[src]",                      40),
    ("wix", "nav_links",         "css", "[data-testid='linkElement']",             50),
    ("wix", "cta_button",        "css", "[data-testid='button-content']",          40),
    # ── Squarespace ──
    ("squarespace", "hero_headline",  "css", ".sqs-block-content h1, .hero-title h1",   60),
    ("squarespace", "hero_image",     "css", ".sqs-image-content img, img.thumb-image", 50),
    ("squarespace", "nav_links",      "css", ".header-nav-item a",                      60),
    ("squarespace", "blog_posts_list","css", "article.blog-item, .sqs-layout .BlogList-item", 50),
    # ── WordPress ──
    ("wordpress", "hero_headline",   "css", ".wp-block-cover h1, .hero-section h1, header.entry-header h1", 50),
    ("wordpress", "hero_image",      "css", ".wp-block-cover img, .hero img",              50),
    ("wordpress", "nav_links",       "css", "nav.main-navigation a, .primary-menu a, #primary-menu a", 60),
    ("wordpress", "blog_posts_list", "css", "article.post, .post-list article, main .entry", 60),
    ("wordpress", "content_main",    "css", "article .entry-content, .post-content",       55),
    ("wordpress", "logo",            "css", ".site-logo img, .custom-logo, .logo img",     55),
    # ── Shopify ──
    ("shopify", "hero_headline",    "css", ".hero__title, .banner__heading, .slideshow__heading", 60),
    ("shopify", "hero_image",       "css", ".hero__image img, .slideshow__image img, .banner__media img", 55),
    ("shopify", "nav_links",        "css", ".header__menu a, nav.header__inline-menu a",   60),
    ("shopify", "product_cards",    "css", ".product-card, .card-wrapper, .grid__item .card", 60),
    ("shopify", "cta_button",       "css", ".button, .btn, button[type='submit']",         40),
    # ── Webflow ──
    ("webflow", "hero_headline",    "css", ".hero-heading, .hero h1, [class*='hero'] h1",  55),
    ("webflow", "hero_image",       "css", ".hero-image, .hero img, [class*='hero'] img",  50),
    ("webflow", "nav_links",        "css", ".nav-link, .w-nav-link",                       65),
    # ── Duda ──
    ("duda", "hero_headline",       "css", ".dmBody h1, .dmHeadingContainer h1",           50),
    ("duda", "nav_links",           "css", ".dmNavigationContainer a",                     55),
    # ── GoDaddy ──
    ("godaddy", "hero_headline",    "css", ".hero-title, section[data-section-type='hero'] h1", 50),
    ("godaddy", "nav_links",        "css", "nav.primary-navigation a, .header-nav a",      55),
    # ── Generic fallbacks (used when platform='_generic') ──
    ("_generic", "hero_headline",   "css", "header h1, .hero h1, section:first-of-type h1", 20),
    ("_generic", "hero_image",      "css", "header img, .hero img, section:first-of-type img", 20),
    ("_generic", "nav_links",       "css", "nav a, header a, [role='navigation'] a",       20),
    ("_generic", "logo",            "css", ".logo img, header img:first-of-type, .site-logo img", 20),
    ("_generic", "blog_posts_list", "css", "article, .blog-post, .post",                   20),
    ("_generic", "content_main",    "css", "main, article, #content, .content",            20),
    ("_generic", "cta_button",      "css", "a.button, button, .btn, .cta",                 20),
]


def _ensure_tables(db: Session) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        # ── Signatures table ──
        db.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScraperPlatformSignatures')
            CREATE TABLE ScraperPlatformSignatures (
                SignatureID        INT IDENTITY PRIMARY KEY,
                PlatformKey        NVARCHAR(64)  NOT NULL,
                PlatformName       NVARCHAR(120) NOT NULL,
                RuleType           NVARCHAR(32)  NOT NULL,
                RuleValue          NVARCHAR(400) NOT NULL,
                ConfidenceWeight   INT           NOT NULL DEFAULT 50,
                Notes              NVARCHAR(400) NULL,
                CreatedAt          DATETIME2     DEFAULT GETDATE(),
                Enabled            BIT           NOT NULL DEFAULT 1
            )
        """))
        # ── Patterns table ──
        db.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScraperPlatformPatterns')
            CREATE TABLE ScraperPlatformPatterns (
                PatternID          INT IDENTITY PRIMARY KEY,
                PlatformKey        NVARCHAR(64)  NOT NULL,
                FieldName          NVARCHAR(80)  NOT NULL,
                SelectorType       NVARCHAR(16)  NOT NULL,  -- 'css' | 'attr' | 'regex'
                SelectorValue      NVARCHAR(600) NOT NULL,
                SuccessCount       INT           NOT NULL DEFAULT 0,
                FailureCount       INT           NOT NULL DEFAULT 0,
                LastUsedAt         DATETIME2     NULL,
                LastSuccessAt      DATETIME2     NULL,
                CreatedBy          NVARCHAR(32)  NOT NULL DEFAULT 'system',
                CreatedAt          DATETIME2     DEFAULT GETDATE()
            )
        """))
        db.execute(text("""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                 WHERE name='IX_ScraperPlatformPatterns_PK_Field'
                   AND object_id = OBJECT_ID('ScraperPlatformPatterns'))
            CREATE UNIQUE INDEX IX_ScraperPlatformPatterns_PK_Field
                ON ScraperPlatformPatterns(PlatformKey, FieldName, SelectorValue)
        """))
        # Add Enabled column for pruning if missing (backwards-compatible ALTER)
        db.execute(text("""
            IF NOT EXISTS (
                SELECT 1 FROM sys.columns
                 WHERE Name='Enabled' AND Object_ID = OBJECT_ID('ScraperPlatformPatterns'))
            ALTER TABLE ScraperPlatformPatterns ADD Enabled BIT NOT NULL DEFAULT 1
        """))
        # ── Learning log ──
        db.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScraperLearningLog')
            CREATE TABLE ScraperLearningLog (
                LogID              INT IDENTITY PRIMARY KEY,
                AgentName          NVARCHAR(32)  NOT NULL,  -- 'chearvil' | 'lavendir'
                PlatformKey        NVARCHAR(64)  NULL,
                SourceURL          NVARCHAR(1000) NULL,
                FieldName          NVARCHAR(80)  NULL,
                SelectorUsed       NVARCHAR(600) NULL,
                Outcome            NVARCHAR(16)  NOT NULL,  -- 'success' | 'failure' | 'new_pattern'
                SampleValue        NVARCHAR(1000) NULL,
                CreatedAt          DATETIME2     DEFAULT GETDATE()
            )
        """))
        db.commit()

        # ── Seed signatures if empty ──
        existing = db.execute(text("SELECT COUNT(*) FROM ScraperPlatformSignatures")).scalar() or 0
        if existing == 0:
            for (key, name, rtype, rvalue, weight, notes) in _SEED_SIGNATURES:
                db.execute(text("""
                    INSERT INTO ScraperPlatformSignatures
                        (PlatformKey, PlatformName, RuleType, RuleValue, ConfidenceWeight, Notes)
                    VALUES (:k, :n, :t, :v, :w, :notes)
                """), {"k": key, "n": name, "t": rtype, "v": rvalue, "w": weight, "notes": notes})
            db.commit()

        # ── Seed patterns if empty ──
        existing = db.execute(text("SELECT COUNT(*) FROM ScraperPlatformPatterns")).scalar() or 0
        if existing == 0:
            for (platform, field, stype, svalue, score) in _SEED_PATTERNS:
                db.execute(text("""
                    INSERT INTO ScraperPlatformPatterns
                        (PlatformKey, FieldName, SelectorType, SelectorValue, SuccessCount, CreatedBy)
                    VALUES (:p, :f, :t, :v, :s, 'seed')
                """), {"p": platform, "f": field, "t": stype, "v": svalue, "s": score})
            db.commit()
        _SCHEMA_READY = True
    except Exception as e:
        print(f"[scraper_knowledge] ensure_tables failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Detection — given HTML, return the most likely platform
# ─────────────────────────────────────────────────────────────────────────────

class DetectRequest(BaseModel):
    html: Optional[str] = None          # raw HTML (preferred)
    url:  Optional[str] = None          # unused today, reserved for future signals
    head_snippet: Optional[str] = None  # first ~10KB of <head> (Chearvil passes this)


def _apply_signatures(html: str, sigs: List[Dict[str, Any]]) -> Dict[str, int]:
    """Walk every active signature against the HTML. Return {platform_key: total_score}."""
    scores: Dict[str, int] = {}
    if not html:
        return scores
    lower_html = html.lower()
    # Extract common features once
    meta_gen_match = re.search(r'<meta[^>]+name\s*=\s*["\']generator["\'][^>]+content\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    meta_gen = (meta_gen_match.group(1) if meta_gen_match else "").lower()
    body_tag_match = re.search(r'<body\b[^>]*>', html, re.IGNORECASE)
    body_tag = body_tag_match.group(0).lower() if body_tag_match else ""
    html_tag_match = re.search(r'<html\b[^>]*>', html, re.IGNORECASE)
    html_tag = html_tag_match.group(0).lower() if html_tag_match else ""

    for s in sigs:
        rtype = s["RuleType"]
        rvalue = (s["RuleValue"] or "").lower()
        if not rvalue:
            continue
        hit = False
        if rtype == "meta_generator":
            hit = rvalue in meta_gen
        elif rtype == "script_src":
            hit = bool(re.search(
                r'<script[^>]+src\s*=\s*["\'][^"\']*' + re.escape(rvalue) + r'[^"\']*["\']',
                lower_html
            ))
        elif rtype == "script_content":
            hit = rvalue in lower_html and "<script" in lower_html
        elif rtype == "link_href":
            hit = bool(re.search(
                r'<link[^>]+href\s*=\s*["\'][^"\']*' + re.escape(rvalue) + r'[^"\']*["\']',
                lower_html
            ))
        elif rtype == "body_class":
            hit = rvalue in body_tag
        elif rtype == "html_attr":
            hit = rvalue in html_tag or rvalue in body_tag
        elif rtype == "html_comment":
            hit = bool(re.search(r'<!--[^>]*' + re.escape(rvalue) + r'[^>]*-->', lower_html))
        if hit:
            scores[s["PlatformKey"]] = scores.get(s["PlatformKey"], 0) + int(s["ConfidenceWeight"])
    return scores


# ── Redis-backed platform detection cache (1-hr TTL, domain-keyed) ──
_DETECT_CACHE: dict = {}
_DETECT_CACHE_TTL_SEC = 60 * 60
_DETECT_CACHE_KEY_PREFIX = "scraperkb:detect:"


def _detect_redis():
    try:
        from saige.redis_client import get_redis_client
        return get_redis_client(decode_responses=True)
    except Exception:
        return None


def _hostname_of(url: str) -> str:
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        # Strip leading 'www.' to unify subdomain variants
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _cache_get_detect(host: str) -> Optional[Dict[str, Any]]:
    if not host:
        return None
    import json as _j, time as _t
    client = _detect_redis()
    if client is not None:
        try:
            raw = client.get(_DETECT_CACHE_KEY_PREFIX + host)
            if raw:
                return _j.loads(raw)
        except Exception:
            pass
    entry = _DETECT_CACHE.get(host)
    if entry and entry.get("_exp", 0) > _t.time():
        return entry.get("payload")
    return None


def _cache_set_detect(host: str, payload: Dict[str, Any]) -> None:
    if not host or not payload:
        return
    import json as _j, time as _t
    client = _detect_redis()
    if client is not None:
        try:
            client.setex(_DETECT_CACHE_KEY_PREFIX + host, _DETECT_CACHE_TTL_SEC, _j.dumps(payload, default=str))
            return
        except Exception:
            pass
    _DETECT_CACHE[host] = {"_exp": _t.time() + _DETECT_CACHE_TTL_SEC, "payload": payload}


@router.post("/detect")
def detect_platform(body: DetectRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)

    # ── Cache hit on URL hostname skips signature matching + DB read ──
    host = _hostname_of(body.url or "")
    if host:
        cached = _cache_get_detect(host)
        if cached:
            return {**cached, "cache": "hit"}

    html = (body.html or body.head_snippet or "") or ""
    sigs = db.execute(text("""
        SELECT PlatformKey, PlatformName, RuleType, RuleValue, ConfidenceWeight
          FROM ScraperPlatformSignatures
         WHERE Enabled = 1
    """)).mappings().all()
    scores = _apply_signatures(html, [dict(s) for s in sigs])

    if not scores:
        result = {"platform_key": "_generic", "platform_name": "Generic (unknown CMS)", "confidence": 0, "scores": {}}
        if host:
            _cache_set_detect(host, result)
        return result

    # Highest score wins; require at least 50 confidence for a named platform
    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]
    name_row = db.execute(text("""
        SELECT TOP 1 PlatformName FROM ScraperPlatformSignatures
         WHERE PlatformKey = :k AND Enabled = 1
    """), {"k": best_key}).fetchone()
    name = name_row[0] if name_row else best_key

    if best_score < 50:
        result = {"platform_key": "_generic", "platform_name": "Generic (low confidence)", "confidence": best_score, "scores": scores}
    else:
        result = {"platform_key": best_key, "platform_name": name, "confidence": best_score, "scores": scores}
    if host:
        _cache_set_detect(host, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Lookup — return known-good selectors for a (platform, field)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/lookup")
def lookup_patterns(
    platform_key: str,
    field_name: Optional[str] = None,
    limit: int = 8,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    params: Dict[str, Any] = {"pk": platform_key, "gk": "_generic"}
    where = "WHERE PlatformKey IN (:pk, :gk) AND ISNULL(Enabled, 1) = 1"
    if field_name:
        where += " AND FieldName = :f"
        params["f"] = field_name
    rows = db.execute(text(f"""
        SELECT PatternID, PlatformKey, FieldName, SelectorType, SelectorValue,
               SuccessCount, FailureCount, LastUsedAt
          FROM ScraperPlatformPatterns
          {where}
         ORDER BY (SuccessCount - FailureCount) DESC, SuccessCount DESC
    """), params).mappings().all()
    out = [dict(r) for r in rows][: max(1, min(int(limit or 8), 40))]
    for r in out:
        # Prefer platform-specific over generic when scores tie
        r["is_platform_specific"] = (r["PlatformKey"] == platform_key)
    return {"platform_key": platform_key, "field_name": field_name, "patterns": out}


# ─────────────────────────────────────────────────────────────────────────────
# Bulk lookup — one round-trip per scrape instead of one per field
# ─────────────────────────────────────────────────────────────────────────────

class BulkLookupRequest(BaseModel):
    platform_key: str
    field_names:  List[str]
    limit_per_field: int = 8


@router.post("/lookup-bulk")
def lookup_patterns_bulk(body: BulkLookupRequest, db: Session = Depends(get_db)):
    """Fetch learned selectors for many fields in one SQL roundtrip."""
    _ensure_tables(db)
    fields = [f for f in (body.field_names or []) if f]
    if not fields:
        return {"platform_key": body.platform_key, "patterns_by_field": {}}

    per_field_limit = max(1, min(int(body.limit_per_field or 8), 40))
    field_placeholders = ",".join(f":f{i}" for i in range(len(fields)))
    params: Dict[str, Any] = {"pk": body.platform_key, "gk": "_generic"}
    for i, name in enumerate(fields):
        params[f"f{i}"] = name

    rows = db.execute(text(f"""
        SELECT PatternID, PlatformKey, FieldName, SelectorType, SelectorValue,
               SuccessCount, FailureCount, LastUsedAt
          FROM ScraperPlatformPatterns
         WHERE PlatformKey IN (:pk, :gk)
           AND ISNULL(Enabled, 1) = 1
           AND FieldName IN ({field_placeholders})
         ORDER BY FieldName,
                  CASE WHEN PlatformKey = :pk THEN 0 ELSE 1 END,
                  (SuccessCount - FailureCount) DESC,
                  SuccessCount DESC
    """), params).mappings().all()

    grouped: Dict[str, List[Dict[str, Any]]] = {f: [] for f in fields}
    for r in rows:
        bucket = grouped.get(r["FieldName"])
        if bucket is None or len(bucket) >= per_field_limit:
            continue
        d = dict(r)
        d["is_platform_specific"] = (d["PlatformKey"] == body.platform_key)
        bucket.append(d)
    return {"platform_key": body.platform_key, "patterns_by_field": grouped}


# ─────────────────────────────────────────────────────────────────────────────
# Record outcomes — the flywheel write-back
# ─────────────────────────────────────────────────────────────────────────────

class OutcomeRequest(BaseModel):
    agent_name:     str                      # 'chearvil' | 'lavendir'
    platform_key:   str
    field_name:     str
    selector_type:  str = "css"
    selector_value: str
    source_url:     Optional[str] = None
    sample_value:   Optional[str] = None


def _upsert_pattern(db: Session, platform_key: str, field_name: str,
                    selector_type: str, selector_value: str,
                    created_by: str) -> int:
    """Find-or-create the pattern row. Returns PatternID."""
    row = db.execute(text("""
        SELECT TOP 1 PatternID FROM ScraperPlatformPatterns
         WHERE PlatformKey = :p AND FieldName = :f AND SelectorValue = :v
    """), {"p": platform_key, "f": field_name, "v": selector_value[:600]}).fetchone()
    if row:
        return int(row[0])
    r = db.execute(text("""
        INSERT INTO ScraperPlatformPatterns
            (PlatformKey, FieldName, SelectorType, SelectorValue, CreatedBy)
        OUTPUT INSERTED.PatternID
        VALUES (:p, :f, :t, :v, :cb)
    """), {
        "p": platform_key, "f": field_name,
        "t": (selector_type or "css")[:16],
        "v": selector_value[:600],
        "cb": (created_by or "system")[:32],
    }).fetchone()
    return int(r[0])


@router.post("/record-success")
def record_success(body: OutcomeRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    pattern_id = _upsert_pattern(
        db, body.platform_key, body.field_name,
        body.selector_type, body.selector_value, body.agent_name
    )
    # Increment success + last-used timestamps
    db.execute(text("""
        UPDATE ScraperPlatformPatterns
           SET SuccessCount  = SuccessCount + 1,
               LastUsedAt    = GETDATE(),
               LastSuccessAt = GETDATE()
         WHERE PatternID = :id
    """), {"id": pattern_id})
    # Audit log
    db.execute(text("""
        INSERT INTO ScraperLearningLog
            (AgentName, PlatformKey, SourceURL, FieldName, SelectorUsed, Outcome, SampleValue)
        VALUES (:a, :p, :u, :f, :s, 'success', :v)
    """), {
        "a": body.agent_name[:32], "p": body.platform_key[:64],
        "u": (body.source_url or "")[:1000], "f": body.field_name[:80],
        "s": body.selector_value[:600],
        "v": (body.sample_value or "")[:1000],
    })
    db.commit()
    return {"ok": True, "pattern_id": pattern_id}


@router.post("/record-failure")
def record_failure(body: OutcomeRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    pattern_id = _upsert_pattern(
        db, body.platform_key, body.field_name,
        body.selector_type, body.selector_value, body.agent_name
    )
    db.execute(text("""
        UPDATE ScraperPlatformPatterns
           SET FailureCount = FailureCount + 1,
               LastUsedAt   = GETDATE()
         WHERE PatternID = :id
    """), {"id": pattern_id})
    db.execute(text("""
        INSERT INTO ScraperLearningLog
            (AgentName, PlatformKey, SourceURL, FieldName, SelectorUsed, Outcome)
        VALUES (:a, :p, :u, :f, :s, 'failure')
    """), {
        "a": body.agent_name[:32], "p": body.platform_key[:64],
        "u": (body.source_url or "")[:1000], "f": body.field_name[:80],
        "s": body.selector_value[:600],
    })
    db.commit()
    return {"ok": True, "pattern_id": pattern_id}


@router.post("/record-new-pattern")
def record_new_pattern(body: OutcomeRequest, db: Session = Depends(get_db)):
    """Record a freshly discovered selector. Same as record-success but logged as 'new_pattern'."""
    _ensure_tables(db)
    pattern_id = _upsert_pattern(
        db, body.platform_key, body.field_name,
        body.selector_type, body.selector_value, body.agent_name
    )
    db.execute(text("""
        UPDATE ScraperPlatformPatterns
           SET SuccessCount  = SuccessCount + 1,
               LastUsedAt    = GETDATE(),
               LastSuccessAt = GETDATE()
         WHERE PatternID = :id
    """), {"id": pattern_id})
    db.execute(text("""
        INSERT INTO ScraperLearningLog
            (AgentName, PlatformKey, SourceURL, FieldName, SelectorUsed, Outcome, SampleValue)
        VALUES (:a, :p, :u, :f, :s, 'new_pattern', :v)
    """), {
        "a": body.agent_name[:32], "p": body.platform_key[:64],
        "u": (body.source_url or "")[:1000], "f": body.field_name[:80],
        "s": body.selector_value[:600],
        "v": (body.sample_value or "")[:1000],
    })
    db.commit()
    return {"ok": True, "pattern_id": pattern_id}


# ─────────────────────────────────────────────────────────────────────────────
# Admin — read-only views
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats")
def knowledge_stats(db: Session = Depends(get_db)):
    _ensure_tables(db)
    platforms = db.execute(text("""
        SELECT p.PlatformKey,
               MAX(s.PlatformName) AS PlatformName,
               COUNT(*)            AS PatternCount,
               SUM(p.SuccessCount) AS TotalSuccesses,
               SUM(p.FailureCount) AS TotalFailures
          FROM ScraperPlatformPatterns p
          LEFT JOIN ScraperPlatformSignatures s ON s.PlatformKey = p.PlatformKey
         GROUP BY p.PlatformKey
         ORDER BY TotalSuccesses DESC
    """)).mappings().all()
    recent = db.execute(text("""
        SELECT TOP 50 AgentName, PlatformKey, FieldName, Outcome, SelectorUsed, SourceURL, CreatedAt
          FROM ScraperLearningLog
         ORDER BY LogID DESC
    """)).mappings().all()
    return {
        "platforms": [dict(p) for p in platforms],
        "recent_log": [dict(r) for r in recent],
    }


@router.get("/platforms")
def list_platforms(db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT PlatformKey, MAX(PlatformName) AS PlatformName,
               COUNT(*) AS SignatureCount,
               SUM(ConfidenceWeight) AS TotalWeight
          FROM ScraperPlatformSignatures
         WHERE Enabled = 1
         GROUP BY PlatformKey
         ORDER BY PlatformName
    """)).mappings().all()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Signature authoring — let the user add/remove fingerprint rules
# ─────────────────────────────────────────────────────────────────────────────

SIGNATURE_RULE_TYPES = ("meta_generator", "script_src", "link_href", "body_class", "html_attr", "html_comment")


def _invalidate_detect_cache() -> None:
    """Clear both local + Redis detect caches so new signatures take effect immediately."""
    _DETECT_CACHE.clear()
    client = _detect_redis()
    if client is None:
        return
    try:
        for k in client.scan_iter(match=f"{_DETECT_CACHE_KEY_PREFIX}*"):
            try:
                client.delete(k)
            except Exception:
                pass
    except Exception:
        pass


@router.get("/signatures")
def list_signatures(platform_key: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure_tables(db)
    if platform_key:
        rows = db.execute(text("""
            SELECT SignatureID, PlatformKey, PlatformName, RuleType, RuleValue,
                   ConfidenceWeight, Notes, Enabled, CreatedAt
              FROM ScraperPlatformSignatures
             WHERE PlatformKey = :pk
             ORDER BY Enabled DESC, ConfidenceWeight DESC
        """), {"pk": platform_key}).mappings().all()
    else:
        rows = db.execute(text("""
            SELECT SignatureID, PlatformKey, PlatformName, RuleType, RuleValue,
                   ConfidenceWeight, Notes, Enabled, CreatedAt
              FROM ScraperPlatformSignatures
             ORDER BY PlatformName, RuleType, ConfidenceWeight DESC
        """)).mappings().all()
    return [dict(r) for r in rows]


class SignatureCreate(BaseModel):
    platform_key:       str
    platform_name:      str
    rule_type:          str
    rule_value:         str
    confidence_weight:  int = 50
    notes:              Optional[str] = None


@router.post("/signatures")
def create_signature(body: SignatureCreate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    pk = (body.platform_key or "").strip().lower()
    pname = (body.platform_name or "").strip()
    rtype = (body.rule_type or "").strip().lower()
    rvalue = (body.rule_value or "").strip()
    if not pk or not pname or not rvalue:
        raise HTTPException(status_code=400, detail="platform_key, platform_name, rule_value are required")
    if rtype not in SIGNATURE_RULE_TYPES:
        raise HTTPException(status_code=400, detail=f"rule_type must be one of {SIGNATURE_RULE_TYPES}")
    weight = max(1, min(100, int(body.confidence_weight or 50)))

    row = db.execute(text("""
        INSERT INTO ScraperPlatformSignatures
            (PlatformKey, PlatformName, RuleType, RuleValue, ConfidenceWeight, Notes)
        OUTPUT INSERTED.SignatureID, INSERTED.CreatedAt
        VALUES (:pk, :pn, :rt, :rv, :w, :notes)
    """), {"pk": pk, "pn": pname, "rt": rtype, "rv": rvalue,
           "w": weight, "notes": body.notes}).mappings().first()
    db.commit()
    _invalidate_detect_cache()
    return {
        "ok": True,
        "signature_id": row["SignatureID"] if row else None,
        "created_at":   row["CreatedAt"]   if row else None,
    }


@router.delete("/signatures/{signature_id}")
def delete_signature(signature_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ScraperPlatformSignatures WHERE SignatureID = :id"),
               {"id": signature_id})
    db.commit()
    _invalidate_detect_cache()
    return {"ok": True, "signature_id": signature_id}


@router.post("/signatures/{signature_id}/toggle")
def toggle_signature(signature_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ScraperPlatformSignatures
           SET Enabled = CASE WHEN ISNULL(Enabled, 1) = 1 THEN 0 ELSE 1 END
         WHERE SignatureID = :id
    """), {"id": signature_id})
    db.commit()
    _invalidate_detect_cache()
    return {"ok": True, "signature_id": signature_id}


# ─────────────────────────────────────────────────────────────────────────────
# Prune — disable low-performing patterns so probe loops skip them
# ─────────────────────────────────────────────────────────────────────────────

class PruneRequest(BaseModel):
    min_attempts:       int   = 10    # need at least this many total tries
    min_failure_ratio:  float = 0.8   # failures/(successes+failures)
    dry_run:            bool  = True
    include_seed:       bool  = False # keep seeded rows safe by default


@router.post("/prune")
def prune_patterns(body: PruneRequest, db: Session = Depends(get_db)):
    """Disable patterns whose failure ratio is high enough that they waste probe time.
    Seeded rows (CreatedBy='seed') are protected unless include_seed=True."""
    _ensure_tables(db)
    min_attempts = max(1, int(body.min_attempts or 10))
    min_ratio = max(0.0, min(1.0, float(body.min_failure_ratio or 0.8)))

    where_seed = "" if body.include_seed else " AND CreatedBy <> 'seed'"
    select_sql = f"""
        SELECT PatternID, PlatformKey, FieldName, SelectorValue,
               SuccessCount, FailureCount, CreatedBy,
               CAST(FailureCount AS FLOAT) /
                   NULLIF(SuccessCount + FailureCount, 0) AS FailureRatio
          FROM ScraperPlatformPatterns
         WHERE ISNULL(Enabled, 1) = 1
           AND (SuccessCount + FailureCount) >= :mn
           AND CAST(FailureCount AS FLOAT) /
                   NULLIF(SuccessCount + FailureCount, 0) >= :mr
           {where_seed}
         ORDER BY FailureRatio DESC, FailureCount DESC
    """
    rows = db.execute(text(select_sql), {"mn": min_attempts, "mr": min_ratio}).mappings().all()
    candidates = [dict(r) for r in rows]

    disabled = 0
    if not body.dry_run and candidates:
        ids = [int(r["PatternID"]) for r in candidates]
        # Update in chunks to avoid parameter-limit issues
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            placeholders = ",".join(f":id{j}" for j in range(len(chunk)))
            params = {f"id{j}": v for j, v in enumerate(chunk)}
            db.execute(text(f"UPDATE ScraperPlatformPatterns SET Enabled = 0 WHERE PatternID IN ({placeholders})"), params)
            disabled += len(chunk)
        db.commit()

    return {
        "dry_run": body.dry_run,
        "min_attempts": min_attempts,
        "min_failure_ratio": min_ratio,
        "matched": len(candidates),
        "disabled": disabled,
        "candidates": candidates,
    }


@router.post("/unprune/{pattern_id}")
def unprune_pattern(pattern_id: int, db: Session = Depends(get_db)):
    """Re-enable a single pattern (manual override for prune mistakes)."""
    _ensure_tables(db)
    db.execute(text("UPDATE ScraperPlatformPatterns SET Enabled = 1 WHERE PatternID = :id"),
               {"id": pattern_id})
    db.commit()
    return {"ok": True, "pattern_id": pattern_id}
