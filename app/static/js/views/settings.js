import { Api, clearApiCache } from "../api.js";
import {
  $,
  escapeHtml,
  loadSettings,
  saveSettings,
  setStatus,
  emptyState,
  SOURCE_TYPES,
} from "../util.js";

export function mountSettings(root) {
  const s = loadSettings();
  const connectorOptions = SOURCE_TYPES.map(
    (t) => `<option value="${escapeHtml(t.id)}.v1">${escapeHtml(t.label)}</option>`
  ).join("");
  root.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <h2>Settings</h2>
        <span class="panel-caption">Local preferences · connector health · debug</span>
      </div>

      <h3>Theme</h3>
      <label class="sr-only" for="set-theme">Theme</label>
      <select id="set-theme" aria-label="Theme">
        <option value="system">System</option>
        <option value="dark">Dark</option>
        <option value="light">Light</option>
      </select>

      <h3>Backend</h3>
      <label for="set-token">API token (optional)
        <input id="set-token" type="password" autocomplete="off" placeholder="Bearer token" />
      </label>
      <p class="muted">Workspace uses same-origin <code>/api/v1</code>. Extension backend URL is configured in extension options. Tokens are stored only in this browser's localStorage.</p>
      <div class="row-actions">
        <button type="button" id="set-logout">Log out / revoke session</button>
      </div>
      <p id="set-auth-status" class="status" hidden role="status"></p>

      <h3>Privacy</h3>
      <label class="checkbox-row"><input id="set-privacy" type="checkbox" /> Minimize analytics / usage posts from this UI</label>
      <label class="checkbox-row"><input id="set-notifications" type="checkbox" /> Show completion toasts when supported</label>
      <p class="muted">Read the <a href="/privacy" target="_blank" rel="noopener">privacy policy</a>. Export or delete your Memory data below.</p>
      <div class="row-actions">
        <button type="button" id="set-export">Export my data (JSON)</button>
        <button type="button" id="set-delete-all" class="danger">Delete all memories</button>
      </div>
      <p id="set-privacy-status" class="status" hidden role="status" aria-live="polite"></p>

      <h3>Import defaults</h3>
      <label for="set-default-connector">Default connector hint
        <select id="set-default-connector">
          <option value="">Auto</option>
          ${connectorOptions}
        </select>
      </label>

      <h3>Debug</h3>
      <label class="checkbox-row"><input id="set-debug" type="checkbox" /> Show API path hints in status lines</label>
      <button type="button" id="set-save">Save settings</button>
      <p id="set-status" class="status" hidden role="status"></p>
    </section>

    <section class="panel">
      <div class="panel-header"><h2>Connector management</h2></div>
      <div id="set-connectors">${emptyState("Loading…")}</div>
    </section>

    <section class="panel">
      <div class="panel-header"><h2>Backend health</h2></div>
      <pre id="set-health" class="code-block">Loading…</pre>
    </section>
  `;

  $("#set-theme", root).value = s.theme || "system";
  $("#set-token", root).value = localStorage.getItem("am_token") || "";
  $("#set-privacy", root).checked = !!s.privacy_minimize;
  $("#set-notifications", root).checked = s.notifications !== false;
  $("#set-default-connector", root).value = s.default_connector || "";
  $("#set-debug", root).checked = !!s.debug;

  applyTheme(s.theme || "system");

  $("#set-save", root).addEventListener("click", () => {
    const theme = $("#set-theme", root).value;
    const token = $("#set-token", root).value.trim();
    if (token) localStorage.setItem("am_token", token);
    else localStorage.removeItem("am_token");
    saveSettings({
      theme,
      privacy_minimize: $("#set-privacy", root).checked,
      notifications: $("#set-notifications", root).checked,
      default_connector: $("#set-default-connector", root).value,
      debug: $("#set-debug", root).checked,
    });
    applyTheme(theme);
    setStatus($("#set-status", root), "Saved.", "success");
  });

  $("#set-logout", root).addEventListener("click", async () => {
    const status = $("#set-auth-status", root);
    try {
      await Api.logout();
      localStorage.removeItem("am_token");
      $("#set-token", root).value = "";
      clearApiCache();
      setStatus(status, "Logged out. Session revoked.", "success");
    } catch (err) {
      localStorage.removeItem("am_token");
      $("#set-token", root).value = "";
      setStatus(status, err.message || "Logout failed; local token cleared.", "error");
    }
  });

  $("#set-export", root).addEventListener("click", async () => {
    const status = $("#set-privacy-status", root);
    try {
      const data = await Api.exportPrivacyData(false);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ai-memory-export-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus(status, "Export downloaded.", "success");
    } catch (err) {
      setStatus(status, err.message || "Export failed", "error");
    }
  });

  $("#set-delete-all", root).addEventListener("click", async () => {
    const status = $("#set-privacy-status", root);
    if (!window.confirm("Permanently delete ALL memories for this user?")) return;
    try {
      const result = await Api.deleteAllMemories();
      clearApiCache();
      setStatus(
        status,
        `Deleted ${result.deleted_count ?? 0} memor${(result.deleted_count ?? 0) === 1 ? "y" : "ies"}.`,
        "success"
      );
    } catch (err) {
      setStatus(status, err.message || "Delete failed", "error");
    }
  });

  loadHealth(root);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme === "system" ? "" : theme;
}

async function loadHealth(root) {
  try {
    const [health, connectors, config] = await Promise.all([
      Api.health(),
      Api.connectorsHealth().catch(() => ({ connectors: [] })),
      Api.pwaConfig().catch(() => ({})),
    ]);
    $("#set-health", root).textContent = JSON.stringify({ health, config }, null, 2);
    const list = connectors.connectors || [];
    $("#set-connectors", root).innerHTML = list.length
      ? `<div class="list">${list
          .map(
            (c) => `
        <div class="list-row static">
          <span class="dot ${c.healthy ? "ok" : "bad"}" aria-hidden="true"></span>
          <span class="list-main">
            <strong>${escapeHtml(c.connector_id)}</strong>
            <small>${escapeHtml(c.detail || (c.healthy ? "healthy" : "unhealthy"))}</small>
          </span>
        </div>`
          )
          .join("")}</div>`
      : emptyState("No connectors reported");
  } catch (err) {
    $("#set-health", root).textContent = err.message;
  }
}
