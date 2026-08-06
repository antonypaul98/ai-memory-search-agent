import { Api, clearApiCache } from "../api.js";
import {
  $,
  escapeHtml,
  formatWhen,
  emptyState,
  skeleton,
  setStatus,
  boundList,
  RENDER_LIMITS,
} from "../util.js";

export function mountImports(root) {
  root.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <h2>Import manager</h2>
        <span class="panel-caption">Import APIs · connector health</span>
      </div>
      <div id="import-health" class="chip-row" aria-live="polite">${skeleton(2)}</div>
      <div id="import-list">${skeleton(3)}</div>
      <div id="import-detail" hidden></div>
    </section>
  `;
  refresh(root);
}

async function refresh(root) {
  const list = $("#import-list", root);
  const healthEl = $("#import-health", root);
  try {
    const [health, imports] = await Promise.all([
      Api.connectorsHealth(),
      Api.imports(RENDER_LIMITS.importList),
    ]);
    healthEl.innerHTML = (health.connectors || [])
      .map(
        (c) =>
          `<span class="chip ${c.healthy ? "ok" : "bad"}" title="${escapeHtml(c.detail || "")}">${escapeHtml(c.connector_id)} · ${c.healthy ? "healthy" : "down"}</span>`
      )
      .join("") || emptyState("No connectors");
    const rows = boundList(imports.imports || [], RENDER_LIMITS.importList);
    if (!rows.length) {
      list.innerHTML = emptyState(
        "No imports yet",
        "Use Capture or bookmarks import to create runs."
      );
      return;
    }
    list.innerHTML = `<div class="list">${rows
      .map(
        (r) => `
      <button type="button" class="list-row" data-import="${escapeHtml(r.import_id)}">
        <span class="src" aria-hidden="true">⇪</span>
        <span class="list-main">
          <strong>${escapeHtml(r.connector_id)}</strong>
          <small>${escapeHtml(r.status)} · ${r.completed_items || 0}/${r.total_items || 0} ok · ${r.failed_items || 0} failed · ${formatWhen(r.created_at)}</small>
        </span>
      </button>`
      )
      .join("")}</div>`;
    list.querySelectorAll("[data-import]").forEach((btn) =>
      btn.addEventListener("click", () => showImport(root, btn.dataset.import))
    );
  } catch (err) {
    list.innerHTML = emptyState("Imports unavailable", err.message);
  }
}

async function showImport(root, id) {
  const detail = $("#import-detail", root);
  detail.hidden = false;
  detail.innerHTML = skeleton(2);
  try {
    const run = await Api.importDetail(id);
    const started = run.created_at ? new Date(run.created_at).getTime() : 0;
    const updated = run.updated_at ? new Date(run.updated_at).getTime() : started;
    const durationMs = Math.max(0, updated - started);
    const items = boundList(run.items || [], RENDER_LIMITS.importItems);
    const truncated =
      (run.items || []).length > RENDER_LIMITS.importItems
        ? `<p class="muted">Showing first ${RENDER_LIMITS.importItems} of ${(run.items || []).length} items.</p>`
        : "";
    detail.innerHTML = `
      <div class="panel nested">
        <div class="panel-header">
          <h3>${escapeHtml(run.connector_id)} · ${escapeHtml(run.status)}</h3>
          <div class="row">
            <button type="button" class="btn-secondary" id="imp-resume" ${run.status === "running" ? "disabled" : ""}>Resume</button>
            <button type="button" class="btn-secondary" id="imp-cancel" ${["completed", "cancelled"].includes(run.status) ? "disabled" : ""}>Cancel</button>
            <button type="button" class="btn-secondary" id="imp-refresh">Refresh</button>
          </div>
        </div>
        <p class="muted">${escapeHtml(run.detail || "")} · duration ~${Math.round(durationMs / 1000)}s</p>
        ${truncated}
        <div class="list compact">
          ${
            items.length
              ? items
                  .map(
                    (i) => `
            <div class="list-row static">
              <span class="list-main">
                <strong>${escapeHtml(i.title || i.url)}</strong>
                <small>${escapeHtml(i.status)} · ${escapeHtml(i.detail || i.error || "")}</small>
              </span>
            </div>`
                  )
                  .join("")
              : emptyState("No items")
          }
        </div>
        <p id="imp-status" class="status" hidden role="status"></p>
      </div>
    `;
    $("#imp-refresh", detail).onclick = () => showImport(root, id);
    $("#imp-resume", detail).onclick = async () => {
      try {
        await Api.importStart(id);
        clearApiCache("imports");
        clearApiCache("agent/status");
        setStatus($("#imp-status", detail), "Resumed", "success");
        showImport(root, id);
        refresh(root);
      } catch (err) {
        setStatus($("#imp-status", detail), err.message, "error");
      }
    };
    $("#imp-cancel", detail).onclick = async () => {
      try {
        await Api.importCancel(id);
        clearApiCache("imports");
        clearApiCache("agent/status");
        setStatus($("#imp-status", detail), "Cancelled", "success");
        showImport(root, id);
        refresh(root);
      } catch (err) {
        setStatus($("#imp-status", detail), err.message, "error");
      }
    };
  } catch (err) {
    detail.innerHTML = emptyState("Import detail failed", err.message);
  }
}
