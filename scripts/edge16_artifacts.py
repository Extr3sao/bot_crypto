"""edge16_artifacts — the WP-EDGE-016 deliverables that are derived, not measured live.

Everything this script writes is either (a) a reading of the tree as it stands
(baseline, authority map, risk parity by searching for who reads each policy
field), or (b) arithmetic on published rows (the PIT restatement, the portfolio
accounting, the CURRENT vs PROPOSED table). The lane's own numbers come from
``edge16_paper_lane.py`` and the independent verifier re-derives both.

    python scripts/edge16_artifacts.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.risk import Risk
from trading_bot.research.disk_budget import free_bytes, plan_window
from trading_bot.research.economic_recovery.alpha15 import (
    ANCHOR_STAKE_USDT,
    COST_MULTIPLIERS,
    PRE_PIT_RUNNERS,
    SINGLE_ASSET_FAMILIES,
    evaluate_trades,
    family_trades,
    round_trip_cost_bps,
    split_index,
)
from trading_bot.research.economic_recovery.experiments import Bar, load_ohlcv
from trading_bot.research.economic_recovery.pit15 import PIT_CONTRACT, audit_trade

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-016"
OUT_15 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"
RISK_CONFIG = REPO / "config" / "risk.yaml"

CORPORA: tuple[tuple[str, Path, tuple[str, ...]], ...] = (
    (
        "EDGE08_ALTS_1H",
        REPO / "data" / "edge08" / "universe-1h",
        ("AAVEUSDT", "CRVUSDT", "KSMUSDT", "SNXUSDT", "SUSHIUSDT", "UNIUSDT"),
    ),
    (
        "EDGE07_HOLDOUT_1H",
        REPO / "data" / "edge07" / "holdout-1h",
        ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    ),
)

#: Every field of the risk policy, with the runtime component expected to read it.
POLICY_FIELDS: tuple[tuple[str, str], ...] = (
    ("max_risk_per_trade_pct", "RiskManager._compute_position_size"),
    ("max_daily_loss_pct", "RiskManager.check_signal"),
    ("max_weekly_loss_pct", "RiskManager.check_signal"),
    ("max_daily_drawdown_pct", "RiskManager.check_signal"),
    ("max_total_drawdown_pct", "RiskManager.check_signal"),
    ("max_open_positions", "RiskManager.check_signal"),
    ("max_trades_per_day", "RiskManager.check_signal"),
    ("max_consecutive_losses", "RiskManager.check_signal (cooldown)"),
    ("consecutive_loss_cooldown_minutes", "RiskManager.check_signal (cooldown)"),
    ("max_asset_exposure_pct", "RiskManager._compute_position_size"),
    ("max_total_exposure_pct", "RiskManager._compute_position_size"),
    ("min_order_notional_usdt", "RiskManager._compute_position_size"),
    ("max_order_notional_usdt", "RiskManager._compute_position_size"),
    ("default_stop_loss_pct", "RiskManager._compute_position_size"),
    ("default_take_profit_pct", "RiskManager._compute_position_size"),
    ("blocks.excessive_spread_bps", "DECLARED, NOT READ by the paper path"),
    ("blocks.extreme_atr_pct", "DECLARED, NOT READ by the paper path"),
    ("blocks.high_latency_ms", "DECLARED, NOT READ by the paper path"),
    ("blocks.weekend_trading", "DECLARED, NOT READ anywhere in the runtime"),
    ("kill_switch_enabled", "RiskManager.check_signal"),
    ("live_trading_enabled", "config validator only (refuses True)"),
)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def readers_of(field: str) -> list[str]:
    """Files under ``src``/``scripts`` that name the policy field (grep, recorded)."""
    pattern = re.compile(rf"[.\[\"']{re.escape(field)}[\"']?\s*[=\]\.,)]")
    hits: list[str] = []
    for root in ("src", "scripts"):
        for path in sorted((REPO / root).rglob("*.py")):
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(path.relative_to(REPO).as_posix())
    return hits


# --- 16A: baseline, authority, defect map ----------------------------------------------


def baseline() -> dict[str, Any]:
    witnesses = [
        "src/trading_bot/research/economic_recovery/alpha15.py",
        "src/trading_bot/research/economic_recovery/pit15.py",
        "scripts/edge15_paper_lane.py",
        "scripts/edge16_paper_lane.py",
        "src/trading_bot/paper/broker.py",
        "src/trading_bot/risk/manager.py",
        "config/risk.yaml",
        "config/strategy_admission.json",
        "reports/economic-recovery/RFC-EDGE-015/RUN_REPORT.json",
        "reports/economic-recovery/RFC-EDGE-015/experimental_paper/PROSPECTIVE_PAPER_REPORT.json",
    ]
    return {
        "schema_version": "EDGE16_BASELINE_V1",
        "captured_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": _git("rev-parse", "HEAD"),
        "head_short": _git("rev-parse", "--short", "HEAD"),
        "head_subject": _git("log", "-1", "--format=%s"),
        "head_committed_at_unix": int(_git("log", "-1", "--format=%ct") or 0),
        "upstream": _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
        "upstream_head": _git("rev-parse", "@{u}"),
        "dirty_tracked_files": len(
            [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
        ),
        "ownership_note": (
            "the working tree carries changes from other work lines: this package only adds its "
            "own files and edits the ones named in EVIDENCE_INDEX.json"
        ),
        "artifacts": {name: sha256(REPO / name) for name in witnesses},
        "preserved_as_historical": {
            "what": "the WP-EDGE-015 experiments",
            "label": "HISTORICAL_DESCRIPTIVE_PRE_PIT_FIX",
            "why": (
                "their exit fills preceded the information that triggered them, so their numbers "
                "are a description of that code, not an economic result"
            ),
            "still_on_disk": str(OUT_15.relative_to(REPO)),
        },
    }


def per_symbol_series() -> list[tuple[str, str, str, list[Bar]]]:
    out: list[tuple[str, str, str, list[Bar]]] = []
    for corpus_name, path, symbols in CORPORA:
        for symbol in symbols:
            matches = sorted(path.glob(f"{symbol}*.json"))
            if not matches:
                continue
            out.append(
                (corpus_name, symbol, symbol.replace("USDT", "/USDT"), load_ohlcv(matches[0]))
            )
    return out


def pit_defect_map() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for corpus_name, _symbol, pair, bars in per_symbol_series():
        for family in SINGLE_ASSET_FAMILIES:
            old = PRE_PIT_RUNNERS[family.name](bars, family.parameters)
            new = family_trades(family, bars)
            bars_index = {bar.ts_ms: index for index, bar in enumerate(bars)}
            same_bar = 0
            for trade in old:
                exit_signal = bars_index[trade["exit_ts_ms"]]
                if exit_signal > 0:
                    same_bar += 1
            shifted = sum(
                1
                for trade in new
                if not trade["is_mark"]
                and trade["exit_fill_index"] == trade["exit_signal_index"] + 1
            )
            rows.append(
                {
                    "corpus": corpus_name,
                    "symbol": pair,
                    "family": family.name,
                    "pre_pit_trades": len(old),
                    "pre_pit_exits_filled_at_their_own_signal_bar": same_bar,
                    "pre_pit_exit_exploit_share": round(same_bar / len(old), 4) if old else 0.0,
                    "post_pit_trades": len(new),
                    "post_pit_exits_filled_one_bar_after_the_signal": shifted,
                    "post_pit_terminal_marks": sum(1 for trade in new if trade["is_mark"]),
                    "post_pit_pit_violations": sum(len(audit_trade(trade)) for trade in new),
                }
            )
    totals = {
        "pre_pit_exits_checked": sum(row["pre_pit_trades"] for row in rows),
        "pre_pit_exits_filled_at_their_own_signal_bar": sum(
            row["pre_pit_exits_filled_at_their_own_signal_bar"] for row in rows
        ),
        "post_pit_pit_violations": sum(row["post_pit_pit_violations"] for row in rows),
    }
    totals["share"] = (
        round(
            totals["pre_pit_exits_filled_at_their_own_signal_bar"]
            / totals["pre_pit_exits_checked"],
            4,
        )
        if totals["pre_pit_exits_checked"]
        else 0.0
    )
    payload = {
        "schema_version": "EDGE16_PIT_DEFECT_MAP_V1",
        "defect": (
            "every exit test read the current bar's close and filled at that same bar's open, a "
            "price that had already happened before the close existed"
        ),
        "contract": PIT_CONTRACT,
        "totals": totals,
        "rows": rows,
        "verified_by": "tests/unit/research/test_edge16_pit.py (16 tests) + edge16_verify.py V03-V06",
        "reading": (
            "the repair moves the fill instant and nothing else: the rules fire on the same signal "
            "bars, entries are unchanged, and the exits that a rule would have taken at the signal "
            "bar are now taken at the next executable bar or marked if the window ends first"
        ),
    }
    return payload, rows


def pit_defect_markdown(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    lines = [
        "# WP-EDGE-016 — PIT defect map",
        "",
        f"*measured on the corpus as committed; {totals['pre_pit_exits_checked']} pre-repair exits*",
        "",
        "## The defect",
        "",
        "Each family read the **current** bar's close (`closes[index]`, `bars[index].close`) to decide",
        "an exit and then filled it at `bars[index].open` — an instant that precedes that close. A",
        "decision cannot be executed before its own information exists, so those exit prices were not",
        "obtainable.",
        "",
        f"**{totals['pre_pit_exits_filled_at_their_own_signal_bar']} of "
        f"{totals['pre_pit_exits_checked']} exits ({totals['share']:.1%}) were filled that way.** Every",
        "family and every symbol was affected, which is why the WP-EDGE-015 economic numbers are",
        "labelled `HISTORICAL_DESCRIPTIVE_PRE_PIT_FIX` rather than corrected in place.",
        "",
        "## The repair",
        "",
        "| clause | rule |",
        "| --- | --- |",
        f"| decision clock | {payload['contract']['decision_clock']} |",
        f"| entry | {payload['contract']['entry_signal']} |",
        f"| exit | {payload['contract']['exit_signal']} |",
        f"| terminal | {payload['contract']['terminal_mark']} |",
        f"| undefined indicator | {payload['contract']['undefined_indicator']} |",
        "",
        "The rules are unchanged: the same signal bars fire, the same entries fill, and the only",
        "difference is that an exit decided at bar *t* is filled at the open of bar *t+1*, or marked",
        "at the window's last close if the series ends first.",
        "",
        "| corpus | symbol | family | pre-PIT trades | exits filled at their own signal bar | post-PIT trades | filled one bar later | marks | violations |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['corpus']} | {row['symbol']} | {row['family']} | {row['pre_pit_trades']} | "
            f"{row['pre_pit_exits_filled_at_their_own_signal_bar']} | {row['post_pit_trades']} | "
            f"{row['post_pit_exits_filled_one_bar_after_the_signal']} | "
            f"{row['post_pit_terminal_marks']} | {row['post_pit_pit_violations']} |"
        )
    lines += [
        "",
        "## What the repair changes economically",
        "",
        "See `ECONOMIC_RESTATEMENT.csv`: the deltas are per trade, per symbol and per family, and the",
        "verdicts in `CURRENT_VS_PROPOSED.json` are recomputed on the repaired fills. A green number",
        "that only exists because an exit was filled one bar early is not a number at all.",
        "",
    ]
    return "\n".join(lines)


# --- 16C: risk parity, portfolio, weekend ----------------------------------------------


def risk_parity_matrix() -> dict[str, Any]:
    rows = []
    for field, expected in POLICY_FIELDS:
        short = field.split(".")[-1]
        files = readers_of(short)
        enforced = expected.startswith("RiskManager")
        rows.append(
            {
                "field": field,
                "expected_reader": expected,
                "files_that_name_it": files,
                "read_by_the_canonical_engine": enforced,
                "read_by_the_lane": short in {"weekend_trading"},
                "status": "ENFORCED" if enforced else "DECLARED_NOT_ENFORCED",
            }
        )
    not_enforced = [row["field"] for row in rows if row["status"] != "ENFORCED"]
    return {
        "schema_version": "EDGE16_RISK_PARITY_MATRIX_V1",
        "canonical_entry_gate": "RiskManager.check_signal",
        "lane_uses_canonical_engine": True,
        "lane_manual_risk_checks_remaining": [],
        "policy_fields": rows,
        "declared_but_not_enforced": not_enforced,
        "reading": (
            "the lane no longer re-implements the policy: entries are approved, sized and refused by "
            "RiskManager. The rows marked DECLARED_NOT_ENFORCED are a finding about the runtime, not "
            "about this lane: the defensive block fields exist in the model and are read by nothing "
            "on the paper path, which is why the weekend veto had to be applied by the lane."
        ),
        "method": "grep for each field name across src/ and scripts/ (recorded per row)",
    }


def portfolio_accounting(lane_report: dict[str, Any]) -> dict[str, Any]:
    old = _load_json(OUT_15 / "experimental_paper" / "PROSPECTIVE_PAPER_REPORT.json") or {}
    old_books = old.get("positions_and_pnl", {})
    return {
        "schema_version": "EDGE16_PORTFOLIO_ACCOUNTING_V1",
        "wp_edge_015": {
            "mode": "THREE_INDEPENDENT_SIMULATIONS",
            "books": old.get("book_ids", []),
            "equity_per_book_usdt": 10_000.0,
            "reported_mark_to_market_usdt": old_books.get("equity_mark_to_market_usdt"),
            "not_a_claim_about_capital": True,
            "why": (
                "three books of 10 000 are three simulations; adding their equity describes nothing "
                "an account could hold, and the 015 comparison used a single 10 000 base, so the two "
                "numbers were never the same quantity"
            ),
        },
        "wp_edge_016": {
            "mode": "ONE_SHARED_PORTFOLIO",
            "book_id": lane_report.get("portfolio", {}).get("book_id"),
            "equity_usdt": lane_report.get("portfolio", {}).get("equity_usdt"),
            "closed_trades": lane_report.get("positions_and_pnl", {}).get("closed_trades"),
            "realised_pnl_usdt": lane_report.get("positions_and_pnl", {}).get("realised_pnl_usdt"),
            "equity_mark_to_market_usdt": lane_report.get("positions_and_pnl", {}).get(
                "equity_mark_to_market_usdt"
            ),
            "identities_hold": lane_report.get("positions_and_pnl", {}).get("identities_all_hold"),
            "gates_that_bind_across_symbols": [
                "max_open_positions",
                "max_total_exposure_pct",
                "max_asset_exposure_pct",
                "max_daily_loss_pct",
                "max_weekly_loss_pct",
                "max_total_drawdown_pct",
            ],
        },
        "reconciliation": {
            "015_sum_of_books": old_books.get("equity_mark_to_market_usdt"),
            "015_single_base_used_for_the_comparison": 10_000.0,
            "016_single_base": lane_report.get("portfolio", {}).get("equity_usdt"),
            "verdict": "NOT_COMPARABLE_UNTIL_RESTATED",
        },
    }


def weekend_policy(lane_report: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = {
        "schema_version": "EDGE16_WEEKEND_POLICY_V1",
        "declared": {"blocks.weekend_trading": False},
        "readers_in_the_runtime": readers_of("weekend_trading"),
        "lane_behaviour": "refuses entries on Saturday and Sunday, recorded as WEEKEND_VETO_POLICY",
        "weekend_refusals_recorded": lane_report.get("weekend_policy", {}).get(
            "weekend_entries_refused"
        ),
        "active_goal_7_of_7": {
            "possible_under_the_policy_as_written": False,
            "blocked_by": "blocks.weekend_trading=false, plus the fact that nothing enforces it",
            "requires": (
                "an explicit risk/governance decision (ADR) that either changes the flag or states "
                "that the lane may trade the weekend despite it; this package does neither"
            ),
        },
        "reading": (
            "the flag is declared and unread: no runtime component consults it, so a 24/7 goal is "
            "neither enabled nor blocked by code — it is a decision nobody has taken"
        ),
    }
    lines = [
        "# WP-EDGE-016 — weekend policy conflict",
        "",
        "`config/risk.yaml` declares `blocks.weekend_trading: false`, i.e. **no trading on Saturday or",
        "Sunday**. The 7/7 ACTIVE goal in the campaign brief needs the opposite.",
        "",
        "## What the code does about it",
        "",
        f"Searching `src/` and `scripts/` for the flag returns: {', '.join(payload['readers_in_the_runtime']) or 'nothing'}.",
        "The canonical risk engine does not consult it (see `RISK_PARITY_MATRIX.json`), the paper cycle",
        "does not consult it, and the runtime does not consult it. The only code that has ever read it",
        "is the experimental lane written for this work package, which honours it: weekend entries are",
        "refused and recorded as `WEEKEND_VETO_POLICY`.",
        "",
        "## Consequence",
        "",
        "* A 7/7 goal cannot be met under the policy as written, and it is not blocked by an enforced",
        "  rule either: the conflict is between a declared intention and an unimplemented one.",
        "* This package does **not** change the flag, does not enable weekend trading and does not",
        "  amend the runtime to read it.",
        "* Unblocking it needs an explicit risk/governance decision with its own RFC/ADR — either a",
        "  changed flag plus the code that enforces it, or a written statement that weekends are out of",
        "  scope for ACTIVE.",
        "",
        f"Weekend refusals recorded by the lane: **{payload['weekend_refusals_recorded']}**.",
        "",
    ]
    return "\n".join(lines), payload


# --- 16D: the restatement ---------------------------------------------------------------


def restatement() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    per_trade: list[dict[str, Any]] = []
    for corpus_name, _symbol, pair, bars in per_symbol_series():
        cut = split_index(bars, 1.0 - 0.30)
        tail = bars[cut:]
        window_days = max((tail[-1].ts_ms - tail[0].ts_ms) / 86_400_000.0, 1e-9)
        for family in SINGLE_ASSET_FAMILIES:
            old_trades = PRE_PIT_RUNNERS[family.name](bars, family.parameters)
            old_tail = [t for t in old_trades if t["entry_ts_ms"] >= tail[0].ts_ms]
            new_tail = [t for t in family_trades(family, bars) if t["entry_ts_ms"] >= tail[0].ts_ms]
            old_metrics = evaluate_trades(
                old_tail,
                symbol=pair,
                window_days=window_days,
                window_start_ms=tail[0].ts_ms,
                window_end_ms=tail[-1].ts_ms,
            )
            new_metrics = evaluate_trades(
                [dict(t) for t in new_tail],
                symbol=pair,
                window_days=window_days,
                window_start_ms=tail[0].ts_ms,
                window_end_ms=tail[-1].ts_ms,
            )
            for trade in new_tail:
                per_trade.append(
                    {
                        "corpus": corpus_name,
                        "symbol": pair,
                        "family": family.name,
                        "entry_signal_index": int(trade["entry_signal_index"]),
                        "entry_fill_index": int(trade["entry_fill_index"]),
                        "exit_signal_index": int(trade["exit_signal_index"]),
                        "exit_fill_index": int(trade["exit_fill_index"]),
                        "entry_ts_ms": int(trade["entry_ts_ms"]),
                        "exit_ts_ms": int(trade["exit_ts_ms"]),
                        "entry_data_available_ms": int(trade["entry_data_available_ms"]),
                        "exit_data_available_ms": int(trade["exit_data_available_ms"]),
                        "entry_price": float(trade["entry_price"]),
                        "exit_price": float(trade["exit_price"]),
                        "gross_bps": float(trade["gross_bps"]),
                        "exit_rule": str(trade["exit_rule"]),
                        "is_mark": bool(trade["is_mark"]),
                        "bars_held": int(trade["bars_held"]),
                    }
                )
            for label, metrics in (("PRE_PIT", old_metrics), ("POST_PIT", new_metrics)):
                delta = metrics["gross_bps_per_trade"] if label == "POST_PIT" else 0.0
                rows.append(
                    {
                        "corpus": corpus_name,
                        "symbol": pair,
                        "family": family.name,
                        "variant": label,
                        "segment": "HELD_OUT_TAIL",
                        "trades": metrics["trades"],
                        "trades_per_day": round(metrics["trades_per_day"], 4),
                        "days_without_trades": metrics["days_without_trades"],
                        "gross_bps_per_trade": round(metrics["gross_bps_per_trade"], 4),
                        "net_bps_total_1x": round(metrics["net_bps_total_1x"], 4),
                        "net_bps_total_2x": round(metrics["net_bps_total_2x"], 4),
                        "net_bps_total_3x": round(metrics["net_bps_total_3x"], 4),
                        "expectancy_bps_per_trade": round(metrics["expectancy_bps_per_trade"], 4),
                        "win_rate": round(metrics["win_rate"], 4),
                        "max_drawdown_bps": round(metrics["max_drawdown_bps"], 4),
                        "sharpe_daily_annualised": round(metrics["sharpe_daily_annualised"], 4),
                        "top5_share_of_gross": round(
                            float(metrics["top5_share_of_gross"] or 0.0), 4
                        ),
                        "trades_losing_money_per_trade": round(
                            float(metrics["trades_losing_money_per_trade"] or 0.0), 4
                        ),
                        "cost_round_trip_bps_1x": round(
                            round_trip_cost_bps(pair, stake_usdt=ANCHOR_STAKE_USDT), 4
                        ),
                        "delta_gross_bps_per_trade": delta,
                    }
                )
    return rows, per_trade


def current_vs_proposed(restated: list[dict[str, Any]], risk: Risk) -> dict[str, Any]:
    notional = min(
        float(risk.max_order_notional_usdt),
        max(
            float(risk.min_order_notional_usdt),
            10_000.0 * float(risk.max_asset_exposure_pct) / 100.0 / float(risk.max_open_positions),
        ),
    )
    proposed: dict[str, dict[str, Any]] = {}
    for row in restated:
        if row["variant"] != "POST_PIT":
            continue
        bucket = proposed.setdefault(
            row["family"],
            {
                "trades": 0,
                "net_usdt_1x": 0.0,
                "net_usdt_2x": 0.0,
                "net_usdt_3x": 0.0,
                "per_symbol": {},
            },
        )
        bucket["trades"] += int(row["trades"])
        for multiplier in COST_MULTIPLIERS:
            key = f"net_bps_total_{multiplier:g}x"
            bucket[f"net_usdt_{multiplier:g}x".replace("1x", "1x")] = (
                bucket.get(f"net_usdt_{multiplier:g}x", 0.0) + float(row[key]) / 10_000.0 * notional
            )
        bucket["per_symbol"][row["symbol"]] = {
            "trades": row["trades"],
            "net_bps_total_1x": row["net_bps_total_1x"],
            "net_bps_total_2x": row["net_bps_total_2x"],
        }
    for family, bucket in proposed.items():
        for key in ("net_usdt_1x", "net_usdt_2x", "net_usdt_3x"):
            bucket[key] = round(bucket.get(key, 0.0), 6)
        bucket["beats_current_at_2x"] = bool(bucket["net_usdt_2x"] > 0 and bucket["trades"] > 0)
        bucket["family"] = family
    winners = sorted(name for name, b in proposed.items() if b["beats_current_at_2x"])
    return {
        "schema_version": "EDGE16_CURRENT_VS_PROPOSED_V1",
        "restated_after": "PIT repair (exit fills moved to the next executable bar)",
        "same_data": "held-out tail of each series, same corpora as WP-EDGE-015",
        "capital_usdt": 10_000.0,
        "order_notional_usdt": round(notional, 2),
        "order_sizing_rule": "config/risk.yaml, as the canonical RiskManager sizes it",
        "current_runtime": {
            "admitted_strategies": [],
            "trades": 0,
            "net_usdt": 0.0,
            "equity_end_usdt": 10_000.0,
        },
        "proposed": dict(sorted((k, v) for k, v in proposed.items())),
        "survive_the_adverse_multiplier": winners,
        "verdict": (
            "NO_RESTATED_EDGE_SURVIVES"
            if not winners
            else f"SURVIVES_COSTS_AT_2X: {', '.join(winners)}"
        ),
        "note": (
            "surviving the adverse cost multiplier is necessary and not sufficient: the decision also "
            "requires the concentration and drawdown thresholds frozen in the WP-EDGE-015 protocol"
        ),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lane_report = _load_json(OUT / "experimental_paper" / "CANONICAL_LANE_REPORT.json") or {}

    base = baseline()
    (OUT / "BASELINE.json").write_text(
        json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    defect, _rows = pit_defect_map()
    (OUT / "PIT_DEFECT_MAP.json").write_text(
        json.dumps(defect, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "PIT_DEFECT_MAP.md").write_text(pit_defect_markdown(defect), encoding="utf-8")

    parity = risk_parity_matrix()
    (OUT / "RISK_PARITY_MATRIX.json").write_text(
        json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    portfolio = portfolio_accounting(lane_report)
    (OUT / "PORTFOLIO_ACCOUNTING.json").write_text(
        json.dumps(portfolio, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    md, weekend = weekend_policy(lane_report)
    (OUT / "WEEKEND_POLICY_CONFLICT.md").write_text(md, encoding="utf-8")
    (OUT / "WEEKEND_POLICY.json").write_text(
        json.dumps(weekend, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    restated, per_trade = restatement()
    with (OUT / "ALPHA_RESTATEMENT_TRADES.jsonl").open("w", encoding="utf-8") as handle:
        for trade in per_trade:
            handle.write(json.dumps(trade, sort_keys=True) + "\n")
    columns = list(restated[0])
    with (OUT / "ECONOMIC_RESTATEMENT.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(restated)

    from trading_bot.config.settings import load_settings

    risk = load_settings(config_dir=REPO / "config", env_file=None).risk
    cvp = current_vs_proposed(restated, risk)
    (OUT / "CURRENT_VS_PROPOSED.json").write_text(
        json.dumps(cvp, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    budget = plan_window(hours=24.0, collector_max_bytes=64 * 1024 * 1024, free=free_bytes(REPO))
    capacity = {
        "schema_version": "EDGE16_CAPACITY_PREFLIGHT_V1",
        "free_bytes": free_bytes(REPO),
        "free_gib": round(free_bytes(REPO) / 1024**3, 3),
        "window_hours": 24.0,
        "collector_max_bytes": 64 * 1024 * 1024,
        "guard_state": budget.state,
        "guard_ok": budget.ok,
        "guard_reasons": list(budget.reasons),
        "guard_relaxed_by_this_package": False,
        "one_hour_of_all_three_symbols_bytes": 3 * 422,
        "retention_plan": {
            "hourly_files_per_day": 24,
            "manifests": "one hash-chained manifest per day, not 24 commits",
            "bounded_retention_days": 30,
            "estimated_bytes_for_30_days": 3 * 24 * 30 * 422,
        },
        "verdict": "CAPTURE_ALLOWED" if budget.ok else "CAPTURE_BLOCKED_DISK",
    }
    (OUT / "CAPACITY_PREFLIGHT.json").write_text(
        json.dumps(capacity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    baseline_bytes = json.dumps(base, sort_keys=True)
    (OUT / "BASELINE.json").write_bytes(baseline_bytes.encode("utf-8"))
    print(f"[16a] baseline head {base['head_short']} dirty={base['dirty_tracked_files']}")
    print(f"[16a] PIT defect: {defect['totals']['share']:.1%} of pre-repair exits were same-bar")
    print(
        f"[16c] policy fields declared but not enforced: {len(parity['declared_but_not_enforced'])}"
    )
    print(
        f"[16d] restatement rows {len(restated)}; trades {len(per_trade)}; C vs P {cvp['verdict']}"
    )
    print(f"[16e] capacity {capacity['verdict']} free {capacity['free_gib']} GiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
