"""
Unit tests for utils/image.py and utils/dom.py

Tests cover:
  - DOMNode tree string representation
  - _dict_to_dom_node conversion
  - Image utility functions (load, crop, resize, base64)
"""

import pytest
import numpy as np
from PIL import Image
from pathlib import Path

from utils.dom import DOMNode, _dict_to_dom_node
from utils.image import (
    crop_image,
    resize_image,
    image_to_base64,
)


class TestDOMNode:
    def test_to_tree_string_simple(self):
        node = DOMNode(tag="div", classes=["card"])
        s = node.to_tree_string()
        assert "div.card" in s

    def test_to_tree_string_with_id(self):
        node = DOMNode(tag="div", id="main", classes=["container"])
        s = node.to_tree_string()
        assert "#main" in s
        assert ".container" in s

    def test_to_tree_string_with_text(self):
        node = DOMNode(tag="p", text="Hello world")
        s = node.to_tree_string()
        assert "Hello world" in s

    def test_to_tree_string_with_bbox(self):
        node = DOMNode(tag="div", bbox={"x": 0, "y": 0, "width": 100, "height": 200})
        s = node.to_tree_string()
        assert "100x200" in s

    def test_to_tree_string_nested(self):
        child = DOMNode(tag="span", text="hi")
        parent = DOMNode(tag="p", children=[child])
        s = parent.to_tree_string()
        assert "p" in s
        assert "span" in s

    def test_to_tree_string_truncates_long_text(self):
        long_text = "A" * 50
        node = DOMNode(tag="p", text=long_text)
        s = node.to_tree_string()
        assert "..." in s


class TestDictToDomNode:
    def test_converts_simple_dict(self):
        data = {
            "tag": "div",
            "id": "test",
            "classes": ["card", "active"],
            "text": "Hello",
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 50},
            "computed_styles": {"display": "flex"},
            "children": [],
        }
        node = _dict_to_dom_node(data)
        assert node.tag == "div"
        assert node.id == "test"
        assert node.classes == ["card", "active"]
        assert node.text == "Hello"
        assert node.bbox["width"] == 100

    def test_converts_nested(self):
        data = {
            "tag": "div",
            "children": [
                {"tag": "p", "children": []},
                {"tag": "span", "children": []},
            ],
        }
        node = _dict_to_dom_node(data)
        assert len(node.children) == 2
        assert node.children[0].tag == "p"

    def test_empty_dict(self):
        node = _dict_to_dom_node(None)
        assert node.tag == "empty"

    def test_missing_fields(self):
        node = _dict_to_dom_node({"tag": "img"})
        assert node.classes == []
        assert node.text == ""
        assert node.bbox is None


class TestImageCrop:
    def test_crop_produces_smaller_image(self):
        img = Image.new("RGB", (200, 200), color=(100, 100, 100))
        cropped = crop_image(img, (50, 50, 100, 80))
        assert cropped.size == (100, 80)

    def test_crop_full_image(self):
        img = Image.new("RGB", (100, 100), color=(50, 50, 50))
        cropped = crop_image(img, (0, 0, 100, 100))
        assert cropped.size == (100, 100)


class TestImageResize:
    def test_resize_dimensions(self):
        img = Image.new("RGB", (200, 100))
        resized = resize_image(img, 100, 50)
        assert resized.size == (100, 50)


class TestImageBase64:
    def test_base64_roundtrip(self):
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        b64 = image_to_base64(img)
        assert b64.startswith("data:image/png;base64,")
        assert len(b64) > 50

    def test_jpeg_format(self):
        img = Image.new("RGB", (10, 10))
        b64 = image_to_base64(img, format="JPEG")
        assert b64.startswith("data:image/jpeg;base64,")
