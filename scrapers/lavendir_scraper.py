"""
Lavendir's Python scraper — mirrors Chearvil's pipeline.

Layers:
  1. httpx fetch → BeautifulSoup parse
  2. Platform detection via /api/scraper-knowledge/detect
  3. Known-pattern lookup for this platform
  4. Design token extraction (colors, fonts, og:image, nav/body/accent roles)
  5. Layout-pattern detection (hero/card-grid/testimonials/gallery/etc.)
  6. Optional Playwright layer: computed styles + spatial content + screenshot
  7. Write-back to the knowledge service for every selector that produced a value

The returned dict has the same shape as Chearvil's scrape + build payloads so Lavendir
can reuse it for advice, for import-into-page, or for design-preview generation.
"""
from __future__ import annotations
import os, re, json, time, asyncio
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urljoin, urlparse

import httpx

try:
    from bs4 import BeautifulSoup  # type: ignore
    BS4_AVAILABLE = True
except Exception:
    BS4_AVAILABLE = False

try:
    from playwright.async_api import async_playwright  # type: ignore
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

BOT_SIGNALS = [
    "cloudflare", "just a moment", "ddos-guard",
    "access denied", "security check", "perimeterx",
]

# Backend base for the knowledge service. When Lavendir's scraper runs in-process
# it can also import the router functions directly — but going through HTTP keeps
# the same contract that Chearvil (Node) uses, so one code path exercises both.
KNOWLEDGE_BASE = os.getenv("OFN_BACKEND_URL", "http://localhost:8000").rstrip("/")
AGENT = "lavendir"


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _resolve(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if href.startswith("data:") or href.startswith("javascript:"):
        return None
    try:
        return urljoin(base, href)
    except Exception:
        return None


def _srcset_widest(srcset: str) -> Optional[str]:
    """Return the URL of the widest candidate in a srcset attribute string.

    Handles both width descriptors ("800w") and pixel-density descriptors ("2x").
    Returns None if the srcset string cannot be parsed.
    """
    best_url: Optional[str] = None
    best_w = -1
    for candidate in srcset.split(","):
        parts = candidate.strip().split()
        if not parts:
            continue
        url = parts[0]
        w = 0
        if len(parts) >= 2:
            desc = parts[1].lower()
            if desc.endswith("w"):
                try:
                    w = int(desc[:-1])
                except ValueError:
                    pass
            elif desc.endswith("x"):
                try:
                    w = int(float(desc[:-1]) * 1000)  # treat 2x as 2000 "virtual px"
                except ValueError:
                    pass
        if w > best_w:
            best_w = w
            best_url = url
    return best_url or None


def _hex_to_rgb(hex_s: str) -> Tuple[int, int, int]:
    h = hex_s.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _brightness(rgb: Tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (r * 299 + g * 587 + b * 114) / 1000


def _saturation(rgb: Tuple[int, int, int]) -> float:
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def _norm_hex(raw: str) -> Optional[str]:
    s = raw.strip().lower().lstrip("#")
    if re.fullmatch(r"[0-9a-f]{3}", s):
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-f]{6}", s):
        return None
    return "#" + s


def _is_near_white(rgb: Tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > 238 and g > 238 and b > 238


def _is_near_black(rgb: Tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r < 15 and g < 15 and b < 15


def _colors_from_string(s: str) -> List[str]:
    out = []
    for m in re.finditer(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", s or ""):
        hx = _norm_hex(m.group(1))
        if hx:
            out.append(hx)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge-service client (best-effort, never raises)
# ─────────────────────────────────────────────────────────────────────────────

async def _knowledge_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{KNOWLEDGE_BASE}{path}", json=payload)
            if r.status_code < 400:
                return r.json() or {}
    except Exception as e:
        print(f"[lavendir_scraper] knowledge POST {path} failed: {e}")
    return {}


async def _knowledge_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{KNOWLEDGE_BASE}{path}", params=params)
            if r.status_code < 400:
                return r.json() or {}
    except Exception as e:
        print(f"[lavendir_scraper] knowledge GET {path} failed: {e}")
    return {}


async def detect_platform(html: str, url: Optional[str] = None) -> Dict[str, Any]:
    """Call knowledge service /detect. Returns {platform_key, platform_name, confidence, scores}.
    Passes URL so the server can cache results by domain."""
    # Pass only the head + first 20KB so we stay small on the wire
    head_cut = html[:30000]
    payload: Dict[str, Any] = {"html": head_cut}
    if url:
        payload["url"] = url
    return await _knowledge_post("/api/scraper-knowledge/detect", payload) or {
        "platform_key": "_generic", "platform_name": "Generic", "confidence": 0, "scores": {}
    }


async def lookup_patterns(platform_key: str, field_name: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"platform_key": platform_key}
    if field_name:
        params["field_name"] = field_name
    data = await _knowledge_get("/api/scraper-knowledge/lookup", params)
    return data.get("patterns", []) or []


async def lookup_patterns_bulk(platform_key: str, field_names: List[str],
                               limit_per_field: int = 8) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch patterns for all fields in one HTTP round-trip.
    Falls back to per-field loop if the bulk endpoint isn't deployed yet."""
    data = await _knowledge_post("/api/scraper-knowledge/lookup-bulk", {
        "platform_key": platform_key,
        "field_names": list(field_names or []),
        "limit_per_field": int(limit_per_field),
    })
    grouped = (data or {}).get("patterns_by_field")
    if isinstance(grouped, dict) and grouped:
        return {f: grouped.get(f, []) or [] for f in field_names}
    # Fallback — iterate if bulk call didn't return usable data
    out: Dict[str, List[Dict[str, Any]]] = {}
    for f in field_names:
        out[f] = await lookup_patterns(platform_key, f)
    return out


async def record_success(platform_key: str, field_name: str, selector: str,
                         source_url: str, sample: str = "") -> None:
    await _knowledge_post("/api/scraper-knowledge/record-success", {
        "agent_name": AGENT, "platform_key": platform_key,
        "field_name": field_name, "selector_type": "css",
        "selector_value": selector, "source_url": source_url,
        "sample_value": (sample or "")[:800],
    })


async def record_failure(platform_key: str, field_name: str, selector: str,
                         source_url: str) -> None:
    await _knowledge_post("/api/scraper-knowledge/record-failure", {
        "agent_name": AGENT, "platform_key": platform_key,
        "field_name": field_name, "selector_type": "css",
        "selector_value": selector, "source_url": source_url,
    })


async def record_new_pattern(platform_key: str, field_name: str, selector: str,
                             source_url: str, sample: str = "") -> None:
    """Register a freshly discovered selector so future scrapes prefer it."""
    await _knowledge_post("/api/scraper-knowledge/record-new-pattern", {
        "agent_name": AGENT, "platform_key": platform_key,
        "field_name": field_name, "selector_type": "css",
        "selector_value": selector, "source_url": source_url,
        "sample_value": (sample or "")[:800],
    })


# Background tasks for knowledge writes — fire-and-forget so probe loop stays fast.
# Keep hard refs to prevent GC cancellation.
_BG_TASKS: set = set()

def _fire(coro) -> None:
    """Schedule a coroutine without awaiting it; hold a ref until it finishes."""
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # No running loop — drop it rather than blocking
        return
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


# ─────────────────────────────────────────────────────────────────────────────
# Design token extraction (BeautifulSoup layer — Chearvil's Cheerio port)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_design_tokens(soup: "BeautifulSoup") -> Dict[str, Any]:
    color_freq:    Dict[str, int] = {}
    nav_colors:    Dict[str, int] = {}
    bg_colors:     Dict[str, int] = {}
    accent_colors: Dict[str, int] = {}
    fonts:         set[str] = set()

    # 1. meta theme-color
    theme = soup.find("meta", attrs={"name": "theme-color"})
    if theme and theme.get("content"):
        hx = _norm_hex(theme["content"])
        if hx:
            color_freq[hx] = color_freq.get(hx, 0) + 30

    # 2. og:image
    og = soup.find("meta", attrs={"property": "og:image"})
    og_image = og["content"] if (og and og.get("content")) else None

    # 3. Inline <style> blocks — aggregate CSS text
    css_parts = [t.get_text() for t in soup.find_all("style") if t.get_text()]
    css_text = "\n".join(css_parts)

    # 3b. Google Fonts URL — <link> tag first, then @import fallback.
    google_fonts_url: Optional[str] = None
    for _link_el in soup.find_all("link"):
        _rel = _link_el.get("rel") or []
        if isinstance(_rel, str):
            _rel = [_rel]
        if "stylesheet" not in _rel:
            continue
        _href = (_link_el.get("href") or "").strip()
        if "fonts.googleapis.com" in _href:
            google_fonts_url = _href
            break
    if not google_fonts_url:
        _gf_m = re.search(
            r'@import\s+url\(["\']?(https://fonts\.googleapis\.com/[^"\')\s]+)["\']?\)',
            css_text, re.IGNORECASE,
        )
        if _gf_m:
            google_fonts_url = _gf_m.group(1)

    # 3c. Resolve CSS custom properties (--variable: value) before hex scanning.
    # Modern WordPress themes (Astra, Kadence, Hello Elementor, Divi, OceanWP,
    # GeneratePress) store the entire brand palette in :root as CSS variables:
    #   :root { --e-global-color-primary: #6EC1E4; --primary-color: #7b68ee; }
    #   nav { background-color: var(--primary-color); }
    # Without resolution the hex scan finds nothing in these rules and the
    # palette falls back to noise. We do a single substitution pass over the
    # already-inlined css_text so subsequent code needs no changes.
    _root_block_rx  = re.compile(r"(?::root|html)\s*\{([^}]*)\}", re.IGNORECASE)
    _var_decl_rx    = re.compile(r"--([\w-]+)\s*:\s*([^;]+)")
    _css_var_map: Dict[str, str] = {}
    for _rm in _root_block_rx.finditer(css_text):
        for _vm in _var_decl_rx.finditer(_rm.group(1)):
            _vname = _vm.group(1).strip()
            _vval  = _vm.group(2).strip()
            # Only keep values that look like colors
            if re.search(r"#[0-9a-fA-F]{3,8}\b|rgb[a]?\s*\(|hsl[a]?\s*\(", _vval) \
                    or re.fullmatch(r"[a-zA-Z]+", _vval):
                _css_var_map[_vname] = _vval

    if _css_var_map:
        def _resolve_css_var(s: str, _d: int = 5) -> str:
            if _d <= 0 or "var(" not in s:
                return s
            def _var_sub(m) -> str:
                n  = m.group(1).strip()
                fb = (m.group(2) or "").strip()
                return _resolve_css_var(_css_var_map.get(n) or fb or m.group(0), _d - 1)
            return re.sub(r"var\(\s*--([\w-]+)\s*(?:,\s*([^)]*?))?\)", _var_sub, s)
        css_text = _resolve_css_var(css_text)

    # Hex colors from CSS (general frequency signal)
    for m in re.finditer(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css_text):
        hx = _norm_hex(m.group(1))
        if not hx:
            continue
        rgb = _hex_to_rgb(hx)
        if _is_near_white(rgb) or _is_near_black(rgb):
            continue
        color_freq[hx] = color_freq.get(hx, 0) + 1

    # Font families. Track frequency separately so we can pick a brand font
    # (most-used non-system family) for the imported site.
    font_freq: Dict[str, int] = {}
    for m in re.finditer(r"font-family\s*:\s*([^;{}]+)", css_text, re.IGNORECASE):
        # Position-weighted: the FIRST family in the stack is the intended one,
        # later entries are fallbacks. Score them descending.
        families = [r.strip().strip("'\"") for r in m.group(1).split(",")]
        for i, raw in enumerate(families):
            f = " ".join(raw.split()[:3])
            if f and not re.fullmatch(
                r"(inherit|initial|unset|sans-serif|serif|monospace|cursive|fantasy|system-ui|-apple-system|BlinkMacSystemFont)",
                f, re.IGNORECASE
            ):
                fonts.add(f)
                font_freq[f] = font_freq.get(f, 0) + max(1, 5 - i)

    def record(hex_s: Optional[str], bucket: Dict[str, int], weight: int) -> None:
        if not hex_s:
            return
        rgb = _hex_to_rgb(hex_s)
        if _is_near_white(rgb) or _is_near_black(rgb):
            return
        bucket[hex_s] = bucket.get(hex_s, 0) + weight
        color_freq[hex_s] = color_freq.get(hex_s, 0) + weight

    nav_selectors  = ["nav", "header", "#header", "#nav", ".header", ".nav",
                      "#menu", ".menu", "#navbar", ".navbar",
                      ".site-header", ".top-nav", "[role='navigation']"]
    body_selectors = ["body", "#wrapper", "#content", "#main", "main",
                      ".main", "#page", ".page", "#container", ".container", ".site-body"]
    cta_selectors  = ["a.button", "button", ".btn", ".cta",
                      "input[type='submit']", "input[type='button']", ".button"]

    def scan_role(selectors: List[str], bucket: Dict[str, int], weight: int) -> None:
        for sel in selectors:
            try:
                for el in soup.select(sel):
                    combined = " ".join([
                        el.get("style", ""), el.get("bgcolor", ""), el.get("color", "")
                    ])
                    for hx in _colors_from_string(combined):
                        record(hx, bucket, weight)
            except Exception:
                # selector syntax from [role=...] etc. can trip strict parsers; skip
                pass

    scan_role(nav_selectors,  nav_colors,   25)
    scan_role(body_selectors, bg_colors,    20)
    scan_role(cta_selectors,  accent_colors, 15)

    # CSS rule-level background-color by role
    patterns = [
        (re.compile(r"(?:nav|header|\.header|\.nav|#header|#nav|\.navbar|\.site-header|\.top-nav|\.menu)[^{]*\{([^}]*)\}", re.IGNORECASE),
         nav_colors, 20),
        (re.compile(r"(?:body|\.main|#content|#wrapper|\.site-body)[^{]*\{([^}]*)\}", re.IGNORECASE),
         bg_colors, 15),
        (re.compile(r"(?:\.btn|button|\.button|\.cta|a\.btn|input\[type=.submit.\])[^{]*\{([^}]*)\}", re.IGNORECASE),
         accent_colors, 15),
    ]
    for rx, bucket, w in patterns:
        for m in rx.finditer(css_text):
            body = m.group(1)
            bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6})", body, re.IGNORECASE)
            if bg:
                record(_norm_hex(bg.group(1)), bucket, w)

    # Sweep bgcolor attribute on any element (old HTML sites)
    for el in soup.select("[bgcolor]"):
        val = el.get("bgcolor", "")
        for hx in _colors_from_string(val):
            tag = (el.name or "").lower()
            if tag in ("nav", "header"):
                record(hx, nav_colors, 20)
            elif tag == "body":
                record(hx, bg_colors, 20)
            else:
                record(hx, color_freq, 3)

    # Pick best per role
    def top(m: Dict[str, int]) -> List[str]:
        return [k for k, _ in sorted(m.items(), key=lambda kv: kv[1], reverse=True)]

    # Body text color from CSS: `body { color: ... }` or `p { color: ... }`
    text_color: Optional[str] = None
    for rx_tc in (
        re.compile(r"body\s*\{[^}]*\bcolor\s*:\s*(#[0-9a-fA-F]{3,6})", re.IGNORECASE),
        re.compile(r"p\s*\{[^}]*\bcolor\s*:\s*(#[0-9a-fA-F]{3,6})", re.IGNORECASE),
        re.compile(r"\.entry-content\s*\{[^}]*\bcolor\s*:\s*(#[0-9a-fA-F]{3,6})", re.IGNORECASE),
    ):
        m_tc = rx_tc.search(css_text)
        if m_tc:
            cand = _norm_hex(m_tc.group(1))
            if cand:
                rgb_tc = _hex_to_rgb(cand)
                if _brightness(rgb_tc) < 160:
                    text_color = cand
                    break

    top_colors = top(color_freq)[:10]

    nav_candidates = top(nav_colors)
    nav_bg = next((h for h in nav_candidates if _brightness(_hex_to_rgb(h)) < 160), None) \
           or (nav_candidates[0] if nav_candidates else None)

    bg_candidates = top(bg_colors)
    page_bg = next(
        (h for h in bg_candidates
         if 80 < _brightness(_hex_to_rgb(h)) < 235),
        None
    ) or (bg_candidates[0] if bg_candidates else None)

    accent_candidates = top(accent_colors)
    accent = next(
        (h for h in accent_candidates
         if _saturation(_hex_to_rgb(h)) > 0.25 and _brightness(_hex_to_rgb(h)) > 60),
        None
    ) or (accent_candidates[0] if accent_candidates else None)

    nav_text = None
    if nav_bg:
        nav_text = "#ffffff" if _brightness(_hex_to_rgb(nav_bg)) < 128 else "#111827"

    # Secondary color: second chromatic color in top_colors distinct from primary.
    # "Distinct" = hue difference > 25 degrees in HSL space.
    def _hue(hx: str) -> float:
        r, g, b = [x / 255.0 for x in _hex_to_rgb(hx)]
        mx, mn = max(r, g, b), min(r, g, b)
        if mx == mn:
            return 0.0
        d = mx - mn
        if mx == r:
            h = (g - b) / d % 6
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        return h * 60.0

    primary_hue = _hue(nav_bg) if nav_bg else None
    secondary: Optional[str] = None
    for c in top_colors:
        if c == nav_bg or c == accent:
            continue
        sat = _saturation(_hex_to_rgb(c))
        if sat < 0.2:
            continue
        if primary_hue is not None:
            diff = abs(_hue(c) - primary_hue)
            if diff > 180:
                diff = 360 - diff
            if diff < 25:
                continue
        secondary = c
        break

    # Pick the brand body font: most-frequent family that isn't a generic
    # OS/emoji fallback. The position-weighted scoring above already biases
    # toward families used as the primary in a font stack.
    _font_skip = re.compile(
        r"^(apple\s*color\s*emoji|noto\s*color\s*emoji|segoe\s*ui\s*emoji|"
        r"emoji|symbol|symbola|arial|helvetica(\s*neue)?|times(\s*new\s*roman)?|"
        r"georgia|verdana|tahoma|courier(\s*new)?|trebuchet|impact|"
        r"sans|serif|mono|inherit|initial|unset)$",
        re.IGNORECASE,
    )
    body_font: Optional[str] = None
    for f, _w in sorted(font_freq.items(), key=lambda kv: kv[1], reverse=True):
        if not _font_skip.match(f):
            body_font = f
            break

    return {
        "colors":          top_colors,
        "fonts":           sorted(fonts)[:6],
        "bodyFont":        body_font,
        "ogImage":         og_image,
        "googleFontsUrl":  google_fonts_url,
        "navBgColor":      nav_bg,
        "pageBgColor":     page_bg,
        "accentColor":     accent,
        "secondaryColor":  secondary,
        "navTextColor":    nav_text,
        "textColor":       text_color,
        "footerBgColor":   nav_bg,
    }


_SOCIAL_DOMAINS: Dict[str, str] = {
    "facebook.com":    "facebook",
    "fb.com":          "facebook",
    "instagram.com":   "instagram",
    "twitter.com":     "twitter",
    "x.com":           "twitter",
    "youtube.com":     "youtube",
    "youtu.be":        "youtube",
    "linkedin.com":    "linkedin",
    "tiktok.com":      "tiktok",
    "pinterest.com":   "pinterest",
}


def _extract_social_links(soup: "BeautifulSoup") -> Dict[str, str]:
    """Scan all <a href> on the page for social-media profile URLs.
    Returns a dict keyed by platform name (facebook, instagram, twitter,
    youtube, linkedin, tiktok, pinterest) with the first matching href."""
    from urllib.parse import urlparse
    found: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href.startswith("http"):
            continue
        try:
            host = urlparse(href).netloc.lower().lstrip("www.")
        except Exception:
            continue
        for domain, platform in _SOCIAL_DOMAINS.items():
            if host == domain or host.endswith("." + domain):
                if platform not in found:
                    found[platform] = href
                break
    return found


def _extract_testimonials(soup: "BeautifulSoup", max_items: int = 8) -> List[Dict[str, Any]]:
    """Detect testimonial/review sections and return a list of
    {author, content, rating} dicts. Handles:
      - Semantic <blockquote> with adjacent <cite>/<footer>/<figcaption>
      - Card grids whose class names contain 'testimonial'/'review'/'quote'
    """
    results: List[Dict[str, Any]] = []

    def _clean_text(el) -> str:
        if el is None:
            return ""
        return re.sub(r"\s+", " ", el.get_text(" ")).strip()

    def _star_rating(el) -> Optional[int]:
        """Try to read a star rating from a nearby element."""
        parent = el.parent
        for _ in range(4):
            if parent is None:
                break
            text = (parent.get_text() or "")
            stars = re.search(r"(\d+)\s*/\s*5|(\d)\s*(?:stars?|★)", text)
            if stars:
                v = int(stars.group(1) or stars.group(2))
                return max(1, min(5, v))
            parent = parent.parent
        return None

    seen: set[str] = set()

    def _add(author: str, content: str, rating: Optional[int] = None) -> None:
        content = content.strip()
        if not content or len(content) < 20 or len(content) > 1000:
            return
        key = content[:80]
        if key in seen:
            return
        seen.add(key)
        results.append({"author": author.strip()[:100], "content": content, "rating": rating})

    # Pattern 1: <blockquote> with adjacent <cite> or <footer>/<figcaption>
    for bq in soup.find_all("blockquote"):
        text = _clean_text(bq.find("p") or bq)
        author = ""
        for tag in ("cite", "footer", "figcaption"):
            sib = bq.find(tag)
            if not sib:
                sib = bq.find_next_sibling(tag)
            if sib:
                author = _clean_text(sib)
                break
        if text:
            _add(author, text, _star_rating(bq))
        if len(results) >= max_items:
            return results

    # Pattern 2: card containers with testimonial/review/quote in class/id
    _TESTI_RE = re.compile(r"testimonial|review|quote", re.IGNORECASE)
    for el in soup.find_all(True, attrs={"class": True}):
        classes = " ".join(el.get("class", []))
        if not _TESTI_RE.search(classes):
            continue
        # Skip very large containers (likely section wrappers, not single cards)
        if len(el.get_text()) > 1200:
            continue
        p = el.find("p") or el.find("blockquote")
        if not p:
            continue
        content = _clean_text(p)
        author = ""
        for cand_cls in ("author", "name", "cite", "attribution", "client"):
            a_el = el.find(class_=re.compile(cand_cls, re.IGNORECASE))
            if a_el:
                author = _clean_text(a_el)
                break
        if not author:
            cite = el.find("cite")
            if cite:
                author = _clean_text(cite)
        _add(author, content, _star_rating(el))
        if len(results) >= max_items:
            return results

    return results


_FEATURE_CARD_CLASSES = re.compile(
    r"icon.?box|feature|service.?item|service.?card|benefit|advantage|"
    r"elementor-icon-box|et_pb_blurb|wp.block.column",
    re.IGNORECASE,
)
_FEATURE_HEADING_TAGS = {"h2", "h3", "h4", "h5"}


def _extract_features_grid(soup: "BeautifulSoup", max_items: int = 9) -> List[Dict[str, Any]]:
    """Detect homepage 'what we offer / services / features' card grids.
    Returns list of {title, description, icon_url?} — max_items capped.

    Heuristic: find a parent element that contains ≥3 sibling children each
    having a short heading + short paragraph (the classic icon-box pattern).
    Works for Elementor, Divi, GeneratePress, Kadence, etc."""
    results: List[Dict[str, Any]] = []
    seen_titles: set[str] = set()

    def _card_from(el) -> Optional[Dict[str, Any]]:
        heading_el = el.find(_FEATURE_HEADING_TAGS)
        if not heading_el:
            return None
        title = re.sub(r"\s+", " ", heading_el.get_text(" ")).strip()
        if not title or len(title) > 120:
            return None
        p = el.find("p")
        desc = re.sub(r"\s+", " ", p.get_text(" ")).strip() if p else ""
        if len(desc) > 400:
            desc = desc[:400]
        # Icon: img or svg inside the card
        icon_url = ""
        img = el.find("img")
        if img and img.get("src"):
            icon_url = img["src"].strip()
        return {"title": title, "description": desc, "icon_url": icon_url}

    # Pass 1: named card class containers
    for el in soup.find_all(True, attrs={"class": True}):
        classes = " ".join(el.get("class", []))
        if not _FEATURE_CARD_CLASSES.search(classes):
            continue
        card = _card_from(el)
        if card and card["title"] not in seen_titles:
            seen_titles.add(card["title"])
            results.append(card)
        if len(results) >= max_items:
            return results

    if len(results) >= 3:
        return results

    # Pass 2: structural heuristic — find a parent with ≥3 direct children
    # each containing a heading + paragraph (the "three columns" layout).
    for parent in soup.find_all(True):
        children = [c for c in parent.children if getattr(c, "name", None)]
        if len(children) < 3 or len(children) > 8:
            continue
        cards = [_card_from(c) for c in children]
        valid = [c for c in cards if c and c["title"]]
        if len(valid) < 3:
            continue
        for card in valid:
            if card["title"] not in seen_titles:
                seen_titles.add(card["title"])
                results.append(card)
        if len(results) >= 3:
            break

    return results[:max_items]


# ── Days-of-week normalization for hours extraction ───────────────────────────
_DAY_ALIASES: Dict[str, str] = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
    "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
    "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday",
    "sunday": "Sunday",
}
_HOURS_ROW_RE = re.compile(
    r"(?P<day>(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?))"
    r"(?:[^:\-–—]*)?"
    r"(?:[:–—\-]\s*)?"
    r"(?P<open>\d{1,2}(?::\d{2})?\s*(?:am|pm))?"
    r"(?:\s*[\-–—to]+\s*"
    r"(?P<close>\d{1,2}(?::\d{2})?\s*(?:am|pm)))?",
    re.IGNORECASE,
)
_CLOSED_RE = re.compile(r"\bclosed\b", re.IGNORECASE)


_DAY_RANGE_ALIASES: Dict[str, str] = {
    "m": "Monday", "t": "Tuesday", "w": "Wednesday",
    "th": "Thursday", "r": "Thursday", "f": "Friday",
    "sa": "Saturday", "s": "Saturday", "su": "Sunday",
}
_DAY_RANGE_ALIASES.update(_DAY_ALIASES)

# Expands "Mon-Fri", "M-F", "Weekdays", "Weekends" into a list of day names.
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
_WEEKEND  = ["Saturday", "Sunday"]
_ALL_DAYS = _WEEKDAYS + _WEEKEND

def _expand_day_range(start: str, end: str) -> List[str]:
    """Return the ordered list of days from start to end (inclusive)."""
    start_n = _DAY_RANGE_ALIASES.get(start.lower().strip()[:3])
    end_n   = _DAY_RANGE_ALIASES.get(end.lower().strip()[:3])
    if not start_n or not end_n:
        return []
    try:
        s_i = _ALL_DAYS.index(start_n)
        e_i = _ALL_DAYS.index(end_n)
    except ValueError:
        return []
    if s_i <= e_i:
        return _ALL_DAYS[s_i:e_i + 1]
    return _ALL_DAYS[s_i:] + _ALL_DAYS[:e_i + 1]

_DAY_RANGE_LINE_RE = re.compile(
    r"(?:"
    r"(?P<from_day>mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|m|th|f|sa|su|t|w|s)"
    r"\s*[-–—/]\s*"
    r"(?P<to_day>mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|m|th|f|sa|su|t|w|s)"
    r"|(?P<weekdays>weekdays?)"
    r"|(?P<weekends>weekends?)"
    r")"
    r"(?:[:\s,]+)"
    r"(?P<hours_text>[^\n]{3,80})",
    re.IGNORECASE,
)
_HOURS_RANGE_RE = re.compile(
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[-–—to]+\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
    re.IGNORECASE,
)


def _extract_hours(soup: "BeautifulSoup") -> List[Dict[str, Any]]:
    """Detect hours-of-operation patterns and return list of
    {day, open, close, closed, notes} dicts (7-entry canonical week).
    Handles: day-range lines (M-F, Mon-Fri, Weekdays), <table> rows,
    <dl>/<dt>/<dd>, and plain-text lines."""
    rows: Dict[str, Dict[str, Any]] = {}

    def _record(day_raw: str, open_t: str, close_t: str, closed: bool, notes: str = "") -> None:
        day = _DAY_ALIASES.get(day_raw.lower().strip()[:3])
        if not day or day in rows:
            return
        rows[day] = {
            "day": day,
            "open": open_t.strip() if open_t else "",
            "close": close_t.strip() if close_t else "",
            "closed": closed or (not open_t and not close_t),
            "notes": notes.strip()[:80],
        }

    # 0. Day-range scan — "M-F 11am-4pm", "Mon-Fri: 9am-5pm", "Weekdays 8am to 6pm"
    full_text = soup.get_text(" ")
    for rm in _DAY_RANGE_LINE_RE.finditer(full_text):
        hours_text = (rm.group("hours_text") or "").strip()
        is_closed = bool(_CLOSED_RE.search(hours_text))
        hm = _HOURS_RANGE_RE.search(hours_text)
        # Skip matches with no discernible hours — likely a false positive
        if not hm and not is_closed:
            continue
        open_t  = hm.group(1) if hm else ""
        close_t = hm.group(2) if hm else ""
        # Expand to individual day names
        if rm.group("weekdays"):
            day_list = _WEEKDAYS
        elif rm.group("weekends"):
            day_list = _WEEKEND
        else:
            day_list = _expand_day_range(
                rm.group("from_day") or "", rm.group("to_day") or ""
            )
        for day_name in day_list:
            _record(day_name, open_t, close_t, is_closed)

    # 1. Table approach — first col = day, second col = hours
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            day_text = re.sub(r"\s+", " ", cells[0].get_text(" ")).strip()
            hours_text = re.sub(r"\s+", " ", cells[1].get_text(" ")).strip()
            m = _HOURS_ROW_RE.search(day_text)
            if not m:
                continue
            is_closed = bool(_CLOSED_RE.search(hours_text))
            hm = re.search(
                r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[\-–—]\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
                hours_text, re.IGNORECASE
            )
            _record(
                m.group("day"),
                hm.group(1) if hm else "",
                hm.group(2) if hm else "",
                is_closed,
            )

    # 2. Definition list: <dt>Monday</dt><dd>9am–5pm</dd>
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            day_text = dt.get_text(" ").strip()
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            hours_text = dd.get_text(" ").strip()
            m = _HOURS_ROW_RE.search(day_text)
            if not m:
                continue
            is_closed = bool(_CLOSED_RE.search(hours_text))
            hm = re.search(
                r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[\-–—]\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
                hours_text, re.IGNORECASE
            )
            _record(m.group("day"), hm.group(1) if hm else "", hm.group(2) if hm else "", is_closed)

    # 3. Plain text — scan visible text lines for "Monday: 9am - 5pm" patterns
    if len(rows) < 3:
        for el in soup.find_all(["p", "li", "div", "span"]):
            if el.find(["p", "div", "table"]):
                continue
            line = re.sub(r"\s+", " ", el.get_text(" ")).strip()
            if len(line) > 120:
                continue
            m = _HOURS_ROW_RE.search(line)
            if not m or not m.group("day"):
                continue
            is_closed = bool(_CLOSED_RE.search(line))
            _record(
                m.group("day"),
                m.group("open") or "",
                m.group("close") or "",
                is_closed,
            )

    # Return in canonical weekday order
    _ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [rows[d] for d in _ORDER if d in rows]


def _extract_faq(soup: "BeautifulSoup", max_items: int = 15) -> List[Dict[str, str]]:
    """Detect FAQ / accordion patterns and return list of {question, answer}.
    Handles: <details>/<summary>, <dl>/<dt>/<dd>, card grids with
    class=faq/accordion/question, and dense h3+p sibling sequences."""
    results: List[Dict[str, str]] = []
    seen: set[str] = set()

    def _add(q: str, a: str) -> None:
        q = re.sub(r"\s+", " ", q).strip().strip("?").strip() + "?"
        a = re.sub(r"\s+", " ", a).strip()
        if not q or not a or q in seen or len(a) < 10:
            return
        if len(q) > 250 or len(a) > 1200:
            return
        seen.add(q)
        results.append({"question": q, "answer": a[:1000]})

    # 1. <details><summary>Q</summary>A</details>
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        q = summary.get_text(" ").strip()
        summary.decompose()
        a = details.get_text(" ").strip()
        _add(q, a)
        if len(results) >= max_items:
            return results

    # 2. Elements with faq/accordion/question in class
    _FAQ_RE = re.compile(r"faq|accordion|question|toggle", re.IGNORECASE)
    for el in soup.find_all(True, attrs={"class": True}):
        classes = " ".join(el.get("class", []))
        if not _FAQ_RE.search(classes):
            continue
        if len(el.get_text()) > 2000:
            continue
        heading = el.find(["h2", "h3", "h4", "h5", "strong", "b", "summary"])
        if not heading:
            continue
        q = heading.get_text(" ").strip()
        heading_copy = heading.__copy__()
        heading.decompose()
        a = el.get_text(" ").strip()
        _add(q, a)
        if len(results) >= max_items:
            return results

    # 3. <dt>/<dd> definition lists
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            q = dt.get_text(" ").strip()
            dd = dt.find_next_sibling("dd")
            if dd:
                _add(q, dd.get_text(" ").strip())
        if len(results) >= max_items:
            return results

    # 4. Dense h3+p sibling pattern (≥4 pairs in same parent = likely FAQ)
    if len(results) < 3:
        for parent in soup.find_all(True):
            children = [c for c in parent.children if getattr(c, "name", None)]
            pairs = []
            i = 0
            while i < len(children) - 1:
                if children[i].name in ("h3", "h4", "h5") and children[i+1].name == "p":
                    pairs.append((children[i].get_text(" "), children[i+1].get_text(" ")))
                    i += 2
                else:
                    i += 1
            if len(pairs) >= 4:
                for q, a in pairs:
                    _add(q, a)
                break

    return results[:max_items]


def _extract_map_embed(soup: "BeautifulSoup") -> Dict[str, str]:
    """Find an embedded Google Maps iframe and return
    {embed_url, address}. Returns empty dict if not found."""
    for iframe in soup.find_all("iframe"):
        src = (iframe.get("src") or "").strip()
        if not src:
            continue
        if "google.com/maps" in src or "maps.google.com" in src:
            # Normalise to embed format if it isn't already
            if "/maps/embed" not in src and "output=embed" not in src:
                if "?" in src:
                    src += "&output=embed"
                else:
                    src += "?output=embed"
            # Try to find a nearby address text
            address = ""
            parent = iframe.parent
            for _ in range(4):
                if parent is None:
                    break
                txt = re.sub(r"\s+", " ", parent.get_text(" ")).strip()
                addr_m = re.search(
                    r"\d+\s+[A-Za-z][\w\s,\.]{5,60}(?:Street|St|Avenue|Ave|Road|Rd|Blvd|Dr|Lane|Ln|Way|Hwy|Highway|Pl|Place|Court|Ct|Suite|Ste)\.?",
                    txt, re.IGNORECASE
                )
                if addr_m:
                    address = addr_m.group(0).strip()
                    break
                parent = parent.parent
            return {"embed_url": src, "address": address}
    return {}


# ── Team / staff member extraction ───────────────────────────────────────────

_TEAM_CARD_CLASSES = re.compile(
    r"team[-_]?member|staff[-_]?member|person[-_]?card|board[-_]?member"
    r"|our[-_]?team|meet[-_]?the[-_]?team|leadership[-_]?card"
    r"|team[-_]?card|team[-_]?item|bio[-_]?card",
    re.I,
)
_TEAM_SECTION_CLASSES = re.compile(
    r"team[-_]?section|our[-_]?team|staff[-_]?section|meet[-_]?the[-_]?team"
    r"|leadership[-_]?section|board[-_]?section",
    re.I,
)


def _extract_team_members(soup: "BeautifulSoup", base_url: str,
                          max_items: int = 12) -> List[Dict[str, Any]]:
    """Detect person/staff cards and return a list of
    {name, role, bio, photo_url} dicts."""
    members: List[Dict[str, Any]] = []
    seen_names: set = set()

    def _card_from_el(el) -> Optional[Dict[str, Any]]:
        # Photo: first <img> in the card
        img_el = el.find("img")
        photo = ""
        if img_el:
            src = (img_el.get("src") or img_el.get("data-src") or
                   img_el.get("data-lazy-src") or "").strip()
            if src and not src.lower().endswith(".svg"):
                photo = _resolve(base_url, src) or ""

        # Name: look for a heading tag or strong inside the card
        name = ""
        for tag in ("h1", "h2", "h3", "h4", "h5", "strong"):
            el2 = el.find(tag)
            if el2:
                t = _clean(el2.get_text())
                if t and len(t) < 80 and not any(c.isdigit() for c in t[:3]):
                    name = t
                    break

        if not name:
            return None
        if name.lower() in seen_names:
            return None

        # Role/title: next sibling text node, or a <p>/<span> after the heading
        role = ""
        for tag in ("p", "span", "em", "div"):
            el2 = el.find(tag)
            if el2:
                t = _clean(el2.get_text())
                if t and t != name and len(t) < 120:
                    role = t
                    break

        # Bio: first <p> longer than 40 chars that isn't the name/role
        bio = ""
        for p in el.find_all("p"):
            t = _clean(p.get_text())
            if t and t != name and t != role and len(t) >= 40:
                bio = t[:400]
                break

        seen_names.add(name.lower())
        return {"name": name, "role": role, "bio": bio, "photo_url": photo}

    # Strategy 1: known card classes
    for el in soup.find_all(True, class_=True):
        classes = " ".join(el.get("class") or [])
        if _TEAM_CARD_CLASSES.search(classes):
            member = _card_from_el(el)
            if member:
                members.append(member)
                if len(members) >= max_items:
                    return members

    if members:
        return members

    # Strategy 2: find a section/div with a team-ish class, then look for
    # repeated sub-elements that all share the same tag+class structure.
    for section in soup.find_all(True, class_=True):
        classes = " ".join(section.get("class") or [])
        if not _TEAM_SECTION_CLASSES.search(classes):
            continue
        candidates = []
        # Look for direct children (or grandchildren) that contain an <img>
        # and a heading — the classic card pattern.
        for child in section.find_all(["article", "div", "li"], recursive=True):
            if child.find("img") and child.find(["h2", "h3", "h4", "h5", "strong"]):
                member = _card_from_el(child)
                if member:
                    candidates.append(member)
        if len(candidates) >= 2:
            # De-dupe (section scan may hit the same card twice)
            seen_names.update(m["name"].lower() for m in members)
            for c in candidates:
                if c["name"].lower() not in seen_names:
                    members.append(c)
                    seen_names.add(c["name"].lower())
                    if len(members) >= max_items:
                        return members
        if members:
            return members

    return members


# ── Pricing / package tier extraction ────────────────────────────────────────

_PRICING_SECTION_CLASSES = re.compile(
    r"pricing[-_]?table|pricing[-_]?plan|price[-_]?table|price[-_]?plan"
    r"|plan[-_]?card|plan[-_]?tier|pricing[-_]?card|pricing[-_]?tier"
    r"|pricing[-_]?box|pricing[-_]?column|plans-?section|packages[-_]?section"
    r"|pricing[-_]?section|subscription[-_]?plan",
    re.I,
)
_PRICE_RE = re.compile(
    r"[\$\£\€]\s*[\d,]+(?:\.\d{1,2})?|[\d,]+(?:\.\d{1,2})?\s*(?:USD|GBP|EUR)",
    re.I,
)
_PERIOD_RE = re.compile(r"/\s*(mo|month|yr|year|week|wk|day|annual|quarterly)", re.I)


def _extract_pricing_table(soup: "BeautifulSoup",
                           max_tiers: int = 6) -> List[Dict[str, Any]]:
    """Detect column-based pricing tiers and return a list of
    {name, price, period, description, features, highlight} dicts."""
    tiers: List[Dict[str, Any]] = []
    seen_names: set = set()

    def _parse_tier(el) -> Optional[Dict[str, Any]]:
        text = _clean(el.get_text(" "))
        # Must contain a price-like pattern
        price_m = _PRICE_RE.search(text)
        if not price_m:
            return None
        price_str = price_m.group(0).strip()
        period_m = _PERIOD_RE.search(text[price_m.start():price_m.start() + 60])
        period = period_m.group(1).lower() if period_m else ""
        if period in ("mo", "month"):
            period = "month"
        elif period in ("yr", "year", "annual"):
            period = "year"

        # Plan name: first short heading
        name = ""
        for tag in ("h1", "h2", "h3", "h4", "h5"):
            h = el.find(tag)
            if h:
                t = _clean(h.get_text())
                if t and len(t) < 60:
                    name = t
                    break
        if not name:
            return None
        if name.lower() in seen_names:
            return None

        # Features: <li> items inside the card
        features = [_clean(li.get_text()) for li in el.find_all("li")
                    if _clean(li.get_text()) and len(_clean(li.get_text())) < 120][:10]

        # Description: first <p> that's not just the price or name
        description = ""
        for p in el.find_all("p"):
            t = _clean(p.get_text())
            if t and t != name and price_str not in t and len(t) > 20:
                description = t[:280]
                break

        # Highlight: classes like "featured", "popular", "recommended", "highlight"
        classes = " ".join(el.get("class") or [])
        highlight = bool(re.search(r"featured|popular|recommended|highlight|best.?value", classes, re.I))

        seen_names.add(name.lower())
        return {
            "name": name,
            "price": price_str,
            "period": period,
            "description": description,
            "features": features,
            "highlight": highlight,
        }

    # Strategy 1: elements with pricing-specific classes
    for el in soup.find_all(True, class_=True):
        classes = " ".join(el.get("class") or [])
        if _PRICING_SECTION_CLASSES.search(classes):
            tier = _parse_tier(el)
            if tier:
                tiers.append(tier)
                if len(tiers) >= max_tiers:
                    return tiers

    if tiers:
        return tiers

    # Strategy 2: structural — look for a parent that contains ≥2 sibling
    # children, each with a price pattern.
    for parent in soup.find_all(["section", "div"], class_=True):
        children = [c for c in parent.find_all(["div", "article", "li"], recursive=False)
                    if _PRICE_RE.search(_clean(c.get_text(" ")))]
        if len(children) >= 2:
            for child in children[:max_tiers]:
                tier = _parse_tier(child)
                if tier:
                    tiers.append(tier)
            if len(tiers) >= 2:
                return tiers
            tiers.clear()
            seen_names.clear()

    return tiers


# ── Interior-page CTA detection ───────────────────────────────────────────────

_CTA_SECTION_CLASSES = re.compile(
    r"cta[-_]?section|call[-_]?to[-_]?action|cta[-_]?banner|cta[-_]?block"
    r"|cta[-_]?wrap|cta[-_]?box|action[-_]?section|cta[-_]?strip"
    r"|cta[-_]?area|highlight[-_]?cta|promo[-_]?banner|promo[-_]?section"
    r"|offer[-_]?section|banner[-_]?cta|hero[-_]?cta",
    re.I,
)


def _extract_page_cta(soup: "BeautifulSoup", base_url: str) -> Dict[str, Any]:
    """Find a prominent CTA band on an interior page.
    Returns {headline, subtext, button_text, button_link, bg_color} or {}."""

    def _parse_cta_el(el) -> Optional[Dict[str, Any]]:
        # Must have at least one <a> that looks like a button
        buttons = [
            a for a in el.find_all("a")
            if any(kw in " ".join(a.get("class") or []).lower()
                   for kw in ("btn", "button", "cta", "action"))
            or (a.get("href") and _clean(a.get_text()) and len(_clean(a.get_text())) < 60)
        ]
        if not buttons:
            return None

        # Headline: first heading
        headline = ""
        for tag in ("h1", "h2", "h3", "h4"):
            h = el.find(tag)
            if h:
                t = _clean(h.get_text())
                if t and len(t) < 200:
                    headline = t
                    break
        if not headline:
            return None

        # Subtext: first <p> different from headline
        subtext = ""
        for p in el.find_all("p"):
            t = _clean(p.get_text())
            if t and t != headline and len(t) > 10:
                subtext = t[:280]
                break

        btn = buttons[0]
        button_text = _clean(btn.get_text()) or "Learn More"
        button_link = _resolve(base_url, btn.get("href") or "") or "#"

        # Background color from inline style
        bg_color = ""
        style = el.get("style") or ""
        bg_m = re.search(r"background(?:-color)?\s*:\s*([^;]+)", style, re.I)
        if bg_m:
            bg_color = bg_m.group(1).strip()

        return {
            "headline": headline,
            "subtext": subtext,
            "button_text": button_text,
            "button_link": button_link,
            "bg_color": bg_color,
        }

    # Strategy 1: CTA class names
    for el in soup.find_all(True, class_=True):
        classes = " ".join(el.get("class") or [])
        if _CTA_SECTION_CLASSES.search(classes):
            result = _parse_cta_el(el)
            if result:
                return result

    # Strategy 2: any section/div that is a visually distinct band with a
    # short headline + button (heuristic: contains an <a class="btn*">)
    for el in soup.find_all(["section", "div"], class_=True):
        classes = " ".join(el.get("class") or []).lower()
        # Skip obviously non-CTA wrappers
        if any(x in classes for x in ("menu", "nav", "footer", "header", "sidebar",
                                       "widget", "comment", "breadcrumb", "modal")):
            continue
        result = _parse_cta_el(el)
        if result and result.get("headline"):
            return result

    return {}


# Common selectors a theme might use to style its footer band. Order matters —
# more specific class/ID hits beat generic <footer> when both exist.
_FOOTER_CSS_SELECTORS = [
    "site-footer", "page-footer", "footer-widget", "footer-wrap", "footer-wrapper",
    "footer-container", "main-footer", "footer-top", "footer-main", "footer-area",
    "footer", "Footer",
]


def _extract_footer_bg(soup: "BeautifulSoup", base_url: str) -> Dict[str, str]:
    """Pull the source <footer>'s background-color and background-image.

    Strategy:
      1. Inline style on the actual <footer> (or its first child).
      2. CSS rules in <style> blocks whose selector matches ANY class/ID
         that appears inside the footer subtree. This handles page builders
         like Elementor where the bg-image rule is keyed off opaque IDs
         (e.g. `.elementor-element-36398a3`) with no `footer` substring.
    Returns absolute URLs."""
    out: Dict[str, str] = {}

    target = soup.find("footer")
    if target is None:
        for sel in (".site-footer", "#site-footer", ".page-footer",
                    "#footer", ".footer", "[class*='site-footer']",
                    "[id*='footer']", "[class*='footer-widget']"):
            try:
                el = soup.select_one(sel)
            except Exception:
                el = None
            if el:
                target = el
                break
    if target is None:
        return out

    def _bg_image_from_style(style: str) -> Optional[str]:
        if not style:
            return None
        m = re.search(r"background(?:-image)?\s*:[^;]*url\(\s*(['\"]?)([^'\")]+)\1\s*\)",
                      style, re.IGNORECASE)
        return m.group(2).strip() if m else None

    def _bg_color_from_style(style: str) -> Optional[str]:
        if not style:
            return None
        m = re.search(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))",
                      style, re.IGNORECASE)
        return m.group(1).strip() if m else None

    # 1) Inline style on the footer element itself (highest priority)
    inline = target.get("style", "") or ""
    img = _bg_image_from_style(inline)
    if img:
        resolved = _resolve(base_url, img)
        if resolved:
            out["footerBgImage"] = resolved
    col = _bg_color_from_style(inline)
    if col:
        out["footerBgColor"] = col

    # 2) Walk the footer subtree to collect class names and IDs that any CSS
    #    rule could be targeting. Include the <footer> element's own attrs.
    classes: set[str] = set()
    ids: set[str] = set()
    def _collect(el):
        try:
            for c in el.get("class", []) or []:
                if c:
                    classes.add(c)
            id_ = el.get("id", "") or ""
            if id_:
                ids.add(id_)
        except AttributeError:
            return
    _collect(target)
    for el in target.find_all(True):
        _collect(el)

    css_text = "\n".join(t.get_text() for t in soup.find_all("style") if t.get_text())
    if not css_text:
        return out

    # Pre-compile a single alternation matcher for the footer subtree's tokens.
    # We require a non-identifier character (or end of string) after each token
    # so `.elementor-32` doesn't match `.elementor-3200`.
    selector_alts: list[str] = ["footer"]  # tag name itself counts
    for c in classes:
        selector_alts.append(rf"\.{re.escape(c)}")
    for i in ids:
        selector_alts.append(rf"#{re.escape(i)}")
    if not selector_alts:
        return out
    token_rx = re.compile(rf"(?:{'|'.join(selector_alts)})(?![\w-])")

    rule_rx = re.compile(r"([^{}]+)\{([^}]*)\}")
    last_color: Optional[str] = None
    last_image: Optional[str] = None
    for m in rule_rx.finditer(css_text):
        selectors = m.group(1)
        body = m.group(2)
        if not token_rx.search(selectors):
            continue
        img2 = _bg_image_from_style(body)
        if img2:
            last_image = img2
        col2 = _bg_color_from_style(body)
        if col2:
            last_color = col2

    if last_image and "footerBgImage" not in out:
        resolved = _resolve(base_url, last_image)
        if resolved:
            out["footerBgImage"] = resolved
    if last_color and "footerBgColor" not in out:
        out["footerBgColor"] = last_color

    return out


