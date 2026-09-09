"""POC02-R2 natural runtime smoke (TRACK F, MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01).

Runs the ARBITRATED composition (`_proposal_set(arbitrate=True)`) against live
PUBLIC binanceusdm bars OUTSIDE the active POC02 campaign: a separate run
identity, no campaign artifacts touched, no Risk/PaperBroker state shared with
POC02, LIVE_CALLS stays 0 (public REST only, PAPER only).

Purpose: prove that under the repaired composition a valid natural case can
reach candidate -> arbitration -> critique -> decision -> verifier -> Risk
without structural deadlock. Natural outcomes are reported HONELY: if no valid
signal exists in the scanned window, the script reports
NATURAL_CASES_TO_RISK=0 and the deterministic known-valid fixture
(``--fixture``) provides secondary proof instead. Nothing is fabricated.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.config.runtime import TradingMode  # noqa: E402
from trading_bot.demo.paper_multi_agent import (  # noqa: E402
    DecisionToCandidateAdapter,
    _proposal_set,
)
from trading_bot.market_data.fake import build_demo_settings  # noqa: E402
from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.multi_agent.contracts import TradeDirection  # noqa: E402
from trading_bot.multi_agent.decision import DecisionEngine  # noqa: E402
from trading_bot.risk.manager import RiskManager  # noqa: E402
from trading_bot.strategies.types import Signal  # noqa: E402

PAPER_ONLY_NOTICE = {
    "MODE": "PAPER",
    "MARKET_DATA_PROVIDER": "binanceusdm (public REST OHLCV, no credentials)",
    "LIVE_CALLS_REQUIRED": 0,
}


def _fetch_public_bars(assets: tuple[str, ...], limit: int = 120) -> dict[str, list[OHLCV]]:
    """PUBLIC binanceusdm bars only (same authority as the POC02 runtime)."""
    import ccxt

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        bars: dict[str, list[OHLCV]] = {}
        for asset in assets:
            symbol = f"{asset}/USDT:USDT"
            rows = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=limit)
            bars[asset] = [
                OHLCV(
                    symbol=symbol,
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
            ]
        return bars
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()


def _fixture_bars(asset: str, *, n: int = 60) -> list[OHLCV]:
    """Deterministic strongly-trending fixture (secondary proof path)."""
    symbol = f"{asset}/USDT"
    start = 1_788_000_000_000
    values = [100.0 + i * 0.5 for i in range(n)]
    return [
        OHLCV(
            symbol=symbol,
            timestamp=start + i * 300_000,
            open=v,
            high=v + 0.5,
            low=v - 0.5,
            close=v,
            volume=1_000.0,
        )
        for i, v in enumerate(values)
    ]


def run_one_window(
    *,
    asset: str,
    bars: list[OHLCV],
    run_id: str,
    risk: RiskManager,
) -> dict[str, Any]:
    """One natural window through arbitration -> critique -> decision -> Risk."""
    latest_ms = bars[-1].timestamp
    decision_time = datetime.fromtimestamp(latest_ms / 1000, tz=UTC)
    proposals, evidence, assessments, board, reports, prices = _proposal_set(
        asset=asset,
        bars=bars,
        now=decision_time,
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        directions=("LONG", "SHORT"),
        arbitrate=True,
    )
    groups = getattr(board, "arbitration_groups", ())
    snapshot = board.snapshot()
    package = DecisionEngine(run_id=run_id).decide(
        snapshot=snapshot,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        assessments=assessments,
        now=decision_time,
    )
    adapter = DecisionToCandidateAdapter()
    candidate = adapter.adapt(
        package,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        now=decision_time,
        prices=prices,
        snapshot=snapshot,
    )
    window: dict[str, Any] = {
        "asset": asset,
        "decision_time": decision_time.isoformat(),
        "run_id": run_id,
        "groups": [g.to_dict() for g in groups],
        "proposals_on_board": len(snapshot.opportunities),
        "decision_outcome": package.outcome.value,
        "selected_candidate_id": package.selected_candidate_id,
        "verifier_verdict": None,
        "reached_risk": False,
        "risk_verdict": None,
    }
    if candidate is None:
        return window
    verification = adapter.verifier.verify(
        package,
        proposals=proposals,
        evidence_registry=evidence,
        now=decision_time,
        reports=reports,
        snapshot=snapshot,
    )
    window["verifier_verdict"] = verification.verdict.value
    if not verification.passed:
        return window
    signal = Signal(
        symbol=f"{asset}/USDT",
        side="buy" if candidate.direction is TradeDirection.LONG else "sell",
        strategy_name=candidate.candidate.strategy_id,
        timeframe="5m",
        confidence=float(candidate.candidate.score),
        price=prices[asset],
        stop_loss_pct=None,
        take_profit_pct=None,
        metadata={"run_id": run_id, "entry_reason": "R2_SMOKE_ARBITRATED"},
    )
    check = risk.check_signal(signal)
    window["reached_risk"] = True
    window["risk_verdict"] = "ACCEPT" if check.approved else f"REJECT:{check.blocked_by}"
    return window


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--fixture", action="store_true", help="deterministic fixture instead of public bars")
    parser.add_argument("--out", default=str(ROOT / "reports" / "poc02-r2-smoke"))
    args = parser.parse_args()

    assets = tuple(a.strip().upper() for a in args.assets.split(",") if a.strip())
    run_id = f"poc02r2-smoke-{int(time.time() * 1000)}"
    settings = build_demo_settings(
        pairs=[(f"{a}/USDT", True) for a in assets], mode="paper", kill_switch_enabled=True
    )
    if settings.runtime.mode is not TradingMode.PAPER or settings.risk.live_trading_enabled:
        raise SystemExit("smoke safety gate failed: PAPER mode required")
    risk = RiskManager(risk=settings.risk.model_copy(update={"max_open_positions": 1}), equity=10_000.0)
    windows: list[dict[str, Any]] = []

    if args.fixture:
        bars_by_asset = {asset: _fixture_bars(asset) for asset in assets}
        source = "deterministic-fixture"
    else:
        bars_by_asset = _fetch_public_bars(assets)
        source = "binanceusdm-public-5m"

    for asset in assets:
        bars = bars_by_asset[asset]
        if len(bars) < 40:
            continue
        windows.append(
            run_one_window(asset=asset, bars=bars, run_id=f"{run_id}:{asset}", risk=risk)
        )

    reached_risk = sum(1 for w in windows if w["reached_risk"])
    risk_accepts = sum(1 for w in windows if w["risk_verdict"] == "ACCEPT")
    natural_none = sum(
        1
        for w in windows
        for g in w["groups"]
        if g["selected_direction"] == "NONE"
    )
    report = {
        "checkpoint": "MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01",
        "track": "F",
        "run_id": run_id,
        "source": source,
        **PAPER_ONLY_NOTICE,
        "live_calls": 0,
        "windows": windows,
        "NATURAL_WINDOWS": len(windows),
        "NATURAL_CASES_TO_RISK": reached_risk,
        "RISK_ACCEPTS": risk_accepts,
        "ARBITRATION_NONE_GROUPS": natural_none,
        "honesty_note": (
            "Natural outcomes only. If NATURAL_CASES_TO_RISK=0 with source="
            "binanceusdm-public-5m, no valid signal existed in the scanned "
            "window; deterministic fixture (--fixture) provides secondary proof."
        ),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"R2_SMOKE_{run_id}.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "run_id", "source", "NATURAL_WINDOWS", "NATURAL_CASES_TO_RISK",
        "RISK_ACCEPTS", "ARBITRATION_NONE_GROUPS")}, indent=1))
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
