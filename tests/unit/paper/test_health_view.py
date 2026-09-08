"""Track D tests: read-only Strategy Health view (UI-01..UI-04)."""

from __future__ import annotations

from trading_bot.paper.health_projection import HealthProjectionRow
from trading_bot.paper.health_view import (
    INSUFFICIENT_EVIDENCE,
    REGIME_COLUMNS,
    build_health_matrix,
    health_view_payload,
)


def _row(
    strategy: str = "Momentum",
    regime: str = "TREND",
    n: int = 50,
    state: str = "HEALTHY",
    asset: str = "BTC/USDT",
) -> HealthProjectionRow:
    return HealthProjectionRow(
        strategy=strategy,
        version="1",
        asset=asset,
        timeframe="5m",
        regime=regime,
        observation_window="2026-09-01/2026-09-08",
        health_state=state,
        rolling_expectancy=0.1,
        baseline_expectancy=0.08,
        rolling_sharpe=1.2,
        baseline_sharpe=1.0,
        profit_factor=1.4,
        drawdown=0.05,
        sample_size=n,
        last_transition="PAPER_ACTIVE",
        reason="baseline",
        next_gate="none",
    )


class TestRowViews:
    def test_payload_rows_include_required_fields(self) -> None:
        payload = health_view_payload([_row()])
        row = payload["rows"][0]
        assert row["health_state"] == "HEALTHY"
        assert row["metrics"]["sample_n"] == 50
        assert row["metrics"]["rolling_expectancy"] == 0.1
        assert row["metrics"]["baseline_expectancy"] == 0.08
        assert row["metrics"]["rolling_sharpe"] == 1.2
        assert row["metrics"]["baseline_sharpe"] == 1.0
        assert row["metrics"]["profit_factor"] == 1.4
        assert row["metrics"]["drawdown"] == 0.05
        assert row["transition"]["last"] == "PAPER_ACTIVE"
        assert row["transition"]["reason"] == "baseline"
        assert row["transition"]["next_action"] == "none"
        assert payload["read_only"] is True

    def test_read_only_flag_on_every_element(self) -> None:
        payload = health_view_payload([_row(), _row(strategy="Trend", regime="RANGE")])
        assert payload["read_only"] is True
        for row in payload["rows"]:
            assert row["read_only"] is True
        assert payload["regime_matrix"]["read_only"] is True


class TestRegimeMatrix:
    def test_matrix_cells_are_evidence_backed(self) -> None:
        rows = [_row(regime="TREND", n=60), _row(regime="RANGE", n=10, state="DEGRADED")]
        matrix = build_health_matrix(rows)
        assert matrix.strategies == ("Momentum",)
        assert matrix.regimes == REGIME_COLUMNS
        by_regime = {c.regime: c for c in matrix.cells[0]}
        assert by_regime["TREND"].status == "HEALTHY"
        assert by_regime["TREND"].evidence_n == 60
        assert by_regime["TREND"].no_evidence is False
        assert by_regime["RANGE"].status == "DEGRADED"
        # untouched columns are honest empty cells
        for regime in ("HIGH_VOL", "SHOCK"):
            assert by_regime[regime].status == INSUFFICIENT_EVIDENCE
            assert by_regime[regime].no_evidence is True
            assert by_regime[regime].evidence_n == 0

    def test_no_family_name_inference(self) -> None:
        """A strategy with no rows anywhere gets all-empty cells — never a
        status guessed from its name/family."""
        matrix = build_health_matrix([], regimes=("TREND", "RANGE"))
        # no strategies discovered: no fabricated rows
        assert matrix.strategies == ()
        assert matrix.cells == ()

    def test_insufficient_sample_cell(self) -> None:
        matrix = build_health_matrix([_row(n=2)], min_evidence_n=5)
        cell = matrix.cells[0][0]
        assert cell.status == INSUFFICIENT_EVIDENCE
        assert cell.no_evidence is True

    def test_matrix_dict_shape(self) -> None:
        payload = health_view_payload([_row()])
        matrix = payload["regime_matrix"]
        assert matrix["regimes"] == list(REGIME_COLUMNS)
        assert matrix["rows"][0]["strategy"] == "Momentum"
        assert len(matrix["rows"][0]["cells"]) == len(REGIME_COLUMNS)
        assert all(cell["read_only"] for row in matrix["rows"] for cell in row["cells"])
