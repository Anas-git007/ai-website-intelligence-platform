"""
Gmail ingestion + understanding layer.

This is the ONLY new module added for Gmail support. It is responsible for:
  - OAuth2 authentication against the real Gmail API
  - Fetching unread/recent emails (subject, sender, body)
  - Cleaning HTML/plain-text bodies into plain text
  - Detecting the product/service mentioned (keyword + fuzzy match against
    the real catalog already sitting in the local knowledge base)
  - Simple rule-based intent classification
  - Persisting processed emails into the `emails` table (db.py) so re-syncs
    don't reprocess the same message twice

It does NOT touch the existing retrieval engine or Claude integration - it
only produces structured records and a retrieval query string. app.py wires
those into the existing `retrieval.get_relevant_context()` and
`claude_client.generate_page_update()` exactly like the manual-input path
already does.

Requires (only if you actually use Gmail features):
    google-api-python-client
    google-auth-httplib2
    google-auth-oauthlib
These are imported lazily so the rest of the system keeps working even if
a user hasn't installed/configured Gmail yet.
"""
import base64
import os
import re
from contextlib import closing
from datetime import datetime, timezone
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

from config import config
import db

# Read-only is enough unless GMAIL_MARK_AS_READ is on, in which case we need
# permission to remove the UNREAD label.
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

PRODUCT_MATCH_THRESHOLD = 0.72


# ---------------------------------------------------------------------------
# OAuth2 / API client (lazy import - see module docstring)
# ---------------------------------------------------------------------------