def _detect_layout_patterns(soup: "BeautifulSoup") -> Dict[str, Any]:
    sections: List[str] = []

    def any_match(*sels: str) -> bool:
        for sel in sels:
            try:
                if soup.select_one(sel):
                    return True
            except Exception:
                pass
        return False

    def count_match(*sels: str) -> int:
        n = 0
        for sel in sels:
            try:
                n += len(soup.select(sel))
            except Exception:
                pass
        return n

    if any_match("[class*='hero']", "[class*='banner']", "[class*='slider']", "[class*='carousel']",
                 "[class*='jumbotron']", "[class*='wp-block-cover']", "[class*='page-header']"):
        sections.append("hero-section")
    if count_match("[class*='card']", "[class*='grid-item']", "[class*='feature']", "[class*='tile']") >= 3:
        sections.append("card-grid")
    if any_match("[class*='testimonial']", "[class*='review']", "[class*='quote']") or count_match("blockquote") >= 2:
        sections.append("testimonials")
    if any_match("[class*='gallery']", "[class*='lightbox']", "[class*='album']") or count_match("img") >= 8:
        sections.append("image-gallery")
    if count_match("[class*='faq']", "[class*='accordion']", "[class*='collapse']") >= 2:
        sections.append("faq")
    if count_match("[class*='team']", "[class*='staff']", "[class*='member']") >= 2:
        sections.append("team-section")
    if any_match("[class*='pricing']", "[class*='price-table']"):
        sections.append("pricing-table")

    # Nav links
    nav_links: List[str] = []
    seen: set[str] = set()
    for sel in ["nav a", "header a", "[role='navigation'] a", "#nav a", "#menu a", ".nav a"]:
        try:
            for a in soup.select(sel):
                t = _clean(a.get_text())
                if t and 1 < len(t) < 40 and t not in seen:
                    seen.add(t)
                    nav_links.append(t)
        except Exception:
            pass
    return {"sections": sections, "navLinks": nav_links[:14]}


