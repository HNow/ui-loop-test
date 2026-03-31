"""
Phase 1: UI Grouping Chain

Modules:
    - division.py    — UIDivision: Partition screenshot into 3-10 semantic regions
    - semantic.py    — SemanticExtraction: Label elements within each region
    - grouping.py    — ComponentGrouping: Build hierarchical component tree

All modules accept a DualProviderClient and Config in their constructor.
"""

from phases.phase1_grouping.division import UIDivision
from phases.phase1_grouping.semantic import SemanticExtraction
from phases.phase1_grouping.grouping import ComponentGrouping

__all__ = [
    "UIDivision",
    "SemanticExtraction",
    "ComponentGrouping",
]
