import { Api, clearApiCache } from "../api.js";
import {
  $,
  escapeHtml,
  sourceFilterOptionsHtml,
  setStatus,
  emptyState,
  confBadge,
  skeleton,
  sourceIcon,
  sourceLabel,
  hitExternalId,
  hitSourceType,
  memoryRef,
  externalLink,
  boundList,
  RENDER_LIMITS,
} from "../util.js";
import { navigate } from "../router.js";

export function mountSearch(root, initialQuery = "") {
  root.innerHTML = `
    <section class="panel hero-panel">
      <div class="panel-header">
        <h2>Universal search</h2>
        <span class="panel-caption">YouTube · Articles · PDFs · GitHub · Bookmarks</span>
      </div>
      <form id="search-form" class="search-form">
        <label class="sr-only" for="search-q">Search query</label>
        <input id="search-q" type="search" placeholder="Find the Docker PDF, Kubernetes repo, RAG article…" autocomplete="off" />
        <button type="submit" id="search-btn">Search</button>
      </form>
      <div class="filters" id="search-filters">
        <label class="sr-only" for="f-source">Source</label>
        <select id="f-source" aria-label="Source">${sourceFilterOptionsHtml()}</select>
        <label class="sr-only" for="f-date-from">From date</label>
        <input id="f-date-from" type="date" aria-label="From date" />
        <label class="sr-only" for="f-date-to">To date</label>
        <input id="f-date-to" type="date" aria-label="To date" />
        <label class="sr-only" for="f-save-reason">Save reason</label>
        <input id="f-save-reason" type="text" placeholder="Why I saved it" aria-label="Save reason" />
        <label class="sr-only" for="f-topic">Topic</label>
        <input id="f-topic" type="text" placeholder="Topic" aria-label="Topic" />
        <label class="sr-only" for="f-connector">Connector</label>
        <input id="f-connector" type="text" placeholder="Connector id" aria-label="Connector" />
        <label class="sr-only" for="f-language">Language</label>
        <input id="f-language" type="text" placeholder="Language" aria-label="Language" />
        <label class="sr-only" for="f-channel">Creator</label>
        <input id="f-channel" type="text" placeholder="Creator / channel" aria-label="Creator" />
        <label class="sr-only" for="f-min-conf">Min confidence</label>
        <input id="f-min-conf" type="number" min="0" max="1" step="0.1" placeholder="Min confidence" aria-label="Min confidence" />
      </div>
      <p id="search-status" class="status" hidden role="status"></p>
      <div id="search-results" class="results" aria-live="polite"></div>
    </section>
  `;

  $("#search-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    await runSearch(root);
  });

  const q = (initialQuery || "").trim();
  if (q) {
    $("#search-q", root).value = q;
    void runSearch(root);
  }
}

/** Prefill / re-run when navigating with `#search/<query>` (V1-7 deep-link). */
export function applySearchQuery(root, query = "") {
  const input = $("#search-q", root);
  if (!input) return;
  const q = (query || "").trim();
  if (!q) return;
  input.value = q;
  void runSearch(root);
}

async function runSearch(root) {
  const q = $("#search-q", root).value.trim();
  const status = $("#search-status", root);
  const out = $("#search-results", root);
  if (!q) {
    setStatus(status, "Enter a search query.", "error");
    return;
  }
  const filters = {
    language: $("#f-language", root).value.trim() || undefined,
    channel: $("#f-channel", root).value.trim() || undefined,
    date_from: $("#f-date-from", root).value || undefined,
    date_to: $("#f-date-to", root).value || undefined,
    save_reason: $("#f-save-reason", root).value.trim() || undefined,
    min_confidence: $("#f-min-conf", root).value || undefined,
  };
  const sourceFilter = $("#f-source", root).value;
  const topicFilter = $("#f-topic", root).value.trim().toLowerCase();
  const connectorFilter = $("#f-connector", root).value.trim().toLowerCase();
  setStatus(status, "Searching…");
  out.innerHTML = skeleton(3);
  $("#search-btn", root).disabled = true;
  try {
    const data = await Api.retrieve(q, 20, filters, { abortTag: "search" });
    let hits = data.results || [];
    if (sourceFilter) {
      hits = hits.filter((h) => hitSourceType(h.result) === sourceFilter);
    }
    if (connectorFilter) {
      hits = hits.filter((h) =>
        String(h.result?.connector_id || "").toLowerCase().includes(connectorFilter)
      );
    }
    if (topicFilter) {
      hits = hits.filter((h) => {
        const topics = h.result?.topics || h.explanation?.topics || [];
        const blob = `${h.result?.title || ""} ${h.result?.matched_text || ""} ${topics.join(" ")}`.toLowerCase();
        return blob.includes(topicFilter);
      });
    }
    const total = hits.length;
    hits = boundList(hits, RENDER_LIMITS.searchResults);
    setStatus(
      status,
      `${total} result${total === 1 ? "" : "s"}${total > hits.length ? ` (showing ${hits.length})` : ""} · path: ${(data.search_path || []).join(" → ")}`
    );
    if (!hits.length) {
      out.innerHTML = emptyState("No matches", "Try another phrase or clear filters.");
      return;
    }
    out.innerHTML = hits
      .map((hit) => {
        const r = hit.result || {};
        const ex = hit.explanation || {};
        const source = hitSourceType(r);
        const ext = hitExternalId(r);
        const link = externalLink(r.original_url || r.url, "Open source");
        return `
        <article class="result-card">
          <div class="card-top">
            <span class="src-badge">${sourceIcon(source)} ${sourceLabel(source)}</span>
            ${confBadge(ex.confidence ?? r.confidence)}
            <span class="muted">${escapeHtml(r.connector_id || "")}</span>
          </div>
          <h3>${escapeHtml(r.title || "Untitled")}</h3>
          <p class="muted">${escapeHtml(r.channel || "")}</p>
          <p class="evidence">${escapeHtml(r.matched_text || "").slice(0, 280)}</p>
          <p class="why"><strong>Why:</strong> ${escapeHtml(ex.why || r.why_matched || "")}</p>
          <div class="card-actions">
            <button type="button" class="btn-secondary" data-open="${escapeHtml(memoryRef(source, ext))}">Open memory</button>
            ${link}
          </div>
        </article>`;
      })
      .join("");
    out.querySelectorAll("[data-open]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("memory", btn.dataset.open))
    );
  } catch (err) {
    setStatus(status, err.message, "error");
    out.innerHTML = emptyState("Search failed", err.message);
  } finally {
    $("#search-btn", root).disabled = false;
  }
}