# ─────────────────────────────────────────────────────────────────────────────
# Navigation-tree extraction (with dropdown/submenu children)
# ─────────────────────────────────────────────────────────────────────────────

# Sentinel for items whose href exists but is a non-navigable placeholder
# ("#", "javascript:void(0)"). Public renderer treats these as "heading only".
_NAV_PLACEHOLDER_HREFS = {"#", "/#", "javascript:void(0)", "javascript:;"}


def _nav_item_from_li(li, base_url: str, depth: int = 0) -> Optional[Dict[str, Any]]:
    """Turn an <li> into a {text, href, children} node. Handles the common
    pattern of <li><a>Label</a><ul><li>...</li></ul></li> used by most CMS
    themes (WordPress, Squarespace, Wix, hand-rolled Bootstrap, etc.).
    Depth cap of 2 since dropdown-of-dropdown is rare and usually noise."""
    if depth > 2:
        return None
    # First <a> inside the li that isn't itself nested in a sub-<ul>
    anchor = None
    for a in li.find_all("a", recursive=False):
        anchor = a
        break
    if anchor is None:
        for a in li.find_all("a"):
            if a.find_parent("ul") is li.find("ul"):
                continue
            anchor = a
            break
    text = ""
    href = ""
    if anchor is not None:
        text = _clean(anchor.get_text())
        href = (anchor.get("href") or "").strip()
    if not text:
        # Sometimes the label is a <span> sibling (e.g. "heading-only" menu parents)
        span = li.find(["span", "button"], recursive=False)
        if span:
            text = _clean(span.get_text())
    if not text or len(text) > 80:
        return None

    children: List[Dict[str, Any]] = []
    for sub_ul in li.find_all("ul", recursive=False):
        for sub_li in sub_ul.find_all("li", recursive=False):
            child = _nav_item_from_li(sub_li, base_url, depth + 1)
            if child:
                children.append(child)

    resolved = _resolve(base_url, href) if href else None
    is_placeholder = href in _NAV_PLACEHOLDER_HREFS
    return {
        "text": text,
        "href": "" if is_placeholder else (resolved or ""),
        "children": children[:25],
    }


def _extract_nav_tree(soup: "BeautifulSoup", base_url: str) -> List[Dict[str, Any]]:
    """Find the primary site nav and return a nested tree of items.
    Falls back to the flat-link list if we can't find a usable <ul> root."""
    # Try nav containers in priority order; pick the one with the most
    # top-level <li> direct children (strongest signal of a real menu).
    candidates: List[Any] = []
    for sel in ("header nav", "nav[role='navigation']", "nav.main-navigation",
                "nav.primary-menu", "nav.menu", "[role='navigation']",
                "header [class*='menu']", "header [class*='nav']", "nav"):
        try:
            for node in soup.select(sel):
                candidates.append(node)
        except Exception:
            continue

    def top_level_count(root) -> int:
        uls = root.find_all("ul", recursive=True, limit=3)
        return max((len(ul.find_all("li", recursive=False)) for ul in uls), default=0)

    candidates = [c for c in candidates if top_level_count(c) >= 2]
    candidates.sort(key=top_level_count, reverse=True)

    for root in candidates[:10]:
        uls = root.find_all("ul", recursive=True)
        # Use the <ul> with the most direct <li> children (primary nav level)
        target = max(uls, key=lambda u: len(u.find_all("li", recursive=False)), default=None)
        if target is None or len(target.find_all("li", recursive=False)) < 2:
            continue
        items: List[Dict[str, Any]] = []
        for li in target.find_all("li", recursive=False):
            node = _nav_item_from_li(li, base_url)
            if node:
                items.append(node)
        if len(items) >= 2:
            return items[:50]

    # Fallback: flat anchor list inside the first nav-like container
    for sel in ("header nav a", "nav a[href]", "[role='navigation'] a"):
        try:
            anchors = soup.select(sel)
        except Exception:
            continue
        flat: List[Dict[str, Any]] = []
        seen: set = set()
        for a in anchors[:100]:
            t = _clean(a.get_text())
            if not t or len(t) > 80 or t in seen:
                continue
            href = (a.get("href") or "").strip()
            seen.add(t)
            flat.append({
                "text": t,
                "href": "" if href in _NAV_PLACEHOLDER_HREFS else (_resolve(base_url, href) or ""),
                "children": [],
            })
        if flat:
            return flat[:50]
    return []


