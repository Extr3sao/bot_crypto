"""RFC-046 controlled discovery campaign — one run, three frozen hypotheses, no tuning.

The driver is deliberately boring: it loads the frozen specs, builds signals from local data,
simulates long/cash fills at the next bar open with the audited cost, evaluates
``PROFITABILITY_GATE_V1`` for each candidate, and stops.

What it cannot do, by construction:

* it has no parameter search, no asset sweep and no timeframe sweep (the specs are inputs);
* it never writes to ``docs/`` or to any governance file;
* it never touches ``reports/rfc035*`` or any rights of way the closed campaigns own;
* it does not refill hypotheses when a candidate fails: ``DISCOVERY_CAMPAIGN_FAILED`` is a result.

Every run records its real UTC instant (the owner's requirement for this programme, which is a
deliberate exception to the repository's no-typed-timestamps convention: the timestamp is computed,
never authored).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research import discovery as D

REPO = Path(__file__).resolve().parents[1]
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"
DATA = REPO / "data" / "raw"
RUN_JSON = REPO / "data" / "rfc046" / "RUN_REPORT.json"
RUN_MD = REPO / "data" / "rfc046" / "RUN_REPORT.md"
DETAIL = REPO / "reports" / "rfc046" / "CAMPAIGN_DETAIL.json"


def _funding_path(asset: str) -> Path:
    return DATA / "alpha002" / "funding_rate" / f"{asset}.json"


def _price_path(asset: str) -> Path:
    return DATA / "alpha003" / "price" / f"{asset}_1h.json"


def run_spec(path: Path) -> dict[str, Any]:
    spec = D.load_spec(path)
    bars = D.load_bars(_price_path(spec.asset))
    funding = D.load_funding(_funding_path(spec.asset))
    if spec.strategy == "weekend_rebound":
        signals = D.signal_weekend_rebound(bars, spec.parameters)
    elif spec.strategy == "settlement_dip":
        signals = D.signal_settlement_dip(bars, funding, spec.parameters)
    elif spec.strategy == "funding_capitulation":
        signals = D.signal_funding_capitulation(bars, funding, spec.parameters)
    else:
        raise D.SpecError(f"{spec.candidate_id}: no generator for strategy {spec.strategy!r}")
    base = D.simulate(spec, bars, signals, cost_multiple=1.0)
    gate = D.evaluate_gate(spec, base, trials=len(list(SPECS.glob("HYP-*.json"))))
    return {
        "spec": spec.to_json(),
        "spec_hash": D.spec_hash_from_file(path),
        "signals": len(signals),
        "trades": [asdict(t) for t in base],
        "gate": gate,
        "data": {
            "price_file": str(_price_path(spec.asset).relative_to(REPO)),
            "funding_file": str(_funding_path(spec.asset).relative_to(REPO)),
            "bars": len(bars),
            "funding_points": len(funding),
            "first_bar_ms": bars[0].open_time_ms if bars else None,
            "last_bar_ms": bars[-1].open_time_ms if bars else None,
        },
    }


def summarise(runs: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = {r["spec"]["candidate_id"]: r["gate"]["verdict"] for r in runs}
    admitted = [c for c, v in verdicts.items() if v == "CANDIDATE_ADMITTED_TO_PAPER_REVIEW"]
    return {
        "campaign_status": "CANDIDATE_ADMITTED" if admitted else "DISCOVERY_CAMPAIGN_FAILED",
        "admitted": admitted,
        "verdicts": verdicts,
        "refill": "NONE — a failed campaign ends; no new hypotheses are generated",
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# RFC-046 RUN REPORT — CONTROLLED DISCOVERY, FIRST CAMPAIGN",
        "",
        f"generated_at_utc = {report['generated_at_utc']} (computed, not authored)",
        f"head_at_run = {report['head_at_run']}",
        f"campaign_status = **{report['campaign']['campaign_status']}**",
        "discovery_offline_authorized = TRUE (ADR-0024)",
        "live_trading = DISABLED",
        "trades_authorized = 0",
        "false_success = 0",
        "",
        "## Candidates (frozen before evaluation; one run, no tuning)",
        "",
        "| candidate | hypothesis | mechanism | asset | strategy | spec_sha256 | trades | OOS trades | net expectancy | net PF | verdict | failed gates |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in report["runs"]:
        spec, gate, metrics = run["spec"], run["gate"], run["gate"]["metrics"]
        lines.append(
            "| {cand} | {hyp} | {mech} | {asset} | {strategy} | `{sha}` | {n} | {oos} | {exp} | {pf} | **{verdict}** | {failed} |".format(
                cand=spec["candidate_id"],
                hyp=spec["hypothesis_id"],
                mech=spec["mechanism"],
                asset=spec["asset"],
                strategy=spec["strategy"],
                sha=run["spec_hash"][:16],
                n=metrics["trades_total"],
                oos=metrics["trades_oos"],
                exp="n/a"
                if metrics["net_expectancy"] is None
                else f"{metrics['net_expectancy'] * 1e4:.2f} bps",
                pf="n/a" if metrics["net_pf"] is None else f"{metrics['net_pf']:.3f}",
                verdict=gate["verdict"],
                failed=", ".join(gate["failed"]) or "—",
            )
        )
    lines += [
        "",
        "Cost model: 23.7906 bps round trip (Binance Spot VIP0 taker, ~1,000 USD notional, "
        "COST_MODEL_V3) and 1.5x = 35.6859 bps in the stress column. Long/cash only: the runtime "
        "excludes derivatives (SRC-02) and spot cannot short.",
        "",
        "Partitions (frozen in the specs, final OOS opened once, never used for selection):",
        "",
        "| partition | window |",
        "| --- | --- |",
    ]
    for part in report["runs"][0]["spec"]["partitions"]:
        lines.append(f"| {part['name']} | {_iso(part['start_ms'])} → {_iso(part['end_ms'])} |")
    lines += [
        "",
        "## Gate detail (PROFITABILITY_GATE_V1, PG-1..PG-11)",
        "",
    ]
    for run in report["runs"]:
        lines.append(f"### {run['spec']['candidate_id']} — {run['gate']['verdict']}")
        lines.append("")
        lines.append("| gate | requirement | pass | observed |")
        lines.append("| --- | --- | --- | --- |")
        for req in run["gate"]["requirements"]:
            observed = req["observed"]
            if isinstance(observed, float):
                observed = f"{observed:.6g}"
            lines.append(f"| {req['id']} | {req['requirement']} | {req['pass']} | {observed} |")
        lines.append("")
    lines += [
        "## Stop rule",
        "",
        f"- {report['campaign']['refill']}",
        "- Builder and verifier are different programs (`scripts/rfc046_campaign_verify.py`).",
        "- A rejection is recorded evidence, not a failure to hide.",
        "",
        "## Standing state (unchanged by this run)",
        "",
        "```text",
        "G_BUSINESS_REENTRY != PASS",
        "LIVE_TRADING = DISABLED",
        "TRADES_AUTHORIZED = 0",
        "PROFITABILITY_VERIFIED = FALSE",
        "```",
        "",
    ]
    return "\n".join(lines)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-suite", action="store_true", help="record the suite as not run")
    args = parser.parse_args()

    spec_paths = sorted(SPECS.glob("HYP-*.json"))
    if not spec_paths:
        raise SystemExit(f"no frozen specs under {SPECS}")
    runs = [run_spec(path) for path in spec_paths]
    campaign = summarise(runs)

    head = "UNKNOWN"
    try:
        import subprocess

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout
        dirty = sorted(line[3:] for line in tree.splitlines() if line.strip())
    except Exception as exc:  # pragma: no cover - git is always present in this checkout
        dirty = [f"UNKNOWN: {exc}"]

    report = {
        "artifact": "RFC-046_FIRST_CAMPAIGN_RUN_REPORT",
        "rfc": "RFC-046",
        "rfc_status": "APPROVED / ACTIVE (ADR-0024, 2026-10-08, option 5A)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_at_run": head,
        "working_tree_at_run": dirty,
        "cost_bps_round_trip": D.ROUND_TRIP_BPS,
        "cost_bps_stressed": round(D.ROUND_TRIP_BPS * D.STRESS_MULTIPLE, 4),
        "signal_version": D.SIGNAL_VERSION,
        "runtime_state": {
            "discovery_offline_authorized": True,
            "live_trading": "DISABLED",
            "trades_authorized": 0,
            "G_BUSINESS_REENTRY": "NOT_PASS",
            "profitability_verified": False,
            "false_success": 0,
        },
        "blockers_registered": [
            "DEF-HTF-PIT-001: not on this data path; the campaign imports no market_data module and "
            "the negative control test asserts the defective helper is absent from it",
            "TD-1 repo-wide mypy failure (another workstream's reports/ script)",
            "TD-2 RFC-035E verifier TypeError with absent inputs (OPEN_NOT_REPAIRED)",
            "TD-3 reports/ concurrency (detail written to reports/rfc046/, tracked summary in data/rfc046/)",
            "TD-4 artificial timestamps: every timestamp in this report is computed at run time",
            "TD-5 evidence outside git: RUN_REPORT.md/json are versioned in data/rfc046/",
        ],
        "campaign": campaign,
        "runs": runs,
    }

    DETAIL.parent.mkdir(parents=True, exist_ok=True)
    DETAIL.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        k: report[k]
        for k in (
            "artifact",
            "rfc",
            "rfc_status",
            "generated_at_utc",
            "head_at_run",
            "working_tree_at_run",
            "cost_bps_round_trip",
            "cost_bps_stressed",
            "signal_version",
            "runtime_state",
            "blockers_registered",
            "campaign",
        )
    }
    summary["runs"] = [
        {
            "hypothesis_id": r["spec"]["hypothesis_id"],
            "candidate_id": r["spec"]["candidate_id"],
            "mechanism": r["spec"]["mechanism"],
            "asset": r["spec"]["asset"],
            "strategy": r["spec"]["strategy"],
            "spec_hash": r["spec_hash"],
            "evidence_level": r["spec"]["evidence_level"],
            "data": r["data"],
            "gate": r["gate"],
        }
        for r in runs
    ]
    RUN_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RUN_MD.write_text(render_md(report), encoding="utf-8")

    print(json.dumps(campaign, indent=2))
    for run in runs:
        gate = run["gate"]
        print(
            f"{run['spec']['candidate_id']}: {gate['verdict']} "
            f"trades={gate['metrics']['trades_total']} oos={gate['metrics']['trades_oos']} "
            f"failed={gate['failed']}"
        )
    print(f"detail  -> {DETAIL.relative_to(REPO)}")
    print(f"summary -> {RUN_JSON.relative_to(REPO)} + {RUN_MD.relative_to(REPO)}")
    if args.skip_suite:
        print("full suite: NOT RUN IN THIS BUILD (recorded as such)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
