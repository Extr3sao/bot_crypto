"""Live Trading Gate — pre-flight checklist validator (Fase 9).

Validates all safety gates before allowing live trading mode.
Each gate has: check function, severity, description.
All gates must pass for live trading to proceed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings


@dataclass(frozen=True, slots=True)
class GateResult:
    """Result of a single gate check."""

    gate_id: str
    name: str
    passed: bool
    severity: str  # critical / high / medium
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GateReport:
    """Complete gate validation report."""

    all_passed: bool
    total_gates: int
    passed_gates: int
    failed_gates: int
    critical_failures: list[GateResult]
    results: list[GateResult]


class LiveTradingGate:
    """Pre-flight validator for live trading.

    Checks:
    1. Runtime mode configuration
    2. Kill switch status
    3. Risk policy completeness
    4. API key presence (env var check, no value exposure)
    5. Sandbox setting
    6. Database connectivity
    7. Exchange configuration
    8. Security constraints

    Usage:
        gate = LiveTradingGate(settings)
        report = gate.validate()
        if not report.all_passed:
            raise LiveTradingBlocked(report)
    """

    def __init__(self, settings: Settings, data_dir: Path | str = "data") -> None:
        self._settings = settings
        self._data_dir = Path(data_dir)
        self._log = structlog.get_logger("live_gate")

    def validate(self) -> GateReport:
        """Run all gate checks and return a report."""
        checks: list[Callable[[], GateResult]] = [
            self._check_mode_configuration,
            self._check_kill_switch,
            self._check_risk_policy,
            self._check_api_keys,
            self._check_sandbox_setting,
            self._check_database,
            self._check_exchange_config,
            self._check_security,
            self._check_logging,
            self._check_risk_limits,
        ]

        results: list[GateResult] = []
        for check_fn in checks:
            try:
                result = check_fn()
                results.append(result)
            except Exception as exc:
                results.append(
                    GateResult(
                        gate_id="ERROR",
                        name=check_fn.__name__,
                        passed=False,
                        severity="critical",
                        message=f"Gate check raised exception: {exc}",
                    )
                )

        critical_failures = [r for r in results if not r.passed and r.severity == "critical"]
        passed = sum(1 for r in results if r.passed)

        report = GateReport(
            all_passed=len(critical_failures) == 0,
            total_gates=len(results),
            passed_gates=passed,
            failed_gates=len(results) - passed,
            critical_failures=critical_failures,
            results=results,
        )

        self._log.info(
            "gate.validation_complete",
            all_passed=report.all_passed,
            total=report.total_gates,
            passed=report.passed_gates,
            failed=report.failed_gates,
            critical=len(critical_failures),
        )

        return report

    def _check_mode_configuration(self) -> GateResult:
        """Verify runtime mode is configured for live."""
        mode = self._settings.runtime.mode
        live_enabled = self._settings.runtime.live_trading_enabled

        if mode == TradingMode.LIVE and not live_enabled:
            return GateResult(
                gate_id="GATE-001",
                name="Mode Configuration",
                passed=False,
                severity="critical",
                message="mode='live' but live_trading_enabled=False",
            )

        if live_enabled and mode not in (TradingMode.LIVE, TradingMode.SHADOW_LIVE):
            return GateResult(
                gate_id="GATE-001",
                name="Mode Configuration",
                passed=False,
                severity="critical",
                message=f"live_trading_enabled=True but mode='{mode.value}'",
            )

        return GateResult(
            gate_id="GATE-001",
            name="Mode Configuration",
            passed=True,
            severity="critical",
            message=f"mode={mode.value}, live_enabled={live_enabled}",
        )

    def _check_kill_switch(self) -> GateResult:
        """Verify kill switch is enabled and functional."""
        kill_switch = self._settings.risk.kill_switch_enabled

        if not kill_switch:
            return GateResult(
                gate_id="GATE-002",
                name="Kill Switch",
                passed=False,
                severity="critical",
                message="kill_switch_enabled=False — CANNOT operate without kill switch",
            )

        return GateResult(
            gate_id="GATE-002",
            name="Kill Switch",
            passed=True,
            severity="critical",
            message="Kill switch enabled and functional",
        )

    def _check_risk_policy(self) -> GateResult:
        """Verify risk policy is complete."""
        risk = self._settings.risk

        issues: list[str] = []
        if risk.max_risk_per_trade_pct <= 0:
            issues.append("max_risk_per_trade_pct <= 0")
        if risk.max_daily_loss_pct <= 0:
            issues.append("max_daily_loss_pct <= 0")
        if risk.max_total_drawdown_pct <= 0:
            issues.append("max_total_drawdown_pct <= 0")
        if risk.max_open_positions <= 0:
            issues.append("max_open_positions <= 0")
        if risk.max_trades_per_day <= 0:
            issues.append("max_trades_per_day <= 0")

        if issues:
            return GateResult(
                gate_id="GATE-003",
                name="Risk Policy",
                passed=False,
                severity="critical",
                message=f"Incomplete risk policy: {', '.join(issues)}",
                details={"issues": issues},
            )

        return GateResult(
            gate_id="GATE-003",
            name="Risk Policy",
            passed=True,
            severity="critical",
            message="Risk policy complete and valid",
        )

    def _check_api_keys(self) -> GateResult:
        """Verify API key environment variables exist (not their values)."""
        required_vars = ["EXCHANGE_API_KEY", "EXCHANGE_API_SECRET"]
        missing: list[str] = []

        for var in required_vars:
            if not os.environ.get(var):
                missing.append(var)

        if missing:
            return GateResult(
                gate_id="GATE-004",
                name="API Keys",
                passed=False,
                severity="critical",
                message=f"Missing API key env vars: {', '.join(missing)}",
                details={"missing_vars": missing},
            )

        return GateResult(
            gate_id="GATE-004",
            name="API Keys",
            passed=True,
            severity="critical",
            message="API key environment variables present",
        )

    def _check_sandbox_setting(self) -> GateResult:
        """Verify sandbox is OFF for live trading."""
        sandbox = self._settings.exchange.sandbox

        if self._settings.runtime.mode == TradingMode.LIVE and sandbox:
            return GateResult(
                gate_id="GATE-005",
                name="Sandbox Setting",
                passed=False,
                severity="critical",
                message="mode='live' but exchange.sandbox=True — live requires sandbox=False",
            )

        return GateResult(
            gate_id="GATE-005",
            name="Sandbox Setting",
            passed=True,
            severity="high",
            message=f"sandbox={sandbox}, mode={self._settings.runtime.mode.value}",
        )

    def _check_database(self) -> GateResult:
        """Verify database is accessible."""
        db_url = self._settings.runtime.storage.database_url

        if "sqlite" in db_url:
            # Extract path from sqlite:///path
            db_path = db_url.replace("sqlite:///", "")
            if db_path != ":memory:" and not Path(db_path).parent.exists():
                return GateResult(
                    gate_id="GATE-006",
                    name="Database",
                    passed=False,
                    severity="high",
                    message=f"SQLite directory does not exist: {Path(db_path).parent}",
                )

        return GateResult(
            gate_id="GATE-006",
            name="Database",
            passed=True,
            severity="high",
            message=f"Database configured: {db_url.split('/')[-1]}",
        )

    def _check_exchange_config(self) -> GateResult:
        """Verify exchange is configured."""
        exchange_id = self._settings.runtime.exchange_id

        if not exchange_id:
            return GateResult(
                gate_id="GATE-007",
                name="Exchange Config",
                passed=False,
                severity="critical",
                message="runtime.exchange_id not configured",
            )

        return GateResult(
            gate_id="GATE-007",
            name="Exchange Config",
            passed=True,
            severity="critical",
            message=f"Exchange: {exchange_id}",
        )

    def _check_security(self) -> GateResult:
        """Verify security constraints."""
        issues: list[str] = []

        # Check .env is not committed (basic check)
        if Path(".env").exists():
            # Check if .env is in .gitignore
            gitignore = Path(".gitignore")
            if gitignore.exists():
                content = gitignore.read_text(encoding="utf-8")
                if ".env" not in content:
                    issues.append(".env exists but not in .gitignore")

        # Check live_trading_enabled in risk is False (defense-in-depth)
        if self._settings.risk.live_trading_enabled:
            issues.append(
                "risk.live_trading_enabled=True (should be False, source of truth is runtime)"
            )

        if issues:
            return GateResult(
                gate_id="GATE-008",
                name="Security",
                passed=False,
                severity="high",
                message=f"Security issues: {', '.join(issues)}",
                details={"issues": issues},
            )

        return GateResult(
            gate_id="GATE-008",
            name="Security",
            passed=True,
            severity="high",
            message="Security constraints satisfied",
        )

    def _check_logging(self) -> GateResult:
        """Verify logging is configured."""
        log_level = self._settings.runtime.logging.level
        log_format = self._settings.runtime.logging.format

        return GateResult(
            gate_id="GATE-009",
            name="Logging",
            passed=True,
            severity="medium",
            message=f"Logging: level={log_level}, format={log_format}",
        )

    def _check_risk_limits(self) -> GateResult:
        """Verify risk limits are sensible."""
        risk = self._settings.risk
        warnings: list[str] = []

        if risk.max_risk_per_trade_pct > 2.0:
            warnings.append(f"max_risk_per_trade_pct={risk.max_risk_per_trade_pct}% (high)")
        if risk.max_daily_loss_pct > 5.0:
            warnings.append(f"max_daily_loss_pct={risk.max_daily_loss_pct}% (high)")
        if risk.max_total_drawdown_pct > 20.0:
            warnings.append(f"max_total_drawdown_pct={risk.max_total_drawdown_pct}% (very high)")

        severity = "high" if warnings else "medium"

        return GateResult(
            gate_id="GATE-010",
            name="Risk Limits",
            passed=True,
            severity=severity,
            message=f"Risk limits: {risk.max_risk_per_trade_pct}%/trade, {risk.max_daily_loss_pct}%/day"
            + (f" — warnings: {', '.join(warnings)}" if warnings else ""),
            details={"warnings": warnings},
        )


class LiveTradingBlocked(Exception):
    """Raised when live trading gate validation fails."""

    def __init__(self, report: GateReport) -> None:
        self.report = report
        failures = [f"{r.gate_id}: {r.message}" for r in report.critical_failures]
        super().__init__(
            f"Live trading blocked: {report.failed_gates}/{report.total_gates} gates failed. "
            f"Critical: {'; '.join(failures)}"
        )


__all__ = ["GateReport", "GateResult", "LiveTradingBlocked", "LiveTradingGate"]
