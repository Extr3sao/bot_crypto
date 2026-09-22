"""Track C tests — preregistered legacy retro-validation harness (LV-01..06)."""

from __future__ import annotations

import pytest

from trading_bot.research.legacy_retro import (
    LEGACY_STRATEGIES,
    CellStatus,
    LegacyRetroHarness,
    LegacyRetroProtocol,
    protocol_fingerprint,
)

TRENDY = [
    0.010,
    0.006,
    0.004,
    0.008,
    0.003,
    0.012,
    0.005,
    0.007,
    0.004,
    0.009,
    0.006,
    0.003,
    0.010,
    0.005,
    0.008,
    0.004,
    0.006,
    0.011,
    0.004,
    0.007,
]
CHOPPY = [
    0.002,
    -0.001,
    -0.004,
    0.001,
    -0.002,
    0.003,
    -0.001,
    -0.003,
    0.002,
    -0.001,
    -0.002,
    0.001,
    -0.003,
    0.002,
    -0.001,
    0.001,
    -0.002,
    0.000,
    0.002,
    -0.001,
]


def _protocol(**overrides: object) -> LegacyRetroProtocol:
    base: dict[str, object] = {
        "name": "LEGACY-RETRO-VALIDATION-01",
        "frozen_at_utc": "2026-09-09T00:00:00Z",
        "assets": ("BTC", "ETH", "SOL"),
        "timeframes": ("5m", "1h"),
        "applicability": {
            "momentum": ("BTC", "ETH", "SOL"),
            "trend": ("BTC", "ETH", "SOL"),
            "breakout": ("BTC", "ETH", "SOL"),
            "mean_reversion": ("BTC", "ETH", "SOL"),
            "volatility": ("BTC", "ETH", "SOL"),
        },
        "directions": ("LONG", "SHORT"),
        "commission_rate": 0.0005,
        "slippage_bps": 1.0,
        "min_trades_per_cell": 15,
        "min_sharpe": 0.10,
        "min_expectancy": 0.0,
        "max_pvalue": 0.10,
        "confidence_level": 0.90,
        "regime_method": "regime_v2_canonical_6dim",
        "use_walk_forward": True,
        "use_purged_cv": True,
        "holdout_fraction": 0.25,
        "holdout_policy": "temporal_holdout_evaluated_last",
        "acceptance_thresholds": {},
    }
    base.update(overrides)
    return LegacyRetroProtocol(**base)  # type: ignore[arg-type]


class TestProtocolFreeze:
    def test_fingerprint_stable_and_sensitive(self) -> None:
        p1 = _protocol()
        p2 = _protocol()
        assert p1.fingerprint == p2.fingerprint
        # Any ex-ante change is detectable.
        p3 = _protocol(min_sharpe=0.2)
        assert p3.fingerprint != p1.fingerprint

    def test_protocol_is_immutable(self) -> None:
        p = _protocol()
        with pytest.raises(AttributeError):
            p.min_sharpe = 0.5  # type: ignore[misc]

    def test_five_legacy_strategies_preregistered(self) -> None:
        assert LEGACY_STRATEGIES == (
            "momentum",
            "trend",
            "breakout",
            "mean_reversion",
            "volatility",
        )
        p = _protocol()
        assert set(p.applicability) == set(LEGACY_STRATEGIES)

    def test_walk_forward_and_holdout_declared(self) -> None:
        p = _protocol()
        assert p.use_walk_forward is True
        assert p.use_purged_cv is True
        assert 0 < p.holdout_fraction < 1
        assert p.holdout_policy == "temporal_holdout_evaluated_last"


