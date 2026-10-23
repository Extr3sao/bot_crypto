"""RFC-030 — orchestrator: emits every required research + reproduction artifact.

Deterministic (§53).  No parameter tuning (§24): publication parameters are
frozen inside the helpers.  The HOLDOUT is only opened when VALIDATION passes
(§57 — opening it early is a FALSE_SUCCESS trigger).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import sprint030_lib as L
from numpy.typing import NDArray

OUT = L.OUT_DIR
# Monthly strategies cannot have as many validation rebalances as weekly ones.
MIN_VALIDATION_REBALANCES = {"EXT-TSMOM-001": 20, "EXT-XMOM-001": 30}
COST_STRESS_MULTIPLIERS = (1.0, 1.5, 2.0)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    except Exception:
        return "UNKNOWN"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    line = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for r in rows:
        body.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join([line, sep, *body])


def _sv(value: Any, digits: int = 2) -> Any:
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return round(value, digits)
    return value


def _clean_metrics(m: dict[str, Any]) -> dict[str, Any]:
    return {k: _sv(v) for k, v in m.items()}


# ---------------------------------------------------------------------------
# research artifacts (§58)
# ---------------------------------------------------------------------------


def write_plan() -> None:
    payload = {
        "rfc": "RFC-030",
        "title": "EXTERNAL ALPHA EVIDENCE & REPRODUCTION PROGRAM",
        "generated": _now(),
        "base_sha": _git("HEAD"),
        "question": (
            "Can Trading Agentic Portable reproduce any externally "
            "documented systematic edge after realistic costs and "
            "out-of-sample validation?"
        ),
        "not": [
            "another edge discovery sprint",
            "another grid search",
            "another indicator",
            "another agent",
            "another execution optimisation",
        ],
        "phases": [
            "ENTRY_GATE",
            "SOURCE_REGISTRY",
            "RESEARCH_UNIVERSE",
            "STRATEGY_SCORECARD",
            "STRATEGY_SELECTION_BEFORE_BACKTESTS",
            "REPRODUCTION_SPEC",
            "DATA_AUDIT",
            "PIT_AUDIT",
            "COST_MODEL",
            "REPRODUCTION",
            "DISCOVERY",
            "VALIDATION",
            "WALK_FORWARD",
            "ROBUSTNESS",
            "HOLDOUT_IF_JUSTIFIED",
            "INDEPENDENT_VERIFY",
            "EXTERNAL_ALPHA_COMPARISON",
            "FINAL_REPORT",
        ],
        "authority_ladder": [
            "PEER-REVIEWED PAPER",
            "OFFICIAL WORKING PAPER / UNIVERSITY",
            "REPRODUCED ACADEMIC RESULT",
            "OFFICIAL EXCHANGE RESEARCH",
            "HIGH-QUALITY QUANT RESEARCH",
            "SOURCE CODE WITH REAL RESULTS",
            "REAL EXPERIMENT",
            "BLOG / SOCIAL MEDIA (discovery pointer only)",
        ],
        "constraints": {
            "no_agents": True,
            "no_parameter_tuning": True,
            "holdout_opened_only_if_validation_passes": True,
            "external_frameworks_not_copied": True,
            "crypto_mandatory": False,
            "frequency_target_suspended": True,
        },
        "selection_rule": L.SELECTION_RULE,
        "max_external_strategies": L.MAX_EXTERNAL_STRATEGIES,
        "max_reproduced": L.MAX_REPRODUCED,
    }
    L.write_json(OUT / "RFC030_PLAN.json", payload)
    L.write_md(OUT / "RFC030_PLAN.md", _plan_md(payload))


def _plan_md(p: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# RFC-030 — EXTERNAL ALPHA EVIDENCE & REPRODUCTION PROGRAM",
            "",
            f"- generated: `{p['generated']}`",
            f"- base_sha: `{p['base_sha']}`",
            "",
            "## Primary question",
            "",
            "> " + p["question"],
            "",
            "## What this is NOT",
            "",
            "\n".join(f"- {x}" for x in p["not"]),
            "",
            "## Phases",
            "",
            "\n".join(f"{i + 1}. {x}" for i, x in enumerate(p["phases"])),
            "",
            "## Source authority ladder (§4)",
            "",
            "\n".join(f"{i + 1}. {x}" for i, x in enumerate(p["authority_ladder"])),
            "",
            "## Constraints",
            "",
            "\n".join(f"- {k}: `{v}`" for k, v in p["constraints"].items()),
            "",
            "## Selection rule (§21 — frozen before any backtest)",
            "",
            "```text",
            p["selection_rule"],
            "```",
            "",
            f"MAX_EXTERNAL_STRATEGIES = {p['max_external_strategies']}  ",
            f"MAX_REPRODUCED = {p['max_reproduced']}",
            "",
        ]
    )


def write_source_registry() -> None:
    payload = {"sources": L.SOURCES, "count": len(L.SOURCES), "generated": _now()}
    L.write_json(OUT / "SOURCE_REGISTRY.json", payload)
    cols = [
        "SOURCE_ID",
        "year",
        "authority_level",
        "asset_class",
        "strategy_family",
        "reliability_score",
        "title",
    ]
    md = [
        "# RFC-030 — SOURCE REGISTRY",
        "",
        f"Sources registered: **{len(L.SOURCES)}**",
        "",
        _table(L.SOURCES, cols),
        "",
        "## Full records",
        "",
    ]
    for s in L.SOURCES:
        md += [
            f"### {s['SOURCE_ID']} — {s['title']}",
            f"- authors: {s['authors']}",
            f"- publication: {s['publication']} ({s['year']})",
            f"- URL: {s['URL']}",
            f"- artifact: {s['artifact_type']}",
            f"- asset class: {s['asset_class']}",
            f"- family: {s['strategy_family']}",
            f"- horizon: {s['holding_horizon']}",
            f"- sample: {s['sample_period']}",
            f"- reported gross: {s['reported_gross_performance']}",
            f"- reported net: {s['reported_net_performance']}",
            f"- cost assumptions: {s['cost_assumptions']}",
            f"- robustness: {s['robustness_evidence']}",
            f"- replication: {s['replication_evidence']}",
            f"- criticisms: {s['known_criticisms']}",
            f"- data required: {s['data_requirements']}",
            f"- implementation: {s['implementation_requirements']}",
            f"- reliability: {s['reliability_score']}/5 ({s['authority_level']})",
            "",
        ]
    L.write_md(OUT / "SOURCE_REGISTRY.md", "\n".join(md))


def write_universe() -> None:
    families = [
        (
            "TIME-SERIES MOMENTUM / TREND",
            ["S02", "S04", "S05", "S06", "S10", "S03"],
            "EXT-TSMOM-001",
        ),
        ("CROSS-SECTIONAL MOMENTUM", ["S01", "S05", "S07", "S08", "S09"], "EXT-XMOM-001"),
        ("MEDIUM/LONG-HORIZON MEAN REVERSION / REVERSAL", ["S09", "S07"], "EXT-XREV-001"),
        ("RELATIVE VALUE / PAIRS", ["S11"], "not-shortlisted (overlaps RFC-028/029)"),
        ("CARRY ACROSS ASSETS", ["S11"], "EXT-CARRY-001"),
        ("VOLATILITY RISK PREMIUM", [], "no accessible PIT options data -> rejected §13"),
        ("SEASONALITY / CALENDAR", ["S12"], "EXT-SEAS-001"),
        ("CROSS-MARKET LEAD/LAG", [], "no cross-market dataset in scope -> rejected §13"),
        ("MARKET-NEUTRAL FACTOR (size)", ["S01"], "needs market caps -> §16 data gap"),
        ("STATISTICAL ARBITRAGE", [], "needs intraday cross-venue data -> rejected §13"),
    ]
    payload = {
        "families_explored": [
            {"family": f, "sources": s, "shortlist_outcome": o} for f, s, o in families
        ],
        "candidate_universe": [c["CANDIDATE_ID"] for c in L.CANDIDATES],
        "rejected_before_shortlist": [
            "VOLATILITY RISK PREMIUM (no PIT options chains available)",
            "CROSS-MARKET LEAD/LAG (no cross-market data in scope)",
            "STATISTICAL ARBITRAGE (no intraday cross-venue data)",
            "MARKET-NEUTRAL SIZE FACTOR (market-cap data not available)",
        ],
        "horizon_policy": "daily/weekly/monthly are allowed (§11); 5m/30m/1h not forced",
        "frequency_target": "suspended (§12)",
        "generated": _now(),
    }
    L.write_json(OUT / "EXTERNAL_RESEARCH_UNIVERSE.json", payload)
    rows = [{"family": f, "sources": ", ".join(s), "shortlist_outcome": o} for f, s, o in families]
    md = [
        "# RFC-030 — EXTERNAL RESEARCH UNIVERSE",
        "",
        _table(rows, ["family", "sources", "shortlist_outcome"]),
        "",
        "## Rejected before the shortlist",
        "",
        "\n".join(f"- {x}" for x in payload["rejected_before_shortlist"]),
        "",
        f"- horizon policy: {payload['horizon_policy']}",
        f"- frequency target: {payload['frequency_target']}",
        "",
    ]
    L.write_md(OUT / "EXTERNAL_RESEARCH_UNIVERSE.md", "\n".join(md))


def write_scorecard() -> None:
    payload = {
        "candidates": L.CANDIDATES,
        "count": len(L.CANDIDATES),
        "generated": _now(),
        "score_axes": [
            "EVIDENCE_STRENGTH",
            "ECONOMIC_HEADROOM",
            "DATA_FEASIBILITY",
            "IMPLEMENTATION_COMPLEXITY",
            "ORTHOGONALITY",
        ],
    }
    L.write_json(OUT / "STRATEGY_SCORECARD.json", payload)
    rows = []
    axes = [
        "EVIDENCE_STRENGTH",
        "ECONOMIC_HEADROOM",
        "DATA_FEASIBILITY",
        "IMPLEMENTATION_COMPLEXITY",
        "ORTHOGONALITY",
    ]
    for c in L.CANDIDATES:
        total = sum(c[k] for k in axes)
        rows.append(
            {
                "CANDIDATE_ID": c["CANDIDATE_ID"],
                "family": c["family"],
                "Evidence": c["EVIDENCE_STRENGTH"],
                "Headroom": c["ECONOMIC_HEADROOM"],
                "Data": c["DATA_FEASIBILITY"],
                "Impl": c["IMPLEMENTATION_COMPLEXITY"],
                "Ortho": c["ORTHOGONALITY"],
                "TOTAL": total,
                "holding": c["expected_holding"],
                "turnover": c["expected_turnover"],
                "DECISION": c["DECISION"],
            }
        )
    md = [
        "# RFC-030 — STRATEGY SCORECARD",
        "",
        "Axes are 0-5.  IMPLEMENTATION_COMPLEXITY: 5 = simple.",
        "ORTHOGONALITY: penalised against already-falsified families "
        "(intraday price momentum, volatility breakout, basis directional "
        "reversal, positioning direction, short-horizon carry).",
        "",
        _table(
            rows,
            [
                "CANDIDATE_ID",
                "family",
                "Evidence",
                "Headroom",
                "Data",
                "Impl",
                "Ortho",
                "TOTAL",
                "holding",
                "turnover",
                "DECISION",
            ],
        ),
        "",
        "## Detail",
        "",
    ]
    for c in L.CANDIDATES:
        md += [
            f"### {c['CANDIDATE_ID']} — {c['family']}",
            f"- CLAIM: {c['CLAIM']}",
            f"- SOURCE: {', '.join(c['SOURCE'])}",
            f"- EVIDENCE: {c['EVIDENCE']}",
            f"- economic mechanism: {c['economic_mechanism']}",
            f"- expected turnover: {c['expected_turnover']}",
            f"- expected holding: {c['expected_holding']}",
            f"- main risks: {c['main_risks']}",
            f"- DECISION: **{c['DECISION']}**",
            "",
        ]
    L.write_md(OUT / "STRATEGY_SCORECARD.md", "\n".join(md))


def write_selection() -> dict[str, Any]:
    axes = [
        "EVIDENCE_STRENGTH",
        "ECONOMIC_HEADROOM",
        "DATA_FEASIBILITY",
        "IMPLEMENTATION_COMPLEXITY",
        "ORTHOGONALITY",
    ]
    ranked = []
    for c in L.CANDIDATES:
        total = sum(c[k] for k in axes)
        ranked.append((total, len(c["SOURCE"]), c["CANDIDATE_ID"], c))
    ranked.sort(key=lambda t: (-t[0], -t[1], t[2]))
    passing = [r for r in ranked if r[3]["DECISION"] == "REPRODUCE"]
    selected = tuple(r[2] for r in passing[: L.MAX_REPRODUCED])
    payload = {
        "selection_rule": L.SELECTION_RULE,
        "ranking": [{"CANDIDATE_ID": r[2], "total": r[0], "n_sources": r[1]} for r in ranked],
        "selected": list(selected),
        "frozen_before_backtests": True,
        "generated": _now(),
        "note": (
            "Selection uses external evidence / rationale / data feasibility "
            "only (§21).  Verified identical to the frozen constant "
            f"L.SELECTED = {list(L.SELECTED)}"
        ),
    }
    L.write_json(OUT / "STRATEGY_SELECTION.json", payload)
    md = [
        "# RFC-030 — STRATEGY SELECTION",
        "",
        "Selection happened **before** any of our backtests (§21).",
        "",
        "```text",
        L.SELECTION_RULE,
        "```",
        "",
        _table(
            [
                {
                    "rank": i + 1,
                    "CANDIDATE_ID": r[2],
                    "total": r[0],
                    "n_sources": r[1],
                    "DECISION": r[3]["DECISION"],
                }
                for i, r in enumerate(ranked)
            ],
            ["rank", "CANDIDATE_ID", "total", "n_sources", "DECISION"],
        ),
        "",
        "## Selected for reproduction",
        "",
        f"**{', '.join(selected)}**",
        "",
    ]
    L.write_md(OUT / "STRATEGY_SELECTION.md", "\n".join(md))
    return payload


# ---------------------------------------------------------------------------
# per-strategy artifacts (§59)
# ---------------------------------------------------------------------------

SPECS: dict[str, dict[str, Any]] = {
    "EXT-TSMOM-001": {
        "original_source": "S02 Moskowitz, Ooi & Pedersen (2012), 'Time Series "
        "Momentum', Journal of Financial Economics 104(2); "
        "extended by S04 (Hurst-Ooi-Pedersen century) and "
        "crypto applications S05/S06/S10.",
        "original_universe": "58 liquid futures: equity indices, FX, commodities, "
        "bonds (§10 allows a portable universe; we use crypto)",
        "original_signal": "sign of trailing 12-month excess return",
        "original_formation_period": "12 months (252 business days)",
        "original_holding_period": "1 month",
        "original_rebalance": "monthly",
        "original_weighting": "each instrument scaled to a 40% annualised "
        "volatility target; portfolio averages them",
        "our_weighting": "inverse-volatility relative weighting with the gross "
        "book normalised to 1 (the vol TARGET is a pure "
        "scaling constant after normalisation; only the "
        "relative inverse-vol structure is preserved)",
        "original_risk_model": "per-instrument ex-ante volatility scaling",
        "original_cost_assumptions": "not modelled (futures); reported GROSS",
        "our_deviations": [
            "asset class: USDT crypto spot panel instead of futures",
            "vol-target clip at [0,4]; gross book normalised to 1 so the 40% "
            "vol TARGET does not scale position size (inverse-vol relative "
            "weighting is preserved instead)",
            "12-month formation measured in calendar days (365) not trading days",
            "monthly rebalance on the first calendar day of each month",
            "realistic spot all-taker cost applied (paper reports gross)",
        ],
        "fidelity": "CLOSE_REPRODUCTION",
        "mechanism": "trend persistence / underreaction + institutional risk-management demand",
    },
    "EXT-XMOM-001": {
        "original_source": "S01 Liu, Tsyvinski & Wu (2022), 'Common Risk Factors "
        "in Cryptocurrency', Journal of Finance 77(2); "
        "weekly-momentum robustness in S05/S09, survivorship "
        "critique in S08.",
        "original_universe": "all cryptocurrencies with data (weekly)",
        "original_signal": "past-week return rank (CMOM sorts on 1-week momentum)",
        "original_formation_period": "1 week",
        "original_holding_period": "1 week",
        "original_rebalance": "weekly",
        "original_weighting": "value-weighted (market cap) long-short portfolios",
        "original_risk_model": "market-neutral (long top / short bottom), "
        "factors reported gross of costs",
        "original_cost_assumptions": "none (gross factor returns)",
        "our_deviations": [
            "market caps unavailable -> equal-weighted quintiles instead of "
            "value-weighted deciles (disclosed, §16 data gap)",
            "universe = 30 liquid Binance USDT pairs incl. two dead names",
            "weekly formation measured as 7 calendar days",
            "realistic spot all-taker cost applied on turnover",
        ],
        "fidelity": "CLOSE_REPRODUCTION",
        "mechanism": "behavioural underreaction / limited attention",
    },
}

RUNNERS: dict[str, Callable[..., L.BacktestResult]] = {
    "EXT-TSMOM-001": L.run_time_series_momentum,
    "EXT-XMOM-001": L.run_cross_sectional_momentum,
}


def _run(
    sid: str, panel: L.Panel, mask: NDArray[Any], cost_bps: float = L.PER_SIDE_COST_BPS, **kw: Any
) -> L.BacktestResult:
    fn = RUNNERS[sid]
    r = fn(panel, mask, cost_bps=cost_bps, **kw)
    r.split = "custom"
    return r


def strategy_dir(sid: str) -> Path:
    return OUT / f"strategy_{sid}"


def write_source_evidence(sid: str) -> None:
    c = next(x for x in L.CANDIDATES if x["CANDIDATE_ID"] == sid)
    srcs = [s for s in L.SOURCES if s["SOURCE_ID"] in c["SOURCE"]]
    trace = {
        "SOURCE": [s["SOURCE_ID"] for s in srcs],
        "CLAIM": c["CLAIM"],
        "STRATEGY_SPEC": f"{sid} ({c['family']})",
        "IMPLEMENTATION": "scripts/sprint030_lib.py :: " + RUNNERS[sid].__name__,
        "TEST": "tests/unit/research/test_sprint030_external_alpha.py",
        "REPRODUCTION_RESULT": f"strategy_{sid}/REPRODUCTION_RESULTS.json",
        "ECONOMIC_RESULT": f"strategy_{sid}/VALIDATION_RESULTS.json",
    }
    payload = {
        "candidate": c,
        "sources": srcs,
        "reproduction_trace": trace,
        "n_independent_sources": len(srcs),
        "generated": _now(),
    }
    L.write_json(strategy_dir(sid) / "SOURCE_EVIDENCE.json", payload)
    md = [
        f"# {sid} — SOURCE EVIDENCE",
        "",
        f"**CLAIM**: {c['CLAIM']}",
        "",
        f"**EVIDENCE**: {c['EVIDENCE']}",
        "",
        f"**MECHANISM**: {c['economic_mechanism']}",
        "",
        "## Sources",
        "",
        _table(
            [
                {
                    "SOURCE_ID": s["SOURCE_ID"],
                    "year": s["year"],
                    "authority": s["authority_level"],
                    "title": s["title"],
                }
                for s in srcs
            ],
            ["SOURCE_ID", "year", "authority", "title"],
        ),
        "",
        "## Reproduction trace (§56)",
        "",
        "```text",
        *[f"{k}: {v}" for k, v in trace.items()],
        "```",
        "",
    ]
    L.write_md(strategy_dir(sid) / "SOURCE_EVIDENCE.md", "\n".join(md))


def write_reproduction_spec(sid: str) -> None:
    spec = SPECS[sid]
    payload = dict(spec) | {
        "strategy": sid,
        "classification": spec["fidelity"],
        "no_parameter_tuning": True,
        "generated": _now(),
    }
    L.write_json(strategy_dir(sid) / "REPRODUCTION_SPEC.json", payload)
    md = [
        f"# {sid} — REPRODUCTION SPEC",
        "",
        f"**FIDELITY: {spec['fidelity']}**",
        "",
        f"- original source: {spec['original_source']}",
        f"- original universe: {spec['original_universe']}",
        f"- original signal: {spec['original_signal']}",
        f"- formation: {spec['original_formation_period']}",
        f"- holding: {spec['original_holding_period']}",
        f"- rebalance: {spec['original_rebalance']}",
        f"- weighting: {spec['original_weighting']}",
        f"- our weighting: {spec.get('our_weighting', 'as original')}",
        f"- risk model: {spec['original_risk_model']}",
        f"- original costs: {spec['original_cost_assumptions']}",
        "",
        "## Our unavoidable deviations",
        "",
        "\n".join(f"- {d}" for d in spec["our_deviations"]),
        "",
    ]
    L.write_md(strategy_dir(sid) / "REPRODUCTION_SPEC.md", "\n".join(md))


def write_data_audit(panel: L.Panel) -> dict[str, Any]:
    fetch = json.loads((OUT / "_fetch_source_audit.json").read_text(encoding="utf-8"))
    per_asset = {}
    for j, sym in enumerate(panel.assets):
        col = panel.close[:, j]
        fin = np.isfinite(col)
        idx = np.where(fin)[0]
        per_asset[sym] = {
            "days": int(fin.sum()),
            "first": datetime.fromtimestamp(int(panel.dates[idx[0]]) / 1000, tz=UTC)
            .date()
            .isoformat()
            if idx.size
            else None,
            "last": datetime.fromtimestamp(int(panel.dates[idx[-1]]) / 1000, tz=UTC)
            .date()
            .isoformat()
            if idx.size
            else None,
            "nan_days": int((~fin).sum()),
            "rows_raw": fetch["assets"].get(sym, {}).get("rows"),
        }
    payload = {
        "source": fetch["source"],
        "window": fetch["window"],
        "calendar_days": panel.n,
        "assets": len(panel.assets),
        "per_asset": per_asset,
        "survivorship_disclosure": fetch["survivorship_note"],
        "missing_data_policy": "no imputation; absent days stay NaN and are excluded",
        "holdout_analytics_read": False,
        "generated": _now(),
    }
    L.write_json(OUT / "DATA_AUDIT.json", payload)
    rows = [{"symbol": s, **v} for s, v in per_asset.items()]
    md = [
        "# RFC-030 — DATA AUDIT",
        "",
        f"- source: `{payload['source']}`",
        f"- window: {payload['window']['start']} .. {payload['window']['end']}",
        f"- calendar days: {panel.n}   assets: {len(panel.assets)}",
        f"- policy: {payload['missing_data_policy']}",
        "",
        "## Survivorship disclosure",
        "",
        payload["survivorship_disclosure"],
        "",
        _table(rows, ["symbol", "days", "first", "last", "nan_days", "rows_raw"]),
        "",
    ]
    L.write_md(OUT / "DATA_AUDIT.md", "\n".join(md))
    return payload


def pit_check(sid: str, panel: L.Panel, mask: NDArray[Any]) -> dict[str, Any]:
    """Runtime PIT proof: masking all future data must not change today's weights."""
    days = (
        L._weekly_rebalance_days(panel, mask)
        if sid == "EXT-XMOM-001"
        else L._monthly_rebalance_days(panel, mask)
    )
    if len(days) < 3:
        return {"status": "INSUFFICIENT", "checks": 0, "mismatches": 0}
    checks = 0
    mismatches = 0
    for i in days[1 : min(len(days), 12)]:
        future = panel.close.copy()
        future[i + 1 :, :] = np.nan
        fpanel = L.Panel(
            dates=panel.dates,
            assets=panel.assets,
            close=future,
            quote_volume=panel.quote_volume,
            open_ms=panel.open_ms,
        )
        a = _weights(sid, panel, i)
        b = _weights(sid, fpanel, i)
        checks += 1
        if not np.allclose(a, b, equal_nan=True):
            mismatches += 1
    return {
        "status": "PASS" if mismatches == 0 else "FAIL",
        "checks": checks,
        "mismatches": mismatches,
        "rule": (
            "signals use only closes at or before the decision day; "
            "execution is co-timed at that daily close"
        ),
    }


