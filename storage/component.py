"""
Component storage and state management.
"""

import json
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Region:
    """A semantic region from Phase 1.1 UI Division."""

    id: str
    name: str
    bbox: tuple[int, int, int, int]  # x, y, width, height
    element_ids: List[str] = field(default_factory=list)
    crop_path: Optional[Path] = None


@dataclass
class Element:
    """An element from Phase 1.2 Semantic Extraction."""

    id: str
    type: str  # container, text, heading, button, image, icon, input, etc.
    bbox: tuple[int, int, int, int]
    content_description: str
    interactable: bool = False
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)


@dataclass
class ComponentTree:
    """Hierarchical component tree from Phase 1.3."""

    root_id: str
    elements: Dict[str, Element] = field(default_factory=dict)
    regions: List[Region] = field(default_factory=list)


@dataclass
class Iteration:
    """A single refinement iteration."""

    number: int
    timestamp: str
    ssim: float
    treebleu: Optional[float] = None
    container_match: Optional[float] = None
    tree_edit_distance: Optional[int] = None
    html_path: Optional[Path] = None
    screenshot_path: Optional[Path] = None
    diff_path: Optional[Path] = None
    notes: str = ""


@dataclass
class DetectedElement:
    """Pre-step element detection from Phase 1.0 (before region division)."""

    id: str
    type: str
    bbox: tuple[int, int, int, int]
    text: str = ""
    confidence: float = 1.0


@dataclass
class Component:
    """Full component state across all phases."""

    id: str
    name: str
    created_at: str
    reference_path: Path
    output_dir: Path

    # Phase 0: Element detection (pre-step)
    detected_elements: List[DetectedElement] = field(default_factory=list)

    # Phase 1 outputs
    regions: List[Region] = field(default_factory=list)
    tree: Optional[ComponentTree] = None

    # Phase 2 outputs
    html_path: Optional[Path] = None

    # Phase 3 outputs
    iterations: List[Iteration] = field(default_factory=list)
    final_ssim: Optional[float] = None
    final_treebleu: Optional[float] = None
    final_container_match: Optional[float] = None

    # Scratchpad
    scratchpad: str = ""

    @staticmethod
    def _convert_paths(obj):
        if isinstance(obj, dict):
            return {k: Component._convert_paths(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [Component._convert_paths(item) for item in obj]
        elif isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, tuple):
            return list(obj)
        return obj

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        d = asdict(self)
        return Component._convert_paths(d)

    @classmethod
    def from_dict(cls, data: dict) -> "Component":
        """Deserialize from dict."""
        # Convert string paths back to Path objects
        for key in ["reference_path", "output_dir", "html_path"]:
            if data.get(key):
                data[key] = Path(data[key])
        for region in data.get("regions", []):
            if region.get("crop_path"):
                region["crop_path"] = Path(region["crop_path"])
        for it in data.get("iterations", []):
            for key in ["html_path", "screenshot_path", "diff_path"]:
                if it.get(key):
                    it[key] = Path(it[key])
        return cls(**data)


class ComponentStore:
    """Manages component storage on disk."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, reference_path: Path) -> Component:
        """Create a new component with initialized directories."""
        comp_id = f"{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
        output_dir = self.base_dir / comp_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy reference image
        ref_dest = output_dir / "reference.png"
        shutil.copy(reference_path, ref_dest)

        component = Component(
            id=comp_id,
            name=name,
            created_at=datetime.now().isoformat(),
            reference_path=ref_dest,
            output_dir=output_dir,
        )

        self.save(component)
        return component

    def save(self, component: Component):
        """Save component state to disk."""
        meta_path = component.output_dir / "component.json"
        meta_path.write_text(
            json.dumps(component.to_dict(), indent=2), encoding="utf-8"
        )

    def load(self, comp_id: str) -> Optional[Component]:
        """Load component from disk."""
        meta_path = self.base_dir / comp_id / "component.json"
        if not meta_path.exists():
            return None

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return Component.from_dict(data)

    def list(self) -> List[Component]:
        """List all components."""
        components = []
        for subdir in self.base_dir.iterdir():
            if subdir.is_dir():
                comp = self.load(subdir.name)
                if comp:
                    components.append(comp)
        return components
