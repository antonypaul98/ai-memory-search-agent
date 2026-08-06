/**
 * Shared API client for the AI Memory Agent extension.
 * Works in service worker, popup, and settings (Chrome extension pages).
 */

export const DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1";

/**
 * @param {object} opts
 * @param {string} [opts.apiBase]
 * @param {string} [opts.token]
 * @param {string} path
 * @param {RequestInit} [init]
 */
export async function agentFetch(opts, path, init = {}) {
  const base = (opts.apiBase || DEFAULT_API_BASE).replace(/\/$/, "");
  const headers = {
    "Content-Type": "application/json",
    ...(init.headers || {}),
  };
  if (opts.token) {
    headers.Authorization = `Bearer ${opts.token}`;
  }
  const controller = new AbortController();
  const timeoutMs = opts.timeoutMs || 30000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${base}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    const text = await resp.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = { detail: text };
      }
    }
    if (!resp.ok) {
      const detail = body?.detail || text || resp.statusText;
      const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

export async function getHealth(opts) {
  return agentFetch(opts, "/health", { method: "GET" });
}

export async function getAgentStatus(opts) {
  return agentFetch(opts, "/agent/status", { method: "GET" });
}

/**
 * Classify (and optionally execute) an agent command.
 * @param {object} opts
 * @param {{ text: string, context?: object, execute?: boolean, confirm_token?: string, limit?: number }} payload
 */
export async function postAgentCommand(opts, payload) {
  return agentFetch(opts, "/agent/command", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Execute a planned agent command (confirm_token required for bulk).
 * @param {object} opts
 * @param {object} payload
 */
export async function executeAgentCommand(opts, payload) {
  return agentFetch(opts, "/agent/command/execute", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function saveToMemory(opts, payload) {
  return agentFetch(opts, "/capture/url", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getCaptureStatus(opts, captureId) {
  return agentFetch(opts, `/capture/status/${encodeURIComponent(captureId)}`, {
    method: "GET",
  });
}

export async function retryCapture(opts, captureId) {
  return agentFetch(opts, `/capture/retry/${encodeURIComponent(captureId)}`, {
    method: "POST",
    body: "{}",
  });
}

export async function previewBookmarks(opts, payload) {
  return agentFetch(opts, "/capture/bookmarks/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importBookmarks(opts, payload) {
  return agentFetch(opts, "/capture/bookmarks/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Multipart PDF upload — do not set Content-Type (boundary is set by fetch).
 * @param {object} opts
 * @param {File|Blob} file
 * @param {string} [title]
 */
export async function capturePdf(opts, file, title = "") {
  const base = (opts.apiBase || DEFAULT_API_BASE).replace(/\/$/, "");
  const form = new FormData();
  form.append("file", file, file.name || "document.pdf");
  if (title) form.append("title", title);
  const headers = {};
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
  const controller = new AbortController();
  const timeoutMs = opts.timeoutMs || 120000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${base}/capture/pdf`, {
      method: "POST",
      headers,
      body: form,
      signal: controller.signal,
    });
    const text = await resp.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = { detail: text };
      }
    }
    if (!resp.ok) {
      const detail = body?.detail || text || resp.statusText;
      const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}
