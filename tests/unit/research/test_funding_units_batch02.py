"""DISCOVERY-BATCH-02 preregistration + funding-unit contract tests (C5).

Covers the DEF-DISCOVERY-001 repair contract:

- funding unit normalization: decimal / percent / bps; unknown unit fails
  closed; non-finite fails closed
- funding interval: 8h vs other intervals explicit; never silently assumed
- annualization: frozen 365d seconds-per-year
- funding PnL sign correctness: LONG pays positive funding, SHORT receives;
  negative funding flips; zero funding is zero
- carry_funding_v2 signal: positive/negative/zero funding, SHORT arm, sign
  correctness in net returns, PIT window behavior
- batch-02 lead specs byte-equal to batch-01 semantics (no retuning) and
  drift detection actually fails on retune
- preregistration fingerprint determinism
"""

from __future__ import annotations

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.research.discovery_batch02_spec import (
    BATCH02_EVAL_SPECS,
    COST_RATE,
    SLIPPAGE_BPS,
    batch02_eval_fingerprint,
    carry_funding_v2_signals,
    cross_sectional_v2_signals,
    verify_batch01_spec_unchanged,
    volatility_structure_v2_signals,
)
from trading_bot.research.discovery_execution import (
    DISCOVERY_EVAL_SPECS as BATCH01_EVAL_SPECS,
)
from trading_bot.research.funding_units import (
    canon_funding_interval_s,
    canon_rate_per_period,
    annualized_rate,
    contract_fingerprint,
    funding_pnl,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _candle(ts_ms: float, o: float, h: float, low: float, c: float,
            vol: float = 100.0) -> OHLCV:
    return OHLCV(symbol="X/USDT:USDT", timestamp=int(ts_ms), open=o, high=h,
                 low=low, close=c, volume=vol)


def _trend_candles(n: int, start: float = 100.0, step: float = 0.05,
                   hour_ms: int = 3_600_000) -> list[OHLCV]:
    out = []
    p = start
    for i in range(n):
        o = p
        c = p + step
        h = max(o, c) + 0.1
        low = min(o, c) - 0.1
        out.append(_candle(i * hour_ms, o, h, low, c))
        p = c
    return out


# --------------------------------------------------------------------------
# funding unit contract (C5)
# --------------------------------------------------------------------------
class TestFundingUnits:
    def test_decimal_passthrough(self):
        assert canon_rate_per_period(0.0001, source_unit="decimal_per_interval") == 0.0001

    def test_percent_and_bps_normalize(self):
        assert canon_rate_per_period(0.01, source_unit="percent_per_interval") == 0.0001
        assert canon_rate_per_period(1.0, source_unit="bps_per_interval") == 0.0001

    def test_unknown_unit_fails_closed(self):
        with pytest.raises(ValueError, match="UNKNOWN_FUNDING_SOURCE_UNIT"):
            canon_rate_per_period(0.0001, source_unit="APR")

    def test_non_finite_fails_closed(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="NON_FINITE"):
                canon_rate_per_period(bad, source_unit="decimal_per_interval")

    def test_interval_8h_explicit(self):
        assert canon_funding_interval_s("8h") == 28800
        assert canon_funding_interval_s(28800) == 28800

    def test_interval_other_than_8h(self):
        assert canon_funding_interval_s("4h") == 14400
        assert canon_funding_interval_s("1h") == 3600

    def test_interval_never_silently_assumed(self):
        with pytest.raises(ValueError, match="FUNDING_INTERVAL_REQUIRED"):
            canon_funding_interval_s(None)

    def test_invalid_interval_fails(self):
        with pytest.raises(ValueError, match="INVALID_FUNDING_INTERVAL"):
            canon_funding_interval_s(0)

    def test_annualization_frozen_365d(self):
        # 0.0001 per 8h -> 0.0001 * (365*24*3600 / 28800) = 0.01095
        assert annualized_rate(0.0001, 28800) == pytest.approx(
            0.0001 * (365 * 24 * 3600) / 28800)

    def test_funding_pnl_long_pays_positive(self):
        assert funding_pnl("LONG", 10_000.0, 0.0001) == pytest.approx(-1.0)

    def test_funding_pnl_short_receives_positive(self):
        assert funding_pnl("SHORT", 10_000.0, 0.0001) == pytest.approx(1.0)

    def test_funding_pnl_negative_rate_flips(self):
        assert funding_pnl("LONG", 10_000.0, -0.0001) == pytest.approx(1.0)
        assert funding_pnl("SHORT", 10_000.0, -0.0001) == pytest.approx(-1.0)

    def test_funding_pnl_zero_is_zero(self):
        assert funding_pnl("LONG", 10_000.0, 0.0) == 0.0
        assert funding_pnl("SHORT", 10_000.0, 0.0) == 0.0

    def test_funding_pnl_rejects_bad_side(self):
        with pytest.raises(ValueError, match="INVALID_POSITION_SIDE"):
            funding_pnl("long ", 10_000.0, 0.0001)

    def test_contract_fingerprint_deterministic(self):
        assert contract_fingerprint() == contract_fingerprint()
        assert len(contract_fingerprint()) == 64


# --------------------------------------------------------------------------
# carry_funding_v2 signal semantics (C5)
# --------------------------------------------------------------------------
def _funding_map(start_ms: int, n_intervals: int, rate: float,
                 interval_s: int = 28800) -> dict[int, float]:
    """Settlement-ms-keyed funding map (canonical batch-02 contract)."""
    return {
        start_ms + i * interval_s * 1000: rate
        for i in range(n_intervals)
    }


class TestCarryFundingV2:
    @staticmethod
    def _settlements(funding: dict[int, float], start_ms: int,
                     end_ms: int) -> int:
        return sum(1 for t in funding if start_ms <= t <= end_ms)

    def test_positive_funding_yields_short_and_short_receives(self):
        # TRUE CARRY: positive funding -> SHORT (receives +rate)
        candles = _trend_candles(120)
        funding = _funding_map(0, 24, 0.0001)  # +1bp per 8h interval
        res = carry_funding_v2_signals(candles, funding, hold_bars=8)
        assert res.opportunities > 0
        assert all(t.direction == "SHORT" for t in res.trades)
        for t in res.trades:
            n_set = self._settlements(funding, t.entry_ts, t.exit_ts)
            assert t.net_return == pytest.approx(
                t.gross_return - 2 * COST_RATE - 2 * SLIPPAGE_BPS / 10_000.0
                + n_set * 0.0001, abs=1e-9)
        assert any(
            self._settlements(funding, t.entry_ts, t.exit_ts) > 0
            for t in res.trades)

    def test_negative_funding_yields_long_and_long_receives(self):
        # TRUE CARRY: negative funding -> LONG (receives |rate|)
        candles = _trend_candles(120)
        funding = _funding_map(0, 24, -0.0001)
        res = carry_funding_v2_signals(candles, funding, hold_bars=8)
        assert res.opportunities > 0
        assert all(t.direction == "LONG" for t in res.trades)
        for t in res.trades:
            n_set = self._settlements(funding, t.entry_ts, t.exit_ts)
            assert t.net_return == pytest.approx(
                t.gross_return - 2 * COST_RATE - 2 * SLIPPAGE_BPS / 10_000.0
                + n_set * 0.0001, abs=1e-9)

    def test_zero_funding_never_trades(self):
        candles = _trend_candles(120)
        funding = _funding_map(0, 24, 0.0)
        res = carry_funding_v2_signals(candles, funding, hold_bars=8)
        assert res.opportunities == 0 and not res.trades

    def test_batch01_hypothesis_sign_defect_documented(self):
        # The v1 hypothesis (LONG when funding positive, "positive-carry
        # accrual") is wrong-signed perp mechanics; the repair is the
        # TRUE-CARRY direction rule.  This test pins the rule: positive
        # funding NEVER produces LONG signals in v2.
        candles = _trend_candles(120)
        funding = _funding_map(0, 24, 0.0005)
        res = carry_funding_v2_signals(candles, funding, hold_bars=8)
        assert res.trades and all(t.direction == "SHORT" for t in res.trades)

    def test_empty_funding_map_is_insufficient(self):
        candles = _trend_candles(120)
        res = carry_funding_v2_signals(candles, {}, hold_bars=8)
        assert res.opportunities == 0  # no data -> no signal (never invented)


# --------------------------------------------------------------------------
# preregistration integrity (DB2-02/DB2-03)
# --------------------------------------------------------------------------
class TestPreregistrationIntegrity:
    def test_lead_specs_equal_batch01_semantics(self):
        mirrored = verify_batch01_spec_unchanged()
        assert mirrored == {
            "volatility_structure_v2": "volatility_structure",
            "cross_sectional_v2": "cross_sectional",
        }

    def test_batch01_specs_untouched_in_module(self):
        # the repair must not have mutated the batch-01 spec object (flat keys)
        v1 = BATCH01_EVAL_SPECS["carry_funding"]
        assert v1["entry_rule"].startswith("LONG when trailing mean funding_rate > 0")
        assert "DECIMAL UNITS" not in v1["entry_rule"]
        assert v1["funding_window"] == 8

    def test_fingerprints_deterministic(self):
        for cat in BATCH02_EVAL_SPECS:
            assert batch02_eval_fingerprint(cat) == batch02_eval_fingerprint(cat)

    def test_retune_detection_fails_hard(self):
        from trading_bot.research import discovery_batch02_spec as spec
        saved = dict(spec.BATCH02_EVAL_SPECS["volatility_structure_v2"])
        try:
            mutated = dict(saved)
            mutated["atr_z"] = 99.0  # economic change
            spec.BATCH02_EVAL_SPECS["volatility_structure_v2"] = mutated
            with pytest.raises(AssertionError, match="RETUNE DETECTED"):
                verify_batch01_spec_unchanged()
        finally:
            spec.BATCH02_EVAL_SPECS["volatility_structure_v2"] = saved

    def test_candidate_set_exact(self):
        assert set(BATCH02_EVAL_SPECS) == {
            "volatility_structure_v2", "cross_sectional_v2", "carry_funding_v2"}
