# Webview Intelligence Console

An AI-powered website intelligence & content optimization system. It pulls real
content from a WordPress site and a PrestaShop store, scrapes and structures the
live storefront HTML, stores everything in a local SQLite knowledge base, and —
given a plain-English client request — automatically retrieves the relevant
context and calls the Claude API to generate a ready-to-paste HTML section plus
SEO, UX, and CTA recommendations.

No mock data, no placeholder APIs: every ingestion path makes a real HTTP call
to a real WordPress REST API, PrestaShop Webservice API, live storefront page,
or the Anthropic Messages API. The only requirement is that *you* supply real
credentials for the sites you want it to read.

## How it fits together

```
                     ┌─────────────────────┐
  WordPress  ───────►│                      │
  REST API           │   SQLite knowledge   │      ┌──────────────┐
                      │   base (FTS5 BM25    │◄────►│  Flask API   │
  PrestaShop ───────► │   keyword search)    │      │   (app.py)   │
  Webservice API      │                      │      └──────┬───────┘
                      └─────────────────────┘             │
  Live storefront                                          │
  pages ─► BeautifulSoup                                   ▼
  section extraction                                ┌──────────────┐
                                                      │ Claude API   │
  Client conversation ──► context retrieval ────────►│ (Messages)   │
  (typed into the UI)     (top 10 relevant chunks)   └──────┬───────┘
                                  ▲                          │
                                  │                          ▼
  Gmail ──► gmail_client.py ──────┘           html_section + seo_suggestions +
  (OAuth2 + real API)   detected_product       improvement_suggestions + cta_variations
  parse + detect        used as retrieval query
                         (+ email sent to Claude
                            as extra context)
```

Gmail is an additional *input* into the same retrieval engine and the same
AI call - it doesn't replace the manual flow or change how WordPress/
PrestaShop/frontend data is stored or searched. `gmail_client.py` is the only
new module from that integration; everything else is the existing pipeline
with a couple of optional parameters added.

The box labeled "Claude API (Messages)" above is really "whichever provider
`AI_PROVIDER` selects" - `ai_provider.py` dispatches to `claude_client.py` or
`gemini_client.py`, both built from the same shared `ai_prompt.py`, so this
diagram is accurate either way.

The four-section page structure (**Hero → Features → Testimonials → CTA**) is a
hard constraint: it's enforced in the prompt *and* checked again in code
(`ai_prompt.validate_structure`) after the model responds, so the layout can't
silently drift even if a model response is malformed - and since that check
lives in the shared `ai_prompt.py` module, it applies identically whether
`AI_PROVIDER` is `claude` or `gemini` (see "AI provider switch" below).

## Project structure

```
ai-website-optimizer/
├── backend/
│   ├── app.py                 Flask app: serves the UI + all API routes
│   ├── config.py              Loads every setting from .env
│   ├── db.py                  SQLite schema, upserts, FTS5/BM25 search
│   ├── wordpress_client.py    Real WordPress REST API ingestion
│   ├── prestashop_client.py   Real PrestaShop Webservice API ingestion
│   ├── frontend_scraper.py    Real HTTP fetch + BeautifulSoup structuring
│   ├── gmail_client.py        Gmail OAuth2 + fetch + clean text + product/intent detection
│   ├── retrieval.py           Merges BM25 hits across sources, top-10 cap
│   ├── ai_prompt.py           Shared prompt + response validation (used by both AI clients)
│   ├── claude_client.py       Real call to the Anthropic Messages API
│   ├── gemini_client.py       Real call to the Gemini API (optional, free-tier-friendly)
│   ├── ai_provider.py         One-line dispatch between claude_client/gemini_client
│   ├── requirements.txt
│   ├── .env.example
│   └── data/                  SQLite file is created here on first run
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```

## 1. Install dependencies

Requires Python 3.10+.

