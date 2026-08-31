import {
  getAgentStatus,
  getHealth,
  previewBookmarks,
  importBookmarks,
  capturePdf,
  postAgentCommand,
  executeAgentCommand,
} from "./shared/api.js";
import { loadSettings, STORAGE_KEYS } from "./shared/storage.js";
import { summarizeContext } from "./shared/context.js";
import { trustBadgeHtml } from "./shared/trust.js";
import {
  getPermissionSnapshot,
  requestBookmarksPermission,
} from "./shared/permissions.js";

const $ = (id) => document.getElementById(id);

let pollTimer = null;
let currentCaptureId = null;
let settings = null;
let activeContext = null;
/** @type {object|null} */
let lastCommandPlan = null;
/** Prevent overlapping command plan/execute requests. */
let commandInFlight = false;

async function init() {
  settings = await loadSettings();
  applyTheme(settings.theme);
  $("btn-pause").textContent = settings.observerPaused
    ? "Resume Observation"
    : "Pause Observation";

  $("btn-settings").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
  $("btn-save").addEventListener("click", onSave);
  $("btn-ask").addEventListener("click", onAsk);
  $("btn-search").addEventListener("click", onSearchMemory);
  $("btn-pause").addEventListener("click", onPauseToggle);
  $("btn-view-context").addEventListener("click", onViewContext);
  $("btn-retry").addEventListener("click", onRetry);
  $("command-form").addEventListener("submit", onCommandSubmit);
  $("btn-command-confirm").addEventListener("click", onCommandConfirmBulk);
  $("btn-command-workspace").addEventListener("click", onCommandOpenWorkspace);
  $("btn-clear-context").addEventListener("click", async (e) => {
    e.preventDefault();
    await chrome.runtime.sendMessage({ type: "CLEAR_TEMP_CONTEXT" });
    $("context-dialog").close();
    await refreshContext();
  });
  $("btn-bookmarks").addEventListener("click", onBookmarksStart);
  $("btn-bookmark-preview").addEventListener("click", onBookmarkPreview);
  $("btn-bookmark-confirm").addEventListener("click", onBookmarkConfirm);
  $("btn-pdf-upload").addEventListener("click", onPdfUpload);
  $("btn-playlist-workspace").addEventListener("click", onPlaylistWorkspace);

  await Promise.all([refreshContext(), refreshHealth(), refreshPermissions()]);
  await restoreActiveCapture();
  // Focus command bar for keyboard-first demos (V1-7).
  try {
    $("command-input").focus();
  } catch {
    /* ignore */
  }
}

/** @type {object[]|null} */
let pendingBookmarkItems = null;
let bookmarkPreviewDone = false;

function applyTheme(theme) {
  document.body.dataset.theme = theme || "system";
}

async function refreshContext() {
  const resp = await chrome.runtime.sendMessage({ type: "GET_ACTIVE_CONTEXT" });
  activeContext = resp?.context || null;
  const summary = summarizeContext(activeContext);
  $("obs-platform").textContent = summary.platformLabel;
  $("obs-title").textContent = summary.title;
  $("obs-creator").textContent = summary.creator || "—";
  $("obs-transcript").textContent = summary.transcriptLabel;
  $("obs-kind-label").textContent =
    activeContext?.platform === "youtube" ? "Video" : "Page";

  if (summary.ready && !settings.observerPaused) {
    $("ready-text").textContent = "Ready to Save";
    $("ready-pulse").className = "pulse";
    $("live-tagline").textContent = "Currently observing — ready when you are";
    $("btn-save").disabled = false;
  } else if (settings.observerPaused) {
    $("ready-text").textContent = "Observation paused";
    $("ready-pulse").className = "pulse warn";
    $("live-tagline").textContent = "Observation paused";
    $("btn-save").disabled = !summary.ready;
  } else {
    $("ready-text").textContent = "Nothing to save here";
    $("ready-pulse").className = "pulse warn";
    $("live-tagline").textContent = "Open a YouTube video or web page";
    $("btn-save").disabled = true;
  }

  if (summary.thumbnail) {
    $("thumb-row").hidden = false;
    $("obs-thumb").src = summary.thumbnail;
    if (summary.progressSec != null) {
      const m = Math.floor(summary.progressSec / 60);
      const s = String(summary.progressSec % 60).padStart(2, "0");
      $("obs-progress").textContent = `At ${m}:${s}`;
    } else {
      $("obs-progress").textContent = "";
    }
  } else {
    $("thumb-row").hidden = true;
  }

  if (settings.debugMode) {
    $("live-tagline").textContent += ` · debug ${activeContext?.observedFrom || "none"}`;
  }
}

