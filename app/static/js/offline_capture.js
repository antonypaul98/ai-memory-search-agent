const DB_NAME = "ai-memory-offline";
const DB_VERSION = 1;
const STORE = "capture_urls";
const MAX_QUEUED = 100;
// Verified online identity is kept in memory only. Never infer an owner from a URL
// or replay legacy ownerless entries under the next person to use this browser.
let ownerContext = null;
let flushing = null;

function currentToken() {
  return localStorage.getItem("am_token") || "";
}

async function resolveOwner() {
  const token = currentToken();
  const response = await fetch("/api/v1/auth/me", { headers: authHeaders(token), cache: "no-store" });
  if (!response.ok) throw new Error("Connect and sign in before saving offline URLs.");
  const user = await response.json();
  if (!user.user_id || currentToken() !== token) throw new Error("Account changed. Reconnect before saving offline URLs.");
  ownerContext = { userId: user.user_id, token };
  return ownerContext;
}

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("Offline queue unavailable."));
  });
}

async function withStore(mode, fn) {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let value;
      try {
        value = fn(store, resolve, reject);
      } catch (err) {
        reject(err);
        return;
      }
      tx.onerror = () => reject(tx.error || new Error("Offline queue failed."));
      if (value !== undefined) resolve(value);
    });
  } finally {
    db.close();
  }
}

export async function offlineCaptureCount() {
  return withStore("readonly", (store, resolve, reject) => {
    const req = store.count();
    req.onsuccess = () => resolve(req.result || 0);
    req.onerror = () => reject(req.error);
  });
}

export async function enqueueOfflineCapture(url) {
  const normalized = new URL(String(url || "").trim());
  if (!/^https?:$/.test(normalized.protocol)) throw new Error("Only http(s) URLs can be queued.");
  const owner = ownerContext;
  if (!owner || owner.token !== currentToken()) {
    throw new Error("Connect and sign in before saving offline URLs.");
  }
  const count = await offlineCaptureCount();
  if (count >= MAX_QUEUED) throw new Error("Offline queue is full. Reconnect before saving more URLs.");
  return withStore("readwrite", (store, resolve, reject) => {
    const req = store.add({
      user_id: owner.userId,
      url: normalized.toString(),
      queued_at: new Date().toISOString(),
    });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function queuedItems() {
  return withStore("readonly", (store, resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function removeQueued(id) {
  return withStore("readwrite", (store, resolve, reject) => {
    const req = store.delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

function authHeaders(token = currentToken()) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function flushOfflineCaptures() {
  // Online events and startup can overlap; only one replay may own the queue.
  if (flushing) return flushing;
  flushing = flushOwnedCaptures().finally(() => { flushing = null; });
  return flushing;
}

async function flushOwnedCaptures() {
  if (!navigator.onLine) return { flushed: 0, remaining: await offlineCaptureCount() };
  const owner = await resolveOwner();
  const items = await queuedItems();
  let flushed = 0;
  for (const item of items) {
    if (item.user_id !== owner.userId) continue;
    if (currentToken() !== owner.token) break;
    try {
      const response = await fetch("/api/v1/capture/url", {
        method: "POST",
        headers: { ...authHeaders(owner.token), "X-Capture-Owner": owner.userId },
        body: JSON.stringify({ url: item.url }),
      });
      if (!response.ok) {
        break;
      }
      await removeQueued(item.id);
      flushed += 1;
    } catch {
      break;
    }
  }
  return { flushed, remaining: await offlineCaptureCount() };
}

function setCaptureStatus(message, kind = "success") {
  const status = document.getElementById("capture-status");
  if (!status) return;
  status.hidden = false;
  status.textContent = message;
  status.className = `status ${kind}`;
}

async function handleOfflineCaptureClick(event) {
  const button = event.target?.closest?.("#capture-url-btn");
  if (!button || navigator.onLine) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const input = document.getElementById("capture-url");
  const url = input?.value?.trim() || "";
  if (!url) {
    setCaptureStatus("Enter a URL to capture.", "error");
    return;
  }
  try {
    await enqueueOfflineCapture(url);
    if (input) input.value = "";
    const count = await offlineCaptureCount();
    setCaptureStatus(`Saved offline. ${count} URL(s) will sync when you reconnect.`, "success");
  } catch (err) {
    setCaptureStatus(err?.message || "Could not queue this URL.", "error");
  }
}

export function installOfflineCaptureQueue() {
  document.addEventListener("click", handleOfflineCaptureClick, true);
  window.addEventListener("online", async () => {
    const result = await flushOfflineCaptures().catch(() => null);
    if (!result || !result.flushed) return;
    const suffix = result.remaining ? ` ${result.remaining} still queued.` : " Queue is clear.";
    setCaptureStatus(`Synced ${result.flushed} offline capture(s).${suffix}`, "success");
  });
  if (navigator.onLine) flushOfflineCaptures().catch(() => {});
}
