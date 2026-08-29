import assert from "node:assert/strict";
import test from "node:test";

import {
  extractSharedUrl,
  shareDestination,
} from "../../app/static/js/share_target.js";

test("uses explicit Web Share Target URL when present", () => {
  assert.equal(
    extractSharedUrl({
      url: "https://example.com/article?id=7",
      text: "Read this later",
    }),
    "https://example.com/article?id=7",
  );
});

test("extracts an http URL embedded in shared text", () => {
  assert.equal(
    extractSharedUrl({ text: "Useful reference: https://example.com/docs)." }),
    "https://example.com/docs",
  );
});

test("rejects non-http share payloads", () => {
  assert.equal(extractSharedUrl({ url: "javascript:alert(1)" }), "");
  assert.equal(extractSharedUrl({ text: "just some text" }), "");
});

test("routes YouTube shares to video ingest", () => {
  assert.equal(shareDestination("https://youtu.be/abc123"), "youtube");
  assert.equal(
    shareDestination("https://www.youtube.com/watch?v=abc123"),
    "youtube",
  );
  assert.equal(
    shareDestination("https://music.youtube.com/watch?v=abc123"),
    "youtube",
  );
});

test("routes other public web shares to universal capture", () => {
  assert.equal(shareDestination("https://github.com/openai/openai"), "universal");
  assert.equal(shareDestination("https://example.com/article"), "universal");
});
