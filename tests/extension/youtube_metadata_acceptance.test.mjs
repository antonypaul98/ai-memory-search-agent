import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const contentScript = readFileSync(new URL("../../extension/content.js", import.meta.url), "utf8");

describe("V1-03 YouTube in-page metadata acceptance", () => {
  it("observes canonical YouTube identity and rich page metadata", () => {
    for (const requiredSignal of [
      "videoId",
      "videoDetails.title",
      "videoDetails.author",
      "videoDetails.shortDescription",
      "videoDetails.thumbnail",
      "videoDetails.lengthSeconds",
      "progressSec",
      "transcriptAvailable",
    ]) {
      assert.match(contentScript, new RegExp(requiredSignal.replace(".", "\\.")));
    }
  });

  it("keeps deterministic DOM/meta fallbacks for SPA pages", () => {
    assert.match(contentScript, /h1\.ytd-watch-metadata yt-formatted-string/);
    assert.match(contentScript, /#channel-name a/);
    assert.match(contentScript, /og:description/);
    assert.match(contentScript, /og:image/);
    assert.match(contentScript, /ytp-subtitles-button/);
  });

  it("remains observation-only and does not write Memory", () => {
    assert.match(contentScript, /Collects temporary page context only\. Never writes to Memory\./);
    assert.match(contentScript, /CONTEXT_OBSERVED/);
    assert.doesNotMatch(contentScript, /\/api\/v1\/capture\/url/);
    assert.doesNotMatch(contentScript, /SAVE_TO_MEMORY/);
  });
});