```bash
cd ai-website-optimizer/backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure credentials

```bash
cp .env.example .env
```

Then edit `.env`:

**WordPress** — `WORDPRESS_BASE_URL` is enough if the content you want is
public. If it's private, create an Application Password under
**WP Admin → Users → Profile → Application Passwords** and set
`WORDPRESS_USERNAME` / `WORDPRESS_APP_PASSWORD`. `WORDPRESS_POST_TYPES` is a
comma-separated list of REST bases — add a custom post type's REST base here
(e.g. `pages,posts,case-studies`) if your "case studies" live in one.

**PrestaShop** — enable the webservice under
**Advanced Parameters → Webservice**, create a key, and grant it at least
**GET** permission on `products` and `categories`. Set `PRESTASHOP_BASE_URL`
and `PRESTASHOP_API_KEY`.

**Claude** — get a key from
[console.anthropic.com](https://console.anthropic.com/settings/keys) and set
`ANTHROPIC_API_KEY`. `ANTHROPIC_MODEL` defaults to `claude-sonnet-4-6`. There's
no free Claude API tier, but a single test generation costs roughly
$0.01–0.03 with Haiku - prepaid credit starts at $5.

**AI provider switch (`AI_PROVIDER`)** — defaults to `claude`. Set it to
`gemini` to run every generation (manual, per-email, and Auto Mode) through
the Gemini API instead, with **zero other code changes**:

```bash
AI_PROVIDER=gemini
GEMINI_API_KEY=your-free-key-from-aistudio.google.com
```

Get a free key (no card required) at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Two things
worth knowing before you send real data through it: Google's free-tier terms
allow your inputs/outputs to be used to improve their models, and the free
tier has been tightened several times in 2026 (current models are Flash/
Flash-Lite; check [ai.google.dev/gemini-api](https://ai.google.dev/gemini-api/docs/rate-limits)
for today's actual rate limits, since they move often). Both providers run
through the exact same prompt and the exact same structure validation (see
`ai_prompt.py`), so output is genuinely comparable — this is meant for
confirming the pipeline works end-to-end for free before paying for Claude,
not as a permanent production swap. Flip `AI_PROVIDER` back to `claude` and
restart whenever you're ready.

**Gmail** —
1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   pick a project and enable the **Gmail API**.
2. Under **APIs & Services → Credentials**, create an OAuth client ID of type
   **Desktop app**, and download the JSON it gives you.
3. Set `GMAIL_CREDENTIALS_PATH` to that file's path (defaults to
   `backend/credentials.json`).

On the first **Sync Gmail**, a browser window opens for you to grant access;
after that, a token is cached at `GMAIL_TOKEN_PATH` and refreshed
automatically, so you won't be prompted again. By default the integration
only requests read-only access (`gmail.readonly`) and tracks which emails
it's already processed in SQLite rather than touching your inbox; set
`GMAIL_MARK_AS_READ=true` if you'd rather it remove the unread label on
processed messages (this requires the broader `gmail.modify` scope).

## 3. Run the backend

```bash
python app.py
```

This serves both the API and the frontend UI together at
**http://localhost:8000** — there's nothing separate to start for the frontend.

## 4. Use it

1. Open `http://localhost:8000`.
2. In the **Knowledge sources** panel, click **Sync WordPress**, **Sync
   products**, and/or paste a few live product/category URLs and click
   **Scrape pages**. Each one hits the real API/site and reports back what it
   pulled in.
3. Generate a page update either way:
   - **Mode 1 — Manual input.** Paste the client's message into **Generate
     page update** and click the button. The backend retrieves the most
     relevant chunks from everything you've synced (no manual pasting) and
     sends them to Claude along with the fixed-structure constraint.
   - **Mode 1b — From a synced email.** Click **Sync Gmail** in the Gmail
     card. Each email lands in the **Email inbox** panel with its detected
     product and intent; click **Generate from this email** on any row to run
     the same pipeline using that email as the client conversation input.
   - **Mode 2 — Gmail Auto Mode.** Click **⚡ Fetch Gmail & Generate
     Updates**. This fetches emails, detects product + intent for each, and
     automatically runs retrieval + Claude for up to
     `GMAIL_AUTO_GENERATE_LIMIT` of them in one go — no further clicks needed.
