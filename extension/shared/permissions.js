/**
 * Permission state for the Agent Permission Manager.
 */

export async function getPermissionSnapshot() {
  const bookmarks = await chrome.permissions.contains({ permissions: ["bookmarks"] });
  let notifications = false;
  try {
    notifications = await chrome.permissions.contains({ permissions: ["notifications"] });
  } catch {
    notifications = false;
  }
  return {
    youtube: { label: "YouTube", status: "allowed", detail: "Observe & save videos" },
    web: { label: "Web pages", status: "allowed", detail: "Observe & save pages" },
    bookmarks: {
      label: "Bookmarks",
      status: bookmarks ? "allowed" : "disabled",
      detail: bookmarks
        ? "Import enabled (preview → confirm)"
        : "Disabled — enable via Import bookmarks",
    },
    notifications: {
      label: "Notifications",
      status: notifications ? "allowed" : "disabled",
      detail: notifications ? "Completion alerts on" : "Optional",
    },
    watchLater: {
      label: "Watch Later",
      status: "coming_soon",
      detail: "Needs Google OAuth — use a public playlist URL in Workspace",
    },
    github: {
      label: "GitHub",
      status: "coming_soon",
      detail: "Not connected",
    },
    future: {
      label: "Future connectors",
      status: "coming_soon",
      detail: "Coming soon",
    },
  };
}

export async function requestBookmarksPermission() {
  return chrome.permissions.request({ permissions: ["bookmarks"] });
}

export async function requestNotificationsPermission() {
  return chrome.permissions.request({ permissions: ["notifications"] });
}
