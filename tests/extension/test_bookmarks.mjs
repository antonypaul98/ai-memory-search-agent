import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BOOKMARK_SYNC_LIMIT,
  flattenBookmarkTree,
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
