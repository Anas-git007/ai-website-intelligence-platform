# AI Website Intelligence & Content Optimizer

An AI-powered content intelligence platform that ingests real content from a **WordPress site**, a **PrestaShop store**, **live storefront pages**, and **Gmail conversations**, stores everything in a searchable local knowledge base, and generates **production-ready HTML content**, **SEO recommendations**, and **CTA suggestions** using **Claude or Gemini**.

Built during an **AI Automation Internship**.

> **Internship Final Version:** This repository contains the final version completed during my internship. The project was actively developed until the internship concluded, and this represents the last fully working implementation produced during that period. A later production-hardening and deployment phase had been planned, but the internship ended before that stage could be completed. The current version includes the complete retrieval pipeline, AI generation workflow, Gmail integration, and multi-source content ingestion architecture developed during the internship.

---

# 1. What This Project Does

Small e-commerce and marketing teams frequently need to update landing pages, product pages, or promotional content based on client requests, customer emails, or changes in product catalogs. Producing copy that remains consistent with existing website content, product data, and brand messaging is often the slowest part of that workflow.

This platform automates that process by combining **multi-source content ingestion**, **local retrieval-augmented generation (RAG)**, and **AI-assisted content generation** into a single workflow:

1. **Ingests real content** from three sources: a WordPress REST API, a PrestaShop Webservice API (products and categories), and live storefront pages that are scraped and structurally parsed.
2. **Stores everything** in a local SQLite knowledge base with **FTS5 full-text search and BM25 ranking**, allowing relevant content to be retrieved based on semantic relevance rather than simple keyword matching.
3. **Optionally synchronizes Gmail** conversations, automatically detecting which product a customer is referring to and classifying the intent of the message (pricing inquiry, complaint, comparison request, conversion intent, or general inquiry).
4. **Accepts a plain-English request** typed manually or generated from a synced email and retrieves the most relevant previously-ingested website and product content.
5. **Calls an AI model** (Claude by default or Gemini as an interchangeable provider) with the retrieved context and a predefined four-section page structure (Hero → Features → Testimonials → CTA).
6. **Returns a ready-to-paste HTML page section**, along with SEO suggestions, UX improvements, and alternative call-to-action variations.
7. **Validates the generated structure in code** after the AI response is received, ensuring that the required page layout cannot silently drift even if the model returns malformed or incomplete output.

The result is a practical **RAG-powered website optimization system** that connects existing business content, customer communication, and generative AI into a single automated content workflow.

---

# 2. Architecture

```text
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
                                                      │ AI Provider  │
  Client conversation ──► context retrieval ────────►│(Claude/Gemini)│
  (typed into the UI)     (top ~10 relevant chunks)  └──────┬───────┘
                                  ▲                          │
                                  │                          ▼
  Gmail ──► gmail_client.py ──────┘           html_section + seo_suggestions +
  (OAuth2 + real API)   detected_product       improvement_suggestions + cta_variations
  parse + detect        used as retrieval query
```

The AI call goes through a one-line dispatcher (`ai_provider.py`) so the entire pipeline works identically whether `AI_PROVIDER` is set to `claude` or `gemini`. Both providers share the same prompt-building logic and response-structure validation implemented in `ai_prompt.py`.

## Core Modules

| Module                 | Responsibility                                                                        |
| ---------------------- | ------------------------------------------------------------------------------------- |
| `app.py`               | Flask application that serves the frontend UI and all API routes                      |
| `config.py`            | Loads configuration from `.env`                                                       |
| `db.py`                | SQLite schema management, upserts, and FTS5/BM25 search                               |
| `wordpress_client.py`  | Retrieves real content from the WordPress REST API                                    |
| `prestashop_client.py` | Retrieves products and categories from the PrestaShop Webservice API                  |
| `frontend_scraper.py`  | Fetches and structures live storefront pages using BeautifulSoup                      |
| `gmail_client.py`      | Gmail OAuth2 integration, email parsing, product detection, and intent classification |
| `retrieval.py`         | Merges BM25 search results across all content sources                                 |
| `ai_prompt.py`         | Shared prompt construction and post-response validation                               |
| `claude_client.py`     | Anthropic Messages API integration                                                    |
| `gemini_client.py`     | Google Gemini API integration                                                         |
| `ai_provider.py`       | Dispatches requests to Claude or Gemini based on configuration                        |

## Frontend

A lightweight HTML/CSS/JavaScript single-page interface is served directly by the Flask backend. The interface provides panels for syncing content sources, submitting manual generation requests, browsing synchronized Gmail messages, and reviewing generated content across **Preview**, **Suggestions**, and **Raw JSON** tabs.

---

# 3. Key Engineering Details