def _gmail_libs():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise RuntimeError(
            "Gmail integration needs google-api-python-client, "
            "google-auth-httplib2 and google-auth-oauthlib. "
            "Run: pip install -r requirements.txt"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, HttpError


def _scopes():
    return [GMAIL_MODIFY_SCOPE] if config.GMAIL_MARK_AS_READ else [GMAIL_READONLY_SCOPE]


def get_credentials():
    """Standard installed-app OAuth2 flow: reuse a cached token if valid,
    refresh it if expired, otherwise open the consent screen once. Mirrors
    Google's own Gmail API quickstart pattern."""
    Request, Credentials, InstalledAppFlow, _build, _HttpError = _gmail_libs()
    scopes = _scopes()

    creds = None
    if os.path.exists(config.GMAIL_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(config.GMAIL_TOKEN_PATH, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(config.GMAIL_CREDENTIALS_PATH):
                raise RuntimeError(
                    f"Gmail OAuth client file not found at '{config.GMAIL_CREDENTIALS_PATH}'. "
                    "Download an OAuth client (Desktop app) from Google Cloud Console > "
                    "APIs & Services > Credentials, and set GMAIL_CREDENTIALS_PATH in .env."
                )
            flow = InstalledAppFlow.from_client_secrets_file(config.GMAIL_CREDENTIALS_PATH, scopes)
            creds = flow.run_local_server(port=0)
        with open(config.GMAIL_TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return creds


def get_service():
    _Request, _Credentials, _Flow, build, _HttpError = _gmail_libs()
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


def fetch_messages(query: str = None, max_results: int = None) -> list:
    """Fetches full message payloads for the given Gmail search query
    (defaults to GMAIL_QUERY, e.g. "is:unread")."""
    service = get_service()
    query = config.GMAIL_QUERY if query is None else query
    max_results = config.GMAIL_MAX_RESULTS if max_results is None else max_results

    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    refs = resp.get("messages", [])

    full_messages = []
    for ref in refs:
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        full_messages.append(msg)
    return full_messages


def mark_as_read(message_id: str):
    service = get_service()
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


# ---------------------------------------------------------------------------
# MIME parsing -> clean text
# ---------------------------------------------------------------------------

def _get_header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_part_data(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_parts(payload: dict):
    """Yields (mime_type, decoded_text) for every leaf part of a Gmail
    message payload, recursing into multipart/* containers."""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    if body.get("data"):
        yield mime_type, _decode_part_data(body["data"])
    for part in payload.get("parts", []) or []:
        yield from _walk_parts(part)


def extract_clean_body(payload: dict) -> str:
    """Prefers the text/plain part; falls back to stripping the text/html
    part with BeautifulSoup (same approach already used for WordPress/
    PrestaShop HTML elsewhere in this system)."""
    plain_chunks, html_chunks = [], []
    for mime_type, text in _walk_parts(payload or {}):
        if mime_type == "text/plain" and text.strip():
            plain_chunks.append(text)
        elif mime_type == "text/html" and text.strip():
            html_chunks.append(text)

    if plain_chunks:
        raw = "\n".join(plain_chunks)
    elif html_chunks:
        raw = "\n".join(
            BeautifulSoup(chunk, "lxml").get_text(separator=" ", strip=True) for chunk in html_chunks
        )
    else:
        raw = ""

    # Drop quoted reply chains ("On Mon, Jan 5 ... wrote:") so detection
    # isn't thrown off by the previous message being quoted back.
    raw = re.split(r"\n\s*On .{0,100} wrote:\s*\n", raw)[0]
    return re.sub(r"[ \t]+", " ", raw).strip()


# ---------------------------------------------------------------------------
# Product detection (keyword + fuzzy match against the real catalog)
# ---------------------------------------------------------------------------

def detect_product(text: str):
    """Returns (product_name_or_empty_string, match_score 0..1).

    1) Direct substring match against real product/page names already
       ingested from WordPress/PrestaShop - cheap and precise.
    2) Fuzzy fallback (difflib, stdlib) across word n-grams of the email
       text, for when the client paraphrases the product name.
    No hard-coded catalog: if nothing has been synced yet, this returns
    ("", 0.0) rather than guessing.
    """
    candidates = db.list_known_entity_names()
    if not candidates or not text.strip():
        return "", 0.0

    lowered = text.lower()
    for name in candidates:
        if name and name.lower() in lowered:
            return name, 0.95

    words = re.findall(r"[A-Za-z0-9]+", text)
    windows = set()
    for size in (1, 2, 3):
        for i in range(len(words) - size + 1):
            windows.add(" ".join(words[i : i + size]))

    best_name, best_score = "", 0.0
    for name in candidates:
        name_lower = name.lower()
        for window in windows:
            score = SequenceMatcher(None, name_lower, window.lower()).ratio()
            if score > best_score:
                best_score, best_name = score, name

    if best_score >= PRODUCT_MATCH_THRESHOLD:
        return best_name, round(best_score, 2)
    return "", round(best_score, 2)


# ---------------------------------------------------------------------------
# Intent classification (simple rule-based, as specified)
# ---------------------------------------------------------------------------

# Checked in order - first matching rule wins, so a frustrated pricing email
# ("this pricing issue is a problem") is correctly read as a complaint first.
INTENT_RULES = [
    ("complaint", [r"\brefund\b", r"\bcomplain\w*\b", r"\bnot working\b", r"\bissue\b",
                   r"\bproblem\b", r"\bdisappointed\b", r"\bunhappy\b", r"\bcancel\b"], 0.85),
    ("pricing inquiry", [r"\bprice\b", r"\bpricing\b", r"\bcost\b", r"\bquote\b",
                          r"\bhow much\b", r"\bdiscount\b"], 0.85),
    ("comparison", [r"\bcompare\b", r"\bcomparison\b", r"\bvs\.?\b", r"\bversus\b",
                     r"\bdifference between\b", r"\balternative\b", r"\bbetter than\b"], 0.8),
    ("conversion intent", [r"\bapply\b", r"\bsign up\b", r"\bsign-up\b", r"\bbook\b",
                            r"\bpurchase\b", r"\bbuy\b", r"\border\b", r"\bget started\b"], 0.85),
    ("general inquiry", [r"\binfo\b", r"\binformation\b", r"\bdetails\b", r"\btell me\b",
                          r"\bmore about\b", r"\bquestions?\b"], 0.7),
]
DEFAULT_INTENT = "interest"
DEFAULT_INTENT_CONFIDENCE = 0.4


def detect_intent(text: str):
    lowered = (text or "").lower()
    for label, patterns, confidence in INTENT_RULES:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return label, confidence
    return DEFAULT_INTENT, DEFAULT_INTENT_CONFIDENCE


# ---------------------------------------------------------------------------
# Putting one message together into the required structured shape
# ---------------------------------------------------------------------------

def process_message(raw_message: dict) -> dict:
    """Converts one raw Gmail API message into the required JSON shape:
    email_id, sender, subject, clean_body, detected_product, intent, confidence.
    """
    payload = raw_message.get("payload", {}) or {}
    headers = payload.get("headers", []) or []

    sender = _get_header(headers, "From")
    subject = _get_header(headers, "Subject")
    clean_body = extract_clean_body(payload)

    detection_text = f"{subject}\n{clean_body}"
    detected_product, product_score = detect_product(detection_text)
    intent, intent_confidence = detect_intent(detection_text)

    # Overall confidence blends how sure we are about the product match
    # with how sure we are about the intent rule that fired.
    if detected_product:
        confidence = round((product_score + intent_confidence) / 2, 2)
    else:
        confidence = round(intent_confidence * 0.7, 2)

    return {
        "email_id": raw_message.get("id", ""),
        "sender": sender,
        "subject": subject,
        "clean_body": clean_body,
        "detected_product": detected_product,
        "intent": intent,
        "confidence": confidence,
    }


def build_retrieval_query(email_record: dict) -> str:
    """Feeds the detected product into the EXISTING retrieval engine as its
    query. Falls back to subject+body if no product was confidently
    detected, so retrieval still has something to work with."""
    product = (email_record.get("detected_product") or "").strip()
    if product:
        return product
    return f"{email_record.get('subject', '')} {email_record.get('clean_body', '')}".strip()[:500]


# ---------------------------------------------------------------------------
# Orchestration: fetch -> process -> persist (no retrieval/Claude calls here)
# ---------------------------------------------------------------------------

def sync_emails(query: str = None, max_results: int = None, mark_read: bool = None) -> list:
    """Fetches messages from Gmail, processes any not already stored, and
    returns the full set of processed records (existing ones included) so
    the UI always has a consistent list to render."""
    mark_read = config.GMAIL_MARK_AS_READ if mark_read is None else mark_read

    raw_messages = fetch_messages(query=query, max_results=max_results)
    fetched_ids = [m.get("id", "") for m in raw_messages]
    already_processed = db.get_processed_email_ids(fetched_ids)

    now = datetime.now(timezone.utc).isoformat()
    records = []

    for raw in raw_messages:
        msg_id = raw.get("id", "")
        if msg_id in already_processed:
            records.append(db.get_email_by_id(msg_id))
            continue

        record = process_message(raw)
        db.upsert_email(
            {
                "email_id": record["email_id"],
                "sender": record["sender"],
                "subject": record["subject"],
                "body": record["clean_body"],
                "detected_product": record["detected_product"],
                "intent": record["intent"],
                "confidence": record["confidence"],
                "processed_at": now,
            }
        )
        if mark_read:
            try:
                mark_as_read(msg_id)
            except Exception:
                pass  # Non-fatal: the email is still recorded as processed locally.

        records.append(db.get_email_by_id(msg_id))

    return records
