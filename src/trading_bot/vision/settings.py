"""settings — ``config/vision.yaml`` plus environment overrides.

Deliberately separate from ``trading_bot.config.settings.Settings``: that model is the
runtime's contract for exchanges, database and risk, and adding a vision section there
would mean every existing caller (and every test that builds settings) validating a
field it does not use. This loader reads one file, applies a small set of ``VISION_*``
overrides, and never stores a credential on disk.

Precedence, highest first: environment variable, yaml value, default.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "config" / "vision.yaml"


@dataclass(frozen=True, slots=True)
class PriceConfig:
    input_usd_per_mtok: float = 0.15
    output_usd_per_mtok: float = 0.60
    image_tokens_estimate: int = 1000


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "VISION_API_KEY"
    timeout_s: float = 60.0
    max_attempts: int = 3
    supports_json_object: bool = True
    detail: str = "high"
    prices: PriceConfig = field(default_factory=PriceConfig)


@dataclass(frozen=True, slots=True)
class LaneConfig:
    timeframe: str = "1h"
    window_bars: int = 120
    decision_every_bars: int = 24
    max_calls_per_run: int = 300
    max_estimated_spend_usd: float = 2.0


@dataclass(frozen=True, slots=True)
class VisionConfig:
    provider: ProviderConfig
    lane: LaneConfig

    def api_key(self, env: Mapping[str, str] | None = None) -> str | None:
        """The credential, read at call time so it is never baked into an object."""
        source = os.environ if env is None else env
        value = (source.get(self.provider.api_key_env) or "").strip()
        return value or None

    def as_public_dict(self) -> dict[str, Any]:
        """Everything except the key: what the ledger records about the setup."""
        return {
            "provider": self.provider.provider,
            "base_url": self.provider.base_url,
            "model": self.provider.model,
            "api_key_env": self.provider.api_key_env,
            "supports_json_object": self.provider.supports_json_object,
            "detail": self.provider.detail,
            "timeout_s": self.provider.timeout_s,
            "max_attempts": self.provider.max_attempts,
            "prices": {
                "input_usd_per_mtok": self.provider.prices.input_usd_per_mtok,
                "output_usd_per_mtok": self.provider.prices.output_usd_per_mtok,
                "image_tokens_estimate": self.provider.prices.image_tokens_estimate,
            },
            "lane": {
                "timeframe": self.lane.timeframe,
                "window_bars": self.lane.window_bars,
                "decision_every_bars": self.lane.decision_every_bars,
                "max_calls_per_run": self.lane.max_calls_per_run,
                "max_estimated_spend_usd": self.lane.max_estimated_spend_usd,
            },
        }


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_vision_config(
    path: Path | str | None = None, *, env: Mapping[str, str] | None = None
) -> VisionConfig:
    """Read the yaml file (if present) and apply ``VISION_*`` overrides."""
    source = os.environ if env is None else env
    raw: dict[str, Any] = {}
    target = Path(path) if path is not None else DEFAULT_CONFIG
    if target.exists():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{target} must contain a mapping")
        raw = loaded

    vision = raw.get("vision") or {}
    lane = raw.get("lane") or {}
    prices = vision.get("prices") or {}

    provider = ProviderConfig(
        provider=str(source.get("VISION_PROVIDER") or vision.get("provider") or "openai-compatible"),
        base_url=str(source.get("VISION_BASE_URL") or vision.get("base_url") or "https://api.openai.com/v1"),
        model=str(source.get("VISION_MODEL") or vision.get("model") or "gpt-4o-mini"),
        api_key_env=str(vision.get("api_key_env") or "VISION_API_KEY"),
        timeout_s=float(source.get("VISION_TIMEOUT_S") or vision.get("timeout_s") or 60.0),
        max_attempts=int(vision.get("max_attempts") or 3),
        supports_json_object=_as_bool(vision.get("supports_json_object"), True),
        detail=str(vision.get("detail") or "high"),
        prices=PriceConfig(
            input_usd_per_mtok=float(prices.get("input_usd_per_mtok", 0.15)),
            output_usd_per_mtok=float(prices.get("output_usd_per_mtok", 0.60)),
            image_tokens_estimate=int(prices.get("image_tokens_estimate", 1000)),
        ),
    )
    lane_config = LaneConfig(
        timeframe=str(lane.get("timeframe") or "1h"),
        window_bars=int(lane.get("window_bars") or 120),
        decision_every_bars=int(lane.get("decision_every_bars") or 24),
        max_calls_per_run=int(lane.get("max_calls_per_run") or 300),
        max_estimated_spend_usd=float(lane.get("max_estimated_spend_usd") or 2.0),
    )
    if lane_config.decision_every_bars < 1:
        raise ValueError("lane.decision_every_bars must be >= 1")
    if lane_config.window_bars < 20:
        raise ValueError("lane.window_bars must be >= 20")
    return VisionConfig(provider=provider, lane=lane_config)
