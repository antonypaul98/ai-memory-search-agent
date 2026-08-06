import { Api } from "../api.js";
import {
  $,
  escapeHtml,
  setStatus,
  emptyState,
  confBadge,
  skeleton,
  sourceIcon,
  hitExternalId,
  hitSourceType,
  memoryRef,
  boundList,
  RENDER_LIMITS,
} from "../util.js";
import { navigate } from "../router.js";

export function mountAsk(root, initialQuery = "") {
  root.innerHTML = `
    <section class="panel hero-panel">
      <div class="panel-header">
        <h2>Ask Memory</h2>
        <span class="panel-caption">Uses existing chat + retrieval — no new answer engine</span>
      </div>
      <form id="ask-form" class="search-form">
        <label class="sr-only" for="ask-q">Question</label>
        <input id="ask-q" type="search" placeholder="What have I learned about RAG?" autocomplete="off" />
        <button type="submit" id="ask-btn">Ask</button>
      </form>
      <p id="ask-status" class="status" hidden role="status"></p>
      <div id="ask-answer" class="answer-panel" aria-live="polite"></div>
    </section>
  `;
  $("#ask-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    await runAsk(root);
  });

  const q = (initialQuery || "").trim();
  if (q) {
    $("#ask-q", root).value = q;
    void runAsk(root);
  }
}

/** Prefill / re-run when navigating with `#ask/<question>` (V1-7 deep-link). */
export function applyAskQuery(root, query = "") {
  const input = $("#ask-q", root);
  if (!input) return;
  const q = (query || "").trim();
  if (!q) return;
  input.value = q;
  void runAsk(root);
}

function normalizeConfidence(confRaw) {
  if (typeof confRaw === "number") return confRaw;
  if (typeof confRaw === "string" && /high|medium|mid|low/i.test(confRaw)) {
    const c = confRaw.toLowerCase();
    if (c.startsWith("h")) return 0.85;
    if (c.startsWith("m")) return 0.55;
    return 0.3;
  }
  const n = Number(confRaw);
  return Number.isFinite(n) ? n : null;
}

async function runAsk(root) {
  const q = $("#ask-q", root).value.trim();
  const status = $("#ask-status", root);
  const out = $("#ask-answer", root);
  if (!q) {
    setStatus(status, "Ask a question about your saved memories.", "error");
    return;
  }
  setStatus(status, "Thinking over your memories…");
  out.innerHTML = skeleton(2);
  $("#ask-btn", root).disabled = true;
  try {
    const [chat, retrieve] = await Promise.all([
      Api.chat({ question: q, top_k: 6 }, { abortTag: "ask" }),
      Api.retrieve(q, 5, {}, { abortTag: "ask-retrieve" }).catch(() => ({ results: [] })),
    ]);
    const sources = boundList(chat.sources || chat.citations || [], RENDER_LIMITS.askEvidence);
    const alts = boundList((retrieve.results || []).slice(1), 4);
    const confNum = normalizeConfidence(chat.confidence);
    setStatus(
      status,
      confNum != null
        ? `Confidence ${Math.round(confNum * 100)}%`
        : `Confidence ${chat.confidence || "—"}`
    );
    const evidenceRows = sources.length
      ? sources
      : boundList(retrieve.results || [], RENDER_LIMITS.askEvidence);
    out.innerHTML = `
      <article class="answer-card">
        <div class="card-top">${confBadge(confNum)} <span class="muted">Grounded answer</span></div>
        <div class="answer-body">${escapeHtml(chat.answer || chat.answer_markdown || "No answer returned.").replaceAll("\n", "<br/>")}</div>
      </article>
      <section class="panel">
        <h3>Evidence</h3>
        <div class="list">
          ${
            evidenceRows.length
              ? evidenceRows
                  .map((s) => {
                    const title = s.title || s.result?.title || "Source";
                    const text = s.matched_text || s.snippet || s.result?.matched_text || "";
                    const ext = hitExternalId(s.result || s);
                    const src = hitSourceType(s.result || s);
                    if (!ext) {
                      return `<div class="list-row static"><span class="list-main"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text).slice(0, 160)}</small></span></div>`;
                    }
                    return `<button type="button" class="list-row" data-open="${escapeHtml(memoryRef(src, ext))}">
                <span class="src" aria-hidden="true">${sourceIcon(src)}</span>
                <span class="list-main"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text).slice(0, 160)}</small></span>
              </button>`;
                  })
                  .join("")
              : emptyState("No evidence returned")
          }
        </div>
      </section>
      ${
        alts.length
          ? `<section class="panel"><h3>Alternative matches</h3><div class="list">${alts
              .map((h) => {
                const r = h.result || {};
                const src = hitSourceType(r);
                const ext = hitExternalId(r);
                return `<button type="button" class="list-row" data-open="${escapeHtml(memoryRef(src, ext))}">
                  <span class="src" aria-hidden="true">${sourceIcon(src)}</span>
                  <span class="list-main"><strong>${escapeHtml(r.title)}</strong><small>${escapeHtml(h.explanation?.why || r.why_matched || "")}</small></span>
                </button>`;
              })
              .join("")}</div></section>`
          : ""
      }
    `;
    out.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => navigate("memory", btn.dataset.open));
    });
  } catch (err) {
    setStatus(status, err.message, "error");
    out.innerHTML = emptyState("Ask failed", err.message);
  } finally {
    $("#ask-btn", root).disabled = false;
  }
}
