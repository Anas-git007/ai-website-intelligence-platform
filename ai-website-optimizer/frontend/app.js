const API_BASE = "";

async function api(path, options = {}) {
  const resp = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try {
    body = await resp.json();
  } catch (_) {
    body = null;
  }
  if (!resp.ok) {
    const message = (body && (body.error || body.detail)) || `Request failed (${resp.status})`;
    const err = new Error(typeof message === "string" ? message : JSON.stringify(message));
    err.body = body;
    throw err;
  }
  return body;
}

/* ---------------- Status pills ---------------- */

async function refreshStatus() {
  try {
    const counts = await api("/api/status");
    setPill("pill-wordpress", counts.wordpress_content);
    setPill("pill-prestashop", counts.prestashop_products);
    setPill("pill-frontend", counts.frontend_sections);
    setPill("pill-gmail", counts.emails);
  } catch (err) {
    console.warn("Could not load status:", err.message);
  }
}

async function refreshAiProviderBadge() {
  const badge = document.getElementById("ai-provider-badge");
  try {
    const health = await api("/api/health");
    badge.textContent = `AI: ${health.ai_provider} · ${health.ai_model}`;
  } catch (err) {
    badge.textContent = "AI: unavailable";
  }
}

function setPill(id, count) {
  const el = document.getElementById(id);
  if (!el) return;
  const strong = el.querySelector("strong");
  strong.textContent = count;
  el.classList.toggle("is-populated", count > 0);
}

/* ---------------- WordPress sync ---------------- */

