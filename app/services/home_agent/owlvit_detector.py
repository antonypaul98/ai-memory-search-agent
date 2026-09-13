"""Optional local OWL-ViT adapter. Model assets must already exist on disk."""
from pathlib import Path

from .image_ingest import DetectedObject, normalize_class


class LocalOwlViTDetector:
    def __init__(self, model_path: str, *, labels: list[str], threshold: float = 0.2):
        if not Path(model_path).is_dir():
            raise ValueError("model_path must be an existing local OWL-ViT checkpoint directory")
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")
        self.labels = list(dict.fromkeys(normalize_class(label) for label in labels))
        if not 1 <= len(self.labels) <= 32:
            raise ValueError("provide 1 to 32 object classes")
        from transformers import OwlViTForObjectDetection, OwlViTProcessor
        self.processor = OwlViTProcessor.from_pretrained(model_path, local_files_only=True)
        self.model = OwlViTForObjectDetection.from_pretrained(model_path, local_files_only=True).eval()
        self.threshold = threshold
        self.detector_id = "owlvit:" + Path(model_path).name

    def detect(self, image):
        import torch
        inputs = self.processor(text=[self.labels], images=image, return_tensors="pt")
        with torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_object_detection(
            outputs, threshold=self.threshold, target_sizes=torch.tensor([image.size[::-1]])
        )[0]
        width, height = image.size
        detections = []
        for score, label, box in zip(result["scores"], result["labels"], result["boxes"]):
            coords = tuple(max(0.0, min(1.0, float(v) / scale))
                           for v, scale in zip(box, (width, height, width, height)))
            if coords[0] >= coords[2] or coords[1] >= coords[3]:
                continue
            detections.append(DetectedObject(self.labels[int(label)], float(score), coords))
        # Bound persistence work deterministically. Scores are model scores,
        # not calibrated probabilities of object identity or present location.
        return sorted(detections, key=lambda d: (-d.confidence, d.object_class, d.box))[:100]
