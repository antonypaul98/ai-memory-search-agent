import { Api, clearApiCache } from "../api.js";
import { $, escapeHtml, setStatus } from "../util.js";

let _pollTimer = null;

export function disposeCapture() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

/** Capture / ingest UI — calls existing ingest & capture APIs only. */
export function mountCapture(root) {
  root.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <h2>Capture</h2>
        <span class="panel-caption">YouTube ingest · playlists · URL / bookmarks</span>
      </div>

      <h3>YouTube URLs</h3>
      <label for="url-input">Paste YouTube URLs (one per line)</label>
      <textarea id="url-input" rows="4" placeholder="https://www.youtube.com/watch?v=..."></textarea>
      <details class="reflection-panel">
        <summary>Memory reflection</summary>
        <div class="reflection-grid">
          <label>Why save?
            <select id="save-reason">
              <option value="goal">Goal</option>
              <option value="project">Project</option>
              <option value="reference" selected>Reference</option>
              <option value="future_learning">Future learning</option>
              <option value="entertainment">Entertainment</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label>Goal <input id="save-goal" type="text" placeholder="Current goal" /></label>
          <label class="full">Note <input id="save-note" type="text" placeholder="Why this matters" /></label>
          <label class="checkbox-row"><input id="force-refresh" type="checkbox" /> Force refresh</label>
        </div>
      </details>
      <button id="process-btn" type="button">Process URLs</button>
      <p id="ingest-status" class="status" hidden></p>
      <div id="ingest-results" class="results"></div>
    </section>

    <section class="panel" id="playlist-panel">
      <div class="panel-header">
        <h2>Playlist import</h2>
        <span class="panel-caption">Preview → confirm → background job</span>
      </div>
      <label for="playlist-url">Public playlist URL</label>
      <input id="playlist-url" type="url" placeholder="https://www.youtube.com/playlist?list=..." />
      <details class="reflection-panel">
        <summary>Playlist reflection &amp; options</summary>
        <div class="reflection-grid">
          <label>Why save?
            <select id="pl-save-reason">
              <option value="goal">Goal</option>
              <option value="project">Project</option>
              <option value="reference" selected>Reference</option>
              <option value="future_learning">Future learning</option>
              <option value="entertainment">Entertainment</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label>Goal <input id="pl-save-goal" type="text" placeholder="Course / project goal" /></label>
          <label class="full">Note <input id="pl-save-note" type="text" placeholder="Why import this playlist" /></label>
          <label class="checkbox-row"><input id="pl-force-refresh" type="checkbox" /> Force refresh existing videos</label>
        </div>
      </details>
      <div class="row">
        <button id="playlist-preview-btn" type="button">Preview playlist</button>
      </div>
      <div id="playlist-preview-card" class="progress-card" hidden></div>
      <div class="callout muted" id="watch-later-note" role="note">
        <strong>Watch Later:</strong> Coming soon (needs Google OAuth).
        Use a <em>public playlist URL</em> for demos — Watch Later is not scraped and has no import button.
      </div>
      <div class="row" id="playlist-job-controls" hidden>
        <button id="playlist-pause-btn" type="button">Pause</button>
        <button id="playlist-resume-btn" type="button">Resume</button>
        <button id="playlist-retry-btn" type="button">Retry failed</button>
        <button id="playlist-cancel-btn" type="button" class="ghost">Cancel job</button>
      </div>
      <p id="playlist-status" class="status" hidden aria-live="polite"></p>
      <div id="playlist-progress" class="progress-list" aria-live="polite"></div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>Universal capture</h2>
        <span class="panel-caption">Articles · GitHub · any public URL</span>
      </div>
      <input id="capture-url" type="url" placeholder="https://…" />
      <button id="capture-url-btn" type="button">Capture URL</button>
      <p id="capture-status" class="status" hidden></p>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>Bookmark import</h2>
        <span class="panel-caption">One URL per line (optional title|url) → import APIs</span>
      </div>
      <textarea id="bookmark-lines" rows="4" placeholder="https://example.com/docs&#10;RAG Notes|https://example.com/rag"></textarea>
      <div class="row">
        <button id="bookmark-preview-btn" type="button">Preview</button>
        <button id="bookmark-import-btn" type="button">Import</button>
      </div>
      <p id="bookmark-status" class="status" hidden></p>
      <pre id="bookmark-preview" class="code-block" hidden></pre>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>PDF upload</h2>
        <span class="panel-caption">POST /capture/pdf</span>
      </div>
      <input id="pdf-file" type="file" accept="application/pdf" />
      <button id="pdf-upload-btn" type="button">Upload PDF</button>
      <p id="pdf-status" class="status" hidden></p>
    </section>
  `;

  wireIngest(root);
  wirePlaylist(root);
  wireCaptureUrl(root);
  wireBookmarks(root);
  wirePdf(root);
}

function reflectionPayload(root, prefix = "") {
  if (prefix === "pl-") {
    return {
      save_reason: $("#pl-save-reason", root).value,
      goal: $("#pl-save-goal", root).value.trim(),
      reflection_note: $("#pl-save-note", root).value.trim(),
      recommendations_enabled: true,
      preferred_creator_only: false,
      allow_other_creators: true,
      difficulty: "intermediate",
      preferred_style: "hands_on",
    };
  }
  return {
    save_reason: $("#save-reason", root).value,
    goal: $("#save-goal", root).value.trim(),
    reflection_note: $("#save-note", root).value.trim(),
    recommendations_enabled: true,
    preferred_creator_only: false,
    allow_other_creators: true,
    difficulty: "intermediate",
    preferred_style: "hands_on",
  };
}

function wireIngest(root) {
  $("#process-btn", root).addEventListener("click", async () => {
    const urls = $("#url-input", root)
      .value.split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    const status = $("#ingest-status", root);
    const out = $("#ingest-results", root);
    if (!urls.length) {
      setStatus(status, "Paste at least one URL.", "error");
      return;
    }
    setStatus(status, `Ingesting ${urls.length} URL(s)…`);
    $("#process-btn", root).disabled = true;
    try {
      const data = await Api.ingest({
        urls,
        force_refresh: $("#force-refresh", root).checked,
        reflection: reflectionPayload(root),
      });
      clearApiCache();
      setStatus(status, "Ingest complete.", "success");
      out.innerHTML = (data.results || [])
        .map(
          (item) => `
        <article class="result-card">
          <div class="card-top">
            <span class="badge ${item.success ? "success" : item.skipped ? "neutral" : "error"}">
              ${item.skipped ? "Skipped" : item.success ? "Done" : "Failed"}
            </span>
          </div>
          <h3>${escapeHtml(item.title || item.url)}</h3>
          <p class="muted">${item.success ? `${item.chunk_count || 0} chunks` : escapeHtml(item.error || "")}</p>
        </article>`
        )
        .join("");
    } catch (err) {
      setStatus(status, err.message, "error");
    } finally {
      $("#process-btn", root).disabled = false;
    }
  });
}

function wirePlaylist(root) {
  let jobId = null;
  let pendingPreview = null;
  let importInFlight = false;

  const previewCard = $("#playlist-preview-card", root);
  const jobControls = $("#playlist-job-controls", root);

  function clearPendingPreview() {
    pendingPreview = null;
    previewCard.hidden = true;
    previewCard.innerHTML = "";
  }

  function syncJobControlButtons(job) {
    const st = String(job?.status || "").toLowerCase();
    const terminal = ["completed", "failed", "cancelled"].includes(st);
    const paused = Boolean(job?.paused);
    const pauseBtn = $("#playlist-pause-btn", root);
    const resumeBtn = $("#playlist-resume-btn", root);
    const retryBtn = $("#playlist-retry-btn", root);
    const cancelBtn = $("#playlist-cancel-btn", root);
    if (pauseBtn) pauseBtn.disabled = terminal || paused;
    if (resumeBtn) resumeBtn.disabled = terminal || !paused;
    if (retryBtn) retryBtn.disabled = terminal && st === "cancelled";
    if (cancelBtn) cancelBtn.disabled = terminal;
  }

  function renderPreviewCard(data) {
    const samples = (data.sample_titles || []).filter(Boolean);
    const sampleHtml = samples.length
      ? `<ol class="sample-list">${samples
          .map((t) => `<li>${escapeHtml(t)}</li>`)
          .join("")}</ol>`
      : `<p class="muted">No sample titles available.</p>`;
    previewCard.hidden = false;
    previewCard.innerHTML = `
      <div class="card-top">
        <span class="badge neutral">Preview</span>
        <span class="badge">${data.video_count ?? 0} videos</span>
      </div>
      <h3>${escapeHtml(data.title || "Playlist")}</h3>
      <p class="muted">ID · ${escapeHtml(data.playlist_id || "—")}</p>
      <p class="meta">Sample titles</p>
      ${sampleHtml}
      <div class="row" style="margin-top:0.75rem">
        <button id="playlist-confirm-btn" type="button" class="primary">Confirm import</button>
        <button id="playlist-cancel-preview-btn" type="button" class="ghost">Cancel</button>
      </div>
    `;
    $("#playlist-confirm-btn", previewCard).addEventListener("click", startConfirmedImport);
    $("#playlist-cancel-preview-btn", previewCard).addEventListener("click", () => {
      clearPendingPreview();
      setStatus($("#playlist-status", root), "Preview cancelled.", "success");
    });
  }

  async function startConfirmedImport() {
    if (!pendingPreview || importInFlight) return;
    const url = $("#playlist-url", root).value.trim();
    const status = $("#playlist-status", root);
    const confirmBtn = $("#playlist-confirm-btn", previewCard);
    importInFlight = true;
    if (confirmBtn) confirmBtn.disabled = true;
    setStatus(
      status,
      `Starting import of “${pendingPreview.title}” (${pendingPreview.video_count} videos)…`
    );
    try {
      const job = await Api.playlistIngest({
        playlist_url: url,
        force_refresh: $("#pl-force-refresh", root).checked,
        reflection: reflectionPayload(root, "pl-"),
      });
      jobId = job.job_id || job.id;
      jobControls.hidden = false;
      clearPendingPreview();
      clearApiCache();
      setStatus(status, `Import started · ${job.playlist_title || "Playlist"}`, "success");
      syncJobControlButtons(job);
      pollJob(root, jobId, (j) => {
        jobId = j.job_id || jobId;
        syncJobControlButtons(j);
      });
    } catch (err) {
      setStatus(status, err.message, "error");
      if (confirmBtn) confirmBtn.disabled = false;
    } finally {
      importInFlight = false;
    }
  }

  $("#playlist-preview-btn", root).addEventListener("click", async () => {
    const url = $("#playlist-url", root).value.trim();
    const status = $("#playlist-status", root);
    if (!url) return setStatus(status, "Enter a public playlist URL.", "error");
    disposeCapture();
    clearPendingPreview();
    setStatus(status, "Previewing playlist…");
    $("#playlist-preview-btn", root).disabled = true;
    try {
      const data = await Api.playlistPreview(url, { abortTag: "playlist-preview" });
      pendingPreview = data;
      renderPreviewCard(data);
      setStatus(
        status,
        `Ready to confirm · ${data.title || "Playlist"} · ${data.video_count ?? 0} videos`,
        "success"
      );
    } catch (err) {
      setStatus(status, err.message, "error");
    } finally {
      $("#playlist-preview-btn", root).disabled = false;
    }
  });

  async function withJobAction(btn, fn) {
    if (!jobId) return;
    if (btn) btn.disabled = true;
    try {
      await fn();
    } catch (err) {
      setStatus($("#playlist-status", root), err.message, "error");
    }
  }

  $("#playlist-pause-btn", root).addEventListener("click", async (e) => {
    await withJobAction(e.currentTarget, async () => {
      await Api.jobPause(jobId);
      setStatus($("#playlist-status", root), "Job paused.", "success");
      const job = await Api.job(jobId);
      renderJobProgress(root, job);
      syncJobControlButtons(job);
    });
  });

  $("#playlist-resume-btn", root).addEventListener("click", async (e) => {
    await withJobAction(e.currentTarget, async () => {
      await Api.jobResume(jobId);
      setStatus($("#playlist-status", root), "Job resumed.", "success");
      pollJob(root, jobId, (j) => syncJobControlButtons(j));
    });
  });

  $("#playlist-retry-btn", root).addEventListener("click", async (e) => {
    await withJobAction(e.currentTarget, async () => {
      await Api.jobRetryFailed(jobId);
      setStatus($("#playlist-status", root), "Retrying failed items…", "success");
      pollJob(root, jobId, (j) => syncJobControlButtons(j));
    });
  });

  $("#playlist-cancel-btn", root).addEventListener("click", async (e) => {
    await withJobAction(e.currentTarget, async () => {
      const job = await Api.jobCancel(jobId);
      disposeCapture();
      renderJobProgress(root, job);
      syncJobControlButtons(job);
      clearApiCache();
      setStatus($("#playlist-status", root), "Job cancelled.", "success");
    });
  });
}

function renderJobProgress(root, job) {
  const prog = $("#playlist-progress", root);
  if (!prog) return;
  const total = job.total_videos || 0;
  const done = (job.completed || 0) + (job.skipped || 0);
  const failed = job.failed || 0;
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const running = !["completed", "failed", "cancelled"].includes(
    String(job.status || "").toLowerCase()
  );
  const items = (job.items || []).slice(0, 12);
  const itemRows = items
    .map((it) => {
      const st = String(it.status || "").toLowerCase();
      const badge =
        st === "completed" || st === "skipped"
          ? "success"
          : st === "failed"
            ? "error"
            : st === "processing"
              ? "loading"
              : "neutral";
      return `<li><span class="badge ${badge}">${escapeHtml(it.status || "?")}</span> ${escapeHtml(
        it.title || it.url || it.item_key || ""
      )}${it.error ? ` <span class="muted">— ${escapeHtml(it.error)}</span>` : ""}</li>`;
    })
    .join("");

  prog.innerHTML = `
    <article class="progress-card">
      <div class="card-top">
        <span class="badge ${running ? "loading" : failed && done < total ? "error" : "success"}">
          ${escapeHtml(job.status || "unknown")}${job.paused ? " · paused" : ""}
        </span>
        <span class="meta">${done}/${total} done · ${failed} failed · ${job.queued || 0} queued</span>
      </div>
      <h3>${escapeHtml(job.playlist_title || "Playlist job")}</h3>
      <div
        class="progress-bar"
        role="progressbar"
        aria-valuenow="${pct}"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-label="Playlist import progress"
      >
        <div class="progress-fill ${running && !job.paused ? "animate" : ""}" style="width:${pct}%;transform:none;animation:none"></div>
      </div>
      <p class="muted">${pct}% · job ${escapeHtml(job.job_id || "")}</p>
      ${
        job.error_summary
          ? `<p class="status error" style="display:block">${escapeHtml(job.error_summary)}</p>`
          : ""
      }
      ${itemRows ? `<ul class="sample-list">${itemRows}</ul>` : ""}
    </article>
  `;
}

function pollJob(root, id, onTick) {
  disposeCapture();
  let inFlight = false;
  const tick = async () => {
    if (inFlight) return;
    inFlight = true;
    try {
      const job = await Api.job(id);
      renderJobProgress(root, job);
      if (typeof onTick === "function") onTick(job);
      const controls = $("#playlist-job-controls", root);
      if (controls) controls.hidden = false;
      const st = String(job.status || "").toLowerCase();
      if (["completed", "failed", "cancelled"].includes(st)) {
        disposeCapture();
        clearApiCache();
        const label =
          st === "completed"
            ? `Import complete · ${job.completed || 0} saved, ${job.skipped || 0} skipped, ${job.failed || 0} failed`
            : st === "cancelled"
              ? "Job cancelled."
              : `Job ${st}${job.error_summary ? ` — ${job.error_summary}` : ""}`;
        setStatus(
          $("#playlist-status", root),
          label,
          st === "completed" || st === "cancelled" ? "success" : "error"
        );
      }
    } catch {
      disposeCapture();
    } finally {
      inFlight = false;
    }
  };
  tick();
  _pollTimer = setInterval(tick, 2500);
}

function wireCaptureUrl(root) {
  $("#capture-url-btn", root).addEventListener("click", async () => {
    const url = $("#capture-url", root).value.trim();
    const status = $("#capture-status", root);
    if (!url) return setStatus(status, "Enter a URL.", "error");
    setStatus(status, "Capturing…");
    try {
      const resp = await Api.captureUrl({ url });
      clearApiCache();
      setStatus(status, `Capture ${resp.status || "queued"} · ${resp.capture_id || ""}`, "success");
    } catch (err) {
      setStatus(status, err.message, "error");
    }
  });
}

function parseBookmarkLines(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, idx) => {
      let title = "";
      let url = line;
      const pipe = line.indexOf("|");
      if (pipe > 0) {
        title = line.slice(0, pipe).trim();
        url = line.slice(pipe + 1).trim();
      }
      return {
        browser_bookmark_id: `ws-${idx + 1}-${url.slice(0, 48)}`,
        folder_path: "Workspace",
        url,
        title: title || url,
      };
    });
}

function wireBookmarks(root) {
  $("#bookmark-preview-btn", root).addEventListener("click", async () => {
    const items = parseBookmarkLines($("#bookmark-lines", root).value);
    const status = $("#bookmark-status", root);
    const preview = $("#bookmark-preview", root);
    if (!items.length) return setStatus(status, "Add at least one bookmark URL.", "error");
    try {
      const data = await Api.bookmarkPreview({ source_browser: "chrome", items });
      preview.hidden = false;
      preview.textContent = JSON.stringify(data, null, 2).slice(0, 4000);
      setStatus(status, "Preview ready", "success");
    } catch (err) {
      setStatus(status, err.message, "error");
    }
  });

  $("#bookmark-import-btn", root).addEventListener("click", async () => {
    const items = parseBookmarkLines($("#bookmark-lines", root).value);
    const status = $("#bookmark-status", root);
    if (!items.length) return setStatus(status, "Add at least one bookmark URL.", "error");
    try {
      const data = await Api.bookmarkImport({ source_browser: "chrome", items });
      clearApiCache();
      setStatus(
        status,
        `Import ${data.import_id || "started"} · ${data.status || "queued"}`,
        "success"
      );
    } catch (err) {
      setStatus(status, err.message, "error");
    }
  });
}

function wirePdf(root) {
  $("#pdf-upload-btn", root).addEventListener("click", async () => {
    const file = $("#pdf-file", root).files?.[0];
    const status = $("#pdf-status", root);
    if (!file) return setStatus(status, "Choose a PDF file.", "error");
    if (file.size > 50 * 1024 * 1024) {
      return setStatus(status, "PDF too large (max 50MB).", "error");
    }
    if (file.type && file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      return setStatus(status, "File must be a PDF.", "error");
    }
    setStatus(status, "Uploading…");
    try {
      const data = await Api.capturePdf(file, file.name);
      clearApiCache();
      setStatus(status, `PDF ingested · ${data.title || file.name}`, "success");
    } catch (err) {
      setStatus(status, err.message, "error");
    }
  });
}
