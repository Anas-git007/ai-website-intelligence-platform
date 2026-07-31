"""
Flask application: serves the frontend UI and exposes the API that drives
ingestion, retrieval, and AI-powered page generation.

Run with:  python app.py
Then open: http://localhost:8000
"""
import os

from flask import Flask, request, jsonify, send_from_directory
import requests

import db
import wordpress_client
import prestashop_client
import frontend_scraper
import gmail_client
import retrieval
import ai_provider
from config import config

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

app = Flask(__name__)
db.init_db()


@app.after_request
def add_cors_headers(response):
    # Permissive CORS so the static frontend can be served from this same
    # process or opened independently during development.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ---------------------------------------------------------------------------
# Frontend (static files)
# ---------------------------------------------------------------------------

@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "ai_provider": config.AI_PROVIDER,
        "ai_model": ai_provider.current_model(),
    })


@app.route("/api/status")
def status():
    return jsonify(db.counts())


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

@app.route("/api/ingest/wordpress", methods=["POST"])
def ingest_wordpress():
    try:
        summary = wordpress_client.ingest_all()
        db.rebuild_fts()
        return jsonify({"ok": True, "summary": summary})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/api/ingest/prestashop", methods=["POST"])
def ingest_prestashop():
    body = request.get_json(silent=True) or {}
    limit = body.get("limit")
    try:
        count = prestashop_client.ingest_products(limit=limit)
        db.rebuild_fts()
        return jsonify({"ok": True, "products_ingested": count})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/api/ingest/frontend", methods=["POST"])
def ingest_frontend():
    body = request.get_json(silent=True) or {}
    urls = [u for u in (body.get("urls") or []) if u.strip()]
    if not urls:
        return jsonify({"ok": False, "error": "Provide a non-empty 'urls' list"}), 400
    try:
        summary = frontend_scraper.ingest_urls(urls)
        db.rebuild_fts()
        return jsonify({"ok": True, "summary": summary})
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/api/gmail/sync", methods=["POST"])
def gmail_sync():
    """Mode 1 half of Gmail support: fetch + parse + store only, no
    generation. Powers the 'Sync Gmail' button."""
    body = request.get_json(silent=True) or {}
    query = body.get("query") or None
    max_results = body.get("max_results") or None
    try:
        records = gmail_client.sync_emails(query=query, max_results=max_results)
        return jsonify({"ok": True, "emails": records})
    except RuntimeError as exc:
        # Missing OAuth client file, missing libraries, etc. - a config problem, not a server error.
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Gmail sync failed: {exc}"}), 502


@app.route("/api/gmail/emails")
def gmail_emails():
    """Lists whatever has already been synced, without hitting Gmail again -
    used to repopulate the email preview panel on page load."""
    limit = int(request.args.get("limit", 25))
    return jsonify({"ok": True, "emails": db.list_recent_emails(limit)})


# ---------------------------------------------------------------------------
# Search (debug / inspection utility over the knowledge base)
# ---------------------------------------------------------------------------

@app.route("/api/search")
def search():
    query = request.args.get("q", "")
    source = request.args.get("source", "all")
    limit = int(request.args.get("limit", 10))
    if not query:
        return jsonify({"ok": False, "error": "Provide a 'q' query parameter"}), 400

    result = {}
    if source in ("all", "wordpress"):
        result["wordpress_content"] = db.search_wordpress(query, limit)
    if source in ("all", "prestashop"):
        result["prestashop_products"] = db.search_prestashop(query, limit)
    if source in ("all", "frontend"):
        result["frontend_structures"] = db.search_frontend(query, limit)
    return jsonify({"ok": True, "results": result})


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------

def _generate_for(client_message: str, email_context: dict = None):
    """Shared retrieval + AI generation, used by the manual /api/generate
    path AND the Gmail-driven paths below. Goes through ai_provider so it
    transparently uses whichever backend AI_PROVIDER in .env selects -
    response shape and status codes are unaffected by which one that is."""
    context = retrieval.get_relevant_context(client_message)

    try:
        result = ai_provider.generate_page_update(client_message, context, email_context=email_context)
    except RuntimeError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text if exc.response is not None else str(exc)
        return 502, {"ok": False, "error": f"{config.AI_PROVIDER.title()} API request failed", "detail": detail}
    except Exception as exc:
        return 502, {"ok": False, "error": f"Generation failed: {exc}"}

    body = {"ok": True, "context_used": context, "result": result}
    if email_context is not None:
        body["email"] = email_context
    return 200, body


@app.route("/api/generate", methods=["POST"])
def generate():
    body = request.get_json(silent=True) or {}
    client_message = (body.get("client_message") or "").strip()
    if not client_message:
        return jsonify({"ok": False, "error": "Provide a non-empty 'client_message'"}), 400

    status_code, result_body = _generate_for(client_message)
    return jsonify(result_body), status_code


@app.route("/api/gmail/generate", methods=["POST"])
def gmail_generate():
    """Mode 1 second half: generate a page update from one already-synced
    email. Powers the per-row 'Generate from this email' button."""
    body = request.get_json(silent=True) or {}
    email_id = (body.get("email_id") or "").strip()
    if not email_id:
        return jsonify({"ok": False, "error": "Provide a non-empty 'email_id'"}), 400

    email_record = db.get_email_by_id(email_id)
    if not email_record:
        return jsonify({"ok": False, "error": f"No stored email with id '{email_id}'. Sync Gmail first."}), 404

    client_message = f"Subject: {email_record.get('subject', '')}\n\n{email_record.get('body', '')}"
    status_code, result_body = _generate_for(client_message, email_context=email_record)
    return jsonify(result_body), status_code


@app.route("/api/gmail/auto", methods=["POST"])
def gmail_auto():
    """Mode 2: Gmail Auto Mode. Fetches emails, processes them, and runs the
    full retrieval + Claude pipeline automatically for up to
    GMAIL_AUTO_GENERATE_LIMIT of them. Powers 'Fetch Gmail & Generate Updates'."""
    body = request.get_json(silent=True) or {}
    query = body.get("query") or None
    max_results = body.get("max_results") or None
    generate_limit = body.get("generate_limit") or config.GMAIL_AUTO_GENERATE_LIMIT

    try:
        records = gmail_client.sync_emails(query=query, max_results=max_results)
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Gmail sync failed: {exc}"}), 502

    generated = []
    for record in records[:generate_limit]:
        client_message = f"Subject: {record.get('subject', '')}\n\n{record.get('body', '')}"
        status_code, result_body = _generate_for(client_message, email_context=record)
        generated.append({"email_id": record["email_id"], "status_code": status_code, **result_body})

    return jsonify({"ok": True, "emails": records, "generated": generated})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=config.FLASK_DEBUG)