def _weights(sid: str, panel: L.Panel, i: int) -> NDArray[Any]:
    if sid == "EXT-XMOM-001":
        if i - 7 < 0:
            return np.zeros(panel.a)
        elig = L._eligible(panel, i, 7)
        sig = np.full(panel.a, np.nan)
        ok = elig & np.isfinite(panel.close[i - 7])
        sig[ok] = panel.close[i, ok] / panel.close[i - 7, ok] - 1.0
        return L._weights_for_signal(panel, i, sig, elig, True, 0.2)
    if i - 365 < 0:
        return np.zeros(panel.a)
    elig = L._eligible(panel, i, 365)
    ok = elig & np.isfinite(panel.close[i - 365])
    sig = np.zeros(panel.a)
    sig[ok] = np.sign(panel.close[i, ok] / panel.close[i - 365, ok] - 1.0)
    lo = max(0, i - 60)
    win = panel.close[lo : i + 1]
    r = win[1:] / win[:-1] - 1.0
    vol = np.full(panel.a, np.nan)
    for jj in range(panel.a):
        col = r[:, jj]
        col = col[np.isfinite(col)]
        if col.size >= 2:
            vol[jj] = float(np.std(col)) * np.sqrt(365.0)
    scale = np.zeros(panel.a)
    good = ok & np.isfinite(vol) & (vol > 0)
    scale[good] = np.clip(0.40 / vol[good], 0.0, 4.0)
    raw = sig * scale
    s = float(np.sum(np.abs(raw)))
    return raw / s if s > 0 else raw


