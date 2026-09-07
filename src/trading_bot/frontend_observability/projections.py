"""Read-only observability projections for the frontend (§9-17).

Every number and object is a projection of committed runtime artifacts
(CAMPAIGN_STATE.json, DAILY_REPORT.json, CAMPAIGN_REPORT.json) and, when
configured, the POC01 runtime's read-only /api/campaign summary.  This
module performs NO calculation that could become an accounting authority:
it reads, formats, and marks insufficient samples.  It never writes to the
trading runtime.

Source authority model (DEF-FE-004, FIXED):

1. explicit ``--reports-root``          (highest authority)
2. explicit ``--campaign-api``          (live summary; artifacts still used
                                         for detail views)
3. unambiguous worktree discovery       (exactly one root containing
                                         campaign state)
4. fail loud: SOURCE_NOT_CONFIGURED / FAIL_AMBIGUOUS_SOURCE

A stale artifact snapshot is never shown silently: every overview payload
carries ``data_source``, ``reports_root``, ``last_persisted_at``,
``stale_age_seconds`` and ``stale``.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

# Committed staleness threshold: the POC01 runtime persists every cycle
# (~5 min cadence); an artifact snapshot older than this is STALE_DATA.
STALE_AFTER_SECONDS = 900

CAMPAIGN_NAMESPACE = "paper-observation-01"


class SourceNotConfigured(RuntimeError):
    """No explicit source and unambiguous discovery found nothing."""


class AmbiguousSource(RuntimeError):
    """Multiple candidate report roots exist; refusing to pick positionally."""


# Current source configuration (mutated only by configure_source/resolve).
_source: dict[str, Any] = {
    "reports_root": None,  # Path | None (explicit)
    "campaign_api": None,  # str | None (explicit URL)
    "resolved_root": None,  # Path | None (after resolution)
    "discovery": "unset",  # unset | explicit | discovered | campaign_api
    "api_payload": None,
    "api_fetched_at": None,
    "api_error": None,
}
_WORKTREE_ROOTS: list[Path] | None = None


# ---------------------------------------------------------------------------
# source configuration / resolution (§5-6)
# ---------------------------------------------------------------------------


def configure_source(
    reports_root: Path | str | None = None, campaign_api: str | None = None
) -> None:
    """Set explicit source configuration (CLI entry point)."""
    _source["reports_root"] = Path(reports_root).resolve() if reports_root else None
    _source["campaign_api"] = campaign_api
    _source["resolved_root"] = _source["reports_root"]
    _source["discovery"] = "explicit" if reports_root else ("campaign_api" if campaign_api else "unset")
    _source["api_payload"] = None
    _source["api_fetched_at"] = None
    _source["api_error"] = None


def set_reports_root(root: Path | str) -> None:
    """Backwards-compatible alias: point projections at an explicit root."""
    configure_source(reports_root=root)


def candidate_report_roots() -> list[Path]:
    """All plausible report roots: every git worktree of this repository."""
    global _WORKTREE_ROOTS
    if _WORKTREE_ROOTS is None:
        roots: list[Path] = [REPO_ROOT]
        try:
            proc = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "worktree", "list", "--porcelain"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if line.startswith("worktree "):
                        p = Path(line[len("worktree "):].strip())
                        if p.is_dir() and p not in roots:
                            roots.append(p)
        except (OSError, subprocess.SubprocessError):
            pass
        _WORKTREE_ROOTS = roots
    unique: list[Path] = []
    seen: set[Path] = set()
    for wt in _WORKTREE_ROOTS:
        rp = (wt / "reports").resolve()
        if rp in seen:
            continue
        seen.add(rp)
        unique.append(rp)
    return unique


def _root_has_campaign_state(root: Path) -> bool:
    ns = root / CAMPAIGN_NAMESPACE
    return ns.is_dir() and any(ns.glob("*/CAMPAIGN_STATE.json"))


def resolve_source() -> Path:
    """Resolve the artifact root per the §5 priority; fail loud when unclear."""
    resolved = _source["resolved_root"]
    if resolved is not None:
        return resolved if isinstance(resolved, Path) else Path(resolved)
    candidates = [r for r in candidate_report_roots() if _root_has_campaign_state(r)]
    if len(candidates) == 1:
        _source["resolved_root"] = candidates[0]
        _source["discovery"] = "discovered"
        return candidates[0]
    if len(candidates) == 0:
        raise SourceNotConfigured(
            "SOURCE_NOT_CONFIGURED: no --reports-root/--campaign-api given and "
            "no worktree contains campaign artifacts (paper-observation-01/*/CAMPAIGN_STATE.json)"
        )
    raise AmbiguousSource(
        "FAIL_AMBIGUOUS_SOURCE: multiple candidate report roots hold campaign "
        f"state: {[str(c) for c in candidates]} — pass --reports-root explicitly"
    )


def reports_root() -> Path:
    """Current read-only artifacts root (resolved)."""
    resolved = resolve_source()
    return resolved if isinstance(resolved, Path) else Path(resolved)


def campaign_api_url() -> str | None:
    url = _source["campaign_api"]
    return url if isinstance(url, str) else None


def fetch_campaign_api(timeout: float = 4.0) -> dict[str, Any] | None:
    """Fetch the POC01 runtime's read-only /api/campaign summary (if configured).

    Never raises: on failure the error is recorded and callers fall back to
    persisted artifacts with DATA_SOURCE = ARTIFACT_SNAPSHOT.
    """
    url = _source["campaign_api"]
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        if isinstance(payload, dict):
            _source["api_payload"] = payload
            _source["api_fetched_at"] = datetime.now(UTC).isoformat()
            _source["api_error"] = None
        else:
            _source["api_error"] = f"unexpected payload: {str(payload)[:120]}"
    except Exception as exc:
        _source["api_error"] = f"{type(exc).__name__}: {exc}"
    payload = _source["api_payload"]
    return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# artifact access (all reads go through the resolved root)
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def campaign_root() -> Path:
    return reports_root() / CAMPAIGN_NAMESPACE


def latest_campaign_dir() -> Path | None:
    root = campaign_root()
    if not root.is_dir():
        return None
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def _campaign_state_path() -> Path:
    d = latest_campaign_dir()
    return (d / "CAMPAIGN_STATE.json") if d else Path("nonexistent")


def _load_state() -> dict[str, Any] | None:
    return _load(_campaign_state_path())


def _iso_ms(ms: Any) -> Any:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def source_info() -> dict[str, Any]:
    """Staleness + authority block for the header and the validator (§7)."""
    state_path = _campaign_state_path()
    state = _load(state_path)
    api = _source["api_payload"]
    if api is not None and _source["campaign_api"]:
        fetch_campaign_api()  # refresh best-effort
        api = _source["api_payload"]
    if api is not None:
        data_source = "POC01_API+ARTIFACTS"
        last_persisted = _source["api_fetched_at"]
        try:
            age = int((datetime.now(UTC) - datetime.fromisoformat(last_persisted)).total_seconds())
        except (TypeError, ValueError):
            age = 0
    elif state is not None:
        data_source = "ARTIFACT_SNAPSHOT"
        mtime = state_path.stat().st_mtime
        last_persisted = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        age = int(time.time() - mtime)
    else:
        data_source = "NONE"
        last_persisted = None
        age = None
    info = {
        "data_source": data_source,
        "reports_root": str(_source["resolved_root"]) if _source["resolved_root"] else None,
        "campaign_api": _source["campaign_api"],
        "discovery": _source["discovery"],
        "campaign_id": (api or state or {}).get("campaign_id"),
        "last_persisted_at": last_persisted,
        "stale_age_seconds": age,
        "stale_threshold_seconds": STALE_AFTER_SECONDS,
        "stale": bool(age is not None and age > STALE_AFTER_SECONDS),
        "api_error": _source["api_error"],
    }
    if info["stale"]:
        info["stale_marker"] = "STALE_DATA"
    return info


# ---------------------------------------------------------------------------
# §9 OVERVIEW
# ---------------------------------------------------------------------------


def _trades_of(entry: dict[str, Any]) -> int:
    """Robust per-day trade count from canonical daily aggregates (no computation of our own)."""
    t = entry.get("trades")
    if isinstance(t, (int, float)):
        return int(t)
    return int(entry.get("wins", 0) or 0) + int(entry.get("losses", 0) or 0)


def _counted_window(campaign_start: str) -> dict[str, Any]:
    """POC01 window semantics: launch day = BURN_IN; 7 complete days follow."""
    try:
        start = datetime.fromisoformat(campaign_start)
    except (TypeError, ValueError):
        return {"status": "UNKNOWN", "note": "campaign_start not parseable"}
    window_start = (start.date() + timedelta(days=1))
    window_end = window_start + timedelta(days=7)
    today = datetime.now(UTC).date()
    if today < window_start:
        status = "BURN_IN (launch day, not counted)"
    elif today < window_end:
        status = f"COUNTED_DAY_{(today - window_start).days + 1} (partial day)"
    else:
        status = "WINDOW_COMPLETE (pending validation)"
    return {
        "status": status,
        "launch_day_burn_in": start.date().isoformat(),
        "counted_window_start": window_start.isoformat(),
        "counted_window_end": window_end.isoformat(),
        "target_days": 7,
    }


def _day_validity(entry: dict[str, Any]) -> tuple[bool, list[str]]:
    """POC01 day-validity contract (observational projection, A2/A3 semantics).

    A day is valid only if: runtime had no errors that day, FALSE_SUCCESS=0,
    and the runtime validity flag is not explicitly False. Raw observations
    stay immutable; this evaluates the contract for *counting* only.
    """
    problems: list[str] = []
    if entry.get("valid") is False:
        problems.append("runtime_flag_invalid")
    if int(entry.get("runtime_errors", 0) or 0) > 0:
        problems.append("runtime_errors")
    if int(entry.get("false_success", 0) or 0) > 0:
        problems.append("false_success")
    return (not problems, problems)


def completed_valid_days(daily: dict[str, Any], campaign_start: str) -> dict[str, Any]:
    """DEF-POC01-OBS-005 repair (observation plane only).

    COMPLETED_VALID_DAYS == count(finalized counted UTC days satisfying the
    validity contract). Burn-in never counts; the current partial day never
    counts; observed dates alone never count. The runtime API's own values
    are echoed as ``runtime_api_semantics`` so the defect stays visible.
    """
    cw = _counted_window(campaign_start)
    try:
        window_start = date.fromisoformat(cw["counted_window_start"])
    except (KeyError, TypeError, ValueError):
        window_start = None
    today = datetime.now(UTC).date()
    days: list[dict[str, Any]] = []
    for day in sorted(daily):
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        finalized = d < today
        counted = window_start is not None and d >= window_start
        entry = daily[day] if isinstance(daily[day], dict) else {}
        valid, problems = _day_validity(entry)
        trades = _trades_of(entry)
        days.append(
            {
                "date": day,
                "finalized": finalized,
                "counted": counted,
                "trades": trades,
                "day_ge_3": trades >= 3,
                "valid": valid,
                "validity_problems": problems,
                "counts_toward_kpi": bool(finalized and counted and valid),
            }
        )
    kpi_days = [d for d in days if d["counts_toward_kpi"]]
    ge3 = sum(1 for d in kpi_days if d["day_ge_3"])
    return {
        "completed_valid_days": len(kpi_days),
        "days_ge_3": ge3,
        "percent_days_ge_3": round(ge3 / len(kpi_days) * 100, 2) if kpi_days else 0.0,
        "burn_in_date": cw.get("launch_day_burn_in"),
        "burn_in_included_in_kpi": False,
        "current_partial_day": today.isoformat(),
        "target_days": 7,
        "days": days,
    }


def overview() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured(
            "SOURCE_NOT_CONFIGURED: no CAMPAIGN_STATE.json under the resolved reports root "
            f"({_source['resolved_root']})"
        )
    api = fetch_campaign_api() if _source["campaign_api"] else None
    daily = state.get("daily", {})
    today = max(daily) if daily else None
    today_entry = daily.get(today, {}) if today else {}
    trades_today = _trades_of(today_entry)
    heartbeat = state.get("heartbeat", {}) or {}
    src = source_info()
    return {
        "mode": "PAPER",
        "data": "REAL_PUBLIC_MARKET" if state.get("provider") == "ccxt" else "DEMO_FIXTURE",
        "live_disabled": True,
        # §7 staleness visibility
        "data_source": src["data_source"],
        "reports_root": src["reports_root"],
        "campaign_api": src["campaign_api"],
        "last_persisted_at": src["last_persisted_at"],
        "stale_age_seconds": src["stale_age_seconds"],
        "stale": src["stale"],
        "stale_threshold_seconds": src["stale_threshold_seconds"],
        "stale_marker": src.get("stale_marker"),
        "api_error": src["api_error"],
        # identity / health (API summary preferred when available)
        "campaign_id": (api or state).get("campaign_id"),
        "campaign_state": (api or state).get("campaign_status") or (api or {}).get("campaign_state"),
        "campaign_start": state.get("campaign_start"),
        "provider_status": (api or {}).get("runtime_health", {}).get("provider_status")
        if isinstance((api or {}).get("runtime_health"), dict)
        else heartbeat.get("provider_status"),
        "run_id": state.get("run_id"),
        # canonical accounting passthrough (artifacts are the authority for numbers)
        "equity": state.get("equity"),
        "initial_equity": state.get("initial_equity"),
        "realized_pnl": state.get("realized_pnl"),
        "unrealized_pnl": state.get("unrealized_pnl"),
        "fees": state.get("fees"),
        "net_pnl": state.get("realized_pnl"),
        "pnl_today": today_entry.get("realized_pnl", 0.0),
        "max_drawdown": _max_drawdown_from_daily(daily),
        "trades_today": trades_today,
        "trades_today_date": today,
        "ge_3_target": {
            "target": 3,
            "met": trades_today >= 3,
            "status": "informational only",
        },
        "open_positions": len(state.get("open_positions", {}) or {}),
        "closed_trades": len(state.get("closed_trades", []) or []),
        "scans_today": today_entry.get("scans"),
        "proposals_today": today_entry.get("proposals"),
        "selected_today": today_entry.get("selected"),
        "risk_accepts_today": today_entry.get("risk_accepts"),
        "risk_rejects_today": today_entry.get("risk_rejects"),
        "burn_in": _counted_window(state.get("campaign_start", "")),
        "day_frequency": completed_valid_days(daily, state.get("campaign_start", "")),
        "campaign_progress": {
            # DEF-POC01-OBS-005: only finalized counted valid days (not observed dates)
            "valid_days": completed_valid_days(daily, state.get("campaign_start", ""))["completed_valid_days"],
            "target_days": 7,
            "counted_window_start": _counted_window(state.get("campaign_start", "")).get("counted_window_start"),
        },
        "campaign_api_summary": {
            k: api.get(k)
            for k in ("campaign_id", "campaign_state", "elapsed_hours", "funnel", "performance", "frequency")
            if isinstance(api, dict) and k in api
        } if api else None,
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
    state = _load_state()
    if state is None:
        return {"source": "unavailable", "days": []}
    daily = state.get("daily", {})
    days: list[dict[str, Any]] = []
    for day_key in sorted(daily):
        e = daily[day_key] if isinstance(daily[day_key], dict) else {}
        trades = _trades_of(e)
        days.append(
            {
                "date": day_key,
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


# ---------------------------------------------------------------------------
# §10 OPPORTUNITY FUNNEL
# ---------------------------------------------------------------------------


def funnel() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for funnel")
    f = state.get("funnel", {}) or {}
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
        "PAPER_CLOSE",
    ]
    counts = {k: int(f.get(k, 0) or 0) for k in steps}
    for extra in ("NO_TRADE", "RISK_REJECT", "RISK_CALLS", "BROKER_CALLS", "CRITIQUES", "REVISIONS"):
        if extra in f:
            counts[extra] = int(f.get(extra, 0) or 0)
    conversions = {}
    for prev, cur in itertools.pairwise(steps):
        conversions[f"{prev}->{cur}"] = _ratio(counts[cur], counts[prev])
    return {"source": "CAMPAIGN_STATE", "counts": counts, "conversions": conversions}


def _ratio(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(part / whole, 4)


# ---------------------------------------------------------------------------
# §11 AGENT CONVERSATION (structured aggregates only; per-event detail is
#     NOT persisted by the campaign runtime — say so, never invent dialogue)
# ---------------------------------------------------------------------------


def agent_timeline(limit: int = 200) -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for agent timeline")
    dm = state.get("debate_metrics", {}) or {}
    funnel = state.get("funnel", {}) or {}
    return {
        "source": "CAMPAIGN_STATE debate_metrics/funnel aggregates",
        "per_event_messages": "NOT_PERSISTED",
        "note": "the POC01 runtime persists debate/decision aggregates, not per-event "
        "agent messages; no narrative is invented here",
        "aggregates": {
            "debates": dm.get("debates") or funnel.get("DEBATES"),
            "critiques": dm.get("critiques") or funnel.get("CRITIQUES"),
            "counter_evidence": dm.get("counter_evidence"),
            "material_dissent": dm.get("material_dissent"),
            "revisions": dm.get("revisions") or funnel.get("REVISIONS"),
            "resolved": dm.get("resolved") or funnel.get("DEBATE_RESOLVED"),
            "unresolved": dm.get("unresolved") or funnel.get("DEBATE_UNRESOLVED"),
            "confidence_increased": dm.get("confidence_increased"),
            "confidence_decreased": dm.get("confidence_decreased"),
            "decision_changed_after_debate": dm.get("decision_changed_after_debate"),
            "winner_changed_after_debate": dm.get("winner_changed_after_debate"),
        },
        "items": [],
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# §12/§13 STRATEGY + ASSET VIEWS
# ---------------------------------------------------------------------------


def strategies() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for strategies")
    by = state.get("by_strategy", {}) or {}
    # Render the full frozen universe; absent families are honest zeros.
    names = list(dict.fromkeys(list(state.get("strategies", []) or []) + sorted(by)))
    out = []
    for name in names:
        agg = by.get(name, {}) or {}
        trades = int(agg.get("trades", 0) or 0)
        out.append(
            {
                "strategy": name,
                "evaluations": agg.get("evaluations", 0),
                "proposals": agg.get("proposals", 0),
                "selected": agg.get("selected", 0),
                "trades": trades,
                "wins": agg.get("wins", 0),
                "losses": agg.get("losses", 0),
                "net_pnl": agg.get("net_pnl", 0.0),
                "expectancy": agg.get("expectancy"),
                "profit_factor": agg.get("profit_factor"),
                "sample": "OK" if trades >= 30 else "INSUFFICIENT_SAMPLE",
            }
        )
    return {"source": "CAMPAIGN_STATE", "strategies": out}


def assets_view() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for assets")
    by = state.get("by_asset", {}) or {}
    names = list(dict.fromkeys(list(state.get("assets", []) or []) + sorted(by)))
    out = []
    for name in names:
        agg = by.get(name, {}) or {}
        trades = int(agg.get("trades", 0) or 0)
        out.append(
            {
                "asset": name,
                "proposals": agg.get("proposals", 0),
                "selected": agg.get("selected", 0),
                "risk_accepted": agg.get("risk_accepted", 0),
                "trades": trades,
                "net_pnl": agg.get("net_pnl", 0.0),
                "sample": "OK" if trades >= 30 else "INSUFFICIENT_SAMPLE",
            }
        )
    return {
        "source": "CAMPAIGN_STATE",
        "assets": out,
        "data_health": state.get("data_health", {}) or {},
        "last_market_timestamp": state.get("last_market_timestamp"),
        "last_market_timestamp_iso": _iso_ms(state.get("last_market_timestamp")),
        "last_successful_scan_time": state.get("last_successful_scan_time"),
        "freshness_invariant": "market_data_time <= decision_time <= execution_time",
    }


# ---------------------------------------------------------------------------
# §14 DECISIONS (aggregates + typed risk/block reasons)
# ---------------------------------------------------------------------------


def decisions() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for decisions")
    dm = state.get("decision_metrics", {}) or {}
    rm = state.get("risk_metrics", {}) or {}
    reasons = state.get("reasons", {}) or {}
    return {
        "source": "CAMPAIGN_STATE decision_metrics/risk_metrics/reasons",
        "per_decision_detail": "NOT_PERSISTED",
        "campaign_aggregates": {
            "selected": dm.get("selected"),
            "rejected": dm.get("rejected"),
            "no_trade": dm.get("no_trade"),
            "verifier_verified": dm.get("verifier_verified"),
            "verifier_rejected": dm.get("verifier_rejected"),
            "selected_with_dissent": dm.get("selected_with_dissent"),
            "blocked_unresolved_conflict": dm.get("blocked_unresolved_conflict"),
        },
        "risk": {
            "accepts": rm.get("accepts"),
            "rejects": rm.get("rejects"),
            "rejection_rate": rm.get("rejection_rate"),
            "reason_distribution": rm.get("reason_distribution", {}) or {},
        },
        "block_reasons": {k: v for k, v in reasons.items() if isinstance(v, (int, float))},
        "decisions": [],
    }


# ---------------------------------------------------------------------------
# §15 TRADES / PORTFOLIO (canonical PnL passthrough)
# ---------------------------------------------------------------------------


def trades() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for trades")
    open_pos = state.get("open_positions", {}) or {}
    open_list = []
    if isinstance(open_pos, dict):
        for symbol, pos in open_pos.items():
            entry = dict(pos) if isinstance(pos, dict) else {"value": pos}
            entry.setdefault("symbol", symbol)
            open_list.append(entry)
    else:  # already a list
        open_list = list(open_pos)
    closed = []
    for t in state.get("closed_trades", []) or []:
        row = dict(t)
        row["opened_at"] = row.get("opened_at") or "NOT_PERSISTED"
        row["closed_at"] = row.get("closed_at") or _iso_ms(row.get("closed_at_ms")) or "NOT_PERSISTED"
        closed.append(row)
    realized = state.get("realized_pnl")
    return {
        "source": "CAMPAIGN_STATE (canonical accounting passthrough)",
        "open_positions": open_list,
        "closed_trades": closed,
        "realized_pnl": realized,
        "unrealized_pnl": state.get("unrealized_pnl"),
        "fees": state.get("fees"),
        "closed_trades_pnl_sum": round(sum(float(t.get("pnl", 0.0) or 0.0) for t in closed), 6),
        "note": "PnL originates from PaperBroker/reconciliation; frontend adds nothing",
    }


# ---------------------------------------------------------------------------
# §16 REPORTS (read-only file access, path jail, campaign isolation)
# ---------------------------------------------------------------------------


def _display_path(p: Path) -> str:
    """Repo-relative display path when possible, absolute otherwise."""
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def report_list() -> list[dict[str, Any]]:
    """Only artifacts of the resolved campaign — no demo/legacy/fixture reports."""
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
                        "path": _display_path(f),
                        "bytes": f.stat().st_size,
                    }
                )
    return out


def report_content(rel_path: str) -> dict[str, Any]:
    """Serve reports only from the reports jail; reject everything else."""
    base = reports_root().resolve()
    target = (base / rel_path).resolve()
    if base not in target.parents and target != base:
        return {"error": "path outside reports jail"}
    if not target.is_file():
        return {"error": "not found"}
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return {"error": "unreadable"}
    return {"path": _display_path(target), "content": text[:200_000]}


# ---------------------------------------------------------------------------
# §17 REPLAY GROUNDWORK — honest partial
# ---------------------------------------------------------------------------


def replay_status() -> dict[str, Any]:
    state = _load_state()
    if state is None:
        raise SourceNotConfigured("SOURCE_NOT_CONFIGURED: no campaign state for replay")
    closed = state.get("closed_trades", []) or []
    chain = [
        {"step": "market", "evidence": "per-event market records", "available": False, "detail": "NOT_PERSISTED (funnel aggregates only)"},
        {"step": "agents", "evidence": "per-event agent messages", "available": False, "detail": "NOT_PERSISTED"},
        {"step": "debate", "evidence": "per-debate reports", "available": False, "detail": "NOT_PERSISTED (aggregate metrics only)"},
        {"step": "decision", "evidence": "last_processed_decision_ids + decision ids on trades", "available": bool(state.get("last_processed_decision_ids") or closed)},
        {"step": "risk", "evidence": "risk_metrics reason distribution", "available": bool(state.get("risk_metrics"))},
        {"step": "trade", "evidence": "closed_trades with decision refs", "available": bool(closed)},
        {"step": "outcome", "evidence": "canonical realized PnL", "available": state.get("realized_pnl") is not None},
    ]
    full = all(c["available"] for c in chain)
    return {
        "RUN_REPLAY": "FUNCTIONAL" if full else "PARTIAL",
        "run_level_replay_cli": "NOT_IMPLEMENTED_IN_HEAD",
        "chain": chain,
        "note": "no fake replay is generated; only artifact-backed steps are marked available",
    }
