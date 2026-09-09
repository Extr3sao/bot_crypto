"""POC02 observation CLI (POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01).

Modes:

- ``--daily``            canonical daily report after a UTC day close
                         (also finalizes any closed-but-unfinalized day
                         via the existing DayStateAuthority contract).
- ``--resolve-shadow``   PIT-resolve pending shadow captures against real
                         public binanceusdm 5m bars (§9).
- ``--status``           write read-only STATUS.json + STATUS.html (§17):
                         coverage, daily trades, frequency KPI, current
                         bottleneck + distribution, shadow captures/
                         resolved, regime coverage. PAPER vs SHADOW is
                         visually explicit; NO controls, no POST.

Read-only analytics over persisted evidence; no parameter change; no
trading-path mutation; no synthetic data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.paper.day_state import DayStateAuthority  # noqa: E402
from trading_bot.paper.poc02_observation import (  # noqa: E402
    analyze_campaign,
    daily_performance_rows,
    frequency_kpis,
    load_cycle_ledger,
    runtime_staleness,
)

CAMPAIGN_DIR = REPO_ROOT / "reports" / "poc02-paper-clean-01"
REPORTS_DIR = CAMPAIGN_DIR / "observation"
POC02_CAMPAIGN_ID = "POC-02-paper-clean-01"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# §17 — read-only STATUS surface
# --------------------------------------------------------------------------


def _fmt_pct(value: object) -> str:
    return f"{value}%" if value is not None else "n/a"


def write_status(campaign_dir: Path) -> Path:
    analysis = analyze_campaign(campaign_dir)
    now = datetime.now(UTC).replace(microsecond=0)
    staleness = analysis["runtime_staleness"]
    freq = analysis["frequency_kpis"]
    bottlenecks = analysis["bottleneck_distribution"]
    regime_map = analysis["regime_coverage_map"]
    shadow = analysis["shadow_risk_analysis"]

    status = {
        "artifact": "POC02_READ_ONLY_STATUS",
        "campaign_id": POC02_CAMPAIGN_ID,
        "written_at_utc": now.isoformat(),
        "mode": "PAPER",
        "execution": "PaperBroker",
        "market_data_provider": "binanceusdm (public, no credentials)",
        "runtime": {
            "status": staleness["status"],
            "heartbeat_utc": staleness.get("heartbeat_utc"),
            "RUNTIME_STALE": staleness["RUNTIME_STALE"],
            "age_minutes": staleness.get("age_minutes"),
            "note": (
                "RUNTIME_STALE surfaces stale heartbeats; old data is never "
                "presented as current"
            )
            if staleness["RUNTIME_STALE"]
            else "heartbeat fresh",
        },
        "coverage": {
            "day_rows": [
                {
                    "utc_day": r["utc_day"],
                    "coverage_ratio_day": r["coverage_ratio_day"],
                    "day_validity": r["day_validity"],
                    "observed_cycles": r["observed_cycles"],
                    "observed_minutes": r["observed_minutes"],
                }
                for r in analysis["daily_performance"]
            ]
        },
        "frequency": freq,
        "bottleneck": bottlenecks,
        "regime_bottleneck_matrix": analysis["regime_bottleneck_matrix"],
        "strategy_contribution": analysis["strategy_contribution"],
        "agent_filter": analysis["agent_filter"],
        "shadow": {
            "label": "SHADOW — counterfactual, EXCLUDED from paper PnL and frequency",
            "captures_total": shadow["captures_total"],
            "resolved_total": shadow["resolved_total"],
            "captures_by_reason": shadow["captures_by_reason"],
            "isolation": shadow["isolation"],
        },
        "regime_coverage_map": regime_map,
        "risk_value_test": analysis["risk_value_test"],
        "read_only": True,
        "no_controls": True,
    }
    status_path = REPORTS_DIR / "STATUS.json"
    _write_json(status_path, status)

    # ---- HTML (read-only; no forms, no buttons, no POST endpoints) ----
    stale_badge = (
        '<span style="background:#c0392b;padding:.2rem .6rem;border-radius:4px">'
        "RUNTIME_STALE</span>"
        if staleness["RUNTIME_STALE"]
        else '<span style="background:#1e8449;padding:.2rem .6rem;border-radius:4px">'
        "LIVE-HEARTBEAT-OK</span>"
    )
    paper_badge = (
        '<span style="background:#2874a6;padding:.2rem .6rem;border-radius:4px">PAPER '
        "MODE &bull; LIVE DISABLED</span>"
    )
    shadow_badge = (
        '<span style="background:#6c3483;padding:.2rem .6rem;border-radius:4px">'
        "SHADOW &bull; COUNTERFACTUAL &bull; EXCLUDED FROM PAPER PnL/FREQUENCY</span>"
    )
    bn_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td><td>"
        f"{round(100 * v / bottlenecks['windows_observed'], 1) if bottlenecks['windows_observed'] else 'n/a'}%"
        "</td></tr>"
        for k, v in bottlenecks["counts"].items()
    )
    cov_rows = "".join(
        f"<tr><td>{r['utc_day']}</td><td>{r['coverage_ratio_day']}</td>"
        f"<td>{r['day_validity']}</td><td>{r['observed_cycles']}</td>"
        f"<td>{r['observed_minutes']}</td></tr>"
        for r in analysis["daily_performance"]
    )
    freq_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in freq.items()
        if not isinstance(v, dict)
    )
    regime_rows = "".join(
        f"<tr><td>{r}</td><td>{c['windows']}</td><td>{c['proposals']}</td>"
        f"<td>{len(c['strategies'])}</td><td>{c['classification']}</td></tr>"
        for r, c in regime_map["regimes"].items()
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30"><title>POC02 STATUS (read-only)</title>
<style>body{{font-family:Segoe UI,Arial;margin:2rem;background:#0f1216;color:#e6e6e6}}
h1{{font-size:1.25rem}}h2{{font-size:1.05rem;margin-top:1.4rem}}
table{{border-collapse:collapse}}td,th{{border:1px solid #333;padding:.3rem .6rem;font-size:.85rem}}
.badge{{padding:.2rem .6rem;border-radius:4px;color:#fff}}</style></head><body>
<h1>POC02 OBSERVATION STATUS {paper_badge} {shadow_badge} {stale_badge}</h1>
<p>Campaign <b>{POC02_CAMPAIGN_ID}</b> &middot; heartbeat {staleness.get('heartbeat_utc', 'n/a')}
&middot; written {now.isoformat()}</p>

<h2>Daily coverage (PAPER runtime)</h2>
<table><tr><th>UTC day</th><th>coverage</th><th>validity</th><th>cycles</th><th>minutes</th></tr>{cov_rows}</table>

<h2>Frequency KPI (target ≥ 3 executed paper trades / valid UTC day — unchanged)</h2>
<table>{freq_rows}</table>

<h2>Bottleneck distribution (current evidence)</h2>
<table><tr><th>bottleneck</th><th>windows</th><th>%</th></tr>{bn_rows}</table>

<h2>Regime coverage map (research input — no auto batch)</h2>
<table><tr><th>regime</th><th>windows</th><th>proposals</th><th>strategies</th><th>class</th></tr>{regime_rows}</table>

<h2>Shadow (§9/§10) — counterfactual only</h2>
<p>captures {shadow['captures_total']} &middot; resolved {shadow['resolved_total']} &middot;
isolation SHADOW_PAPERBROKER_CALLS=0</p>

<p style="color:#85929e">READ-ONLY surface: no controls, no orders, no risk or execution
endpoints. PAPER rows come from the paper ledger; SHADOW rows are counterfactual and never
count toward paper PnL or trade frequency.</p>
</body></html>"""
    html_path = REPORTS_DIR / "STATUS.html"
    html_path.write_text(html, encoding="utf-8")
    return status_path


