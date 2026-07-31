"""
Live frontend extraction: fetches real WordPress / PrestaShop (or any storefront)
pages over HTTP and converts their HTML into structured sections using
BeautifulSoup, classified by heuristics into hero / product info / CTA /
related products / testimonials / features blocks.

NEW in this version — theme token extraction:
  extract_theme_tokens() runs BEFORE the <style> decompose step so the
  colour palette, font families, CSS custom properties, real image URLs,
  and the theme's main stylesheet URL are captured and stored as a special
  section_type='theme_css' record. format_context() in ai_prompt.py reads
  this record and exposes it to the AI as "BRAND DESIGN TOKENS" so the
  generated page can reproduce the actual site look rather than inventing
  a completely different design.

Previous bug: <style> tags were stripped before anything was saved, and
format_context() only passed .text (plain text), never .html, so the model
had zero visual information to work from.
"""
import re
from collections import Counter
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import config
import db

SECTION_KEYWORDS = {
    "hero": ["hero", "banner", "jumbotron", "masthead", "intro-section"],
    "product_info": [
        "product-information", "product-info", "product-details",
        "product-description", "product-cover",
    ],
    "cta": ["cta", "call-to-action", "add-to-cart", "promo-block", "buy-now"],
    "related_products": [
        "related", "accessories", "cross-selling", "also-like", "featured-products",
        "product-miniature", "products-section",
    ],
    "testimonials": ["testimonial", "review", "rating-comment", "customer-quote"],
    "features": ["features", "specification", "product-features", "feature-list"],
}


def _classify(tag) -> str:
    classes = tag.get("class") or []
    tag_id = tag.get("id") or ""
    haystack = (" ".join(classes) + " " + tag_id).lower()
    for section_type, keywords in SECTION_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return section_type
    return "generic"


def _clean_font_name(raw: str) -> str:
    """Normalise a font-family token: strip quotes, take the first face name."""
    name = raw.strip().split(",")[0]
    name = name.strip().strip("'\"")
    return name


