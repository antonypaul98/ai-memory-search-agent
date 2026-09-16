"""Home Agent raw-image dependency wiring.

The detector is deliberately local-only: model assets must already exist under the
repository's model directory. No network download is attempted at request time.
"""
from pathlib import Path

from app.config import get_settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest
from app.services.home_agent.image_ingest import HomeImageIngestService
from app.services.home_agent.owlvit_detector import LocalOwlViTDetector

from .dependencies import get_home_agent_capture_registry


_MODEL_PATH = Path("./models/owlvit-base-patch32")
_DEFAULT_LABELS = [
    "keys",
    "wallet",
    "phone",
    "remote control",
    "glasses",
    "backpack",
]


def get_home_agent_authenticated_image_ingest() -> AuthenticatedHomeImageIngest:
    """Build local raw-image ingest; fail closed when model assets are absent."""
    settings = get_settings()
    store = PostgresHomeImageStore(get_postgres_connection_factory(settings))
    detector = LocalOwlViTDetector(str(_MODEL_PATH), labels=_DEFAULT_LABELS)
    image_ingest = HomeImageIngestService(store, detector)
    return AuthenticatedHomeImageIngest(
        registry=get_home_agent_capture_registry(),
        image_ingest=image_ingest,
    )
