"""
Phase 3: Self-Correcting Refinement

Modules:
    - matcher.py    — ComponentMatcher: Match DOM elements back to component tree
    - comparator.py — VisualComparator: Per-component SSIM + vision analysis
    - repair.py     — TargetedRepair: Fix specific components (BeautifulSoup-based)

All modules accept a DualProviderClient and Config in their constructor.
"""

from phases.phase3_refinement.matcher import ComponentMatcher
from phases.phase3_refinement.comparator import VisualComparator
from phases.phase3_refinement.repair import TargetedRepair

__all__ = [
    "ComponentMatcher",
    "VisualComparator",
    "TargetedRepair",
]
