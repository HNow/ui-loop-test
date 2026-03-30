"""
visual_diff — Pixel diff overlay (magenta = mismatch regions).
Returns the overlay image and what percentage of pixels differ.
SSIM removed — defer all qualitative analysis to vision_analyze.
"""
import base64
import io
from typing import Union

import numpy as np
from PIL import Image


def _load_image(source: Union[str, bytes]) -> Image.Image:
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source)).convert("RGB")
    try:
        data = base64.b64decode(source)
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return Image.open(source).convert("RGB")


def _image_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def visual_diff(
    reference_image: Union[str, bytes],
    generated_image: Union[str, bytes],
    resize_to_match: bool = True,
    diff_threshold: int = 35,
) -> dict:
    """
    Compare reference and generated screenshots.

    Returns:
        {
            "pixel_diff_pct": float,   # % of pixels that differ
            "overlay": base64 PNG,     # reference with mismatched pixels in magenta
        }
    """
    try:
        ref = _load_image(reference_image)
        gen = _load_image(generated_image)

        if resize_to_match and gen.size != ref.size:
            gen = gen.resize(ref.size, Image.LANCZOS)

        ref_arr = np.array(ref, dtype=np.float32)
        gen_arr = np.array(gen, dtype=np.float32)

        diff = np.abs(ref_arr - gen_arr)
        diff_mask = diff.max(axis=-1) > diff_threshold

        pixel_diff_pct = round(float(diff_mask.sum()) / diff_mask.size * 100, 2)

        overlay_arr = ref_arr.copy().astype(np.uint8)
        overlay_arr[diff_mask] = [255, 0, 255]  # magenta

        return {
            "pixel_diff_pct": pixel_diff_pct,
            "overlay": _image_to_b64(Image.fromarray(overlay_arr)),
        }

    except Exception as e:
        return {"error": str(e)}
