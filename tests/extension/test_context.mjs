/**
 * Unit tests for Context Observer pure helpers.
 * Run: node --test tests/extension/test_context.mjs
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  isRestrictedUrl,
  classifyPlatform,
  extractYoutubeVideoId,
  isContextExpired,
  summarizeContext,
} from "../../extension/shared/context.js";

describe("isRestrictedUrl", () => {
  it("blocks browser internals", () => {
    assert.equal(isRestrictedUrl("chrome://settings"), true);
    assert.equal(isRestrictedUrl("about:blank"), true);
    assert.equal(isRestrictedUrl("chrome-extension://abc/popup.html"), true);
  });

  it("allows http(s)", () => {
    assert.equal(isRestrictedUrl("https://www.youtube.com/watch?v=abc"), false);
  });
});

describe("classifyPlatform", () => {
  it("detects youtube", () => {
    assert.equal(classifyPlatform("https://www.youtube.com/watch?v=abc123"), "youtube");
    assert.equal(classifyPlatform("https://youtu.be/abc123"), "youtube");
  });

  it("detects web", () => {
    assert.equal(classifyPlatform("https://example.com/article"), "web");
  });
});

describe("extractYoutubeVideoId", () => {
  it("parses watch and short urls", () => {
    assert.equal(
      extractYoutubeVideoId("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
      "dQw4w9WgXcQ"
    );
    assert.equal(extractYoutubeVideoId("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ");
  });
});

describe("summarizeContext", () => {
  it("marks youtube ready to save", () => {
    const s = summarizeContext({
      platform: "youtube",
      url: "https://www.youtube.com/watch?v=abc",
      title: "Building AI Agents",
      transcriptAvailable: true,
    });
    assert.equal(s.platformLabel, "YouTube");
    assert.equal(s.title, "Building AI Agents");
    assert.equal(s.transcriptLabel, "Likely available");
    assert.equal(s.ready, true);
  });
});

describe("isContextExpired", () => {
  it("expires after expiresAt", () => {
    assert.equal(isContextExpired({ expiresAt: Date.now() - 1 }), true);
    assert.equal(isContextExpired({ expiresAt: Date.now() + 60_000 }), false);
  });
});
