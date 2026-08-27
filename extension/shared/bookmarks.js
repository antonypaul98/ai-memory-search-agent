/** Shared bookmark snapshot helpers for manual and scheduled sync. */

/** Maximum bookmark URLs accepted by the backend request model. */
export const BOOKMARK_SYNC_LIMIT = 500;

/**
 * Flatten a chrome.bookmarks tree into API import items.
 * Pure function so it can be regression-tested without Chrome APIs.
 */
export function flattenBookmarkTree(nodes, path = "", out = []) {
  for (const node of nodes || []) {
    const nextPath = node.title ? (path ? `${path}/${node.title}` : node.title) : path;
    if (node.url && /^https?:\/\//i.test(node.url)) {
      out.push({
        browser_bookmark_id: String(node.id),
        folder_path: path || "Bookmarks",
        url: node.url,
        title: node.title || node.url,
      });
    }
    if (node.children?.length) flattenBookmarkTree(node.children, nextPath, out);
  }
  return out;
}

/**
 * Collect a bounded snapshot and explicitly report whether it is complete.
 * Removal reconciliation is safe only when snapshot_complete is true.
 */
export async function collectBookmarkSnapshot() {
  const tree = await chrome.bookmarks.getTree();
  const all = flattenBookmarkTree(tree);
  return {
    items: all.slice(0, BOOKMARK_SYNC_LIMIT),
    total: all.length,
    snapshot_complete: all.length <= BOOKMARK_SYNC_LIMIT,
  };
}