4. Review the rendered **Preview**, the **Suggestions** (SEO / UX / CTA
   variations), or the **Raw JSON** tab. Copy the HTML out of the JSON view
   (`result.html_section`) into the corresponding WordPress page or PrestaShop
   CMS block.

## API reference

| Method | Path                    | Body                                  | Purpose |
|--------|--------------------------|----------------------------------------|---------|
| GET    | `/api/health`            | –                                       | Liveness check + active AI provider/model |
| GET    | `/api/status`            | –                                       | Row counts per knowledge source (incl. emails) |
| POST   | `/api/ingest/wordpress`  | –                                       | Syncs all configured post types |
| POST   | `/api/ingest/prestashop` | `{"limit": 50}` (optional)              | Syncs products + category names |
| POST   | `/api/ingest/frontend`   | `{"urls": ["https://..."]}`             | Scrapes & structures live pages |
| GET    | `/api/search?q=...`      | –                                       | Debug: raw BM25 search over the knowledge base |
| POST   | `/api/generate`          | `{"client_message": "..."}`             | Retrieves context + calls the active AI provider (Mode 1: manual) |
| POST   | `/api/gmail/sync`        | `{"query": "is:unread"}` (optional)     | Fetches + parses + stores emails, no generation |
| GET    | `/api/gmail/emails`      | –                                       | Lists already-synced emails (no Gmail call) |
| POST   | `/api/gmail/generate`    | `{"email_id": "..."}`                   | Retrieves context + calls Claude for one stored email |
| POST   | `/api/gmail/auto`        | `{"query": "...", "generate_limit": 3}` (both optional) | Mode 2: sync + auto-generate in one call |

