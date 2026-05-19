"""Config loader — reads config.yaml, merges with env vars."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class SourceConfig:
    enabled: bool
    config: dict[str, Any]


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_base: str
    max_tokens: int
    temperature: float


@dataclass
class ImageConfig:
    provider: str
    tongyi_model: str
    tongyi_size: str
    local_sd_url: str
    local_sd_model: str


@dataclass
class Config:
    sources: dict[str, SourceConfig]
    scoring: dict[str, Any]
    llm: LLMConfig
    images: ImageConfig
    schedule: dict[str, Any]
    proxy: dict[str, Any]
    _raw: dict[str, Any] = field(repr=False)


def load_config(path: Optional[str] = None) -> Config:
    """Load config from yaml, resolve from closest ancestor directory."""
    if path is None:
        path = _find_config_file()
    else:
        path = str(Path(path).resolve())

    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    sources = {}
    for name, cfg in raw.get("sources", {}).items():
        sources[name] = SourceConfig(
            enabled=cfg.get("enabled", True),
            config={k: v for k, v in cfg.items() if k != "enabled"},
        )

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        provider=llm_raw.get("provider", "deepseek"),
        model=llm_raw.get("model", "deepseek-chat"),
        api_base=llm_raw.get("api_base", "https://api.deepseek.com"),
        max_tokens=llm_raw.get("max_tokens", 4096),
        temperature=llm_raw.get("temperature", 0.7),
    )

    img_raw = raw.get("images", {})
    images = ImageConfig(
        provider=img_raw.get("provider", "tongyi"),
        tongyi_model=img_raw.get("tongyi_model", "wan2.1-t2i-turbo"),
        tongyi_size=img_raw.get("tongyi_size", "1024*1024"),
        local_sd_url=img_raw.get("local_sd_url", "http://127.0.0.1:7860"),
        local_sd_model=img_raw.get("local_sd_model", "sd_xl_base_1.0"),
    )

    return Config(
        sources=sources,
        scoring=raw.get("scoring", {}),
        llm=llm,
        images=images,
        schedule=raw.get("schedule", {"lookback_days": 7}),
        proxy=raw.get("proxy", {"enabled": False}),
        _raw=raw,
    )


def _find_config_file() -> str:
    """Walk up from CWD to find config.yaml."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "config.yaml"
        if candidate.exists():
            return str(candidate)
    # Fallback: same directory as this file
    return str(Path(__file__).resolve().parent.parent / "config.yaml")