document.getElementById("btn-sync-wordpress").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync-wordpress");
  const result = document.getElementById("result-wordpress");
  btn.disabled = true;
  result.className = "source-card__result";
  result.textContent = "Syncing…";
  try {
    const data = await api("/api/ingest/wordpress", { method: "POST" });
    const parts = Object.entries(data.summary).map(([type, val]) => `${type}: ${val}`);
    result.textContent = parts.join(" · ");
    result.classList.add("is-success");
    refreshStatus();
  } catch (err) {
    result.textContent = err.message;
    result.classList.add("is-error");
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- PrestaShop sync ---------------- */

document.getElementById("btn-sync-prestashop").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync-prestashop");
  const result = document.getElementById("result-prestashop");
  const limitVal = document.getElementById("input-ps-limit").value;
  btn.disabled = true;
  result.className = "source-card__result";
  result.textContent = "Syncing…";
  try {
    const data = await api("/api/ingest/prestashop", {
      method: "POST",
      body: JSON.stringify({ limit: limitVal ? Number(limitVal) : null }),
    });
    result.textContent = `${data.products_ingested} products ingested`;
    result.classList.add("is-success");
    refreshStatus();
  } catch (err) {
    result.textContent = err.message;
    result.classList.add("is-error");
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- Frontend scrape ---------------- */

document.getElementById("btn-sync-frontend").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync-frontend");
  const result = document.getElementById("result-frontend");
  const urls = document
    .getElementById("input-frontend-urls")
    .value.split("\n")
    .map((u) => u.trim())
    .filter(Boolean);

  if (urls.length === 0) {
    result.className = "source-card__result is-error";
    result.textContent = "Add at least one URL.";
    return;
  }

  btn.disabled = true;
  result.className = "source-card__result";
  result.textContent = "Scraping…";
  try {
    const data = await api("/api/ingest/frontend", {
      method: "POST",
      body: JSON.stringify({ urls }),
    });
    const parts = Object.entries(data.summary).map(
      ([url, val]) => `${new URL(url).pathname}: ${val}`
    );
    result.textContent = parts.join(" · ");
    result.classList.add("is-success");
    refreshStatus();
  } catch (err) {
    result.textContent = err.message;
    result.classList.add("is-error");
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- Generate ---------------- */

function renderList(id, items) {
  const ul = document.getElementById(id);
  ul.innerHTML = "";
  (items || []).forEach((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    ul.appendChild(li);
  });
}

/**
 * Trigger a client-side download of the generated html_file.
 * Called by the Download button in the results panel.
 */
function downloadGeneratedPage(htmlContent) {
  const blob = new Blob([htmlContent], { type: "text/html" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "generated-page.html";
  a.click();
  URL.revokeObjectURL(a.href);
}

/**
 * Renders a /api/generate-shaped response ({ result, context_used, email? })
 * into the shared results panel. Used by the manual textarea flow AND by
 * both Gmail-driven flows (per-email "Generate" and full Auto mode), so
 * whichever path triggered generation, the output lands in the same place.
 *
 * Master prompt v3 contract:
 *   result.html_file   — complete self-contained HTML document
 *   result.download_button — standalone button HTML snippet (informational)
 *   result.seo_suggestions / improvement_suggestions / cta_variations — lists
 *   result.structure_warnings — added by finalize_result() on the server
 */
function renderGenerationResult(data) {
  const { result, context_used, email } = data;

  document.getElementById("empty-state").hidden = true;
  document.getElementById("results").hidden = false;

  // Source banner: shown only when this result came from an email.
  const banner = document.getElementById("source-banner");
  if (email) {
    banner.hidden = false;
    banner.textContent = `Generated from email · ${email.sender} — "${email.subject}"`;
  } else {
    banner.hidden = true;
  }

  // ------------------------------------------------------------------
  // Preview — render the full self-contained html_file directly.
  // The generated document already has its own <style> and <script> tags
  // so we don't inject any extra styles here (unlike the old html_section
  // approach which needed PREVIEW_STYLES to be added by the UI).
  // ------------------------------------------------------------------
  const frame = document.getElementById("preview-frame");
  frame.srcdoc = result.html_file || "";

  // Download button in the results panel toolbar
  let dlBtn = document.getElementById("btn-download-page");
  if (!dlBtn) {
    dlBtn = document.createElement("button");
    dlBtn.id = "btn-download-page";
    dlBtn.type = "button";
    dlBtn.className = "btn btn--small";
    dlBtn.textContent = "⬇ Download HTML";
    // Insert after the tabs row
    const tabs = document.querySelector(".tabs");
    if (tabs) tabs.insertAdjacentElement("afterend", dlBtn);
  }
  dlBtn.onclick = () => downloadGeneratedPage(result.html_file || "");

  // Structure warnings
  const warningEl = document.getElementById("structure-warning");
  if (result.structure_warnings && result.structure_warnings.length) {
    warningEl.hidden = false;
    warningEl.textContent = "Structure check: " + result.structure_warnings.join(" · ");
  } else {
    warningEl.hidden = true;
  }

  // Suggestions
  renderList("list-seo", result.seo_suggestions);
  renderList("list-improvements", result.improvement_suggestions);
  renderList("list-cta", result.cta_variations);

  // Raw JSON
  document.getElementById("json-view").textContent = JSON.stringify(data, null, 2);
}

document.getElementById("btn-generate").addEventListener("click", async () => {
  const btn = document.getElementById("btn-generate");
  const status = document.getElementById("generate-status");
  const message = document.getElementById("input-client-message").value.trim();

  if (!message) {
    status.className = "generate-status is-error";
    status.textContent = "Describe what the client wants first.";
    return;
  }

  btn.disabled = true;
  status.className = "generate-status is-loading";
  status.textContent = "Retrieving context and generating…";

  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ client_message: message }),
    });
    renderGenerationResult(data);
    status.className = "generate-status";
    status.textContent = `Done · used ${data.context_used.total_chunks} context chunk(s)`;
  } catch (err) {
    status.className = "generate-status is-error";
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- Gmail ---------------- */

const generatedEmailIds = new Set();

function intentPillClass(intent) {
  if (intent === "complaint") return "is-complaint";
  if (intent === "pricing inquiry") return "is-pricing";
  if (intent === "conversion intent") return "is-conversion";
  return "";
}

function renderEmailList(emails) {
  const list = document.getElementById("email-list");
  const empty = document.getElementById("email-empty-state");

  if (!emails || emails.length === 0) {
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  list.innerHTML = "";
  emails.forEach((email) => {
    const row = document.createElement("div");
    row.className = "email-row";

    const main = document.createElement("div");
    main.className = "email-row__main";
    const sender = document.createElement("div");
    sender.className = "email-row__sender";
    sender.textContent = email.sender || "(unknown sender)";
    const subject = document.createElement("div");
    subject.className = "email-row__subject";
    subject.textContent = email.subject || "(no subject)";
    main.append(sender, subject);

    const meta = document.createElement("div");
    meta.className = "email-row__meta";

    const productPill = document.createElement("span");
    productPill.className = "tag-pill tag-pill--product";
    productPill.textContent = email.detected_product || "no product detected";
    meta.appendChild(productPill);

    const intentPill = document.createElement("span");
    intentPill.className = `tag-pill tag-pill--intent ${intentPillClass(email.intent)}`;
    intentPill.textContent = email.intent || "unknown";
    meta.appendChild(intentPill);

    const confidence = document.createElement("span");
    confidence.className = "email-row__confidence";
    confidence.textContent = `${Math.round((email.confidence || 0) * 100)}%`;
    meta.appendChild(confidence);

    const actionBtn = document.createElement("button");
    actionBtn.type = "button";
    actionBtn.className = "btn btn--small";
    actionBtn.textContent = generatedEmailIds.has(email.email_id)
      ? "View result"
      : "Generate from this email";
    actionBtn.addEventListener("click", () => generateFromEmail(email.email_id, actionBtn));

    row.append(main, meta, actionBtn);
    list.appendChild(row);
  });
}

async function loadStoredEmails() {
  try {
    const data = await api("/api/gmail/emails");
    renderEmailList(data.emails);
  } catch (err) {
    console.warn("Could not load stored emails:", err.message);
  }
}

async function generateFromEmail(emailId, triggerBtn) {
  const result = document.getElementById("result-gmail");
  if (triggerBtn) {
    triggerBtn.disabled = true;
    triggerBtn.textContent = "Generating…";
  }
  try {
    const data = await api("/api/gmail/generate", {
      method: "POST",
      body: JSON.stringify({ email_id: emailId }),
    });
    renderGenerationResult(data);
    generatedEmailIds.add(emailId);
    document.querySelector('.tab[data-tab="preview"]').click();
    document.getElementById("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    result.className = "source-card__result is-error";
    result.textContent = err.message;
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = generatedEmailIds.has(emailId)
        ? "View result"
        : "Generate from this email";
    }
  }
}

document.getElementById("btn-sync-gmail").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync-gmail");
  const result = document.getElementById("result-gmail");
  const query = document.getElementById("input-gmail-query").value.trim();

  btn.disabled = true;
  result.className = "source-card__result";
  result.textContent = "Syncing…";
  try {
    const data = await api("/api/gmail/sync", {
      method: "POST",
      body: JSON.stringify(query ? { query } : {}),
    });
    renderEmailList(data.emails);
    result.textContent = `${data.emails.length} email(s) synced`;
    result.classList.add("is-success");
    refreshStatus();
  } catch (err) {
    result.textContent = err.message;
    result.classList.add("is-error");
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-gmail-auto").addEventListener("click", async () => {
  const btn = document.getElementById("btn-gmail-auto");
  const result = document.getElementById("result-gmail");
  const query = document.getElementById("input-gmail-query").value.trim();

  btn.disabled = true;
  result.className = "source-card__result";
  result.textContent = "Fetching, processing, and generating…";
  try {
    const data = await api("/api/gmail/auto", {
      method: "POST",
      body: JSON.stringify(query ? { query } : {}),
    });

    renderEmailList(data.emails);
    data.generated.forEach((g) => {
      if (g.ok) generatedEmailIds.add(g.email_id);
    });
    renderEmailList(data.emails); // re-render so "View result" labels pick up

    const succeeded = data.generated.filter((g) => g.ok);
    if (succeeded.length > 0) {
      renderGenerationResult(succeeded[0]);
      document.querySelector('.tab[data-tab="preview"]').click();
    }

    result.textContent = `Synced ${data.emails.length} · generated ${succeeded.length}/${data.generated.length} page update(s)`;
    result.classList.add("is-success");
    refreshStatus();
  } catch (err) {
    result.textContent = err.message;
    result.classList.add("is-error");
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- Tabs ---------------- */

document.querySelectorAll(".tab").forEach((tabBtn) => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("is-active"));
    tabBtn.classList.add("is-active");
    document
      .querySelector(`.tab-panel[data-panel="${tabBtn.dataset.tab}"]`)
      .classList.add("is-active");
  });
});

refreshStatus();
loadStoredEmails();
refreshAiProviderBadge();