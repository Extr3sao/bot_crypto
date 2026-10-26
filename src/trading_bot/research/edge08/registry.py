"""WP-EDGE-08 — the benchmark label, cached once per process.

``market_regime_series`` walks the benchmark's daily bars and is not cheap; the runner asks for the
label of every trade it produced, and the analysis asks again for the breakdown. This module builds
the series once and hands out the same tuple afterwards, so two readings of the same trade cannot
disagree about the market it was taken in.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.edge01.features import market_regime_at

__all__ = ["regime_at", "regime_rows", "reset_cache"]

_ROWS: tuple[Any, ...] | None = None
_META: dict[str, Any] = {}


def regime_rows() -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The benchmark's regime series and its provenance, built once."""
    global _ROWS, _META
    if _ROWS is None:
        from trading_bot.research.edge08.universe import benchmark_regime_rows

        _ROWS, _META = benchmark_regime_rows()
    return _ROWS, dict(_META)


def regime_at(decision_ts: int) -> str:
    """The benchmark label as of one decision instant."""
    rows, _ = regime_rows()
    return market_regime_at(rows, decision_ts)


def reset_cache() -> None:
    """Forget the cached series (the tests build it against a temporary corpus)."""
    global _ROWS, _META
    _ROWS = None
    _META = {}