def _collect_internal_links(soup: "BeautifulSoup", base_url: str) -> List[str]:
    """Return all unique same-origin page URLs found in <a href> tags.

    Filters out: external links, media/static files, WP admin/feed/tag paths,
    and URL fragments.  Suitable for discovering pages not listed in the nav.
    """
    from urllib.parse import urlparse as _urlparse

    _parsed_base = _urlparse(base_url)
    origin = f"{_parsed_base.scheme}://{_parsed_base.netloc}"
    home = origin.rstrip("/")

    _SKIP_EXTS = frozenset([
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar",
        ".mp4", ".mp3", ".avi", ".mov", ".css", ".js",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ])
    _SKIP_PREFIXES = (
        "/wp-admin", "/wp-content", "/wp-includes", "/wp-login",
        "/wp-json", "/xmlrpc", "/feed",
    )
    _SKIP_SEGMENTS = ("/tag/", "/author/", "/page/", "/attachment/", "/comment-page-")

    seen: set = set()
    results: List[str] = []

    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        resolved = _resolve(base_url, href)
        if not resolved:
            continue
        # Same origin only
        if not (resolved.startswith(origin + "/") or resolved.rstrip("/") == home):
            continue
        p_path = _urlparse(resolved).path.lower().rstrip("/")
        if any(p_path.endswith(ext) for ext in _SKIP_EXTS):
            continue
        if any(p_path.startswith(pfx) for pfx in _SKIP_PREFIXES):
            continue
        if any(seg in p_path for seg in _SKIP_SEGMENTS):
            continue
        # Normalize: strip fragment and trailing slash
        clean = resolved.split("#")[0].rstrip("/")
        if not clean or clean == home:
            continue
        if clean not in seen:
            seen.add(clean)
            results.append(clean)

    return results


def _extract_logo_url(soup: "BeautifulSoup", base_url: str) -> Optional[str]:
    """Find the site logo. Prefers images whose filename/alt/class mention 'logo',
    scoped to <header>/.site-header first, then falling back to any <img> match.
    Returns absolute URL or None."""
    def _score_img(img) -> int:
        score = 0
        src = (img.get("src") or img.get("data-src") or "").lower()
        alt = (img.get("alt") or "").lower()
        cls = " ".join(img.get("class") or []).lower()
        parent_cls = " ".join((img.parent.get("class") if img.parent and img.parent.get("class") else []) or []).lower()
        for key, weight in (("logo", 10), ("brand", 5), ("site-title", 5)):
            if key in src: score += weight
            if key in alt: score += weight
            if key in cls: score += weight
            if key in parent_cls: score += weight
        return score

    # Search inside header/branding containers first.
    candidates: List = []
    for scope_sel in ("header", ".site-header", ".site-branding", "#site-header",
                      ".header", "#header", ".logo", "#logo", ".site-logo", ".custom-logo-link"):
        try:
            for el in soup.select(scope_sel):
                candidates.extend(el.find_all("img"))
        except Exception:
            pass
    # If nothing found in header scope, widen to the whole page — but still score.
    if not candidates:
        candidates = list(soup.find_all("img"))

    best = None
    best_score = 0
    for img in candidates:
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        s = _score_img(img)
        if s > best_score:
            best_score = s
            best = src
    if best and best_score > 0:
        return _resolve(base_url, best)
    return None


def _extract_slideshow_images(soup: "BeautifulSoup", base_url: str) -> List[str]:
    """Find images inside common slideshow/carousel containers (MetaSlider,
    Smart Slider, Swiper, Slick, WP block slideshow, hero sliders, etc).

    Returns a deduped list of absolute URLs, in document order. Skips SVGs
    (those are usually nav icons, not slide content). Returns [] if nothing
    looks like a slideshow — single hero images go through
    _extract_hero_image_url instead.
    """
    selectors = [
        # MetaSlider (very common WP plugin)
        ".metaslider img", ".ml-slide img", ".ml-slider img",
        # Smart Slider 3
        ".n2-ss-slider img", ".n2-ss-slide img",
        # Swiper
        ".swiper-slide img", ".swiper-container img",
        # Slick
        ".slick-slide img", ".slick-slider img",
        # Revolution slider
        ".rev_slider img", ".rev-slider img", "rs-slide img",
        # Generic
        "[class*='slideshow'] img", "[class*='slider'] img", "[class*='carousel'] img",
        ".wp-block-cover img",
    ]
    seen: set[str] = set()
    urls: List[str] = []
    for sel in selectors:
        try:
            nodes = soup.select(sel)
        except Exception:
            continue
        for img in nodes:
            src = (img.get("src") or img.get("data-src") or
                   img.get("data-lazy-src") or img.get("data-original") or "")
            # MetaSlider often uses srcset — grab the widest candidate
            if not src:
                srcset = img.get("srcset") or img.get("data-srcset") or ""
                if srcset:
                    cands = [c.strip().split(" ")[0] for c in srcset.split(",") if c.strip()]
                    src = cands[-1] if cands else ""
            if not src or src.lower().endswith(".svg"):
                continue
            absolute = _resolve(base_url, src)
            # Filter query-string noise so the same image at different sizes
            # isn't counted twice
            key = absolute.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            urls.append(absolute)
        # Stop at the first selector that found multiple images — we've
        # located the actual slideshow container
        if len(urls) >= 2:
            break
    # Require at least 2 distinct slide images; otherwise it's just a hero.
    return urls if len(urls) >= 2 else []


def _extract_hero_image_url(soup: "BeautifulSoup", base_url: str) -> Optional[str]:
    """Return an absolute URL for the largest above-the-fold banner image.
    Prefers explicit hero containers, falls back to og:image, then first sizable <img>."""
    # Check explicit hero/banner <img> selectors first (classic themes + WP block editor).
    # wp-block-cover is the Gutenberg "Cover" block — the dominant hero pattern for sites
    # built with the default WP editor since 5.0. page-header is common in Genesis/Divi/custom themes.
    for sel in (
        "[class*='wp-block-cover'] img", "[class*='cover__image'] img",
        "[class*='page-header'] img",
        "[class*='hero'] img", "[class*='banner'] img",
        "[class*='slider'] img", "[class*='carousel'] img",
        "header + section img", "main img",
    ):
        try:
            img = soup.select_one(sel)
        except Exception:
            continue
        if not img:
            continue
        src = (img.get("src") or img.get("data-src") or
               img.get("data-lazy-src") or img.get("data-original") or "")
        if src and not src.lower().endswith(".svg"):
            return _resolve(base_url, src)

    # Gutenberg cover blocks often store the image only as a CSS background-image on
    # the wrapper div (no <img> child). Check inline styles on cover/page-header elements.
    for sel in ("[class*='wp-block-cover']", "[class*='page-header']", "[class*='hero-section']"):
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if not el:
            continue
        style = el.get("style") or ""
        bg_m = re.search(r"background(?:-image)?\s*:\s*[^;]*url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)",
                         style, re.IGNORECASE)
        if bg_m:
            src = bg_m.group(1).strip()
            if src and not src.startswith("data:"):
                return _resolve(base_url, src)
    # og:image / twitter:image is the site owner's canonical representative image —
    # far better than the arbitrary first <img> on a card-grid homepage.
    for attr_pair in (
        {"property": "og:image"}, {"name": "og:image"},
        {"property": "twitter:image"}, {"name": "twitter:image"},
    ):
        og = soup.find("meta", attrs=attr_pair)
        if og and og.get("content"):
            resolved = _resolve(base_url, og["content"])
            if resolved:
                return resolved
    # Last resort: first non-svg image on the page; prefer srcset widest candidate
    # over the fallback src so responsive images aren't downsampled.
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or
               img.get("data-lazy-src") or img.get("data-original") or "")
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        if srcset:
            # srcset: "url1 400w, url2 800w, url3 1600w" — pick widest
            best = _srcset_widest(srcset)
            if best:
                src = best
        if src and not src.lower().endswith(".svg"):
            return _resolve(base_url, src)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core content extraction (text/images/links)
# ─────────────────────────────────────────────────────────────────────────────

_ARTICLE_SCOPE_SELECTORS = [
    "article.post",
    "article.hentry",
    "article[class*='post']",
    "article[class*='entry']",
    "main article",
    "article",
    ".entry-content",
    ".post-content",
    ".article-content",
    ".single-post .content",
    "main .content",
    "[role='main'] article",
    "[role='main']",
    "main",
]


def _find_article_scope(soup: "BeautifulSoup"):
    """Return (scope_element, scope_kind) for the main article container, or (None, '')."""
    # Prefer the <article> with the longest body text — avoids related-post <article> stubs.
    articles = soup.find_all("article")
    if articles:
        best = max(articles, key=lambda el: len(_clean(el.get_text())), default=None)
        if best and len(_clean(best.get_text())) > 120:
            return best, "article"
    for sel in _ARTICLE_SCOPE_SELECTORS:
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if el and len(_clean(el.get_text())) > 120:
            return el, sel
    return None, ""


_HTML_ALLOWED_TAGS = {
    "p", "a", "strong", "em", "b", "i", "u",
    "br", "ul", "ol", "li", "blockquote",
    "h2", "h3", "h4", "h5",
}
_HTML_ALLOWED_ATTRS = {
    "a": {"href", "title"},
}

# Hosts whose <iframe> embeds we trust enough to keep when bridging body
# content into the page builder. Anything else gets dropped because we don't
# want to inadvertently embed third-party tracking/widgets that could break
# under the imported site's CSP or load arbitrary JS.
_IFRAME_ALLOWED_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be",
    "vimeo.com", "player.vimeo.com",
    "calendly.com",
    "mailchimp.com", "list-manage.com",
    "google.com/maps", "maps.google.com",
    "spotify.com", "open.spotify.com",
    "soundcloud.com", "w.soundcloud.com",
)

def _iframe_host_allowed(src: str) -> bool:
    if not src:
        return False
    s = src.lower()
    return any(h in s for h in _IFRAME_ALLOWED_HOSTS)

def _sanitize_html_fragment(el, *, base_url: str = "") -> str:
    """Render a BeautifulSoup element as a sanitized HTML string.
    - Strips disallowed tags (keeps inner text via .unwrap()).
    - Keeps only allowed attributes.
    - Resolves relative <a href> against base_url.
    - Discards `<a href>` values that are javascript:/data:/about:/#empty.
    Returns the cleaned innerHTML (without the wrapper element itself).
    """
    if el is None:
        return ""
    try:
        from copy import copy as _copy
        node = _copy(el)
    except Exception:
        node = el
    try:
        for child in list(node.find_all(True)):
            tag = (child.name or "").lower()
            if tag not in _HTML_ALLOWED_TAGS:
                child.unwrap()
                continue
            allowed = _HTML_ALLOWED_ATTRS.get(tag, set())
            for attr in list(child.attrs.keys()):
                if attr not in allowed:
                    del child.attrs[attr]
            if tag == "a":
                href = (child.get("href") or "").strip()
                if not href or href.lower().startswith(("javascript:", "data:", "about:", "vbscript:")):
                    child.unwrap()
                    continue
                if href.startswith("#"):
                    # Anchor links lose meaning outside the source page; drop.
                    child.unwrap()
                    continue
                resolved = _resolve(base_url, href) if base_url else href
                child.attrs["href"] = resolved or href
        # Render inner HTML — joining child decoded strings preserves order.
        inner = "".join(str(c) for c in node.children).strip()
        # Collapse runs of whitespace inside the fragment for cleanliness.
        inner = re.sub(r"\s+", " ", inner)
        return inner
    except Exception:
        try:
            return el.get_text(" ", strip=True)
        except Exception:
            return ""


def _extract_body_ordered(scope_soup, base_url: str, *, max_chars: int = 8000) -> str:
    """Walk the article scope in DOM order and emit ONE combined HTML string
    that interleaves headings, paragraphs, lists, figures (with captions),
    and trusted iframes — preserving the source page's reading order.

    This is the structured counterpart to the flat `bodyHtml` list. Use it
    when the importer needs to render a faithful page body, not just a pile
    of paragraphs glued together.

    Caps total output at `max_chars` so a single source page can't blow up
    the resulting block payload.
    """
    if scope_soup is None:
        return ""
    parts: list[str] = []
    seen_text: set[str] = set()
    seen_img: set[str] = set()
    total = 0

    def _add(html: str):
        nonlocal total
        if not html:
            return
        if total + len(html) > max_chars:
            return
        parts.append(html)
        total += len(html)

    # Top-level structural tags we care about. We use a flat find_all rather
    # than recursion so nested wrappers (Elementor's column→widget→inner-text
    # nesting) collapse naturally — we handle dedup via seen_text/seen_img.
    structural = scope_soup.find_all([
        "h2", "h3", "h4",
        "p", "blockquote",
        "ul", "ol",
        "figure", "img",
        "iframe",
    ])
    for el in structural:
        if total >= max_chars:
            break
        tag = (el.name or "").lower()

        # Skip elements inside a parent we'll already emit (e.g. <p> inside
        # <blockquote>, <li> inside <ul>, <img> inside <figure>).
        if el.find_parent(["blockquote", "figure", "ul", "ol"]):
            if tag != "ul" and tag != "ol" and tag != "blockquote" and tag != "figure":
                continue
            # but a nested ul/ol inside another list is unusual — skip too
            if el.find_parent(["ul", "ol"]) and tag in ("ul", "ol"):
                continue

        if tag in ("h2", "h3", "h4"):
            txt = _clean(el.get_text(" ", strip=True))
            if not txt or len(txt) < 2 or len(txt) > 200 or txt in seen_text:
                continue
            seen_text.add(txt)
            _add(f"<{tag}>{txt}</{tag}>")
        elif tag in ("p", "blockquote"):
            txt = _clean(el.get_text(" ", strip=True))
            if not txt or len(txt) < 8 or txt in seen_text:
                continue
            seen_text.add(txt)
            inner = _sanitize_html_fragment(el, base_url=base_url)
            if not inner.strip():
                continue
            _add(f"<{tag}>{inner}</{tag}>")
        elif tag in ("ul", "ol"):
            items_html: list[str] = []
            for li in el.find_all("li", recursive=False) or el.find_all("li"):
                t = _clean(li.get_text(" ", strip=True))
                if not t or t in seen_text:
                    continue
                seen_text.add(t)
                inner = _sanitize_html_fragment(li, base_url=base_url)
                if inner.strip():
                    items_html.append(f"<li>{inner}</li>")
            if items_html:
                _add(f"<{tag}>{''.join(items_html)}</{tag}>")
        elif tag == "figure":
            img = el.find("img")
            if img is None:
                continue
            src = (img.get("src") or img.get("data-src")
                   or img.get("data-lazy-src") or img.get("data-original") or "").strip()
            abs_src = _resolve(base_url, src)
            if not abs_src or abs_src in seen_img:
                continue
            lower = abs_src.lower()
            if any(x in lower for x in ("logo", "favicon", "avatar", "sprite", "gravatar",
                                         "spinner", "icon-", "/icons/", "placeholder")):
                continue
            seen_img.add(abs_src)
            cap_el = el.find("figcaption")
            cap = _clean(cap_el.get_text(" ", strip=True)) if cap_el else ""
            alt = _clean(img.get("alt") or "")
            if cap:
                _add(f'<figure><img src="{abs_src}" alt="{alt}"><figcaption>{cap}</figcaption></figure>')
            else:
                _add(f'<figure><img src="{abs_src}" alt="{alt}"></figure>')
        elif tag == "img":
            src = (el.get("src") or el.get("data-src")
                   or el.get("data-lazy-src") or el.get("data-original") or "").strip()
            abs_src = _resolve(base_url, src)
            if not abs_src or abs_src in seen_img:
                continue
            lower = abs_src.lower()
            if any(x in lower for x in ("logo", "favicon", "avatar", "sprite", "gravatar",
                                         "spinner", "icon-", "/icons/", "placeholder")):
                continue
            # Skip tiny known-dimension images
            try:
                w = int(re.match(r"\s*(\d+)", str(el.get("width") or "0")).group(1))
                h = int(re.match(r"\s*(\d+)", str(el.get("height") or "0")).group(1))
                if (w and w < 200) or (h and h < 100):
                    continue
            except Exception:
                pass
            seen_img.add(abs_src)
            alt = _clean(el.get("alt") or "")
            _add(f'<figure><img src="{abs_src}" alt="{alt}"></figure>')
        elif tag == "iframe":
            src = (el.get("src") or "").strip()
            abs_src = _resolve(base_url, src) if src else ""
            if not abs_src or not _iframe_host_allowed(abs_src):
                continue
            # Cap dimensions so a single embed can't dominate the page; emit
            # a responsive 16:9 wrapper.
            _add(
                '<div class="embed-responsive" style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;margin:1rem 0;">'
                f'<iframe src="{abs_src}" allowfullscreen loading="lazy" '
                'style="position:absolute;top:0;left:0;width:100%;height:100%;border:0;"></iframe>'
                '</div>'
            )
    return "".join(parts).strip()