class TestMatrixEvaluation:
    def test_validated_cell_passes_all_gates(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        v = harness.evaluate_cell(
            strategy_id="momentum",
            asset="BTC",
            timeframe="5m",
            regime="TREND",
            trade_returns=TRENDY,
        )
        assert v.status == CellStatus.VALIDATED_CELL
        assert v.metrics is not None
        assert v.metrics.prob_sharpe_gt0 >= 0.5
        assert v.metrics.permutation_pvalue < 0.10
        assert v.protocol_fingerprint == protocol_fingerprint(_protocol())

    def test_failed_cell_does_not_aggregate_away(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        v = harness.evaluate_cell(
            strategy_id="momentum",
            asset="ETH",
            timeframe="5m",
            regime="RANGE",
            trade_returns=CHOPPY,
        )
        assert v.status == CellStatus.FAILED_CELL
        assert "failed gates" in v.reason
        assert v.metrics is not None

    def test_insufficient_sample_fail_closed(self) -> None:
        harness = LegacyRetroHarness(_protocol(min_trades_per_cell=30))
        v = harness.evaluate_cell(
            strategy_id="trend",
            asset="SOL",
            timeframe="1h",
            regime="TREND",
            trade_returns=TRENDY,  # 20 < 30
        )
        assert v.status == CellStatus.INSUFFICIENT_SAMPLE
        assert v.metrics is None

    def test_not_applicable_when_not_preregistered(self) -> None:
        harness = LegacyRetroHarness(_protocol(applicability={"momentum": ("BTC", "ETH", "SOL")}))
        v = harness.evaluate_cell(
            strategy_id="trend",
            asset="BTC",
            timeframe="5m",
            regime="TREND",
            trade_returns=TRENDY,
        )
        assert v.status == CellStatus.NOT_APPLICABLE

    def test_regime_binding_must_be_declared(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        v = harness.evaluate_cell(
            strategy_id="momentum",
            asset="BTC",
            timeframe="5m",
            regime="BROADER_TREND_CLASS",
            trade_returns=TRENDY,
            regime_binding="opportunistic_merge",  # never legal
        )
        assert v.status == CellStatus.NOT_APPLICABLE
        assert "declared_fallback" in v.reason

    def test_declared_fallback_is_legal_and_labeled(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        v = harness.evaluate_cell(
            strategy_id="momentum",
            asset="BTC",
            timeframe="5m",
            regime="TREND_BROADER",
            trade_returns=TRENDY,
            regime_binding="declared_fallback",
        )
        assert v.status == CellStatus.VALIDATED_CELL
        assert v.regime_binding == "declared_fallback"

    def test_zero_variance_cell_is_not_validated(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        flat = [0.001] * 20  # zero variance -> degenerate statistics
        v = harness.evaluate_cell(
            strategy_id="mean_reversion",
            asset="BTC",
            timeframe="5m",
            regime="RANGE",
            trade_returns=flat,
        )
        # zero-variance: CI is degenerate (0,0) so ci_excludes_negative fails
        assert v.status == CellStatus.FAILED_CELL
        assert "ci_excludes_negative" in v.reason

    def test_matrix_over_five_strategies(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        rows = [
            {"strategy_id": s, "asset": a, "timeframe": tf, "regime": r, "regime_binding": "exact"}
            for s in LEGACY_STRATEGIES
            for a in ("BTC", "ETH", "SOL")
            for tf in ("5m",)
            for r in ("TREND", "RANGE")
        ]
        verdicts = harness.evaluate_matrix(
            rows, trade_returns_for=lambda row: TRENDY if row["regime"] == "TREND" else CHOPPY
        )
        assert len(verdicts) == 30
        statuses = {v.status for v in verdicts}
        assert statuses <= set(CellStatus.all())
        assert CellStatus.VALIDATED_CELL in statuses
        assert CellStatus.FAILED_CELL in statuses


class TestHealthBaselines:
    def test_baselines_only_from_valid_cells(self) -> None:
        harness = LegacyRetroHarness(_protocol())
        good = harness.evaluate_cell(
            strategy_id="momentum",
            asset="BTC",
            timeframe="5m",
            regime="TREND",
            trade_returns=TRENDY,
        )
        bad = harness.evaluate_cell(
            strategy_id="momentum",
            asset="ETH",
            timeframe="5m",
            regime="RANGE",
            trade_returns=CHOPPY,
        )
        insufficient = harness.evaluate_cell(
            strategy_id="trend",
            asset="SOL",
            timeframe="1h",
            regime="TREND",
            trade_returns=TRENDY[:5],
        )
        baselines = harness.baselines_from_valid_cells(
            [good, bad, insufficient],
            bars_per_cell={("momentum", "BTC", "5m", "TREND"): 4000},
        )
        assert len(baselines) == 1
        b = baselines[0]
        assert b.strategy_id == "momentum" and b.regime == "TREND"
        assert b.baseline_expectancy > 0
        # All-win sample: PF is undefined (no losses) and stays honestly None
        assert b.baseline_profit_factor is None
        assert b.baseline_trade_frequency == pytest.approx(20 * 100 / 4000)
        assert b.window_fingerprint
        assert b.protocol_fingerprint

    def test_no_baseline_from_poc01_partial_results(self) -> None:
        # Baselines require a VALIDATED cell under the frozen protocol;
        # POC01 partial-day data (1 scan, 0 trades) can never produce one.
        harness = LegacyRetroHarness(_protocol(min_trades_per_cell=15))
        v = harness.evaluate_cell(
            strategy_id="volatility",
            asset="BTC",
            timeframe="5m",
            regime="HIGH_VOL",
            trade_returns=[],
        )
        assert v.status == CellStatus.INSUFFICIENT_SAMPLE
        assert harness.baselines_from_valid_cells([v]) == []
