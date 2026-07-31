"""
Optional alternate AI generation backend — calls the real Gemini API
(https://ai.google.dev, generativelanguage.googleapis.com) instead of
Claude. Useful for testing this pipeline on Gemini's free tier (Google AI
Studio, no card required) before paying for Claude usage.

Mirrors claude_client.py's public interface exactly:
    generate_page_update(client_message, context, email_context=None) -> dict
so it's a drop-in alternative selected by AI_PROVIDER in .env — see
ai_provider.py for the one-line dispatch. Both clients build their prompt
from the same shared ai_prompt module and validate the response the same
way (ai_prompt.finalize_result), so output is directly comparable across
providers and switching back to AI_PROVIDER=claude needs no code changes.

No extra dependency: like every other client in this system, this talks to
the REST API directly with `requests` rather than pulling in Google's SDK.
"""
import requests

from config import config
import ai_prompt

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def generate_page_update(client_message: str, context: dict, email_context: dict = None) -> dict:
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured in .env (get a free one at "
            "https://aistudio.google.com/apikey, no credit card required)"
        )

    user_prompt = ai_prompt.build_user_prompt(client_message, context, email_context)

    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": ai_prompt.SYSTEM_PROMPT}]},
        "generationConfig": {
            # Full html_file output (complete HTML doc + inline CSS/JS) easily
            # exceeds 4 000 tokens. MAX_TOKENS defaults to 8 192 and is
            # configurable via .env.
            "maxOutputTokens": config.MAX_TOKENS,
            # Belt-and-suspenders: ask Gemini to constrain to JSON on top of
            # the prompt instruction, matching the same parsing step that
            # ai_prompt.extract_json() applies to Claude output too.
            "responseMimeType": "application/json",
        },
    }
    headers = {
        "content-type": "application/json",
        "x-goog-api-key": config.GEMINI_API_KEY,
    }
    url = f"{API_BASE}/{config.GEMINI_MODEL}:generateContent"

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            raise ValueError(f"Gemini blocked this request (blockReason={block_reason})")
        raise ValueError("Gemini returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", []) or []
    raw_text = "\n".join(p.get("text", "") for p in parts if "text" in p)
    if not raw_text.strip():
        finish_reason = candidates[0].get("finishReason", "unknown")
        raise ValueError(f"Gemini returned an empty response (finishReason={finish_reason})")

    parsed = ai_prompt.extract_json(raw_text)
    return ai_prompt.finalize_result(parsed, provider="Gemini")