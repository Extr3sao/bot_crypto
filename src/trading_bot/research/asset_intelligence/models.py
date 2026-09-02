"""AssetContext — canonical versioned contract (RFC-AIL-002).

One frozen dataclass produced by every AssetAgent. Everything is
point-in-time: every feature was computed exclusively from bars whose
timestamp <= ``timestamp``. Immutable after creation (frozen=True) so a
context can be replayed exactly.

Optional fields (funding/open_interest/correlation/asset_specific) stay
None until a real data source exists — never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import FEATURE_VERSIONS

__all__ = [
    "ASSET_CONTEXT_SCHEMA_VERSION",
    "AssetContext",
    "AssetContextError",
]

ASSET_CONTEXT_SCHEMA_VERSION = "asset-context-v1"

# Mandatory feature keys: a context build fails closed without them.
MANDATORY_FEATURES = ("returns", "volatility_atr", "trend", "momentum_rsi")

# Maximum age (ms) of the context relative to the newest bar it may see.
# Older contexts are "stale" and rejected by validate_context.
STALE_AFTER_MS = 15 * 60 * 1000


class AssetContextError(RuntimeError):
    """Raised when an AssetContext fails validation (fail closed)."""


@dataclass(frozen=True, slots=True)
class AssetContext:
    """Structured, point-in-time intelligence about one asset."""

    asset: str
    timestamp: int

    # Regime / states (populated from shared features + regime classifier)
    market_regime: str | None = None
    trend_state: str | None = None
    volatility_state: str | None = None
    liquidity_state: str | None = None

    # Feature bags (plain dicts, JSON-serialisable)
    momentum_features: dict[str, Any] = field(default_factory=dict)
    volatility_features: dict[str, Any] = field(default_factory=dict)
    volume_features: dict[str, Any] = field(default_factory=dict)

    # Optional contexts — None until a real source exists (never fabricated)
    funding_context: dict[str, Any] | None = None
    open_interest_context: dict[str, Any] | None = None
    correlation_context: dict[str, Any] | None = None
    asset_specific_features: dict[str, Any] | None = None

    # Data quality / provenance
    data_quality: dict[str, Any] = field(default_factory=dict)
    data_fingerprint: str = ""
    dataset_id: str = ""

    # Versioning (reconstruction contract)
    agent_version: str = ""
    context_schema_version: str = ASSET_CONTEXT_SCHEMA_VERSION
    feature_versions: dict[str, str] = field(default_factory=lambda: dict(FEATURE_VERSIONS))
    regime_method_version: str = ""

    # Provenance of the window used (for replay/audit)
    window_start_ts: int = 0
    window_end_ts: int = 0
    bar_count: int = 0

    # Stable id for observability: asset_context_id (dataset→context→strategy chain)
    @property
    def asset_context_id(self) -> str:
        return f"AC-{self.asset}-{self.timestamp}-{self.data_fingerprint[:12]}"

    def to_dict(self) -> dict[str, Any]:
        """Full serialisation (replay contract: dict → AssetContext)."""
        return {
            "asset": self.asset,
            "timestamp": self.timestamp,
            "market_regime": self.market_regime,
            "trend_state": self.trend_state,
            "volatility_state": self.volatility_state,
            "liquidity_state": self.liquidity_state,
            "momentum_features": self.momentum_features,
            "volatility_features": self.volatility_features,
            "volume_features": self.volume_features,
            "funding_context": self.funding_context,
            "open_interest_context": self.open_interest_context,
            "correlation_context": self.correlation_context,
            "asset_specific_features": self.asset_specific_features,
            "data_quality": self.data_quality,
            "data_fingerprint": self.data_fingerprint,
            "dataset_id": self.dataset_id,
            "agent_version": self.agent_version,
            "context_schema_version": self.context_schema_version,
            "feature_versions": self.feature_versions,
            "regime_method_version": self.regime_method_version,
            "window_start_ts": self.window_start_ts,
            "window_end_ts": self.window_end_ts,
            "bar_count": self.bar_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssetContext:
        """Rebuild a context from ``to_dict`` output (exact replay)."""
        known = {f for f in cls.__dataclass_fields__}
        payload = {k: v for k, v in d.items() if k in known}
        return cls(**payload)

    def validate(self, *, now_ts: int | None = None) -> None:
        """Fail-closed validation (RFC-AIL-002 / negative tests N3-N5).

        Raises :class:`AssetContextError` when the context is unusable:
        - missing identity/versioning fields
        - missing mandatory features (N4)
        - dataset fingerprint absent (N3)
        - stale relative to ``now_ts`` (N5)
        - future leak: window_end_ts > timestamp (point-in-time violation)
        """
        if not self.asset or not self.timestamp:
            raise AssetContextError("asset context missing asset or timestamp")
        if not self.context_schema_version:
            raise AssetContextError("asset context missing schema version")
        if not self.agent_version:
            raise AssetContextError("asset context missing agent version")
        if not self.data_fingerprint:
            raise AssetContextError("asset context missing data fingerprint (N3)")
        for key in MANDATORY_FEATURES:
            if key == "returns" and self.returns_value is None:
                raise AssetContextError(f"asset context missing mandatory feature: {key} (N4)")
            if key == "volatility_atr" and self.volatility_value is None:
                raise AssetContextError(f"asset context missing mandatory feature: {key} (N4)")
            if key == "trend" and not self.trend_value:
                raise AssetContextError(f"asset context missing mandatory feature: {key} (N4)")
            if key == "momentum_rsi" and self.momentum_value is None:
                raise AssetContextError(f"asset context missing mandatory feature: {key} (N4)")
        if self.window_end_ts > self.timestamp:
            raise AssetContextError(
                f"point-in-time violation: window_end_ts {self.window_end_ts} > context ts {self.timestamp}"
            )
        if now_ts is not None and self.timestamp < now_ts - STALE_AFTER_MS:
            raise AssetContextError(
                f"stale asset context: ts {self.timestamp} older than {STALE_AFTER_MS}ms (N5)"
            )

    # ---- typed accessors over the feature bags ---------------------------
    @property
    def returns_value(self) -> float | None:
        v = self.momentum_features.get("returns")
        return float(v) if v is not None else None

    @property
    def volatility_value(self) -> float | None:
        v = self.volatility_features.get("atr_norm")
        return float(v) if v is not None else None

    @property
    def trend_value(self) -> dict[str, float | str] | None:
        v = self.momentum_features.get("trend")
        return v if isinstance(v, dict) else None

    @property
    def momentum_value(self) -> float | None:
        v = self.momentum_features.get("rsi")
        return float(v) if v is not None else None
