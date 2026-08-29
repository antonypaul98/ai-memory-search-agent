import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BOOKMARK_SYNC_LIMIT,
  buildBookmarkSyncPlan,
  collectBookmarkSnapshot,
  flattenBookmarkTree,
  normalizeBookmarkSyncHours,
} from "../../extension/shared/bookmarks.js";

test("flattenBookmarkTree preserves IDs, folders, titles and http URLs", () => {
  const tree = [
    {
      id: "root",
      title: "Bookmarks Bar",
      children: [
        {
          id: "folder",
          title: "Research",
          children: [
            { id: "1", title: "RAG", url: "https://example.com/rag" },
            { id: "2", title: "Local", url: "chrome://settings" },
          ],
        },
      ],
    },
  ];

  assert.deepEqual(flattenBookmarkTree(tree), [
    {
      browser_bookmark_id: "1",
      folder_path: "Bookmarks Bar/Research",
      url: "https://example.com/rag",
      title: "RAG",
    },
  ]);
});

test("bookmark sync request limit remains aligned with backend", () => {
  assert.equal(BOOKMARK_SYNC_LIMIT, 500);
});

test("scheduled bookmark sync stays off without explicit opt-in or permission", () => {
  assert.deepEqual(buildBookmarkSyncPlan({ bookmarkSyncEnabled: false }, true), {
    enabled: false,
    periodInMinutes: null,
  });
  assert.deepEqual(buildBookmarkSyncPlan({ bookmarkSyncEnabled: true }, false), {
    enabled: false,
    periodInMinutes: null,
  });
});

test("scheduled bookmark sync cadence is normalized to the supported range", () => {
  assert.equal(normalizeBookmarkSyncHours("bad"), 24);
  assert.equal(normalizeBookmarkSyncHours(0), 1);
  assert.equal(normalizeBookmarkSyncHours(500), 168);
  assert.deepEqual(
    buildBookmarkSyncPlan(
      { bookmarkSyncEnabled: true, bookmarkSyncHours: 12 },
      true
    ),
    { enabled: true, periodInMinutes: 720 }
  );
});

test("bookmark snapshots are bounded and mark truncation as incomplete", async () => {
  const children = Array.from({ length: BOOKMARK_SYNC_LIMIT + 1 }, (_, index) => ({
    id: String(index + 1),
    title: `Bookmark ${index + 1}`,
    url: `https://example.com/${index + 1}`,
  }));
  const previousChrome = globalThis.chrome;
  globalThis.chrome = {
    bookmarks: {
      async getTree() {
        return [{ id: "root", title: "Bookmarks", children }];
      },
    },
  };
  try {
    const snapshot = await collectBookmarkSnapshot();
    assert.equal(snapshot.items.length, BOOKMARK_SYNC_LIMIT);
    assert.equal(snapshot.total, BOOKMARK_SYNC_LIMIT + 1);
    assert.equal(snapshot.snapshot_complete, false);
  } finally {
    globalThis.chrome = previousChrome;
  }
});
