"""Opt-in smoke test for the real local-only Home Agent OWL-ViT adapter.

This test is intentionally skipped in ordinary CI because the repository does not
ship the model checkpoint. To run it, point HOME_AGENT_OWLVIT_MODEL_PATH at an
already-present local OWL-ViT checkpoint. No runtime model download is allowed.
"""
import os
from pathlib import Path

import pytest
from PIL import Image

from app.services.home_agent.owlvit_detector import LocalOwlViTDetector


MODEL_ENV = "HOME_AGENT_OWLVIT_MODEL_PATH"


def _local_model_path() -> Path:
    raw = os.environ.get(MODEL_ENV)
    if not raw:
        pytest.skip(f"set {MODEL_ENV} to an existing local OWL-ViT checkpoint")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        pytest.fail(f"{MODEL_ENV} must point to an existing directory: {path}")
    return path


@pytest.mark.slow
def test_real_owlvit_checkpoint_runs_offline(monkeypatch):
    """Load and execute a real checkpoint while forcing Hugging Face offline."""
    model_path = _local_model_path()

    # Defense in depth around LocalOwlViTDetector(local_files_only=True): if a
    # dependency regresses toward network lookup, Hugging Face must fail closed.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    detector = LocalOwlViTDetector(
        str(model_path),
        labels=["keys", "wallet", "phone"],
        threshold=0.99,
    )
    image = Image.new("RGB", (64, 64), "white")
    detections = detector.detect(image)

    assert detector.detector_id.startswith("owlvit:sha256:")
    assert len(detector.detector_id) == len("owlvit:sha256:") + 64
    assert isinstance(detections, list)
    assert len(detections) <= 100
    for detection in detections:
        assert detection.object_class in {"keys", "wallet", "phone"}
        assert 0.0 <= detection.confidence <= 1.0
        x1, y1, x2, y2 = detection.box
        assert 0.0 <= x1 < x2 <= 1.0
        assert 0.0 <= y1 < y2 <= 1.0