def _extract_content(soup: "BeautifulSoup", base_url: str) -> Dict[str, Any]:
    page_title = _clean(
        (soup.title.get_text() if soup.title else "")
        or (soup.h1.get_text() if soup.h1 else "")
        or base_url
    )

    meta_desc_el = soup.find("meta", attrs={"name": "description"}) \
                or soup.find("meta", attrs={"property": "og:description"})
    meta_description = _clean(meta_desc_el["content"]) if (meta_desc_el and meta_desc_el.get("content")) else ""

    og_image_el = soup.find("meta", attrs={"property": "og:image"}) \
               or soup.find("meta", attrs={"name": "og:image"}) \
               or soup.find("meta", attrs={"property": "twitter:image"})
    og_image = _resolve(base_url, og_image_el["content"]) if (og_image_el and og_image_el.get("content")) else ""

    # Remove noise (after design tokens + layout have already been captured)
    for sel in ["script", "style", "noscript", "iframe",
                "header", "nav", "footer", "aside",
                "[role='navigation']", "[role='banner']", "[role='contentinfo']",
                "[class*='sidebar']", "[class*='related']", "[class*='you-may-also-like']",
                "[class*='comments']", "[id*='comments']",
                "[class*='share']", "[class*='social']",
                "[class*='breadcrumb']", "[class*='pagination']",
                "[class*='menu']", "[class*='navbar']"]:
        try:
            for el in soup.select(sel):
                el.decompose()
        except Exception:
            pass

    # Scope: prefer the main article container when we can find one.
    article_scope, scope_kind = _find_article_scope(soup)
    scope_soup = article_scope if article_scope is not None else soup

    # Headings — only within article scope when we have one; otherwise page-wide.
    headings: List[Dict[str, str]] = []
    for tag in ["h1", "h2", "h3", "h4"]:
        for h in scope_soup.find_all(tag):
            t = _clean(h.get_text())
            if t:
                headings.append({"level": tag.upper(), "text": t})

    # Body paragraphs — scoped. Capture both plain text (legacy callers) and
    # sanitized HTML (preserves inline links/bold/lists for the importer).
    body_text: List[str] = []
    body_html: List[str] = []
    body_selectors = ["p", "li", "blockquote", "figcaption"]
    seen_text: set[str] = set()
    for sel in body_selectors:
        try:
            for el in scope_soup.select(sel):
                t = _clean(el.get_text())
                if not t or len(t) <= 20 or t in seen_text:
                    continue
                seen_text.add(t)
                body_text.append(t)
                html_frag = _sanitize_html_fragment(el, base_url=base_url)
                # Wrap loose <li> fragments back in their list type so the
                # importer can render them as lists rather than orphan text.
                if sel == "li":
                    body_html.append(f"<li>{html_frag}</li>")
                elif sel == "blockquote":
                    body_html.append(f"<blockquote>{html_frag}</blockquote>")
                else:
                    body_html.append(f"<p>{html_frag}</p>")
        except Exception:
            pass

    # Images — scoped.
    images: List[Dict[str, Any]] = []
    seen_img: set[str] = set()
    for img in scope_soup.find_all("img"):
        src = (img.get("src") or img.get("data-src")
               or img.get("data-lazy-src") or img.get("data-original"))
        abs_src = _resolve(base_url, src)
        if not abs_src or abs_src in seen_img:
            continue
        lower = abs_src.lower()
        if any(x in lower for x in ("logo", "favicon", "avatar", "sprite", "gravatar",
                                     "spinner", "icon-", "/icons/", "placeholder")):
            continue
        seen_img.add(abs_src)
        images.append({
            "url": abs_src,
            "alt": _clean(img.get("alt") or ""),
            "width":  img.get("width"),
            "height": img.get("height"),
        })
    # CSS background images within scope
    for el in scope_soup.select("[style*='background']"):
        style_val = el.get("style", "")
        m = re.search(r"url\(['\"]?([^'\")\s]+)['\"]?\)", style_val, re.IGNORECASE)
        if m:
            abs_src = _resolve(base_url, m.group(1))
            if abs_src and abs_src not in seen_img:
                seen_img.add(abs_src)
                images.append({"url": abs_src, "alt": "", "width": None, "height": None})

    # Links — scoped.
    links: List[Dict[str, str]] = []
    seen_link: set[str] = set()
    for a in scope_soup.find_all("a", href=True):
        href = _resolve(base_url, a.get("href"))
        text = _clean(a.get_text())
        if href and text and href not in seen_link:
            seen_link.add(href)
            links.append({"href": href, "text": text[:200]})

    body_ordered = _extract_body_ordered(scope_soup, base_url)

    return {
        "pageTitle":       page_title,
        "metaDescription": meta_description,
        "ogImage":         og_image,
        "articleScope":    scope_kind,
        "headings":        headings,
        "bodyText":        body_text,
        "bodyHtml":        body_html,
        "bodyOrdered":     body_ordered,
        "images":          images,
        "links":           links[:500],
    }


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Footer extraction — pulls contact info, social links, and copyright from the
# source site's <footer> element and returns a structured payload that the
# importer can render into the site's footer_html field.
# ─────────────────────────────────────────────────────────────────────────────

_SOCIAL_DOMAINS = {
    "facebook.com":   "Facebook",
    "instagram.com":  "Instagram",
    "twitter.com":    "Twitter",
    "x.com":          "X",
    "youtube.com":    "YouTube",
    "linkedin.com":   "LinkedIn",
    "tiktok.com":     "TikTok",
    "pinterest.com":  "Pinterest",
    "vimeo.com":      "Vimeo",
    "threads.net":    "Threads",
}

_WEB_BUILDER_CREDIT = re.compile(
    r"(websites? by|powered by|site by|built by|designed by|created by)\s*:?",
    re.IGNORECASE,
)


_SPONSOR_HEADING_RX = re.compile(
    r"\b(sponsors?|our\s+sponsors?|presenting\s+sponsors?|partners?|"
    r"our\s+partners?|supporters?|affiliates?|corporate\s+partners?|"
    r"event\s+sponsors?|proud\s+sponsors?|gold\s+sponsors?|silver\s+sponsors?|"
    r"platinum\s+sponsors?|bronze\s+sponsors?)\b",
    re.IGNORECASE,
)
# Class/ID hints for sponsor-shaped sections (Elementor, generic CMS)
_SPONSOR_CONTAINER_HINTS = re.compile(r"sponsor|partner|supporter|affiliate", re.IGNORECASE)


_BG_IMAGE_RX = re.compile(r"background-image\s*:\s*url\((['\"]?)([^'\")]+)\1\)", re.IGNORECASE)


def _collect_logo_items(region: Any, base_url: str) -> List[Dict[str, str]]:
    """Walk a DOM subtree and return logo-shaped items as [{name, logo_url, url}].
    Detects:
      - <img src/data-src/data-lazy-src/srcset>
      - any element with data-thumbnail (Elementor Gallery widget)
      - any element with inline style="background-image:url(...)"
    """
    if region is None:
        return []

    items: List[Dict[str, str]] = []
    seen: set = set()

    def _push(src: str, host_el: Any) -> None:
        src = (src or "").strip()
        if not src:
            return
        resolved = _resolve(base_url, src)
        if not resolved or resolved in seen:
            return
        # Skip obvious non-logo svg/data tracking pixels
        low = resolved.lower()
        if low.startswith("data:") and "image/gif" in low:
            return
        seen.add(resolved)

        # Name: alt / aria-label / title on the host or any ancestor up to region
        name = ""
        node = host_el
        for _ in range(4):
            if node is None or node is region:
                break
            for attr in ("alt", "aria-label", "title"):
                val = (node.get(attr) if hasattr(node, "get") else None) or ""
                val = val.strip()
                if val and val.lower() not in {"logo", "image", "sponsor", "partner", ""}:
                    name = val
                    break
            if name:
                break
            node = getattr(node, "parent", None)

        # figcaption fallback
        if not name:
            fig = host_el.find_parent("figure") if hasattr(host_el, "find_parent") else None
            if fig:
                cap = fig.find("figcaption")
                if cap:
                    name = _clean(cap.get_text()) or name

        # Link: parent <a href>
        href = ""
        a_parent = host_el.find_parent("a") if hasattr(host_el, "find_parent") else None
        if a_parent and a_parent.get("href"):
            raw = (a_parent.get("href") or "").strip()
            if raw and not raw.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                href = _resolve(base_url, raw) or ""

        items.append({"name": name, "logo_url": resolved, "url": href})

    # 1. <img> tags
    for img in region.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if not src:
            srcset = img.get("srcset") or ""
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        # skip tiny obviously-decorative
        try:
            w = int(img.get("width") or 0)
            h = int(img.get("height") or 0)
            if w and h and (w < 30 or h < 20):
                continue
        except Exception:
            pass
        _push(src, img)

    # 2. Elementor Gallery — divs with data-thumbnail
    for el in region.find_all(attrs={"data-thumbnail": True}):
        _push(el.get("data-thumbnail") or "", el)

    # 3. Inline style="background-image:url(...)"
    for el in region.find_all(style=True):
        style = el.get("style") or ""
        m = _BG_IMAGE_RX.search(style)
        if m:
            _push(m.group(2), el)

    return items


_CTA_BUTTON_HINTS = re.compile(r"button|btn|cta", re.IGNORECASE)


def _extract_ctas(soup: "BeautifulSoup", base_url: str) -> List[Dict[str, Any]]:
    """Find call-to-action banner sections shaped like:
        [short heading text]   [styled button link]
    Returns a list of {headline, button_text, button_link, bg_color}.
    Preserves source order and DOES NOT dedupe — the same CTA repeated above
    and below a content block on the source page should appear twice on the
    rebuilt page too.
    """
    if soup is None:
        return []

    debug = bool(os.environ.get("LAVENDIR_CTA_DEBUG"))
    ctas: List[Dict[str, Any]] = []
    used_scope_ids: set = set()  # avoid re-emitting the same CTA from sibling buttons

    # Find every button-shaped anchor in the page body.
    # Note: we DON'T skip <footer> parents because page builders like Elementor
    # use a "footer" template region for body-content CTA bars. The scope-shape
    # validator below will reject true footer junk (many links, copyright, etc).
    for button in soup.find_all("a"):
        if button.find_parent(["nav", "header"]):
            continue
        a_cls = " ".join(button.get("class", []) or []).lower()
        role  = (button.get("role") or "").lower()
        href  = (button.get("href") or "").strip()
        txt   = _clean(button.get_text())
        if not txt or not href or len(txt) > 60:
            if debug and txt:
                print(f"[CTA] skip text/href len: txt={txt!r} href={href!r}")
            continue
        if href.lower().startswith(("javascript:", "mailto:", "tel:")):
            if debug:
                print(f"[CTA] skip protocol: {txt!r} -> {href!r}")
            continue
        looks_buttoned = (
            _CTA_BUTTON_HINTS.search(a_cls) or role == "button"
            or "background" in (button.get("style") or "").lower()
        )
        if not looks_buttoned:
            continue

        if debug:
            print(f"[CTA] BUTTON candidate: {txt!r} -> {href!r}  cls={a_cls[:80]!r}")

        # Walk UP from the button looking for the smallest ancestor that
        # also contains a heading. That ancestor IS the CTA scope.
        scope = None
        bailed = False
        for ancestor in button.parents:
            if ancestor.name not in ("section", "div"):
                continue
            cls = " ".join(ancestor.get("class", []) or []).lower()
            eid = (ancestor.get("id") or "").lower()
            if any(s in (cls + " " + eid) for s in ("menu", "navbar", "breadcrumb", "sidebar", "pagination", "comments")):
                bailed = True
                if debug:
                    print(f"[CTA]   bail at ancestor cls={cls[:60]!r} id={eid!r}")
                break  # scope is invalid — bail
            heads = ancestor.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heads:
                scope = ancestor
                break
        if scope is None:
            if debug:
                print(f"[CTA]   no valid scope (bailed={bailed})")
            continue

        scope_id = id(scope)
        if scope_id in used_scope_ids:
            if debug:
                print(f"[CTA]   scope already used (sibling button) — skip")
            continue

        # Sanity: the scope shouldn't be the entire page. Reject if it
        # contains too many other buttons (that means it's a parent of
        # multiple CTAs, not a single CTA scope).
        scope_buttons = []
        for a in scope.find_all("a"):
            ac = " ".join(a.get("class", []) or []).lower()
            if _CTA_BUTTON_HINTS.search(ac) or (a.get("role") or "").lower() == "button":
                scope_buttons.append(a)
        scope_heads = scope.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        scope_paras = [p for p in scope.find_all("p") if _clean(p.get_text())]
        big_imgs = [i for i in scope.find_all("img")
                    if int(i.get("width") or 0) >= 200 or int(i.get("height") or 0) >= 200]
        if debug:
            sc_cls = " ".join(scope.get("class", []) or [])
            print(f"[CTA]   SCOPE class={sc_cls[:80]!r}  buttons={len(scope_buttons)} heads={len(scope_heads)} paras={len(scope_paras)} big_imgs={len(big_imgs)}")
        if len(scope_buttons) > 1:
            continue
        # Reject if the scope has too many headings or paragraphs to be a CTA bar
        if len(scope_heads) > 2:
            continue
        if len(scope_paras) > 1:
            continue
        if big_imgs:
            continue

        heading_text = ""
        for h in scope_heads:
            t = _clean(h.get_text())
            if t and len(t) <= 80:
                heading_text = t
                break
        if not heading_text:
            if debug:
                print(f"[CTA]   no usable heading text in scope")
            continue

        if href and not href.lower().startswith(("#",)):
            button_href = _resolve(base_url, href) or href
        else:
            button_href = href

        # Background color from inline style if present (walk up to find one)
        bg_color = ""
        for n in [scope] + list(scope.parents)[:3]:
            if not hasattr(n, "get"):
                continue
            style = n.get("style") or ""
            bg_match = re.search(r"background(?:-color)?\s*:\s*([^;]+)", style, re.IGNORECASE)
            if bg_match:
                cand = bg_match.group(1).strip()
                if cand and "url(" not in cand.lower() and "gradient" not in cand.lower():
                    bg_color = cand
                    break

        if debug:
            print(f"[CTA]   ACCEPT: headline={heading_text!r} btn={txt!r}")
        ctas.append({
            "headline":    heading_text,
            "button_text": txt,
            "button_link": button_href,
            "bg_color":    bg_color,
        })
        used_scope_ids.add(scope_id)
        if len(ctas) >= 8:
            break
    return ctas


_BANNER_BG_URL_RE = re.compile(r"background(?:-image)?\s*:\s*[^;}]*url\((['\"]?)([^'\")]+)\1\)", re.IGNORECASE)
_BANNER_HEIGHT_RE = re.compile(r"(?:min-)?height\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|vh|rem|em)", re.IGNORECASE)
_BANNER_PADDING_RE = re.compile(r"padding(?:-(?:top|bottom|block-start|block-end))?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*px", re.IGNORECASE)
# Overlay tint on the ::before/::after pseudo of a banner section. Matches
# rgba(...), rgb(...), hsla(...), hsl(...), or #hex on background[-color].
# We deliberately exclude `url(...)` matches — those would be the image
# itself, not an overlay color.
_BANNER_OVERLAY_RE = re.compile(
    r"background(?:-color)?\s*:\s*("
    r"rgba?\([^)]+\)"
    r"|hsla?\([^)]+\)"
    r"|#[0-9a-fA-F]{3,8}"
    r")",
    re.IGNORECASE,
)
_BANNER_OPACITY_RE = re.compile(r"(?<!-)opacity\s*:\s*([0-9.]+)", re.IGNORECASE)


def _hex_to_rgb(h: str) -> Optional[tuple]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return None


def _apply_alpha_to_color(color: str, alpha: float) -> str:
    """Convert `rgb(...)` or `#hex` plus an opacity into a single `rgba(...)`."""
    a = max(0.0, min(1.0, alpha))
    if color.startswith("#"):
        rgb = _hex_to_rgb(color)
        if not rgb:
            return color
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {a:.2f})"
    m = re.match(r"rgb\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*\)", color, re.IGNORECASE)
    if m:
        return f"rgba({m.group(1)}, {m.group(2)}, {m.group(3)}, {a:.2f})"
    return color


def _scale_rgba_alpha(color: str, mult: float) -> str:
    """Multiply an `rgba(...)` color's alpha channel by `mult`."""
    m = re.match(r"rgba\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9.]+)\s*\)", color, re.IGNORECASE)
    if not m:
        return color
    try:
        a = max(0.0, min(1.0, float(m.group(4)) * mult))
    except Exception:
        return color
    return f"rgba({m.group(1)}, {m.group(2)}, {m.group(3)}, {a:.2f})"


