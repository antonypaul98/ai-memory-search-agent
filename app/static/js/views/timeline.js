import { Api } from "../api.js";
import {
  $,
  escapeHtml,
  formatWhen,
  sourceIcon,
  emptyState,
  skeleton,
  debounce,
  hitSourceType,
  memoryRef,
  boundList,
  RENDER_LIMITS,
} from "../util.js";
import { navigate } from "../router.js";

let _reload = null;

export function mountTimeline(root) {
  disposeTimeline();
  root.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <h2>Memory timeline</h2>
        <span class="panel-caption">Chronological view of saved knowledge</span>
      </div>
      <div class="filters">
        <label class="sr-only" for="tl-mode">Mode</label>
        <select id="tl-mode" aria-label="Timeline mode">
          <option value="recently_saved">Recently saved</option>
          <option value="first_learned">First learned</option>
          <option value="most_revisited">Most revisited</option>
          <option value="recently_learned">Recently learned</option>
          <option value="topic_evolution">Topic evolution</option>
        </select>
        <label class="sr-only" for="tl-group">Group by</label>
        <select id="tl-group" aria-label="Group by">
          <option value="day">Group by day</option>
          <option value="week">Group by week</option>
          <option value="month">Group by month</option>
          <option value="flat">Flat list</option>
        </select>
        <label class="sr-only" for="tl-topic">Topic filter</label>
        <input id="tl-topic" type="search" placeholder="Filter topic" aria-label="Topic filter" />
        <label class="sr-only" for="tl-q">Search titles</label>
        <input id="tl-q" type="search" placeholder="Search titles…" aria-label="Search titles" />
      </div>
      <div id="tl-body" aria-live="polite">${skeleton(4)}</div>
    </section>
  `;
  _reload = debounce(() => loadTimeline(root), 200);
  ["tl-mode", "tl-group", "tl-topic", "tl-q"].forEach((id) => {
    $(`#${id}`, root).addEventListener("change", _reload);
    $(`#${id}`, root).addEventListener("input", _reload);
  });
  loadTimeline(root);
}

export function disposeTimeline() {
  if (_reload?.cancel) _reload.cancel();
  _reload = null;
}

async function loadTimeline(root) {
  const body = $("#tl-body", root);
  body.innerHTML = skeleton(3);
  try {
    const mode = $("#tl-mode", root).value;
    const topic = $("#tl-topic", root).value.trim();
    const q = $("#tl-q", root).value.trim().toLowerCase();
    const group = $("#tl-group", root).value;
    const data = await Api.timeline(mode, topic, RENDER_LIMITS.timelineEntries, {
      abortTag: "timeline",
    });
    let entries = data.entries || [];
    if (q) entries = entries.filter((e) => (e.title || "").toLowerCase().includes(q));
    entries = boundList(entries, RENDER_LIMITS.timelineEntries);
    if (!entries.length) {
      body.innerHTML = emptyState("No timeline entries");
      return;
    }
    if (group === "flat") {
      body.innerHTML = `<div class="list">${entries.map(rowHtml).join("")}</div>`;
    } else {
      const keyFn =
        group === "month"
          ? (e) => String(e.saved_at || "").slice(0, 7)
          : group === "week"
            ? (e) => weekKey(e.saved_at)
            : (e) => String(e.saved_at || "").slice(0, 10);
      const map = new Map();
      for (const e of entries) {
        const k = keyFn(e) || "Unknown";
        if (!map.has(k)) map.set(k, []);
        map.get(k).push(e);
      }
      body.innerHTML = [...map.entries()]
        .map(
          ([label, items]) => `
        <section class="timeline-group">
          <h3>${escapeHtml(label)}</h3>
          <div class="list">${items.map(rowHtml).join("")}</div>
        </section>`
        )
        .join("");
    }
    body.querySelectorAll("[data-open]").forEach((btn) =>
      btn.addEventListener("click", () => navigate("memory", btn.dataset.open))
    );
  } catch (err) {
    body.innerHTML = emptyState("Timeline failed", err.message);
  }
}

function rowHtml(e) {
  const source = hitSourceType(e) || e.source_type || "youtube";
  const ext = e.external_id || e.video_id || "";
  return `<button type="button" class="list-row" data-open="${escapeHtml(memoryRef(source, ext))}">
    <span class="src" aria-hidden="true">${sourceIcon(source)}</span>
    <span class="list-main">
      <strong>${escapeHtml(e.title)}</strong>
      <small>${escapeHtml(e.channel || "")} · ${formatWhen(e.saved_at)} · ${(e.topics || []).slice(0, 3).map(escapeHtml).join(", ")}</small>
    </span>
  </button>`;
}

function weekKey(iso) {
  if (!iso) return "Unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  const onejan = new Date(d.getFullYear(), 0, 1);
  const week = Math.ceil(((d - onejan) / 86400000 + onejan.getDay() + 1) / 7);
  return `${d.getFullYear()}-W${String(week).padStart(2, "0")}`;
}
