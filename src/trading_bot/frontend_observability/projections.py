"""Read-only observability projections for the frontend (§9-16).

Every number and object is a projection of committed runtime artifacts
(CAMPAIGN_STATE.json, DAILY_REPORT.json, CAMPAIGN_REPORT.json,
RUN_REPORT.json).  This module performs NO calculation that could become
an accounting authority: it reads, formats, and marks insufficient
samples.  It never writes to the trading runtime.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS = REPO_ROOT / "reports"

_DEMO_REPORT = REPORTS / "demo-paper-01" / "RUN_REPORT.json"
_DEMO_STATUS = REPORTS / "demo-paper-01" / "DASHBOARD_STATUS.json"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def campaign_root() -> Path:
    return REPORTS / "paper-observation-01"


def latest_campaign_dir() -> Path | None:
    root = campaign_root()
    if not root.is_dir():
        return None
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def _ratio(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(part / whole, 4)


# --------------------------------------------------------------------------
# §9 OVERVIEW
# --------------------------------------------------------------------------


def _trades_of(entry: dict[str, Any]) -> int:
    """Robust per-day trade count from canonical daily aggregates (no computation of our own)."""
    t = entry.get("trades")
    if isinstance(t, (int, float)):
        return int(t)
    return int(entry.get("wins", 0) or 0) + int(entry.get("losses", 0) or 0)


def overview() -> dict[str, Any]:
    state = _load(_latest(_campaign_state_path()))
    if state is None:
        demo = _load(_DEMO_STATUS) or _load(_DEMO_REPORT)
        if demo is None:
            return {
                "mode": "PAPER",
                "live_disabled": True,
                "error": "no campaign or demo artifacts found in reports root",
            }
        return {
            "mode": demo.get("mode", "PAPER"),
            "data": demo.get("provider", "DEMO_FIXTURE"),
            "live_disabled": True,
            "note": "no campaign state found; showing certified fixture demo summary",
            "equity": demo.get("equity"),
            "pnl_today": demo.get("realized_pnl"),
            "total_pnl": demo.get("realized_pnl"),
            "realized_pnl": demo.get("realized_pnl"),
            "unrealized_pnl": demo.get("unrealized_pnl", 0),
            "trades_today": demo.get("paper_trades"),
            "ge_3_target": "informational",
            "open_positions": demo.get("open_positions"),
            "closed_trades": demo.get("closed_trades"),
            "campaign_progress": "N/A (fixture demo)",
        }
    daily = state.get("daily", {})
    today = max(daily) if daily else None
    today_entry = daily.get(today, {}) if today else {}
    trades_today = _trades_of(today_entry)
    return {
        "mode": "PAPER",
        "data": "REAL_PUBLIC_MARKET" if state.get("provider") == "ccxt" else "DEMO_FIXTURE",
        "live_disabled": True,
        "campaign_id": state.get("campaign_id"),
        "campaign_state": state.get("campaign_status"),
        "campaign_start": state.get("campaign_start"),
        "equity": state.get("equity"),
        "initial_equity": state.get("initial_equity"),
        "pnl_today": today_entry.get("realized_pnl", 0.0),
        "total_pnl": state.get("realized_pnl"),
        "realized_pnl": state.get("realized_pnl"),
        "unrealized_pnl": state.get("unrealized_pnl"),
        "max_drawdown": _max_drawdown_from_daily(daily),
        "trades_today": trades_today,
        "trades_today_date": today,
        "ge_3_target": {
            "target": 3,
            "met": trades_today >= 3,
            "status": "informational only",
        },
        "open_positions": len(state.get("open_positions", {})),
        "closed_trades": len(state.get("closed_trades", [])),
        "campaign_progress": {
            "valid_days": sum(1 for e in daily.values() if e.get("valid", True)),
            "target_days": 7,
            "counted_window_start": "next complete UTC midnight after campaign_start (launch day = BURN_IN)",
        },
    }


def _max_drawdown_from_daily(daily: dict[str, Any]) -> float | None:
    """Projection-only drawdown from per-day realized PnL (canonical numbers stay in accounting)."""
    if not daily:
        return None
    values = [float(daily[k].get("realized_pnl", 0.0) or 0.0) for k in sorted(daily)]
    equity, peak, mdd = 0.0, 0.0, 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    return round(mdd, 6)


def daily_series() -> dict[str, Any]:
    """Per-day projection of the canonical daily aggregates (for charts)."""
    state = _load(_campaign_state_path())
    if state is None:
        return {"source": "unavailable", "days": []}
    daily = state.get("daily", {})
    days: list[dict[str, Any]] = []
    for date in sorted(daily):
        e = daily[date] if isinstance(daily[date], dict) else {}
        trades = _trades_of(e)
        days.append(
            {
                "date": date,
                "scans": e.get("scans"),
                "proposals": e.get("proposals"),
                "debates": e.get("debates"),
                "no_trade": e.get("no_trade"),
                "risk_accepts": e.get("risk_accepts"),
                "risk_rejects": e.get("risk_rejects"),
                "closes": e.get("closes"),
                "wins": e.get("wins"),
                "losses": e.get("losses"),
                "trades": trades,
                "day_ge_3": trades >= 3,
                "realized_pnl": e.get("realized_pnl"),
                "max_intraday_drawdown": e.get("max_intraday_drawdown"),
                "fees": e.get("fees"),
                "false_success": e.get("false_success"),
                "data_health_events": e.get("data_health_events"),
                "valid": e.get("valid", True),
            }
        )
    return {"source": "CAMPAIGN_STATE daily aggregates", "days": days}


def _campaign_state_path() -> Path:
    d = latest_campaign_dir()
    return (d / "CAMPAIGN_STATE.json") if d else Path("nonexistent")


def _latest(path: Path) -> Path:
    return path


# --------------------------------------------------------------------------
# §9 OPPORTUNITY FUNNEL
# --------------------------------------------------------------------------


def funnel() -> dict[str, Any]:
    state = _load(_campaign_state_path())
    if state is None:
        demo = _load(_DEMO_STATUS) or _load(_DEMO_REPORT)
        f = (demo or {}).get("funnel", {})
        src = "demo RUN_REPORT"
    else:
        f = state.get("funnel", {})
        src = "CAMPAIGN_STATE"
    # Canonical §12 funnel keys as persisted by the POC01 runtime.
    steps = [
        "MARKET_SCANS",
        "TRADE_PROPOSALS",
        "DEBATES",
        "DECISION_SELECTED",
        "VERIFIER_VERIFIED",
        "CANDIDATE_ADMITTED",
        "RISK_ACCEPT",
        "PAPER_OPEN",
    ]
    counts = {k: int(f.get(k, 0) or 0) for k in steps}
    counts["NO_TRADE"] = int(f.get("NO_TRADE", 0) or 0)
    counts["RISK_REJECT"] = int(f.get("RISK_REJECT", 0) or 0)
    conversions = {}
    for prev, cur in itertools.pairwise(steps):
        conversions[f"{prev}->{cur}"] = _ratio(counts[cur], counts[prev])
    return {"source": src, "counts": counts, "conversions": conversions}


# --------------------------------------------------------------------------
# §10 AGENT CONVERSATION TIMELINE (structured artifacts only)
# --------------------------------------------------------------------------


def agent_timeline(limit: int = 200) -> dict[str, Any]:
    report = _load(_DEMO_REPORT) or {}
    events = report.get("events", [])
    items: list[dict[str, Any]] = []
    for ev in events:
        kind = ev.get("event", "")
        entry: dict[str, Any] = {"event": kind, "run_id": ev.get("run_id"), "trace_id": ev.get("trace_id")}
        for key in ("symbol", "side", "confidence", "notional", "price", "reason", "verifier"):
            if key in ev:
                entry[key] = ev[key]
        if any(k in ev for k in ("stance", "proposal", "decision", "verdict", "fill")) or kind:
            items.append(entry)
    decisions = report.get("decisions", [])
    for dec in decisions:
        outcome = dec.get("outcome")
        pkg = dec.get("package", {}) or {}
        items.append(
            {
                "event": f"DecisionEngine.{outcome}",
                "decision_id": dec.get("decision_id"),
                "verifier": dec.get("verifier"),
                "cycle": dec.get("cycle"),
                "package_winner": pkg.get("winner"),
            }
        )
    return {"source": "RUN_REPORT.json events+decisions", "items": items[-limit:]}


# --------------------------------------------------------------------------
# §11 STRATEGY VIEW (insufficient samples marked, never computed)
# --------------------------------------------------------------------------


def strategies() -> dict[str, Any]:
    state = _load(_campaign_state_path())
    if state is None:
        demo = _load(_DEMO_STATUS) or {}
        by = demo.get("pnl_by_strategy") or {}
        return {
            "source": "demo DASHBOARD_STATUS",
            "strategies": [
                {"strategy": name, "net_pnl": pnl, "sample": "INSUFFICIENT_SAMPLE"}
                for name, pnl in by.items()
            ],
        }
    out = []
    for name, agg in state.get("by_strategy", {}).items():
        trades = int(agg.get("trades", 0) or 0)
        out.append(
            {
                "strategy": name,
                "evaluations": agg.get("evaluations"),
                "proposals": agg.get("proposals"),
                "selected": agg.get("selected"),
                "trades": trades,
                "wins": agg.get("wins"),
                "losses": agg.get("losses"),
                "net_pnl": agg.get("net_pnl"),
                "expectancy": agg.get("expectancy"),
                "profit_factor": agg.get("profit_factor"),
                "sample": "OK" if trades >= 30 else "INSUFFICIENT_SAMPLE",
            }
        )
    return {"source": "CAMPAIGN_STATE", "strategies": out}


# --------------------------------------------------------------------------
# §12 ASSET VIEW
# --------------------------------------------------------------------------


def assets_view() -> dict[str, Any]:
    state = _load(_campaign_state_path())
    if state is None:
        demo = _load(_DEMO_STATUS) or {}
        by = demo.get("pnl_by_asset") or {}
        return {
            "source": "demo DASHBOARD_STATUS",
            "assets": [
                {"asset": a, "net_pnl": pnl, "sample": "INSUFFICIENT_SAMPLE"} for a, pnl in by.items()
            ],
        }
    out = []
    for name, agg in state.get("by_asset", {}).items():
        out.append(
            {
                "asset": name,
                "proposals": agg.get("proposals"),
                "selected": agg.get("selected"),
                "risk_accepted": agg.get("risk_accepted"),
                "trades": agg.get("trades"),
                "net_pnl": agg.get("net_pnl"),
                "sample": "OK" if int(agg.get("trades", 0) or 0) >= 30 else "INSUFFICIENT_SAMPLE",
            }
        )
    return {
        "source": "CAMPAIGN_STATE",
        "assets": out,
        "data_health": {
            "last_market_timestamp": state.get("last_market_timestamp"),
            "last_successful_scan_time": state.get("last_successful_scan_time"),
            "freshness_invariant": "market_data_time <= decision_time <= execution_time",
        },
    }


# --------------------------------------------------------------------------
# §13 DECISIONS VIEW
# --------------------------------------------------------------------------


def decisions() -> dict[str, Any]:
    report = _load(_DEMO_REPORT) or {}
    items = []
    for dec in report.get("decisions", []):
        pkg = dec.get("package", {}) or {}
        items.append(
            {
                "decision_id": dec.get("decision_id"),
                "outcome": dec.get("outcome"),
                "verifier": dec.get("verifier"),
                "verifier_version": dec.get("verifier_version"),
                "winner": pkg.get("winner"),
                "alternatives": pkg.get("alternatives"),
                "dissent": pkg.get("dissent"),
                "revisions": pkg.get("revisions"),
            }
        )
    state = _load(_campaign_state_path())
    dm = (state or {}).get("decision_metrics", {})
    return {
        "source": "RUN_REPORT decisions + campaign decision_metrics",
        "decisions": items,
        "campaign_aggregates": {
            "selected": dm.get("selected"),
            "rejected": dm.get("rejected"),
            "no_trade": dm.get("no_trade"),
            "verifier_verified": dm.get("verifier_verified"),
            "verifier_rejected": dm.get("verifier_rejected"),
        },
    }


# --------------------------------------------------------------------------
# §14 TRADES / PORTFOLIO (canonical PnL passthrough)
# --------------------------------------------------------------------------


def trades() -> dict[str, Any]:
    state = _load(_campaign_state_path())
    if state is not None:
        return {
            "source": "CAMPAIGN_STATE (canonical accounting passthrough)",
            "open_positions": state.get("open_positions", {}),
            "closed_trades": state.get("closed_trades", []),
            "realized_pnl": state.get("realized_pnl"),
            "unrealized_pnl": state.get("unrealized_pnl"),
            "fees": state.get("fees"),
            "note": "PnL originates from PaperBroker/reconciliation; frontend adds nothing",
        }
    report = _load(_DEMO_REPORT) or {}
    return {
        "source": "demo RUN_REPORT",
        "closed_trades": report.get("trades", report.get("closed_trades", [])),
        "realized_pnl": report.get("realized_pnl"),
        "unrealized_pnl": report.get("unrealized_pnl", 0),
        "note": "canonical numbers from demo accounting",
    }


# --------------------------------------------------------------------------
# §15 REPORTS (read-only file access, path-jail)
# --------------------------------------------------------------------------


def report_list() -> list[dict[str, Any]]:
    root = campaign_root()
    out: list[dict[str, Any]] = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*.json")) + sorted(d.rglob("*.md")):
                out.append(
                    {
                        "campaign_id": d.name,
                        "name": f.name,
                        "path": str(f.relative_to(REPO_ROOT)),
                        "bytes": f.stat().st_size,
                    }
                )
    demo = REPORTS / "demo-paper-01"
    if demo.is_dir():
        for f in sorted(demo.glob("RUN_REPORT.*")):
            out.append({"campaign_id": "demo-paper-01", "name": f.name, "path": str(f.relative_to(REPO_ROOT)), "bytes": f.stat().st_size})
    return out


def report_content(rel_path: str) -> dict[str, Any]:
    """Serve reports only from the reports/ jail; reject everything else."""
    base = REPORTS.resolve()
    target = (base / rel_path).resolve()
    if base not in target.parents and target != base:
        return {"error": "path outside reports jail"}
    if not target.is_file():
        return {"error": "not found"}
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return {"error": "unreadable"}
    return {"path": str(target.relative_to(REPO_ROOT)), "content": text[:200_000]}


# --------------------------------------------------------------------------
# §16 REPLAY GROUNDWORK — honest partial
# --------------------------------------------------------------------------


def replay_status() -> dict[str, Any]:
    report = _load(_DEMO_REPORT) or {}
    events = report.get("events", [])
    chain = [
        {"step": "market", "evidence": "market.scan events", "available": any("scan" in e.get("event", "") for e in events)},
        {"step": "agents", "evidence": "proposal/critique events", "available": any("proposal" in e.get("event", "") for e in events)},
        {"step": "debate", "evidence": "debate events + DebateReport refs", "available": any("debate" in e.get("event", "") for e in events)},
        {"step": "decision", "evidence": "DecisionPackage records", "available": bool(report.get("decisions"))},
        {"step": "risk", "evidence": "risk.approved/rejected events", "available": any("risk" in e.get("event", "") for e in events)},
        {"step": "trade", "evidence": "paper.fill events", "available": any("fill" in e.get("event", "") for e in events)},
        {"step": "outcome", "evidence": "closed trades + realized PnL", "available": bool(report.get("closed_trades") or report.get("realized_pnl"))},
    ]
    full = all(c["available"] for c in chain)
    return {
        "RUN_REPLAY": "FUNCTIONAL" if full else "PARTIAL",
        "run_level_replay_cli": "NOT_IMPLEMENTED_IN_HEAD",
        "chain": chain,
        "note": "no fake replay is generated; only artifact-backed steps are marked available",
    }
