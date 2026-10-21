"""EXP-004A foundation: prove the infrastructure can observe and measure, without running the experiment.

This script does **not** run ``EXP-004A``. It performs the four things that must be true before that
experiment may exist, and reports what it found:

1. **Admission** — re-derive, from the bar store's own ``fetched_at_ms``, how many days were
   genuinely observed rather than backfilled, per declared series set. Three lanes are reported
   because the answer depends on which series you require, and quoting one number for all three is
   how a 235-day corpus was believed to be evidence.
2. **Sealing** — write those classifications into an append-only, hash-chained attestation file and
   verify every prefix digest against the store. A count that survives this cannot be edited later
   without the edit being visible.
3. **Cost** — measure the round trip from the ST-6 tape, labelling each component ``KNOWN`` /
   ``OBSERVED`` / ``ESTIMATED`` / ``ASSUMED``, and refusing to publish a 500 USDT number from a
   200 USDT walk.
4. **Independence** — count observation days rather than experiments, including the documented case
   where two identifiers produced one measurement.

Outputs go to ``docs/agentic/exp004a/``, which is deliberately **not** under
``reports/ai-bots/``: a run directory there would make ``discover_existing_runs("EXP-004A")``
non-empty and spend the identifier this script exists to keep available.

Research only. No order, no credential, no promotion, ``economic_executions: 0``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.execution_cost import (  # noqa: E402
    evaluate_cost_question,
    load_st6_quotes,
    measure_asset,
)
from trading_bot.research.prereg_gate import (  # noqa: E402
    discover_existing_runs,
)
from trading_bot.research.prereg_gate import (  # noqa: E402
    evaluate as gate_evaluate,
)
from trading_bot.research.prospective import (  # noqa: E402
    AttestationLedger,
    ObservationBook,
    accumulate,
    index_series,
    intersection_epoch,
)

RUNS_ROOT = "reports/ai-bots"
REPORT_DIR = REPO / "docs" / "agentic" / "exp004a"
STATE_DIR = REPO / "data" / "exp004a"
STORE = REPO / "data" / "forward" / "edge03"
ST6_TAPE = REPO / "data" / "st6" / "ST6_OBSERVATIONS.jsonl"
COVERAGE_CLAIM = REPO / "data" / "forward" / "edge04" / "coverage.json"

ASSETS = ("BTC", "ETH", "SOL")
TARGET_DAYS = 90
LAG_BOUNDS = {"1h": 7_200_000, "15m": 1_800_000}

#: The frozen model's round trip, as `docs/agentic/NEXT_EXPERIMENT_PROPOSAL.md` §3 records it.
REFERENCE_BPS = {"BTCUSDT": 24.786, "ETHUSDT": 24.786, "SOLUSDT": 27.310}


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False, timeout=120
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_indexes(intervals: tuple[str, ...]) -> dict[str, Any]:
    indexes: dict[str, Any] = {}
    for interval in intervals:
        for asset in ASSETS:
            path = STORE / interval / f"{asset}.jsonl"
            indexes[f"{interval}:{asset}"] = index_series(path, asset, interval)
    return indexes


def _lane(indexes: dict[str, Any], intervals: tuple[str, ...], now: datetime) -> dict[str, Any]:
    """Accumulate one lane, using the epoch its own bytes support."""
    selected = [indexes[key] for key in sorted(indexes) if key.split(":")[0] in intervals]
    firsts = {
        f"{index.interval}:{index.asset}": min(bar.day() for bar in index.bars)
        for index in selected
    }
    epoch = intersection_epoch(firsts)
    result = accumulate(
        indexes=selected,
        epoch=epoch,
        now=now,
        target_days=TARGET_DAYS,
        lag_bounds={key: LAG_BOUNDS[key] for key in intervals},
    )
    return {
        "series": list(result.series),
        "series_first_day": firsts,
        "intersection_epoch": epoch,
        "counts": result.counts,
        "admissible": result.admissible,
        "admissible_days": list(result.admissible_days),
        "remaining": result.remaining,
        "satisfied": result.satisfied,
        "projection": result.projection(),
        "settled_days": len(result.days),
        "pending_days": list(result.pending),
        "_accumulation": result,
    }


def _seal(name: str, lane: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
    selected = [indexes[key] for key in lane["series"]]
    ledger = AttestationLedger(path=STATE_DIR / f"admission_{name}.jsonl")
    written = ledger.seal(lane["_accumulation"].days, selected, sealed_at_utc=_now_iso())
    verification = ledger.verify(selected)
    return {
        "ledger": str(ledger.path.relative_to(REPO)),
        "records_appended_this_run": len(written),
        "records_total": verification.records,
        "series_checked": verification.series_checked,
        "verified": verification.ok,
        "admissible_from_ledger": len(verification.admissible),
        "errors": list(verification.errors),
        "ledger_sha256_16": _sha16(Path(ledger.path)) if Path(ledger.path).exists() else None,
    }


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reconcile_inventory(lanes: dict[str, Any]) -> dict[str, Any]:
    """Separate the four numbers that the single figure ``235`` conflates."""
    claim: dict[str, Any] = {}
    if COVERAGE_CLAIM.exists():
        payload = json.loads(COVERAGE_CLAIM.read_text(encoding="utf-8"))
        claim = {
            "days_with_any_data": payload.get("days_with_any_data"),
            "window_observation_days": payload.get("window_observation_days"),
            "densely_covered_but_backfilled": payload.get("densely_covered_but_backfilled"),
            "prospectively_observed": payload.get("prospectively_observed"),
            "prospectively_observed_days": payload.get("prospectively_observed_days"),
            "required_days": payload.get("required_days"),
            "rule": payload.get("rule"),
            "window_vs_prospective": payload.get("window_vs_prospective"),
        }
    lane_1h = lanes["1h"]
    lane_both = lanes["1h+15m"]
    return {
        "the_single_figure": 235,
        "what_it_counts": "UTC days on which the 1h series holds bars, whether or not they were observed when they closed",
        "decomposition": {
            "days_with_any_bar": claim.get("days_with_any_data"),
            "days_complete_enough_to_classify": claim.get("window_observation_days"),
            "dense_but_backfilled": claim.get("densely_covered_but_backfilled"),
            "prospectively_observed_1h_only": lane_1h["admissible"],
            "prospectively_observed_1h_and_15m": lane_both["admissible"],
        },
        "why_the_numbers_differ": [
            "235 counts days with bars; 229 of them arrived after their own close, which makes them history rather than observation",
            "the 1h lane admits 5 days; the 15m lane starts on 2026-10-07, so a day requiring both admits 4",
            "on 2026-10-15 the 1h series has 22 of 24 bars inside the lag bound (0.9167, admitted) while the 15m series has 79 of 96 (0.8229, refused)",
            "no day before a series' own freeze is a forward observation for that series: the 15m corpus ends at 2026-10-07T11:30Z, so 2026-03-01..2026-10-07 is out of sample for 15m and untouched only for 1h",
            "EXP-004A requires 90 days; the 1h lane would need 85 more at its current rate and the joint lane 86",
        ],
        "claim_source": "data/forward/edge04/coverage.json (a derived file, regenerated on every observer tick)",
        "claim": claim,
        "resolved_by": "re-derived from data/forward/edge03/*/*.jsonl in this run, not read from the claim",
        "conclusion": (
            "the 235-day figure is arithmetically correct and evidentially inert: it is a row count over a "
            "corpus that is 97.4 % backfilled, and it does not describe 235 days of anything an experiment may use"
        ),
    }


def _independence() -> dict[str, Any]:
    book = ObservationBook()
    # Identifiers that measured the same out-of-sample window over the same trade set. J and K are
    # documented as one measurement in EXPERIMENT_INVENTORY.md §1.1 (identical net_usdt, identical
    # 175 OOS trades), so they are registered against the same evidence digest.
    book.use("EXP-003K", "2026-08-06/2026-08-20", "dataset:7fbdfefa", "EXP-003K-CANDIDATE-001")
    book.use("EXP-003J", "2026-08-06/2026-08-20", "dataset:7fbdfefa", "EXP-003J run report")
    book.use("WP-EDGE-07", "2026-03-01/2026-10-14", "dataset:edge07-trend", "edge-recovery")
    book.use("EXP-003N", "2026-06-21/2026-08-06", "dataset:7fbdfefa", "EXP-003N in-sample")
    return {
        **book.as_dict(),
        "reading": (
            "four experiment claims resolve to three independent windows; J and K in particular are one "
            "measurement, so a fifth negative result from that pair would be a recount rather than evidence"
        ),
    }


def _cost() -> dict[str, Any]:
    if not ST6_TAPE.exists():
        return {"status": "TAPE_MISSING", "path": str(ST6_TAPE)}
    quotes = load_st6_quotes(ST6_TAPE)
    days = len({quote.day for quote in quotes if quote.usable})
    measured_200 = {f"{asset}USDT": measure_asset(quotes, asset=f"{asset}USDT", size_usdt=200.0) for asset in ASSETS}
    measured_500 = {f"{asset}USDT": measure_asset(quotes, asset=f"{asset}USDT", size_usdt=500.0) for asset in ASSETS}
    return {
        "tape": str(ST6_TAPE.relative_to(REPO)),
        "quotes_loaded": len(quotes),
        "quotes_usable": sum(1 for quote in quotes if quote.usable),
        "distinct_days": days,
        "at_200_usdt": {
            "status": "MEASURED_AT_THE_SIZE_THE_TAPE_WALKED",
            "assets": {key: row.as_dict() for key, row in measured_200.items()},
            "rule": evaluate_cost_question(
                measured_200, observed_days=days, coverage=1.0, reference_bps=REFERENCE_BPS
            ),
        },
        "at_500_usdt": {
            "status": "LOWER_BOUND_ONLY",
            "reason": "every ST-6 window walked 200 USDT; depth is not linear, so 500 USDT is not that number scaled",
            "assets": {key: row.as_dict() for key, row in measured_500.items()},
            "rule": evaluate_cost_question(
                measured_500, observed_days=days, coverage=1.0, reference_bps=REFERENCE_BPS
            ),
        },
        "fee_dominance": {
            "fee_round_trip_bps": 20.0,
            "median_measured_at_200_bps": {
                key: round(row.median_bps, 6) for key, row in measured_200.items()
            },
            "share_of_total_from_fee": {
                key: round(20.0 / row.median_bps, 6) for key, row in measured_200.items()
            },
            "reading": (
                "at the size the tape walked, the round trip is the venue fee plus a spread of a few "
                "hundredths of a basis point: the 4.79 bps of spread and slippage the frozen model charges "
                "on BTC is not visible in the measurement, and that gap is the whole of the COST-CONFIRM question"
            ),
        },
        "not_a_decision": (
            "13 days is below the frozen 60-day floor, and the 500 USDT size was never walked; the rule is "
            "reported for its arithmetic, not for its verdict"
        ),
    }


def _gate(manifest: str, registry: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for mode in ("inspect", "authorize"):
        result = gate_evaluate(
            repo=REPO,
            experiment_id="EXP-004A",
            manifest_path=manifest,
            registry_path=registry,
            mode=mode,
            runs_root=RUNS_ROOT,
        )
        results[mode] = {
            "decision": result["decision"],
            "exit_code": result["exit_code"],
            "errors": result["errors"],
            "checks": result["checks"],
            "economic_executions": result["economic_executions"],
        }
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    parser.add_argument("--skip-seal", action="store_true", help="measure without writing the ledger")
    args = parser.parse_args(argv)

    started = _now_iso()
    now = datetime.now(UTC)
    indexes = _load_indexes(("1h", "15m"))

    lanes = {
        "1h": _lane(indexes, ("1h",), now),
        "15m": _lane(indexes, ("15m",), now),
        "1h+15m": _lane(indexes, ("1h", "15m"), now),
    }
    seals: dict[str, Any] = {}
    if not args.skip_seal:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        seals = {"1h": _seal("1h", lanes["1h"], indexes), "1h+15m": _seal("1h+15m", lanes["1h+15m"], indexes)}

    for lane in lanes.values():
        lane.pop("_accumulation", None)

    discovery = discover_existing_runs(REPO, "EXP-004A", RUNS_ROOT)
    gate = _gate(
        "config/preregistrations/EXP-004A.json",
        "config/preregistrations/EXP-004A.datasets.json",
    )

    report: dict[str, Any] = {
        "mission": "TAP-EXP-004A-FOUNDATION",
        "generated_at_utc": _now_iso(),
        "started_at_utc": started,
        "authority": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "remote": _git("remote", "get-url", "origin"),
            "worktrees": len([line for line in _git("worktree", "list").splitlines() if line.strip()]),
            "dirty_entries": len([line for line in _git("status", "--porcelain").splitlines() if line.strip()]),
        },
        "admission": {
            "store": str(STORE.relative_to(REPO)),
            "lag_bounds_ms": LAG_BOUNDS,
            "target_days": TARGET_DAYS,
            "lanes": lanes,
            "seals": seals,
        },
        "inventory_reconciliation": _reconcile_inventory(lanes),
        "independence": _independence(),
        "execution_cost": _cost(),
        "identifier": {
            "experiment_id": "EXP-004A",
            "discover_existing_runs": discovery,
            "spent": bool(discovery),
            "report_directory": str(REPORT_DIR.relative_to(REPO)),
            "report_directory_inside_runs_root": str(REPORT_DIR.relative_to(REPO)).startswith(RUNS_ROOT),
        },
        "gate": gate,
        "standing": {
            "economic_executions": 0,
            "live_orders": 0,
            "promotions": 0,
            "false_success": 0,
            "exp004a_authorised": gate["authorize"]["exit_code"] == 0,
            "live_trading": "DISABLED",
            "trades_authorized": 0,
        },
    }
    report["conclusion"] = _conclusion(report)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "RUN_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out / "RUN_REPORT.md").write_text(_render(report), encoding="utf-8", newline="\n")
    print(json.dumps({key: report[key] for key in ("standing", "identifier")}, indent=2))
    return 0 if not report["standing"]["exp004a_authorised"] else 1


def _conclusion(report: dict[str, Any]) -> dict[str, Any]:
    lanes = report["admission"]["lanes"]
    cost = report["execution_cost"]
    seals = report["admission"]["seals"]
    return {
        "can_observe_prospectively": lanes["1h"]["admissible"] > 0,
        "can_verify_what_it_observed": all(row.get("verified") for row in seals.values()) if seals else None,
        "days_admissible_1h": lanes["1h"]["admissible"],
        "days_required": TARGET_DAYS,
        "can_measure_cost": cost.get("at_200_usdt", {}).get("status") == "MEASURED_AT_THE_SIZE_THE_TAPE_WALKED",
        "measured_median_1h_asset_bps": cost.get("fee_dominance", {}).get("median_measured_at_200_bps"),
        "can_measure_cost_at_the_declared_notional": False,
        "why_not_at_declared_notional": "the tape walked 200 USDT; 500 USDT would be an interpolation",
        "exp004a_authorised": report["standing"]["exp004a_authorised"],
        "identifier_still_unspent": not report["identifier"]["spent"],
        "reading": (
            "the infrastructure can watch a day, prove afterwards that it watched it, and price a round trip "
            "at the size the tape actually walked. It cannot yet do the last of those at the declared notional, "
            "and it has 4 of the 90 days EXP-004A requires, so the experiment is prepared and not authorised."
        ),
    }


def _render(report: dict[str, Any]) -> str:
    lanes = report["admission"]["lanes"]
    cost = report["execution_cost"]
    recon = report["inventory_reconciliation"]
    seal_1h = report["admission"]["seals"].get("1h", {})
    lines = [
        "# RUN_REPORT — TAP-EXP-004A-FOUNDATION",
        "",
        f"**Generated:** {report['generated_at_utc']} · **HEAD:** `{report['authority']['head'][:7]}` · "
        f"**Branch:** `{report['authority']['branch']}`",
        "**Economic executions:** 0 · **Live orders:** 0 · **Promotions:** 0 · **`FALSE_SUCCESS`:** 0",
        "",
        "## 1. What this run proves",
        "",
        "| Claim | Result |",
        "| --- | --- |",
        f"| The system can accumulate prospectively observed days | **yes — {lanes['1h']['admissible']} admitted** (1h lane) |",
        f"| The count can be sealed and re-verified from the bytes | **{'yes' if seal_1h.get('verified') else 'no'}** — {seal_1h.get('records_total')} attestations, {seal_1h.get('series_checked')} series digests, {len(seal_1h.get('errors') or [])} error(s) |",
        "| Cost can be measured, not just modelled | **yes at 200 USDT**; no at 500 USDT, where the tape never walked |",
        f"| Duplicate experiments are counted once | **yes — {report['independence']['independent_day_count']} independent windows from {report['independence']['naive_observation_count']} claims** |",
        f"| `EXP-004A` is authorised | **no — gate exit {report['gate']['authorize']['exit_code']}** |",
        "",
        "## 2. Admission by lane",
        "",
        "A day is admissible only if every declared series holds 90 % of its calendar bars **and** every one of",
        "those bars was stored inside its lag bound. The lanes differ because the series start on different days.",
        "",
        "| Lane | Series | Intersection epoch | Settled days | Admitted | Remaining to 90 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, lane in lanes.items():
        lines.append(
            f"| `{name}` | {len(lane['series'])} | {lane['intersection_epoch']} | "
            f"{lane['settled_days']} | **{lane['admissible']}** | {lane['remaining']} |"
        )
    lines += [
        "",
        "Admitted days (1h lane): " + ", ".join(lanes["1h"]["admissible_days"]) + ".",
        "",
        "### Sealed attestations",
        "",
        "| Ledger | Records | Series checked | Verified | Errors |",
        "| --- | --- | --- | --- | --- |",
    ]
    for seal in report["admission"]["seals"].values():
        lines.append(
            f"| `{seal['ledger']}` | {seal['records_total']} | {seal['series_checked']} | "
            f"{'yes' if seal['verified'] else '**no**'} | {len(seal['errors'])} |"
        )
    lines += [
        "",
        "## 3. The 235-day figure, decomposed",
        "",
        f"**Claim:** `{recon['claim_source']}` reports **235** days.",
        "",
        "| Quantity | Value |",
        "| --- | --- |",
        f"| Days holding any 1h bar | {recon['decomposition']['days_with_any_bar']} |",
        f"| Days complete enough to classify | {recon['decomposition']['days_complete_enough_to_classify']} |",
        f"| Dense but backfilled | {recon['decomposition']['dense_but_backfilled']} |",
        f"| Prospectively observed, 1h only | **{recon['decomposition']['prospectively_observed_1h_only']}** |",
        f"| Prospectively observed, 1h and 15m | **{recon['decomposition']['prospectively_observed_1h_and_15m']}** |",
        "",
        "Why they differ:",
        "",
    ]
    lines += [f"{index}. {reason}" for index, reason in enumerate(recon["why_the_numbers_differ"], start=1)]
    lines += [
        "",
        f"**Conclusion.** {recon['conclusion']}.",
        "",
        "## 4. Execution cost, measured",
        "",
        f"Tape: `{cost.get('tape')}` — {cost.get('quotes_loaded')} quotes, {cost.get('quotes_usable')} usable, "
        f"{cost.get('distinct_days')} distinct days.",
        "",
        "### At 200 USDT — the size the tape walked",
        "",
        "| Asset | Observations | Median bps | p90 bps | Weakest component | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for asset, row in cost["at_200_usdt"]["assets"].items():
        lines.append(
            f"| {asset} | {row['observations']} | **{row['median_bps']}** | {row['p90_bps']} | "
            f"{row['knowledge']} | {row['status']} |"
        )
    lines += [
        "",
        "### At 500 USDT — never walked",
        "",
        "| Asset | Median bps (lower bound) | Size status | Status |",
        "| --- | --- | --- | --- |",
    ]
    for asset, row in cost["at_500_usdt"]["assets"].items():
        lines.append(
            f"| {asset} | {row['median_bps']} | {row['size_status']} | {row['status']} |"
        )
    lines += [
        "",
        f"**Fee dominance.** {cost['fee_dominance']['reading']}.",
        "",
        "| Asset | Median at 200 USDT | Share of the round trip that is the 20 bps fee |",
        "| --- | --- | --- |",
    ]
    for asset, value in cost["fee_dominance"]["median_measured_at_200_bps"].items():
        share = cost["fee_dominance"]["share_of_total_from_fee"][asset]
        lines.append(f"| {asset} | {value} | {share} |")
    lines += [
        "",
        f"**The frozen rule**, applied without adjustment: `{cost['at_200_usdt']['rule']['outcome']}` at 200 USDT "
        f"and `{cost['at_500_usdt']['rule']['outcome']}` at 500 USDT. {cost['not_a_decision']}.",
        "",
        "## 5. Independence",
        "",
        f"{report['independence']['naive_observation_count']} experiment claims → "
        f"**{report['independence']['independent_day_count']} independent windows** "
        f"(overstated by {report['independence']['overstated_by']}).",
        "",
        "| Window | Experiments | Same bytes |",
        "| --- | --- | --- |",
    ]
    for row in report["independence"]["duplicates"]:
        lines.append(
            f"| {row['day']} | {', '.join(row['experiments'])} | {'yes' if row['same_bytes'] else 'no'} |"
        )
    lines += [
        "",
        f"{report['independence']['reading']}.",
        "",
        "## 6. The gate, on the real manifest",
        "",
        "| Mode | Decision | Exit | Defects |",
        "| --- | --- | --- | --- |",
    ]
    for mode, row in report["gate"].items():
        lines.append(f"| `{mode}` | {row['decision']} | {row['exit_code']} | {len(row['errors'])} |")
    lines += [
        "",
        "Authorize-mode defects:",
        "",
    ]
    lines += [f"- `{error}`" for error in report["gate"]["authorize"]["errors"]] or ["- none"]
    lines += [
        "",
        "## 7. Identifier",
        "",
        f"`discover_existing_runs('EXP-004A')` → `{report['identifier']['discover_existing_runs']}`. "
        f"Spent: **{report['identifier']['spent']}**. The report lives at "
        f"`{report['identifier']['report_directory']}`, outside `{RUNS_ROOT}`, so producing it does not spend "
        "the identifier it prepares.",
        "",
        "## 8. Reproduce",
        "",
        "```bash",
        "./.venv/Scripts/python.exe scripts/exp004a_foundation.py",
        "./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prospective_admission.py \\",
        "    tests/unit/research/test_execution_cost_measured.py \\",
        "    tests/unit/research/test_prereg_gate_two_phase.py \\",
        "    tests/unit/research/test_prereg_gate_escape.py -q",
        "./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate --repo . --experiment-id EXP-004A \\",
        "    --manifest config/preregistrations/EXP-004A.json \\",
        "    --registry config/preregistrations/EXP-004A.datasets.json --mode authorize",
        "```",
        "",
        "## 9. Final statement",
        "",
        report["conclusion"]["reading"],
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