Each processed email is stored (and returned by `/api/gmail/sync`,
`/api/gmail/emails`, and inside `/api/gmail/auto`'s `emails` list) as:

```json
{
  "email_id": "18f2a...",
  "sender": "Jane Client <jane@client.com>",
  "subject": "Quick question about Backup Pro 1TB",
  "clean_body": "Hi team, how much does Backup Pro 1TB cost per month?",
  "detected_product": "Backup Pro 1TB",
  "intent": "pricing inquiry",
  "confidence": 0.9
}
```

`detected_product` comes from matching the email text against the real
product/page names already sitting in the local knowledge base (exact
substring match first, fuzzy `difflib` match as a fallback) — there's no
hard-coded product list, so it's only as good as what you've synced.
`intent` comes from a small ordered set of keyword rules (complaint → pricing
inquiry → comparison → conversion intent → general inquiry → interest as the
default), exactly as specified: "price" → pricing inquiry, "apply"/"book" →
conversion intent, and so on.

`/api/generate` returns:

```json
{
  "ok": true,
  "context_used": { "wordpress_content": [...], "prestashop_products": [...], "frontend_structures": [...], "total_chunks": 7 },
  "result": {
    "html_section": "<section class=\"hero\">...</section><section class=\"features\">...</section><section class=\"testimonials\">...</section><section class=\"cta\">...</section>",
    "seo_suggestions": ["..."],
    "improvement_suggestions": ["..."],
    "cta_variations": ["..."],
    "structure_warnings": []
  }
}
```

`/api/gmail/generate` and the per-email results inside `/api/gmail/auto`
return this exact same shape, plus one extra top-level `"email": {...}` key
holding the processed email record that drove the generation - the frontend
uses it to show "Generated from email · sender — subject" above the preview.

`structure_warnings` is populated if Claude ever drops or renames one of the
four locked sections — that's the code-level enforcement of the design system
constraint, separate from the prompt-level one.

## Worked example

Say you've synced a WordPress page about your backup product and a PrestaShop
product "Backup Pro 1TB" ($9.99, category "Backup Plans"), plus scraped its
live product page.

**Client conversation input:**

> "Hey — can we get the backup plan page to push our summer sale harder?
> Customers keep asking on chat if restoring files is actually fast, so maybe
> address that too."

**What happens:**
1. `retrieval.get_relevant_context()` BM25-searches all three tables for
   tokens like *backup*, *restore*, *fast*, *plan*, *sale*, and returns the
   top ~10 matching chunks (the WordPress page, the PrestaShop product, and
   any scraped sections mentioning restore speed).
2. `claude_client.generate_page_update()` (or `gemini_client`'s, if
   `AI_PROVIDER=gemini`) sends that context plus the message to whichever
   model is active, with the locked Hero/Features/Testimonials/CTA structure.
3. You get back a ready `html_section`, restore-speed-focused
   `seo_suggestions` (e.g. mentioning "fast file restore" in a heading),
   `improvement_suggestions` (e.g. adding a restore-time stat near the
   features section), and a few `cta_variations` built around the sale.

## Worked example — Gmail Auto Mode

Same synced WordPress/PrestaShop content as above. A client emails:

> Subject: Quick question about Backup Pro 1TB
> "Hi team, how much does Backup Pro 1TB cost per month? Also is restore
> actually fast? Thanks, Jane"

Clicking **⚡ Fetch Gmail & Generate Updates** runs:

1. `gmail_client.sync_emails()` fetches the message, extracts the clean text
   (decoding the MIME parts and dropping any quoted reply chain), and stores
   it. `detect_product()` matches "Backup Pro 1TB" directly against the
   PrestaShop catalog already in SQLite (confidence 0.95); `detect_intent()`
   matches `\bhow much\b` → **pricing inquiry** (confidence 0.85).
2. `gmail_client.build_retrieval_query()` feeds `"Backup Pro 1TB"` straight
   into the *same* `retrieval.get_relevant_context()` used by manual mode -
   no separate retrieval path for email.
3. `ai_provider.generate_page_update()` calls the active model (Claude or
   Gemini, whichever `AI_PROVIDER` selects) with the email as `email_context`
   *and* the retrieved website context, both inside the same
   Hero/Features/Testimonials/CTA-locked prompt.
4. The UI's **Email inbox** row for Jane's email shows pills for `Backup Pro
   1TB` and `pricing inquiry`; the generated result appears in the same
   Preview/Suggestions/JSON tabs as manual mode, with a banner reading
   "Generated from email · Jane — Quick question about Backup Pro 1TB".

## Notes on scope

- The frontend scraper uses keyword heuristics against common class/id
  patterns (`hero`, `cta`, `related`, `testimonial`, etc.) rather than one
  hard-coded PrestaShop theme's DOM, since themes vary. If your theme uses
  very different markup, extend `SECTION_KEYWORDS` in `frontend_scraper.py`.
- Retrieval uses SQLite FTS5 with BM25 ranking — real keyword search, no
  external embedding service required. If you later want semantic search,
  swap `retrieval.py`'s ranking for a real embeddings call without touching
  the rest of the system.
- Product detection in `gmail_client.py` only knows about products/pages
  you've already synced from WordPress/PrestaShop - sync those first, or
  emails will fall back to a subject+body keyword search with no detected
  product. Intent detection is intentionally simple keyword rules, not a
  model call, so it's free and instant; swap `INTENT_RULES` for a Claude call
  if you need more nuance later.
- `credentials.json` and `token.json` (Gmail OAuth) and `.env` hold real
  secrets - they're already covered by `.gitignore`. Don't commit them.
- This is a local, single-user tool: there's no auth layer on the Flask API.
  Don't expose it on the open internet as-is.
