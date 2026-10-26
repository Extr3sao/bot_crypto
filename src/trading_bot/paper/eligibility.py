"""Evidence-only strategy eligibility report for real-data PAPER (G-7).

The admission ledger remains the sole authority.  This module does not enable,
promote or execute anything: it asks the canonical ``StrategyRegistry`` and
``StrategyRouter`` what the committed ledger would select for an actual
``AssetContext`` and records **every** verdict, including the refusals.

A strategy can only appear as ``SELECTED`` here when the committed ledger says
it is ``PAPER_CANDIDATE``/``PAPER_ACTIVE`` and admitted.  If the ledger admits
nothing, the report must say so; it must not invent a candidate to make the
vertical look complete.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_bot.autonomous.admission_ledger import AdmissionLedger
from trading_bot.autonomous.strategy_state import StrategyRegistry
from trading_bot.market_data.types import OHLCV
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.router_gates import RouterGates
from trading_bot.research.strategy_router import StrategyRouter

__all__ = ["EligibilityReport", "bars_fingerprint", "evaluate_eligibility"]


def bars_fingerprint(bars: list[OHLCV]) -> str:
    payload = json.dumps(
        [
            [
                b.symbol,
                int(b.timestamp),
                float(b.open),
                float(b.high),
                float(b.low),
                float(b.close),
                float(b.volume),
            ]
            for b in bars
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class EligibilityReport:
    timeframe: str
    decision_time_ms: int
    rows: tuple[dict[str, Any], ...]
    selected: tuple[str, ...]
    counts: dict[str, int]
    registry: dict[str, Any]
    router_traces: dict[str, list[str]]
    context_errors: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "decision_time_ms": self.decision_time_ms,
            "rows": list(self.rows),
            "selected": list(self.selected),
            "counts": dict(self.counts),
            "registry": dict(self.registry),
            "router_traces": {key: list(value) for key, value in self.router_traces.items()},
            "context_errors": list(self.context_errors),
        }


def evaluate_eligibility(
    *,
    ledger_path: Path | str,
    assets: list[str] | tuple[str, ...],
    timeframe: str,
    bars_by_symbol: dict[str, list[OHLCV]],
    decision_time_ms: int,
) -> EligibilityReport:
    """Evaluate the committed ledger against real PIT bars.

    ``bars_by_symbol`` keys are ``BASE/USDT`` symbols.  The function never
    mutates the ledger, the registry or the bars.
    """
    ledger = AdmissionLedger.load(Path(ledger_path))
    registry = StrategyRegistry.from_ledger(ledger, assets=list(assets))
    strategy_map = registry.strategy_map(timeframe)
    router = StrategyRouter(gates=RouterGates(timeframe=timeframe))
    context_registry = CryptoAssetAgentRegistry()

    rows: list[dict[str, Any]] = []
    selected: list[str] = []
    traces: dict[str, list[str]] = {}
    context_errors: list[dict[str, str]] = []

    for symbol in sorted(bars_by_symbol):
        asset = symbol.split("/")[0]
        bars = [bar for bar in bars_by_symbol[symbol] if int(bar.timestamp) <= decision_time_ms]
        try:
            context = context_registry.build_context(
                asset,
                bars,
                decision_time_ms,
                data_fingerprint=bars_fingerprint(bars),
            )
            selection = router.select_eligible_strategies(
                context,
                context.market_regime,
                strategy_map,
            )
            traces[symbol] = list(selection.trace)
            routed_by_id = {item.strategy_id: item for item in selection.routed}
        except Exception as exc:
            context_errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
            traces[symbol] = [f"context_error: {type(exc).__name__}: {exc}"]
            routed_by_id = {}
            context = None

        for strategy_id in sorted(strategy_map):
            record = registry.record(strategy_id)
            if record is None:
                continue
            routed = routed_by_id.get(strategy_id)
            if routed is None:
                verdict = "NOT_APPLICABLE"
                reason = "context could not be built at the decision instant"
                if context is not None:
                    reason = "router returned no verdict for this strategy"
            else:
                verdict = routed.verdict
                reason = routed.reason or "SELECTED"
            is_selected = verdict == "SELECTED"
            if is_selected:
                selected.append(f"{asset}:{strategy_id}")
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "version": record.version,
                    "family": record.family,
                    "asset": asset,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "regime": getattr(context, "market_regime", None),
                    "validation_status": record.admission_status.value,
                    "admitted_for_paper": record.admitted_for_paper,
                    "expected_gross_edge_bps": record.expected_gross_edge_bps,
                    "router_verdict": verdict,
                    "eligibility_reason": reason,
                    "selected": is_selected,
                    "evidence_ids": list(record.evidence_ids),
                }
            )

    counts: dict[str, int] = {}
    for row in rows:
        verdict = str(row["router_verdict"])
        counts[verdict] = counts.get(verdict, 0) + 1

    return EligibilityReport(
        timeframe=timeframe,
        decision_time_ms=int(decision_time_ms),
        rows=tuple(rows),
        selected=tuple(sorted(selected)),
        counts=counts,
        registry=registry.as_dict(),
        router_traces=traces,
        context_errors=tuple(context_errors),
    )
