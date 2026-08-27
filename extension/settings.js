import { getHealth } from "./shared/api.js";
import { loadSettings, saveSettings } from "./shared/storage.js";
import {
  requestBookmarksPermission,
  requestNotificationsPermission,
} from "./shared/permissions.js";

const $ = (id) => document.getElementById(id);

async function init() {
  const s = await loadSettings();
  $("apiBase").value = s.apiBase;
  $("token").value = s.token;
  $("theme").value = s.theme;
  $("observerPaused").checked = s.observerPaused;
  $("privacyMode").checked = s.privacyMode;
  $("notificationsEnabled").checked = s.notificationsEnabled;
  $("debugMode").checked = s.debugMode;
  $("bookmarkSyncEnabled").checked = s.bookmarkSyncEnabled;
  $("bookmarkSyncHours").value = String(s.bookmarkSyncHours || 24);
  document.body.dataset.theme = s.theme;

  $("btn-save").addEventListener("click", onSave);
  $("btn-test").addEventListener("click", onTest);
  $("theme").addEventListener("change", () => {
    document.body.dataset.theme = $("theme").value;
  });
}

async function onSave() {
  if ($("notificationsEnabled").checked) {
    await requestNotificationsPermission();
  }

  let bookmarkSyncEnabled = $("bookmarkSyncEnabled").checked;
  if (bookmarkSyncEnabled) {
    const granted = await requestBookmarksPermission();
    if (!granted) {
      bookmarkSyncEnabled = false;
      $("bookmarkSyncEnabled").checked = false;
      $("bookmark-sync-status").textContent =
        "Bookmarks permission was not granted, so scheduled sync remains off.";
    } else {
      $("bookmark-sync-status").textContent = "Scheduled bookmark sync enabled.";
    }
  } else {
    $("bookmark-sync-status").textContent = "Scheduled bookmark sync is off.";
  }

  const rawHours = Number($("bookmarkSyncHours").value || 24);
  const bookmarkSyncHours = Number.isFinite(rawHours)
    ? Math.min(168, Math.max(1, Math.round(rawHours)))
    : 24;

  await saveSettings({
    apiBase: $("apiBase").value.trim(),
    token: $("token").value.trim(),
    theme: $("theme").value,
    observerPaused: $("observerPaused").checked,
    privacyMode: $("privacyMode").checked,
    notificationsEnabled: $("notificationsEnabled").checked,
    debugMode: $("debugMode").checked,
    bookmarkSyncEnabled,
    bookmarkSyncHours,
  });
  await chrome.runtime.sendMessage({ type: "CONFIGURE_BOOKMARK_SYNC" });
  $("save-status").textContent = "Settings saved.";
}

async function onTest() {
  $("conn-status").textContent = "Checking…";
  try {
    const health = await getHealth({
      apiBase: $("apiBase").value.trim(),
      token: $("token").value.trim(),
    });
    $("conn-status").textContent = `Connected — ${health.app_name} (${health.status})`;
  } catch (err) {
    $("conn-status").textContent = `Failed — ${err.message}`;
  }
}

init();
