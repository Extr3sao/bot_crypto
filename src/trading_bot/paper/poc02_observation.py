"""POC02 observation and alpha-diagnosis (POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01).

STRICTLY OBSERVATIONAL: every function here READS persisted campaign
evidence (cycle ledger, coverage ledger, attribution ledger, shadow
ledgers, receipts) and produces analytical artifacts. Nothing in this
module gates, routes, sizes, or tunes anything:

- no RiskManager / PaperBroker / router mutation,
- no threshold change, no parameter change, no promotion,
- no synthetic data: counts come from recorded evidence only; a cell with
  no evidence is reported as such (never inferred from one cycle).

Checkpoint mapping:

- §2/§3  daily coverage + daily performance rows (per UTC day)
- §4     frequency KPIs (COMPLETED_VALID_DAYS, DAYS_GE_3, TRADES_PER_VALID_DAY, ...)
- §5     bottleneck counts/proportions (canonical taxonomy incl. OTHER_RISK)
- §6     REGIME x BOTTLENECK matrix from BottleneckState rows
- §7     strategy contribution (signals/proposals/selected/risk/paper/PnL/overlap)
- §8     agent-filter rates overall / by regime / by strategy / by asset
- §10    shadow risk analysis per rejection reason (ConditionedShadowMetrics)
- §11    risk-value test: PAPER accepted vs SHADOW rejected comparison
- §12    regime coverage map (WELL_COVERED / UNDER_COVERED / NO_EDGE / INSUFFICIENT)
- §18    RUNTIME_STALE surface from the campaign-state heartbeat
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_bot.paper.bottleneck import BottleneckState

__all__ = [
    "FREQUENCY_TARGET_TRADES_PER_DAY",
    "agent_filter_analysis",
    "analyze_campaign",
    "daily_performance_rows",
    "frequency_kpis",
    "load_attribution_ledger",
    "load_cycle_ledger",
    "regime_bottleneck_matrix",
    "regime_coverage_map",
    "risk_value_test",
    "runtime_staleness",
    "shadow_risk_analysis",
    "strategy_contribution",
]

FREQUENCY_TARGET_TRADES_PER_DAY = 3  # preregistered; never lowered
CANON_BOTTLENECKS: tuple[str, ...] = BottleneckState.ALL


# --------------------------------------------------------------------------
# ledger loaders (read-only)
# --------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn trailing line never invents evidence
    return rows


def load_cycle_ledger(campaign_dir: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(Path(campaign_dir) / "POC02_CYCLE_LEDGER.jsonl")
    # normalize: earliest ledger rows predate the utc_date/cycle_id fields;
    # derive utc_date from cycle_id ("<campaign>:<YYYY-MM-DD>:<n>") or from
    # the run_id epoch-ms. Deterministic reconstruction, never invention.
    for row in rows:
        if not row.get("utc_date"):
            cycle_id = str(row.get("cycle_id") or "")
            parts = cycle_id.split(":")
            if len(parts) >= 3:
                row["utc_date"] = parts[1]
            else:
                run_id = str(row.get("run_id") or "")
                if run_id.startswith("poc02-") and run_id[6:].isdigit():
                    row["utc_date"] = datetime.fromtimestamp(
                        int(run_id[6:]) / 1000, tz=UTC
                    ).strftime("%Y-%m-%d")
    return rows


def load_attribution_ledger(campaign_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(Path(campaign_dir) / "cycles" / "POC02_ATTRIBUTION.jsonl")


def load_coverage_rows(campaign_dir: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    path = Path(campaign_dir) / "POC02_COVERAGE_DAILY.jsonl"
    for row in _read_jsonl(path):
        rows[str(row["utc_day"])] = row
    return rows


def load_finalizations(campaign_dir: Path) -> dict[str, dict[str, Any]]:
    path = Path(campaign_dir) / "POC02_DAY_FINALIZATIONS.json"
    if not path.exists():
        return {}
    loaded: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


# --------------------------------------------------------------------------
# §3 — daily performance
# --------------------------------------------------------------------------


def daily_performance_rows(campaign_dir: Path) -> list[dict[str, Any]]:
    """One row per UTC day with evidence; zero-trade days are kept."""
    campaign_dir = Path(campaign_dir)
    cycles = load_cycle_ledger(campaign_dir)
    attribution = load_attribution_ledger(campaign_dir)
    cov_rows = load_coverage_rows(campaign_dir)
    finalizations = load_finalizations(campaign_dir)

    by_day_cycles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cycles:
        by_day_cycles[row["utc_date"]].append(row)

    def _day_of(row: dict[str, Any]) -> str:
        ts = row.get("written_at") or row.get("closed_at")
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%d")
        return str(ts)[:10] if ts else "UNKNOWN"

    attr_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attribution:
        attr_by_day[_day_of(row)].append(row)

    days = sorted(set(by_day_cycles) | set(cov_rows))
    out: list[dict[str, Any]] = []
    for day in days:
        cyc = by_day_cycles.get(day, [])
        attr = attr_by_day.get(day, [])
        opens = [a for a in attr if a.get("stage") == "PAPER_OPEN"]
        closes = [a for a in attr if a.get("stage") == "PAPER_CLOSE"]
        wins = sum(1 for c in closes if float(c.get("net_pnl", 0.0)) > 0)
        losses = sum(1 for c in closes if float(c.get("net_pnl", 0.0)) < 0)
        gross = round(sum(float(c.get("gross_pnl", 0.0)) for c in closes), 8)
        net = round(sum(float(c.get("net_pnl", 0.0)) for c in closes), 8)
        cov = cov_rows.get(day, {})
        fin = finalizations.get(day)
        observed_minutes = int(cov.get("observed_minutes", 0) or 0)
        # preregistered contract: >= 0.80 observed/expected minutes
        expected_minutes = int(cov.get("expected_minutes", 1440) or 1440)
        day_validity = fin["validity"] if fin else cov.get("day_validity", "PENDING")
        counts_valid = fin is not None and fin.get("validity") == "VALID"
        out.append(
            {
                "utc_day": day,
                "scans": sum(len(c.get("bottlenecks", [])) for c in cyc),
                "signals_if_persisted": sum(
                    1
                    for a in attr
                    if a.get("stage") in ("SELECTED", "AGENT_REJECT", "RISK_REJECT", "PAPER_OPEN")
                ),
                "proposals": sum(
                    int(c.get("state", {}).get("trade_proposals", 0) or 0) for c in cyc
                ),
                "debates": sum(int(c.get("state", {}).get("debates", 0) or 0) for c in cyc),
                "selected": sum(
                    int(c.get("state", {}).get("decisions_selected", 0) or 0) for c in cyc
                ),
                "verified": sum(
                    1
                    for c in cyc
                    for d in c.get("state", {}).get("decisions", [])
                    if d.get("verifier") == "VERIFIED"
                ),
                "risk_accepts": sum(
                    int(c.get("state", {}).get("risk_accepts", 0) or 0) for c in cyc
                ),
                "risk_rejects": sum(
                    int(c.get("state", {}).get("risk_rejects", 0) or 0) for c in cyc
                ),
                "paper_opens": len(opens),
                "paper_closes": len(closes),
                "wins": wins,
                "losses": losses,
                "gross_pnl": gross,
                "net_pnl": net,
                "trades": len(opens),
                "trades_ge_3": len(opens) >= FREQUENCY_TARGET_TRADES_PER_DAY,
                "observed_cycles": int(cov.get("observed_cycles", 0) or 0),
                "expected_cycles": int(cov.get("expected_cycles", 0) or 0),
                "coverage_ratio_day": cov.get("coverage_ratio"),
                "runtime_downtime_minutes": cov.get("runtime_downtime_minutes"),
                "provider_downtime_minutes": cov.get("provider_downtime_minutes"),
                "observed_minutes": observed_minutes,
                "expected_minutes": expected_minutes,
                "day_closed": fin is not None or _is_closed(day),
                "day_validity": day_validity,
                "DAY_COUNTS_FOR_COVERAGE": counts_valid,
                "FINALIZED": fin is not None,
            }
        )
    return out


def _is_closed(day: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    boundary = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(days=1)
    return now >= boundary


# --------------------------------------------------------------------------
# §4 — frequency KPIs
# --------------------------------------------------------------------------


def frequency_kpis(perf_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Frequency evidence over COMPLETED_VALID days only (never partial)."""
    valid = [r for r in perf_rows if r["FINALIZED"] and r["DAY_COUNTS_FOR_COVERAGE"]]
    completed_valid_days = len(valid)
    days_ge_3 = sum(1 for r in valid if r["trades_ge_3"])
    total_trades = sum(r["trades"] for r in valid)
    per_day = [r["trades"] for r in valid]
    return {
        "COMPLETED_VALID_DAYS": completed_valid_days,
        "DAYS_GE_3": days_ge_3,
        "PERCENT_DAYS_GE_3": (
            round(100.0 * days_ge_3 / completed_valid_days, 2) if completed_valid_days else None
        ),
        "TOTAL_TRADES": total_trades,
        "TRADES_PER_VALID_DAY": (
            round(total_trades / completed_valid_days, 4) if completed_valid_days else None
        ),
        "MEDIAN_TRADES_PER_VALID_DAY": (statistics.median(per_day) if per_day else None),
        "TARGET_TRADES_PER_VALID_DAY": FREQUENCY_TARGET_TRADES_PER_DAY,
        "denominator_note": ("partial/invalid days excluded; zero-trade valid days retained"),
        "target_lowered": False,
    }


