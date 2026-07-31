"""
WordPress ingestion via the real WordPress REST API (wp-json/wp/v2).

Supports any post type with a REST base (pages, posts, or a custom post
type like "case-studies") - configure WORDPRESS_POST_TYPES in .env.
Uses WordPress Application Passwords for auth if the site's content is
private; otherwise hits the public REST endpoints anonymously.
"""
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import config
import db


def _auth():
    if config.WORDPRESS_USERNAME and config.WORDPRESS_APP_PASSWORD:
        return (config.WORDPRESS_USERNAME, config.WORDPRESS_APP_PASSWORD)
    return None


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)


def fetch_post_type(post_type: str, per_page: int = 50):
    """Pull every item of a given REST post type, following WP's
    X-WP-TotalPages pagination header until exhausted."""
    if not config.WORDPRESS_BASE_URL:
        raise ValueError("WORDPRESS_BASE_URL is not configured in .env")

    endpoint = f"{config.WORDPRESS_BASE_URL}/wp-json/wp/v2/{post_type}"
    page = 1
    results = []

    while True:
        resp = requests.get(
            endpoint,
            params={"per_page": per_page, "page": page},
            auth=_auth(),
            timeout=config.REQUEST_TIMEOUT,
        )
        if resp.status_code == 400:
            # WordPress returns 400 (rest_post_invalid_page_number) once you
            # page past the last page - that's our natural stop condition.
            break
        resp.raise_for_status()

        batch = resp.json()
        if not batch:
            break
        results.extend(batch)

        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1

    return results


def ingest_post_type(post_type: str) -> int:
    items = fetch_post_type(post_type)
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for item in items:
        raw_title = (item.get("title") or {}).get("rendered", "")
        content_html = (item.get("content") or {}).get("rendered", "")
        record = {
            "wp_id": item.get("id"),
            "post_type": post_type,
            "title": _strip_html(raw_title) or raw_title.strip(),
            "slug": item.get("slug", ""),
            "link": item.get("link", ""),
            "content_html": content_html,
            "content_text": _strip_html(content_html),
            "fetched_at": now,
        }
        db.upsert_wordpress_item(record)
        count += 1

    return count


def ingest_all() -> dict:
    """Ingest every configured post type. Returns a per-type summary so
    partial failures (e.g. one custom post type not registered on this
    site) don't kill the whole sync."""
    summary = {}
    for post_type in config.WORDPRESS_POST_TYPES:
        try:
            summary[post_type] = ingest_post_type(post_type)
        except requests.RequestException as exc:
            summary[post_type] = f"error: {exc}"
    return summary