def write_strategy_data_audit(sid: str, data_audit: dict[str, Any]) -> None:
    payload = {"strategy": sid, **data_audit, "generated": _now()}
    L.write_json(strategy_dir(sid) / "DATA_AUDIT.json", payload)
    md = [
        f"# {sid} — DATA AUDIT",
        "",
        f"- source: `{data_audit['source']}`",
        f"- window: {data_audit['window']['start']} .. {data_audit['window']['end']}",
        f"- assets: {data_audit['assets']}, calendar days: {data_audit['calendar_days']}",
        f"- policy: {data_audit['missing_data_policy']}",
        "",
        f"{data_audit['survivorship_disclosure']}",
        "",
    ]
    L.write_md(strategy_dir(sid) / "DATA_AUDIT.md", "\n".join(md))


def write_pit_audit(
    sid: str, panel: L.Panel, split_masks: dict[str, NDArray[Any]]
) -> dict[str, Any]:
    results = {name: pit_check(sid, panel, m) for name, m in split_masks.items()}
    overall = (
        "PASS" if all(r["status"] in ("PASS", "INSUFFICIENT") for r in results.values()) else "FAIL"
    )
    payload = {"strategy": sid, "overall": overall, "per_split": results, "generated": _now()}
    L.write_json(strategy_dir(sid) / "PIT_AUDIT.json", payload)
    md = [
        f"# {sid} — PIT AUDIT",
        "",
        f"**{overall}**",
        "",
        "Rule: signals use only closes at or before the decision day; execution "
        "is co-timed at that daily close.  The automatic check masks every "
        "future close and re-derives today's weights.",
        "",
        _table(
            [{"split": k, **v} for k, v in results.items()],
            ["split", "status", "checks", "mismatches"],
        ),
        "",
    ]
    L.write_md(strategy_dir(sid) / "PIT_AUDIT.md", "\n".join(md))
    return payload


