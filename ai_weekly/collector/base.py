"""Abstract base class for all collectors."""

import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from ai_weekly.db import Article, Database

logger = logging.getLogger(__name__)

# AI-related keywords for filtering
AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "neural network", "transformer",
    "openai", "anthropic", "gemini", "claude", "mistral", "llama", "copilot",
    "chatgpt", "stable diffusion", "diffusion model", "reinforcement learning",
    "nlp", "computer vision", "robotics", "autonomous", "generative ai",
    "agent", "rag", "fine-tun", "alignment", "AGI",
]


def is_ai_related(title: str, summary: str = "") -> bool:
    """Quick keyword check — if the title or summary mentions AI topics."""
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in AI_KEYWORDS)


def get_proxy(config: Optional[dict] = None) -> Optional[str]:
    """Return proxy URL if configured."""
    if os.environ.get("HTTPS_PROXY"):
        return os.environ["HTTPS_PROXY"]
    if config and config.get("enabled"):
        return config.get("https") or config.get("http")
    return None


class RateLimiter:
    """Simple token-bucket rate limiter."""
    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last_call = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


class BaseCollector(ABC):
    """All collectors extend this."""

    source_name: str = "base"

    def __init__(self, config: dict, proxy_config: Optional[dict] = None):
        self.config = config
        self._client: Optional[httpx.Client] = None
        self._proxy = get_proxy(proxy_config)
        self._limiter = RateLimiter(min_interval=0.5)

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=30,
                proxy=self._proxy,
                headers={"User-Agent": "AI-Weekly-Bot/0.1"},
            )
        return self._client

    @abstractmethod
    def collect(self, db: Database, lookback_days: int) -> list[int]:
        """Collect articles, insert into DB, return list of new article IDs."""
        ...

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
