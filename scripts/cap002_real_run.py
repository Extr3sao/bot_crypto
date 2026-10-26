"""CAP-002 free real market pilot — runner (real data, no TradingView).

Reuses the repository's existing real provider (public Binance via CCXT) to build
a real, causal :class:`MarketSnapshot` for BTC and ETH at 1H/4H/1D, evaluates the
replacement gate ``G_REAL_MARKET_CONTEXT``, freezes ``MARKET_ANALYST_V1.0`` and
seals whatever analyst answers are present as real :class:`DecisionRecord`s.

The LLM analyst is the client (ChatGPT / Codex / the agent), not the repo: this
runner writes a prompt package per asset, and seals the analyst answer file when
it exists.  Synthetic data never enters here.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cap001_run as c1  # noqa: E402

from trading_bot.research import agentic_contracts as ac  # noqa: E402
from trading_bot.research import market_analyst_v1 as mav  # noqa: E402
from trading_bot.research import real_market_context as rmc  # noqa: E402

OUT = REPO / "reports" / "agentic-pilot-cap002"
REPORTS = REPO / "reports"


def asset_key(asset: str) -> str:
    return asset.split(":")[-1]


def last_completed_boundary_ms(*, now_ms: int | None = None, bar_ms: int = 4 * 3_600 * 1_000) -> int:
    """The close of the last completed 4H bar (open of the current one)."""
    moment = int(time.time() * 1_000) if now_ms is None else int(now_ms)
    return (moment // bar_ms) * bar_ms


def fetch_asset_rows(connector: Any, asset: str) -> dict[str, list[Any]]:
    return {key: rmc.fetch_provider_ohlcv(connector, asset, key) for key in rmc.CONTRACT_INTERVALS}


def main() -> int:
    gate_state = c1.entry_gate()
    decision_ms = last_completed_boundary_ms()
    decision_time = decision_ms // 1_000

    connector = rmc.make_connector()
    raw_by_asset = {asset: fetch_asset_rows(connector, asset) for asset in rmc.PILOT_ASSETS}
    btc_rows_4h = rmc.completed_rows(
        raw_by_asset["BINANCE:BTCUSDT"]["4h"], decision_ms=decision_ms, interval_key="4h"
    )

    artifacts: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    for asset in rmc.PILOT_ASSETS:
        rows = {
            key: rmc.completed_rows(raw_by_asset[asset][key], decision_ms=decision_ms, interval_key=key)
            for key in rmc.CONTRACT_INTERVALS
        }
        artifact = rmc.build_real_snapshot_artifact(
            asset=asset,
            decision_time=decision_time,
            rows_by_interval=rows,
            reference_rows_4h=btc_rows_4h,
        )
        artifacts[asset] = artifact
        gates[asset] = rmc.evaluate_g_real_market_context(artifact, snapshot_at=decision_time)

    sealed: dict[str, Any] = {}
    for asset in rmc.PILOT_ASSETS:
        key = asset_key(asset)
        decision_path = OUT / f"ANALYST_DECISION_{key}.json"
        if decision_path.is_file():
            payload = json.loads(decision_path.read_text(encoding="utf-8"))
            record = mav.seal_analyst_decision(
                payload,
                snapshot_hash=artifacts[asset]["snapshot_hash"],
                raw_data_hash=artifacts[asset]["raw_evidence_hash"],
                critic_output={"note": "single-analyst pilot; no separate critic model in V1"},
            )
            sealed[asset] = {
                "decision_id": "DEC-" + record.decision_hash[:16],
                "record": record.to_dict(),
                "record_verified": record.is_verified(),
                "analyst_payload": payload,
            }

    report = {
        "spike": "CAP-002 FREE REAL MARKET PILOT",
        "provider": rmc.PROVIDER,
        "source_type": rmc.REAL_SOURCE_TYPE,
        "tradingview_used": False,
        "assets": list(rmc.PILOT_ASSETS),
        "timeframes": list(rmc.CONTRACT_INTERVALS),
        "decision_time": decision_time,
        "gates": gates,
        "g_real_market_context": "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL",
        "g_tv_context": ac.G_TV_CONTEXT,
        "market_analyst": {"version": mav.PROMPT_VERSION, "frozen": True, "prompt_digest": mav.prompt_digest()},
        "sealed_decisions": {asset: sealed[asset]["record"] for asset in sealed},
        "real_sealed_decisions": len(sealed),
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "business_validated_edge_count": ac.KPI_VALUES["STRATEGY_EDGE"],
        "alpha_research_freeze": ac.ALPHA_RESEARCH_FREEZE,
        "economic_state_digest_unchanged": c1.file_digest(c1.ECONOMIC_STATE),
        "entry_gate": {
            "branch": gate_state["branch"],
            "head_short": gate_state["head_short"],
            "worktree_dirty": gate_state["worktree_dirty"],
            "freeze_seen": gate_state["freeze_seen"],
        },
    }
    for asset in rmc.PILOT_ASSETS:
        key = asset_key(asset)
        c1.write_json(OUT / f"REAL_EVIDENCE_{key}.json", artifacts[asset]["raw_evidence"])
        snap = dict(artifacts[asset])
        snap.pop("raw_evidence", None)
        c1.write_json(OUT / f"REAL_SNAPSHOT_{key}.json", snap)
        c1.write_json(OUT / f"REAL_GATE_{key}.json", gates[asset])
        c1.write_json(
            OUT / f"ANALYST_PACKAGE_{key}.json",
            {
                "prompt_version": mav.PROMPT_VERSION,
                "prompt_digest": mav.prompt_digest(),
                "system_prompt": mav.SYSTEM_PROMPT,
                "output_fields": list(mav.ANALYST_OUTPUT_FIELDS),
                "allowed_decisions": list(mav.ALLOWED_DECISIONS),
                "allowed_horizons": list(mav.HORIZONS),
                "snapshot_hash": artifacts[asset]["snapshot_hash"],
                "raw_data_hash": artifacts[asset]["raw_evidence_hash"],
                "snapshot": artifacts[asset]["snapshot"],
            },
        )
        if asset in sealed:
            c1.write_json(OUT / f"SEALED_DECISION_{key}.json", sealed[asset])
            c1.write_md(OUT / f"SEALED_DECISION_{key}.md", c1.render(f"REAL SEALED DECISION — {asset}", sealed[asset]))

    c1.write_json(REPORTS / "CAP002_REAL_PILOT_REPORT.json", report)
    c1.write_md(REPORTS / "CAP002_REAL_PILOT_REPORT.md", c1.render("CAP-002 FREE REAL MARKET PILOT", report))

    print("CAP-002 FREE REAL MARKET PILOT")
    print(f"provider = {rmc.PROVIDER}  decision_time = {decision_time}")
    for asset in rmc.PILOT_ASSETS:
        gate = gates[asset]
        print(f"{asset}: {gate['gate']} = {gate['status']}  failed={gate['failed']}")
        print(f"  1D completed bars = {artifacts[asset]['derived']['daily_bars_for_sma200']}")
    print(f"G_REAL_MARKET_CONTEXT = {report['g_real_market_context']}")
    print(f"G_TV_CONTEXT = {report['g_tv_context']}")
    print(f"MARKET_ANALYST = {mav.PROMPT_VERSION} frozen")
    print(f"REAL SEALED DECISIONS = {report['real_sealed_decisions']}")
    for asset, item in sealed.items():
        print(f"  {asset}: {item['record']['decision']}  id={item['decision_id']}  verified={item['record_verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
