"""
OpenAI-compatible LLM client for OpenRouter and Fireworks.
No SDK dependencies - pure HTTP requests.
"""

import asyncio
import base64
import json
import logging
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Union
import aiohttp

from config import LLMConfig

_log = logging.getLogger("pipeline.llm")

MAX_RETRIES = 3
RETRY_BACKOFF = [10, 30, 60]


@dataclass
class Message:
    role: str  # "system", "user", "assistant", "tool"
    content: Union[str, List[dict]]  # Text or multimodal content blocks

    @classmethod
    def text(cls, role: str, content: str) -> "Message":
        return cls(role=role, content=content)

    @classmethod
    def multimodal(cls, role: str, items: List[dict]) -> "Message":
        return cls(role=role, content=items)


@dataclass
class LLMResponse:
    content: str
    usage: dict
    model: str
    finish_reason: str


class LLMClient:
    """OpenAI-compatible client supporting both text and vision."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP session on context exit."""
        if self.session:
            await self.session.close()
            self.session = None

    def _image_to_base64(self, image_path: Union[str, Path]) -> tuple[str, str]:
        """Convert image to base64 data URI. Returns (data_uri, mime_type)."""
        path = Path(image_path)
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/png"

        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return f"data:{mime_type};base64,{encoded}", mime_type

    def build_vision_content(
        self,
        text: str,
        images: List[Union[str, Path, tuple[str, str]]],  # path or (base64, mime)
    ) -> List[dict]:
        """Build multimodal content block for vision models."""
        content = [{"type": "text", "text": text}]

        for img in images:
            if isinstance(img, (str, Path)):
                data_uri, mime = self._image_to_base64(img)
            else:
                data_uri, mime = img

            content.append({"type": "image_url", "image_url": {"url": data_uri}})

        return content

    async def complete(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Send completion request."""
        if not self.session:
            raise RuntimeError("Client not entered as async context manager")

        # Build request payload
        payload = {
            "model": model or self.config.model,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content
                    if isinstance(msg.content, str)
                    else msg.content,
                }
                for msg in messages
            ],
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        # Provider-specific headers
        if self.config.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/ui-loop-test"
            headers["X-Title"] = "UI Loop Test"

        for attempt in range(MAX_RETRIES):
            try:
                async with self.session.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status == 429:
                        wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                        _log.warning(f"Rate limited (429), retrying in {wait}s...")
                        await asyncio.sleep(wait)
                        continue

                    if resp.status != 200:
                        text = await resp.text()
                        _log.error(f"API error {resp.status}: {text[:500]}")
                        raise RuntimeError(f"API error {resp.status}: {text}")

                    data = await resp.json()
                    break
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    _log.warning(
                        f"Request failed ({type(e).__name__}), retrying in {wait}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    raise RuntimeError(
                        f"API call failed after {MAX_RETRIES} attempts: {e}"
                    ) from e

        if stream:
            pass

        choice = data["choices"][0]
        raw_content = choice["message"]["content"]
        usage = data.get("usage", {})
        _log.debug(
            f"LLM response: model={data.get('model', '?')} "
            f"tokens={usage.get('total_tokens', '?')} "
            f"content_len={len(raw_content)} "
            f"finish={choice.get('finish_reason', '?')}"
        )
        return LLMResponse(
            content=raw_content,
            usage=usage,
            model=data.get("model", payload["model"]),
            finish_reason=choice.get("finish_reason", "unknown"),
        )

    async def vision_complete(
        self,
        prompt: str,
        images: List[Union[str, Path]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """Convenience method for vision tasks."""
        content = self.build_vision_content(prompt, images)
        messages = [Message.multimodal("user", content)]

        return await self.complete(
            messages=messages,
            model=model or self.config.vision_model,
            temperature=temperature,
        )


class DualProviderClient:
    """Manages separate clients for code gen and vision tasks."""

    def __init__(
        self,
        code_config: LLMConfig,
        vision_config: LLMConfig,
        codegen_config: Optional[LLMConfig] = None,
    ):
        self.code_client = LLMClient(code_config)
        self.vision_client = LLMClient(vision_config)
        self.codegen_client: Optional[LLMClient] = (
            LLMClient(codegen_config) if codegen_config else None
        )

    async def __aenter__(self):
        await self.code_client.__aenter__()
        await self.vision_client.__aenter__()
        if self.codegen_client:
            await self.codegen_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close all clients on context exit."""
        await self.code_client.__aexit__(exc_type, exc_val, exc_tb)
        await self.vision_client.__aexit__(exc_type, exc_val, exc_tb)
        if self.codegen_client:
            await self.codegen_client.__aexit__(exc_type, exc_val, exc_tb)

    async def code_complete(self, messages: List[Message], **kwargs) -> LLMResponse:
        """Use code generation model."""
        return await self.code_client.complete(messages, **kwargs)

    async def vision_analyze(
        self, prompt: str, images: List[Union[str, Path]], **kwargs
    ) -> LLMResponse:
        """Use vision model for image analysis."""
        return await self.vision_client.vision_complete(prompt, images, **kwargs)

    async def codegen_from_vision(
        self, prompt: str, images: List[Union[str, Path]], **kwargs
    ) -> LLMResponse:
        """Use VLLM codegen model for full-page HTML generation from screenshot."""
        client = self.codegen_client or self.vision_client
        return await client.vision_complete(prompt, images, **kwargs)