async function refreshHealth() {
  try {
    const health = await getHealth(settings);
    const status = await getAgentStatus(settings);
    $("h-backend").textContent = status.backend_status || health.status || "ok";
    $("h-connected").textContent = status.connected ? "Connected" : "Offline";
    $("h-version").textContent = status.version || "—";
    $("h-queue").textContent = String(status.pending_captures ?? 0);
    $("h-jobs").textContent = String(status.pending_jobs ?? 0);
    $("h-sync").textContent = formatTime(status.last_sync_at);
    $("h-user").textContent = status.display_name || status.user_id || "—";
    $("h-auth").textContent = status.auth_enabled ? "Enabled" : "Demo mode";

    $("m-today").textContent = String(status.today_saves ?? 0);
    $("m-processing").textContent = String(status.processing_count ?? 0);
    $("m-indexed").textContent = String(status.indexed_count ?? 0);
    $("m-count").textContent = String(status.memory_count ?? 0);
    $("m-latest").textContent = status.latest_memory?.title || "None yet";
    if (status.recent_searches?.length) {
      $("m-searches").textContent = status.recent_searches.map((s) => s.query).join(" · ");
    } else {
      $("m-searches").textContent = "None yet";
    }
    window.__pwaUrl = status.pwa_url;
  } catch (err) {
    $("h-backend").textContent = "error";
    $("h-connected").textContent = "Disconnected";
    $("h-version").textContent = "—";
    $("live-tagline").textContent = `Backend unreachable — ${err.message}`;
    $("ready-pulse").className = "pulse fail";
  }
}

async function refreshPermissions() {
  const snap = await getPermissionSnapshot();
  const list = $("perm-list");
  list.innerHTML = "";
  for (const item of Object.values(snap)) {
    const li = document.createElement("li");
    const badgeClass =
      item.status === "allowed"
        ? "badge"
        : item.status === "coming_soon"
          ? "badge coming_soon"
          : "badge disabled";
    const label =
      item.status === "allowed"
        ? "Allowed"
        : item.status === "coming_soon"
          ? "Coming soon"
          : "Disabled";
    li.innerHTML = `<span>${item.label}<br/><small style="color:var(--muted)">${item.detail}</small></span><span class="${badgeClass}">${label}</span>`;
    list.appendChild(li);
  }
}

async function onSave() {
  $("btn-save").disabled = true;
  $("save-card").hidden = false;
  $("save-msg").textContent = "Added to Memory";
  $("save-detail").textContent = "Processing…";
  $("btn-retry").hidden = true;
  setStageVisual("queued");

  const resp = await chrome.runtime.sendMessage({ type: "SAVE_TO_MEMORY" });
  if (!resp?.ok) {
    $("save-msg").textContent = "Could not add to Memory";
    $("save-detail").textContent = resp?.error || "Unknown error";
    setStageVisual("failed");
    $("btn-retry").hidden = true;
    $("btn-save").disabled = false;
    return;
  }
  currentCaptureId = resp.status.capture_id;
  $("save-detail").textContent = resp.status.message || resp.status.stage_detail || "";
  startPolling(currentCaptureId);
}

function startPolling(captureId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const resp = await chrome.runtime.sendMessage({
      type: "POLL_CAPTURE",
      captureId,
    });
    if (!resp?.ok) return;
    applyCaptureStatus(resp.status);
  }, 1200);
}