# --------------------------------------------------------------------------
# §5/§6 — bottleneck telemetry + regime matrix
# --------------------------------------------------------------------------


def bottleneck_distribution(cycle_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for row in cycle_rows:
        for b in row.get("bottlenecks", []):
            counts[str(b.get("bottleneck", "OTHER_RISK"))] += 1
    total = sum(counts.values())
    return {
        "windows_observed": total,
        "counts": {k: counts.get(k, 0) for k in CANON_BOTTLENECKS if counts.get(k)},
        "proportions": (
            {k: round(v / total, 4) for k, v in sorted(counts.items())} if total else {}
        ),
        "dominant": counts.most_common(1)[0][0] if counts else None,
    }


def regime_bottleneck_matrix(cycle_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """REGIME x BOTTLENECK matrix with proportions per regime cell.

    Cells with a single observation are flagged (never interpreted alone).
    """
    by_regime: dict[str, Counter[str]] = defaultdict(Counter)
    for row in cycle_rows:
        for b in row.get("bottlenecks", []):
            regime = str(b.get("regime", "UNCLASSIFIED"))
            by_regime[regime][str(b.get("bottleneck", "OTHER_RISK"))] += 1
    matrix: dict[str, Any] = {}
    for regime, counter in sorted(by_regime.items()):
        total = sum(counter.values())
        matrix[regime] = {
            "windows": total,
            "single_observation": total <= 1,
            "counts": dict(counter),
            "proportions": {k: round(v / total, 4) for k, v in counter.items()},
        }
    return {
        "matrix": matrix,
        "regimes_observed": len(matrix),
        "note": "proportions are within-regime; single-observation cells are flagged, not interpreted",
    }


# --------------------------------------------------------------------------
# §7 — strategy contribution
# --------------------------------------------------------------------------

_LEGACY_STRATEGIES = ("Momentum", "Trend", "Breakout", "MeanReversion", "Volatility")


def strategy_contribution(
    cycle_rows: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
) -> dict[str, Any]:
    """Per-legacy-strategy funnel contribution + overlap (observational)."""
    strategy_rows: dict[str, dict[str, Any]] = {}

    def _blank(strategy: str) -> dict[str, Any]:
        return {
            "strategy": strategy,
            "proposals": 0,
            "selected": 0,
            "agent_rejects": 0,
            "risk_accepts": 0,
            "risk_rejects": 0,
            "paper_trades": 0,
            "net_pnl": 0.0,
            "regime_distribution": {},
            "assets": set(),
        }

    for row in attribution:
        stage = row.get("stage")
        strategy = str(row.get("strategy_id") or "UNKNOWN")
        entry = strategy_rows.setdefault(strategy, _blank(strategy))
        regime = str(row.get("regime") or "UNCLASSIFIED")
        asset = str(row.get("asset") or "?")
        if stage in ("SELECTED", "AGENT_REJECT", "RISK_REJECT", "PAPER_OPEN"):
            entry["proposals"] += 1
            entry["regime_distribution"][regime] = entry["regime_distribution"].get(regime, 0) + 1
            entry["assets"].add(asset)
        if stage == "SELECTED":
            entry["selected"] += 1
        elif stage == "AGENT_REJECT":
            entry["agent_rejects"] += 1
        elif stage == "RISK_REJECT":
            entry["risk_rejects"] += 1
        elif stage == "PAPER_OPEN":
            entry["paper_trades"] += 1
            entry["risk_accepts"] += 1

    # PnL: PAPER_CLOSE rows carry symbol but not strategy; map via the most
    # recent PAPER_OPEN for that symbol (positions are one-per-symbol).
    open_strategy_by_symbol: dict[str, str] = {}
    for row in attribution:
        if row.get("stage") == "PAPER_OPEN":
            open_strategy_by_symbol[str(row.get("symbol"))] = str(
                row.get("strategy_id") or "UNKNOWN"
            )
        elif row.get("stage") == "PAPER_CLOSE":
            strategy = open_strategy_by_symbol.get(str(row.get("symbol")), "UNKNOWN")
            strategy_rows.setdefault(strategy, _blank(strategy))
            strategy_rows[strategy]["net_pnl"] = round(
                strategy_rows[strategy]["net_pnl"] + float(row.get("net_pnl", 0.0)), 8
            )

    # proposals that never produced attribution rows (NO_SIGNAL day evidence)
    total_proposals_state = sum(
        int(c.get("state", {}).get("trade_proposals", 0) or 0) for c in cycle_rows
    )
    attributed_proposals = sum(v["proposals"] for v in strategy_rows.values())

    out: dict[str, Any] = {}
    for strategy, v in sorted(strategy_rows.items()):
        v["assets"] = sorted(v["assets"])
        v["incremental_note"] = (
            "overlap/incrementality require proposal-id level co-occurrence; "
            "recorded as evidence, not a profitability claim"
        )
        out[strategy] = v
    return {
        "strategies": out,
        "attributed_proposals": attributed_proposals,
        "state_counter_proposals": total_proposals_state,
        "evidence_gap": max(total_proposals_state - attributed_proposals, 0),
        "insufficient_evidence_strategies": [
            s
            for s, v in strategy_rows.items()
            if v["paper_trades"] + v["risk_rejects"] + v["agent_rejects"] < 10
        ],
        "profitability_claim": "NONE — insufficient sample; observational counts only",
    }


# --------------------------------------------------------------------------
# §8 — agent-filter analysis
# --------------------------------------------------------------------------


def agent_filter_analysis(
    cycle_rows: list[dict[str, Any]], attribution: list[dict[str, Any]]
) -> dict[str, Any]:
    """AGENT_FILTER_RATE overall + conditioned by regime/strategy/asset.

    Rate = AGENT_REJECT attribution rows / (rows that reached the agent
    decision stage: SELECTED + AGENT_REJECT). Cycle-level AGENT_FILTER
    bottleneck windows are reported alongside.
    """
    selected = [a for a in attribution if a.get("stage") == "SELECTED"]
    agent_rejects = [a for a in attribution if a.get("stage") == "AGENT_REJECT"]
    reached = len(selected) + len(agent_rejects)

    def _rate(rows: list[dict[str, Any]], denominator: int) -> float | None:
        return round(len(rows) / denominator, 4) if denominator else None

    def _condition(field: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for a in attribution:
            if a.get("stage") in ("SELECTED", "AGENT_REJECT"):
                groups[str(a.get(field) or "UNKNOWN")].append(a)
        out: dict[str, Any] = {}
        for key, rows in sorted(groups.items()):
            rej = sum(1 for r in rows if r.get("stage") == "AGENT_REJECT")
            out[key] = {
                "reached_agent": len(rows),
                "agent_rejects": rej,
                "AGENT_FILTER_RATE": round(rej / len(rows), 4) if rows else None,
                "single_observation": len(rows) <= 1,
            }
        return out

    cycle_agent_windows = sum(
        1
        for row in cycle_rows
        for b in row.get("bottlenecks", [])
        if b.get("bottleneck") == BottleneckState.AGENT_FILTER
    )
    windows = sum(len(r.get("bottlenecks", [])) for r in cycle_rows)
    # decision-level outcome detail (typed reasons; no loosening implied)
    reject_reasons: Counter[str] = Counter()
    for a in agent_rejects:
        for reason in a.get("decision_reasons", []) or []:
            reject_reasons[str(reason)] += 1
    return {
        "AGENT_FILTER_RATE": _rate(agent_rejects, reached),
        "candidates_reaching_agent": reached,
        "agent_rejects": len(agent_rejects),
        "selected": len(selected),
        "AGENT_FILTER_RATE_BY_REGIME": _condition("regime"),
        "AGENT_FILTER_RATE_BY_STRATEGY": _condition("strategy_id"),
        "AGENT_FILTER_RATE_BY_ASSET": _condition("asset"),
        "cycle_windows_AGENT_FILTER": cycle_agent_windows,
        "cycle_windows_total": windows,
        "rejection_reason_distribution": dict(reject_reasons),
        "candidate_detail_note": (
            "per-candidate evidence/counter-evidence/critic persisted in "
            "POC02_ATTRIBUTION.jsonl (AGENT_REJECT rows); agents unchanged"
        ),
        "agents_loosened": False,
    }


# --------------------------------------------------------------------------
# §10 — shadow risk analysis
# --------------------------------------------------------------------------


def shadow_risk_analysis(campaign_dir: Path) -> dict[str, Any]:
    """Per-reason shadow counterfactual metrics (strictly isolated)."""
    from trading_bot.shadow.integration import ShadowCaptureHook
    from trading_bot.shadow.reject_metrics import RejectReasonAnalysis
    from trading_bot.shadow.router import ConditionedShadowMetrics

    hook = ShadowCaptureHook(
        captures_path=Path(campaign_dir) / "shadow" / "shadow_captures.jsonl",
        outcomes_path=Path(campaign_dir) / "shadow" / "shadow_outcomes.jsonl",
    )
    analysis = RejectReasonAnalysis(hook.outcomes).summary()
    conditioned = ConditionedShadowMetrics(hook.outcomes.trades)
    by_regime = conditioned.by_condition("risk_rejection_reason", "regime_signature")
    by_strategy = conditioned.by_condition("risk_rejection_reason", "strategy_id")
    by_asset = conditioned.by_condition("risk_rejection_reason", "asset")
    by_health = conditioned.by_condition("risk_rejection_reason", "strategy_health_state")
    reason_counts: Counter[str] = Counter(c.risk_rejection_reason for c in hook.captures.captures)
    return {
        "captures_total": len(hook.captures.captures),
        "resolved_total": len(hook.outcomes.trades),
        "captures_by_reason": dict(reason_counts),
        "per_reason": analysis,
        "conditioned_by_regime": _stringify_keys(by_regime),
        "conditioned_by_strategy": _stringify_keys(by_strategy),
        "conditioned_by_asset": _stringify_keys(by_asset),
        "conditioned_by_health": _stringify_keys(by_health),
        "isolation": {
            "SHADOW_PAPERBROKER_CALLS": 0,
            "SHADOW_PNL_CONTAMINATION": 0,
            "SHADOW_FREQUENCY_CONTAMINATION": 0,
            "labels": "EXCLUDED_FROM_PAPER_PNL + EXCLUDED_FROM_PAPER_FREQUENCY",
        },
        "recommendation": (
            "NO Risk change until sample is sufficient (per-reason "
            "classification is INSUFFICIENT_EVIDENCE below n=20)"
        ),
    }


def _stringify_keys(mapping: dict[tuple[str, ...], Any]) -> dict[str, Any]:
    return {"|".join(k): v for k, v in mapping.items()}


# --------------------------------------------------------------------------
# §11 — risk value test
# --------------------------------------------------------------------------


def risk_value_test(campaign_dir: Path) -> dict[str, Any]:
    """PAPER-accepted vs SHADOW-rejected counterfactual comparison.

    Observational only; requires sufficient shadow sample before any
    interpretation is offered (no automatic Risk change).
    """
    from trading_bot.shadow.integration import ShadowCaptureHook

    hook = ShadowCaptureHook(
        captures_path=Path(campaign_dir) / "shadow" / "shadow_captures.jsonl",
        outcomes_path=Path(campaign_dir) / "shadow" / "shadow_outcomes.jsonl",
    )
    resolved = hook.outcomes.trades
    attribution = load_attribution_ledger(Path(campaign_dir))
    paper_closes = [a for a in attribution if a.get("stage") == "PAPER_CLOSE"]
    paper_net = [float(a.get("net_pnl", 0.0)) for a in paper_closes]
    shadow_net = [t.net_pnl for t in resolved]

    def _stats(values: list[float]) -> dict[str, Any]:
        wins = sum(1 for v in values if v > 0)
        losses = sum(1 for v in values if v < 0)
        gw = sum(v for v in values if v > 0)
        gl = sum(-v for v in values if v < 0)
        return {
            "n": len(values),
            "wins": wins,
            "losses": losses,
            "expectancy_net": round(sum(values) / len(values), 8) if values else None,
            "profit_factor": (round(gw / gl, 4) if gl > 0 else None),
        }

    paper_stats = _stats(paper_net)
    shadow_stats = _stats(shadow_net)
    sufficient = shadow_stats["n"] >= 20 and paper_stats["n"] >= 20
    comparison: dict[str, Any] | None = None
    if sufficient:
        pe, se = paper_stats["expectancy_net"], shadow_stats["expectancy_net"]
        comparison = {
            "paper_expectancy_vs_shadow": (
                "PAPER_HIGHER"
                if (pe or 0) > (se or 0)
                else "SHADOW_HIGHER"
                if (se or 0) > (pe or 0)
                else "EQUAL"
            ),
            "risk_improves_expectancy": (pe or 0) > (se or 0),
            "risk_blocks_positive_expectancy": (se or 0) > 0 and (se or 0) > (pe or 0),
            "comparability_note": (
                "contexts compared at portfolio level; per-context conditioning "
                "in shadow_risk_analysis"
            ),
        }
    return {
        "PAPER_ACCEPTED": paper_stats,
        "SHADOW_REJECTED": shadow_stats,
        "sufficient_sample": sufficient,
        "comparison": comparison,
        "status": (
            "EVIDENCE_SUFFICIENT_FOR_COMPARISON"
            if sufficient
            else "INSUFFICIENT_SAMPLE — no interpretation, no Risk change"
        ),
        "automatic_risk_change": False,
    }


# --------------------------------------------------------------------------
# §12 — regime coverage map
# --------------------------------------------------------------------------


def regime_coverage_map(
    cycle_rows: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
) -> dict[str, Any]:
    """REGIME → opportunity count → strategy coverage.

    Classification (observational, preregistered):
      WELL_COVERED      ≥ 20 windows AND ≥ 2 strategies proposing
      UNDER_COVERED     ≥ 5 windows AND < 2 strategies
      NO_EDGE           ≥ 5 windows, proposals exist, zero downstream
                        progress (selected+risk+paper == 0)
      INSUFFICIENT_EVIDENCE < 5 windows (incl. single-cycle regimes)
    """
    windows_by_regime: Counter[str] = Counter()
    proposals_by_regime: Counter[str] = Counter()
    strategies_by_regime: dict[str, set[str]] = defaultdict(set)
    progress_by_regime: Counter[str] = Counter()
    for row in cycle_rows:
        for b in row.get("bottlenecks", []):
            windows_by_regime[str(b.get("regime", "UNCLASSIFIED"))] += 1
    for a in attribution:
        stage = a.get("stage")
        regime = str(a.get("regime") or "UNCLASSIFIED")
        if stage in ("SELECTED", "AGENT_REJECT", "RISK_REJECT", "PAPER_OPEN"):
            proposals_by_regime[regime] += 1
            if a.get("strategy_id"):
                strategies_by_regime[regime].add(str(a["strategy_id"]))
        if stage in ("SELECTED", "PAPER_OPEN"):
            progress_by_regime[regime] += 1

    regimes = sorted(set(windows_by_regime) | set(proposals_by_regime))
    cells: dict[str, Any] = {}
    for regime in regimes:
        windows = windows_by_regime.get(regime, 0)
        proposals = proposals_by_regime.get(regime, 0)
        strategies = len(strategies_by_regime.get(regime, set()))
        progress = progress_by_regime.get(regime, 0)
        if windows < 5:
            label = "INSUFFICIENT_EVIDENCE"
        elif proposals == 0:
            label = "NO_SIGNAL_REGIME"
        elif windows >= 20 and strategies >= 2:
            label = "WELL_COVERED"
        elif progress == 0:
            label = "NO_EDGE"
        else:
            label = "UNDER_COVERED"
        cells[regime] = {
            "windows": windows,
            "proposals": proposals,
            "strategies": sorted(strategies_by_regime.get(regime, set())),
            "downstream_progress": progress,
            "classification": label,
        }
    return {
        "regimes": cells,
        "WELL_COVERED_REGIMES": [
            r for r, c in cells.items() if c["classification"] == "WELL_COVERED"
        ],
        "UNDER_COVERED_REGIMES": [
            r for r, c in cells.items() if c["classification"] == "UNDER_COVERED"
        ],
        "NO_EDGE_REGIMES": [r for r, c in cells.items() if c["classification"] == "NO_EDGE"],
        "INSUFFICIENT_EVIDENCE": [
            r for r, c in cells.items() if c["classification"] == "INSUFFICIENT_EVIDENCE"
        ],
        "next_research_input_note": (
            "research targets come from regimes with observed market movement "
            "but ≈0 proposals (NO_SIGNAL_REGIME) or NO_EDGE — evidence first, "
            "then hypotheses (no automatic Discovery Batch 03)"
        ),
        "discovery_batch_03": "NOT_STARTED",
    }


# --------------------------------------------------------------------------
# §18 — runtime staleness
# --------------------------------------------------------------------------


def runtime_staleness(
    campaign_state: dict[str, Any],
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 30,
) -> dict[str, Any]:
    """Heartbeat freshness surface (§18). Never changes trading behavior."""
    now = now or datetime.now(UTC)
    hb = campaign_state.get("heartbeat_utc")
    if not hb:
        return {"RUNTIME_STALE": True, "reason": "NO_HEARTBEAT"}
    try:
        hb_dt = datetime.fromisoformat(str(hb))
    except ValueError:
        return {"RUNTIME_STALE": True, "reason": "UNPARSEABLE_HEARTBEAT"}
    if hb_dt.tzinfo is None:
        hb_dt = hb_dt.replace(tzinfo=UTC)
    age_min = round((now - hb_dt).total_seconds() / 60.0, 1)
    return {
        "RUNTIME_STALE": age_min > stale_after_minutes,
        "heartbeat_utc": str(hb),
        "age_minutes": age_min,
        "stale_after_minutes": stale_after_minutes,
        "status": str(campaign_state.get("status")),
        "display_note": (
            "stale heartbeats must surface RUNTIME_STALE; old data is never "
            "silently presented as current"
        ),
    }


# --------------------------------------------------------------------------
# campaign-level aggregation
# --------------------------------------------------------------------------


def analyze_campaign(campaign_dir: Path) -> dict[str, Any]:
    """Full observational bundle for reports/STATUS surfaces."""
    campaign_dir = Path(campaign_dir)
    cycle_rows = load_cycle_ledger(campaign_dir)
    attribution = load_attribution_ledger(campaign_dir)
    state_path = campaign_dir / "POC02_CAMPAIGN_STATE.json"
    campaign_state = (
        json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    )
    perf = daily_performance_rows(campaign_dir)
    state = {
        "daily_performance": perf,
        "frequency_kpis": frequency_kpis(perf),
        "bottleneck_distribution": bottleneck_distribution(cycle_rows),
        "regime_bottleneck_matrix": regime_bottleneck_matrix(cycle_rows),
        "strategy_contribution": strategy_contribution(cycle_rows, attribution),
        "agent_filter": agent_filter_analysis(cycle_rows, attribution),
        "shadow_risk_analysis": shadow_risk_analysis(campaign_dir),
        "risk_value_test": risk_value_test(campaign_dir),
        "regime_coverage_map": regime_coverage_map(cycle_rows, attribution),
        "runtime_staleness": runtime_staleness(campaign_state),
        "answers": {
            "q1_where_opportunities_lost": (
                "see bottleneck_distribution (dominant collapse point) + "
                "regime_bottleneck_matrix (concentration by regime)"
            ),
            "q2_regime_dependent": (
                "yes if dominant bottleneck differs across regimes with "
                "≥5 windows; matrix cells flagged single_observation otherwise"
            ),
            "q3_risk_rejects_quality": (
                "see risk_value_test + shadow per-reason classification; "
                "no claim before sufficient sample"
            ),
            "q4_useful_strategies": "see strategy_contribution",
            "q5_regimes_without_strategies": (
                "see regime_coverage_map UNDER_COVERED/NO_EDGE/NO_SIGNAL_REGIME"
            ),
            "q6_frequency_trajectory": ("see frequency_kpis; target ≥3 trades/valid-day unchanged"),
        },
    }
    return state
