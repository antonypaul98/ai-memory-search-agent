function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Render persisted trust metadata for extension search results.
 * Returns an empty string when trust metadata is unavailable or invalid.
 */
export function trustBadgeHtml(result) {
  const tier = result?.trust_tier;
  const score = Number(result?.trust_score);
  if (!tier || !Number.isFinite(score)) return "";

  const boundedScore = Math.min(1, Math.max(0, score));
  const label = String(tier).replaceAll("_", " ");
  return `<span class="badge" title="Persisted trust score">Trust: ${escapeHtml(label)} ${Math.round(boundedScore * 100)}%</span>`;
}
