"""U-01 unified command bar acceptance regressions."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_extension_command_bar_routes_search_ask_and_capture_from_one_input() -> None:
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")

    # One form/input feeds the agent command planner for all three accepted intents.
    assert '$("command-form").addEventListener("submit", onCommandSubmit)' in popup
    assert 'const text = $("command-input").value.trim();' in popup
    assert "postAgentCommand(settings" in popup

    # Search and chat remain explicit command intents from the same input.
    assert '`ask ${q}`' in popup
    assert '`search ${q}`' in popup
    assert 'resp.plan?.intent === "search"' in popup or 'intent === "search"' in popup
    assert 'resp.plan?.intent === "ask"' in popup or 'intent === "ask"' in popup

    # Capture/save is also dispatched from that command flow and reuses the existing
    # canonical SAVE_TO_MEMORY path instead of introducing a second write path.
    assert 'resp.plan?.intent === "save"' in popup
    assert "if (activeContext) await onSave();" in popup
    assert 'type: "SAVE_TO_MEMORY"' in popup


def test_unified_command_preserves_confirmation_gate_for_bulk_writes() -> None:
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")

    assert 'resp.status === "confirm_required"' in popup
    assert "lastCommandPlan?.confirm_token" in popup
    assert "requires_confirm" in popup
    assert "executeAgentCommand(settings" in popup
    assert "confirm_token: consumedToken" in popup


def test_unified_command_does_not_auto_open_bulk_handoffs_before_confirmation() -> None:
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")

    assert "Don't auto-open for bulk until confirmed" in popup
    assert 'resp.plan?.intent === "open_workspace"' in popup
