"""Shared pytest fixtures and helpers for scanner unit tests + BDD step_defs.

This conftest re-exports the canonical public API from
``trading_bot.market_data.fake`` (``FakeMarketDataSource``,
``make_flat_ohlcv``, ``assert_called_once_per_symbol``,
``build_demo_settings``) so BDD step_defs that import from
``tests.unit.scanner.conftest`` keep working unchanged. Test-only
extensions (the ``build_settings`` alias + fixtures) live here.

Pine contract (TSK-103.5.1.*):

- ``build_settings``: alias for ``build_demo_settings`` (kept under
  the conftest-local name for backward compat with F4 sentinels in
  ``test_universe_scanner.py`` and BDD step_defs).
- ``settings_paper`` / ``settings_research`` / ``settings_live``:
  pytest fixtures that pre-construct ``Settings`` with sensible
  per-mode defaults.
- ``load_settings_from_assets_yaml``: optional loader over the real
  YAMLs (TSK-099 ``load_settings()``); not used in the GREEN path.

Anti-duplication note:

- ``test_universe_scanner.py`` and ``test_mode_filters.py`` keep
  their own LOCAL ``FakeMarketDataSource`` and ``_build_settings``
  copies (intentional; they are self-contained sentinels). The
  shared helpers here exist so BDD step_defs and the CLI
  ``scan --demo`` path can both use the same canonical source.
- The canonical source of truth for the fake is
  ``trading_bot.market_data.fake``. This conftest is a thin
  re-export layer + test-only extensions.
"""

from __future__ import annotations

import pytest

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.market_data.fake import (
    FakeMarketDataSource,
    assert_called_once_per_symbol,
    build_demo_fetcher,
    build_demo_settings,
    make_flat_ohlcv,
    make_high_volatility_ohlcv,
)
from trading_bot.market_data.types import OHLCV

# NOTE: pytest fixtures (settings_paper, settings_research, settings_live)
# are intentionally NOT in __all__ — fixtures are consumed by name in
# test fn args, not importable via `from conftest import ...`.
__all__ = [
    "OHLCV",
    "FakeMarketDataSource",
    "assert_called_once_per_symbol",
    "build_demo_fetcher",
    "build_demo_settings",
    "build_settings",
    "load_settings_from_assets_yaml",
    "make_flat_ohlcv",
    "make_high_volatility_ohlcv",
]

# ---------------------------------------------------------------------------
# Alias: build_settings is the conftest-local name preserved for backward
# compat. F4 sentinels + BDD step_defs use it; the canonical name in
# trading_bot.market_data.fake is ``build_demo_settings``.
# ---------------------------------------------------------------------------

build_settings = build_demo_settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def settings_paper() -> Settings:
    """Settings coherente para mode=paper. 5 pares USDT activos."""
    return build_settings(
        pairs=[
            ("BTC/USDT", True),
            ("ETH/USDT", True),
            ("SOL/USDT", True),
            ("AVAX/USDT", True),
            ("MATIC/USDT", True),
        ],
        kill_switch_enabled=False,
        min_volume_usdt=5_000_000,
        mode="paper",
    )


@pytest.fixture(scope="function")
def settings_research() -> Settings:
    """Settings coherente para mode=research. 3 pares con thresholds relaxed."""
    return build_settings(
        pairs=[
            ("BTC/USDT", True),
            ("ETH/USDT", True),
            ("BNB/USDT", True),
        ],
        kill_switch_enabled=False,
        min_volume_usdt=1_000_000,
        mode="research",
    )


@pytest.fixture(scope="function")
def settings_live() -> Settings:
    """Settings coherente para mode=live. 1 par con endurecimiento aplicado."""
    return build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        mode="live",
    )


# ---------------------------------------------------------------------------
# Optional YAML loader (TSK-103.5.1.2)
# ---------------------------------------------------------------------------


def load_settings_from_assets_yaml(
    repo_root: str | None = None,
    *,
    mode_override: str | None = None,
) -> Settings:
    """Carga ``Settings`` desde los YAMLs reales.

    Wrapper sobre ``trading_bot.config.settings.load_settings()`` (TSK-099).
    Resuelve ``repo_root`` automaticamente si no se pasa.

    Args:
        repo_root: Directorio raiz del repo. Si ``None``, resuelve
            desde el path de este conftest (``tests/unit/scanner/`` -> ``..``, ``..``, ``..``).
        mode_override: Si se especifica, parchea ``runtime.mode`` post-load.
    """
    from pathlib import Path

    from trading_bot.config.settings import load_settings

    if repo_root is None:
        conftest_path = Path(__file__).resolve()
        resolved = conftest_path.parent.parent.parent.parent
        repo_root = str(resolved)

    settings = load_settings(config_dir=Path(repo_root) / "config", env_file=None)

    if mode_override is not None:
        settings = settings.model_copy(
            update={
                "runtime": settings.runtime.model_copy(update={"mode": TradingMode(mode_override)})
            }
        )
    return settings
