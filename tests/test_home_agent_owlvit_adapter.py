from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image
import torch

from app.services.home_agent.owlvit_detector import LocalOwlViTDetector


def test_adapter_uses_image_processor_and_preserves_class_score_box():
    model = MagicMock(return_value="model-output")
    postprocess = MagicMock(return_value=[{
        "scores": torch.tensor([.91]), "labels": torch.tensor([0]),
        "boxes": torch.tensor([[10, 5, 90, 45]]),
    }])

    class Processor:
        image_processor = SimpleNamespace(post_process_object_detection=postprocess)
        def __call__(self, **kwargs):
            assert kwargs["text"] == [["keys"]]
            return {"pixel_values": "pixels"}

    detector = LocalOwlViTDetector.__new__(LocalOwlViTDetector)
    detector.processor, detector.model = Processor(), model
    detector.labels, detector.threshold = ["keys"], .2
    result = detector.detect(Image.new("RGB", (100, 50)))
    assert len(result) == 1
    assert result[0].object_class == "keys"
    assert abs(result[0].confidence - .91) < .00001
    assert result[0].box == (.1, .1, .9, .9)
    assert postprocess.call_args.kwargs["target_sizes"].tolist() == [[50, 100]]
