"""Home Agent physical-memory primitives.

This package is intentionally isolated from ambient capture. It models
consented observations after a capture adapter has produced them.
"""

from .physical_memory import ObjectSighting, PhysicalMemoryIndex
from .query_service import HomeAgentQueryService, WhereAnswer

__all__ = [
    "HomeAgentQueryService",
    "ObjectSighting",
    "PhysicalMemoryIndex",
    "WhereAnswer",
]
