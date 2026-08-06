/**
 * AI Memory Workspace — presentation shell over existing APIs.
 * No domain / connector business logic.
 */
import { abortInflight } from "./js/api.js";
import { bindNav, currentRoute, navigate } from "./js/router.js";
import { loadSettings } from "./js/util.js";
import { renderDashboard } from "./js/views/dashboard.js";
import { mountSearch, applySearchQuery } from "./js/views/search.js";
import { mountAsk, applyAskQuery } from "./js/views/ask.js";
import { mountTimeline, disposeTimeline } from "./js/views/timeline.js";
import { mountTopics } from "./js/views/topics.js";
import { mountImports } from "./js/views/imports.js";
import { mountCapture, disposeCapture } from "./js/views/capture.js";
import { mountSettings } from "./js/views/settings.js";
import { renderMemory } from "./js/views/memory.js";

const mounted = {
  search: false,
  ask: false,
  timeline: false,
  topics: false,
  imports: false,
  capture: false,
  settings: false,
};

const TITLE = {
  dashboard: "Dashboard",
  search: "Search",
  ask: "Ask Memory",
  timeline: "Timeline",
  topics: "Topics",
  imports: "Imports",
  capture: "Capture",
  settings: "Settings",
  memory: "Memory",
};

const LEAD = {
  dashboard: "What is happening across your library right now.",
  search: "Search YouTube, articles, PDFs, GitHub, and bookmarks together.",
  ask: "Ask grounded questions over saved memories.",
  timeline: "Browse when knowledge was saved and learned.",
  topics: "Explore topics, roadmaps, and capsules.",
  imports: "Monitor, resume, and cancel connector imports.",
  capture: "Ingest URLs, playlists, bookmarks, and PDFs.",
  settings: "Theme, privacy, tokens, and connector health.",
  memory: "Metadata, evidence, related memories, and processing history.",
};

function applyLegacyHash() {
  const h = (location.hash || "").replace(/^#/, "");
  if (h === "chat") {
    location.replace("#ask");
    return true;
  }
  return false;
}

function safeDecodeURIComponent(value) {
  if (!value) return "";
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function onlineBanner() {
  const el = document.getElementById("online-status");
  if (!el) return;
  const sync = () => {
    el.textContent = navigator.onLine ? "Online" : "Offline";
    el.classList.toggle("offline", !navigator.onLine);
    el.classList.toggle("online", navigator.onLine);
  };
  window.addEventListener("online", sync);
  window.addEventListener("offline", sync);
  sync();
}

function updateChrome(route) {
  document.title = `${TITLE[route] || "Workspace"} · AI Memory`;
  const h1 = document.querySelector(".workspace-title");
  const lead = document.querySelector(".workspace-lead");
  if (h1) h1.textContent = TITLE[route] || "Workspace";
  if (lead) lead.textContent = LEAD[route] || "";
}

function disposeLeaving(prevRoute) {
  abortInflight(prevRoute || "");
  if (prevRoute === "capture") disposeCapture();
  if (prevRoute === "timeline") disposeTimeline();
}

let _prevRoute = "";

async function onRoute(route, param, ctx = {}) {
  const { signal } = ctx;
  if (_prevRoute && _prevRoute !== route) disposeLeaving(_prevRoute);
  _prevRoute = route;
  updateChrome(route);

  if (route === "dashboard") {
    await renderDashboard(document.getElementById("view-dashboard"), { signal });
    return;
  }
  if (route === "memory") {
    await renderMemory(document.getElementById("view-memory"), param, { signal });
    return;
  }
  if (route === "topics") {
    mountTopics(document.getElementById("view-topics"), param, { signal });
    mounted.topics = true;
    return;
  }
  if (route === "search") {
    const root = document.getElementById("view-search");
    const q = param ? safeDecodeURIComponent(param) : "";
    if (!mounted.search) {
      mountSearch(root, q);
      mounted.search = true;
    } else if (q) {
      applySearchQuery(root, q);
    }
    return;
  }
  if (route === "ask") {
    const root = document.getElementById("view-ask");
    const q = param ? safeDecodeURIComponent(param) : "";
    if (!mounted.ask) {
      mountAsk(root, q);
      mounted.ask = true;
    } else if (q) {
      applyAskQuery(root, q);
    }
    return;
  }
  if (route === "timeline") {
    if (!mounted.timeline) {
      mountTimeline(document.getElementById("view-timeline"));
      mounted.timeline = true;
    }
    return;
  }
  if (route === "imports") {
    mountImports(document.getElementById("view-imports"));
    mounted.imports = true;
    return;
  }
  if (route === "capture") {
    if (!mounted.capture) {
      mountCapture(document.getElementById("view-capture"));
      mounted.capture = true;
    }
    return;
  }
  if (route === "settings") {
    mountSettings(document.getElementById("view-settings"));
    mounted.settings = true;
  }
}

function handleShareTarget() {
  const params = new URLSearchParams(location.search);
  const shared = params.get("url") || params.get("text") || "";
  if (!shared) return;
  navigate("capture");
  setTimeout(() => {
    const input = document.getElementById("url-input");
    if (input && !input.value) input.value = shared;
  }, 50);
}

function boot() {
  applyLegacyHash();
  const settings = loadSettings();
  if (settings.theme && settings.theme !== "system") {
    document.documentElement.dataset.theme = settings.theme;
  }
  onlineBanner();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  bindNav(onRoute);
  handleShareTarget();
  currentRoute();
}

boot();
