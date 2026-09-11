"""Home Agent physical-memory primitives.

This package is intentionally isolated from ambient capture. It models
consented observations after a capture adapter has produced them.
"""

from .physical_memory import ObjectSighting, PhysicalMemoryIndex

__all__ = ["ObjectSighting", "PhysicalMemoryIndex"]
