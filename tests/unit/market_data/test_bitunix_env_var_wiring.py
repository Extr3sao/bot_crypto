"""Regression tests for TSK-178: env-var fallback in Bitunix client constructors.

Pre-refactor history: ``BitunixSpotClient()`` and ``BitunixFuturesClient()``
yielded ``api_key == ""`` and ``api_secret == ""`` when constructed with no
kwarg, regardless of the surrounding environment. Post-refactor (TSK-178),
the constructors read ``BITUNIX_API_KEY`` / ``BITUNIX_API_SECRET`` from the
environment when the kwarg is empty.

Contract verified here:
  1. Explicit kwarg wins over env-var (back-compat preserved).
  2. Empty kwarg + env-var set -> env-var value is used.
  3. Empty kwarg + env-var unset -> empty string (legacy default preserved).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _scrub_bitunix_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Always start each test with both Bitunix env-vars removed.

    Without this, a developer's accidental ``setenv BITUNIX_API_KEY=...``
    would silently leak into unrelated tests.
    """
    monkeypatch.delenv("BITUNIX_API_KEY", raising=False)
    monkeypatch.delenv("BITUNIX_API_SECRET", raising=False)


def test_spot_explicit_kwarg_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-refactor contract: kwarg wins. Post-refactor contract unchanged."""
    monkeypatch.setenv("BITUNIX_API_KEY", "env-leaks-in-if-bug")
    monkeypatch.setenv("BITUNIX_API_SECRET", "env-secret-leaks-in-if-bug")
    from trading_bot.market_data.bitunix import BitunixSpotClient

    c = BitunixSpotClient(api_key="explicit-key", api_secret="explicit-secret")
    assert c.api_key == "explicit-key"
    assert c.api_secret == "explicit-secret"


def test_spot_env_var_picked_up_when_kwarg_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """New contract: empty kwarg falls back to env-var."""
    monkeypatch.setenv("BITUNIX_API_KEY", "from-env")
    monkeypatch.setenv("BITUNIX_API_SECRET", "from-env-secret")
    from trading_bot.market_data.bitunix import BitunixSpotClient

    c = BitunixSpotClient()
    assert c.api_key == "from-env"
    assert c.api_secret == "from-env-secret"


def test_spot_default_empty_when_neither_set() -> None:
    """Legacy default preserved when neither kwarg nor env-var set."""
    from trading_bot.market_data.bitunix import BitunixSpotClient

    c = BitunixSpotClient()
    assert c.api_key == ""
    assert c.api_secret == ""


def test_futures_explicit_kwarg_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same precedence for futures client."""
    monkeypatch.setenv("BITUNIX_API_KEY", "env-leaks-in-if-bug")
    monkeypatch.setenv("BITUNIX_API_SECRET", "env-secret-leaks-in-if-bug")
    from trading_bot.market_data.bitunix_futures import BitunixFuturesClient

    fc = BitunixFuturesClient(api_key="explicit-key", api_secret="explicit-secret")
    assert fc.api_key == "explicit-key"
    assert fc.api_secret == "explicit-secret"


def test_futures_env_var_picked_up_when_kwarg_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BITUNIX_API_KEY", "futures-from-env")
    monkeypatch.setenv("BITUNIX_API_SECRET", "futures-secret-from-env")
    from trading_bot.market_data.bitunix_futures import BitunixFuturesClient

    fc = BitunixFuturesClient()
    assert fc.api_key == "futures-from-env"
    assert fc.api_secret == "futures-secret-from-env"


def test_futures_default_empty_when_neither_set() -> None:
    from trading_bot.market_data.bitunix_futures import BitunixFuturesClient

    fc = BitunixFuturesClient()
    assert fc.api_key == ""
    assert fc.api_secret == ""
