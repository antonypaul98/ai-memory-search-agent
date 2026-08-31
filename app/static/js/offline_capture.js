const DB_NAME = "ai-memory-offline";
const DB_VERSION = 1;
const STORE = "capture_urls";
const MAX_QUEUED = 100;

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
  const count = await offlineCaptureCount();
  if (count >= MAX_QUEUED) throw new Error("Offline queue is full. Reconnect before saving more URLs.");
  return withStore("readwrite", (store, resolve, reject) => {
    const req = store.add({
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

function authHeaders() {
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem("am_token");
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function flushOfflineCaptures() {
  if (!navigator.onLine) return { flushed: 0, remaining: await offlineCaptureCount() };
  const items = await queuedItems();
  let flushed = 0;
  for (const item of items) {
    try {
      const response = await fetch("/api/v1/capture/url", {
        method: "POST",
        headers: authHeaders(),
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