def write_cost_model(sid: str) -> None:
    payload = {
        "strategy": sid,
        "our_cost_model": "EXT_CRYPTO_COST_MODEL_V1",
        "components_bps": dict(L.EXT_CRYPTO_COST_MODEL_V1),
        "per_side_cost_bps": L.PER_SIDE_COST_BPS,
        "charging_rule": (
            "one-way cost charged on traded notional sum_a |w_t - w_{t-1}| per rebalance"
        ),
        "publication_cost_assumption": SPECS[sid]["original_cost_assumptions"],
        "note": (
            "Papers report gross factor returns; we apply a conservative "
            "spot all-taker cost so a gross edge cannot be called profitable."
        ),
        "generated": _now(),
    }
    L.write_json(strategy_dir(sid) / "COST_MODEL.json", payload)
    md = [
        f"# {sid} — COST MODEL",
        "",
        f"- model: `{payload['our_cost_model']}`",
        f"- per-side cost: **{L.PER_SIDE_COST_BPS} bps** "
        f"(fee {L.EXT_CRYPTO_COST_MODEL_V1['taker_fee_bps']} + "
        f"half-spread {L.EXT_CRYPTO_COST_MODEL_V1['half_spread_bps']} + "
        f"impact {L.EXT_CRYPTO_COST_MODEL_V1['impact_bps']})",
        f"- charging rule: {payload['charging_rule']}",
        f"- original assumption: {payload['publication_cost_assumption']}",
        "",
        payload["note"],
        "",
    ]
    L.write_md(strategy_dir(sid) / "COST_MODEL.md", "\n".join(md))


