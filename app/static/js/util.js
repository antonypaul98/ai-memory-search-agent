/** Presentation helpers — no domain rules. */

/** Known source types for filters/icons. Fallback label uses raw type for unknowns. */
export const SOURCE_TYPES = [
  { id: "youtube", label: "YouTube" },
  { id: "web", label: "Articles" },
  { id: "pdf", label: "PDF" },
  { id: "github", label: "GitHub" },
  { id: "bookmark", label: "Bookmarks" },
];

/** Hard render caps — presentation safety, not pagination policy. */
export const RENDER_LIMITS = {
  searchResults: 40,
  timelineEntries: 100,
  importItems: 100,
  importList: 50,
  dashboardList: 12,
  topicCards: 60,
  askEvidence: 12,
};

export function $(sel, root = document) {
  return typeof sel === "string" ? root.querySelector(sel) : sel;
}

export function $all(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Allow only http(s) URLs for href attributes. */
export function safeHref(url) {
  const raw = String(url ?? "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch {
    /* invalid */
  }
  return "";
}

export function externalLink(url, label) {
  const href = safeHref(url);
  if (!href) return "";
  const text = escapeHtml(label || href);
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
}

export function formatWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(iso).slice(0, 16);
  }
}

export function sourceIcon(sourceType = "") {
  const map = {
    youtube: "▶",
    web: "◈",
    pdf: "▣",
    github: "⌥",
    bookmark: "☆",
  };
  return map[String(sourceType).toLowerCase()] || "●";
}

export function sourceLabel(sourceType = "") {
  const known = SOURCE_TYPES.find((s) => s.id === String(sourceType).toLowerCase());
  if (known) return known.label;
  return sourceType || "Memory";
}

export function sourceFilterOptionsHtml(includeAll = true) {
  const all = includeAll ? `<option value="">All sources</option>` : "";
  return (
    all +
    SOURCE_TYPES.map(
      (s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.label)}</option>`
    ).join("")
  );
}

/** Prefer universal external_id; fall back to legacy video_id field from search hits. */
export function hitExternalId(result = {}) {
  return result.external_id || result.video_id || result.memory_id || "";
}

export function hitSourceType(result = {}) {
  return result.source_type || "youtube";
}

export function memoryRef(sourceType, externalId) {
  return `${sourceType || "youtube"}:${externalId || ""}`;
}

export function parseMemoryRef(param) {
  if (!param) return { sourceType: "", externalId: "" };
  const decoded = decodeURIComponent(param);
  if (decoded.includes(":")) {
    const idx = decoded.indexOf(":");
    return {
      sourceType: decoded.slice(0, idx) || "",
      externalId: decoded.slice(idx + 1),
    };
  }
  return { sourceType: "", externalId: decoded };
}

export function boundList(items, limit) {
  const arr = Array.isArray(items) ? items : [];
  return arr.slice(0, Math.max(0, limit));
}

export function setStatus(el, message, kind = "") {
  if (!el) return;
  el.hidden = !message;
  el.textContent = message || "";
  el.className = `status ${kind}`.trim();
  if (message) el.setAttribute("role", "status");
}

export function skeleton(count = 3) {
  return Array.from({ length: count })
    .map(() => `<div class="skeleton-card" aria-hidden="true"></div>`)
    .join("");
}

export function emptyState(title, hint = "") {
  return `<div class="empty-state" role="status"><strong>${escapeHtml(title)}</strong>${
    hint ? `<p>${escapeHtml(hint)}</p>` : ""
  }</div>`;
}

export function confBadge(score) {
  if (score == null) return "";
  const pct = Math.round(Number(score) * 100);
  if (Number.isNaN(pct)) return `<span class="conf">${escapeHtml(String(score))}</span>`;
  const level = pct >= 70 ? "high" : pct >= 40 ? "mid" : "low";
  return `<span class="conf conf-${level}">${pct}%</span>`;
}

export function debounce(fn, ms = 250) {
  let t;
  const wrapped = (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(t);
  return wrapped;
}

export function groupByDay(entries, dateKey = "saved_at") {
  const groups = new Map();
  for (const e of entries) {
    const raw = e[dateKey] || e.published_at || "";
    const day = String(raw).slice(0, 10) || "Unknown";
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(e);
  }
  return groups;
}

export function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem("am_workspace_settings") || "{}");
  } catch {
    return {};
  }
}

export function saveSettings(partial) {
  const next = { ...loadSettings(), ...partial };
  localStorage.setItem("am_workspace_settings", JSON.stringify(next));
  return next;
}
