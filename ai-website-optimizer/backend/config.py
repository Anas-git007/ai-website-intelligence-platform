"""
Central configuration loaded from environment variables (.env).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _split_list(raw: str):
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


class Config:
    # --- WordPress ---
    WORDPRESS_BASE_URL = os.getenv("WORDPRESS_BASE_URL", "").rstrip("/")
    WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME", "")
    WORDPRESS_APP_PASSWORD = os.getenv("WORDPRESS_APP_PASSWORD", "")
    WORDPRESS_POST_TYPES = _split_list(os.getenv("WORDPRESS_POST_TYPES", "pages,posts"))

    # --- PrestaShop ---
    PRESTASHOP_BASE_URL = os.getenv("PRESTASHOP_BASE_URL", "").rstrip("/")
    PRESTASHOP_API_KEY = os.getenv("PRESTASHOP_API_KEY", "")

    # --- Claude / Anthropic ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ANTHROPIC_API_VERSION = "2023-06-01"

    # --- AI provider switch ---
    # "claude" (default) or "gemini" (free tier available).
    # Flipping this in .env is all that's needed — no code changes.
    AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").strip().lower()

    # --- Gemini (optional alternate provider) ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # --- Token budget ---
    # The generated html_file is a complete HTML document (4 sections + inline
    # CSS + inline JS). 4 000 was too low and caused truncation. 8 192 is a
    # safe default; raise it in .env if you have very content-heavy pages.
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))

    # --- Gmail ---
    GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    GMAIL_QUERY = os.getenv("GMAIL_QUERY", "is:unread")
    GMAIL_MAX_RESULTS = int(os.getenv("GMAIL_MAX_RESULTS", "10"))
    GMAIL_MARK_AS_READ = os.getenv("GMAIL_MARK_AS_READ", "").lower() in ("1", "true", "yes")
    GMAIL_AUTO_GENERATE_LIMIT = int(os.getenv("GMAIL_AUTO_GENERATE_LIMIT", "3"))

    # --- App ---
    PORT = int(os.getenv("PORT", "8000"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
    SCRAPER_USER_AGENT = os.getenv(
        "SCRAPER_USER_AGENT", "AI-Website-Optimizer/1.0 (+local-tool)"
    )
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")

    _default_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "knowledge.db")
    DATABASE_PATH = os.getenv("DATABASE_PATH") or _default_db_path


config = Config()