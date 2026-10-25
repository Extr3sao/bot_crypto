"""RFC-046 cost forensics — gross edge vs the documented cost floor.

The first campaign failed (`DISCOVERY_CAMPAIGN_FAILED`).  A rejection on net expectancy alone does
not say *why* it failed, and the two possible causes demand opposite conclusions:

* **cost-disqualified** — the mechanism earns a positive gross edge that the documented cost floor
  eats.  The edge exists; the venue, product or turnover does not permit harvesting it.
* **no gross edge** — the mechanism loses money before any cost is charged.  No cost improvement,
  venue change or fee tier can rescue it; the economic story is simply wrong.

This script recomputes both numbers from the raw price/funding files with the frozen specs, so the
decomposition is measured rather than inferred from the net figure.  It also records the cheapest
scenario in the frozen cost model, which bounds what a cost-side fix could ever reach.

It changes no policy, admits nothing, and does not touch the campaign verdict.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import run
from typing import Any

from trading_bot.research import discovery as D

REPO = Path(__file__).resolve().parents[1]
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"
DATA = REPO / "data" / "raw"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
RUN_JSON = REPO / "data" / "rfc046" / "RUN_REPORT.json"
OUT_JSON = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
OUT_MD = REPO / "data" / "rfc046" / "COST_FORENSICS.md"

SPOT = "Spot"
BPS = 10_000.0

# Verdict vocabulary.  Order matters: the first rule that matches wins.
VERDICT_ZERO_SAMPLE = "ZERO_SAMPLE"
VERDICT_NO_GROSS_EDGE = "NO_GROSS_EDGE"
VERDICT_COST_DISQUALIFIED = "COST_DISQUALIFIED"
VERDICT_COST_BOUND = "COST_BOUND"


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head() -> str:
    proc = run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _price_path(asset: str) -> Path:
    return DATA / "alpha003" / "price" / f"{asset}_1h.json"


def _funding_path(asset: str) -> Path:
    return DATA / "alpha002" / "funding_rate" / f"{asset}.json"


def _signals(
    spec: D.HypothesisSpec, bars: list[D.Bar], funding: list[D.FundingPoint]
) -> list[D.Signal]:
    if spec.strategy == "weekend_rebound":
        return D.signal_weekend_rebound(bars, spec.parameters)
    if spec.strategy == "settlement_dip":
        return D.signal_settlement_dip(bars, funding, spec.parameters)
    if spec.strategy == "funding_capitulation":
        return D.signal_funding_capitulation(bars, funding, spec.parameters)
    raise D.SpecError(f"{spec.candidate_id}: no generator for strategy {spec.strategy!r}")


def _mean_bps(values: list[float]) -> float | None:
    return round(sum(values) / len(values) * BPS, 6) if values else None


def cost_scenarios() -> dict[str, Any]:
    """The documented cost landscape, read from the frozen model rather than typed here."""
    doc = json.loads(COST_MODEL.read_text(encoding="utf-8"))
    rows = [
        {
            "scenario_id": s["evaluation"]["scenario_id"],
            "product": s["spec"]["product"],
            "round_trip_bps": float(s["evaluation"]["round_trip_bps"]),
        }
        for s in doc["scenarios"]
    ]
    rows.sort(key=lambda r: (r["round_trip_bps"], r["scenario_id"]))
    spot = [r for r in rows if r["product"] == SPOT]
    admission = next(r for r in rows if r["scenario_id"] == doc["admission_scenario_id"])
    return {
        "name": doc["model"],
        "admission_scenario": admission["scenario_id"],
        "admission_round_trip_bps": admission["round_trip_bps"],
        "stress_multiple": D.STRESS_MULTIPLE,
        "stressed_round_trip_bps": round(admission["round_trip_bps"] * D.STRESS_MULTIPLE, 4),
        "cheapest_documented_bps": rows[0]["round_trip_bps"],
        "cheapest_documented_scenario": rows[0]["scenario_id"],
        "cheapest_spot_bps": spot[0]["round_trip_bps"],
        "cheapest_spot_scenario": spot[0]["scenario_id"],
        "scenarios": rows,
    }


def _verdict(
    gross_all_bps: float | None,
    n_total: int,
    costs: dict[str, Any],
    partition_gross_bps: dict[str, float | None],
) -> tuple[str, str]:
    if n_total == 0 or gross_all_bps is None:
        return (
            VERDICT_ZERO_SAMPLE,
            "no trade was generated, so no edge was measured in either direction: the entry filter "
            "never fired on the frozen data. Nothing about cost or mechanism follows from this.",
        )
    if gross_all_bps <= 0.0:
        return (
            VERDICT_NO_GROSS_EDGE,
            f"gross expectancy is {gross_all_bps:.4f} bps per trade, i.e. the mechanism loses money "
            f"before any cost is charged. Cost reduction cannot rescue it; this is an economic "
            f"rejection, not an execution-cost rejection.",
        )

    # An aggregate positive gross is not the same as a harvestable one: if the sign is not stable
    # across partitions, the aggregate is carried by a single window and the mechanism has no edge
    # out of sample either.  Saying so is the difference between a forensics artefact and a flattering
    # one.
    unstable = [
        (name, value)
        for name, value in partition_gross_bps.items()
        if value is None or value <= 0.0
    ]
    stability_note = (
        ""
        if not unstable
        else (
            " The aggregate is not a stable edge: gross is not positive in "
            + ", ".join(f"{name} ({value} bps)" for name, value in unstable)
            + ", so the positive figure is confined to the earlier window and the mechanism has no "
            "gross edge out of sample either. Cost is the second problem, not the first."
        )
    )

    if gross_all_bps < costs["cheapest_documented_bps"]:
        return (
            VERDICT_COST_DISQUALIFIED,
            f"gross expectancy is {gross_all_bps:.4f} bps per trade, below even the cheapest "
            f"documented scenario in the frozen cost model "
            f"({costs['cheapest_documented_bps']} bps, {costs['cheapest_documented_scenario']}). "
            f"No cost-side change documented in this repository rescues it." + stability_note,
        )
    return (
        VERDICT_COST_BOUND,
        f"gross expectancy is {gross_all_bps:.4f} bps per trade: positive and above the cheapest "
        f"documented scenario, but below the admission cost of "
        f"{costs['admission_round_trip_bps']} bps. A cheaper documented venue/product could in "
        f"principle change the verdict, which makes this the only candidate whose failure is "
        f"primarily an execution-cost outcome." + stability_note,
    )


def analyse_spec(path: Path, costs: dict[str, Any], recorded: dict[str, Any]) -> dict[str, Any]:
    spec = D.load_spec(path)
    bars = D.load_bars(_price_path(spec.asset))
    funding = D.load_funding(_funding_path(spec.asset))
    signals = _signals(spec, bars, funding)
    trades = D.simulate(spec, bars, signals, cost_multiple=1.0)

    gross = [t.gross_ret for t in trades]
    net = [t.net_ret for t in trades]
    oos = [t for t in trades if t.partition == "final_oos"]

    # Identity guard: the decomposition is only meaningful if gross - cost == net for every trade.
    for trade in trades:
        expected = trade.gross_ret - spec.cost_bps / BPS
        if abs(expected - trade.net_ret) > 1e-12:
            raise D.SpecError(
                f"{spec.candidate_id}: net != gross - cost for the trade at {trade.entry_time_ms}; "
                f"the forensics decomposition would be unsound"
            )

    by_partition: dict[str, dict[str, Any]] = {}
    for name in [p.name for p in spec.partitions]:
        subset = [t for t in trades if t.partition == name]
        by_partition[name] = {
            "n": len(subset),
            "gross_bps": _mean_bps([t.gross_ret for t in subset]),
            "net_bps": _mean_bps([t.net_ret for t in subset]),
        }

    gross_all = _mean_bps(gross)
    wins = [t.gross_ret for t in trades if t.gross_ret > 0]
    losses = [t.gross_ret for t in trades if t.gross_ret <= 0]
    verdict, reason = _verdict(
        gross_all, len(trades), costs, {name: v["gross_bps"] for name, v in by_partition.items()}
    )

    recorded_net = recorded.get("metrics", {}).get("net_expectancy")
    recorded_net_bps = None if recorded_net is None else round(float(recorded_net) * BPS, 6)
    measured_net_bps = _mean_bps(net)

    return {
        "hypothesis_id": spec.hypothesis_id,
        "candidate_id": spec.candidate_id,
        "mechanism": spec.mechanism,
        "asset": spec.asset,
        "strategy": spec.strategy,
        "spec_hash": D.spec_hash_from_file(path),
        "signals": len(signals),
        "trades_total": len(trades),
        "trades_oos": len(oos),
        "gross_expectancy_bps": gross_all,
        "net_expectancy_bps": measured_net_bps,
        "oos_gross_expectancy_bps": _mean_bps([t.gross_ret for t in oos]),
        "oos_net_expectancy_bps": _mean_bps([t.net_ret for t in oos]),
        "stressed_net_expectancy_bps": _mean_bps([t.net_ret_stressed for t in trades]),
        "partition_detail": by_partition,
        "zero_sample": len(trades) == 0,
        # For a zero-sample candidate every partition is unmeasured, not measured-negative, so the
        # stability fields are left empty rather than reporting an absence of data as an edge verdict.
        "gross_positive_in_every_partition": (
            None
            if not trades
            else all(
                v["gross_bps"] is not None and v["gross_bps"] > 0.0 for v in by_partition.values()
            )
        ),
        "partitions_without_gross_edge": (
            []
            if not trades
            else sorted(
                name
                for name, v in by_partition.items()
                if v["gross_bps"] is None or v["gross_bps"] <= 0.0
            )
        ),
        "hit_rate": round(len(wins) / len(trades), 6) if trades else None,
        "avg_gross_win_bps": _mean_bps(wins),
        "avg_gross_loss_bps": _mean_bps(losses),
        "break_even_round_trip_bps": gross_all,
        "break_even_vs_admission": (
            None if gross_all is None else round(gross_all / costs["admission_round_trip_bps"], 6)
        ),
        "cost_reduction_factor_required": (
            None
            if gross_all is None or gross_all <= 0
            else round(costs["admission_round_trip_bps"] / gross_all, 6)
        ),
        "verdict": verdict,
        "verdict_reason": reason,
        "recorded_net_expectancy_bps": recorded_net_bps,
        "recorded_vs_measured": {
            # ``comparable`` is False only when the recorded run itself had no value to compare
            # (the zero-sample candidate).  A missing value is not a reproduction, so it is
            # recorded as not comparable rather than claimed as a match.
            "comparable": recorded_net_bps is not None and measured_net_bps is not None,
            "match": (
                (recorded_net_bps is None and measured_net_bps is None)
                or (
                    recorded_net_bps is not None
                    and measured_net_bps is not None
                    and abs(recorded_net_bps - measured_net_bps) < 1e-4
                )
            ),
            "abs_diff_bps": (
                None
                if recorded_net_bps is None or measured_net_bps is None
                else round(abs(recorded_net_bps - measured_net_bps), 9)
            ),
        },
    }


def build() -> dict[str, Any]:
    costs = cost_scenarios()
    run_report = json.loads(RUN_JSON.read_text(encoding="utf-8"))
    recorded_by_hypothesis = {
        r["hypothesis_id"]: r["gate"] for r in run_report["runs"] if "gate" in r
    }
    candidates = [
        analyse_spec(path, costs, recorded_by_hypothesis.get(path.stem, {}))
        for path in sorted(SPECS.glob("HYP-*.json"))
    ]
    mismatched = [
        c["candidate_id"]
        for c in candidates
        if c["recorded_vs_measured"]["comparable"] and not c["recorded_vs_measured"]["match"]
    ]
    if mismatched:
        raise D.SpecError(
            f"forensics disagree with the recorded run for {mismatched}; refusing to publish a "
            f"decomposition that does not reproduce the evidence it explains"
        )
    return {
        "artifact": "RFC-046_COST_FORENSICS",
        "rfc": "RFC-046",
        "purpose": (
            "Separate a cost-disqualified rejection (positive gross edge eaten by the documented "
            "cost floor) from an economic rejection (negative gross edge, which no cost can rescue)."
        ),
        "generated_at_utc": _now_utc(),
        "head_at_run": _head(),
        "cost_model": costs,
        "candidates": {c["candidate_id"]: c for c in candidates},
        "campaign_status_unchanged": run_report["campaign"]["campaign_status"],
        "false_success": 0,
        "standing_state": run_report["runtime_state"],
        "admission_effect": "NONE — this artefact explains a rejection; it admits nothing and it "
        "generates no new hypothesis (RFC-046 stop rule).",
    }


def _fmt(value: float | None, suffix: str = " bps") -> str:
    """A missing measurement is rendered as missing, never as ``None`` with units."""
    return "n/a (zero sample)" if value is None else f"{value}{suffix}"


def _cell(value: float | None) -> str:
    """Table cell: a missing measurement is ``n/a``, and no other cell is ever rewritten."""
    return "n/a" if value is None else str(value)


def render_md(report: dict[str, Any]) -> str:
    costs = report["cost_model"]
    lines = [
        "# RFC-046 COST FORENSICS — WHY THE THREE CANDIDATES DIED",
        "",
        f"generated_at_utc = {report['generated_at_utc']} (computed, not authored)",
        f"head_at_run = {report['head_at_run']}",
        f"campaign_status_unchanged = **{report['campaign_status_unchanged']}**",
        f"false_success = {report['false_success']}",
        "",
        "This artefact changes nothing: it decomposes a recorded rejection. It admits no candidate "
        "and generates no new hypothesis (RFC-046 stop rule).",
        "",
        "## The decomposition",
        "",
        f"`net = gross - {costs['admission_round_trip_bps']} bps` per round trip in the admission "
        f"scenario `{costs['admission_scenario']}`, so gross expectancy is net expectancy plus the "
        f"cost floor. Because the floor is a constant added to every trade, the sign of gross is the "
        f"sign of the mechanism's own edge and is independent of execution.",
        "",
        "| candidate | N | gross bps | net bps | break-even cost bps | hit rate | OOS gross bps | verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cid, c in report["candidates"].items():
        lines.append(
            f"| {cid} | {c['trades_total']} | {_cell(c['gross_expectancy_bps'])} | "
            f"{_cell(c['net_expectancy_bps'])} | {_cell(c['break_even_round_trip_bps'])} | "
            f"{_cell(c['hit_rate'])} | {_cell(c['oos_gross_expectancy_bps'])} | "
            f"**{c['verdict']}** |"
        )

    lines += [
        "",
        "## The documented cost landscape (frozen model, not retuned here)",
        "",
        "| scenario | product | round trip bps |",
        "| --- | --- | --- |",
    ]
    for row in costs["scenarios"]:
        lines.append(f"| {row['scenario_id']} | {row['product']} | {row['round_trip_bps']} |")
    lines += [
        "",
        f"Admission scenario: `{costs['admission_scenario']}` at "
        f"**{costs['admission_round_trip_bps']} bps**; stressed at "
        f"{costs['stress_multiple']}x = **{costs['stressed_round_trip_bps']} bps**. Cheapest "
        f"documented scenario of any product: **{costs['cheapest_documented_bps']} bps** "
        f"(`{costs['cheapest_documented_scenario']}`); cheapest *spot* scenario: "
        f"**{costs['cheapest_spot_bps']} bps** (`{costs['cheapest_spot_scenario']}`).",
        "",
        "## Per candidate",
        "",
    ]
    for cid, c in report["candidates"].items():
        lines += [
            f"### {cid} — {c['verdict']}",
            "",
            f"- strategy: `{c['strategy']}` on {c['asset']} ({c['mechanism']}); spec hash "
            f"`{c['spec_hash'][:16]}`",
            f"- gross expectancy: **{_fmt(c['gross_expectancy_bps'])}**; net expectancy "
            f"{_fmt(c['net_expectancy_bps'])}; stressed net {_fmt(c['stressed_net_expectancy_bps'])}",
            f"- break-even round trip: **{_fmt(c['break_even_round_trip_bps'])}**"
            + (
                ""
                if c["break_even_vs_admission"] is None
                else f" — {c['break_even_vs_admission']}x the admission cost"
            ),
            f"- out-of-sample: gross {_fmt(c['oos_gross_expectancy_bps'])} over "
            f"{c['trades_oos']} trades",
            f"- partitions: {json.dumps(c['partition_detail'], sort_keys=True)}",
            f"- gross positive in every partition: "
            f"{_cell(c['gross_positive_in_every_partition'])}"
            + (
                ""
                if c["zero_sample"] or not c["partitions_without_gross_edge"]
                else "; no gross edge in: " + ", ".join(c["partitions_without_gross_edge"])
            )
            + (" (unmeasured: no trades)" if c["zero_sample"] else ""),
            "- recorded run reproduced: "
            + (
                "n/a — the recorded run had no value to compare (not comparable)"
                if not c["recorded_vs_measured"]["comparable"]
                else f"{c['recorded_vs_measured']['match']} "
                f"(comparable: True, diff {c['recorded_vs_measured']['abs_diff_bps']} bps)"
            ),
            "",
            c["verdict_reason"],
            "",
        ]

    lines += [
        "## What this does and does not license",
        "",
        "- It does **not** change the campaign verdict: `DISCOVERY_CAMPAIGN_FAILED` stands.",
        "- It does **not** generate replacement hypotheses.",
        "- It **does** establish, from the recorded evidence, which of the two failure causes "
        "applies to each candidate — the input any future owner decision needs.",
        "",
        "```text",
        "G_BUSINESS_REENTRY != PASS",
        "LIVE_TRADING = DISABLED",
        "TRADES_AUTHORIZED = 0",
        "PROFITABILITY_VERIFIED = FALSE",
        "FALSE_SUCCESS = 0",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="build and verify, write nothing")
    args = parser.parse_args(argv)

    report = build()
    if args.check:
        print(json.dumps({"candidates": len(report["candidates"]), "ok": True}))
        return 0

    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(report), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO)}")
    print(f"wrote {OUT_MD.relative_to(REPO)}")
    for cid, c in report["candidates"].items():
        print(
            f"{cid}: gross={c['gross_expectancy_bps']} bps net={c['net_expectancy_bps']} bps "
            f"break_even={c['break_even_round_trip_bps']} bps -> {c['verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
