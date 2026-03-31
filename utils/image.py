"""
Image processing utilities.
"""

import base64
import io
from pathlib import Path
from typing import Tuple, List
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans


def load_image(path: Path) -> Image.Image:
    """Load image from path."""
    return Image.open(path).convert("RGB")


def save_image(img: Image.Image, path: Path) -> None:
    """Save image to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def image_to_base64(img: Image.Image, format: str = "PNG") -> str:
    """Convert PIL image to base64 data URI."""
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    mime = "image/png" if format == "PNG" else f"image/{format.lower()}"
    return f"data:{mime};base64,{encoded}"


def crop_image(img: Image.Image, bbox: Tuple[int, int, int, int]) -> Image.Image:
    """Crop image to bounding box (x, y, width, height)."""
    x, y, w, h = bbox
    return img.crop((x, y, x + w, y + h))


def resize_image(img: Image.Image, width: int, height: int) -> Image.Image:
    """Resize image to target dimensions."""
    return img.resize((width, height), Image.Resampling.LANCZOS)


def extract_colors(image_path: Path, num_colors: int = 8) -> List[dict]:
    """
    Extract dominant colors using k-means clustering.
    Returns list of {hex, rgb, coverage_pct} dicts, sorted by dominance.
    """
    img = load_image(image_path)
    
    # Resize for speed
    img_small = img.resize((150, 150), Image.Resampling.LANCZOS)
    pixels = np.array(img_small).reshape(-1, 3)
    
    # K-means clustering
    kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=10)
    kmeans.fit(pixels)
    
    # Get colors and their coverage
    colors = kmeans.cluster_centers_.astype(int)
    labels = kmeans.labels_
    
    # Count coverage
    unique, counts = np.unique(labels, return_counts=True)
    total = len(labels)
    
    color_list = []
    for idx, count in zip(unique, counts):
        rgb = tuple(colors[idx])
        hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        coverage = (count / total) * 100
        color_list.append({
            "hex": hex_color,
            "rgb": rgb,
            "coverage_pct": round(coverage, 2)
        })
    
    # Sort by coverage (most dominant first)
    color_list.sort(key=lambda x: x["coverage_pct"], reverse=True)
    return color_list


def compute_ssim(
    img1: Image.Image,
    img2: Image.Image,
    resize_to_match: bool = True
) -> Tuple[float, np.ndarray]:
    """
    Compute SSIM between two images.
    Returns (ssim_score, diff_array).
    """
    from skimage.metrics import structural_similarity as ssim
    
    # Ensure same size
    if resize_to_match and img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
    
    # Convert to numpy arrays
    arr1 = np.array(img1)
    arr2 = np.array(img2)
    
    # Compute SSIM
    score, diff = ssim(arr1, arr2, full=True, channel_axis=-1)
    return score, diff


def create_diff_overlay(
    ref_img: Image.Image,
    gen_img: Image.Image,
    diff_threshold: int = 35
) -> Image.Image:
    """
    Create a diff overlay highlighting mismatched regions.
    Returns PIL Image with magenta highlights over reference.
    """
    # Match sizes
    if ref_img.size != gen_img.size:
        gen_img = gen_img.resize(ref_img.size, Image.Resampling.LANCZOS)
    
    ref_arr = np.array(ref_img)
    gen_arr = np.array(gen_img)
    
    # Compute absolute difference
    diff = np.abs(ref_arr.astype(float) - gen_arr.astype(float))
    
    # Threshold
    mask = np.any(diff > diff_threshold, axis=-1)
    
    # Create overlay (magenta for differences)
    overlay = ref_arr.copy()
    overlay[mask] = [255, 0, 255]  # Magenta
    
    return Image.fromarray(overlay)


def annotate_image(
    img: Image.Image,
    elements: List[Tuple[str, Tuple[int, int, int, int]]],
    color: Tuple[int, int, int] = (255, 0, 0),
    width: int = 2
) -> Image.Image:
    """
    Draw bounding boxes and labels on image for visualization.
    elements: list of (label, (x, y, w, h))
    """
    from PIL import ImageDraw, ImageFont
    
    draw = ImageDraw.Draw(img)
    
    for label, (x, y, w, h) in elements:
        # Draw box
        draw.rectangle([x, y, x + w, y + h], outline=color, width=width)
        
        # Draw label
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Label background
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.rectangle([x, y - text_h - 2, x + text_w + 4, y], fill=color)
        draw.text((x + 2, y - text_h - 2), label, fill=(255, 255, 255), font=font)
    
    return img
