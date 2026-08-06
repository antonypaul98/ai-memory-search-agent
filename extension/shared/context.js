/**
 * Pure helpers for Context Observer — unit-testable without Chrome APIs.
 */

export const RESTRICTED_URL_PREFIXES = [
  "chrome://",
  "chrome-extension://",
  "edge://",
  "about:",
  "devtools://",
  "view-source:",
  "chrome-search://",
  "chrome-devtools://",
];

/**
 * @param {string} url
 * @returns {boolean}
 */
export function isRestrictedUrl(url) {
  if (!url || typeof url !== "string") return true;
  const lower = url.toLowerCase();
  return RESTRICTED_URL_PREFIXES.some((p) => lower.startsWith(p));
}

/**
 * @param {string} url
 * @returns {"youtube"|"web"|"unsupported"}
 */
export function classifyPlatform(url) {
  if (isRestrictedUrl(url)) return "unsupported";
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

/**
 * @param {string} url
 * @returns {string|null}
 */
export function extractYoutubeVideoId(url) {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) {
      return u.pathname.split("/").filter(Boolean)[0] || null;
    }
    if (u.searchParams.get("v")) return u.searchParams.get("v");
    const shorts = u.pathname.match(/\/(?:shorts|embed|live)\/([^/?]+)/);
    if (shorts) return shorts[1];
  } catch {
    return null;
  }
  return null;
}

/**
 * @param {object} ctx
 * @returns {boolean}
 */
export function isContextExpired(ctx, now = Date.now()) {
  if (!ctx) return true;
  if (!ctx.expiresAt) return false;
  return now > ctx.expiresAt;
}

/**
 * Build a user-facing observation summary.
 * @param {object} ctx
 */
export function summarizeContext(ctx) {
  if (!ctx) {
    return {
      platformLabel: "None",
      title: "Nothing observed yet",
      transcriptLabel: "—",
      ready: false,
    };
  }
  const platform = ctx.platform || "web";
  const platformLabel =
    platform === "youtube" ? "YouTube" : platform === "web" ? "Web page" : "Unsupported";
  let transcriptLabel = "Unknown";
  if (ctx.transcriptAvailable === true) transcriptLabel = "Likely available";
  if (ctx.transcriptAvailable === false) transcriptLabel = "Unavailable / unknown";
  if (platform === "web") transcriptLabel = "Page text on save";
  return {
    platformLabel,
    title: ctx.title || "Untitled",
    creator: ctx.creator || "",
    transcriptLabel,
    ready: Boolean(ctx.url) && !isRestrictedUrl(ctx.url),
    progressSec: ctx.progressSec ?? null,
    thumbnail: ctx.thumbnail || "",
  };
}
