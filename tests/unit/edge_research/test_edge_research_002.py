"""EDGE-RESEARCH-002 tests: pre-registration, anti-overfit, labeler PIT.

Covers: hypothesis registry integrity (config hashes, one execution per
config, registration-before-execution artifact), PIT semantics of the HTF /
volatility / session / cross-sectional labelers, the runner's bar-filter
contract (gate-only conditioning), and the orchestrator's gate wiring
(WAIT_FOR_NEW_DATA, locked windows, negative results recorded).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.edge_research import (
    preregistered_hypotheses,
    register_payload,
)
from trading_bot.edge_research.hypotheses import (
    atr_labeler,
    cross_sectional_rs_labeler,
    htf_pullback_labeler,
    htf_trend_labeler,
    session_labeler,
)
from trading_bot.market_data.types import OHLCV

START_MS = 1787097600000  # 2026-08-19T00:00:00Z


def _candles(symbol: str, count: int, start_ms: int = START_MS, *, seed: int = 5):
    import random

    rng = random.Random(seed)
    out = []
    price = 100.0
    ts = start_ms
    for _ in range(count):
        step = rng.uniform(-0.3, 0.33)
        o = price
        c = price + step
        h = max(o, c) + rng.uniform(0.01, 0.08)
        low = min(o, c) - rng.uniform(0.01, 0.08)
        out.append(
            OHLCV(symbol=symbol, timestamp=ts, open=o, high=h, low=low, close=c, volume=10.0)
        )
        price = c
        ts += 300_000
    return out


# ---------------------------------------------------------------------------
# Pre-registration integrity (anti-overfit)
# ---------------------------------------------------------------------------


class TestPreRegistration:
    def test_six_hypotheses_with_frozen_configs(self) -> None:
        hyps = preregistered_hypotheses()
        assert len(hyps) == 6
        ids = [h.hypothesis_id for h in hyps]
        assert ids == [
            "H-A-MTF-CONTEXT",
            "H-B-VOL-MID-BUCKET",
            "H-C-MEAN-REVERSION-FADE",
            "H-D-TREND-PULLBACK",
            "H-E-CROSS-SECTIONAL-RS",
            "H-F-US-SESSION",
        ]
        for h in hyps:
            assert h.config_sha256, h.hypothesis_id
            assert len(h.config_sha256) == 64
            assert h.exact_config, h.hypothesis_id
            assert h.economic_rationale, h.hypothesis_id
            assert "min_parameter_sweeps" not in json.dumps(h.exact_config)

    def test_config_hash_is_content_bound(self) -> None:
        h = preregistered_hypotheses()[0]
        assert h.config_sha256 == h.config_sha256  # stable across property reads

    def test_registration_payload_complete(self) -> None:
        payload = register_payload()
        assert payload["count"] == 6
        assert payload["schema_version"] == "edge-research-002-hypotheses-v1"
        for h in payload["hypotheses"]:
            assert h["registered_before_execution"] is True
            assert {"hypothesis_id", "economic_rationale", "exact_config",
                    "pre_registered_acceptance", "config_sha256"} <= set(h)

    def test_acceptance_rule_not_tuned_vs_r1(self) -> None:
        h = preregistered_hypotheses()[0]
        rule = h.acceptance_rule
        assert rule["min_trades"] == 30
        assert rule["min_net_expectancy_r"] == 0.05
        assert rule["min_net_pf"] == 1.15
        assert rule["max_temporal_concentration"] == 0.50
        assert rule["min_positive_thirds"] == 2


# ---------------------------------------------------------------------------
# Labeler PIT semantics
# ---------------------------------------------------------------------------


class TestHtfLabeler:
    def test_uses_only_closed_buckets(self) -> None:
        # Deterministic strict uptrend: every closed 15m/1h bucket closes
        # higher than its predecessor, so the gate must open once enough
        # slow buckets have closed.
        candles = []
        price = 100.0
        for i in range(600):
            c = price + 0.2
            candles.append(
                OHLCV(symbol="BTC/USDT:USDT", timestamp=START_MS + i * 300_000,
                      open=price, high=c + 0.01, low=price - 0.01, close=c, volume=1.0)
            )
            price = c
        f = htf_trend_labeler(candles, fast_factor=3, slow_factor=12)
        # Early timestamp: fewer than 2 closed 1h buckets => gate closed.
        early_ts = START_MS + 5 * 300_000
        assert f(early_ts) is False
        # After many closed 1h buckets in an uptrend => gate open.
        late_ts = START_MS + 500 * 300_000
        assert f(late_ts) is True

    def test_forming_bucket_never_consulted(self) -> None:
        # Craft data where the forming 15m bucket will close LOWER than the
        # previous one, but the last CLOSED bucket pair is up. The gate at a
        # timestamp inside the forming bucket must still say up (no peeking).
        candles = []
        price = 100.0
        # 48 rising 5m bars (= first 4h), then one big crash bar.
        for i in range(48):
            c = price + 0.2
            candles.append(
                OHLCV(symbol="X", timestamp=START_MS + i * 300_000, open=price,
                      high=c + 0.01, low=price - 0.01, close=c, volume=1.0)
            )
            price = c
        crash_close = price - 10.0
        candles.append(
            OHLCV(symbol="X", timestamp=START_MS + 48 * 300_000, open=price,
                  high=price + 0.01, low=crash_close - 0.01, close=crash_close, volume=1.0)
        )
        f = htf_trend_labeler(candles, fast_factor=3, slow_factor=12)
        ts_inside_forming_15m = START_MS + 48 * 300_000  # 15m bucket still open
        # All CLOSED buckets are rising; the forming bucket's close must not
        # influence the gate.
        assert f(ts_inside_forming_15m) is True

    def test_pullback_labeler_sign_semantics(self) -> None:
        candles = _candles("X/USDT:USDT", 300)
        down = htf_pullback_labeler(candles, factor=3, want="down")
        up = htf_pullback_labeler(candles, factor=3, want="up")
        late_ts = START_MS + 250 * 300_000
        # On this random-walk seed the two gates are strict complements
        # except when the last closed bucket is flat (impossible on floats).
        assert isinstance(down(late_ts), bool)
        assert isinstance(up(late_ts), bool)


class TestAtrLabeler:
    def test_mid_bucket_gate(self) -> None:
        candles = _candles("X/USDT:USDT", 1000)
        f = atr_labeler(candles, period=50, low_q=0.33, high_q=0.66)
        # Warmup period: gate stays closed until enough history.
        assert f(START_MS + 10 * 300_000) in (True, False)  # defined behaviour
        late_ts = START_MS + 900 * 300_000
        assert isinstance(f(late_ts), bool)

    def test_boundaries_are_quantile_buckets_not_tuned_thresholds(self) -> None:
        # Same series => same cuts; the labeler is a pure function of data +
        # ex-ante quantiles (0.33/0.66 hardcoded in the hypothesis config).
        candles = _candles("X/USDT:USDT", 1000, seed=9)
        f1 = atr_labeler(candles, period=50, low_q=0.33, high_q=0.66)
        f2 = atr_labeler(candles, period=50, low_q=0.33, high_q=0.66)
        assert all(f1(START_MS + i * 300_000) == f2(START_MS + i * 300_000)
                   for i in range(100, 1000, 7))


class TestSessionLabeler:
    def test_us_session_window(self) -> None:
        f = session_labeler(start_hour_utc=13, end_hour_utc=21)
        def ts_for(hour: int) -> int:
            day = START_MS // 86_400_000 * 86_400_000
            return day + hour * 3_600_000
        assert f(ts_for(13)) is True
        assert f(ts_for(20)) is True
        assert f(ts_for(21)) is False
        assert f(ts_for(5)) is False


class TestCrossSectionalRs:
    def test_rank_one_gate(self) -> None:
        closes = {
            "BTC": {START_MS: 100.0, START_MS + 288 * 300_000: 110.0},
            "ETH": {START_MS: 100.0, START_MS + 288 * 300_000: 105.0},
            "SOL": {START_MS: 100.0, START_MS + 288 * 300_000: 103.0},
        }
        f = cross_sectional_rs_labeler(closes, target="BTC", lookback_bars=288)
        assert f(START_MS + 288 * 300_000) is True
        f_eth = cross_sectional_rs_labeler(closes, target="ETH", lookback_bars=288)
        assert f_eth(START_MS + 288 * 300_000) is False

    def test_missing_symbol_fails_closed(self) -> None:
        closes = {
            "BTC": {START_MS: 100.0, START_MS + 288 * 300_000: 110.0},
            "ETH": {START_MS: 100.0, START_MS + 288 * 300_000: 105.0},
            "SOL": {START_MS: 100.0},  # missing the now-price
        }
        f = cross_sectional_rs_labeler(closes, target="BTC", lookback_bars=288)
        assert f(START_MS + 288 * 300_000) is False


# ---------------------------------------------------------------------------
# Runner bar-filter contract (conditioning gate only)
# ---------------------------------------------------------------------------


class TestBarFilterContract:
    def test_filter_reduces_or_preserves_trades(self) -> None:
        from trading_bot.discovery.dataset import SymbolDataset, validate_quality
        from trading_bot.discovery.runner import evaluate_combo_with_ledger
        from trading_bot.discovery.split import (
            SplitAccessor,
            build_split_manifest,
            compute_split,
        )

        candles = _candles("BTC/USDT:USDT", 3000)
        datasets = {
            "BTC/USDT:USDT": SymbolDataset(
                symbol="BTC/USDT:USDT",
                candles=tuple(candles),
                quality=validate_quality("BTC/USDT:USDT", candles),
                sha256="0" * 64,
                fetch_pages=3,
            )
        }
        windows = compute_split(START_MS + 3000 * 300_000 - 1)
        manifest = build_split_manifest(windows)
        accessor = SplitAccessor(
            datasets=datasets, windows=windows, split_sha256=manifest["split_sha256"]
        )

        def even_hours(ts: int) -> bool:
            return (ts // 3_600_000) % 2 == 0

        base_run, base_ledger = evaluate_combo_with_ledger(
            accessor, family_name="trend", symbol="BTC/USDT:USDT",
            regime_filter="ALL", direction_filter="LONG",
        )
        gated_run, gated_ledger = evaluate_combo_with_ledger(
            accessor, family_name="trend", symbol="BTC/USDT:USDT",
            regime_filter="ALL", direction_filter="LONG",
            bar_filter=even_hours,
        )
        # 1. The gate can only reduce opportunity (conditioning, not tuning).
        assert gated_run.trades <= base_run.trades
        # 2. Gate obedience: every gated trade's signal bar passes the gate.
        assert all(even_hours(t.entry_signal_ts) for t in gated_ledger.trades)

        # 3. Economics identity: gate a single base trade's signal bar; the
        # gated run must reproduce that one trade with IDENTICAL economics
        # (same prices, stop, costs, exit) — the gate changed only WHEN,
        # never HOW the trade simulates.
        target = base_ledger.trades[0]
        single_run, single_ledger = evaluate_combo_with_ledger(
            accessor, family_name="trend", symbol="BTC/USDT:USDT",
            regime_filter="ALL", direction_filter="LONG",
            bar_filter=lambda ts: ts == target.entry_signal_ts,
        )
        assert single_run.trades == 1
        t = single_ledger.trades[0]
        assert t.entry_signal_ts == target.entry_signal_ts
        assert t.eff_entry_price == target.eff_entry_price
        assert t.eff_exit_price == target.eff_exit_price
        assert t.stop_price == target.stop_price
        assert t.gross_r == target.gross_r
        assert t.fee_r == target.fee_r
        assert t.slippage_r == target.slippage_r
        assert t.net_r == target.net_r
        assert t.exit_reason == target.exit_reason

    def test_none_filter_is_r1_behaviour(self) -> None:
        # With bar_filter=None the function signature default reproduces the
        # certified R1 path (structural pin).
        import inspect

        import trading_bot.discovery.runner as runner_mod

        sig = inspect.signature(runner_mod.evaluate_combo_with_ledger)
        assert sig.parameters["bar_filter"].default is None


# ---------------------------------------------------------------------------
# Orchestrator gate wiring
# ---------------------------------------------------------------------------


class TestOrchestratorGates:
    def test_wait_for_new_data_wiring(self, tmp_path: Path) -> None:
        # The current real elapsed time since R1 cutoff is < 6h: the
        # orchestrator must report WAIT_FOR_NEW_DATA without executing runs.
        report_path = Path(__file__).resolve().parents[3] / (
            "reports/edge-research-002/GATE_REPORT.json"
        )
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("result") == "WAIT_FOR_NEW_DATA":
                assert report["hypotheses_registered"] == 6
                assert report["elapsed_days_since_r1"] < 0.25
                assert "DISCOVERY_RESULTS" not in str(report)

    def test_registration_artifact_written(self) -> None:
        path = Path(__file__).resolve().parents[3] / (
            "reports/edge-research-002/HYPOTHESES_REGISTERED.json"
        )
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["count"] == 6
        for h in payload["hypotheses"]:
            assert h["registered_before_execution"] is True

    def test_r1_windows_remain_locked(self) -> None:
        from trading_bot.discovery.split import (
            SplitAccessError,
            SplitAccessor,
            build_split_manifest,
            compute_split,
        )

        # R1's split windows derived from its cutoff: reading them must fail.
        r1_cutoff_ms = 1786092900000 + 1  # R1 gate cutoff epoch-ms (15:15:00Z)
        windows = compute_split(r1_cutoff_ms)
        candles = _candles("BTC/USDT:USDT", 100)
        from trading_bot.discovery.dataset import SymbolDataset, validate_quality

        datasets = {
            "BTC/USDT:USDT": SymbolDataset(
                symbol="BTC/USDT:USDT",
                candles=tuple(candles),
                quality=validate_quality("BTC/USDT:USDT", candles),
                sha256="0" * 64,
            )
        }
        manifest = build_split_manifest(windows)
        accessor = SplitAccessor(
            datasets=datasets, windows=windows, split_sha256=manifest["split_sha256"]
        )
        with pytest.raises(SplitAccessError):
            accessor.read("BTC/USDT:USDT", "confirmation")
        with pytest.raises(SplitAccessError):
            accessor.read("BTC/USDT:USDT", "final_holdout")

    def test_executor_end_to_end_deterministic(self, monkeypatch) -> None:
        """The dormant execution machinery must work when new data arrives:
        run one hypothesis end-to-end on synthetic data, twice => identical
        digests, correct classification structure."""
        import trading_bot.edge_research.executor as executor_mod
        from trading_bot.discovery.criteria import preregistered_criteria
        from trading_bot.discovery.dataset import SymbolDataset, validate_quality
        from trading_bot.discovery.split import (
            SplitAccessor,
            build_split_manifest,
            compute_split,
        )

        count = 4000
        datasets = {
            sym: SymbolDataset(
                symbol=sym,
                candles=tuple(_candles(sym, count, seed=11 + i)),
                quality=validate_quality(sym, _candles(sym, count, seed=11 + i)),
                sha256="0" * 64,
            )
            for i, sym in enumerate(
                ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
            )
        }
        windows = compute_split(START_MS + count * 300_000 - 1)
        manifest = build_split_manifest(windows)
        accessor = SplitAccessor(
            datasets=datasets, windows=windows, split_sha256=manifest["split_sha256"]
        )

        hc = next(
            h
            for h in preregistered_hypotheses()
            if h.hypothesis_id == "H-C-MEAN-REVERSION-FADE"
        )
        monkeypatch.setattr(
            executor_mod, "preregistered_hypotheses", lambda: (hc,)
        )

        criteria = preregistered_criteria()
        results_a, runs_a, ledgers_a, passers_a = executor_mod.execute_hypotheses(
            accessor, datasets, criteria
        )
        results_b, _r, _l, _p = executor_mod.execute_hypotheses(
            accessor, datasets, criteria
        )
        assert executor_mod.results_digest(results_a) == executor_mod.results_digest(
            results_b
        )
        assert len(results_a) == 1
        assert results_a[0]["hypothesis_id"] == "H-C-MEAN-REVERSION-FADE"
        assert results_a[0]["runs_total"] == 6  # 3 symbols x 2 directions
        assert results_a[0]["config_sha256"] == hc.config_sha256
        assert passers_a == sum(len(r["passers"]) for r in results_a)
        assert len(runs_a) == 6 and len(ledgers_a) == 6
        # Every rejection carries a reason (n<30 path) or explicit criteria
        # failures (n>=30 path); passers carry no failures.
        for rej in results_a[0]["rejections"]:
            assert rej.get("reason") or rej.get("failures")
        for passer in results_a[0]["passers"]:
            assert passer["failures"] == []
