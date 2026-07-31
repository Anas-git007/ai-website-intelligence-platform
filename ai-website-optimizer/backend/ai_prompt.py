"""
Shared prompt construction + response parsing/validation
used by BOTH claude_client.py and gemini_client.py.
"""

import json
import re

REQUIRED_SECTIONS = ["hero", "features", "testimonials", "cta"]

REQUIRED_RESULT_KEYS = [
    "html_file",
    "download_button",
    "seo_suggestions",
    "improvement_suggestions",
    "cta_variations",
]

# ============================================================================
# Download assets
# ============================================================================

_DOWNLOAD_SCRIPT = """<script>
function downloadHTML() {
    var html = document.documentElement.outerHTML;
    var blob = new Blob([html], {type:'text/html'});
    var a = document.createElement('a');

    a.href = URL.createObjectURL(blob);
    a.download = 'generated-page.html';
    a.click();
}
</script>"""

_DOWNLOAD_BUTTON = """
<button onclick="downloadHTML()"
style="position:fixed;
bottom:20px;
right:20px;
z-index:9999;
padding:10px 18px;
background:#0E8388;
color:#fff;
border:none;
border-radius:6px;
font-size:14px;
font-weight:600;
cursor:pointer;">
Download Page
</button>
""".strip()

# Precompute escaped versions
ESCAPED_DOWNLOAD_SCRIPT = _DOWNLOAD_SCRIPT.replace("\n", " ")
ESCAPED_DOWNLOAD_BUTTON = _DOWNLOAD_BUTTON.replace('"', '\\"')

# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = f"""
You are a senior conversion copywriter and web content strategist
working from a brand's real WordPress and PrestaShop content.

You are performing "theme-preserving conversion optimisation":

- Reuse existing class names from frontend_structures context
- Preserve spacing logic, layout hierarchy, and brand feel
- Improve copywriting
- Improve CTA clarity
- Improve email-driven personalization
- Never redesign the site
- Never add new section types
- Never change section order


LOCKED PAGE STRUCTURE:

Output exactly these four sections:

<section class="hero"></section>
<section class="features"></section>
<section class="testimonials"></section>
<section class="cta"></section>


Ground all factual claims in provided context.

If information is unavailable:
- Write generic content
- Do not invent products
- Do not invent prices
- Do not invent statistics


EMAIL INTENT → CTA STRATEGY

pricing:
    emphasize pricing clarity
    CTA = "Get Quote"

purchase:
    short funnel
    direct action

complaint:
    trust
    reassurance
    support

comparison:
    highlight differentiators

inquiry:
    informative structure


OUTPUT:

Return ONLY a single JSON object.

{{
    "html_file":"FULL HTML",
    "download_button":"{ESCAPED_DOWNLOAD_BUTTON}",
    "seo_suggestions":["..."],
    "improvement_suggestions":["..."],
    "cta_variations":["..."]
}}

HTML REQUIREMENTS:

1. Must be complete HTML:
   <!DOCTYPE html><html>...</html>

2. Must include inline CSS:
   <style>...</style>

3. Must include EXACT script:
   {ESCAPED_DOWNLOAD_SCRIPT}

4. Must include EXACT button before </body>:
   {ESCAPED_DOWNLOAD_BUTTON}

5. Must contain exactly:

   <section class="hero">
   <section class="features">
   <section class="testimonials">
   <section class="cta">

6. No external CSS

7. No external JS

