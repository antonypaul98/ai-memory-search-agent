/**
 * Settings + temporary context storage helpers.
 * Temporary context lives in session storage and expires automatically.
 */

export const CONTEXT_TTL_MS = 30 * 60 * 1000;
export const STORAGE_KEYS = {
  apiBase: "apiBase",
  token: "token",
  theme: "theme",
  notificationsEnabled: "notificationsEnabled",
  privacyMode: "privacyMode",
  debugMode: "debugMode",
  observerPaused: "observerPaused",
  lastCaptureId: "lastCaptureId",
  lastCaptureAt: "lastCaptureAt",
};

/**
 * @returns {Promise<object>}
 */
export async function loadSettings() {
  const sync = await chrome.storage.sync.get([
    STORAGE_KEYS.apiBase,
    STORAGE_KEYS.token,
    STORAGE_KEYS.theme,
    STORAGE_KEYS.notificationsEnabled,
    STORAGE_KEYS.privacyMode,
    STORAGE_KEYS.debugMode,
  ]);
  const local = await chrome.storage.local.get([STORAGE_KEYS.observerPaused]);
  return {
    apiBase: sync.apiBase || "http://127.0.0.1:8000/api/v1",
    token: sync.token || "",
    theme: sync.theme || "system",
    notificationsEnabled: Boolean(sync.notificationsEnabled),
    privacyMode: Boolean(sync.privacyMode),
    debugMode: Boolean(sync.debugMode),
    observerPaused: Boolean(local.observerPaused),
  };
}

/**
 * @param {object} partial
 */
export async function saveSettings(partial) {
  const syncKeys = {};
  const localKeys = {};
  for (const [k, v] of Object.entries(partial)) {
    if (k === STORAGE_KEYS.observerPaused) {
      localKeys[k] = v;
    } else {
      syncKeys[k] = v;
    }
  }
  if (Object.keys(syncKeys).length) await chrome.storage.sync.set(syncKeys);
  if (Object.keys(localKeys).length) await chrome.storage.local.set(localKeys);
}

/**
 * @param {number|string} tabId
 * @param {object} context
 */
export async function writeTempContext(tabId, context) {
  const key = `ctx:${tabId}`;
  const payload = {
    ...context,
    observedAt: Date.now(),
    expiresAt: Date.now() + CONTEXT_TTL_MS,
  };
  if (chrome.storage.session) {
    await chrome.storage.session.set({ [key]: payload });
  } else {
    await chrome.storage.local.set({ [key]: payload });
  }
  return payload;
}

/**
 * @param {number|string} tabId
 */
export async function readTempContext(tabId) {
  const key = `ctx:${tabId}`;
  const store = chrome.storage.session || chrome.storage.local;
  const data = await store.get(key);
  const ctx = data[key];
  if (!ctx) return null;
  if (ctx.expiresAt && Date.now() > ctx.expiresAt) {
    await store.remove(key);
    return null;
  }
  return ctx;
}

export async function clearTempContext(tabId) {
  const key = `ctx:${tabId}`;
  if (chrome.storage.session) await chrome.storage.session.remove(key);
  await chrome.storage.local.remove(key);
}

export async function clearAllTempContext() {
  const session = chrome.storage.session;
  if (session) {
    const all = await session.get(null);
    const keys = Object.keys(all).filter((k) => k.startsWith("ctx:"));
    if (keys.length) await session.remove(keys);
  }
  const local = await chrome.storage.local.get(null);
  const localKeys = Object.keys(local).filter((k) => k.startsWith("ctx:"));
  if (localKeys.length) await chrome.storage.local.remove(localKeys);
}

/**
 * Remove expired temporary contexts.
 */
export async function sweepExpiredContext() {
  const store = chrome.storage.session || chrome.storage.local;
  const all = await store.get(null);
  const now = Date.now();
  const expired = [];
  for (const [k, v] of Object.entries(all)) {
    if (!k.startsWith("ctx:")) continue;
    if (v?.expiresAt && now > v.expiresAt) expired.push(k);
  }
  if (expired.length) await store.remove(expired);
  return expired.length;
}