def _extract_page_banner(soup: "BeautifulSoup", base_url: str) -> Dict[str, Any]:
    """Find the page-title banner section on an interior page: the first
    section near the top of <body> that contains the page H1 and has a
    background image (CSS-backed, inline-styled, or data-attr lazy-loaded).

    Generalizable across CMSes:
      - WordPress / Elementor: per-page CSS targets `.elementor-element-XXXX`
      - Divi: `.et_pb_section_X { background-image: ... }`
      - Custom themes: inline `style="background-image: url(...)"` on a
        section/header/div near the top
      - Lazy-load themes: `data-bg`, `data-background`, `data-bg-image`

    Returns {background_url, height, title} or {}.
    """
    if soup is None:
        return {}
    body = soup.body or soup
    if body is None:
        return {}

    # Build a class -> background-url + height index from every inline <style>
    # block. Linked stylesheets are NOT fetched here — they should be inlined
    # before this is called (same pre-processing as design_tokens does).
    css_blob = ""
    for st in soup.find_all("style"):
        text = st.string if st.string else "".join(st.strings)
        if text:
            css_blob += "\n" + text
    bg_index: Dict[str, str] = {}
    height_index: Dict[str, int] = {}
    padding_index: Dict[str, int] = {}
    overlay_index: Dict[str, str] = {}  # class -> rgba/hex tint applied via ::before/::after
    if css_blob:
        # Naive CSS rule extraction. Skips @media nesting (will misparse — that's
        # acceptable; we only need the desktop default rule for each class).
        for rm in re.finditer(r"([^{}]+)\{([^{}]*)\}", css_blob):
            sel = rm.group(1)
            decls = rm.group(2)
            is_pseudo = "::before" in sel or "::after" in sel
            classes_in_sel = re.findall(r"\.([A-Za-z][\w-]+)", sel)
            if not classes_in_sel:
                continue
            if is_pseudo:
                # Overlay tint: pseudo-element with a solid/translucent background
                # color and (usually) an opacity declaration. Skip if it has a
                # background-image (that's a decorative pseudo, not an overlay).
                if _BANNER_BG_URL_RE.search(decls):
                    continue
                ov_m = _BANNER_OVERLAY_RE.search(decls)
                if not ov_m:
                    continue
                color = ov_m.group(1).strip()
                op_m = _BANNER_OPACITY_RE.search(decls)
                if op_m:
                    try:
                        op = float(op_m.group(1))
                        # Fold opacity into the rgba alpha when both are present
                        if color.lower().startswith("rgb(") or color.startswith("#"):
                            color = _apply_alpha_to_color(color, op)
                        elif color.lower().startswith("rgba("):
                            color = _scale_rgba_alpha(color, op)
                    except Exception:
                        pass
                for c in classes_in_sel:
                    overlay_index.setdefault(c, color)
                continue
            url_m = _BANNER_BG_URL_RE.search(decls)
            h_m = _BANNER_HEIGHT_RE.search(decls)
            ptot = sum(int(float(pm.group(1))) for pm in _BANNER_PADDING_RE.finditer(decls))
            if url_m:
                url = url_m.group(2).strip()
                if url and not url.startswith("data:") and "gradient" not in url.lower():
                    for c in classes_in_sel:
                        bg_index.setdefault(c, url)
            if h_m:
                hp = int(float(h_m.group(1)))
                if h_m.group(2).lower() == "vh":
                    hp = int(hp * 8)  # rough vh→px (assume ~800px viewport)
                for c in classes_in_sel:
                    height_index.setdefault(c, hp)
            if ptot:
                for c in classes_in_sel:
                    padding_index[c] = padding_index.get(c, 0) + ptot

    # Find the page H1 — the page title is the most reliable anchor for "this
    # is the banner ancestor we care about". Falls back to first H2 if no H1.
    h1 = body.find("h1")
    if h1 is None:
        h1 = body.find("h2")
    if h1 is None:
        return {}
    title = _clean(h1.get_text())
    if not title or len(title) > 120:
        return {}
    # Skip H1s that are clearly inside the global site header (logo wrap)
    if h1.find_parent("nav") or h1.find_parent("header"):
        # Try the next H1 outside the header
        for h in body.find_all(["h1", "h2"])[1:5]:
            if not h.find_parent("nav") and not h.find_parent("header"):
                h1 = h
                title = _clean(h.get_text())
                if title and len(title) <= 120:
                    break
        else:
            return {}

    # Look for a banner subtext — the first short paragraph or H2/H3 that
    # appears near the H1 (either as a sibling in the same wrapper, or as a
    # descendant of the heading wrapper). Most CMS banners pair an H1 with
    # one tagline line; we accept up to ~280 chars and reject anything that
    # looks like body content (links, multiple sentences with markup).
    subtext = ""
    try:
        # Strategy: walk up the H1 a few levels, and at each level scan the
        # subtree for the first non-H1 text-bearing element that isn't a
        # button/nav fragment.
        seen = {id(h1)}
        ascender = h1
        for _depth in range(3):
            ascender = ascender.parent
            if ascender is None or ascender.name == "body":
                break
            for el in ascender.find_all(["p", "h2", "h3", "div", "span"], limit=20):
                if id(el) in seen:
                    continue
                if el is h1 or h1 in getattr(el, "descendants", []) and el is not h1:
                    continue
                # Skip nav/button/list scraps
                if el.find_parent(["nav", "footer", "ul", "ol", "button"]):
                    continue
                if el.name in ("div", "span"):
                    # Only accept divs that are themselves leaf text containers
                    if el.find(["p", "h2", "h3", "h4", "ul", "ol", "img", "a"]):
                        continue
                txt = _clean(el.get_text(" ", strip=True))
                if not txt or len(txt) < 8 or len(txt) > 280:
                    continue
                if txt == title:
                    continue
                subtext = txt
                break
            if subtext:
                break
    except Exception:
        subtext = ""

    def _specificity(c: str) -> int:
        """Higher score = more specific (hex/digit suffix wins over generic class)."""
        score = 0
        if re.search(r"[0-9a-f]{4,}$", c, re.IGNORECASE): score += 100
        if re.search(r"\d", c):                         score += 20
        score += min(len(c), 40)
        return score

    def _build_result(bg_url: str, height: int, overlay: str = "") -> Dict[str, Any]:
        resolved = _resolve(base_url, bg_url) or bg_url
        # When a background image was found but no explicit height, use a
        # sensible visual default (400px) rather than 0 which triggers 70vh.
        effective_h = height if height >= 100 else 400
        r: Dict[str, Any] = {
            "background_url": resolved,
            "height": effective_h,
            "title": title,
            "subtext": subtext,
        }
        if overlay:
            r["overlay_color"] = overlay
        return r

    # Walk up the H1 looking for an ancestor that has a background image.
    # 15 levels covers deep Elementor nesting: section > container > column > widget-wrap > h1
    cur = h1
    for _ in range(15):
        cur = cur.parent
        if cur is None or cur.name == "body":
            break
        if cur.name in ("nav", "footer"):
            continue

        # 1) Inline style background
        style = cur.get("style") or ""
        m = _BANNER_BG_URL_RE.search(style)
        if m:
            url = m.group(2).strip()
            if url and not url.startswith("data:") and "gradient" not in url.lower():
                h_m = _BANNER_HEIGHT_RE.search(style)
                height = int(float(h_m.group(1))) if h_m else 0
                return _build_result(url, height)

        # 2) Simple data-* lazy-load attributes
        for attr in ("data-bg", "data-background", "data-bg-image", "data-image"):
            v = (cur.get(attr) or "").strip()
            if v and not v.startswith("data:") and "gradient" not in v.lower():
                return _build_result(v, 0)

        # 3) Elementor / Beaver Builder / Divi data-settings JSON.
        # Elementor stores background info as JSON on section/column elements:
        #   data-settings='{"background_background":"classic",
        #                   "background_image":{"url":"https://...","id":123}}'
        # Other builders use similar patterns with different key names.
        settings_raw = (cur.get("data-settings") or cur.get("data-config") or "").strip()
        if settings_raw and settings_raw.startswith("{"):
            try:
                settings = json.loads(settings_raw)
                # Elementor primary key
                bg_img = settings.get("background_image") or {}
                bg_url = (bg_img.get("url") if isinstance(bg_img, dict) else None) or ""
                # Some builders use background_src or bg_image
                if not bg_url:
                    bg_url = (settings.get("background_src") or settings.get("bg_image") or "")
                if bg_url and isinstance(bg_url, str) and not bg_url.startswith("data:"):
                    # Elementor stores min_height as {"unit":"px","size":400} at key
                    # "_min_height" or "min_height"
                    h_obj = settings.get("_min_height") or settings.get("min_height") or {}
                    height = 0
                    if isinstance(h_obj, dict):
                        try:
                            height = int(float(h_obj.get("size") or 0))
                            if (h_obj.get("unit") or "").lower() == "vh":
                                height = int(height * 8)
                        except Exception:
                            pass
                    # Overlay: background_color in data-settings
                    overlay = settings.get("background_color") or settings.get("bg_color") or ""
                    return _build_result(bg_url, height, overlay)
            except Exception:
                pass

        # 4) Class match against the inline-CSS background-image index.
        # Prefer specific classes (with a hex/numeric suffix that uniquely
        # identifies a single section, e.g. `elementor-element-09e25f2` or
        # `et_pb_section_3`) over generic theme classes.
        cls_list = cur.get("class", []) or []
        for cls in sorted(cls_list, key=_specificity, reverse=True):
            if cls not in bg_index:
                continue
            height = height_index.get(cls, 0)
            if height < 100:
                pad_h = padding_index.get(cls, 0)
                height = (pad_h + 60) if pad_h >= 100 else 0
            overlay = overlay_index.get(cls) or next(
                (overlay_index[c2] for c2 in cls_list if c2 in overlay_index), ""
            )
            return _build_result(bg_index[cls], height, overlay)

    return {}


def _extract_sponsors(soup: "BeautifulSoup", base_url: str) -> List[Dict[str, str]]:
    """Find a sponsor/partner section and return [{name, logo_url, url}] entries.
    Strategy:
      1. Locate a container by class/id matching sponsor/partner hints
         containing >=2 logo-like elements (img / data-thumbnail / bg-image).
      2. Locate a heading whose text matches sponsor patterns; walk UP its
         ancestors until we find one containing >=2 logo-like elements.
    Returns at most ~30 entries. Empty list if nothing convincing is found.
    """
    if soup is None:
        return []

    candidates: List[Any] = []

    # Strategy 1: containers with matching class/id
    for el in soup.find_all(True):
        cls = " ".join(el.get("class", []) or [])
        eid = el.get("id", "") or ""
        if not (cls or eid):
            continue
        hay = f"{cls} {eid}"
        if _SPONSOR_CONTAINER_HINTS.search(hay):
            if any(s in hay.lower() for s in ("menu", "nav-", "footer-bottom", "copyright")):
                continue
            logos = _collect_logo_items(el, base_url)
            if len(logos) >= 2:
                candidates.append((el, logos))

    # Strategy 2: headings that name sponsors — walk UP to the first
    # ancestor containing >=2 logo items (gallery may be sibling-of-sibling).
    if not candidates:
        for h in soup.find_all(["h1", "h2", "h3", "h4"]):
            text = _clean(h.get_text())
            if not text or not _SPONSOR_HEADING_RX.search(text):
                continue
            node = h.parent
            climbed = 0
            while node is not None and climbed < 8:
                logos = _collect_logo_items(node, base_url)
                if len(logos) >= 2:
                    candidates.append((node, logos))
                    break
                node = getattr(node, "parent", None)
                climbed += 1

    if not candidates:
        return []

    # Pick the candidate with the most logos (most likely the real grid)
    candidates.sort(key=lambda pair: len(pair[1]), reverse=True)
    sponsors = candidates[0][1][:30]
    return sponsors


def _extract_footer(raw_html: str, base_url: str) -> Optional[Dict[str, Any]]:
    """Find the source site's <footer> and return structured pieces.
    Returns None if no footer is present."""
    if not raw_html:
        return None
    soup = BeautifulSoup(raw_html, "html.parser")
    footer = soup.find("footer")
    if footer is None:
        # Some themes don't use a <footer> tag — look for the common classes.
        for sel in ("[class*='site-footer']", "[id*='footer']", "[class*='footer-widget']"):
            try:
                el = soup.select_one(sel)
            except Exception:
                el = None
            if el:
                footer = el
                break
    if footer is None:
        return None

    # Strip noise we never want to carry over
    for el in footer.select("script, style, noscript, iframe, form, [class*='widget-title']"):
        el.decompose()

    # Resolve relative URLs so the footer works when rendered on our domain
    for a in footer.find_all("a", href=True):
        a["href"] = _resolve(base_url, a.get("href"))

    # Collect + classify links
    emails: List[str] = []
    phones: List[str] = []
    social: List[Dict[str, str]] = []
    other_links: List[Dict[str, str]] = []
    seen_href: set = set()
    for a in footer.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = _clean(a.get_text())
        if not href:
            continue
        low_href = href.lower()
        if low_href.startswith("mailto:"):
            em = href.split(":", 1)[1].split("?", 1)[0].strip().lstrip("%20").strip()
            if em and em not in emails:
                emails.append(em)
            continue
        if low_href.startswith("tel:"):
            ph = href.split(":", 1)[1].strip()
            if ph and ph not in phones:
                phones.append(ph)
            continue
        if low_href.startswith("javascript:") or low_href == "#":
            continue
        # Social?
        try:
            from urllib.parse import urlparse
            host = (urlparse(href).netloc or "").lower().lstrip("www.")
        except Exception:
            host = ""
        social_label = None
        for dom, label in _SOCIAL_DOMAINS.items():
            if host == dom or host.endswith("." + dom):
                social_label = label
                break
        if social_label:
            if href not in seen_href:
                seen_href.add(href)
                social.append({"label": social_label, "href": href})
            continue
        # Otherwise regular footer link (quick-nav, legal, etc.)
        if text and href not in seen_href and not _WEB_BUILDER_CREDIT.search(text):
            seen_href.add(href)
            other_links.append({"text": text[:80], "href": href})

    # Plain-text phone fallback — pick up numbers not wrapped in tel: links.
    if not phones:
        _phone_rx = re.compile(
            r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"
        )
        for el in footer.find_all(["p", "li", "div", "address", "span"]):
            t = el.get_text(" ").strip()
            if len(t) > 300:
                continue
            pm = _phone_rx.search(t)
            if pm:
                ph = re.sub(r"\s+", "", pm.group(0)).strip()
                if ph and ph not in phones:
                    phones.append(ph)
            if len(phones) >= 3:
                break

    # Address: look for a paragraph/li that contains a recognisable address pattern.
    # Supports: US state+ZIP, PO Box, street address with common suffix, or
    # "City, ST" without ZIP (common on small association/org footers).
    address = ""
    _addr_pats = [
        re.compile(r"\b(PO Box|P\.O\. Box)\b", re.IGNORECASE),
        re.compile(r"\b[A-Z]{2}\s*\d{5}\b"),
        re.compile(
            r"\b\d+\s+\w[\w\s]*"
            r"(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Ln|Way|Blvd|Boulevard|"
            r"Highway|Hwy|County Road|CR|Rural Route|RR|Place|Pl|Court|Ct|Trail|Trl)\b",
            re.IGNORECASE,
        ),
        re.compile(r",\s*[A-Za-z]{2}\s*\d{5}"),          # ", MN 55734"
        re.compile(r",\s*[A-Za-z][a-z]+,?\s+[A-Z]{2}\b"),    # ", Elgin, MN" or ", Elgin MN"
    ]
    for el in footer.find_all(["p", "li", "div", "address", "span"]):
        t = _clean(el.get_text(" "))
        if not t or len(t) > 250:
            continue
        if any(p.search(t) for p in _addr_pats):
            address = t
            break

    # Copyright
    copyright_line = ""
    full_text = _clean(footer.get_text(" "))
    m = re.search(r"(?:©|\(c\)|copyright)[^|]{0,180}", full_text, re.IGNORECASE)
    if m:
        copyright_line = m.group(0).strip(" -|").strip()
        # Trim web-builder credit tail ("| Websites By: prime42")
        copyright_line = re.split(r"\s*\|\s*", copyright_line)[0].strip()

    # Membership / Join CTA — many association sites surface a prominent
    # "Become a member" call in the footer. Capture it conservatively so we
    # only fire when both a membership headline AND an action verb are present.
    # When multiple candidates exist (e.g. "Join Today!" + "Renew Membership"),
    # pick the strongest acquisition CTA — JOIN beats RENEW every time.
    membership: Optional[Dict[str, str]] = None
    cta_verb = re.compile(
        r"\b(join|become|sign\s*up|subscribe|register|enroll|renew)\b",
        re.IGNORECASE,
    )
    membership_topic = re.compile(
        r"\b(member(s|ship)?|donor|supporter|subscriber)\b",
        re.IGNORECASE,
    )
    # Higher score = better CTA. New-member acquisition wins over renewals.
    def _membership_score(text: str, href: str) -> int:
        t = (text or "").lower()
        h = (href or "").lower()
        score = 0
        if re.search(r"\bjoin\b", t):           score += 100
        if "join" in h:                          score += 40
        if re.search(r"\bbecome\b", t):          score += 80
        if re.search(r"\bsign\s*up\b", t):       score += 70
        if re.search(r"\bregister\b", t):        score += 60
        if re.search(r"\benroll\b", t):          score += 60
        if re.search(r"\bsubscribe\b", t):       score += 40
        if re.search(r"\brenew\b", t):           score += 10  # weakest — existing members only
        if "today" in t or "now" in t:           score += 5
        return score

    candidates: List[Tuple[int, str, str]] = []
    for a in footer.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = _clean(a.get_text())
        if not href or not text or len(text) > 60:
            continue
        if href.lower().startswith(("mailto:", "tel:", "javascript:")) or href == "#":
            continue
        link_topical = bool(membership_topic.search(text)) or "member" in href.lower()
        link_action  = bool(cta_verb.search(text))
        context = ""
        node = a.parent
        for _ in range(3):
            if node is None:
                break
            context += " " + (node.get_text(" ") or "")
            node = getattr(node, "parent", None)
        ctx_topical = bool(membership_topic.search(context))
        ctx_action  = bool(cta_verb.search(context))
        if (link_action and (link_topical or ctx_topical)) or \
           (link_topical and ctx_action):
            score = _membership_score(text, href)
            if score > 0:
                candidates.append((score, text, href))

    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        _score, best_text, best_href = candidates[0]
        title = ""
        for h in footer.find_all(["h2", "h3", "h4", "h5", "h6"]):
            ht = _clean(h.get_text())
            if ht and membership_topic.search(ht) and len(ht) <= 60:
                title = ht
                break
        membership = {
            "title": title or "Membership",
            "label": best_text,
            "href":  best_href,
        }

    return {
        "emails":      emails,
        "phones":      phones,
        "social":      social,
        "links":       other_links,
        "address":     address,
        "copyright":   copyright_line,
        "membership":  membership or {},
        "text":        full_text[:2000],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Platform-aware field extraction + learning write-back
# ─────────────────────────────────────────────────────────────────────────────

FIELD_PROBES = [
    # (field_name, transform_result_to_sample)
    "hero_headline",
    "hero_image",
    "logo",
    "nav_links",
    "cta_button",
    "content_main",
    "blog_posts_list",
    "product_cards",
]


# Heuristic fallback selectors — tried in order when all learned patterns miss.
# If one matches, we grab the value AND register it as a new pattern for this
# platform so future scrapes of the same platform skip straight to it.
_HEURISTIC_SELECTORS: Dict[str, List[str]] = {
    "hero_headline":   ["main h1", "h1", "section:first-of-type h1", "header h1"],
    "hero_image":      ["main img", "section:first-of-type img", "header img", "img"],
    "logo":            ["a[href='/'] img", "header a img", ".logo img", "[class*='logo'] img"],
    "nav_links":       ["header nav a", "nav a[href]", "header a[href]", "[role='navigation'] a"],
    "cta_button":      ["a.button", "a.btn", "button.primary", "a[class*='cta']", "a[class*='button']"],
    "content_main":    ["main", "article", "[role='main']", "#main", "#content"],
    "blog_posts_list": ["article", "[class*='post']", "[class*='blog'] article", "main article"],
    "product_cards":   ["[class*='product']", "[class*='card']", "li.product", "[data-product-id]"],
}


# ── Gemini-assisted last-resort selector discovery ──
# Triggers only when learned patterns AND hardcoded heuristics both miss.
# One call handles all still-missing fields so we pay the latency/token cost once.
GEMINI_FALLBACK_MODEL = os.getenv("LAVENDIR_GEMINI_MODEL", "gemini-2.5-flash")

# Per-host cooldown so repeated scrapes of the same site don't re-pay the ~15s
# Gemini call when heuristics + learned patterns are still short.
_GEMINI_COOLDOWN_SEC = int(os.getenv("LAVENDIR_GEMINI_COOLDOWN_SEC", str(15 * 60)))
_GEMINI_COOLDOWN_PREFIX = "scraperkb:gemini-cooldown:"
_GEMINI_COOLDOWN_LOCAL: Dict[str, float] = {}


def _gemini_cooldown_redis():
    try:
        from saige.redis_client import get_redis_client
        return get_redis_client(decode_responses=True)
    except Exception:
        return None


def _host_of(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        h = (urlparse(url).netloc or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _gemini_cooldown_active(host: str) -> bool:
    if not host:
        return False
    client = _gemini_cooldown_redis()
    if client is not None:
        try:
            return bool(client.get(_GEMINI_COOLDOWN_PREFIX + host))
        except Exception:
            pass
    exp = _GEMINI_COOLDOWN_LOCAL.get(host, 0.0)
    return exp > time.time()


def _gemini_cooldown_mark(host: str) -> None:
    if not host:
        return
    client = _gemini_cooldown_redis()
    if client is not None:
        try:
            client.setex(_GEMINI_COOLDOWN_PREFIX + host, _GEMINI_COOLDOWN_SEC, "1")
            return
        except Exception:
            pass
    _GEMINI_COOLDOWN_LOCAL[host] = time.time() + _GEMINI_COOLDOWN_SEC


_FIELD_DESCRIPTIONS = {
    "hero_headline":   "the main page headline (the largest, most prominent heading)",
    "hero_image":      "the main banner/hero image (the largest visually prominent image at the top)",
    "logo":            "the site logo image (usually in the top-left, often a link to '/')",
    "nav_links":       "the primary navigation menu anchor links",
    "cta_button":      "the primary call-to-action button/link (e.g., 'Shop now', 'Get started', 'Contact us')",
    "content_main":    "the main content container (usually <main>, <article>, or role='main')",
    "blog_posts_list": "the list of blog posts on a blog index page",
    "product_cards":   "repeated product cards on a shop/listing page",
}


async def _gemini_discover_selectors(html: str, missing_fields: List[str],
                                     source_url: Optional[str] = None) -> Dict[str, str]:
    """Ask Gemini for CSS selectors for the fields that neither learned patterns
    nor hardcoded heuristics could match. Returns {field: selector} — missing or
    unparseable fields are simply absent. Fails closed on any error."""
    if not missing_fields:
        return {}
    host = _host_of(source_url)
    if _gemini_cooldown_active(host):
        print(f"[lavendir_scraper] gemini cooldown active for {host} — skipping")
        return {}
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {}
    try:
        import google.generativeai as genai
    except Exception:
        return {}
    # Mark cooldown up-front so concurrent scrapes of the same host don't stampede.
    _gemini_cooldown_mark(host)

    # Trim HTML to keep tokens sane. Prefer <body> contents; fall back to first N chars.
    snippet = html or ""
    m = re.search(r"<body\b[^>]*>([\s\S]*)</body>", snippet, re.IGNORECASE)
    if m:
        snippet = m.group(1)
    snippet = snippet[:12000]

    field_lines = "\n".join(f"- {f}: {_FIELD_DESCRIPTIONS.get(f, f)}" for f in missing_fields)
    prompt = (
        "You are extracting CSS selectors from an HTML page.\n"
        "For each listed field, return a single CSS selector that uniquely identifies that element "
        "on the page, or null if the page has no such element.\n\n"
        f"Fields:\n{field_lines}\n\n"
        "HTML (truncated):\n"
        "```html\n"
        f"{snippet}\n"
        "```\n\n"
        "Return ONLY a JSON object mapping field name to selector (or null). No prose, no code fences."
    )

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=GEMINI_FALLBACK_MODEL,
            generation_config={"response_mime_type": "application/json"},
        )
        # Gemini SDK's generate_content is sync; run in a thread so we don't block the loop.
        # Hard-cap at 15s — if Gemini is slow, scrape still returns with heuristic results.
        resp = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, lambda: model.generate_content(prompt)),
            timeout=15.0,
        )
        text_out = (resp.text or "").strip()
        if not text_out:
            return {}
        data = json.loads(text_out)
        if not isinstance(data, dict):
            return {}
        out: Dict[str, str] = {}
        for f in missing_fields:
            v = data.get(f)
            if isinstance(v, str) and v.strip():
                out[f] = v.strip()
        return out
    except Exception as e:
        print(f"[lavendir_scraper] gemini selector fallback failed: {e}")
        return {}