8. No additional script tags
""".strip()

# ============================================================================
# Context formatters
# ============================================================================


def format_context(context: dict) -> str:

    parts = []

    wordpress = context.get("wordpress_content", [])

    if wordpress:
        parts.append(
            "WORDPRESS CONTENT "
            "(use for brand tone and style only):"
        )

        for item in wordpress:

            parts.append(
                f"- [{item.get('post_type','')}] "
                f"{item.get('title','')} "
                f"({item.get('link','')})\n"
                f"{item.get('content_text','')[:600]}"
            )

    prestashop = context.get("prestashop_products", [])

    if prestashop:

        parts.append(
            "\nPRESTASHOP PRODUCTS "
            "(factual source only):"
        )

        for item in prestashop:

            name = (
                item.get("name_en")
                or item.get("name_cs")
                or item.get("name", "")
            )

            description = (
                item.get("description_text_en")
                or item.get("description_text_cs")
                or item.get("description_text", "")
            )

            category = (
                item.get("category_en")
                or item.get("category_cs")
                or item.get("category", "")
            )

            parts.append(
                f"- {name}"
                f" | price:{item.get('price','')}"
                f" | category:{category}\n"
                f"{description[:400]}"
            )

    frontend = context.get("frontend_structures", [])

    if frontend:

        parts.append(
            "\nLIVE FRONTEND STRUCTURES:"
        )

        for item in frontend:

            parts.append(
                f"- [{item.get('section_type','')}] "
                f"{item.get('heading','')} "
                f"({item.get('source_url','')})\n"
                f"{item.get('text','')[:400]}"
            )

    if not parts:

        return (
            "No website context found. "
            "Write generic content only."
        )

    return "\n".join(parts)


def format_email_context(email_context: dict) -> str:

    return (
        "CLIENT EMAIL DATA:\n"
        f"From:{email_context.get('sender','')}\n"
        f"Subject:{email_context.get('subject','')}\n"
        f"Detected product:"
        f"{email_context.get('detected_product')}\n"
        f"Intent:"
        f"{email_context.get('intent')}\n"
        f"Confidence:"
        f"{email_context.get('confidence')}\n"
        f"Body:"
        f"{(email_context.get('clean_body') or '')[:1200]}"
    )


def build_user_prompt(
    client_message: str,
    context: dict,
    email_context: dict = None
):

    prompt = [
        "CLIENT INPUT:",
        client_message.strip(),
        ""
    ]

    if email_context:
        prompt.append(
            format_email_context(
                email_context
            )
        )

    prompt.append(
        "\nRETRIEVED WEBSITE CONTEXT:"
    )

    prompt.append(
        format_context(
            context
        )
    )

    return "\n".join(prompt)


# ============================================================================
# JSON extraction
# ============================================================================

def extract_json(raw_text: str):

    cleaned = raw_text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned
    )

    cleaned = re.sub(
        r"```\s*$",
        "",
        cleaned
    )

    try:
        return json.loads(cleaned)

    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")

    if start == -1:
        raise ValueError(
            "No JSON found"
        )

    depth = 0
    in_string = False
    escaped = False

    for i, ch in enumerate(cleaned[start:], start):

        if escaped:
            escaped = False
            continue

        if ch == "\\" and in_string:
            escaped = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if not in_string:

            if ch == "{":
                depth += 1

            elif ch == "}":

                depth -= 1

                if depth == 0:

                    return json.loads(
                        cleaned[start:i+1]
                    )

    raise ValueError(
        "Could not extract JSON"
    )


# ============================================================================
# Validation
# ============================================================================

def validate_structure(html: str):

    warnings = []

    for section in REQUIRED_SECTIONS:

        pattern = (
            rf'class\s*=\s*["\'][^"\']*'
            rf'\b{re.escape(section)}\b'
        )

        if not re.search(
            pattern,
            html,
            re.IGNORECASE
        ):

            warnings.append(
                f"Missing section: {section}"
            )

    return warnings


def finalize_result(
    parsed: dict,
    provider: str = ""
):

    missing = [
        x for x in REQUIRED_RESULT_KEYS
        if x not in parsed
    ]

    if missing:

        label = (
            f"{provider} "
            if provider
            else ""
        )

        raise ValueError(
            f"{label}missing keys: {missing}"
        )

    parsed[
        "structure_warnings"
    ] = validate_structure(
        parsed["html_file"]
    )

    return parsed