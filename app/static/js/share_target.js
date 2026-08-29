const HTTP_URL_RE = /https?:\/\/[^\s<>"']+/i;
const TRAILING_PUNCTUATION_RE = /[),.;!?\]}]+$/;

function normalizeHttpUrl(value) {
  const candidate = String(value || "").trim().replace(TRAILING_PUNCTUATION_RE, "");
  if (!candidate) return "";
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return parsed.toString();
  } catch {
    return "";
  }
}

/** Extract one public-web-style URL from a Web Share Target payload. */
export function extractSharedUrl({ url = "", text = "" } = {}) {
  const direct = normalizeHttpUrl(url);
  if (direct) return direct;
  const match = String(text || "").match(HTTP_URL_RE);
  return match ? normalizeHttpUrl(match[0]) : "";
}

/** Route YouTube shares to video ingest and everything else to universal capture. */
export function shareDestination(url) {
  const normalized = normalizeHttpUrl(url);
  if (!normalized) return "";
  const host = new URL(normalized).hostname.toLowerCase();
  if (host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com")) {
    return "youtube";
  }
  return "universal";
}
