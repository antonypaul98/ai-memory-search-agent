import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const topics = readFileSync("app/static/js/views/topics.js", "utf8");
const api = readFileSync("app/static/js/api.js", "utf8");

test("duplicate knowledge UI requires confirmation before merge", () => {
  assert.match(topics, /Duplicate knowledge/);
  assert.match(topics, /window\.confirm\(/);
  assert.match(topics, /Api\.memoryByExternal\("youtube"/);
  assert.match(topics, /Api\.mergeMemory\(/);
  assert.match(topics, /Keep A · merge B into A/);
  assert.match(topics, /Keep B · merge A into B/);
});

test("merge API helper sends an explicit confirmed request", () => {
  assert.match(api, /mergeMemory:/);
  assert.match(api, /into_memory_id: intoMemoryId/);
  assert.match(api, /confirm: true/);
  assert.match(api, /reason: "duplicate_merge"/);
});
