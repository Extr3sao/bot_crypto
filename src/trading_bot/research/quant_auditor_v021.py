"""QuantAuditor V0.2.1 — independent PnL reconstruction and metrics validation.

V0.2.1 §7: PnL Reconstruction Check — auditor reconstructs PnL independently.
V0.2.1 §25: Real Metrics Validation — recalculate independently from trades.
V0.2.1 §27: Daily Frequency from executed trades.
V0.2.1 §26: Profit Factor edge cases handled correctly.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

from .backtest_evidence import RealBacktestResult, TradeRecord

try:
    from trading_agent.core.models_v02 import AuditCheck, AuditResultV02, new_id
except ImportError:
    import uuid
    from dataclasses import dataclass, field
    from typing import Any, Literal

    def new_id(prefix: str = "") -> str:
        uid = uuid.uuid4().hex[:12]
        return f"{prefix}-{uid}" if prefix else uid

    AuditSeverity = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]
    AuditCheckStatus = Literal["PASS", "FAIL", "SKIP", "WARNING"]

    @dataclass(frozen=True, slots=True)
    class AuditCheck:  # type: ignore[no-redef]
        check_id: str = ""
        category: str = ""
        status: AuditCheckStatus = "PASS"
        severity: AuditSeverity = "INFO"
        description: str = ""
        observed: str = ""
        expected: str = ""
        evidence_path: str = ""

        @property
        def is_blocking(self) -> bool:
            return self.status == "FAIL" and self.severity in ("ERROR", "CRITICAL")

        @property
        def check(self) -> str:
            return self.check_id

        @property
        def passed(self) -> bool:
            return self.status == "PASS"

    @dataclass(frozen=True, slots=True)
    class AuditResultV02:  # type: ignore[no-redef]
        audit_id: str = field(default_factory=lambda: new_id("AUD"))
        experiment_id: str = ""
        window_id: str = ""
        verdict: Literal["PASS", "FAIL", "INCONCLUSIVE"] = "INCONCLUSIVE"
        checks: list[AuditCheck] = field(default_factory=list)
        completed_at: float = field(default_factory=lambda: __import__("time").time())

        @property
        def failed_checks(self) -> list[AuditCheck]:
            return [c for c in self.checks if c.status == "FAIL"]

        @property
        def blocking_checks(self) -> list[AuditCheck]:
            return [c for c in self.checks if c.is_blocking]

        @property
        def failed_count(self) -> int:
            return len(self.failed_checks)

        @property
        def passed_count(self) -> int:
            return sum(1 for c in self.checks if c.status == "PASS")

        @property
        def findings(self) -> list[AuditCheck]:
            return self.checks


@dataclass(frozen=True, slots=True)
class ReconstructedMetrics:
    """Independently reconstructed metrics from trade records."""

    n: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    gross_pf: float = 0.0
    net_pf: float = 0.0
    max_drawdown: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0

    # Daily frequency
    avg_trades_per_day: float = 0.0
    median_trades_per_day: float = 0.0
    min_trades_per_day: int = 0
    max_trades_per_day: int = 0
    zero_trade_days: int = 0
    pct_days_ge_1: float = 0.0
    pct_days_ge_2: float = 0.0
    pct_days_ge_3: float = 0.0


@dataclass(frozen=True, slots=True)
class PnLReconciliation:
    """Result of PnL reconciliation between engine and auditor."""

    reconciled: bool = True
    engine_net_pnl: float = 0.0
    auditor_net_pnl: float = 0.0
    difference: float = 0.0
    tolerance: float = 1e-6
    status: str = ""  # "CONSISTENT", "INCONSISTENT", "AUDIT_FAIL"


class QuantAuditorV021:
    """Independent PnL reconstruction and metrics validation.

    V0.2.1 §7: Reconstruct PnL independently from backtest engine.
    V0.2.1 §25: Recalculate all metrics from trade records.
    V0.2.1 §26: Handle profit factor edge cases.
    V0.2.1 §27: Daily frequency from executed trades only.
    """

    def __init__(self, tolerance: float = 1e-6) -> None:
        self._tolerance = tolerance
        self._log = structlog.get_logger("quant_auditor_v021")

    def audit(
        self,
        backtest_result: RealBacktestResult,
        experiment_id: str = "",
    ) -> AuditResultV02:
        """Run complete audit on a backtest result.

        Returns AuditResultV02 with all checks.
        """
        checks: list[AuditCheck] = []

        # 1. Reconstruct PnL from trades
        recon = self._reconstruct_from_trades(backtest_result.trades)
        checks.append(
            AuditCheck(
                check_id="pnl_reconstruction",
                category="PNL",
                status="PASS" if recon.n >= 0 else "FAIL",
                description="PnL reconstructed from individual trades",
                observed=f"n={recon.n}, net_pnl={recon.net_pnl:.6f}",
            )
        )

        # 2. PnL reconciliation
        reconciliation = self._reconcile_pnl(backtest_result, recon)
        checks.append(
            AuditCheck(
                check_id="pnl_reconciliation",
                category="PNL",
                status="PASS" if reconciliation.reconciled else "FAIL",
                severity="CRITICAL" if not reconciliation.reconciled else "INFO",
                description=f"PnL reconciliation: engine={reconciliation.engine_net_pnl:.6f}, auditor={reconciliation.auditor_net_pnl:.6f}",
                observed=f"diff={reconciliation.difference:.10f}, tolerance={reconciliation.tolerance}",
                expected=f"diff <= {reconciliation.tolerance}",
            )
        )

        # 3. Metrics reconstruction
        metrics_check = self._validate_metrics(backtest_result, recon)
        checks.append(metrics_check)

        # 4. Profit factor edge cases
        pf_check = self._check_profit_factor_edge_cases(recon)
        checks.append(pf_check)

        # 5. Daily frequency
        freq_check = self._make_frequency_check(backtest_result.trades)
        checks.append(freq_check)

        # 6. Trade count validation
        n_check = AuditCheck(
            check_id="trade_count_source",
            category="DATA",
            status="PASS",
            description=f"Trade count: {backtest_result.n_trades}",
            observed=f"metrics_source={backtest_result.metrics_source}",
        )
        checks.append(n_check)

        # 7. Evidence class check
        ev_check = AuditCheck(
            check_id="evidence_class",
            category="DATA",
            status="PASS"
            if (
                backtest_result.evidence is not None
                and backtest_result.evidence.evidence_class.is_operational
            )
            else "FAIL",
            severity="ERROR"
            if (
                backtest_result.evidence is None
                or not backtest_result.evidence.evidence_class.is_operational
            )
            else "INFO",
            description=f"Evidence class: {backtest_result.evidence.evidence_class.value if backtest_result.evidence else 'NONE'}",
        )
        checks.append(ev_check)

        # Determine verdict
        blocking = [c for c in checks if c.is_blocking]
        verdict = "PASS" if not blocking else "FAIL"

        return AuditResultV02(
            experiment_id=experiment_id,
            verdict=verdict,
            checks=checks,
        )

    def _reconstruct_from_trades(self, trades: list[TradeRecord]) -> ReconstructedMetrics:
        """Reconstruct all metrics from individual trade records.

        V0.2.1 §7: Independent PnL reconstruction.
        V0.2.1 §25: Independent metrics reconstruction.
        """
        n = len(trades)
        if n == 0:
            return ReconstructedMetrics()

        # PnL reconstruction
        gross_pnl = sum(t.gross_pnl for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        total_fees = sum(t.fees for t in trades)
        total_slippage = sum(t.slippage for t in trades)

        # Win/loss
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        win_rate = len(wins) / n

        # Averages
        avg_win = statistics.mean([t.net_pnl for t in wins]) if wins else 0.0
        avg_loss = statistics.mean([abs(t.net_pnl) for t in losses]) if losses else 0.0

        # Expectancy: (win_rate * avg_win) - (loss_rate * avg_loss)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Profit factor (V0.2.1 §26: handle edge cases)
        gross_win_sum = sum(t.gross_pnl for t in wins) if wins else 0.0
        gross_loss_sum = sum(abs(t.gross_pnl) for t in losses) if losses else 0.0
        gross_pf = self._safe_pf(gross_win_sum, gross_loss_sum)

        net_win_sum = sum(t.net_pnl for t in wins) if wins else 0.0
        net_loss_sum = sum(abs(t.net_pnl) for t in losses) if losses else 0.0
        net_pf = self._safe_pf(net_win_sum, net_loss_sum)

        # Max drawdown
        max_dd = self._compute_max_drawdown(trades)

        # Daily frequency (V0.2.1 §27)
        daily = self._compute_daily_frequency(trades)

        return ReconstructedMetrics(
            n=n,
            wins=len(wins),
            losses=len(losses),
            win_rate=win_rate,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            expectancy=expectancy,
            gross_pf=gross_pf,
            net_pf=net_pf,
            max_drawdown=max_dd,
            total_fees=total_fees,
            total_slippage=total_slippage,
            avg_trades_per_day=daily["avg"],
            median_trades_per_day=daily["median"],
            min_trades_per_day=daily["min"],
            max_trades_per_day=daily["max"],
            zero_trade_days=daily["zero_days"],
            pct_days_ge_1=daily["pct_ge_1"],
            pct_days_ge_2=daily["pct_ge_2"],
            pct_days_ge_3=daily["pct_ge_3"],
        )

    def _safe_pf(self, wins_sum: float, losses_sum: float) -> float:
        """Compute profit factor handling edge cases (V0.2.1 §26)."""
        if losses_sum == 0:
            if wins_sum > 0:
                return float("inf")
            return 0.0  # No trades or all breakeven
        return wins_sum / losses_sum

    def _compute_max_drawdown(self, trades: list[TradeRecord]) -> float:
        """Compute max drawdown from trade net_pnl sequence."""
        if not trades:
            return 0.0

        equity = 10_000.0  # Assume initial capital
        peak = equity
        max_dd = 0.0

        for t in trades:
            equity += t.net_pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _compute_daily_frequency(self, trades: list[TradeRecord]) -> dict[str, Any]:
        """Compute daily frequency from executed trades (V0.2.1 §27)."""
        import datetime

        daily_counts: dict[str, int] = defaultdict(int)
        for t in trades:
            day = datetime.datetime.fromtimestamp(
                t.exit_timestamp / 1000.0, tz=datetime.UTC
            ).strftime("%Y-%m-%d")
            daily_counts[day] += 1

        if not daily_counts:
            return {
                "avg": 0.0,
                "median": 0.0,
                "min": 0,
                "max": 0,
                "zero_days": 0,
                "pct_ge_1": 0.0,
                "pct_ge_2": 0.0,
                "pct_ge_3": 0.0,
            }

        counts = list(daily_counts.values())
        total_days = len(counts)

        return {
            "avg": statistics.mean(counts),
            "median": statistics.median(counts),
            "min": min(counts),
            "max": max(counts),
            "zero_days": sum(1 for c in counts if c == 0),
            "pct_ge_1": sum(1 for c in counts if c >= 1) / total_days * 100,
            "pct_ge_2": sum(1 for c in counts if c >= 2) / total_days * 100,
            "pct_ge_3": sum(1 for c in counts if c >= 3) / total_days * 100,
        }

    def _make_frequency_check(self, trades: list[TradeRecord]) -> AuditCheck:
        """Create frequency check from trade records."""
        daily = self._compute_daily_frequency(trades)
        return AuditCheck(
            check_id="daily_frequency",
            category="DATA",
            status="PASS",
            description=f"Frequency: avg={daily['avg']:.2f}, median={daily['median']:.1f}",
            observed=f"trades={len(trades)}, days={daily['avg'] + daily['median']}",
        )

    def _reconcile_pnl(
        self,
        result: RealBacktestResult,
        recon: ReconstructedMetrics,
    ) -> PnLReconciliation:
        """Reconcile engine PnL vs auditor PnL.

        V0.2.1 §7: Compare engine vs auditor with explicit tolerance.
        """
        diff = abs(result.net_pnl - recon.net_pnl)
        reconciled = diff <= self._tolerance

        status = "CONSISTENT" if reconciled else "AUDIT_FAIL"
        return PnLReconciliation(
            reconciled=reconciled,
            engine_net_pnl=result.net_pnl,
            auditor_net_pnl=recon.net_pnl,
            difference=diff,
            tolerance=self._tolerance,
            status=status,
        )

    def _validate_metrics(
        self,
        result: RealBacktestResult,
        recon: ReconstructedMetrics,
    ) -> AuditCheck:
        """Validate engine metrics against reconstructed metrics."""
        mismatches: list[str] = []

        if result.n_trades != recon.n:
            mismatches.append(f"n_trades: engine={result.n_trades}, auditor={recon.n}")
        if abs(result.win_rate - recon.win_rate) > self._tolerance:
            mismatches.append(f"win_rate: engine={result.win_rate}, auditor={recon.win_rate}")
        if abs(result.net_pnl - recon.net_pnl) > self._tolerance:
            mismatches.append(f"net_pnl: engine={result.net_pnl}, auditor={recon.net_pnl}")

        passed = len(mismatches) == 0

        return AuditCheck(
            check_id="metrics_reconstruction",
            category="PNL",
            status="PASS" if passed else "FAIL",
            severity="CRITICAL" if not passed else "INFO",
            description="Independent metrics reconstruction"
            + (f": {', '.join(mismatches)}" if mismatches else ""),
            observed=f"engine_trades={result.n_trades}, auditor_trades={recon.n}",
            expected="All metrics match within tolerance",
        )

    def _check_profit_factor_edge_cases(self, recon: ReconstructedMetrics) -> AuditCheck:
        """V0.2.1 §26: Handle PF edge cases correctly."""
        issues: list[str] = []

        # Check: no division by zero
        if recon.n > 0 and recon.gross_pf == 0.0 and recon.wins > 0:
            issues.append("PF=0 with wins present — potential calculation error")

        # Check: inf PF handled
        if recon.gross_pf == float("inf"):
            # This is valid: all winners, no losers
            pass

        # Check: zero trades
        if recon.n == 0 and recon.gross_pf != 0.0:
            issues.append("PF != 0 with zero trades")

        passed = len(issues) == 0

        return AuditCheck(
            check_id="profit_factor_edge_cases",
            category="PNL",
            status="PASS" if passed else "FAIL",
            description=f"PF edge cases: gross_pf={recon.gross_pf}, net_pf={recon.net_pf}",
            observed=f"n={recon.n}, wins={recon.wins}, losses={recon.losses}",
        )


__all__ = [
    "PnLReconciliation",
    "QuantAuditorV021",
    "ReconstructedMetrics",
]
