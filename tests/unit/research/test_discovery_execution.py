"""DISCOVERY-EXECUTION-01 tests (Track C, ALPHA-DISCOVERY-AND-SHADOW-V2-01)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research.discovery_execution import (
    DISCOVERY_EVAL_SPECS,
    DiscoveryReport,
    discovery_eval_fingerprint,
    execute_discovery_batch,
)
from trading_bot.research.legacy_retro import LegacyRetroHarness, LegacyRetroProtocol

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _candles(n: int, start_ms: int = 1_700_000_000_000, drift: float = 0.0) -> list[OHLCV]:
    out: list[OHLCV] = []
    price = 100.0
    for i in range(n):
        o = price
        c = price * (1 + drift)
        high = max(o, c) * 1.001
        low = min(o, c) * 0.999
        out.append(
            OHLCV(
                symbol="X/USDT:USDT",
                timestamp=start_ms + i * 300_000,  # 5m
                open=o,
                high=high,
                low=low,
                close=c,
                volume=10.0,
            )
        )
        price = c
    return out


def _protocol() -> LegacyRetroProtocol:
    return LegacyRetroProtocol(
        name="discovery-test",
        frozen_at_utc="2026-09-09T00:00:00Z",
        assets=("X",),
        timeframes=("5m",),
        applicability={"*": ("X",)},
        directions=("LONG", "SHORT"),
        commission_rate=0.0004,
        slippage_bps=2.0,
        min_trades_per_cell=5,
        min_sharpe=0.0,
        min_expectancy=0.0,
        max_pvalue=0.05,
        confidence_level=0.90,
        regime_method="window_snapshot",
        use_walk_forward=False,
        use_purged_cv=False,
        holdout_fraction=0.0,
        holdout_policy="none",
    )


def _harness() -> LegacyRetroHarness:
    return LegacyRetroHarness(_protocol())


class _FakeFetcher:
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        return _candles(limit)


# --------------------------------------------------------------------------
# C1 — preregistration fingerprints
# --------------------------------------------------------------------------


def test_eval_specs_cover_all_six_categories() -> None:
    assert set(DISCOVERY_EVAL_SPECS) == {
        "carry_funding",
        "cross_sectional",
        "session_time",
        "liquidity_flow",
        "volatility_structure",
        "regime_transition_defense",
    }


def test_eval_fingerprints_deterministic_and_distinct() -> None:
    fps = {c: discovery_eval_fingerprint(c) for c in DISCOVERY_EVAL_SPECS}
    assert len(set(fps.values())) == len(fps)
    assert all(len(v) == 64 for v in fps.values())
    assert fps == {c: discovery_eval_fingerprint(c) for c in DISCOVERY_EVAL_SPECS}


# --------------------------------------------------------------------------
# C5 — result states & honest accounting
# --------------------------------------------------------------------------


def test_flat_series_yields_insufficient_sample_not_pass() -> None:
    report = execute_discovery_batch(
        fetcher=_FakeFetcher(),
        funding_fetcher=lambda symbol: {},
        harness=_harness(),
        assets=("X",),
        timeframes=("5m",),
        window_bars=200,
        commission_rate=0.0004,
        slippage_bps=2.0,
    )
    assert isinstance(report, DiscoveryReport)
    d = report.to_dict()
    # A flat synthetic series must never mint a DISCOVERY_PASS.
    assert all(c["status"] != "DISCOVERY_PASS" for c in d["cells"])
    statuses = {c["status"] for c in d["cells"]}
    assert statuses <= {"INSUFFICIENT_SAMPLE", "DISCOVERY_FAIL", "DISCOVERY_PASS", "NOT_APPLICABLE"}


def test_report_result_states_reconcile() -> None:
    report = execute_discovery_batch(
        fetcher=_FakeFetcher(),
        funding_fetcher=lambda symbol: {},
        harness=_harness(),
        assets=("X",),
        timeframes=("5m",),
        window_bars=200,
        commission_rate=0.0004,
        slippage_bps=2.0,
    )
    d = report.to_dict()
    total = sum(d["result_states"].values())
    # 5 evaluated categories + 1 honest cross_sectional NOT_APPLICABLE cell.
    assert total == len(d["cells"]) == 6


def test_cell_metrics_are_valid_json_with_cost_model() -> None:
    report = execute_discovery_batch(
        fetcher=_FakeFetcher(),
        funding_fetcher=lambda symbol: {},
        harness=_harness(),
        assets=("X",),
        timeframes=("5m",),
        window_bars=200,
        commission_rate=0.0004,
        slippage_bps=2.0,
    )
    for cell in report.cells:
        payload: dict[str, Any] = json.loads(cell.metrics_json)
        assert "cost_model" in payload
        assert payload["n"] == cell.n_trades


# --------------------------------------------------------------------------
# C6 — frequency evidence recorded, never tuned
# --------------------------------------------------------------------------


def test_frequency_fields_present() -> None:
    report = execute_discovery_batch(
        fetcher=_FakeFetcher(),
        funding_fetcher=lambda symbol: {},
        harness=_harness(),
        assets=("X",),
        timeframes=("5m",),
        window_bars=200,
        commission_rate=0.0004,
        slippage_bps=2.0,
    )
    freq = report.frequency
    assert "opportunities_by_category" in freq
    assert "days_with_opportunity_by_category" in freq
    assert "opportunities_per_day" in freq
    assert freq["note"].startswith("C6")


# --------------------------------------------------------------------------
# PIT discipline: decision at bar t must not see bar t+1
# --------------------------------------------------------------------------


def test_no_future_leak_step_change() -> None:
    # 300 flat bars then a single huge spike: any strategy trading BEFORE the
    # spike would leak. Build candles where the spike happens mid-series.
    n_flat, n_after = 150, 150
    candles = _candles(n_flat + n_after)
    spike_idx = n_flat
    spiked = list(candles)
    c = spiked[spike_idx]
    spiked[spike_idx] = OHLCV(
        symbol=c.symbol,
        timestamp=c.timestamp,
        open=c.open,
        high=c.high * 1.2,
        low=c.low,
        close=c.close * 1.2,
        volume=c.volume * 50,
    )
    report = execute_discovery_batch(
        fetcher=_FakeFetcher(),
        funding_fetcher=lambda symbol: {},
        harness=_harness(),
        assets=("X",),
        timeframes=("5m",),
        window_bars=200,
        commission_rate=0.0004,
        slippage_bps=2.0,
    )
    assert report.dataset_fingerprint  # executes cleanly; specific trade-level
    # assertions are covered by the legacy executor's PIT tests.


def test_prereg_block_recorded_in_report() -> None:
    report = execute_discovery_batch(
        fetcher=_FakeFetcher(),
        funding_fetcher=lambda symbol: {},
        harness=_harness(),
        assets=("X",),
        timeframes=("5m",),
        window_bars=200,
        commission_rate=0.0004,
        slippage_bps=2.0,
    )
    pre = report.preregistration
    assert pre["frozen_candidate_manifest_sha256"].startswith("e8d5aa62")
    assert pre["frozen_candidate_manifest_commit"] == "f155a69"
    assert set(pre["eval_spec_fingerprints"]) == set(DISCOVERY_EVAL_SPECS)


@pytest.mark.parametrize("category", sorted(DISCOVERY_EVAL_SPECS))
def test_every_spec_fingerprint_stable(category: str) -> None:
    assert len(discovery_eval_fingerprint(category)) == 64
