import assert from "node:assert/strict";
import test from "node:test";

import { trustBadgeHtml } from "../../extension/shared/trust.js";

test("renders persisted trust tier and percentage", () => {
  assert.equal(
    trustBadgeHtml({ trust_tier: "high_confidence", trust_score: 0.876 }),
    '<span class="badge" title="Persisted trust score">Trust: high confidence 88%</span>'
  );
});

test("omits invalid trust metadata and clamps scores", () => {
  assert.equal(trustBadgeHtml({ trust_score: 0.5 }), "");
  assert.equal(trustBadgeHtml({ trust_tier: "high", trust_score: "nope" }), "");
  assert.match(trustBadgeHtml({ trust_tier: "high", trust_score: 1.5 }), />Trust: high 100%</);
});

test("escapes trust labels before rendering", () => {
  const html = trustBadgeHtml({ trust_tier: '<img src=x onerror="boom">', trust_score: 0.4 });
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
});
