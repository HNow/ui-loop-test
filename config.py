"""
Configuration management for UI Cloning Agent.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Load .env file if it exists
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is optional


@dataclass
class LLMConfig:
    """Configuration for a single LLM provider."""

    provider: str  # "openrouter" or "fireworks"
    api_key: str
    base_url: str
    model: str
    vision_model: Optional[str] = None  # Different model for vision tasks
    max_tokens: int = 4096
    temperature: float = 0.7

    @property
    def effective_vision_model(self) -> str:
        return self.vision_model or self.model


@dataclass
class Config:
    """Global application configuration."""

    # Providers
    provider: str = "openrouter"
    vision_provider: Optional[str] = "openrouter"

    # Paths
    output_dir: Path = field(default_factory=lambda: Path("./output"))

    # Loop settings
    max_iterations: int = 32
    ssim_threshold: float = 0.88
    plateau_patience: int = 2
    plateau_delta: float = 0.005

    # Phase 1: Grouping
    target_regions_min: int = 3
    target_regions_max: int = 10
    max_elements_per_region: int = 40  # For division correction

    # Phase 2: Codegen — plain CSS only (no Tailwind)
    use_tailwind: bool = False

    # Phase 3: Refinement
    per_component_threshold: float = 0.90  # SSIM threshold for per-component match

    # Server settings
    serve_port: int = 8765
    serve_host: str = "127.0.0.1"

    def __post_init__(self):
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_llm_config(self, for_vision: bool = False) -> LLMConfig:
        """Get LLM config for the active provider."""
        provider = self.vision_provider if for_vision else self.provider

        if provider == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "OPENROUTER_API_KEY not set. "
                    "Create a .env file with OPENROUTER_API_KEY=your_key "
                    "or set the environment variable."
                )
            return LLMConfig(
                provider="openrouter",
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                model="google/gemini-3-flash-preview",  # Better spatial reasoning
                vision_model="google/gemini-3-flash-preview",
                max_tokens=8192,
                temperature=0.3,  # Lower for consistent structure
            )
        elif provider == "fireworks":
            api_key = os.getenv("FIREWORKS_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "FIREWORKS_API_KEY not set. "
                    "Create a .env file with FIREWORKS_API_KEY=your_key "
                    "or set the environment variable."
                )
            return LLMConfig(
                provider="fireworks",
                api_key=api_key,
                base_url="https://api.fireworks.ai/inference/v1",
                model="accounts/fireworks/models/llama-v3p2-11b-vision-instruct",
                vision_model="accounts/fireworks/models/llama-v3p2-11b-vision-instruct",
                max_tokens=4096,
                temperature=0.7,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")
