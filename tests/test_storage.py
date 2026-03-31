"""
Unit tests for storage/component.py

Tests cover:
  - Component dataclass construction and serialization round-trip
  - ComponentStore create/save/load/list lifecycle
  - Region, Element, ComponentTree, Iteration construction
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from storage.component import (
    Component,
    ComponentStore,
    ComponentTree,
    DetectedElement,
    Element,
    Iteration,
    Region,
)


class TestRegion:
    def test_construct_defaults(self):
        r = Region(id="r1", name="header", bbox=(0, 0, 100, 50))
        assert r.element_ids == []
        assert r.crop_path is None

    def test_with_all_fields(self):
        r = Region(
            id="r2",
            name="footer",
            bbox=(0, 900, 1200, 100),
            element_ids=["e1", "e2"],
            crop_path=Path("/tmp/crop.png"),
        )
        assert len(r.element_ids) == 2
        assert r.crop_path == Path("/tmp/crop.png")


class TestElement:
    def test_construct_defaults(self):
        e = Element(
            id="e1", type="button", bbox=(10, 20, 80, 30), content_description="Submit"
        )
        assert e.parent_id is None
        assert e.children_ids == []
        assert e.interactable is False

    def test_with_hierarchy(self):
        e = Element(
            id="e2",
            type="container",
            bbox=(0, 0, 200, 200),
            content_description="card",
            parent_id="root",
            children_ids=["c1", "c2"],
            interactable=False,
        )
        assert e.parent_id == "root"
        assert len(e.children_ids) == 2


class TestComponentTree:
    def test_empty_tree(self):
        t = ComponentTree(root_id="r")
        assert t.elements == {}
        assert t.regions == []

    def test_with_elements(self):
        root = Element(
            id="r", type="container", bbox=(0, 0, 100, 100), content_description="root"
        )
        child = Element(
            id="c",
            type="button",
            bbox=(10, 10, 50, 20),
            content_description="btn",
            parent_id="r",
        )
        t = ComponentTree(root_id="r", elements={"r": root, "c": child})
        assert "r" in t.elements
        assert t.elements["c"].parent_id == "r"


class TestIteration:
    def test_construct_minimal(self):
        it = Iteration(number=1, timestamp=1234567890.0, ssim=0.75)
        assert it.treebleu is None
        assert it.notes == ""

    def test_construct_full(self):
        it = Iteration(
            number=2,
            timestamp=1234567891.0,
            ssim=0.88,
            treebleu=0.72,
            container_match=0.91,
            tree_edit_distance=5,
            html_path=Path("/tmp/index.html"),
            screenshot_path=Path("/tmp/iter_2.png"),
            notes="Repaired 3 issues",
        )
        assert it.ssim == 0.88
        assert it.html_path == Path("/tmp/index.html")


class TestComponent:
    def test_to_dict_roundtrip(self, tmp_path):
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"\x89PNG\r\n\x1a\n")
        out = tmp_path / "comp_001"
        out.mkdir()

        comp = Component(
            id="comp_001",
            name="Test Component",
            created_at="2026-01-01T00:00:00",
            reference_path=ref,
            output_dir=out,
            regions=[Region(id="r1", name="hero", bbox=(0, 0, 500, 400))],
        )

        d = comp.to_dict()

        assert isinstance(d["reference_path"], str)
        assert d["regions"][0]["name"] == "hero"

        restored = Component.from_dict(d)
        assert restored.id == comp.id
        assert isinstance(restored.reference_path, Path)
        assert restored.reference_path == ref
        assert len(restored.regions) == 1

    def test_to_dict_with_iterations(self, tmp_path):
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"\x89PNG")
        out = tmp_path / "comp_002"
        out.mkdir()

        comp = Component(
            id="comp_002",
            name="Iter Test",
            created_at="2026-01-01T00:00:00",
            reference_path=ref,
            output_dir=out,
            iterations=[
                Iteration(
                    number=1,
                    timestamp="123456.0",
                    ssim=0.65,
                    html_path=out / "index.html",
                    screenshot_path=out / "iter_1.png",
                )
            ],
        )

        d = comp.to_dict()
        assert isinstance(d["iterations"][0]["html_path"], str)

        restored = Component.from_dict(d)
        assert len(restored.iterations) == 1
        assert isinstance(restored.iterations[0], dict) or hasattr(
            restored.iterations[0], "ssim"
        )
        if isinstance(restored.iterations[0], dict):
            assert restored.iterations[0]["ssim"] == 0.65
        else:
            assert restored.iterations[0].ssim == 0.65


class TestComponentStore:
    def test_create_and_load(self, tmp_path):
        store = ComponentStore(tmp_path / "store")

        ref = tmp_path / "reference.png"
        ref.write_bytes(b"\x89PNG\r\n\x1a\n")

        comp = store.create("My Test", ref)

        assert comp.id.startswith("my_test_")
        assert (comp.output_dir / "reference.png").exists()
        assert (comp.output_dir / "component.json").exists()

        loaded = store.load(comp.id)
        assert loaded is not None
        assert loaded.id == comp.id
        assert loaded.name == "My Test"

    def test_load_nonexistent(self, tmp_path):
        store = ComponentStore(tmp_path / "store")
        assert store.load("no_such_id") is None

    def test_list_components(self, tmp_path):
        store = ComponentStore(tmp_path / "store")

        ref = tmp_path / "reference.png"
        ref.write_bytes(b"\x89PNG\r\n\x1a\n")

        c1 = store.create("Alpha", ref)
        c2 = store.create("Beta", ref)

        all_comps = store.list()
        ids = {c.id for c in all_comps}
        assert c1.id in ids
        assert c2.id in ids

    def test_save_preserves_state(self, tmp_path):
        store = ComponentStore(tmp_path / "store")

        ref = tmp_path / "reference.png"
        ref.write_bytes(b"\x89PNG\r\n\x1a\n")

        comp = store.create("Save Test", ref)
        comp.scratchpad = "some notes here"
        store.save(comp)

        loaded = store.load(comp.id)
        assert loaded.scratchpad == "some notes here"
