import { getHealth } from "./shared/api.js";
import { loadSettings, saveSettings } from "./shared/storage.js";
import { requestNotificationsPermission } from "./shared/permissions.js";

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
  await saveSettings({
    apiBase: $("apiBase").value.trim(),
    token: $("token").value.trim(),
    theme: $("theme").value,
    observerPaused: $("observerPaused").checked,
    privacyMode: $("privacyMode").checked,
    notificationsEnabled: $("notificationsEnabled").checked,
    debugMode: $("debugMode").checked,
  });
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
