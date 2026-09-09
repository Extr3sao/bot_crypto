"""DISCOVERY-BATCH-02 execution driver (POC02-LAUNCH-AND-DISCOVERY-BATCH-02).

Preregistration: docs/external-audit-01/DISCOVERY_BATCH_02_PREREGISTRATION.json
(committed BEFORE execution, e1f1193).  This driver:

  1. fetches the deeper preregistered windows (1h x 17520 bars per asset,
     5m x 1500 bars) from PUBLIC binanceusdm (no credentials);
  2. fetches REAL binanceusdm funding history for the carry cells (C6) —
     INSUFFICIENT_DATA if depth is unavailable, never synthetic;
  3. executes the three preregistered candidates via
     ``trading_bot.research.batch02_execution.execute_batch02`` with the
     FROZEN LegacyRetroHarness gates (batch-01 thresholds, no lowering);
  4. persists results with regime x asset x timeframe attribution
     (Track D), frequency evidence (Track E) and the preregistration hash.

PAPER/research only: public market data, no orders, no promotions.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.batch02_execution import (  # noqa: E402
    BATCH02_PREREG_JSON,
    BATCH02_PREREG_SHA256,
    execute_batch02,
)
from trading_bot.research.discovery_batch02_spec import (  # noqa: E402
    DEEPER_1H_BARS,
    DEEPER_5M_BARS,
    verify_batch01_spec_unchanged,
)
from trading_bot.research.funding_data import fetch_funding_history  # noqa: E402
from trading_bot.research.legacy_retro import LegacyRetroHarness, LegacyRetroProtocol  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "external-audit-01"
OUT_JSON = OUT_DIR / "DISCOVERY_BATCH_02_RESULTS.json"

FROZEN_PROTOCOL = dict(
    name="canonical legacy discovery protocol (batch-01 execution values)",
    frozen_at_utc="2026-08-28T00:00:00Z",
    assets=("BTC", "ETH", "SOL"),
    timeframes=("5m", "1h"),
    applicability={
        "volatility_structure_v2": ("BTC", "ETH", "SOL"),
        "cross_sectional_v2": ("BTC+ETH+SOL",),
        "carry_funding_v2": ("BTC", "ETH", "SOL"),
    },
    directions=("LONG", "SHORT"),
    commission_rate=0.0004,
    slippage_bps=2.0,
    min_trades_per_cell=15,
    min_sharpe=0.0,
    min_expectancy=0.0,
    max_pvalue=0.05,
    confidence_level=0.90,
    regime_method="regime_v2_canonical_6dim",
    use_walk_forward=True,
    use_purged_cv=True,
    holdout_fraction=0.25,
    holdout_policy="temporal_holdout_evaluated_last",
    acceptance_thresholds={},
)


class BinanceUsdmWindowedFetcher:
    """PUBLIC binanceusdm OHLCV fetcher with end-anchored pagination.

    ``fetch_ohlcv(symbol, tf, limit, end_ms)`` returns the ``limit`` bars
    whose close is <= ``end_ms`` (window boundary pinned at the batch
    launch instant per the preregistration: LENGTH is frozen, anchor is
    the execution instant).  No credentials; no private methods.
    """

    provider = "binanceusdm-public-ccxt"

    def __init__(self) -> None:
        import ccxt

        self._ex = ccxt.binanceusdm({"enableRateLimit": True})

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        end_ms: int | None = None,
    ):
        import ccxt

        step_ms = 3_600_000 if timeframe == "1h" else 300_000
        end = int(end_ms or self._ex.milliseconds())
        # Forward pagination over exactly [end - limit*step, end): each API
        # range is requested once; bars opening at/after `end` are dropped
        # (PIT boundary stays honest).
        window_start = end - limit * step_ms
        out: list[list[float]] = []
        cursor = window_start
        while cursor < end:
            page_limit = min(1000, limit - len(out))
            rows = self._fetch_with_backoff(
                symbol, timeframe, since=cursor, limit=page_limit
            )
            if not rows:
                break
            appended = 0
            for r in rows:
                if r[0] >= end:
                    break
                if not out or r[0] > out[-1][0]:
                    out.append(r)
                    appended += 1
            if appended == 0:
                break
            cursor = out[-1][0] + step_ms
            if len(out) >= limit:
                break
        out = out[-limit:]
        candles = []
        from trading_bot.market_data.types import OHLCV

        for r in out:
            candles.append(
                OHLCV(
                    symbol=symbol,
                    timestamp=int(r[0]),
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    volume=float(r[5]),
                )
            )
        return candles

    def _fetch_with_backoff(self, symbol: str, timeframe: str, *, since: int, limit: int):
        """Public fetch with bounded 429 backoff (public IP limits)."""
        import ccxt

        delays = (10.0, 30.0)
        for attempt, delay in enumerate((0.0,) + delays):
            if delay:
                time.sleep(delay)
            try:
                return self._ex.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=since, limit=limit
                )
            except ccxt.DDoSProtection:
                if attempt == len(delays):
                    raise
        return []


def main() -> int:
    started = datetime.now(UTC).replace(microsecond=0)
    end_ms_by_tf = {"1h": int(time.time() * 1000), "5m": int(time.time() * 1000)}
    fetcher = BinanceUsdmWindowedFetcher()
    protocol = LegacyRetroProtocol(**FROZEN_PROTOCOL)
    harness = LegacyRetroHarness(protocol)
    b01 = verify_batch01_spec_unchanged()
    assert b01 == {
        "volatility_structure_v2": "volatility_structure",
        "cross_sectional_v2": "cross_sectional",
    }, f"batch-01 lead drift detected: {b01}"

    def funding_fetcher(symbol: str):
        # REAL funding history (C6): binanceusdm fetchFundingRateHistory.
        # Depth is provider-limited (public endpoint); the recorded window
        # start is whatever the exchange returns — never synthesized.
        ds = fetch_funding_history(
            symbol,
            window_start_ms=end_ms_by_tf["1h"] - DEEPER_1H_BARS * 3_600_000,
            window_end_ms=end_ms_by_tf["1h"],
        )
        return ds

    # The executor wants (funding_by_ms, interval_s, meta); adapt from the
    # FundingDataset while preserving provenance per symbol.
    funding_meta: dict[str, dict] = {}

    def funding_fetcher_adapted(symbol: str):
        ds = funding_fetcher(symbol)
        funding_meta[symbol] = ds.to_meta()
        return ds.rates_by_ms, ds.interval_s, {"rows": ds.n_observations}

    # monkeypatch-free: wrap the executor's row conversion is unnecessary —
    # it accepts any mapping; instead adapt rows -> canonical tuples here.

    class _FundingRowsAdapter:
        """Present the FundingDataset as ccxt-shaped rows for the executor."""

        def __init__(self, symbol: str) -> None:
            self._symbol = symbol
            self._ds = None

        def __call__(self, symbol: str):
            ds = funding_fetcher(symbol)
            self._ds = ds
            funding_meta[symbol] = ds.to_meta()
            return [
                {"timestamp": t, "fundingRate": r}
                for t, r in sorted(ds.rates_by_ms.items())
            ]

    report = execute_batch02(
        fetcher=fetcher,
        funding_fetcher=_FundingRowsAdapter(None),
        harness=harness,
        window_end_by_tf=end_ms_by_tf,
        assets=("BTC", "ETH", "SOL"),
        timeframes=("5m", "1h"),
        window_bars={"5m": DEEPER_5M_BARS, "1h": DEEPER_1H_BARS},
        commission_rate=0.0004,
        slippage_bps=2.0,
    )

    results = {
        "artifact": "DISCOVERY_BATCH_02_RESULTS",
        "checkpoint": "POC02-LAUNCH-AND-DISCOVERY-BATCH-02",
        "batch": "DISCOVERY-BATCH-02",
        "preregistration": BATCH02_PREREG_JSON,
        "preregistration_sha256": BATCH02_PREREG_SHA256,
        "frozen_protocol_fingerprint": protocol.fingerprint,
        "batch01_spec_verification": b01,
        "executed_at_utc": started.isoformat(),
        "window_end_utc": datetime.fromtimestamp(
            end_ms_by_tf["1h"] / 1000, tz=UTC
        ).isoformat(),
        "window_bars": {"1h": DEEPER_1H_BARS, "5m": DEEPER_5M_BARS},
        "funding_provenance": funding_meta,
        "dataset_fingerprint": report.dataset_fingerprint,
        "window_meta": report.window_meta,
        "preregistration_detail": report.preregistration,
        "cells": [
            {
                "category": c.category,
                "asset": c.asset,
                "timeframe": c.timeframe,
                "regime": c.regime,
                "status": c.status,
                "n_trades": c.n_trades,
                "metrics": json.loads(c.metrics_json),
                "reason": c.reason,
                "spec_fingerprint": c.spec_fingerprint,
            }
            for c in report.cells
        ],
        "frequency": report.frequency,
        "governance": {
            "research_only": True,
            "paper_promotions": 0,
            "no_retuning_after_results": True,
        },
    }
    OUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    summary = {}
    for c in results["cells"]:
        summary.setdefault(c["category"], []).append(
            f"{c['asset']}:{c['timeframe']}:{c['regime']}={c['status']}(n={c['n_trades']})"
        )
    print(json.dumps(summary, indent=1))
    print("wrote", OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
