"""
extract_colors — Dominant color palette from an image via k-means clustering.
Run once at iteration 0, inject results into context.
"""
import base64
import io
from typing import Union

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans


def _load_image(source: Union[str, bytes]) -> Image.Image:
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source)).convert("RGB")
    try:
        data = base64.b64decode(source)
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return Image.open(source).convert("RGB")


def extract_colors(image: Union[str, bytes], num_colors: int = 8) -> dict:
    """
    Extract dominant colors from an image using k-means.

    Args:
        image:      File path or base64 string
        num_colors: Number of dominant colors to return

    Returns:
        {
            "colors": [
                {"hex": "#rrggbb", "rgb": [r, g, b], "coverage_pct": float},
                ...
            ]   # ordered most-dominant first
        }
    """
    try:
        img = _load_image(image)

        # Resize for speed — 150x150 is plenty for clustering
        img = img.resize((150, 150), Image.LANCZOS)
        pixels = np.array(img).reshape(-1, 3).astype(np.float32)

        kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init="auto")
        labels = kmeans.fit_predict(pixels)
        centers = kmeans.cluster_centers_.astype(int)

        counts = np.bincount(labels, minlength=num_colors)
        total = counts.sum()

        # Sort by coverage descending
        order = np.argsort(counts)[::-1]

        colors = []
        for idx in order:
            r, g, b = int(centers[idx][0]), int(centers[idx][1]), int(centers[idx][2])
            colors.append({
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "rgb": [r, g, b],
                "coverage_pct": round(float(counts[idx]) / total * 100, 1),
            })

        return {"colors": colors}

    except Exception as e:
        return {"error": str(e)}
