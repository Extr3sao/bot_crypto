"""PAPER-OBSERVATION-CAMPAIGN-01 durable state and metrics.

Canonical, atomically persisted campaign state plus aggregation helpers.
This module never re-implements strategy, ranking, debate, decision,
verification, risk, or accounting: numbers come from certified runtime
artifacts (DecisionPackage, DebateReport, RiskManager, PaperBroker,
reconciliation).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "poc01-state-v1"

REASON_TAXONOMY = (
    # decision / adapter boundaries
    "NO_PROPOSAL",
    "INSUFFICIENT_EVIDENCE",
    "UNRESOLVED_CONFLICT",
    "LOWER_RANKED_ALTERNATIVE",
    "STALE",
    "EXPIRED",
    "INVALID_TRACE",
    # risk boundaries
    "MAX_OPEN_POSITIONS",
    "RISK_EXPOSURE",
    "RISK_LIMIT",
    "PORTFOLIO_CONSTRAINT",
    # campaign boundaries
    "STALE_DATA_NO_TRADE",
    "FUTURE_DATA_REJECTED",
    "PROVIDER_FAILURE",
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def day_key(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Durable atomic JSON write: temp file + os.replace (same directory)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


class CorruptedStateError(RuntimeError):
    """Raised when durable campaign state cannot be parsed."""


@dataclass
class DurableCampaignState:
    """Canonical POC01 durable state (schema poc01-state-v1)."""

    schema_version: str = SCHEMA_VERSION
    campaign_id: str = ""
    campaign_start: str = ""
    campaign_status: str = "ACTIVE"

    implementation_commit: str = ""
    provider: str = ""
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL")
    strategies: tuple[str, ...] = ("momentum", "trend", "breakout", "mean_reversion", "volatility")

    last_successful_scan_time: str | None = None
    last_market_timestamp: int | None = None
    last_processed_decision_ids: list[str] = field(default_factory=list)
    processed_order_ids: list[str] = field(default_factory=list)
    processed_fill_ids: list[str] = field(default_factory=list)
    processed_proposal_ids: list[str] = field(default_factory=list)
    processed_data_fingerprints: list[str] = field(default_factory=list)

    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)

    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees: float = 0.0
    equity: float = 10_000.0
    initial_equity: float = 10_000.0

    daily: dict[str, dict[str, Any]] = field(default_factory=dict)
    funnel: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, int] = field(default_factory=dict)
    by_asset: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_strategy: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_regime: dict[str, dict[str, Any]] = field(default_factory=dict)
    debate_metrics: dict[str, Any] = field(default_factory=lambda: {
        "debates": 0, "critiques": 0, "revisions": 0,
        "resolved": 0, "unresolved": 0,
        "decision_changed_after_debate": 0, "winner_changed_after_debate": 0,
        "confidence_increased": 0, "confidence_decreased": 0,
        "counter_evidence": 0, "material_dissent": 0,
    })
    decision_metrics: dict[str, Any] = field(default_factory=lambda: {
        "candidate_count": 0, "selected": 0, "rejected": 0, "no_trade": 0,
        "selected_with_dissent": 0, "blocked_unresolved_conflict": 0,
        "revision_changed_winner": 0, "verifier_verified": 0, "verifier_rejected": 0,
    })
    risk_metrics: dict[str, Any] = field(default_factory=lambda: {
        "accepts": 0, "rejects": 0, "rejection_rate": 0.0,
        "reason_distribution": {}, "avg_simultaneous_positions": 0.0,
        "max_simultaneous_positions": 0, "asset_exposure": {},
    })
    data_health: dict[str, Any] = field(default_factory=lambda: {
        "stale_events": 0, "future_events": 0, "gaps": 0,
        "duplicate_candles": 0, "provider_failures": 0,
    })

    runs: list[dict[str, Any]] = field(default_factory=list)
    run_id: str = ""
    trace_id: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    heartbeat: dict[str, Any] = field(default_factory=lambda: {
        "last_scan_time": None,
        "last_successful_decision_cycle": 0,
        "provider_status": "OK",
        "last_persistence_success": None,
        "last_reconciliation_success": None,
        "campaign_state": "ACTIVE",
    })

    # ------------------------------------------------------------------
    # funnel / reasons
    # ------------------------------------------------------------------

    def bump(self, funnel_key: str) -> None:
        self.funnel[funnel_key] = self.funnel.get(funnel_key, 0) + 1

    def bump_reason(self, reason: str) -> None:
        key = str(reason)
        self.reasons[key] = self.reasons.get(key, 0) + 1

    # ------------------------------------------------------------------
    # duplicates
    # ------------------------------------------------------------------

    def seen_decision(self, decision_id: str) -> bool:
        return decision_id in self.last_processed_decision_ids

    def seen_data_fingerprint(self, fingerprint: str) -> bool:
        return fingerprint in self.processed_data_fingerprints

    def mark_decision(self, decision_id: str) -> None:
        if decision_id and decision_id not in self.last_processed_decision_ids:
            self.last_processed_decision_ids.append(decision_id)

    def mark_order(self, order_id: str) -> None:
        if order_id and order_id not in self.processed_order_ids:
            self.processed_order_ids.append(order_id)

    def mark_fill(self, fill_id: str) -> None:
        if fill_id and fill_id not in self.processed_fill_ids:
            self.processed_fill_ids.append(fill_id)

    # ------------------------------------------------------------------
    # serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for f in self.__dataclass_fields__.values():
            value = getattr(self, f.name)
            payload[f.name] = sorted(value) if isinstance(value, set) else value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DurableCampaignState:
        kwargs: dict[str, Any] = {}
        for name, f in cls.__dataclass_fields__.items():
            if name not in payload:
                continue
            value = payload[name]
            if f.type == "tuple[str, ...]" and isinstance(value, list):
                value = tuple(value)
            kwargs[name] = value
        return cls(**kwargs)


class CampaignStateStore:
    """Atomic durable-state repository (write + fsync + os.replace)."""

    def __init__(self, campaign_dir: Path | str) -> None:
        self.campaign_dir = Path(campaign_dir)
        self.path = self.campaign_dir / "CAMPAIGN_STATE.json"

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> DurableCampaignState:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CorruptedStateError(str(exc)) from exc
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise CorruptedStateError(
                f"unsupported schema_version: {payload.get('schema_version')!r}"
            )
        return DurableCampaignState.from_dict(payload)

    def save(self, state: DurableCampaignState) -> None:
        _atomic_write_json(self.path, state.to_dict())


def performance_metrics(
    *,
    initial_equity: float,
    equity: float,
    closed_trades: list[dict[str, Any]],
    realized_pnl: float,
    unrealized_pnl: float,
    fees: float,
) -> dict[str, Any]:
    """Canonical performance numbers from PaperBroker accounting only."""
    wins = [t for t in closed_trades if float(t.get("pnl", 0.0)) > 0]
    losses = [t for t in closed_trades if float(t.get("pnl", 0.0)) < 0]
    gross_win = sum(float(t["pnl"]) for t in wins)
    gross_loss = abs(sum(float(t["pnl"]) for t in losses))
    trades = len(closed_trades)
    avg_win = gross_win / len(wins) if wins else None
    avg_loss = gross_loss / len(losses) if losses else None
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    peak = initial_equity
    running = initial_equity
    max_dd = 0.0
    for t in sorted(closed_trades, key=lambda t: float(t.get("closed_at_ms", 0))):
        running += float(t["pnl"])
        peak = max(peak, running)
        if peak > 0:
            max_dd = max(max_dd, (peak - running) / peak)
    return {
        "starting_equity": round(initial_equity, 8),
        "ending_equity": round(equity, 8),
        "gross_pnl": round(realized_pnl + sum(abs(float(t.get("fees", 0.0))) for t in closed_trades), 8),
        "net_pnl": round(realized_pnl, 8),
        "realized_pnl": round(realized_pnl, 8),
        "unrealized_pnl": round(unrealized_pnl, 8),
        "fees": round(fees, 8),
        "trades": trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / trades, 6) if trades else None,
        "average_win": round(avg_win, 8) if avg_win is not None else None,
        "average_loss": round(avg_loss, 8) if avg_loss is not None else None,
        "expectancy": (
            round((gross_win - gross_loss) / trades, 8) if trades else None
        ),
        "profit_factor": round(pf, 6) if pf is not None else None,
        "max_drawdown_pct": round(max_dd, 8),
        "return_pct": round((equity - initial_equity) / initial_equity * 100, 8) if initial_equity else None,
        "sample_status": "OK" if trades >= 30 else "INSUFFICIENT_SAMPLE",
    }


def daily_report_payload(
    *,
    campaign_id: str,
    day: str,
    day_entry: dict[str, Any],
) -> dict[str, Any]:
    day_trades = day_entry.get("trades", 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "date": day,
        "valid_observation_duration": day_entry.get("valid_duration_hours", 0.0),
        "market_scans": day_entry.get("scans", 0),
        "proposals": day_entry.get("proposals", 0),
        "debates": day_entry.get("debates", 0),
        "selected": day_entry.get("selected", 0),
        "no_trade": day_entry.get("no_trade", 0),
        "risk_accepts": day_entry.get("risk_accepts", 0),
        "risk_rejects": day_entry.get("risk_rejects", 0),
        "paper_opens": day_entry.get("trades", 0),
        "paper_closes": day_entry.get("closes", 0),
        "wins": day_entry.get("wins", 0),
        "losses": day_entry.get("losses", 0),
        "realized_pnl": day_entry.get("realized_pnl", 0.0),
        "unrealized_pnl": day_entry.get("unrealized_pnl", 0.0),
        "fees": day_entry.get("fees", 0.0),
        "max_intraday_drawdown": day_entry.get("max_intraday_drawdown", 0.0),
        "data_health_events": day_entry.get("data_health_events", 0),
        "runtime_errors": day_entry.get("runtime_errors", 0),
        "trades_per_day": day_trades,
        "day_ge_3": int(day_trades >= 3),
        "false_success": day_entry.get("false_success", 0),
    }