function applyCaptureStatus(status) {
  const stage = status.stage || status.status;
  setStageVisual(stage);
  $("save-detail").textContent = status.message || status.stage_detail || status.error || "";
  if (stage === "completed" || status.status === "completed" || status.status === "stored") {
    $("save-msg").textContent = "In Memory";
    $("btn-retry").hidden = true;
    $("btn-save").disabled = false;
    clearInterval(pollTimer);
    pollTimer = null;
    refreshHealth();
  } else if (stage === "failed" || status.status === "failed") {
    $("save-msg").textContent = "Failed";
    $("btn-retry").hidden = false;
    $("btn-save").disabled = false;
    clearInterval(pollTimer);
    pollTimer = null;
  } else {
    $("save-msg").textContent = "Added to Memory";
  }
}

function setStageVisual(stage) {
  const order = [
    "queued",
    "metadata",
    "transcript",
    "chunking",
    "embedding",
    "indexed",
    "completed",
  ];
  const alias = {
    processing: "metadata",
    storing: "indexed",
    capsule: "chunking",
    skipped: "completed",
    stored: "completed",
    retry: "queued",
  };
  const normalized = alias[stage] || stage;
  const failed = stage === "failed";
  const idx = order.indexOf(normalized);
  for (const li of $("stages").querySelectorAll("li")) {
    li.className = "";
    const s = li.dataset.stage;
    const si = order.indexOf(s);
    if (failed) {
      if (si <= Math.max(idx, 0)) li.className = "done";
      if (s === "completed") {
        li.className = "fail";
        li.textContent = "Failed";
      }
      continue;
    }
    li.textContent = s[0].toUpperCase() + s.slice(1);
    if (normalized === "completed" || normalized === "indexed") {
      if (si <= order.indexOf(normalized)) li.className = "done";
      continue;
    }
    if (si < idx) li.className = "done";
    if (si === idx) li.className = "active";
  }
}

async function onRetry() {
  if (!currentCaptureId) return;
  $("btn-retry").hidden = true;
  const resp = await chrome.runtime.sendMessage({
    type: "RETRY_CAPTURE",
    captureId: currentCaptureId,
  });
  if (resp?.ok) {
    applyCaptureStatus(resp.status);
    startPolling(currentCaptureId);
  }
}

function workspaceDeepLink(hash) {
  const base = `${String(window.__pwaUrl || "http://127.0.0.1:8000/")
    .trim()
    .replace(/\/+$/, "")}/`;
  const frag = hash.startsWith("#") ? hash : `#${hash}`;
  return `${base}${frag}`;
}