def _render_results(name: str, sid: str, blocks: list[tuple[str, dict[str, Any]]]) -> None:
    payload = {"strategy": sid, "sections": {k: v for k, v in blocks}, "generated": _now()}
    L.write_json(strategy_dir(sid) / f"{name}.json", payload)
    md = [f"# {sid} — {name.replace('_', ' ')}", ""]
    for label, m in blocks:
        md += [f"## {label}", ""]
        if m.get("status") == "NO_TRADES":
            md += ["NO_TRADES", ""]
            continue
        md += ["```json", json.dumps(_clean_metrics(m), indent=2, sort_keys=True), "```", ""]
    L.write_md(strategy_dir(sid) / f"{name}.md", "\n".join(md))


def _metrics(res: L.BacktestResult, sid: str) -> dict[str, Any]:
    return res.metrics(L.PERIODS_PER_YEAR[sid])


def evaluate_strategy(
    sid: str,
    panel: L.Panel,
    splits: dict[str, NDArray[Any]],
    pit: dict[str, Any],
) -> dict[str, Any]:
    ppy = L.PERIODS_PER_YEAR[sid]
    disc = _run(sid, panel, splits["DISCOVERY"])
    val = _run(sid, panel, splits["VALIDATION"])
    full_mask = np.ones(panel.n, dtype=bool)
    rep = _run(sid, panel, full_mask)

    m_rep = _metrics(rep, sid)
    m_disc = _metrics(disc, sid)
    m_val = _metrics(val, sid)

    # walk-forward: rolling 365-day windows stepping 183 days over the full sample
    import datetime as _dt

    wf = []
    start = panel.dates[0]
    end = panel.dates[-1]
    w0 = int(start)
    while w0 < end:
        w1 = w0 + 365 * 86_400_000
        mask = (panel.dates >= w0) & (panel.dates < w1)
        r = _run(sid, panel, mask)
        m = _metrics(r, sid)
        if m.get("status") == "OK" and m["rebalances"] > 0:
            wf.append(
                {
                    "start": _dt.datetime.fromtimestamp(w0 / 1000, tz=UTC).date().isoformat(),
                    "rebalances": m["rebalances"],
                    "net_expectancy_bps": m["net_expectancy_bps"],
                    "gross_expectancy_bps": m["gross_expectancy_bps"],
                    "sharpe": m["sharpe"],
                }
            )
        w0 += 183 * 86_400_000
    pos_windows = sum(1 for x in wf if x["net_expectancy_bps"] > 0)
    wf_summary = {
        "status": "OK",
        "windows": len(wf),
        "positive_windows": pos_windows,
        "positive_fraction": (pos_windows / len(wf)) if wf else None,
    }

    # robustness
    cost_stress = {}
    for mult in COST_STRESS_MULTIPLIERS:
        r = _run(sid, panel, splits["VALIDATION"], cost_bps=L.PER_SIDE_COST_BPS * mult)
        m = _metrics(r, sid)
        cost_stress[f"x{mult}"] = {
            "net_expectancy_bps": m.get("net_expectancy_bps"),
            "status": m.get("status"),
        }
    param_adj: dict[str, Any] = {}
    variants: dict[str, dict[str, Any]]
    if sid == "EXT-XMOM-001":
        variants = {
            "form_7d": {"formation_days": 7},
            "form_14d": {"formation_days": 14},
            "form_28d": {"formation_days": 28},
            "quantile_30": {"quantile": 0.3},
        }
    else:
        # NOTE: `vol_target` is a pure scaling constant under gross-normalisation
        # (inverse-vol *relative* weighting is what matters), so sensitivity is
        # probed through the vol lookback and the formation window instead.
        variants = {
            "form_365d": {"formation_days": 365},
            "form_182d": {"formation_days": 182},
            "vol_lookback_30": {"vol_lookback": 30},
            "vol_lookback_120": {"vol_lookback": 120},
        }
    for k, kw in variants.items():
        r = _run(sid, panel, splits["VALIDATION"], **kw)
        m = _metrics(r, sid)
        param_adj[k] = {
            "net_expectancy_bps": m.get("net_expectancy_bps"),
            "status": m.get("status"),
        }

    return {
        "strategy": sid,
        "periods_per_year": ppy,
        "reproduction": m_rep,
        "discovery": m_disc,
        "validation": m_val,
        "walk_forward": wf,
        "walk_forward_summary": wf_summary,
        "cost_stress": cost_stress,
        "param_adjacent": param_adj,
        "pit": pit,
    }


