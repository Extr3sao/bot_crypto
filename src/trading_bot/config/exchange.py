"""Exchange configuration. Mirrors config/exchange.yaml."""

from __future__ import annotations

from pydantic import BaseModel, Field

_ACCOUNT_TYPE_RE = r"^(spot|margin)$"
_DEFAULT_TYPE_RE = r"^(spot|margin|future|swap|option)$"
_TIME_IN_FORCE_RE = r"^(GTC|IOC|FOK|GTD)$"


class ExchangeTimeouts(BaseModel):
    """HTTP timeouts for CCXT requests."""

    request_ms: int = Field(15_000, ge=100)
    recv_window_ms: int = Field(5_000, ge=0)


class ExchangeRetries(BaseModel):
    """Retry policy with exponential backoff."""

    max_attempts: int = Field(5, ge=1, le=20)
    initial_backoff_ms: int = Field(500, ge=10)
    max_backoff_ms: int = Field(8_000, ge=100)


class ExchangeEndpoints(BaseModel):
    """Optional explicit endpoint overrides (empty = CCXT default)."""

    api_base: str = ""
    ws_base: str = ""


class Exchange(BaseModel):
    """Single exchange (CCXT-format) configuration block.

    Top-level key in exchange.yaml is `exchange:`. The Settings root binds
    this directly so user code reads `settings.exchange.id` (single level).
    """

    id: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="CCXT exchange id, e.g. binance, kraken, bybit.",
    )
    api_key: str = ""
    api_secret: str = ""
    password: str = ""
    account_type: str = Field("spot", pattern=_ACCOUNT_TYPE_RE)
    sandbox: bool = True
    default_type: str = Field("spot", pattern=_DEFAULT_TYPE_RE)
    rate_limit_ms: int = Field(250, ge=50)
    options: dict[str, object] = Field(default_factory=dict)
    timeouts: ExchangeTimeouts = Field(default_factory=ExchangeTimeouts)
    retries: ExchangeRetries = Field(default_factory=ExchangeRetries)
    time_in_force_default: str = Field("GTC", pattern=_TIME_IN_FORCE_RE)
    post_only_default: bool = True
    endpoints: ExchangeEndpoints = Field(default_factory=ExchangeEndpoints)
