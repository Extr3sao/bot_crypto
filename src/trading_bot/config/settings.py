"""Application settings.

In the recovery runbook this module is imported in two contexts:
- runtime (real or paper trading), where it uses the real config classes,
- offline verification, where it may be imported without the broader runtime
  stack. The module exposes both the canonical surface and a compat getter
  used by offline tooling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .types import FLAT_ENV_ALIASES, Settings, load_settings, ROUNDTRIP_COST_BPS, STRATEGY_ADMISSION_CONFIG, STRATEGY_ADMISSION_CONFIG_PATH

__all__ = ["Settings", "get_settings", "_COMPAT_DEFAULT_SETTINGS"]


def get_settings() -> Settings:
    return Settings()


_COMPAT_DEFAULT_SETTINGS: Dict[str, Any] = {
    "exchange_api_key": "",
    "exchange_secret": "",
    "exchange_sandbox": False,
}
