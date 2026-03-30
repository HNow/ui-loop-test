"""
vision_analyze — Qualitative visual analysis via Gemini Flash (OpenRouter).
Use sparingly: iteration 0 bootstrap, plateau-breaking, final QA.
Requires OPENROUTER_API_KEY env var.
"""

import base64
import io
import os
from typing import Union

import requests
from PIL import Image

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-preview"
THINKING_BUDGET = 16000


def _load_as_b64(source: Union[str, bytes]) -> str:
    """Return base64-encoded JPEG (reduced size for API efficiency)."""
    if isinstance(source, bytes):
        img = Image.open(io.BytesIO(source)).convert("RGB")
    else:
        try:
            data = base64.b64decode(source)
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            img = Image.open(source).convert("RGB")

    # Resize to max 1280px wide to save tokens
    max_w = 1280
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def vision_analyze(
    images: list[Union[str, bytes]],
    prompt: str,
) -> dict:
    """
    Send images + prompt to Gemini Flash for qualitative analysis.

    Args:
        images:  List of image paths or base64 strings (max 4)
        prompt:  Analysis question — be specific, include SSIM + iter context

    Returns:
        {"analysis": str}  on success
        {"error": str}     on failure

    Env vars:
        OPENROUTER_API_KEY  — required
    """
    if len(images) > 4:
        return {"error": "Maximum 4 images per call"}

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {"error": "Set OPENROUTER_API_KEY env var"}

    return _call_openrouter(images, prompt, api_key)


def _call_openrouter(images, prompt, api_key):
    content = []
    for img in images:
        b64 = _load_as_b64(img)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            }
        )
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": content}],
        # Always use max thinking budget — images are token-heavy,
        # give the model plenty of reasoning space.
        "reasoning": {"max_tokens": THINKING_BUDGET},
    }

    try:
        resp = requests.post(
            OPENROUTER_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5173",
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return {"analysis": text}
    except Exception as e:
        return {"error": str(e)}
