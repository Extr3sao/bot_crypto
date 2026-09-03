"""RUN-OP-002 — permanent guard for the active-runtime EMA crossover strategy.

Scope (single file):

    src/trading_bot/strategies/ema_crossover.py

Why this file is guarded: it is an ACTIVE_RUNTIME strategy implementation
(reachable through ``TradingPipeline.tick`` and selectable via strategy
config). RUN-OP-002 closed its 14 strict-mypy errors (untyped ``_had_cross``
params plus ``float | list[float] | dict[str, float]`` union leaking into
``len()``/indexing on the ``*_history`` keys) with annotation-only fixes
(``cast(list[Any], ...)``) that preserve the exact runtime fallback of
``.get(key, [])``.

Guard contract:

1. Static ruff guard — the file must stay 100% ruff-clean (no residual
   whitelist: no new debt is accepted on this file).
2. Static mypy guard — the file must stay strict-mypy-clean.
3. Behavior lock — the exact runtime paths the cast touches (crossover
   detection over ``*_history`` lists, ``[0]`` indexing, the ``None``
   no-history/no-crossover outcome) are re-executed and locked so the
   annotation fix can never silently change strategy semantics.

Tooling: if ``ruff``/``mypy`` are unavailable the static checks SKIP (never
PASS), mirroring the environment-gate honesty contract used by the other
cert guard tests.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.strategies.ema_crossover import EmaCrossoverStrategy
from trading_bot.strategies.types import StrategyConfig

REPO = Path(__file__).resolve().parents[3]
TARGET = REPO / "src" / "trading_bot" / "strategies" / "ema_crossover.py"


def _tool(name: str) -> str | None:
    """Locate a tool on PATH, then alongside the running interpreter."""
    found = shutil.which(name)
    if found:
        return found
    exe = Path(sys.executable).with_name(f"{name}.exe" if sys.platform == "win32" else name)
    return str(exe) if exe.is_file() else None


def _cfg(**entry_overrides: object) -> StrategyConfig:
    entry = {
        "rsi_long_threshold": 50.0,
        "rsi_short_threshold": 50.0,
        "require_crossover": True,
    }
    entry.update(entry_overrides)
    return StrategyConfig(
        name="ema_crossover",
        state="paper",
        enabled=True,
        description="guard fixture",
        timeframes=["5m"],
        indicator_names=["ema_fast", "ema_slow", "rsi", "atr"],
        entry_rules=entry,
        exit_rules={
            "stop_loss_atr_multiplier": 1.5,
            "take_profit_atr_multiplier": 2.0,
        },
        filters={},
    )


def _candles(close: float, n: int = 25) -> list[OHLCV]:
    base = 100.0
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1_700_000_000_000 + i * 60_000,
            open=base + i,
            high=base + i + 1,
            low=base + i - 1,
            close=close if i == n - 1 else base + i,
            volume=10.0,
        )
        for i in range(n)
    ]


def _indicators(
    *,
    fast: float,
    slow: float,
    fast_history: list[float],
    slow_history: list[float],
    rsi: float = 60.0,
) -> dict:
    return {
        "ema_fast": fast,
        "ema_slow": slow,
        "rsi": rsi,
        "atr": 2.0,
        "ema_fast_history": fast_history,
        "ema_slow_history": slow_history,
    }


@pytest.mark.skipif(
    _tool("ruff") is None,
    reason="ruff not available in this environment (environment gate, not PASS)",
)
def test_static_ruff_guard() -> None:
    """ema_crossover.py must stay ruff-clean with zero residual whitelist."""
    proc = subprocess.run(
        [_tool("ruff"), "check", "--output-format", "concise", "--no-cache", str(TARGET)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"ruff findings on {TARGET.name}:\n{proc.stdout}"


@pytest.mark.skipif(
    _tool("mypy") is None,
    reason="mypy not available in this environment (environment gate, not PASS)",
)
def test_static_mypy_guard() -> None:
    """ema_crossover.py must stay strict-mypy-clean."""
    proc = subprocess.run(
        [_tool("mypy"), str(TARGET)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"mypy errors on {TARGET.name}:\n{proc.stdout}"


def test_long_crossover_with_history_produces_buy() -> None:
    """History branch (cast-touched): long cross detected over history lists."""
    strat = EmaCrossoverStrategy()
    signal = strat.evaluate(
        _candles(close=101.0),
        _indicators(fast=30.0, slow=20.0, fast_history=[20.0, 30.0], slow_history=[25.0, 20.0]),
        _cfg(),
    )
    assert signal is not None
    assert signal.side == "buy"
    assert signal.strategy_name == "ema_crossover"
    assert "CRUCE ALCISTA" in signal.metadata["explanation"]


def test_short_crossover_with_history_produces_sell() -> None:
    """History branch (cast-touched): short cross detected over history lists."""
    strat = EmaCrossoverStrategy()
    signal = strat.evaluate(
        _candles(close=99.0),
        _indicators(fast=15.0, slow=25.0, fast_history=[20.0, 15.0], slow_history=[18.0, 25.0], rsi=40.0),
        _cfg(),
    )
    assert signal is not None
    assert signal.side == "sell"
    assert "CRUCE BAJISTA" in signal.metadata["explanation"]


def test_require_crossover_with_no_history_returns_none() -> None:
    """No-history outcome stays: crossover required but never observed -> no signal."""
    strat = EmaCrossoverStrategy()
    signal = strat.evaluate(
        _candles(close=101.0),
        _indicators(fast=30.0, slow=20.0, fast_history=[], slow_history=[]),
        _cfg(),
    )
    assert signal is None


def test_require_crossover_absent_falls_back_to_state_only() -> None:
    """Default fallback stays: without require_crossover the state alone signals."""
    strat = EmaCrossoverStrategy()
    signal = strat.evaluate(
        _candles(close=101.0),
        _indicators(fast=30.0, slow=20.0, fast_history=[], slow_history=[]),
        _cfg(require_crossover=False),
    )
    assert signal is not None
    assert signal.side == "buy"


def test_malformed_scalar_history_ignored_safely() -> None:
    """Negative: scalar (non-list) history must not crash and must not signal."""
    strat = EmaCrossoverStrategy()
    indicators = _indicators(fast=30.0, slow=20.0, fast_history=[], slow_history=[])
    indicators["ema_fast_history"] = 5.0  # malformed: scalar instead of list
    indicators["ema_slow_history"] = 3.0
    signal = strat.evaluate(_candles(close=101.0), indicators, _cfg())
    assert signal is None


def test_malformed_dict_history_ignored_safely() -> None:
    """Negative: dict history must not crash and must not produce execution."""
    strat = EmaCrossoverStrategy()
    indicators = _indicators(fast=30.0, slow=20.0, fast_history=[], slow_history=[])
    indicators["ema_fast_history"] = {"latest": 5.0}  # malformed: dict not list
    indicators["ema_slow_history"] = {"latest": 3.0}
    # Crossover is required; malformed history carries no crossover evidence,
    # so the strategy must ignore it and return no signal (never crash).
    signal = strat.evaluate(_candles(close=101.0), indicators, _cfg())
    assert signal is None


def test_malformed_history_state_only_fallback() -> None:
    """Negative: malformed history + no crossover requirement still signals safely."""
    strat = EmaCrossoverStrategy()
    indicators = _indicators(fast=30.0, slow=20.0, fast_history=[], slow_history=[])
    indicators["ema_fast_history"] = 5.0
    indicators["ema_slow_history"] = 3.0
    signal = strat.evaluate(
        _candles(close=101.0),
        indicators,
        _cfg(require_crossover=False),
    )
    assert signal is not None
    assert signal.side == "buy"
