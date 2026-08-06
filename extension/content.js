/**
 * Context Observer — content script (self-contained, no imports).
 * Collects temporary page context only. Never writes to Memory.
 */

(function () {
  "use strict";

  const RESTRICTED = [
    "chrome://",
    "chrome-extension://",
    "edge://",
    "about:",
    "devtools://",
    "view-source:",
  ];

  function isRestricted(url) {
    if (!url) return true;
    const lower = url.toLowerCase();
    return RESTRICTED.some((p) => lower.startsWith(p));
  }

  function classify(url) {
    if (isRestricted(url)) return "unsupported";
    try {
      const u = new URL(url);
      const host = u.hostname.replace(/^www\./, "");
      if (host === "youtube.com" || host === "m.youtube.com" || host === "youtu.be") {
        return "youtube";
      }
      if (u.protocol === "http:" || u.protocol === "https:") return "web";
    } catch {
      return "unsupported";
    }
    return "unsupported";
  }

  function youtubeVideoId(url) {
    try {
      const u = new URL(url);
      if (u.hostname.includes("youtu.be")) {
        return u.pathname.split("/").filter(Boolean)[0] || null;
      }
      if (u.searchParams.get("v")) return u.searchParams.get("v");
      const m = u.pathname.match(/\/(?:shorts|embed|live)\/([^/?]+)/);
      if (m) return m[1];
    } catch {
      return null;
    }
    return null;
  }

  function meta(name) {
    const el =
      document.querySelector(`meta[property="${name}"]`) ||
      document.querySelector(`meta[name="${name}"]`);
    return el?.getAttribute("content")?.trim() || "";
  }

  function parseYtInitial() {
    const scripts = Array.from(document.scripts);
    for (const s of scripts) {
      const text = s.textContent || "";
      if (!text.includes("ytInitialPlayerResponse")) continue;
      const m = text.match(/ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;/s);
      if (!m) continue;
      try {
        return JSON.parse(m[1]);
      } catch {
        /* continue */
      }
    }
    return null;
  }

  function observeYouTube(url) {
    const videoId = youtubeVideoId(url);
    const player = parseYtInitial();
    const videoDetails = player?.videoDetails || {};
    const video = document.querySelector("video");
    const title =
      videoDetails.title ||
      document.querySelector("h1.ytd-watch-metadata yt-formatted-string")?.textContent?.trim() ||
      document.title.replace(/ - YouTube$/i, "").trim() ||
      meta("og:title");
    const creator =
      videoDetails.author ||
      document.querySelector("#channel-name a")?.textContent?.trim() ||
      meta("og:video:tag") ||
      "";
    const description =
      (videoDetails.shortDescription || "").slice(0, 800) ||
      meta("og:description").slice(0, 800);
    const thumbnail =
      videoDetails.thumbnail?.thumbnails?.slice(-1)?.[0]?.url ||
      meta("og:image") ||
      (videoId ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : "");
    const durationSec = videoDetails.lengthSeconds
      ? Number(videoDetails.lengthSeconds)
      : video?.duration && Number.isFinite(video.duration)
        ? video.duration
        : null;
    const progressSec =
      video && Number.isFinite(video.currentTime) ? Math.floor(video.currentTime) : null;

    let transcriptAvailable = null;
    try {
      const hasCaptions =
        Boolean(player?.captions?.playerCaptionsTracklistRenderer?.captionTracks?.length) ||
        Boolean(document.querySelector(".ytp-subtitles-button"));
      transcriptAvailable = hasCaptions ? true : null;
    } catch {
      transcriptAvailable = null;
    }

    return {
      platform: "youtube",
      url,
      title,
      creator,
      description,
      thumbnail,
      videoId: videoId || videoDetails.videoId || "",
      durationSec,
      progressSec,
      transcriptAvailable,
      observedFrom: "content_script",
    };
  }

  function observeWeb(url) {
    const title = document.title || meta("og:title") || "";
    const creator =
      meta("author") ||
      meta("article:author") ||
      document.querySelector('[rel="author"]')?.textContent?.trim() ||
      "";
    const description = meta("og:description") || meta("description") || "";
    const thumbnail = meta("og:image") || "";
    const selection = window.getSelection?.()?.toString()?.trim() || "";
    return {
      platform: "web",
      url,
      title,
      creator,
      description: description.slice(0, 800),
      thumbnail,
      videoId: "",
      durationSec: null,
      progressSec: null,
      transcriptAvailable: null,
      selectedText: selection.slice(0, 2000),
      observedFrom: "content_script",
    };
  }

  function collect() {
    const url = location.href;
    if (isRestricted(url)) return null;
    const platform = classify(url);
    if (platform === "unsupported") return null;
    if (platform === "youtube") return observeYouTube(url);
    return observeWeb(url);
  }

  function publish() {
    const ctx = collect();
    if (!ctx) return;
    chrome.runtime.sendMessage({ type: "CONTEXT_OBSERVED", context: ctx }, () => {
      void chrome.runtime.lastError;
    });
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "GET_PAGE_CONTEXT") {
      sendResponse({ ok: true, context: collect() });
      return true;
    }
    return false;
  });

  // Never read password / payment fields — we only use title, meta, selection, video element.
  publish();
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      publish();
    }
  }, 1500);

  // Progress updates for YouTube — listen on document capture phase for video events
  document.addEventListener(
    "timeupdate",
    (ev) => {
      if (!(ev.target instanceof HTMLVideoElement)) return;
      if (classify(location.href) !== "youtube") return;
      if (!window.__aiMemoryProgressTick) {
        window.__aiMemoryProgressTick = true;
        setTimeout(() => {
          window.__aiMemoryProgressTick = false;
          publish();
        }, 4000);
      }
    },
    true
  );
})();
