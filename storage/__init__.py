"""
Storage module for component state persistence.

Exports:
    - ComponentStore: Manages component directories and JSON state files
    - Component: Full component state across all phases
    - Region, Element, ComponentTree: Phase 1 data structures
    - Iteration: Phase 3 iteration record
"""

from storage.component import (
    ComponentStore,
    Component,
    Region,
    Element,
    ComponentTree,
    Iteration,
)

__all__ = [
    "ComponentStore",
    "Component",
    "Region",
    "Element",
    "ComponentTree",
    "Iteration",
]
