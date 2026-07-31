from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import config
import db


CS_LANG_ID = "1"
EN_LANG_ID = "3"


def _auth():
    if not config.PRESTASHOP_API_KEY:
        raise ValueError("PRESTASHOP_API_KEY is not configured")
    return (config.PRESTASHOP_API_KEY, "")


def _strip_html(html: str) -> str:
    if not html:
        return ""

    return BeautifulSoup(html, "lxml").get_text(
        separator=" ",
        strip=True,
    )


def _localized_xml(node, lang_id: str) -> str:
    """
    Extract:

    <name>
        <language id="1">...</language>
        <language id="3">...</language>
    </name>
    """
    if node is None:
        return ""

    lang = node.find("language", {"id": str(lang_id)})
    if lang is None:
        return ""

    return lang.get_text(strip=True)


def _request(path: str, params: dict = None):
    if not config.PRESTASHOP_BASE_URL:
        raise ValueError("PRESTASHOP_BASE_URL is not configured")

    url = f"{config.PRESTASHOP_BASE_URL}/api/{path}"

    resp = requests.get(
        url,
        params=params,
        auth=_auth(),
        timeout=config.REQUEST_TIMEOUT,
    )

    resp.raise_for_status()

    return BeautifulSoup(resp.content, "xml")


def fetch_category_name(category_id):
    try:
        soup = _request(f"categories/{category_id}")

        category = soup.find("category")
        if category is None:
            return {
                "cs": "",
                "en": "",
            }

        name_node = category.find("name")

        return {
            "cs": _localized_xml(name_node, CS_LANG_ID),
            "en": _localized_xml(name_node, EN_LANG_ID),
        }

    except requests.RequestException:
        return {
            "cs": "",
            "en": "",
        }


def fetch_products(limit: int = None):
    soup = _request(
        "products",
        {"display": "full"},
    )

    products = soup.find_all("product")

    if limit:
        products = products[:limit]

    return products


def ingest_products(limit: int = None) -> int:
    products = fetch_products(limit)

    now = datetime.now(timezone.utc).isoformat()

    category_name_cache = {}
    count = 0

    for p in products:
        try:
            ps_id = p.find("id").text.strip()

            category_node = p.find("id_category_default")
            category_id = (
                category_node.text.strip()
                if category_node and category_node.text
                else ""
            )

            if category_id not in category_name_cache:
                category_name_cache[category_id] = (
                    fetch_category_name(category_id)
                    if category_id
                    else {"cs": "", "en": ""}
                )

            category_name = category_name_cache[category_id]

            name_node = p.find("name")
            desc_node = p.find("description")
            short_node = p.find("description_short")

            name_cs = _localized_xml(
                name_node,
                CS_LANG_ID,
            )

            name_en = _localized_xml(
                name_node,
                EN_LANG_ID,
            )

            description_html_cs = (
                _localized_xml(desc_node, CS_LANG_ID)
                or _localized_xml(short_node, CS_LANG_ID)
            )

            description_html_en = (
                _localized_xml(desc_node, EN_LANG_ID)
                or _localized_xml(short_node, EN_LANG_ID)
            )

            price_node = p.find("price")
            price = (
                price_node.text.strip()
                if price_node and price_node.text
                else ""
            )

            link = ""
            if config.PRESTASHOP_BASE_URL and ps_id:
                link = (
                    f"{config.PRESTASHOP_BASE_URL}"
                    f"/index.php?controller=product"
                    f"&id_product={ps_id}"
                )

            record = {
                "ps_id": ps_id,

                "name_cs": name_cs,
                "name_en": name_en,

                "description_html_cs": description_html_cs,
                "description_html_en": description_html_en,

                "description_text_cs": _strip_html(
                    description_html_cs
                ),
                "description_text_en": _strip_html(
                    description_html_en
                ),

                "category_cs": category_name["cs"],
                "category_en": category_name["en"],

                "price": price,
                "link": link,
                "fetched_at": now,
            }

            db.upsert_prestashop_product(record)

            count += 1

        except Exception as e:
            print(
                f"Failed to ingest product "
                f"{p.find('id').text if p.find('id') else '?'}: {e}"
            )

    return count