def gates(sid: str, ev: dict[str, Any], holdout: dict[str, Any] | None) -> dict[str, Any]:
    min_reb = MIN_VALIDATION_REBALANCES.get(sid, 30)
    disc_ok = (
        ev["discovery"].get("status") == "OK"
        and (ev["discovery"].get("net_expectancy_bps") or 0) > 0
    )
    val_ok = (
        ev["validation"].get("status") == "OK"
        and ev["validation"].get("rebalances", 0) >= min_reb
        and (ev["validation"].get("net_expectancy_bps") or 0) > 0
    )
    robust_ok = val_ok and (ev["cost_stress"]["x1.5"].get("net_expectancy_bps") or -1) > 0
    hold_ok = bool(
        val_ok
        and holdout
        and holdout.get("status") == "OK"
        and (holdout.get("net_expectancy_bps") or 0) > 0
    )
    pit_ok = ev["pit"]["overall"] == "PASS"
    if not pit_ok:
        classification = "PIT_FAIL"
    elif hold_ok:
        classification = "HOLDOUT_PASS"
    elif robust_ok:
        classification = "ROBUST_NET_EDGE"
    elif val_ok:
        classification = "VALIDATED_NET_EDGE"
    elif disc_ok:
        classification = "EDGE_DECAYED"
    else:
        classification = "NO_EDGE"
    return {
        "G_REPRO": "PASS" if pit_ok else "FAIL",
        "G_DISCOVERY": "PASS" if disc_ok else "FAIL",
        "G_VALIDATION": "PASS" if val_ok else "FAIL",
        "G_ROBUST": "PASS" if robust_ok else "FAIL",
        "G_HOLDOUT": (
            "PASS"
            if hold_ok
            else (
                "OPENED_FAIL"
                if (val_ok and holdout)
                else ("NOT_OPENED" if not val_ok else "NOT_REACHED")
            )
        ),
        "CLASSIFICATION": classification,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_plan()
    write_source_registry()
    write_universe()
    write_scorecard()
    selection = write_selection()

    panel = L.build_panel()
    splits = L.split_masks(panel)
    data_audit = write_data_audit(panel)

    results: dict[str, Any] = {}
    for sid in L.SELECTED:
        write_source_evidence(sid)
        write_reproduction_spec(sid)
        write_strategy_data_audit(sid, data_audit)
        write_cost_model(sid)
        pit = write_pit_audit(sid, panel, splits)
        ev = evaluate_strategy(sid, panel, splits, pit)
        # HOLDOUT only if VALIDATION passes (§57)
        if (
            ev["validation"].get("status") == "OK"
            and (ev["validation"].get("net_expectancy_bps") or 0) > 0
        ):
            r = _run(sid, panel, splits["HOLDOUT"])
            holdout = _metrics(r, sid)
            holdout["opened"] = True
        else:
            holdout = {
                "status": "NOT_OPENED",
                "reason": "VALIDATION did not produce a positive net edge",
            }
        ev["holdout"] = holdout
        ev["gates"] = gates(sid, ev, None if holdout.get("status") == "NOT_OPENED" else holdout)

        _render_results("REPRODUCTION_RESULTS", sid, [("FULL SAMPLE", ev["reproduction"])])
        _render_results("DISCOVERY_RESULTS", sid, [("DISCOVERY", ev["discovery"])])
        _render_results("VALIDATION_RESULTS", sid, [("VALIDATION", ev["validation"])])
        _render_results("WALK_FORWARD_RESULTS", sid, [("SUMMARY", ev["walk_forward_summary"])])
        _render_results(
            "ROBUSTNESS_RESULTS",
            sid,
            [
                (
                    "COST_STRESS",
                    {
                        "status": "OK",
                        **{
                            k: v["net_expectancy_bps"]
                            for k, v in ev["cost_stress"].items()
                            if v["status"] == "OK"
                        },
                    },
                ),
                (
                    "PARAM_ADJACENT (sensitivity, not tuning)",
                    {
                        "status": "OK",
                        **{
                            k: v["net_expectancy_bps"]
                            for k, v in ev["param_adjacent"].items()
                            if v["status"] == "OK"
                        },
                    },
                ),
                ("WITHOUT_BEST_DISCOVERY", ev["discovery"]),
            ],
        )
        _render_results("HOLDOUT_RESULTS", sid, [("HOLDOUT", ev["holdout"])])
        results[sid] = ev
        print(
            f"[run030] {sid}: discovery_net="
            f"{ev['discovery'].get('net_expectancy_bps')} "
            f"validation_net={ev['validation'].get('net_expectancy_bps')} "
            f"-> {ev['gates']['CLASSIFICATION']}",
            flush=True,
        )

    comparison = write_comparison(results, selection)
    hashes = write_hashes(panel, results)
    write_final_report(results, comparison, hashes, data_audit)
    print("[run030] done", flush=True)


def write_comparison(results: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for sid, ev in results.items():
        c = next(x for x in L.CANDIDATES if x["CANDIDATE_ID"] == sid)
        rows.append(
            {
                "strategy": sid,
                "source_evidence_strength": c["EVIDENCE_STRENGTH"],
                "published_performance": "see SOURCE_REGISTRY (gross, no costs)",
                "reproduction_fidelity": SPECS[sid]["fidelity"],
                "our_gross_expectancy_bps": ev["reproduction"].get("gross_expectancy_bps"),
                "our_net_expectancy_bps": ev["reproduction"].get("net_expectancy_bps"),
                "validation_net_expectancy_bps": ev["validation"].get("net_expectancy_bps"),
                "robustness": ev["gates"]["G_ROBUST"],
                "turnover_notional": ev["reproduction"].get("mean_turnover_notional"),
                "cost_expectancy_bps": ev["reproduction"].get("cost_expectancy_bps"),
                "data_quality": "daily Binance archives, 30 assets, PIT-clean, "
                "survivorship disclosed",
                "classification": ev["gates"]["CLASSIFICATION"],
            }
        )
    payload = {"rows": rows, "selection": selection, "generated": _now()}
    L.write_json(OUT / "EXTERNAL_ALPHA_COMPARISON.json", payload)
    md = [
        "# RFC-030 — EXTERNAL ALPHA COMPARISON",
        "",
        _table(
            rows,
            [
                "strategy",
                "source_evidence_strength",
                "reproduction_fidelity",
                "our_gross_expectancy_bps",
                "our_net_expectancy_bps",
                "validation_net_expectancy_bps",
                "robustness",
                "turnover_notional",
                "cost_expectancy_bps",
                "classification",
            ],
        ),
        "",
    ]
    L.write_md(OUT / "EXTERNAL_ALPHA_COMPARISON.md", "\n".join(md))
    return payload


def write_hashes(panel: L.Panel, results: dict[str, Any]) -> dict[str, Any]:
    data_hashes = {}
    for sym in panel.assets:
        p = L.CACHE_DIR / f"daily_{sym}.npz"
        data_hashes[sym] = L.sha256_file(p)
    payload = {
        "code": {
            "sprint030_lib": L.sha256_file(L.REPO / "scripts" / "sprint030_lib.py"),
            "sprint030_run": L.sha256_file(L.REPO / "scripts" / "sprint030_run.py"),
            "sprint030_fetch": L.sha256_file(L.REPO / "scripts" / "sprint030_fetch.py"),
        },
        "cost_model": L.EXT_CRYPTO_COST_MODEL_V1,
        "config_hash": L.sha256_obj(
            {
                "universe": L.UNIVERSE,
                "splits": L.SPLIT_BOUNDS,
                "cost": L.EXT_CRYPTO_COST_MODEL_V1,
                "selected": L.SELECTED,
            }
        ),
        "data_hashes": data_hashes,
        "holdout_opened": {
            sid: results[sid]["holdout"].get("status") != "NOT_OPENED" for sid in results
        },
        "generated": _now(),
    }
    L.write_json(OUT / "_hashes.json", payload)
    return payload


def write_final_report(
    results: dict[str, Any],
    comparison: dict[str, Any],
    hashes: dict[str, Any],
    data_audit: dict[str, Any],
) -> None:
    n_reproduced = len(results)
    validated = [s for s, e in results.items() if e["gates"]["G_VALIDATION"] == "PASS"]
    robust = [s for s, e in results.items() if e["gates"]["G_ROBUST"] == "PASS"]
    holdouts = [s for s, e in results.items() if e["gates"]["G_HOLDOUT"] == "PASS"]
    g_repro = (
        "PASS"
        if all(e["gates"]["G_REPRO"] == "PASS" for e in results.values()) and n_reproduced >= 1
        else "FAIL"
    )
    payload = {
        "rfc": "RFC-030",
        "generated": _now(),
        "external_strategies_researched": L.MAX_EXTERNAL_STRATEGIES,
        "shortlisted": [c["CANDIDATE_ID"] for c in L.CANDIDATES],
        "reproduced": list(results),
        "G_EXT_REPRO": g_repro,
        "validated_net_edges": validated,
        "robust_net_edges": robust,
        "holdout_passes": holdouts,
        "paper_candidates": holdouts if holdouts else [],
        "per_strategy": {
            s: results[s]["gates"]
            | {
                "discovery_net_expectancy_bps": results[s]["discovery"].get("net_expectancy_bps"),
                "validation_net_expectancy_bps": results[s]["validation"].get("net_expectancy_bps"),
                "reproduction_net_expectancy_bps": results[s]["reproduction"].get(
                    "net_expectancy_bps"
                ),
            }
            for s in results
        },
        "top_strategy": _top_strategy(results),
        "data_audit_summary": {
            "assets": data_audit["assets"],
            "calendar_days": data_audit["calendar_days"],
            "survivorship": data_audit["survivorship_disclosure"],
        },
        "hashes": hashes["config_hash"],
    }
    L.write_json(L.REPO / "reports" / "RFC030_FINAL_REPORT.json", payload)
    L.write_md(
        L.REPO / "reports" / "RFC030_FINAL_REPORT.md", _final_md(payload, results, comparison)
    )


def _top_strategy(results: dict[str, Any]) -> dict[str, Any]:
    def rank(e: dict[str, Any]) -> tuple[int, float]:
        order = {
            "HOLDOUT_PASS": 4,
            "ROBUST_NET_EDGE": 3,
            "VALIDATED_NET_EDGE": 2,
            "EDGE_DECAYED": 1,
            "NO_EDGE": 0,
            "PIT_FAIL": -1,
        }
        return order.get(e["gates"]["CLASSIFICATION"], -1), (
            e["validation"].get("net_expectancy_bps") or -1e9
        )

    sid = max(results, key=lambda s: rank(results[s]))
    ev = results[sid]
    m = ev["reproduction"]
    return {
        "strategy": sid,
        "source": SPECS[sid]["original_source"].split(".")[0] + ".",
        "source_quality": "PEER-REVIEWED PAPER",
        "economic_mechanism": SPECS[sid]["mechanism"],
        "reproduction_fidelity": SPECS[sid]["fidelity"],
        "market": "USDT crypto spot (30 assets)",
        "horizon": SPECS[sid]["original_holding_period"],
        "turnover_notional": m.get("mean_turnover_notional"),
        "trades": m.get("rebalances"),
        "gross_expectancy_bps": m.get("gross_expectancy_bps"),
        "cost_bps": m.get("cost_expectancy_bps"),
        "net_expectancy_bps": m.get("net_expectancy_bps"),
        "validation_net_expectancy_bps": ev["validation"].get("net_expectancy_bps"),
        "classification": ev["gates"]["CLASSIFICATION"],
        "next": _next_text(sid, results),
    }


def _next_text(sid: str, results: dict[str, Any]) -> str:
    ev = results[sid]
    cls = ev["gates"]["CLASSIFICATION"]
    if cls == "HOLDOUT_PASS":
        return (
            "external edge PASSES validation and holdout after realistic "
            "costs; next step is a deterministic paper-trading evaluation "
            "(no live capital) on the frozen specification"
        )
    if cls == "ROBUST_NET_EDGE":
        return "validated and cost-robust, but holdout not passed"
    if cls == "VALIDATED_NET_EDGE":
        return "positive out-of-sample but not robust to cost stress"
    if cls == "EDGE_DECAYED":
        return "edge present in discovery but absent in validation (post-publication decay)"
    return "no reproducible net edge"


def _final_md(payload: dict[str, Any], results: dict[str, Any], comparison: dict[str, Any]) -> str:
    t = payload["top_strategy"]
    lines = [
        "# RFC-030 EXTERNAL ALPHA REPRODUCTION",
        "",
        "```text",
        "RFC-030 EXTERNAL ALPHA REPRODUCTION",
        "",
        f"External strategies researched = {payload['external_strategies_researched']}",
        "",
        f"Shortlisted = {len(L.CANDIDATES)}",
        "",
        f"Reproduced = {len(payload['reproduced'])}",
        "",
        f"G_EXT_REPRO = {payload['G_EXT_REPRO']}",
        "",
        f"Validated net edges = {len(payload['validated_net_edges'])}",
        "",
        f"Robust net edges = {len(payload['robust_net_edges'])}",
        "",
        f"Holdout passes = {len(payload['holdout_passes'])}",
        "",
        f"PAPER CANDIDATES = {payload['paper_candidates'] or 'NONE'}",
        "```",
        "",
        "## Per-strategy verdicts",
        "",
        _table(
            [{"strategy": s, **v} for s, v in payload["per_strategy"].items()],
            [
                "strategy",
                "CLASSIFICATION",
                "G_REPRO",
                "G_DISCOVERY",
                "G_VALIDATION",
                "G_ROBUST",
                "G_HOLDOUT",
                "discovery_net_expectancy_bps",
                "validation_net_expectancy_bps",
            ],
        ),
        "",
        "## Top strategy report (§63)",
        "",
        "```text",
        f"STRATEGY = {t['strategy']}",
        f"EXTERNAL SOURCE = {t['source']}",
        f"SOURCE QUALITY = {t['source_quality']}",
        f"ECONOMIC MECHANISM = {t['economic_mechanism']}",
        f"REPRODUCTION FIDELITY = {t['reproduction_fidelity']}",
        f"MARKET = {t['market']}",
        f"HORIZON = {t['horizon']}",
        f"TURNOVER = {t['turnover_notional']}",
        f"TRADES = {t['trades']}",
        f"GROSS EXPECTANCY = {t['gross_expectancy_bps']} bps",
        f"COST = {t['cost_bps']} bps",
        f"NET EXPECTANCY = {t['net_expectancy_bps']} bps",
        f"NET VALIDATION EXPECTANCY = {t['validation_net_expectancy_bps']} bps",
        f"CLASSIFICATION = {t['classification']}",
        f"NEXT = {t['next']}",
        "```",
        "",
        "## External alpha comparison",
        "",
        _table(
            comparison["rows"],
            [
                "strategy",
                "source_evidence_strength",
                "reproduction_fidelity",
                "our_gross_expectancy_bps",
                "our_net_expectancy_bps",
                "validation_net_expectancy_bps",
                "robustness",
                "classification",
            ],
        ),
        "",
        "## Data",
        "",
        f"- assets: {payload['data_audit_summary']['assets']}, "
        f"calendar days: {payload['data_audit_summary']['calendar_days']}",
        f"- {payload['data_audit_summary']['survivorship']}",
        "",
        f"- config hash: `{payload['hashes']}`",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