* **No mock data by design** — every ingestion path performs real HTTP/API calls (WordPress, PrestaShop, live storefront scraping, Gmail, and AI providers).
* **Local full-text search** — retrieval is implemented using SQLite FTS5 with BM25 ranking, avoiding the need for an external vector database.
* **Provider-agnostic AI architecture** — Claude and Gemini are interchangeable through a single configuration flag.
* **Locked output structure** — the required Hero → Features → Testimonials → CTA layout is enforced both in the prompt and through post-generation validation.
* **Gmail integration** — email requests use the same retrieval and generation pipeline as manually entered requests.
* **Rule-based product and intent detection** — product matching combines exact and fuzzy matching against the synchronized catalog without requiring an additional AI classification step.
* **Privacy-conscious Gmail handling** — the application defaults to read-only Gmail access and tracks processed emails locally.
* **Secure repository setup** — `.env`, `credentials.json`, and OAuth tokens are excluded from version control through `.gitignore`.

---

# 4. Tech Stack

* **Backend:** Python 3.10+, Flask
* **Database:** SQLite with FTS5 (BM25 full-text search)
* **AI:** Anthropic Claude API and Google Gemini API
* **Content Sources:** WordPress REST API, PrestaShop Webservice API, live storefront scraping
* **Email:** Gmail API (OAuth2)
* **Frontend:** HTML, CSS, and JavaScript

---

# 5. Project Structure

```text
ai-website-intelligence-platform/
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── db.py
│   ├── wordpress_client.py
│   ├── prestashop_client.py
│   ├── frontend_scraper.py
│   ├── gmail_client.py
│   ├── retrieval.py
│   ├── ai_prompt.py
│   ├── claude_client.py
│   ├── gemini_client.py
│   ├── ai_provider.py
│   ├── test.py
│   ├── requirements.txt
│   ├── .env
│   └── data/
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```

---

# 6. Configuration

All configuration is managed through `backend/.env`.

| Variable                    | Purpose                                               |
| --------------------------- | ----------------------------------------------------- |
| `WORDPRESS_BASE_URL`        | WordPress site URL                                    |
| `WORDPRESS_USERNAME`        | WordPress username                                    |
| `WORDPRESS_APP_PASSWORD`    | WordPress application password                        |
| `WORDPRESS_POST_TYPES`      | Post types to synchronize                             |
| `PRESTASHOP_BASE_URL`       | PrestaShop store URL                                  |
| `PRESTASHOP_API_KEY`        | PrestaShop Webservice API key                         |
| `ANTHROPIC_API_KEY`         | Claude API key                                        |
| `ANTHROPIC_MODEL`           | Claude model selection                                |
| `AI_PROVIDER`               | `claude` or `gemini`                                  |
| `GEMINI_API_KEY`            | Gemini API key                                        |
| `GMAIL_CREDENTIALS_PATH`    | Gmail OAuth credentials                               |
| `GMAIL_TOKEN_PATH`          | Cached Gmail OAuth token                              |
| `GMAIL_MARK_AS_READ`        | Whether synchronized emails should be marked as read  |
| `GMAIL_AUTO_GENERATE_LIMIT` | Maximum emails processed per automatic generation run |

---

# 7. Usage

```bash
cd ai-website-intelligence-platform/backend

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # Add your API credentials

python app.py
```

The application serves both the backend API and frontend interface at:

```text
http://localhost:8000
```

## Typical Workflow

1. Synchronize **WordPress**, **PrestaShop**, and/or **live storefront pages**.
2. Generate content either from a manual request or directly from a synchronized Gmail email.
3. Review the generated HTML, SEO suggestions, and CTA recommendations.
4. Copy the generated content into the appropriate WordPress page or PrestaShop CMS block.

---

# 8. What I Built During the Internship

* Designed a **multi-source retrieval-augmented generation (RAG) architecture** combining REST APIs, XML APIs, and scraped HTML content.
* Implemented **SQLite FTS5 with BM25 ranking** as a lightweight local retrieval engine.
* Built a **provider-agnostic AI integration layer** supporting both Claude and Gemini.
* Implemented **Gmail-driven content generation**, including OAuth2 integration, MIME parsing, and product/intent detection.
* Enforced a **validated output contract** to guarantee consistent page structure.
* Worked with **real production-style integrations** rather than mocked data, handling authentication, pagination, HTML variability, and API interoperability across multiple systems.

---

# 9. Current Scope and Planned Extensions

This repository contains the final version completed during the internship. The core retrieval, synchronization, and AI generation architecture is fully implemented and operational. The items below represent enhancements that were planned for a later production-hardening phase after the internship period.

### Planned Improvements

* Add a comprehensive **unit and integration test suite**
* Implement **authentication and authorization** for hosted deployments
* Improve **theme-independent storefront parsing**
* Add additional AI providers beyond Claude and Gemini
* Replace rule-based intent detection with a lightweight ML/NLP classifier
* Add **retry and exponential backoff** for external API calls
* Integrate a production-grade **secrets manager**
* Add **CI/CD automation**, linting, and formatting checks
* Refine the frontend UI for a more polished production experience

---

# Author

**Muhammad Anas**

Bachelor of Computer Science (Data Analysis)
University of Messina (UNIME), Italy

---

# License

This project is released under the **MIT License**.
