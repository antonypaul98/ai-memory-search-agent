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
    <section class="panel" id="duplicate-knowledge">
      <div class="panel-header">
        <h2>Duplicate knowledge</h2>
        <span class="panel-caption">Review likely duplicates before merging</span>
      </div>
      <div id="duplicate-cards" aria-live="polite">${skeleton(2)}</div>
    </section>
    <section class="panel" id="topic-detail" hidden></section>
  `;
  loadTopics(root, initialTopic, signal);
  loadDuplicates(root, signal);
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

async function loadDuplicates(root, signal) {
  const cards = $("#duplicate-cards", root);
  if (!cards) return;
  try {
    const response = await Api.duplicates(20, { abortTag: "duplicates", signal });
    if (signal?.aborted) return;
    const items = response.items || [];
    if (!items.length) {
      cards.innerHTML = emptyState(
        "No duplicate knowledge found",
        "Likely duplicate memories will appear here for review."
      );
      return;
    }
    cards.innerHTML = items.map(duplicateCard).join("");
    cards.querySelectorAll("[data-merge-source]").forEach((button) => {
      button.addEventListener("click", () => mergeDuplicate(root, button, signal));
    });
    cards.querySelectorAll("[data-open-video]").forEach((button) => {
      button.addEventListener("click", () =>
        navigate("memory", memoryRef("youtube", button.dataset.openVideo || ""))
      );
    });
  } catch (err) {
    if (signal?.aborted) return;
    cards.innerHTML = emptyState("Duplicate review unavailable", err.message);
  }
}

function duplicateCard(item) {
  const shared = (item.shared_topics || []).slice(0, 6);
  const diversity = Math.round(Number(item.diversity_score || 0) * 100);
  return `
    <article class="result-card duplicate-card">
      <div class="panel-header">
        <strong>${escapeHtml(item.relationship || "Possible duplicate")}</strong>
        <span class="panel-caption">${diversity}% explanation diversity</span>
      </div>
      <div class="card-grid">
        <div>
          <button type="button" class="linkish" data-open-video="${escapeHtml(item.video_id_a)}">
            ${escapeHtml(item.title_a || item.video_id_a)}
          </button>
          <small class="muted">A · ${escapeHtml(item.video_id_a)}</small>
        </div>
        <div>
          <button type="button" class="linkish" data-open-video="${escapeHtml(item.video_id_b)}">
            ${escapeHtml(item.title_b || item.video_id_b)}
          </button>
          <small class="muted">B · ${escapeHtml(item.video_id_b)}</small>
        </div>
      </div>
      ${shared.length ? `<p class="muted">Shared topics: ${shared.map(escapeHtml).join(", ")}</p>` : ""}
      ${item.evidence ? `<p>${escapeHtml(item.evidence)}</p>` : ""}
      <div class="button-row">
        <button type="button" class="secondary" data-merge-source="${escapeHtml(item.video_id_b)}" data-merge-target="${escapeHtml(item.video_id_a)}">
          Keep A · merge B into A
        </button>
        <button type="button" class="secondary" data-merge-source="${escapeHtml(item.video_id_a)}" data-merge-target="${escapeHtml(item.video_id_b)}">
          Keep B · merge A into B
        </button>
      </div>
    </article>`;
}

async function mergeDuplicate(root, button, signal) {
  const sourceVideoId = button.dataset.mergeSource || "";
  const targetVideoId = button.dataset.mergeTarget || "";
  if (!sourceVideoId || !targetVideoId) return;

  const approved = window.confirm(
    "Merge these memories? The source will be marked as merged into the memory you keep. This action is recorded in the lifecycle audit trail."
  );
  if (!approved) return;

  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Merging…";
  try {
    const [source, target] = await Promise.all([
      Api.memoryByExternal("youtube", sourceVideoId, { cache: false, signal }),
      Api.memoryByExternal("youtube", targetVideoId, { cache: false, signal }),
    ]);
    if (!source?.memory_id || !target?.memory_id) {
      throw new Error("Could not resolve both memories to canonical records.");
    }
    await Api.mergeMemory(source.memory_id, target.memory_id, { signal });
    if (signal?.aborted) return;
    await loadDuplicates(root, signal);
  } catch (err) {
    if (signal?.aborted) return;
    button.disabled = false;
    button.textContent = original;
    window.alert(`Merge failed: ${err.message}`);
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