function observerContextPayload() {
  if (!activeContext) return null;
  return {
    url: activeContext.url || activeContext.canonicalUrl || null,
    title: activeContext.title || null,
    platform: activeContext.platform || null,
  };
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setCommandHint(msg, isError = false) {
  const el = $("command-hint");
  el.textContent = msg || "";
  el.style.color = isError ? "var(--fail)" : "var(--muted)";
  el.setAttribute("role", "status");
}

function renderCommandPlan(plan) {
  lastCommandPlan = plan;
  const box = $("command-plan");
  const actions = $("command-actions");
  const confirmBtn = $("btn-command-confirm");
  const wsBtn = $("btn-command-workspace");
  if (!plan) {
    box.hidden = true;
    actions.hidden = true;
    return;
  }
  const steps = (plan.steps || [])
    .map((s) => `<li>${escapeHtml(s.label || s.id)}</li>`)
    .join("");
  box.hidden = false;
  box.innerHTML = `
    <div class="plan-head">
      <span class="badge">${escapeHtml(plan.intent)}</span>
      <span class="muted">${Math.round((plan.confidence || 0) * 100)}%</span>
    </div>
    <p class="plan-summary">${escapeHtml(plan.summary || "")}</p>
    <ol class="plan-steps">${steps}</ol>
    ${plan.bulk ? `<p class="callout"><strong>Bulk:</strong> confirm required — no silent import.</p>` : ""}
    ${plan.help_text ? `<p class="muted">${escapeHtml(plan.help_text)}</p>` : ""}
  `;
  actions.hidden = false;
  confirmBtn.hidden = !plan.requires_confirm;
  wsBtn.hidden = !plan.workspace_url;
}

function renderCommandResults(status, message, result, intent) {
  const box = $("command-results");
  box.hidden = false;
  if (intent === "search" && result?.results) {
    const items = result.results.slice(0, 5);
    if (!items.length) {
      box.innerHTML = `<p class="muted">${escapeHtml(message || "No results.")}</p>`;
      return;
    }
    box.innerHTML = items
      .map((r) => {
        const title = escapeHtml(r.title || r.video_title || "Untitled");
        const snip = escapeHtml(
          (r.snippet || r.matched_text || r.why_matched || "").slice(0, 160)
        );
        const trust = trustBadgeHtml(r);
        return `<div class="cmd-hit"><strong>${title}</strong>${trust ? `<div>${trust}</div>` : ""}<p class="muted">${snip}</p></div>`;
      })
      .join("");
    return;
  }
  if (intent === "ask" && result) {
    const answer = escapeHtml(
      (result.answer || result.response || message || "").slice(0, 600)
    );
    const sources = (result.sources || result.citations || []).slice(0, 3);
    const srcHtml = sources
      .map((s) => `<li>${escapeHtml(s.title || s.video_id || "source")}</li>`)
      .join("");
    box.innerHTML = `
      <p class="cmd-answer">${answer}</p>
      ${srcHtml ? `<ul class="cmd-sources">${srcHtml}</ul>` : ""}
      <p class="muted">${escapeHtml(message || "")}</p>
    `;
    return;
  }
  box.innerHTML = `<p class="${status === "error" || status === "confirm_required" ? "fail-text" : "muted"}">${escapeHtml(message || status)}</p>`;
}

async function onCommandSubmit(e) {
  e.preventDefault();
  if (commandInFlight) return;
  const text = $("command-input").value.trim();
  if (!text) {
    setCommandHint("Type a command — try “help”.", true);
    return;
  }
  commandInFlight = true;
  $("btn-command").disabled = true;
  $("command-results").hidden = true;
  setCommandHint("Planning…");
  try {
    const resp = await postAgentCommand(settings, {
      text,
      context: observerContextPayload(),
      execute: true,
      limit: 5,
    });
    renderCommandPlan(resp.plan);
    if (resp.status === "confirm_required") {
      setCommandHint("Review the plan, then confirm bulk action.", true);
      renderCommandResults(resp.status, resp.message, null, resp.plan?.intent);
    } else if (resp.plan?.intent === "save") {
      setCommandHint(resp.message || "Use Save To Memory for the current tab.");
      renderCommandResults(resp.status, resp.message, resp.result, "save");
      if (activeContext) await onSave();
    } else if (resp.executed && (resp.status === "executed" || resp.status === "handoff")) {
      setCommandHint(resp.message || "Done.");
      renderCommandResults(resp.status, resp.message, resp.result, resp.plan?.intent);
      if (
        resp.status === "handoff" &&
        resp.result?.workspace_url &&
        (resp.plan?.intent === "open_workspace" ||
          resp.plan?.intent === "import_playlist")
      ) {
        // Don't auto-open for bulk until confirmed; open_workspace may.
        if (resp.plan?.intent === "open_workspace") {
          chrome.tabs.create({ url: resp.result.workspace_url });
        }
      }
    } else {
      setCommandHint(resp.message || "Planned.", resp.status === "error");
      renderCommandResults(resp.status, resp.message, resp.result, resp.plan?.intent);
    }
  } catch (err) {
    setCommandHint(err.message || String(err), true);
    renderCommandPlan(null);
  } finally {
    commandInFlight = false;
    $("btn-command").disabled = false;
  }
}

async function onCommandConfirmBulk() {
  if (commandInFlight) return;
  if (!lastCommandPlan?.confirm_token || !lastCommandPlan.requires_confirm) {
    setCommandHint("Nothing to confirm — run a bulk command first.", true);
    return;
  }
  commandInFlight = true;
  $("btn-command-confirm").disabled = true;
  setCommandHint("Confirming…");
  const consumedToken = lastCommandPlan.confirm_token;
  try {
    const resp = await executeAgentCommand(settings, {
      intent: lastCommandPlan.intent,
      query: lastCommandPlan.query,
      original_text: lastCommandPlan.original_text || $("command-input").value,
      confirm_token: consumedToken,
      context: observerContextPayload(),
    });
    // Clear consumed token from local state (server marks single-use).
    if (lastCommandPlan) {
      lastCommandPlan = {
        ...lastCommandPlan,
        ...(resp.plan || {}),
        confirm_token: resp.plan?.confirm_token ?? null,
        requires_confirm: Boolean(resp.plan?.requires_confirm),
      };
    }
    renderCommandPlan(lastCommandPlan);
    renderCommandResults(resp.status, resp.message, resp.result, lastCommandPlan?.intent);
    if (!resp.executed || resp.status === "confirm_required" || resp.status === "error") {
      setCommandHint(resp.message || "Confirm failed.", true);
      return;
    }
    setCommandHint(resp.message || "Confirmed — finish preview in Workspace.");
    // Handoff to existing preview→confirm UX (never silent bulk write).
    if (lastCommandPlan?.intent === "import_bookmarks") {
      await onBookmarksStart();
      $("import-card")?.scrollIntoView?.({ block: "nearest" });
    } else if (resp.result?.workspace_url || lastCommandPlan?.workspace_url) {
      chrome.tabs.create({
        url: resp.result?.workspace_url || lastCommandPlan.workspace_url,
      });
    }
  } catch (err) {
    setCommandHint(err.message || String(err), true);
  } finally {
    commandInFlight = false;
    $("btn-command-confirm").disabled = false;
  }
}

function onCommandOpenWorkspace() {
  const url = lastCommandPlan?.workspace_url;
  if (!url) {
    chrome.tabs.create({ url: workspaceDeepLink("#dashboard") });
    return;
  }
  chrome.tabs.create({ url });
}

async function onAsk() {
  const q = $("command-input").value.trim();
  if (q) {
    $("command-input").value = q.startsWith("ask ") ? q : `ask ${q}`;
    await onCommandSubmit(new Event("submit"));
    return;
  }
  chrome.tabs.create({ url: workspaceDeepLink("#ask") });
}

async function onSearchMemory() {
  const q = $("command-input").value.trim();
  if (q) {
    $("command-input").value = /^(search|find)\b/i.test(q) ? q : `search ${q}`;
    await onCommandSubmit(new Event("submit"));
    return;
  }
  chrome.tabs.create({ url: workspaceDeepLink("#search") });
}

async function onPlaylistWorkspace() {
  // Deep-link only — never starts playlist ingest or Watch Later from the popup.
  chrome.tabs.create({ url: workspaceDeepLink("#capture") });
}

function setImportStatus(msg, isError = false) {
  const el = $("import-status");
  el.textContent = msg || "";
  el.style.color = isError ? "var(--fail)" : "var(--muted)";
}

function walkBookmarks(nodes, path, out) {
  for (const n of nodes || []) {
    const nextPath = n.title ? (path ? `${path}/${n.title}` : n.title) : path;
    if (n.url && /^https?:\/\//i.test(n.url)) {
      out.push({
        browser_bookmark_id: String(n.id),
        folder_path: path || "Bookmarks",
        url: n.url,
        title: n.title || n.url,
      });
    }
    if (n.children?.length) walkBookmarks(n.children, nextPath, out);
  }
}

async function collectBookmarkItems() {
  const tree = await chrome.bookmarks.getTree();
  const items = [];
  walkBookmarks(tree, "", items);
  // Cap payload size for V1 preview/confirm
  return items.slice(0, 500);
}

async function onBookmarksStart() {
  setImportStatus("Requesting bookmarks permission…");
  const granted = await requestBookmarksPermission();
  if (!granted) {
    setImportStatus("Bookmarks permission denied.", true);
    await refreshPermissions();
    return;
  }
  try {
    pendingBookmarkItems = await collectBookmarkItems();
    bookmarkPreviewDone = false;
    $("bookmark-panel").hidden = false;
    $("btn-bookmark-confirm").disabled = true;
    $("bookmark-preview").hidden = true;
    $("bookmark-summary").textContent = `${pendingBookmarkItems.length} bookmark URL(s) found — preview before import.`;
    setImportStatus("Ready to preview.");
    await refreshPermissions();
  } catch (err) {
    setImportStatus(err.message || String(err), true);
  }
}

async function onBookmarkPreview() {
  if (!pendingBookmarkItems?.length) {
    setImportStatus("No bookmarks loaded.", true);
    return;
  }
  setImportStatus("Previewing…");
  $("btn-bookmark-confirm").disabled = true;
  bookmarkPreviewDone = false;
  try {
    const data = await previewBookmarks(settings, {
      source_browser: "chrome",
      sync_mode: "manual",
      items: pendingBookmarkItems,
    });
    const pre = $("bookmark-preview");
    pre.hidden = false;
    pre.textContent = JSON.stringify(
      {
        total: data.total ?? pendingBookmarkItems.length,
        new: data.new_count ?? data.new,
        duplicates: data.duplicate_count ?? data.duplicates,
        unsupported: data.unsupported_count ?? data.unsupported,
        ...data,
      },
      null,
      2
    ).slice(0, 2500);
    bookmarkPreviewDone = true;
    $("btn-bookmark-confirm").disabled = false;
    setImportStatus("Preview ready — confirm to import.");
  } catch (err) {
    setImportStatus(err.message || String(err), true);
  }
}

async function onBookmarkConfirm() {
  if (!pendingBookmarkItems?.length || !bookmarkPreviewDone) {
    setImportStatus("Preview bookmarks first.", true);
    return;
  }
  $("btn-bookmark-confirm").disabled = true;
  setImportStatus("Importing bookmarks…");
  try {
    const data = await importBookmarks(settings, {
      source_browser: "chrome",
      sync_mode: "manual",
      items: pendingBookmarkItems,
    });
    setImportStatus(
      `Import ${data.import_id || "started"} · ${data.status || "queued"}`
    );
    pendingBookmarkItems = null;
    bookmarkPreviewDone = false;
  } catch (err) {
    $("btn-bookmark-confirm").disabled = false;
    setImportStatus(err.message || String(err), true);
  }
}

async function onPdfUpload() {
  const file = $("pdf-file").files?.[0];
  if (!file) {
    setImportStatus("Choose a PDF file.", true);
    return;
  }
  if (file.size > 50 * 1024 * 1024) {
    setImportStatus("PDF too large (max 50MB).", true);
    return;
  }
  setImportStatus("Uploading PDF…");
  $("btn-pdf-upload").disabled = true;
  try {
    const data = await capturePdf(settings, file, file.name);
    if (data?.success === false && data?.error) {
      setImportStatus(data.error, true);
    } else {
      setImportStatus(`PDF ingested · ${data?.title || file.name}`);
    }
  } catch (err) {
    setImportStatus(err.message || String(err), true);
  } finally {
    $("btn-pdf-upload").disabled = false;
  }
}

async function onPauseToggle() {
  if (settings.observerPaused) {
    await chrome.runtime.sendMessage({ type: "RESUME_OBSERVER" });
    settings.observerPaused = false;
  } else {
    await chrome.runtime.sendMessage({ type: "PAUSE_OBSERVER" });
    settings.observerPaused = true;
  }
  $("btn-pause").textContent = settings.observerPaused
    ? "Resume Observation"
    : "Pause Observation";
  await refreshContext();
}

async function onViewContext() {
  $("context-json").textContent = JSON.stringify(activeContext || {}, null, 2);
  $("context-dialog").showModal();
}

async function restoreActiveCapture() {
  const local = await chrome.storage.local.get([
    STORAGE_KEYS.lastCaptureId,
    STORAGE_KEYS.lastCaptureAt,
  ]);
  if (!local.lastCaptureId) return;
  if (local.lastCaptureAt && Date.now() - local.lastCaptureAt > 15 * 60 * 1000) return;
  currentCaptureId = local.lastCaptureId;
  $("save-card").hidden = false;
  startPolling(currentCaptureId);
}

function formatTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

init();