def fetch_html(url: str) -> str:
    headers = {"User-Agent": config.SCRAPER_USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_stylesheet_sample(url: str, max_bytes: int = 40_000) -> str:
    """
    Fetch up to `max_bytes` of a CSS stylesheet and return it as text.

    WordPress theme stylesheets can exceed 500 KB. We cap the fetch to keep
    the extracted token set manageable. The first 40 KB contains the vast
    majority of root/body/heading rules that define brand colours.
    """
    try:
        headers = {"User-Agent": config.SCRAPER_USER_AGENT, "Range": f"bytes=0-{max_bytes - 1}"}
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text[:max_bytes]
    except requests.RequestException:
        return ""


def extract_theme_tokens(raw_html: str, source_url: str) -> dict:
    """
    Extract visual design tokens from the raw HTML of a page BEFORE any
    <style> stripping.  Returns a dict containing:
      css_vars        — CSS custom property name → value (--color-primary etc.)
      top_colors      — hex colours ranked by frequency in inline CSS
      fonts           — font-family face names
      stylesheet_url  — URL of the main theme stylesheet (may be None)
      stylesheet_css  — first 40 KB of that stylesheet (may be empty)
      image_urls      — real image URLs found on the page (no SVG / spinners)
      inline_css      — full inline <style> text (up to 6 000 chars)
    """
    soup = BeautifulSoup(raw_html, "lxml")

    # ── 1. Collect ALL inline <style> content ────────────────────────────────
    inline_css = "\n".join(tag.get_text() for tag in soup.find_all("style"))

    # ── 2. CSS custom properties (--color-*, --font-*, --bg-* …) ─────────────
    var_pattern = re.compile(
        r"--(color|font|bg|background|text|primary|secondary|accent|dark|light"
        r"|brand|heading|link|button|main|body)[^:]*\s*:\s*([^;}{]+)",
        re.IGNORECASE,
    )
    css_vars = {}
    for match in var_pattern.finditer(inline_css):
        key = match.group(0).split(":")[0].strip()
        val = match.group(2).strip()
        css_vars[key] = val
    css_vars = dict(list(css_vars.items())[:20])

    # ── 3. Hex colour frequency ───────────────────────────────────────────────
    hex_pat = re.compile(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}(?=[^0-9a-fA-F]|$)")
    color_freq = Counter(c.lower() for c in hex_pat.findall(inline_css))
    top_colors = [c for c, _ in color_freq.most_common(10)]

    # ── 4. Font families ──────────────────────────────────────────────────────
    raw_fonts = re.findall(r"font-family\s*:\s*([^;}{]+)", inline_css, re.IGNORECASE)
    seen_fonts: dict = {}
    for rf in raw_fonts:
        name = _clean_font_name(rf)
        if name and name.lower() not in ("inherit", "initial", "unset", "sans-serif", "serif", "monospace"):
            seen_fonts[name.lower()] = name
    fonts = list(seen_fonts.values())[:6]

    # ── 5. Main theme stylesheet URL ──────────────────────────────────────────
    stylesheet_url = None
    all_sheets = [
        lnk.get("href", "")
        for lnk in soup.find_all("link", rel=lambda r: r and "stylesheet" in r)
        if lnk.get("href")
    ]
    # Prefer the WordPress theme stylesheet; skip plugin / block-library CSS
    for href in all_sheets:
        if "themes" in href and "plugins" not in href and "block-library" not in href:
            stylesheet_url = href
            break
    # Fallback: any non-plugin sheet
    if not stylesheet_url:
        for href in all_sheets:
            if "plugins" not in href and "block-library" not in href and href:
                stylesheet_url = href
                break

    # ── 6. Fetch theme stylesheet and extend colour/font extraction ───────────
    stylesheet_css = ""
    if stylesheet_url:
        stylesheet_css = fetch_stylesheet_sample(stylesheet_url)
        if stylesheet_css:
            # Augment top_colors with stylesheet values
            sheet_colors = Counter(c.lower() for c in hex_pat.findall(stylesheet_css))
            combined = color_freq + sheet_colors
            top_colors = [c for c, _ in combined.most_common(10)]
            # Augment fonts
            for rf in re.findall(r"font-family\s*:\s*([^;}{]+)", stylesheet_css, re.IGNORECASE):
                name = _clean_font_name(rf)
                if (name
                        and name.lower() not in ("inherit", "initial", "unset",
                                                  "sans-serif", "serif", "monospace")
                        and name.lower() not in seen_fonts):
                    seen_fonts[name.lower()] = name
            fonts = list(seen_fonts.values())[:6]
            # Augment CSS vars
            for match in var_pattern.finditer(stylesheet_css):
                key = match.group(0).split(":")[0].strip()
                if key not in css_vars:
                    val = match.group(2).strip()
                    css_vars[key] = val
            css_vars = dict(list(css_vars.items())[:20])

    # ── 7. Real image URLs (skip SVG icons, spinners, placeholder images) ─────
    image_urls = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if (src
                and not src.endswith(".svg")
                and "placeholder" not in src
                and "spinner" not in src.lower()
                and "icon" not in src.lower()
                and src not in image_urls):
            image_urls.append(src)
    image_urls = image_urls[:15]

    return {
        "css_vars": css_vars,
        "top_colors": top_colors,
        "fonts": fonts,
        "stylesheet_url": stylesheet_url,
        "stylesheet_css": stylesheet_css[:6000],   # cap context size
        "image_urls": image_urls,
        "inline_css": inline_css[:6000],
    }


def _tokens_to_text(tokens: dict) -> str:
    """Serialise theme tokens to a human-readable string for the DB text column."""
    lines = []
    if tokens["top_colors"]:
        lines.append("COLORS: " + ", ".join(tokens["top_colors"]))
    if tokens["fonts"]:
        lines.append("FONTS: " + ", ".join(tokens["fonts"]))
    if tokens["css_vars"]:
        lines.append("CSS VARS:")
        for k, v in tokens["css_vars"].items():
            lines.append(f"  {k}: {v}")
    if tokens["image_urls"]:
        lines.append("IMAGES:")
        for url in tokens["image_urls"]:
            lines.append(f"  {url}")
    if tokens["stylesheet_url"]:
        lines.append(f"THEME STYLESHEET: {tokens['stylesheet_url']}")
    return "\n".join(lines)


def _tokens_to_html(tokens: dict) -> str:
    """
    Store the combined raw CSS in the html column so format_context() can
    pass it directly to the model (up to 6 000 chars).
    """
    parts = []
    if tokens["inline_css"]:
        parts.append("/* === INLINE PAGE CSS === */\n" + tokens["inline_css"])
    if tokens["stylesheet_css"]:
        parts.append("/* === THEME STYLESHEET SAMPLE === */\n" + tokens["stylesheet_css"])
    combined = "\n\n".join(parts)
    return combined[:8000]


def extract_sections(raw_html: str, source_url: str) -> list:
    """
    Parse the raw HTML into a list of section records for the DB.

    IMPORTANT: theme token extraction happens BEFORE the <style> decompose so
    that colour/font information is captured first. Previously all <style> tags
    were destroyed before any data was saved, leaving the model with no visual
    information about the original site.
    """
    # ── Theme tokens (must happen before decompose) ───────────────────────────
    tokens = extract_theme_tokens(raw_html, source_url)
    theme_record = {
        "source_url": source_url,
        "section_type": "theme_css",
        "heading": "Brand design tokens",
        "html": _tokens_to_html(tokens),
        "text": _tokens_to_text(tokens),
    }

    # ── Section extraction ────────────────────────────────────────────────────
    soup = BeautifulSoup(raw_html, "lxml")
    # Now strip scripts / inline styles from the soup used for section text
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = soup.find_all(["section", "div", "header", "footer"])
    sections = []
    seen: set = set()

    for tag in candidates:
        marker = id(tag)
        if marker in seen:
            continue
        seen.add(marker)

        text = tag.get_text(separator=" ", strip=True)
        if len(text) < 20:
            continue

        section_type = _classify(tag)
        if section_type == "generic" and len(text) < 80:
            continue

        heading_tag = tag.find(["h1", "h2", "h3"])
        heading = heading_tag.get_text(strip=True) if heading_tag else ""

        sections.append(
            {
                "source_url": source_url,
                "section_type": section_type,
                "heading": heading,
                "html": str(tag)[:8000],
                "text": text[:2000],
            }
        )

    # Deduplicate nested containers
    deduped: dict = {}
    for s in sections:
        key = (s["section_type"], s["heading"], s["text"][:120])
        if key not in deduped or len(s["html"]) < len(deduped[key]["html"]):
            deduped[key] = s

    # theme_css record first so it gets top BM25 priority for visual queries
    return [theme_record] + list(deduped.values())


def ingest_url(url: str) -> int:
    raw_html = fetch_html(url)
    sections = extract_sections(raw_html, url)
    now = datetime.now(timezone.utc).isoformat()
    for s in sections:
        s["fetched_at"] = now
    db.replace_frontend_sections(url, sections)
    return len(sections)


def ingest_urls(urls: list) -> dict:
    summary = {}
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            summary[url] = ingest_url(url)
        except requests.RequestException as exc:
            summary[url] = f"error: {exc}"
    return summary