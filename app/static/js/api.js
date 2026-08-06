/** Shared API client with short-lived response cache. No business logic. */
const API_BASE = "/api/v1";

const _cache = new Map();
const DEFAULT_TTL_MS = 15000;
const MAX_ERROR_DETAIL = 240;

/** Active AbortControllers keyed by caller tag (route disposal). */
const _inflight = new Map();

export function clearApiCache(substring = "") {
  const needle = String(substring || "");
  for (const key of [..._cache.keys()]) {
    if (!needle || key.includes(needle)) _cache.delete(key);
  }
}

export function abortInflight(tag = "") {
  for (const [key, controller] of [..._inflight.entries()]) {
    if (!tag || key === tag || key.startsWith(`${tag}:`)) {
      controller.abort();
      _inflight.delete(key);
    }
  }
}

function _normalizeErrorDetail(detail) {
  const text = String(detail ?? "Request failed");
  // Avoid echoing tokens or oversized payloads into the UI.
  const scrubbed = text.replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, "Bearer [redacted]");
  return scrubbed.length > MAX_ERROR_DETAIL
    ? `${scrubbed.slice(0, MAX_ERROR_DETAIL)}…`
    : scrubbed;
}

export async function apiFetch(path, options = {}, timeoutMs = 120000) {
  const method = (options.method || "GET").toUpperCase();
  const cacheable = method === "GET" && options.cache !== false;
  const cacheKey = `${method}:${path}`;
  if (cacheable) {
    const hit = _cache.get(cacheKey);
    if (hit && hit.expires > Date.now()) return hit.data;
  }

  const externalSignal = options.signal;
  const controller = new AbortController();
  const tag = options.abortTag || "";
  if (tag) {
    const prev = _inflight.get(tag);
    if (prev) prev.abort();
    _inflight.set(tag, controller);
  }
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = {
    ...(options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
    ...(options.headers || {}),
  };
  const token = localStorage.getItem("am_token");
  if (token) headers.Authorization = `Bearer ${token}`;

  const { abortTag: _a, ttlMs, cache: _c, signal: _s, ...fetchOpts } = options;

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...fetchOpts,
      method,
      signal: controller.signal,
      headers,
    });
    const text = await response.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        throw new Error(`Invalid JSON: ${_normalizeErrorDetail(text)}`);
      }
    }
    if (!response.ok) {
      const detail = body?.detail || text || response.statusText;
      throw new Error(
        `Request failed (${response.status}): ${_normalizeErrorDetail(detail)}`
      );
    }
    if (cacheable) {
      _cache.set(cacheKey, {
        data: body,
        expires: Date.now() + (ttlMs || DEFAULT_TTL_MS),
      });
    }
    return body;
  } catch (err) {
    if (err.name === "AbortError") {
      if (externalSignal?.aborted || (tag && !_inflight.has(tag))) {
        throw new Error("Request cancelled.");
      }
      throw new Error("Request timed out.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
    if (tag && _inflight.get(tag) === controller) _inflight.delete(tag);
  }
}

export const Api = {
  health: () => apiFetch("/health", {}, 15000),
  pwaConfig: () => apiFetch("/pwa/config", {}, 15000),
  agentStatus: (opts = {}) => apiFetch("/agent/status", opts, 20000),
  insights: (opts = {}) => apiFetch("/intelligence/insights", opts),
  topics: (limit = 40, opts = {}) =>
    apiFetch(`/intelligence/topics?limit=${limit}`, opts),
  topic: (id, opts = {}) =>
    apiFetch(`/intelligence/topics/${encodeURIComponent(id)}`, opts),
  roadmap: (topic, opts = {}) =>
    apiFetch(`/intelligence/roadmap?topic=${encodeURIComponent(topic)}`, opts),
  capsules: (limit = 40, opts = {}) =>
    apiFetch(`/intelligence/capsules?limit=${limit}`, opts),
  timeline: (mode = "recently_saved", topic = "", limit = 40, opts = {}) => {
    const q = new URLSearchParams({ mode, limit: String(limit) });
    if (topic) q.set("topic", topic);
    return apiFetch(`/intelligence/timeline?${q}`, opts);
  },
  retrieve: (q, limit = 8, filters = {}, opts = {}) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    Object.entries(filters).forEach(([k, v]) => {
      if (v != null && v !== "") params.set(k, String(v));
    });
    return apiFetch(`/intelligence/retrieve?${params}`, { ...opts, cache: false });
  },
  search: (q, limit = 8, filters = {}, opts = {}) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    Object.entries(filters).forEach(([k, v]) => {
      if (v != null && v !== "") params.set(k, String(v));
    });
    return apiFetch(`/search?${params}`, { ...opts, cache: false });
  },
  chat: (body, opts = {}) =>
    apiFetch(
      "/chat",
      { method: "POST", body: JSON.stringify(body), cache: false, ...opts },
      120000
    ),
  memories: (limit = 40, opts = {}) => apiFetch(`/memories?limit=${limit}`, opts),
  memory: (id, opts = {}) =>
    apiFetch(`/memories/${encodeURIComponent(id)}`, opts),
  memoryLifecycle: (id, opts = {}) =>
    apiFetch(`/memories/${encodeURIComponent(id)}/lifecycle`, opts),
  deleteMemory: (id, opts = {}) =>
    apiFetch(`/memories/${encodeURIComponent(id)}`, {
      method: "DELETE",
      cache: false,
      ...opts,
    }),
  exportPrivacyData: (download = false, opts = {}) =>
    apiFetch(`/privacy/export${download ? "?download=true" : ""}`, {
      cache: false,
      ...opts,
    }),
  deleteAllMemories: (opts = {}) =>
    apiFetch("/privacy/memories", { method: "DELETE", cache: false, ...opts }),
  logout: (opts = {}) =>
    apiFetch("/auth/logout", { method: "POST", cache: false, ...opts }),
  me: (opts = {}) => apiFetch("/auth/me", { cache: false, ...opts }),
  memoryByExternal: (sourceType, externalId, opts = {}) =>
    apiFetch(
      `/memories/by-external?source_type=${encodeURIComponent(sourceType)}&external_id=${encodeURIComponent(externalId)}`,
      opts
    ),
  youtubeMemory: (videoId, opts = {}) =>
    apiFetch(`/youtube/memories/${encodeURIComponent(videoId)}`, opts),
  youtubeRelated: (videoId, opts = {}) =>
    apiFetch(`/youtube/memories/${encodeURIComponent(videoId)}/related`, opts),
  imports: (limit = 40, opts = {}) => apiFetch(`/imports?limit=${limit}`, opts),
  importDetail: (id, opts = {}) =>
    apiFetch(`/imports/${encodeURIComponent(id)}`, { cache: false, ...opts }),
  importStart: (id, opts = {}) =>
    apiFetch(`/imports/${encodeURIComponent(id)}/start`, {
      method: "POST",
      cache: false,
      ...opts,
    }),
  importCancel: (id, opts = {}) =>
    apiFetch(`/imports/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      cache: false,
      ...opts,
    }),
  connectorsHealth: (opts = {}) => apiFetch("/connectors/health", opts),
  ingest: (body, opts = {}) =>
    apiFetch(
      "/videos/ingest",
      { method: "POST", body: JSON.stringify(body), cache: false, ...opts },
      900000
    ),
  playlistPreview: (url, opts = {}) =>
    apiFetch("/playlists/preview", {
      method: "POST",
      body: JSON.stringify({ playlist_url: url }),
      cache: false,
      ...opts,
    }),
  playlistIngest: (body, opts = {}) =>
    apiFetch("/playlists/ingest", {
      method: "POST",
      body: JSON.stringify(body),
      cache: false,
      ...opts,
    }),
  job: (id, opts = {}) =>
    apiFetch(`/jobs/${encodeURIComponent(id)}`, { cache: false, ...opts }),
  jobPause: (id, opts = {}) =>
    apiFetch(`/jobs/${encodeURIComponent(id)}/pause`, { method: "POST", ...opts }),
  jobResume: (id, opts = {}) =>
    apiFetch(`/jobs/${encodeURIComponent(id)}/resume`, { method: "POST", ...opts }),
  jobRetryFailed: (id, opts = {}) =>
    apiFetch(`/jobs/${encodeURIComponent(id)}/retry-failed`, { method: "POST", ...opts }),
  jobCancel: (id, opts = {}) =>
    apiFetch(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", ...opts }),
  captureUrl: (body, opts = {}) =>
    apiFetch("/capture/url", {
      method: "POST",
      body: JSON.stringify(body),
      cache: false,
      ...opts,
    }),
  bookmarkPreview: (body, opts = {}) =>
    apiFetch("/capture/bookmarks/preview", {
      method: "POST",
      body: JSON.stringify(body),
      cache: false,
      ...opts,
    }),
  bookmarkImport: (body, opts = {}) =>
    apiFetch("/capture/bookmarks/import", {
      method: "POST",
      body: JSON.stringify(body),
      cache: false,
      ...opts,
    }),
  capturePdf: (file, title = "", opts = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    return apiFetch("/capture/pdf", {
      method: "POST",
      body: form,
      cache: false,
      ...opts,
    });
  },
};
