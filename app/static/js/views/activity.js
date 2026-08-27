import { Api } from "../api.js";
import { $, emptyState, escapeHtml, formatWhen, skeleton, boundList } from "../util.js";

const MAX_EVENTS = 120;
const SAFE_PAYLOAD_KEYS = ["tool", "policy_tier", "error_type", "status", "reason"];

export function mountActivity(root) {
  root.innerHTML = `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Agent activity</h2>
          <span class="panel-caption">Read-only audit trail of agent runs and tool actions</span>
        </div>
        <button id="activity-refresh" type="button" class="button secondary">Refresh</button>
      </div>
      <div class="filters">
        <label class="sr-only" for="activity-type">Event type</label>
        <select id="activity-type" aria-label="Agent event type">
          <option value="">All agent events</option>
          <option value="agent.run.started">Run started</option>
          <option value="agent.run.awaiting_approval">Awaiting approval</option>
          <option value="agent.run.approved">Approved</option>
          <option value="agent.run.completed">Run completed</option>
          <option value="agent.run.failed">Run failed</option>
          <option value="agent.tool.started">Tool started</option>
        </select>
      </div>
      <div id="activity-summary" class="muted" aria-live="polite"></div>
      <div id="activity-body" aria-live="polite">${skeleton(4)}</div>
    </section>
  `;

  const reload = () => loadActivity(root);
  $("#activity-refresh", root).addEventListener("click", reload);
  $("#activity-type", root).addEventListener("change", reload);
  loadActivity(root);
}

async function loadActivity(root) {
  const body = $("#activity-body", root);
  const summary = $("#activity-summary", root);
  body.innerHTML = skeleton(3);
  summary.textContent = "";

  try {
    const eventType = $("#activity-type", root).value;
    const data = await Api.events(eventType, MAX_EVENTS, {
      abortTag: "activity",
      cache: false,
    });
    let events = Array.isArray(data?.events) ? data.events : [];
    if (!eventType) {
      events = events.filter((event) => String(event.event_type || "").startsWith("agent."));
    }
    events = boundList(events.slice().reverse(), MAX_EVENTS);

    if (!events.length) {
      body.innerHTML = emptyState("No agent activity yet", "Agent runs will appear here after they execute.");
      return;
    }

    const completed = events.filter((e) => e.event_type === "agent.run.completed").length;
    const failed = events.filter((e) => e.event_type === "agent.run.failed").length;
    const awaiting = events.filter((e) => e.event_type === "agent.run.awaiting_approval").length;
    summary.textContent = `${events.length} events · ${completed} completed · ${failed} failed · ${awaiting} awaiting approval`;
    body.innerHTML = `<div class="list">${events.map(eventRow).join("")}</div>`;
  } catch (err) {
    body.innerHTML = emptyState("Agent activity failed", err.message);
  }
}

function eventRow(event) {
  const type = String(event.event_type || "agent.event");
  const actor = String(event.actor || "system");
  const aggregate = String(event.aggregate_id || "");
  const safePayload = SAFE_PAYLOAD_KEYS
    .filter((key) => event.payload && event.payload[key] != null && event.payload[key] !== "")
    .map((key) => `${key}: ${String(event.payload[key])}`)
    .join(" · ");
  const meta = [actor, formatWhen(event.created_at), aggregate ? `run ${aggregate.slice(0, 8)}` : "", safePayload]
    .filter(Boolean)
    .join(" · ");

  return `<div class="list-row" data-event-id="${escapeHtml(event.event_id || "")}">
    <span class="src" aria-hidden="true">${eventGlyph(type)}</span>
    <span class="list-main">
      <strong>${escapeHtml(readableType(type))}</strong>
      <small>${escapeHtml(meta)}</small>
    </span>
  </div>`;
}

function readableType(type) {
  return type
    .replace(/^agent\./, "")
    .split(".")
    .map((part) => part.replace(/_/g, " "))
    .join(" · ");
}

function eventGlyph(type) {
  if (type.endsWith("failed")) return "!";
  if (type.endsWith("awaiting_approval")) return "?";
  if (type.endsWith("completed")) return "✓";
  if (type.includes("tool")) return "↳";
  return "•";
}
