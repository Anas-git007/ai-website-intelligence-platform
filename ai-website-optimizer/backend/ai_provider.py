"""
Picks which AI backend handles generate_page_update() based on AI_PROVIDER
in .env. This is the ONLY place that needs to know both providers exist -
app.py calls ai_provider.generate_page_update(...) exactly like it
previously called claude_client.generate_page_update(...) directly, so
flipping AI_PROVIDER between "claude" and "gemini" needs no other code
changes anywhere in the system.
"""
from config import config
import claude_client
import gemini_client

PROVIDERS = {
    "claude": claude_client.generate_page_update,
    "gemini": gemini_client.generate_page_update,
}


def generate_page_update(client_message: str, context: dict, email_context: dict = None) -> dict:
    provider = config.AI_PROVIDER
    handler = PROVIDERS.get(provider)
    if handler is None:
        raise RuntimeError(
            f"Unknown AI_PROVIDER '{provider}' in .env - use 'claude' or 'gemini'."
        )
    return handler(client_message, context, email_context=email_context)


def current_model() -> str:
    """Used by /api/health so the UI can always show which provider/model
    a generate click will actually hit."""
    if config.AI_PROVIDER == "gemini":
        return config.GEMINI_MODEL
    return config.ANTHROPIC_MODEL
