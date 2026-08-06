import { Api } from "../api.js";
import {
  escapeHtml,
  formatWhen,
  sourceIcon,
  sourceLabel,
  emptyState,
  skeleton,
  parseMemoryRef,
  memoryRef,
  externalLink,
  hitExternalId,
  hitSourceType,
  boundList,
  setStatus,
} from "../util.js";
import { navigate } from "../router.js";

export async function renderMemory(root, param, { signal } = {}) {
  root.innerHTML = skeleton(3);
  const { sourceType, externalId } = parseMemoryRef(param);
  if (!externalId) {
    root.innerHTML = emptyState(
      "Select a memory",
      "Open one from search, timeline, or dashboard."
    );
    return;
  }
  const opts = { abortTag: "memory", signal };
  try {
    let universal = null;
    let youtube = null;
    let related = { items: [] };
    let lifecycle = [];
    let evidence = [];
    let importsTouching = [];

    try {
      universal = await Api.memoryByExternal(sourceType || "youtube", externalId, opts);
      lifecycle = await Api.memoryLifecycle(universal.memory_id, opts).catch(() => []);
    } catch {
      /* optional when UMS row missing */
    }

    const resolvedType = sourceType || universal?.source_type || "youtube";
    if (resolvedType === "youtube") {
      youtube = await Api.youtubeMemory(externalId, opts).catch(() => null);
      related = await Api.youtubeRelated(externalId, opts).catch(() => ({ items: [] }));
    }

    const title = youtube?.title || universal?.title || externalId;
    const author = youtube?.channel || universal?.source_author || "";
    const url = youtube?.url || universal?.canonical_url || "";
    const connector =
      youtube?.connector_id ||
      universal?.provenance?.connector_id ||
      `${resolvedType}.v1`;

    try {
      const ret = await Api.retrieve(title.slice(0, 120), 4, {}, opts);
      evidence = (ret.results || []).filter((h) => {
        const r = h.result || {};
        return hitExternalId(r) === externalId || hitSourceType(r) === resolvedType;
      });
      if (!evidence.length) evidence = boundList(ret.results || [], 2);
    } catch {
      evidence = [];
    }

    try {
      const runs = await Api.imports(30, opts);
      importsTouching = (runs.imports || []).filter(
        (r) =>
          String(r.connector_id || "").includes(resolvedType) ||
          String(r.detail || "").includes(externalId)
      );
    } catch {
      importsTouching = [];
    }

    if (signal?.aborted) return;

    const stages = youtube?.pipeline_stages || [];
    const linkHtml = externalLink(url, url);
    root.innerHTML = `
      <section class="panel">
        <div class="panel-header">
          <h2><span aria-hidden="true">${sourceIcon(resolvedType)}</span> ${escapeHtml(title)}</h2>
          <span class="panel-caption">${sourceLabel(resolvedType)} · ${escapeHtml(connector)}</span>
        </div>
        <p class="muted">${escapeHtml(author)} · saved ${formatWhen(youtube?.saved_at || universal?.created_at)}</p>
        ${linkHtml ? `<p>${linkHtml}</p>` : ""}
        <div class="meta-grid">
          <div><span class="stat-label">Status</span><strong>${escapeHtml(String(youtube?.processing_status || universal?.lifecycle_state || "—"))}</strong></div>
          <div><span class="stat-label">Language</span><strong>${escapeHtml(youtube?.language || "—")}</strong></div>
          <div><span class="stat-label">Chunks</span><strong>${youtube?.chunk_count ?? universal?.embedding_refs?.chunk_count ?? "—"}</strong></div>
          <div><span class="stat-label">Transcript</span><strong>${escapeHtml(youtube?.transcript_status || "—")}</strong></div>
        </div>
        ${
          universal?.memory_id
            ? `<p class="row-actions" style="margin-top:1rem">
                <button type="button" id="mem-delete" class="danger">Delete memory</button>
                <span id="mem-delete-status" class="status" hidden role="status"></span>
              </p>`
            : ""
        }
      </section>

      <section class="panel">
        <h3>Content preview</h3>
        <p>${escapeHtml((youtube?.description || universal?.metadata?.description_excerpt || "").slice(0, 800) || "No preview.")}</p>
      </section>

      <section class="panel">
        <h3>Evidence</h3>
        <div class="list">
          ${
            evidence.length
              ? evidence
                  .map((h) => {
                    const r = h.result || {};
                    return `<div class="list-row static"><span class="list-main">
                      <strong>${escapeHtml(r.title || title)}</strong>
                      <small>${escapeHtml(r.matched_text || h.explanation?.why || "").slice(0, 220)}</small>
                    </span></div>`;
                  })
                  .join("")
              : emptyState("No retrieval evidence yet", "Search or Ask to surface matched chunks.")
          }
        </div>
      </section>

      <section class="panel">
        <h3>Transcript</h3>
        <p class="muted">Availability: ${escapeHtml(String(youtube?.transcript_availability || universal?.metadata?.transcript_availability || "unknown"))} · status: ${escapeHtml(youtube?.transcript_status || "—")}</p>
        <p>${
          youtube?.chunk_count || universal?.embedding_refs?.chunk_count
            ? `${youtube?.chunk_count ?? universal?.embedding_refs?.chunk_count} indexed chunk(s) available via search/retrieve APIs.`
            : "Full transcript text is served through retrieval/search — open Search with this title to read matched segments."
        }</p>
      </section>

      <section class="panel">
        <h3>Related memories</h3>
        <div class="list">
          ${(related.items || [])
            .map(
              (r) => `
            <button type="button" class="list-row" data-open="${escapeHtml(memoryRef("youtube", r.video_id))}">
              <span class="src" aria-hidden="true">${sourceIcon("youtube")}</span>
              <span class="list-main"><strong>${escapeHtml(r.title)}</strong><small>${escapeHtml(r.relationship)} · ${(r.strength * 100).toFixed(0)}%</small></span>
            </button>`
            )
            .join("") || emptyState("No related memories")}
        </div>
      </section>

      <section class="panel">
        <h3>Timeline / processing history</h3>
        <div class="list compact">
          ${
            stages.length
              ? stages
                  .map(
                    (st) => `
            <div class="list-row static"><span class="list-main">
              <strong>${escapeHtml(st.stage || st.name || "")}</strong>
              <small>${escapeHtml(st.status || st.detail || "")} · ${formatWhen(st.at || st.created_at)}</small>
            </span></div>`
                  )
                  .join("")
              : ""
          }
          ${
            lifecycle.length
              ? lifecycle
                  .map(
                    (ev) => `
            <div class="list-row static"><span class="list-main">
              <strong>${escapeHtml(ev.to_state || ev.stage || "")}</strong>
              <small>${escapeHtml(ev.reason || ev.detail || "")} · ${formatWhen(ev.created_at)}</small>
            </span></div>`
                  )
                  .join("")
              : !stages.length
                ? emptyState("No lifecycle events")
                : ""
          }
        </div>
      </section>

      <section class="panel">
        <h3>Import history</h3>
        <div class="list compact">
          ${
            importsTouching.length
              ? importsTouching
                  .map(
                    (r) => `
            <button type="button" class="list-row" data-go-imports>
              <span class="list-main">
                <strong>${escapeHtml(r.connector_id)}</strong>
                <small>${escapeHtml(r.status)} · ${formatWhen(r.created_at)}</small>
              </span>
            </button>`
                  )
                  .join("")
              : emptyState("No linked import runs")
          }
        </div>
      </section>

      <section class="panel">
        <h3>Connector information</h3>
        <pre class="code-block">${escapeHtml(
          JSON.stringify(
            {
              source_type: resolvedType,
              connector_id: connector,
              external_id: externalId,
              memory_id: universal?.memory_id,
              tags: youtube?.tags || [],
              playlist: youtube?.playlist_title,
              embedding_status: youtube?.embedding_status,
            },
            null,
            2
          )
        )}</pre>
      </section>
    `;
    root.querySelectorAll("[data-open]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("memory", btn.dataset.open))
    );
    root.querySelectorAll("[data-go-imports]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("imports"))
    );
    const delBtn = root.querySelector("#mem-delete");
    if (delBtn && universal?.memory_id) {
      delBtn.addEventListener("click", async () => {
        if (!window.confirm("Permanently delete this memory and its indexed chunks?")) return;
        delBtn.disabled = true;
        try {
          await Api.deleteMemory(universal.memory_id, opts);
          setStatus(root.querySelector("#mem-delete-status"), "Deleted.", "success");
          navigate("dashboard");
        } catch (err) {
          setStatus(root.querySelector("#mem-delete-status"), err.message || "Delete failed", "error");
          delBtn.disabled = false;
        }
      });
    }
  } catch (err) {
    if (signal?.aborted) return;
    root.innerHTML = emptyState("Memory not found", err.message);
  }
}