def _extract_by_selector(soup: "BeautifulSoup", selector: str, field: str):
    """Run a selector and shape its output the same way the learned-pattern loop does.
    Returns (sample_str, structured_value) or (None, None) if nothing usable."""
    try:
        found = soup.select(selector)
    except Exception:
        return None, None
    if not found:
        return None, None
    if field in ("hero_image", "logo"):
        el = next((e for e in found if e.name == "img" or e.find("img")), None) or found[0]
        img = el if (el.name == "img") else el.find("img")
        src = img.get("src") if img else None
        if src:
            return src, src
        return None, None
    if field == "nav_links":
        vals = []
        for a in found[:14]:
            t = _clean(a.get_text())
            href = a.get("href", "")
            if t and href:
                vals.append({"text": t[:80], "href": href})
        if vals:
            return ", ".join(v["text"] for v in vals[:6]), vals
        return None, None
    text_val = _clean(found[0].get_text())
    if text_val:
        return text_val[:400], text_val
    return None, None


async def _probe_fields(soup: "BeautifulSoup", platform_key: str, source_url: str,
                        raw_html: Optional[str] = None) -> Dict[str, Any]:
    """For each field we care about, try learned selectors in order.
    Record success on the first one that yields a value; record failure for ones that didn't.
    After learned + heuristic passes, Gemini is asked once for any still-missing fields."""
    out: Dict[str, Any] = {}
    missing_fields: List[str] = []
    patterns_by_field = await lookup_patterns_bulk(platform_key, FIELD_PROBES)
    for field in FIELD_PROBES:
        patterns = patterns_by_field.get(field) or []
        winner = None
        first_sample = None
        tried: List[str] = []
        for p in patterns:
            sel = p.get("SelectorValue")
            if not sel:
                continue
            tried.append(sel)
            try:
                found = soup.select(sel)
            except Exception:
                # malformed selector — record once as failure so it falls in the rankings
                _fire(record_failure(platform_key, field, sel, source_url))
                continue
            if not found:
                continue
            # Shape the sample based on field
            if field in ("hero_image", "logo"):
                el = next((e for e in found if e.name == "img" or e.find("img")), None) or found[0]
                img = el if (el.name == "img") else el.find("img")
                if img and img.get("src"):
                    winner = sel
                    first_sample = img.get("src")
                    out[field] = {"selector": sel, "value": first_sample}
                    break
            elif field == "nav_links":
                vals = []
                for a in found[:14]:
                    t = _clean(a.get_text())
                    href = a.get("href", "")
                    if t and href:
                        vals.append({"text": t[:80], "href": href})
                if vals:
                    winner = sel
                    first_sample = ", ".join(v["text"] for v in vals[:6])
                    out[field] = {"selector": sel, "value": vals}
                    break
            else:
                text_val = _clean(found[0].get_text())
                if text_val:
                    winner = sel
                    first_sample = text_val[:400]
                    out[field] = {"selector": sel, "value": text_val}
                    break

        # Heuristic fallback — if no learned pattern matched, try generic selectors.
        # First hit gets recorded as a new_pattern so the flywheel grows for this platform.
        if winner is None:
            for sel in _HEURISTIC_SELECTORS.get(field, []):
                if sel in tried:
                    continue  # already scored as a failure above
                sample, value = _extract_by_selector(soup, sel, field)
                if value is None:
                    continue
                winner = sel
                first_sample = sample
                out[field] = {"selector": sel, "value": value, "source": "heuristic"}
                _fire(record_new_pattern(platform_key, field, sel, source_url, first_sample or ""))
                break

        # Write-back (fire-and-forget so probe loop doesn't block on network I/O):
        # winner gets a success; every other selector tried gets a failure.
        for sel in tried:
            if sel == winner:
                _fire(record_success(platform_key, field, sel, source_url, first_sample or ""))
            else:
                _fire(record_failure(platform_key, field, sel, source_url))

        if winner is None:
            missing_fields.append(field)

    # ── Gemini last-resort: one call for all still-missing fields ──
    if missing_fields and raw_html:
        suggestions = await _gemini_discover_selectors(raw_html, missing_fields, source_url=source_url)
        for field, sel in suggestions.items():
            sample, value = _extract_by_selector(soup, sel, field)
            if value is None:
                continue
            out[field] = {"selector": sel, "value": value, "source": "gemini"}
            _fire(record_new_pattern(platform_key, field, sel, source_url, sample or ""))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Optional Playwright layer
# ─────────────────────────────────────────────────────────────────────────────

def _looks_bot_blocked(html: str, status_code: int = 200) -> bool:
    """Heuristic check whether a fetched page is a bot-challenge / block page."""
    if status_code in (403, 429, 503):
        return True
    if not html:
        return False
    head = html[:6000].lower()
    if len(html) < 1200 and any(sig in head for sig in BOT_SIGNALS):
        return True
    # Common challenge markers that appear even when the body is nonzero
    for marker in (
        "just a moment", "checking your browser", "enable javascript",
        "ray id:", "cf-chl", "cloudflare-static", "please verify you are human",
        "access denied", "ddos-guard", "perimeterx",
    ):
        if marker in head:
            return True
    return False


async def _fetch_html_via_playwright(url: str, timeout_ms: int = 25000) -> Optional[str]:
    """Fetch fully-rendered HTML via Playwright. Returns None if unavailable or blocked."""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=UA,
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await page.wait_for_timeout(2500)
                except Exception:
                    await browser.close()
                    return None
            title = (await page.title() or "").lower()
            if any(sig in title for sig in BOT_SIGNALS):
                await browser.close()
                return None
            html = await page.content()
            await browser.close()
            return html
    except Exception:
        return None


async def _fetch_pages_content_playwright(
    urls: List[str],
    *,
    concurrency: int = 3,
    timeout_ms: int = 20000,
) -> Dict[str, Dict[str, Any]]:
    """Render each URL with Playwright and run `_extract_content` on the rendered
    HTML. Used as a fallback for pages where httpx-only extraction returned an
    empty body (Elementor/Divi/React pages that paint content client-side).

    Shares a single browser instance across pages for speed, but limits page-
    level concurrency with a semaphore so we don't overwhelm the target host.
    Returns {url: {"headings": [...], "bodies": [...], "images": [...], "links": [...]}}
    for every URL that rendered successfully. Failed URLs are omitted."""
    if not PLAYWRIGHT_AVAILABLE or not urls:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    sem = asyncio.Semaphore(max(1, concurrency))

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=UA,
            )

            async def _one(u: str):
                async with sem:
                    page = None
                    try:
                        page = await context.new_page()
                        try:
                            await page.goto(u, wait_until="networkidle", timeout=timeout_ms)
                        except Exception:
                            try:
                                await page.goto(u, wait_until="domcontentloaded", timeout=timeout_ms)
                                await page.wait_for_timeout(1500)
                            except Exception:
                                return
                        title = (await page.title() or "").lower()
                        if any(sig in title for sig in BOT_SIGNALS):
                            return
                        html = await page.content()
                        if not html:
                            return
                        soup = BeautifulSoup(html, "html.parser")
                        content = _extract_content(soup, u)
                        banner = _extract_page_banner(soup, u)
                        out[u] = {
                            "headings":         content.get("headings") or [],
                            "bodies":           content.get("bodyText") or [],
                            "bodies_html":      content.get("bodyHtml") or [],
                            "body_ordered":     content.get("bodyOrdered") or "",
                            "images":           content.get("images") or [],
                            "links":            content.get("links") or [],
                            "banner":           banner or {},
                            "meta_title":       content.get("pageTitle") or "",
                            "meta_description": content.get("metaDescription") or "",
                            "og_image":         content.get("ogImage") or "",
                            "faq_items":        _extract_faq(soup),
                            "map_embed":        _extract_map_embed(soup),
                            "hours_rows":       _extract_hours(soup),
                            "team_members":     _extract_team_members(soup, u),
                            "pricing_table":    _extract_pricing_table(soup),
                            "page_cta":         _extract_page_cta(soup, u),
                        }
                    except Exception:
                        return
                    finally:
                        if page is not None:
                            try:
                                await page.close()
                            except Exception:
                                pass

            await asyncio.gather(*[_one(u) for u in urls])
            await browser.close()
    except Exception as e:
        print(f"[lavendir_scraper] _fetch_pages_content_playwright error: {e}")
    return out


async def _capture_page_styles(url: str, timeout_ms: int = 25000) -> Dict[str, Any]:
    """Run Playwright (if available) to get computed styles + spatial content + screenshot.
    Returns empty dict if Playwright is not installed or the site bot-blocks us."""
    if not PLAYWRIGHT_AVAILABLE:
        return {"available": False}
    result: Dict[str, Any] = {"available": True, "botBlocked": False}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=UA,
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await page.wait_for_timeout(2500)
                except Exception as e:
                    await browser.close()
                    return {"available": True, "error": str(e)}

            title = (await page.title() or "").lower()
            if any(sig in title for sig in BOT_SIGNALS):
                await browser.close()
                return {"available": True, "botBlocked": True}

            styles = await page.evaluate("""() => {
                function rgb2hex(rgb, allowNearWhiteBlack) {
                  if (!rgb || rgb === 'rgba(0, 0, 0, 0)' || rgb === 'transparent') return null;
                  const m = rgb.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([0-9.]+))?/);
                  if (!m) return null;
                  const r = +m[1], g = +m[2], b = +m[3];
                  const a = m[4] === undefined ? 1 : parseFloat(m[4]);
                  if (a < 0.15) return null;
                  if (!allowNearWhiteBlack) {
                    if (r>240&&g>240&&b>240) return null;
                    if (r<15&&g<15&&b<15) return null;
                  }
                  return '#' + [r,g,b].map(x => x.toString(16).padStart(2,'0')).join('');
                }
                // Walk an element + its descendants to find the first non-transparent bg.
                function firstSolidBg(root){
                  if (!root) return null;
                  const stack = [root];
                  let guard = 0;
                  while (stack.length && guard < 400) {
                    guard++;
                    const el = stack.shift();
                    const cs = getComputedStyle(el);
                    const h = rgb2hex(cs.backgroundColor, false);
                    if (h) return h;
                    // Also consider background-image gradients → pluck first color stop
                    const bi = cs.backgroundImage || '';
                    const gm = bi.match(/rgba?\\([^)]+\\)/);
                    if (gm) { const gh = rgb2hex(gm[0], false); if (gh) return gh; }
                    for (const c of el.children) stack.push(c);
                  }
                  return null;
                }
                function bg(sels, descend){
                  for (const s of sels){
                    try{
                      const el=document.querySelector(s);
                      if(!el) continue;
                      const self = rgb2hex(getComputedStyle(el).backgroundColor, false);
                      if (self) return self;
                      if (descend) {
                        const nested = firstSolidBg(el);
                        if (nested) return nested;
                      }
                    }catch{}
                  }
                  return null;
                }
                function col(sels){for (const s of sels){try{const el=document.querySelector(s);if(!el) continue;const h=rgb2hex(getComputedStyle(el).color, true);if(h) return h;}catch{}}return null;}
                // Fallback: scan all elements in the top 400px, pick the widest
                // element whose computed bg is solid and whose area is largest.
                function topBannerBg(){
                  const candidates = [];
                  document.querySelectorAll('*').forEach(el=>{
                    try{
                      const r = el.getBoundingClientRect();
                      if (r.top > 400 || r.bottom < 0) return;
                      if (r.width < 400 || r.height < 20) return;
                      const cs = getComputedStyle(el);
                      const h = rgb2hex(cs.backgroundColor, false);
                      if (!h) return;
                      candidates.push({h, area: r.width * Math.min(r.height, 200), top: r.top});
                    }catch{}
                  });
                  if (!candidates.length) return null;
                  candidates.sort((a,b)=>b.area-a.area);
                  return candidates[0].h;
                }
                // Probe nav menu link typography from the live computed
                // styles. Walks several common nav selectors, returns the
                // first that yields a real anchor with text content.
                function navAnchorTypo(){
                  const selectors = [
                    'header nav a','nav.primary a','nav.main a','nav.menu a',
                    '.navbar a','.main-navigation a','.primary-menu a',
                    '#menu a','#nav a','nav a','header a'
                  ];
                  for (const s of selectors) {
                    try {
                      const els = document.querySelectorAll(s);
                      for (const el of els) {
                        const txt = (el.innerText||'').trim();
                        if (!txt || txt.length > 40) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 8 || r.height < 8) continue;  // skip hidden
                        if (r.top > 600) continue;  // must be near top of page
                        const cs = getComputedStyle(el);
                        const w = cs.fontWeight;
                        if (!w) continue;
                        return {
                          fontWeight: w,
                          textTransform: cs.textTransform || '',
                          letterSpacing: cs.letterSpacing || '',
                          fontSize: cs.fontSize || ''
                        };
                      }
                    } catch {}
                  }
                  return null;
                }
                return {
                  navBgColor:   bg(['nav','header','#header','#nav','.navbar','.nav','.site-header','.top-nav','[role=\"navigation\"]'], true) || topBannerBg(),
                  pageBgColor:  bg(['html','body','#wrapper','#page','.site-body','#container'], false),
                  accentColor:  bg(['a.button','button[type=\"submit\"]','.btn','.cta','input[type=\"submit\"]','.button'], true),
                  navTextColor: col(['nav a','header a','.navbar a','.nav a','#menu a']),
                  textColor:    col(['body','main p','.entry-content p','article p','p']),
                  linkColor:    col(['main a','.entry-content a','article a','a']),
                  navTypo:      navAnchorTypo()
                };
            }""")

            # Scroll for lazy loads
            await page.evaluate("""async () => {
                await new Promise(r => {
                  let d=0; const step=600; const max=Math.min(document.body.scrollHeight, 6000);
                  const t=setInterval(()=>{d+=step;window.scrollBy(0,step);if(d>=max){window.scrollTo(0,0);clearInterval(t);r();}},80);
                });
            }""")
            await page.wait_for_timeout(400)

            spatial = await page.evaluate("""() => {
                const items=[];
                document.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,td,th,figcaption,blockquote').forEach(el=>{
                  const t=(el.innerText||'').trim(); if(!t||t.length<20) return;
                  const r=el.getBoundingClientRect();
                  if (r.width<10||r.height<2) return;
                  const y=Math.round(r.top+window.scrollY); if (y>8000) return;
                  items.push({tag:el.tagName.toLowerCase(), text:t.substring(0,500), x:Math.round(r.left), y});
                });
                items.sort((a,b)=>a.y-b.y||a.x-b.x);
                const seen=new Set();
                return items.filter(i=>{if(seen.has(i.text)) return false; seen.add(i.text); return true;}).slice(0,200);
            }""")

            shot = await page.screenshot(type="jpeg", quality=60, clip={"x":0,"y":0,"width":1280,"height":900})
            import base64
            b64 = base64.b64encode(shot).decode("ascii")
            if len(b64) >= 400_000:
                b64 = ""
            await browser.close()
            result.update({"styles": styles, "spatialContent": spatial, "screenshotB64": b64})
    except Exception as e:
        result["error"] = str(e)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Sitemap discovery
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_sitemap_urls(base_url: str, *, timeout: float = 8.0) -> List[str]:
    """Discover all page URLs for a site via its XML sitemap(s).

    Tries common sitemap paths in order.  Handles both plain ``<urlset>``
    sitemaps and ``<sitemapindex>`` files (one level of nesting).  Returns
    only URLs on the same origin, excluding media and WP infrastructure paths.
    """
    from urllib.parse import urlparse as _urlparse
    from xml.etree import ElementTree as ET

    _parsed = _urlparse(base_url)
    origin = f"{_parsed.scheme}://{_parsed.netloc}"

    _SITEMAP_CANDIDATES = [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/wp-sitemap.xml",
        "/page-sitemap.xml",
        "/post-sitemap.xml",
        "/sitemap/sitemap.xml",
    ]
    _NS_RE = re.compile(r"\{[^}]*\}")
    _SKIP_KEYS = (
        "/wp-content/", "/wp-includes/", "?attachment_id=",
        "/feed/", "/tag/", "/author/",
    )
    _MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
                   ".pdf", ".mp4", ".mp3", ".zip")

    def _parse_xml(text: str):
        """Return (page_urls, child_sitemap_urls) from sitemap XML text."""
        pages: List[str] = []
        children: List[str] = []
        try:
            root_el = ET.fromstring(text)
        except ET.ParseError:
            return pages, children
        root_tag = _NS_RE.sub("", root_el.tag).lower()
        is_index = root_tag == "sitemapindex"
        for el in root_el.iter():
            tag = _NS_RE.sub("", el.tag).lower()
            if tag != "loc" or not el.text:
                continue
            loc = el.text.strip()
            if not loc:
                continue
            if is_index or loc.endswith(".xml"):
                children.append(loc)
            elif loc.startswith(origin):
                if not any(k in loc for k in _SKIP_KEYS):
                    if not any(loc.lower().endswith(ext) for ext in _MEDIA_EXTS):
                        pages.append(loc)
        return pages, children

    collected: List[str] = []
    seen: set = set()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": UA}) as client:
        # Phase 0: check robots.txt for explicit Sitemap: directives
        root_text = ""
        try:
            rb = await client.get(origin + "/robots.txt")
            if rb.status_code == 200:
                for line in rb.text.splitlines():
                    m = re.match(r"Sitemap\s*:\s*(.+)", line.strip(), re.IGNORECASE)
                    if not m:
                        continue
                    sm_url = m.group(1).strip()
                    if not sm_url:
                        continue
                    try:
                        rs = await client.get(sm_url)
                        if rs.status_code == 200 and (
                            "<loc>" in rs.text or "<urlset" in rs.text or "<sitemapindex" in rs.text
                        ):
                            root_text = rs.text
                            break
                    except Exception:
                        continue
        except Exception:
            pass

        # Phase 1: try each candidate path until one returns 200 XML
        if not root_text:
            for path in _SITEMAP_CANDIDATES:
                try:
                    r = await client.get(origin + path)
                    if r.status_code == 200 and ("<loc>" in r.text or "<urlset" in r.text or "<sitemapindex" in r.text):
                        root_text = r.text
                        break
                except Exception:
                    continue

        if not root_text:
            return []

        pages, children = _parse_xml(root_text)
        for p in pages:
            if p not in seen:
                seen.add(p)
                collected.append(p)

        # Phase 2: follow child sitemaps (one level deep)
        async def _fetch_child(url: str):
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
            return ""

        if children:
            child_texts = await asyncio.gather(*[_fetch_child(c) for c in children[:20]])
            for ct in child_texts:
                if not ct:
                    continue
                sub_pages, _ = _parse_xml(ct)
                for p in sub_pages:
                    if p not in seen:
                        seen.add(p)
                        collected.append(p)

    return collected


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

