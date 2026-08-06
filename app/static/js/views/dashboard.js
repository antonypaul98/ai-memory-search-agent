import { Api } from "../api.js";
import {
  escapeHtml,
  formatWhen,
  sourceIcon,
  sourceLabel,
  skeleton,
  emptyState,
  memoryRef,
  boundList,
  RENDER_LIMITS,
  hitSourceType,
} from "../util.js";
import { navigate } from "../router.js";

let _seq = 0;

export async function renderDashboard(root, { signal } = {}) {
  const seq = ++_seq;
  root.innerHTML = skeleton(4);
  const opts = { abortTag: "dashboard", signal };
  try {
    const [status, insights, imports, health, timeline, topics, memories] =
      await Promise.all([
        Api.agentStatus(opts),
        Api.insights(opts).catch(() => null),
        Api.imports(8, opts).catch(() => ({ imports: [] })),
        Api.connectorsHealth(opts).catch(() => ({ connectors: [] })),
        Api.timeline("recently_saved", "", 8, opts).catch(() => ({ entries: [] })),
        Api.topics(8, opts).catch(() => ({ topics: [] })),
        Api.memories(RENDER_LIMITS.dashboardList, opts).catch(() => []),
      ]);
    if (seq !== _seq || signal?.aborted) return;

    const connectors = health.connectors || [];
    const healthy = connectors.filter((c) => c.healthy).length;
    const recentImports = imports.imports || [];
    const entries = timeline.entries || [];
    const topicList = topics.topics || insights?.top_topics || [];
    const todayIso = new Date().toISOString().slice(0, 10);
    const memList = Array.isArray(memories) ? memories : [];
    const todayCaptures = memList.filter((m) =>
      String(m.created_at || "").startsWith(todayIso)
    );
    const searches = status.recent_searches || [];
    const queue = recentImports.filter((r) =>
      ["running", "pending", "paused", "queued"].includes(
        String(r.status || "").toLowerCase()
      )
    );

    const recentRows = boundList(
      memList.length
        ? memList
        : entries.map((e) => ({
            source_type: hitSourceType(e) || "youtube",
            external_id: e.external_id || e.video_id,
            title: e.title,
            source_author: e.channel,
            created_at: e.saved_at,
          })),
      RENDER_LIMITS.dashboardList
    );

    root.innerHTML = `
    <div class="dash-grid">
      <article class="stat-card">
        <span class="stat-label">Memories</span>
        <strong class="stat-value">${status.memory_count ?? 0}</strong>
        <span class="stat-meta">${status.today_saves ?? 0} saved today</span>
      </article>
      <article class="stat-card">
        <span class="stat-label">Processing</span>
        <strong class="stat-value">${status.processing_count ?? status.pending_captures ?? 0}</strong>
        <span class="stat-meta">${status.pending_jobs ?? 0} jobs queued</span>
      </article>
      <article class="stat-card">
        <span class="stat-label">Indexed chunks</span>
        <strong class="stat-value">${status.document_count ?? 0}</strong>
        <span class="stat-meta">${status.chroma_connected ? "Chroma online" : "Chroma offline"}</span>
      </article>
      <article class="stat-card">
        <span class="stat-label">Connectors</span>
        <strong class="stat-value">${healthy}/${connectors.length || 0}</strong>
        <span class="stat-meta">backend ${escapeHtml(status.backend_status || "—")}</span>
      </article>
    </div>

    <div class="dash-columns">
      <section class="panel">
        <div class="panel-header">
          <h2>Recent memories</h2>
          <button type="button" class="linkish" data-go="timeline">Timeline</button>
        </div>
        <div class="list">
          ${
            recentRows.length
              ? recentRows
                  .map(
                    (m) => `
            <button type="button" class="list-row" data-ref="${escapeHtml(
              memoryRef(m.source_type || "youtube", m.external_id || "")
            )}">
              <span class="src" aria-hidden="true">${sourceIcon(m.source_type)}</span>
              <span class="list-main">
                <strong>${escapeHtml(m.title)}</strong>
                <small>${sourceLabel(m.source_type)} · ${escapeHtml(m.source_author || "")} · ${formatWhen(m.created_at)}</small>
              </span>
            </button>`
                  )
                  .join("")
              : emptyState("No memories yet", "Save a YouTube video, article, PDF, or bookmark.")
          }
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h2>Processing queue</h2>
          <button type="button" class="linkish" data-go="imports">Import manager</button>
        </div>
        <div class="list">
          ${
            (queue.length ? queue : recentImports.slice(0, 5)).length
              ? (queue.length ? queue : recentImports.slice(0, 5))
                  .map(
                    (r) => `
            <div class="list-row static">
              <span class="src" aria-hidden="true">⇪</span>
              <span class="list-main">
                <strong>${escapeHtml(r.connector_id)}</strong>
                <small>${escapeHtml(r.status)} · ${r.completed_items || 0}/${r.total_items || 0} · ${formatWhen(r.created_at)}</small>
              </span>
            </div>`
                  )
                  .join("")
              : emptyState("Queue idle", "No imports running.")
          }
        </div>
      </section>
    </div>

    <div class="dash-columns">
      <section class="panel">
        <div class="panel-header"><h2>Today's captures</h2></div>
        <div class="list">
          ${
            todayCaptures.length
              ? todayCaptures
                  .map(
                    (m) => `
            <button type="button" class="list-row" data-ref="${escapeHtml(
              memoryRef(m.source_type || "youtube", m.external_id || "")
            )}">
              <span class="src" aria-hidden="true">${sourceIcon(m.source_type)}</span>
              <span class="list-main">
                <strong>${escapeHtml(m.title)}</strong>
                <small>${sourceLabel(m.source_type)} · ${formatWhen(m.created_at)}</small>
              </span>
            </button>`
                  )
                  .join("")
              : emptyState("Nothing saved today yet")
          }
        </div>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h2>Search activity</h2>
          <button type="button" class="linkish" data-go="search">Search</button>
        </div>
        <div class="list compact">
          ${
            searches.length
              ? searches
                  .slice(0, 8)
                  .map(
                    (s) => `
            <div class="list-row static">
              <span class="list-main">
                <strong>${escapeHtml(s.query)}</strong>
                <small>${formatWhen(s.created_at)}</small>
              </span>
            </div>`
                  )
                  .join("")
              : emptyState("No recent searches")
          }
        </div>
      </section>
    </div>

    <div class="dash-columns">
      <section class="panel">
        <div class="panel-header">
          <h2>Topics</h2>
          <button type="button" class="linkish" data-go="topics">Explore</button>
        </div>
        <div class="chip-row">
          ${
            topicList.length
              ? topicList
                  .slice(0, 12)
                  .map(
                    (t) =>
                      `<button type="button" class="chip" data-topic="${escapeHtml(t.name)}">${escapeHtml(t.name)} <em>${t.memory_count || 0}</em></button>`
                  )
                  .join("")
              : emptyState("Topics appear after indexing")
          }
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>Connector health</h2></div>
        <div class="list compact">
          ${
            connectors.length
              ? connectors
                  .map(
                    (c) => `
            <div class="list-row static">
              <span class="dot ${c.healthy ? "ok" : "bad"}" aria-hidden="true"></span>
              <span class="list-main">
                <strong>${escapeHtml(c.connector_id)}</strong>
                <small>${escapeHtml(c.detail || (c.healthy ? "ok" : "unhealthy"))}</small>
              </span>
            </div>`
                  )
                  .join("")
              : emptyState("No connector status")
          }
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header"><h2>Memory growth</h2></div>
      <div class="growth-bars" aria-label="Memory growth">
        ${(insights?.memory_growth || [])
          .slice(-12)
          .map((g) => {
            const max = Math.max(
              ...(insights.memory_growth || []).map((x) => x.count || 0),
              1
            );
            const h = Math.max(8, Math.round(((g.count || 0) / max) * 64));
            return `<div class="bar" style="height:${h}px" title="${escapeHtml(g.date)}: ${g.count}"></div>`;
          })
          .join("") || emptyState("Growth appears as you save")}
      </div>
      <p class="muted">Searches recently: ${searches.length} · streak ${insights?.learning_streak_days ?? 0}d</p>
    </section>
  `;

    root.querySelectorAll("[data-go]").forEach((btn) =>
      btn.addEventListener("click", () => navigate(btn.dataset.go))
    );
    root.querySelectorAll("[data-ref]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("memory", btn.dataset.ref))
    );
    root.querySelectorAll("[data-topic]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("topics", btn.dataset.topic))
    );
  } catch (err) {
    if (signal?.aborted || seq !== _seq) return;
    root.innerHTML = emptyState("Dashboard unavailable", err.message);
  }
}
