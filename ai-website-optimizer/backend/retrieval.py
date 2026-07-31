"""
Context retrieval engine.

Given the client's conversation text, finds the most relevant chunks across
all three knowledge sources using real FTS5/BM25 search (db.py), merges
them into one globally-ranked list, and caps the result so the AI
generation layer only ever sees a focused context window instead of the
whole knowledge base.
"""
import db

DEFAULT_PER_SOURCE_LIMIT = 6
DEFAULT_TOTAL_LIMIT = 10


def get_relevant_context(
    query: str,
    per_source_limit: int = DEFAULT_PER_SOURCE_LIMIT,
    total_limit: int = DEFAULT_TOTAL_LIMIT,
) -> dict:
    wp_hits = db.search_wordpress(query, per_source_limit)
    ps_hits = db.search_prestashop(query, per_source_limit)
    fe_hits = db.search_frontend(query, per_source_limit)

    tagged = (
        [{"source": "wordpress", "rank": r["rank"], "item": r} for r in wp_hits]
        + [{"source": "prestashop", "rank": r["rank"], "item": r} for r in ps_hits]
        + [{"source": "frontend", "rank": r["rank"], "item": r} for r in fe_hits]
    )
    # BM25 in SQLite: lower (more negative) is more relevant.
    tagged.sort(key=lambda t: t["rank"])
    top = tagged[:total_limit]

    context = {"wordpress_content": [], "prestashop_products": [], "frontend_structures": []}
    key_by_source = {
        "wordpress": "wordpress_content",
        "prestashop": "prestashop_products",
        "frontend": "frontend_structures",
    }
    for t in top:
        context[key_by_source[t["source"]]].append(t["item"])

    context["query"] = query
    context["total_chunks"] = len(top)
    return context
