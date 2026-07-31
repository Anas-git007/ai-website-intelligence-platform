"""
AI generation layer — calls the real Anthropic Messages API (no SDK
dependency, just `requests`) with the client conversation plus the
retrieved website context, and returns the structured JSON the rest of
the system expects.

generate_page_update() accepts an optional `email_context` (a processed
Gmail record from gmail_client.py). When present, it is included in the
prompt as a distinct "CLIENT EMAIL DATA" block ahead of the website
context, matching the existing manual-input behaviour exactly when absent.

Prompt construction and response validation live in ai_prompt.py, shared
with gemini_client.py, so the two providers are tested against identical
instructions — see ai_provider.py for how AI_PROVIDER picks between them.
"""
import requests

from config import config
import ai_prompt

API_URL = "https://api.anthropic.com/v1/messages"


def generate_page_update(client_message: str, context: dict, email_context: dict = None) -> dict:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured in .env")

    user_prompt = ai_prompt.build_user_prompt(client_message, context, email_context)

    payload = {
        "model": config.ANTHROPIC_MODEL,
        # Full html_file output (complete HTML doc + inline CSS/JS) easily
        # exceeds 4 000 tokens. MAX_TOKENS defaults to 8 192 and is
        # configurable via .env.
        "max_tokens": config.MAX_TOKENS,
        "system": ai_prompt.SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": config.ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks)

    parsed = ai_prompt.extract_json(raw_text)
    return ai_prompt.finalize_result(parsed, provider="Claude")