# --------------------------------------------------------------------------
# daily report + checkpoint triggers
# --------------------------------------------------------------------------


def finalize_closed_days(campaign_dir: Path) -> list[dict]:
    auth = DayStateAuthority(campaign_dir)
    done: list[dict] = []
    for day in sorted(load_coverage_rows_days(campaign_dir)):
        res = auth.finalize_day(day)
        if res.get("finalized") and not res.get("DAY_NOT_CLOSED"):
            done.append(res)
    return done


def load_coverage_rows_days(campaign_dir: Path) -> list[str]:
    path = campaign_dir / "POC02_COVERAGE_DAILY.jsonl"
    days: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                days.add(json.loads(line)["utc_day"])
    return sorted(days)


def run_daily(campaign_dir: Path) -> dict:
    now = datetime.now(UTC).replace(microsecond=0)
    finalized = finalize_closed_days(campaign_dir)
    perf = daily_performance_rows(campaign_dir)
    freq = frequency_kpis(perf)
    cycle_rows = load_cycle_ledger(campaign_dir)
    from trading_bot.paper.poc02_observation import (
        bottleneck_distribution,
        regime_bottleneck_matrix,
    )

    bottlenecks = bottleneck_distribution(cycle_rows)
    matrix = regime_bottleneck_matrix(cycle_rows)
    staleness = runtime_staleness(
        _load_state(campaign_dir)
    )
    report = {
        "artifact": "POC02_DAILY_OBSERVATION_REPORT",
        "campaign_id": POC02_CAMPAIGN_ID,
        "generated_at_utc": now.isoformat(),
        "days_finalized_now": finalized,
        "daily_performance": perf,
        "frequency_kpis": freq,
        "bottleneck_distribution": bottlenecks,
        "regime_bottleneck_matrix": matrix,
        "runtime_staleness": staleness,
        "no_parameter_change": True,
        "discovery_batch_03": "NOT_STARTED",
        "confirmation_lock": {
            "confirmation_id": "CONF-EDGE-002-001",
            "window": "2026-09-08 → 2026-09-22",
            "consumed": False,
            "executions": 0,
        },
    }
    day = now.strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"DAILY_OBSERVATION_{day}.json"
    _write_json(path, report)
    write_status(campaign_dir)
    return report


def _load_state(campaign_dir: Path) -> dict:
    path = campaign_dir / "POC02_CAMPAIGN_STATE.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", action="store_true", help="write daily observation report")
    parser.add_argument("--status", action="store_true", help="write read-only STATUS surfaces")
    parser.add_argument("--resolve-shadow", action="store_true", help="PIT-resolve pending shadow captures")
    parser.add_argument(
        "--campaign-dir", type=Path, default=CAMPAIGN_DIR,
        help="campaign directory (default: reports/poc02-paper-clean-01)",
    )
    args = parser.parse_args(argv)
    campaign_dir = args.campaign_dir.resolve()

    if args.resolve_shadow:
        from trading_bot.shadow.resolver import resolve_pending_shadow_captures

        summary = resolve_pending_shadow_captures(
            captures_path=campaign_dir / "shadow" / "shadow_captures.jsonl",
            outcomes_path=campaign_dir / "shadow" / "shadow_outcomes.jsonl",
        )
        _write_json(REPORTS_DIR / "SHADOW_RESOLUTION_LATEST.json", summary)
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if args.daily:
        report = run_daily(campaign_dir)
        print(json.dumps(report, indent=2, default=str))
        return 0

    if args.status:
        path = write_status(campaign_dir)
        print(f"STATUS written: {path}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
