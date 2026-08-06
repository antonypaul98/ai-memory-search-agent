import { Api } from "../api.js";
import {
  $,
  escapeHtml,
  emptyState,
  skeleton,
  boundList,
  RENDER_LIMITS,
  memoryRef,
} from "../util.js";
import { navigate } from "../router.js";

export function mountTopics(root, initialTopic = "", { signal } = {}) {
  root.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <h2>Topic explorer</h2>
        <span class="panel-caption">Intelligence APIs · roadmaps · capsules</span>
      </div>
      <div id="topic-cards" aria-live="polite">${skeleton(4)}</div>
    </section>
    <section class="panel" id="topic-detail" hidden></section>
  `;
  loadTopics(root, initialTopic, signal);
}

async function loadTopics(root, focus = "", signal) {
  const cards = $("#topic-cards", root);
  try {
    const [topics, capsules] = await Promise.all([
      Api.topics(RENDER_LIMITS.topicCards, { abortTag: "topics", signal }),
      Api.capsules(20, { abortTag: "capsules", signal }),
    ]);
    if (signal?.aborted) return;
    const list = boundList(topics.topics || [], RENDER_LIMITS.topicCards);
    const caps = capsules.capsules || [];
    if (!list.length) {
      cards.innerHTML = emptyState("No topics yet", "Index memories to discover topics.");
      return;
    }
    cards.innerHTML = `
      <div class="card-grid">
        ${list
          .map(
            (t) => `
          <button type="button" class="topic-card" data-topic="${escapeHtml(t.name)}">
            <strong>${escapeHtml(t.name)}</strong>
            <span>${t.memory_count || 0} memories</span>
            <small>${escapeHtml(t.category || "topic")} · ${escapeHtml((t.summary || "").slice(0, 100))}</small>
          </button>`
          )
          .join("")}
      </div>
      <h3>Capsules</h3>
      <div class="chip-row">
        ${
          caps.length
            ? caps
                .map(
                  (c) =>
                    `<span class="chip">${escapeHtml(c.name)} <em>${c.memory_count || 0}</em></span>`
                )
                .join("")
            : "<span class='muted'>No capsules yet</span>"
        }
      </div>
    `;
    cards.querySelectorAll("[data-topic]").forEach((btn) =>
      btn.addEventListener("click", () => showTopic(root, btn.dataset.topic, signal))
    );
    if (focus) showTopic(root, focus, signal);
  } catch (err) {
    if (signal?.aborted) return;
    cards.innerHTML = emptyState("Topics unavailable", err.message);
  }
}

async function showTopic(root, name, signal) {
  const detail = $("#topic-detail", root);
  detail.hidden = false;
  detail.innerHTML = skeleton(2);
  try {
    const [topic, roadmap] = await Promise.all([
      Api.topic(name, { abortTag: "topic-detail", signal }).catch(() => null),
      Api.roadmap(name, { abortTag: "roadmap", signal }),
    ]);
    if (signal?.aborted) return;
    const t = topic || { name, summary: "", memory_count: 0, video_ids: [] };
    detail.innerHTML = `
      <div class="panel-header">
        <h2>${escapeHtml(t.name || name)}</h2>
        <span class="panel-caption">${t.memory_count || 0} memories · ${escapeHtml(t.category || "")}</span>
      </div>
      <p>${escapeHtml(t.summary || "No summary yet.")}</p>
      <h3>Learning roadmap</h3>
      <div class="roadmap">
        ${levelBlock("Beginner", roadmap.beginner)}
        ${levelBlock("Intermediate", roadmap.intermediate)}
        ${levelBlock("Advanced", roadmap.advanced)}
      </div>
      ${
        (roadmap.missing_prerequisites || []).length
          ? `<p class="muted">Missing prerequisites: ${roadmap.missing_prerequisites.map(escapeHtml).join(", ")}</p>`
          : ""
      }
      <h3>Memories</h3>
      <div class="chip-row">
        ${(t.video_ids || roadmap.recommended_order || [])
          .slice(0, 12)
          .map((id) => {
            const vid = typeof id === "string" ? id : id.video_id || "";
            return `<button type="button" class="chip" data-open="${escapeHtml(memoryRef("youtube", vid))}">${escapeHtml(vid)}</button>`;
          })
          .join("") || "<span class='muted'>None</span>"}
      </div>
    `;
    detail.querySelectorAll("[data-open]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("memory", btn.dataset.open))
    );
  } catch (err) {
    if (signal?.aborted) return;
    detail.innerHTML = emptyState("Could not load topic", err.message);
  }
}

function levelBlock(label, steps = []) {
  if (!steps.length) return `<div class="road-level"><h4>${label}</h4><p class="muted">None</p></div>`;
  return `<div class="road-level"><h4>${label}</h4><ul>${steps
    .map(
      (s) =>
        `<li><button type="button" class="linkish" data-open="${escapeHtml(memoryRef("youtube", s.video_id))}">${escapeHtml(s.title)}</button> <small class="muted">${escapeHtml(s.reason || "")}</small></li>`
    )
    .join("")}</ul></div>`;
}
