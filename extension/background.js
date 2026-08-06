/**
 * AI Memory Agent — service worker (MV3 module).
 */

import {
  saveToMemory,
  getCaptureStatus,
  retryCapture,
} from "./shared/api.js";
import {
  loadSettings,
  saveSettings,
  writeTempContext,
  readTempContext,
  clearTempContext,
  clearAllTempContext,
  sweepExpiredContext,
  STORAGE_KEYS,
} from "./shared/storage.js";
import { isRestrictedUrl, classifyPlatform } from "./shared/context.js";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "save-to-memory",
      title: "Add to Memory",
      contexts: ["page", "link", "selection"],
    });
  });
  chrome.alarms.create("context-ttl-sweep", { periodInMinutes: 5 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "context-ttl-sweep") {
    sweepExpiredContext();
  }
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "save-to-memory") return;
  const url = info.linkUrl || info.pageUrl || tab?.url;
  if (!url || isRestrictedUrl(url)) return;
  const settings = await loadSettings();
  let context = tab?.id != null ? await readTempContext(tab.id) : null;
  if (!context && tab?.id != null) {
    context = await requestPageContext(tab.id);
  }
  await performSave({
    settings,
    url,
    title: tab?.title || context?.title || "",
    selectedText: info.selectionText || context?.selectedText || "",
    context,
    tabId: tab?.id,
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then((result) => sendResponse(result))
    .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
  return true;
});

async function handleMessage(message, sender) {
  const type = message?.type;
  if (type === "CONTEXT_OBSERVED") {
    const settings = await loadSettings();
    if (settings.observerPaused) {
      return { ok: true, paused: true };
    }
    const tabId = sender.tab?.id;
    if (tabId == null) return { ok: false, error: "No tab" };
    if (sender.tab?.incognito) return { ok: false, error: "Incognito blocked" };
    const ctx = {
      ...message.context,
      tabId,
      windowId: sender.tab.windowId,
    };
    if (settings.privacyMode) {
      ctx.description = "";
      ctx.selectedText = "";
    }
    await writeTempContext(tabId, ctx);
    return { ok: true };
  }

  if (type === "GET_ACTIVE_CONTEXT") {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return { ok: false, context: null };
    let ctx = await readTempContext(tab.id);
    if (!ctx && !isRestrictedUrl(tab.url || "")) {
      ctx = await requestPageContext(tab.id);
      if (ctx) {
        ctx.tabId = tab.id;
        ctx.windowId = tab.windowId;
        const settings = await loadSettings();
        if (!settings.observerPaused) {
          await writeTempContext(tab.id, ctx);
        }
      }
    }
    if (!ctx && tab.url && !isRestrictedUrl(tab.url)) {
      ctx = {
        platform: classifyPlatform(tab.url),
        url: tab.url,
        title: tab.title || "",
        creator: "",
        description: "",
        thumbnail: "",
        tabId: tab.id,
        windowId: tab.windowId,
        observedFrom: "active_tab",
      };
    }
    return { ok: true, context: ctx, tab };
  }

  if (type === "PAUSE_OBSERVER") {
    await saveSettings({ [STORAGE_KEYS.observerPaused]: true });
    return { ok: true, paused: true };
  }

  if (type === "RESUME_OBSERVER") {
    await saveSettings({ [STORAGE_KEYS.observerPaused]: false });
    return { ok: true, paused: false };
  }

  if (type === "CLEAR_TEMP_CONTEXT") {
    if (message.tabId != null) {
      await clearTempContext(message.tabId);
    } else {
      await clearAllTempContext();
    }
    return { ok: true };
  }

  if (type === "SAVE_TO_MEMORY") {
    const settings = await loadSettings();
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url || isRestrictedUrl(tab.url)) {
      return { ok: false, error: "This page cannot be added to Memory." };
    }
    let context = await readTempContext(tab.id);
    if (!context) {
      context = await requestPageContext(tab.id);
    }
    return performSave({
      settings,
      url: tab.url,
      title: tab.title || context?.title || "",
      selectedText: context?.selectedText || "",
      context,
      tabId: tab.id,
      goal: message.goal || "",
    });
  }

  if (type === "POLL_CAPTURE") {
    const settings = await loadSettings();
    const status = await getCaptureStatus(settings, message.captureId);
    return { ok: true, status };
  }

  if (type === "RETRY_CAPTURE") {
    const settings = await loadSettings();
    const status = await retryCapture(settings, message.captureId);
    await chrome.storage.local.set({
      [STORAGE_KEYS.lastCaptureId]: status.capture_id,
      [STORAGE_KEYS.lastCaptureAt]: Date.now(),
    });
    return { ok: true, status };
  }

  return { ok: false, error: "Unknown message" };
}

async function requestPageContext(tabId) {
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "GET_PAGE_CONTEXT" });
    return resp?.context || null;
  } catch {
    return null;
  }
}

async function performSave({ settings, url, title, selectedText, context, tabId, goal }) {
  const observed = context
    ? {
        platform: context.platform || "",
        creator: context.creator || "",
        thumbnail: context.thumbnail || "",
        description: settings.privacyMode ? "" : context.description || "",
        video_id: context.videoId || "",
        duration_sec: context.durationSec ?? null,
        progress_sec: context.progressSec ?? null,
        transcript_available: context.transcriptAvailable ?? null,
        tab_id: tabId ?? null,
        window_id: context.windowId ?? null,
        extra: { title: context.title || title },
      }
    : null;

  const payload = {
    url,
    title: title || context?.title || "",
    selected_text: settings.privacyMode ? "" : selectedText || "",
    page_description: settings.privacyMode ? "" : context?.description || "",
    goal: goal || "",
    source_type: "agent_extension",
    async_processing: true,
    observed,
  };

  const status = await saveToMemory(settings, payload);
  await chrome.storage.local.set({
    [STORAGE_KEYS.lastCaptureId]: status.capture_id,
    [STORAGE_KEYS.lastCaptureAt]: Date.now(),
  });

  if (settings.notificationsEnabled) {
    try {
      chrome.notifications?.create({
        type: "basic",
        iconUrl: "icons/icon-128.png",
        title: "AI Memory Agent",
        message: status.message || "Added to Memory",
      });
    } catch {
      /* optional */
    }
  }

  return { ok: true, status };
}