async def scrape(url: str, *, use_playwright: bool = False,
                 learn: bool = True, fetch_timeout: float = 20.0) -> Dict[str, Any]:
    """
    Fetch + parse + detect-platform + learning-aware field extraction.
    Returns a full payload compatible with Chearvil's /scrape response plus:
      - platform: {platform_key, platform_name, confidence, scores}
      - probed_fields: {field_name: {selector, value}}
      - capture:   optional Playwright results (styles/spatial/screenshot)
    """
    if not BS4_AVAILABLE:
        return {"error": "beautifulsoup4 is not installed. Run: pip install beautifulsoup4"}

    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url.strip()

    t0 = time.time()
    bot_blocked = False
    fetch_method = "httpx"
    # ── Fetch ──
    try:
        async with httpx.AsyncClient(timeout=fetch_timeout, follow_redirects=True,
                                     headers={"User-Agent": UA}) as client:
            resp = await client.get(url)
            status_code = resp.status_code
            html = resp.text if status_code < 400 else ""
    except httpx.RequestError as e:
        status_code, html = 0, ""
        print(f"[lavendir_scraper] httpx fetch error: {type(e).__name__}: {e}")
    except Exception as e:
        status_code, html = 0, ""
        print(f"[lavendir_scraper] httpx fetch exception: {e}")

    # ── Auto Playwright fallback if the site looks bot-blocked ──
    if _looks_bot_blocked(html, status_code):
        bot_blocked = True
        if PLAYWRIGHT_AVAILABLE:
            rendered = await _fetch_html_via_playwright(url)
            if rendered:
                html = rendered
                status_code = 200
                fetch_method = "playwright-fallback"

    if not html:
        if status_code >= 400:
            return {"error": f"Target site returned HTTP {status_code}.", "status": status_code,
                    "bot_blocked": bot_blocked}
        return {"error": f"Could not reach {url}.", "bot_blocked": bot_blocked}

    # ── SPA shell fallback: static HTML parsed but has almost no body content.
    # Covers React/Next/Vue/Angular sites where the initial HTML is just a
    # <div id="root"></div> and all text/images are painted by JS.
    if PLAYWRIGHT_AVAILABLE and fetch_method == "httpx":
        probe_soup = BeautifulSoup(html, "html.parser")
        for tag in probe_soup(["script", "style", "noscript"]):
            tag.decompose()
        visible_text = _clean(probe_soup.get_text(" "))
        headings_ct = len(probe_soup.find_all(["h1", "h2", "h3"]))
        imgs_ct = len(probe_soup.find_all("img"))
        if headings_ct == 0 and imgs_ct == 0 and len(visible_text) < 400:
            rendered = await _fetch_html_via_playwright(url)
            if rendered and len(rendered) > len(html):
                html = rendered
                fetch_method = "playwright-spa"

    soup = BeautifulSoup(html, "html.parser")

    # ── Detect platform + load known patterns ──
    platform = await detect_platform(html, url=url) if learn else {"platform_key": "_generic"}
    platform_key = platform.get("platform_key") or "_generic"

    # ── Fetch external stylesheets so design-token analysis sees CSS that WP/
    # theme-based sites keep in separate files. Inject as inline <style> blocks
    # before token extraction. Capped to keep scrapes fast.
    try:
        stylesheet_hrefs: List[str] = []
        for link in soup.find_all("link", rel=True):
            rel = " ".join(link.get("rel") or []).lower()
            if "stylesheet" not in rel:
                continue
            href = link.get("href") or ""
            if not href:
                continue
            stylesheet_hrefs.append(_resolve(url, href))
            if len(stylesheet_hrefs) >= 8:
                break
        if stylesheet_hrefs:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True,
                                         headers={"User-Agent": UA}) as css_client:
                async def _fetch_one(h):
                    try:
                        r = await css_client.get(h)
                        return r.text if r.status_code < 400 else ""
                    except Exception:
                        return ""
                css_texts = await asyncio.gather(*[_fetch_one(h) for h in stylesheet_hrefs])
            merged_css = "\n".join(t for t in css_texts if t)
            if merged_css:
                synthetic = soup.new_tag("style")
                synthetic.string = merged_css
                (soup.head or soup).append(synthetic)
    except Exception as _css_ex:
        print(f"[lavendir_scraper] external css fetch skipped: {_css_ex}")

    # ── Extract design DNA BEFORE we strip <style> tags ──
    design_tokens  = _extract_design_tokens(soup)
    # Footer-specific background overrides: `_extract_design_tokens` falls back
    # to the nav color, which is wrong when the footer has its own image/color.
    footer_bg = _extract_footer_bg(soup, url)
    if footer_bg.get("footerBgColor"):
        design_tokens["footerBgColor"] = footer_bg["footerBgColor"]
    if footer_bg.get("footerBgImage"):
        design_tokens["footerBgImage"] = footer_bg["footerBgImage"]
    layout_patterns = _detect_layout_patterns(soup)
    nav_tree       = _extract_nav_tree(soup, url)

    # ── Page discovery: sitemap + full internal-link crawl ──────────────────
    # Build a deduplicated list of all same-origin page URLs so that the
    # import pipeline can create and populate pages beyond the visible nav.
    _pd_seen: set = set()
    _pd_urls: List[str] = []

    def _pd_add(u: str) -> None:
        u = (u or "").split("#")[0].rstrip("/")
        if u and u not in _pd_seen:
            _pd_seen.add(u)
            _pd_urls.append(u)

    # 1. URLs explicitly listed in the nav tree (walk full tree)
    def _walk_nav(items):
        for item in items:
            if item.get("href"):
                _pd_add(item["href"])
            for child in (item.get("children") or []):
                if child.get("href"):
                    _pd_add(child["href"])
                for gc in (child.get("children") or []):
                    if gc.get("href"):
                        _pd_add(gc["href"])
    _walk_nav(nav_tree)

    # 2. Every <a href> on the homepage pointing to the same domain
    for _il in _collect_internal_links(soup, url):
        _pd_add(_il)

    # 3. Sitemap XML (the most comprehensive source when available)
    try:
        for _su in await _fetch_sitemap_urls(url):
            _pd_add(_su)
    except Exception as _sm_ex:
        print(f"[lavendir_scraper] sitemap fetch skipped: {_sm_ex}")

    # 4. 2nd-level crawl: fetch top nav pages and harvest their internal links.
    # Catches subpages/blog posts that aren't linked from the homepage but appear
    # in the body of a parent page (e.g., "Blog" → individual post links).
    # Capped to 12 nav pages and uses a short timeout to keep scrapes fast.
    _nav_top_hrefs = [
        item["href"] for item in nav_tree
        if item.get("href") and item["href"] not in _pd_seen
    ][:12]
    if _nav_top_hrefs:
        try:
            async with httpx.AsyncClient(
                timeout=7.0, follow_redirects=True,
                headers={"User-Agent": UA},
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            ) as _2l_client:
                _2l_sem = asyncio.Semaphore(6)

                async def _fetch_2l(sub_url: str) -> List[str]:
                    async with _2l_sem:
                        try:
                            r2 = await _2l_client.get(sub_url)
                            if r2.status_code < 400 and r2.text:
                                sub_soup = BeautifulSoup(r2.text, "html.parser")
                                return _collect_internal_links(sub_soup, sub_url)
                        except Exception:
                            pass
                        return []

                _2l_batches = await asyncio.gather(*[_fetch_2l(h) for h in _nav_top_hrefs])
                for _2l_links in _2l_batches:
                    for _2l_link in _2l_links:
                        _pd_add(_2l_link)
        except Exception as _2l_ex:
            print(f"[lavendir_scraper] 2nd-level crawl skipped: {_2l_ex}")

    print(f"[lavendir_scraper] page discovery: {len(_pd_urls)} unique page URLs found")

    slideshow_urls = _extract_slideshow_images(soup, url)
    hero_image_url = _extract_hero_image_url(soup, url)
    logo_url       = _extract_logo_url(soup, url)
    # The same banner-section logic used for interior pages — when the
    # homepage has a styled hero section (CSS background-image on a
    # specific Elementor/Divi/etc. wrapper), this gives a more accurate
    # hero than `_extract_hero_image_url` which just hunts for big <img>s.
    homepage_banner = _extract_page_banner(soup, url) or {}

    # ── Platform-aware field probing (learning flywheel) ──
    probed: Dict[str, Any] = {}
    if learn:
        try:
            probed = await _probe_fields(soup, platform_key, url, raw_html=html)
        except Exception as e:
            print(f"[lavendir_scraper] probe error: {e}")

    # ── Core content extraction (uses a fresh soup because we're about to strip tags) ──
    # Re-parse so the structural tags are back for content extraction paths
    soup_for_content = BeautifulSoup(html, "html.parser")
    content = _extract_content(soup_for_content, url)
    # Extract the source <footer> from raw HTML (before any decomposition).
    footer_data = _extract_footer(html, url)
    # Sponsors / partners section (logo grid). Parse a FRESH soup — the
    # `soup_for_content` instance has been mutated by `_extract_content`
    # (which decomposes nav/header/footer/menu/social wrappers, often taking
    # the sponsor section with them on Elementor sites).
    try:
        sponsors_soup = BeautifulSoup(html, "html.parser")
        sponsors_data = _extract_sponsors(sponsors_soup, url)
    except Exception as _sp_ex:
        print(f"[lavendir_scraper] sponsors extract skipped: {_sp_ex}")
        sponsors_data = []
    # CTA banners — same fresh-soup reasoning as sponsors above.
    try:
        ctas_soup = BeautifulSoup(html, "html.parser")
        ctas_data = _extract_ctas(ctas_soup, url)
    except Exception as _cta_ex:
        print(f"[lavendir_scraper] ctas extract skipped: {_cta_ex}")
        ctas_data = []

    # Social links — scan all anchors for known social-platform domains.
    try:
        social_links = _extract_social_links(soup)
    except Exception as _sl_ex:
        print(f"[lavendir_scraper] social links extract skipped: {_sl_ex}")
        social_links = {}

    # Testimonials — detect blockquote/card patterns with author attribution.
    try:
        testimonials_data = _extract_testimonials(soup)
    except Exception as _tst_ex:
        print(f"[lavendir_scraper] testimonials extract skipped: {_tst_ex}")
        testimonials_data = []

    # Features/services grid — detect repeated icon-box card patterns.
    try:
        features_data = _extract_features_grid(soup)
    except Exception as _feat_ex:
        print(f"[lavendir_scraper] features grid extract skipped: {_feat_ex}")
        features_data = []

    # ── Optional Playwright layer ──
    capture: Dict[str, Any] = {"available": False}
    nav_typo: Dict[str, str] = {}
    if use_playwright:
        capture = await _capture_page_styles(url)
        # Playwright styles are authoritative — overlay them on design_tokens
        ps_styles = capture.get("styles") or {}
        for k in ("navBgColor", "pageBgColor", "accentColor", "navTextColor", "textColor", "linkColor"):
            if ps_styles.get(k):
                design_tokens[k] = ps_styles[k]
        # Nav menu typography (font weight, text-transform, etc.) from computed styles
        if isinstance(ps_styles.get("navTypo"), dict):
            nav_typo = {k: str(v) for k, v in ps_styles["navTypo"].items() if v}
    # Fallback: CSS regex over the merged stylesheets we already inlined.
    # Looks for `nav a { ... font-weight: 700 ... }` patterns. Generic enough
    # to catch most theme-based sites even without Playwright.
    if not nav_typo.get("fontWeight"):
        try:
            css_blob = ""
            for st in soup.find_all("style"):
                if st.string:
                    css_blob += st.string + "\n"
                if len(css_blob) > 600_000:
                    break
            # Match rules whose selector touches a nav anchor and whose body
            # declares a font-weight value.
            for m in re.finditer(
                r"(?P<sel>[^{}]+?)\{(?P<body>[^{}]*?font-weight\s*:\s*(?P<w>[0-9]{3}|bold|normal)[^{}]*?)\}",
                css_blob,
                re.IGNORECASE,
            ):
                sel = m.group("sel").lower()
                if not re.search(r"(^|[\s,>+~]|^)(nav|header)\b[^,{}]*\ba\b", sel):
                    continue
                w = m.group("w").lower()
                if w == "bold":
                    w = "700"
                elif w == "normal":
                    w = "400"
                nav_typo["fontWeight"] = w
                break
        except Exception as _navw_ex:
            print(f"[lavendir_scraper] nav font-weight CSS scan skipped: {_navw_ex}")

    return {
        "url":             url,
        "elapsed_ms":      int((time.time() - t0) * 1000),
        "platform":        platform,
        "designTokens":    design_tokens,
        "layoutPatterns":  layout_patterns,
        "navTree":         nav_tree,
        "allPageUrls":     _pd_urls,
        "heroImageUrl":    hero_image_url or "",
        "homepageBanner":  homepage_banner,
        "slideshowImages": slideshow_urls,
        "logoUrl":         logo_url or "",
        "footer":          footer_data or {},
        "sponsors":        sponsors_data or [],
        "ctas":            ctas_data or [],
        "socialLinks":     social_links or {},
        "testimonials":    testimonials_data or [],
        "featuresGrid":    features_data or [],
        "navTypo":         nav_typo,
        "probed_fields":   probed,
        "capture":         capture,
        "fetch_method":    fetch_method,
        "bot_blocked":     bot_blocked,
        **content,
        "stats": {
            "headings":   len(content["headings"]),
            "paragraphs": len(content["bodyText"]),
            "images":     len(content["images"]),
            "links":      len(content["links"]),
        },
    }


# Convenience synchronous wrapper for callers outside an event loop
def scrape_sync(url: str, **kwargs: Any) -> Dict[str, Any]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Caller is already in a loop — they should await scrape() directly.
            raise RuntimeError("scrape_sync called from within a running event loop; use `await scrape(url)`")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(scrape(url, **kwargs))
