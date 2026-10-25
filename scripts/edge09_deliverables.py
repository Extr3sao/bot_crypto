#!/usr/bin/env python
"""WP-EDGE-09 — the artifact names RFC-EDGE-009 asks for, rendered from one reading.

    python scripts/edge09_deliverables.py

Every file written here is **derived**: it reorganises payloads that WP-EDGE-09A
to 09E already produced and measured, and re-measures nothing. Each artifact
carries the digests of the payloads it was rendered from, so the derivation can
be checked instead of trusted, and a field that was never measured is written as
``null`` with its name in ``unmeasured_fields`` rather than filled with a zero.

Written under ``reports/edge-recovery/WP-EDGE-09/``:

* ``BASELINE.json``                          (09A)
* ``DATA_CAPABILITY_REGISTRY.{json,md}``     (09A/09B)
* ``DATA_FEASIBILITY_MATRIX.{json,md}``      (09B)
* ``HYPOTHESIS_REGISTRY.json``, ``EXPERIMENT_PLAN.md``, ``WINDOW_LEDGER.jsonl`` (09C)
* ``ECONOMIC_FEASIBILITY_REPORT.{json,md}``, ``COST_CAPACITY_FREQUENCY_MATRIX.{json,md}`` (09D)
* ``EXPERIMENT_LEDGER.jsonl``, ``RESULTS_MATRIX.{json,md}`` (09E)
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09.registration import (  # noqa: E402
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    HYPOTHESES,
    LADDER,
    SCENARIOS_COMPARED,
    SCHEMA_VERSION,
    WP,
)

AUDIT_JSON = WP / "audit" / "ESTATE.json"
SOURCES_JSON = WP / "sources" / "SOURCE_VIABILITY.json"
PREREG_JSON = WP / "PREREGISTRATION.json"
PANEL_JSON = WP / "panel" / "PANEL.json"
GATES_JSON = WP / "gates" / "COST_LIQUIDITY_CAPACITY.json"
EXP_JSON = WP / "experiments" / "EXPERIMENTS.json"
REGISTRY_JSON = WP / "experiments" / "EXPERIMENT_REGISTRY.json"
VERIFY_JSON = WP / "VERIFICATION.json"

PANEL_CSV = WP / "panel" / "PANEL_SECONDS.csv"

FOLLOW_UP_JSON = WP / "DELIVERABLES.json"

#: Fields the RFC's records name that this package did not measure. They are
#: declared once, here, so no artifact can present a null as a measurement.
UNMEASURED = (
    "duplicates (the collector appends events; no trade-id de-duplication pass exists)",
    "stale_rate (no staleness threshold is registered for the forward capture)",
    "provider_failure_rate (reconnect counters exist in the capture, not a failure rate)",
    "turnover, exposure, max_drawdown, profit_factor, expectancy (no PnL backtest was run)",
    "pnl_usd (the cost gate stopped every arm before a simulator was invoked)",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def mtime_utc(path: Path) -> str | None:
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_from_ms(value: int | None) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def source_digests(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)).replace("\\", "/"): digest
        for path in paths
        if (digest := sha256_file(path))
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def fail_open(value: Any, digits: int = 4) -> Any:
    return None if value is None else round(float(value), digits)


# ------------------------------------------------------------------ 09A/09B


def baseline(facts: dict[str, Any]) -> dict[str, Any]:
    audit = facts["audit"]
    panel = facts["panel_meta"]
    authoritative = audit.get("authoritative") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09A",
        "artifact": "BASELINE",
        "as_of_utc": facts["as_of_utc"],
        "head": audit.get("head"),
        "branch": audit.get("branch"),
        "rfc_present": audit.get("rfc_present"),
        "authoritative_inputs": authoritative.get("files"),
        "runtime_mode": authoritative.get("runtime_mode"),
        "live_trading_enabled": {
            "runtime.yaml": authoritative.get("runtime_live_trading_enabled"),
            "risk.yaml": authoritative.get("risk_live_trading_enabled"),
        },
        "risk_limits_read_not_written": authoritative.get("risk_limits_read_not_written"),
        "data_estate": (audit.get("estate") or {}).get("directories"),
        "captures_enumerated": len(audit.get("captures") or []),
        "panel": {
            "runs": panel.get("runs"),
            "grid_seconds": panel.get("grid_seconds"),
            "declared_run_selection": panel.get("declared_run_selection"),
            "selection_rule": panel.get("selection_rule"),
            "built_at_utc": mtime_utc(PANEL_CSV),
            "digests": panel.get("digests"),
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
        },
        "tests": {
            "suite": "tests/unit/research/test_edge09_microstructure.py",
            "evidence": "RUN_REPORT.json -> tests (run with --tests during 09F)",
        },
        "unmeasured_fields": list(UNMEASURED),
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
        "promotion": "NONE",
        "order_sent": False,
    }


def data_capability_registry(facts: dict[str, Any]) -> dict[str, Any]:
    panel = facts["panel_meta"]
    sources = facts["sources"]
    digests = panel.get("digests") or {}
    panel_digest = (digests.get("panel_seconds") or {}).get("sha256")
    verdicts = {row["source_id"]: row for row in sources.get("source_verdicts") or []}
    forward = verdicts.get("SRC-19") or {}
    rows: list[dict[str, Any]] = []
    for key, stat in sorted((panel.get("stats") or {}).items()):
        run, market, symbol = key.split("|")
        rows.append(
            {
                "dataset_id": f"EDGE09-PANEL-{run}-{market}-{symbol}",
                "provider": "Binance public market data, captured by this repository's forward collector",
                "instrument": symbol,
                "venue": "Binance",
                "market_type": market,
                "data_type": "quotes (book_ticker) + trades (agg_trade) + depth snapshots + open interest",
                "resolution": f"{panel.get('grid_seconds')} s grid, {panel.get('depth_levels_kept')} depth levels kept",
                "first_event_time_utc": iso_from_ms(stat.get("first_second_ms")),
                "last_event_time_utc": iso_from_ms(stat.get("last_second_ms")),
                "first_available_at_utc": iso_from_ms(stat.get("first_second_ms")),
                "availability_semantics": (
                    "the panel takes the FIRST quote at or after each one-second boundary and "
                    "keeps its receive clock as the decision clock; event_time <= receive_time = "
                    "decision_time, and a horizon is served only by a row at or after it"
                ),
                "ingested_at_utc": mtime_utc(PANEL_CSV),
                "coverage": {
                    "seconds": stat.get("seconds"),
                    "quotes": stat.get("quotes"),
                    "trades": stat.get("trades"),
                    "trade_volume": stat.get("trade_volume"),
                    "oi_samples": stat.get("oi_samples"),
                    "depth_snapshots": stat.get("depth_snapshots"),
                    "files": stat.get("files"),
                },
                "gaps": {
                    "missing_seconds": stat.get("missing_seconds"),
                    "truncated_segments": stat.get("truncated_segments"),
                    "truncated_paths": stat.get("truncated_paths"),
                },
                "duplicates": None,
                "stale_rate": None,
                "provider_failure_rate": None,
                "license": "Binance public market data; research use only, no redistribution",
                "retrieval_cost": 0.0,
                "storage_cost": "local disk, counted in the estate audit",
                "source_version": (facts["source_digests"].get("docs/FORWARD_DATA_CONTRACT.json")),
                "sha256": panel_digest,
                "authority_class": "RUNTIME_REACHABLE (written by the paper-lab capture, read here)",
                "point_in_time": forward.get("pit"),
                "quality_verdict": forward.get("classification", "FORWARD_ONLY"),
                "quality_why": forward.get("why"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09A",
        "artifact": "DATA_CAPABILITY_REGISTRY",
        "as_of_utc": facts["as_of_utc"],
        "records": rows,
        "sources_declared": sources.get("source_verdicts"),
        "probes": sources.get("probes"),
        "unmeasured_fields": list(UNMEASURED),
        "rule": (
            "a record exists per stream of the folded capture; a field the package did not "
            "measure is null and named in unmeasured_fields, never filled with zero"
        ),
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
    }


def data_feasibility_matrix(facts: dict[str, Any]) -> dict[str, Any]:
    sources = facts["sources"]
    verdicts = {row["source_id"]: row for row in sources.get("source_verdicts") or []}
    panel = facts["panel_meta"]
    streams = sorted((panel.get("stats") or {}).keys())
    markets = sorted({key.split("|")[1] for key in streams})
    symbols = sorted({key.split("|")[2] for key in streams})

    def dataset_ids() -> list[str]:
        return [f"EDGE09-PANEL-{key}" for key in streams]

    families = [
        {
            "family": "spreads and liquidity (book imbalance)",
            "mechanism": "the book's own imbalance predicts the mid move by more than a round trip",
            "minimum_data": "forward quote/depth at the touch, point-in-time",
            "data_available": bool(verdicts.get("SRC-19")),
            "dataset_ids": dataset_ids(),
            "source_ids": ["SRC-19"],
            "status": "MEASURED_AND_REJECTED",
            "why": (
                "the capture exists and was measured; the best long-only gross is far below "
                "the barrier and the tape offers no clearing move at a 1 or 5 second horizon"
            ),
        },
        {
            "family": "regimes",
            "mechanism": "momentum or reversal only in a regime observable in real time",
            "minimum_data": "OHLCV point-in-time plus volatility and volume",
            "data_available": bool(verdicts.get("SRC-20")),
            "dataset_ids": [],
            "source_ids": ["SRC-20"],
            "status": "DEFERRED",
            "why": (
                "klines are available but a bar close is not a decision instant this runtime "
                "would trade on; the package does not open a new window for it, and no arm here "
                "survived the cost gate to justify one"
            ),
        },
        {
            "family": "cross-asset (lead/lag)",
            "mechanism": "BTC leads or lags ETH and the alts by more than the round trip",
            "minimum_data": "synchronised bars, one venue and one clock",
            "data_available": True,
            "dataset_ids": dataset_ids(),
            "source_ids": ["SRC-19", "SRC-20"],
            "status": "DEFERRED",
            "why": (
                "the captured clock is one venue, but three symbols over a few hours cannot "
                "separate a lead/lag effect from a shared move; the sample is declared too small"
            ),
        },
        {
            "family": "funding and open interest",
            "mechanism": "positioning imbalances are exploitable after their publication instant",
            "minimum_data": "funding and OI history with the real publication time",
            "data_available": bool(verdicts.get("SRC-21")) or bool(verdicts.get("SRC-22")),
            "dataset_ids": [],
            "source_ids": ["SRC-21", "SRC-22"],
            "status": "DEFERRED",
            "why": (
                "funding history is available and OI is retained for about 30 days; the forward "
                "capture held only 14 usable quadrant states, below the registered floor of 500, "
                "so the family is deferred rather than rejected on a sample too small to judge"
            ),
        },
        {
            "family": "events",
            "mechanism": "a post-event reaction is capturable",
            "minimum_data": "an event feed with publication timestamps",
            "data_available": bool(verdicts.get("SRC-23")),
            "dataset_ids": [],
            "source_ids": ["SRC-23"],
            "status": "REJECTED_NO_DATA",
            "why": (
                "no public liquidation or event feed answered in this environment (probe 404), "
                "and a retrospective timestamp cannot be used as a publication instant"
            ),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09B",
        "artifact": "DATA_FEASIBILITY_MATRIX",
        "as_of_utc": facts["as_of_utc"],
        "universe": {"markets": markets, "symbols": symbols, "streams": len(streams)},
        "families": families,
        "probes": sources.get("probes"),
        "capture": {
            "roots": (sources.get("captured") or {}).get("roots"),
            "total_hours": (sources.get("captured") or {}).get("total_hours"),
            "longest_seconds": (sources.get("captured") or {}).get("longest_seconds"),
            "continuity_note": (sources.get("captured") or {}).get("continuity_note"),
        },
        "rule": (
            "PROJECT != PATTERN != IMPLEMENTATION: a family is FEASIBLE only when the data its "
            "minimum specification names exists here, with the availability semantics it needs"
        ),
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
    }


# --------------------------------------------------------------------- 09C


def hypothesis_registry(facts: dict[str, Any]) -> dict[str, Any]:
    prereg = facts["prereg"]
    registry = {row["id"]: row for row in facts["registry"]}
    rows: list[dict[str, Any]] = []
    for hypothesis in HYPOTHESES:
        outcome = registry.get(hypothesis.id) or {}
        registered_at = prereg.get("as_of_utc") or prereg.get("registered_at_utc")
        rows.append(
            {
                "hypothesis_id": hypothesis.id,
                "version": SCHEMA_VERSION,
                "track": hypothesis.track,
                "title": hypothesis.title,
                "mechanism": hypothesis.statement,
                "counter_hypothesis": hypothesis.falsified_if,
                "required_data": hypothesis.data_requirement,
                "executable_under_runtime": hypothesis.executable,
                "status": outcome.get("classification", "PROPOSED"),
                "failed_filter": outcome.get("failed_filter"),
                "evidence": "reports/edge-recovery/WP-EDGE-09/experiments/EXPERIMENT_REGISTRY.json",
                "multiple_testing_family": prereg.get("multiple_testing_family", "EDGE09"),
                "lifecycle": [
                    {
                        "state": "PROPOSED",
                        "at_utc": registered_at,
                        "evidence": "PREREGISTRATION.json",
                    },
                    {
                        "state": "DATA_CHECKED",
                        "at_utc": facts["audit_time"],
                        "evidence": "audit/ESTATE.json",
                    },
                    {
                        "state": "FEASIBLE",
                        "at_utc": facts["sources_time"],
                        "evidence": "sources/SOURCE_VIABILITY.json",
                    },
                    {
                        "state": "DEV_TESTED",
                        "at_utc": facts["experiments_time"],
                        "evidence": "experiments/EXPERIMENTS.json",
                    },
                ],
                "terminal_state": outcome.get("classification", "PROPOSED"),
                "promotion": "NONE",
                "note": hypothesis.note,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09C",
        "artifact": "HYPOTHESIS_REGISTRY",
        "as_of_utc": facts["as_of_utc"],
        "registered_before_reading": prereg.get("registered_before_reading"),
        "registered_at_utc": prereg.get("as_of_utc"),
        "hypotheses": rows,
        "negative_control_rule": prereg.get("negative_control_rule"),
        "declared_limitations": prereg.get("declared_limitations"),
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
    }


def render_experiment_plan(facts: dict[str, Any]) -> str:
    prereg = facts["prereg"]
    thresholds = prereg.get("thresholds") or {}
    lines = [
        "# WP-EDGE-09C — experiment plan (frozen before any measurement)",
        "",
        f"*Registered at `{prereg.get('as_of_utc')}`, before the panel was read. "
        "This document renders the registration; the registration is the contract.*",
        "",
        "## 1. Grid, horizons and tracks",
        "",
        f"- Grid: {prereg.get('grid_seconds')} s. Decision horizons: "
        f"{', '.join(str(value) for value in prereg.get('horizons_seconds') or [])} s.",
        f"- Frequency horizons: "
        f"{', '.join(str(value) for value in prereg.get('frequency_horizons_seconds') or [])} s.",
        f"- Universe: {', '.join(prereg.get('universe') or [])} over "
        f"{', '.join(prereg.get('markets') or [])}.",
        f"- ACTIVE keeps the objective of **{ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY} executed "
        "trades a day** across the aggregate universe; no trade is forced to reach it.",
        f"- QUALITY is judged separately, floor "
        f"{thresholds.get('quality_frequency_floor_trades_per_day')} trades/day.",
        "",
        "## 2. Thresholds",
        "",
        "| Threshold | Value |",
        "| --- | ---: |",
    ]
    for key, value in thresholds.items():
        lines.append(f"| `{key}` | {value} |")
    lines += [
        "",
        "## 3. Filter ladder, applied in this order",
        "",
        "| # | Filter | Rule |",
        "| --- | --- | --- |",
    ]
    for row in LADDER:
        lines.append(f"| {row['id']} | {row['name']} | {row['rule']} |")
    lines += [
        "",
        "## 4. Cost scenarios compared (all authoritative V3 specs)",
        "",
        "| Scenario |",
        "| --- |",
    ]
    for scenario in SCENARIOS_COMPARED:
        lines.append(f"| `{scenario}` |")
    lines += [
        "",
        "## 5. Windows this plan may read",
        "",
        "- **DEV**: the forward capture this repository already holds, declared in the window "
        "ledger; it is *not* a fresh holdout.",
        "- **VAL**: only for a hypothesis that survives F3; the cost gate stopped every arm, so "
        "VAL was never opened.",
        "- **FRESH_OOS / FORWARD**: never read by this package; the 60-day forward count never "
        "started.",
        "- Holdouts consumed by WP-EDGE-07 and WP-EDGE-08 stay blocked and are listed in "
        "`WINDOW_LEDGER.jsonl` with `read_by_this_package: false`.",
        "",
        "## 6. Stop rules",
        "",
    ]
    for row in HYPOTHESES:
        lines.append(f"- `{row.id}` — {row.title}: **stops if** {row.falsified_if}")
    lines += [
        "",
        "## 7. Decision vocabulary",
        "",
        f"{', '.join(f'`{value}`' for value in prereg.get('classifications') or [])}.",
        "",
        "## 8. Negative control",
        "",
        f"{prereg.get('negative_control_rule')}",
        "",
    ]
    return "\n".join(lines)


def window_ledger(facts: dict[str, Any]) -> list[dict[str, Any]]:
    panel = facts["panel_meta"]
    sources = facts["sources"]
    prereg = facts["prereg"]
    read_at = mtime_utc(PANEL_CSV)
    rows: list[dict[str, Any]] = []
    for key, stat in sorted((panel.get("stats") or {}).items()):
        run, market, symbol = key.split("|")
        rows.append(
            {
                "window_id": f"EDGE09-FORWARD-{run}",
                "window_role": "CONSULTED",
                "instrument": symbol,
                "market": market,
                "run": run,
                "first_read_utc": read_at,
                "first_second_utc": iso_from_ms(stat.get("first_second_ms")),
                "last_second_utc": iso_from_ms(stat.get("last_second_ms")),
                "span_seconds": stat.get("seconds"),
                "missing_seconds": stat.get("missing_seconds"),
                "fresh_holdout": False,
                "why": (
                    "the repository's own forward capture: readable, and it can never be "
                    "presented as a fresh holdout because it was read here"
                ),
                "dataset_id": f"EDGE09-PANEL-{key}",
            }
        )
    rows.append(
        {
            "window_id": "EDGE09-VAL",
            "window_role": "VAL",
            "first_read_utc": None,
            "status": "NOT_READ",
            "why": (
                "the cost gate (F2/F3) stopped every arm before validation was opened, so no "
                "validation window was consumed"
            ),
        }
    )
    rows.append(
        {
            "window_id": "EDGE09-FRESH_OOS",
            "window_role": "FRESH_OOS",
            "first_read_utc": None,
            "status": "NOT_READ",
            "why": "no arm survived to need unseen data; nothing was reserved and then read",
        }
    )
    rows.append(
        {
            "window_id": "EDGE09-FORWARD-60D",
            "window_role": "FORWARD",
            "first_read_utc": None,
            "status": "NOT_STARTED",
            "eligible_days": 0,
            "why": (
                "the 60-day forward count starts only from prospective observation that is "
                "eligible; this package attributes no backfill to it"
            ),
        }
    )
    for entry in prereg.get("consumed_holdouts") or []:
        rows.append(
            {
                "window_id": f"CONSUMED-{entry.get('holder')}",
                "window_role": "CONSULTED_OOS",
                "first_read_utc": None,
                "status": "BLOCKED",
                "holder": entry.get("holder"),
                "what": entry.get("what"),
                "symbols": entry.get("symbols"),
                "evidence": entry.get("evidence"),
                "read_by_this_package": False,
                "why": (
                    "a window another package already spent stays spent; this package neither "
                    "reads it nor re-labels it fresh"
                ),
            }
        )
    rows.append(
        {
            "window_id": "EDGE09-CAPTURE-ROOT",
            "window_role": "CONSULTED",
            "first_read_utc": read_at,
            "captured_hours": (sources.get("captured") or {}).get("total_hours"),
            "runs_enumerated": len(facts["audit"].get("captures") or []),
            "why": "every capture on disk is enumerated in the estate audit; two are folded in",
        }
    )
    return rows


# --------------------------------------------------------------------- 09D


def economic_feasibility_report(facts: dict[str, Any]) -> dict[str, Any]:
    gates = facts["gates"]
    experiments = facts["experiments"]
    barriers = gates.get("barriers") or []
    admission = gates.get("admission_barrier_bps") or {}
    cells = [
        cell
        for cell in (experiments.get("experiments") or {}).get("E-01_imbalance") or []
        if cell.get("stats")
    ]
    best = max(cells, key=lambda cell: cell["stats"]["long_only_mean_bps"], default=None)
    best_gross = best["stats"]["long_only_mean_bps"] if best else None
    venue = experiments.get("venue_comparison") or {}
    cheapest = min(
        venue.get("scenarios") or [],
        key=lambda row: row["cheapest_round_trip_bps"],
        default=None,
    )
    rows = []
    for key, cost in sorted(admission.items()):
        market, symbol = key.split("|")
        rows.append(
            {
                "market": market,
                "symbol": symbol,
                "admission_round_trip_bps": cost,
                "break_even_bps": cost,
                "required_1_5x_bps": round(cost * 1.5, 4),
                "best_measured_long_only_gross_bps": best_gross,
                "net_at_best_gross_bps": None
                if best_gross is None
                else round(best_gross - cost, 4),
                "gap_to_break_even_bps": None
                if best_gross is None
                else round(cost - best_gross, 4),
                "survives": None if best_gross is None else bool(best_gross >= cost),
            }
        )
    fees = [row["components_bps"]["fee"] for row in barriers if "components_bps" in row]
    mean_fee = sum(fees) / len(fees) if fees else None
    mean_barrier = sum(admission.values()) / len(admission) if admission else None
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09D",
        "artifact": "ECONOMIC_FEASIBILITY_REPORT",
        "as_of_utc": facts["as_of_utc"],
        "decision": "NO_ECONOMIC_EDGE_FOUND",
        "decision_scope": (
            "no measured structure in this capture covers the round trip; the decision is about "
            "this capture and this venue set, not about microstructure in general"
        ),
        "per_asset": rows,
        "fee_share_of_barrier": None
        if mean_fee is None or not mean_barrier
        else round(mean_fee / mean_barrier, 4),
        "mean_fee_bps": None if mean_fee is None else round(mean_fee, 4),
        "mean_barrier_bps": None if mean_barrier is None else round(mean_barrier, 4),
        "best_measured_long_only_gross_bps": best_gross,
        "best_measured_cell": None
        if best is None
        else {
            "run": best["run"],
            "market": best["market"],
            "symbol": best["symbol"],
            "horizon_seconds": best["horizon_seconds"],
            "ic": best["ic"],
            "n": best["n"],
            "classification": best["verdict"]["classification"],
        },
        "cheapest_registered_venue": None
        if cheapest is None
        else {
            "scenario": cheapest["scenario"],
            "venue": cheapest["venue"],
            "cheapest_round_trip_bps": cheapest["cheapest_round_trip_bps"],
            "still_above_best_gross": cheapest["cheapest_round_trip_bps"] > (best_gross or 0.0),
        },
        "frequency_bound": gates.get("frequency_pooled"),
        "frequency_measured": experiments.get("frequency_pooled"),
        "capacity_note": experiments.get("capacity", {}).get("note"),
        "what_would_change_the_answer": [
            "a taker fee low enough that fee + spread + impact falls under the measured gross, "
            "or a measured maker fill model that turns a passive product into a costed one",
            "a product with a different cost structure (the runtime's spot book is long-only)",
            "a structure whose gross move is measured at or above 34-36 bps (1.5x of 23-24 bps) "
            "rather than the 1.6 bps best measured here",
        ],
        "what_is_not_measured": [
            *UNMEASURED,
            "perp aggressor flow (the environment delivered zero perp aggTrade messages)",
            "maker fills on every venue (no measured fill model exists in this project)",
            "liquidation prints (no public endpoint answered)",
        ],
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
        "promotion": "NONE",
        "order_sent": False,
    }


def cost_capacity_frequency_matrix(facts: dict[str, Any]) -> dict[str, Any]:
    gates = facts["gates"]
    experiments = facts["experiments"]
    spreads = {
        (row["run"], row["market"], row["symbol"]): row
        for row in gates.get("spread_by_stream") or []
    }
    admission = gates.get("admission_barrier_bps") or {}
    capacity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in gates.get("capacity") or []:
        capacity.setdefault((row["market"], row["symbol"]), []).append(row)
    frequency = {
        (row["run"], row["market"], row["symbol"]): row
        for row in (gates.get("frequency") or [])
        if row["horizon_seconds"] in (1, 5, 60)
    }
    measured = {
        (cell["run"], cell["market"], cell["symbol"], cell["horizon_seconds"]): cell
        for cell in (experiments.get("experiments") or {}).get("E-05_frequency") or []
    }
    rows: list[dict[str, Any]] = []
    for key, spread in sorted(spreads.items()):
        run, market, symbol = key
        cost = admission.get(f"{market}|{symbol}")
        snapshots = capacity.get((market, symbol)) or []
        notionals = sorted(row["bid_notional_within_5.0bps_usd"] for row in snapshots)
        median_notional = (
            None
            if not notionals
            else (
                notionals[len(notionals) // 2]
                if len(notionals) % 2
                else (notionals[len(notionals) // 2 - 1] + notionals[len(notionals) // 2]) / 2.0
            )
        )
        entry: dict[str, Any] = {
            "run": run,
            "market": market,
            "symbol": symbol,
            "measured_spread_median_bps": spread.get("median_bps"),
            "measured_spread_observations": spread.get("observations"),
            "admission_round_trip_bps": cost,
            "required_1_5x_bps": None if cost is None else round(cost * 1.5, 4),
            "capacity_snapshots": len(snapshots),
            "capacity_median_bid_notional_within_5bps_usd": None
            if median_notional is None
            else round(median_notional, 4),
            "absorbs_1000_usd": None if median_notional is None else median_notional >= 1000.0,
        }
        for horizon in (1, 5, 60):
            row = frequency.get((run, market, symbol, horizon))
            cell = measured.get((run, market, symbol, horizon))
            entry[f"tape_clearing_per_day_h{horizon}s"] = (row or {}).get("clearing_per_day")
            entry[f"selector_opportunities_per_day_h{horizon}s"] = (cell or {}).get(
                "opportunities_per_day"
            )
            entry[f"measured_windows_h{horizon}s"] = (row or {}).get("measured_windows")
        rows.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09D",
        "artifact": "COST_CAPACITY_FREQUENCY_MATRIX",
        "as_of_utc": facts["as_of_utc"],
        "rows": rows,
        "pooled_frequency": {
            "tape_upper_bound": gates.get("frequency_pooled"),
            "selector_measured": experiments.get("frequency_pooled"),
        },
        "active_target_trades_per_day": ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
        "grid_seconds": gates.get("grid_seconds"),
        "quote_size_usd": gates.get("quote_size_usd"),
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
    }


# --------------------------------------------------------------------- 09E


def experiment_ledger(facts: dict[str, Any]) -> list[dict[str, Any]]:
    experiments = facts["experiments"]
    registry = {row["id"]: row for row in facts["registry"]}
    prereg = facts["prereg"]
    gates = facts["gates"]
    admission = gates.get("admission_barrier_bps") or {}
    config_digest = sha256_file(PREREG_JSON)
    panel_digest = (facts["panel_meta"].get("digests") or {}).get("panel_seconds", {}).get("sha256")
    read_at = mtime_utc(PANEL_CSV)
    contracts = {
        "config_digest": config_digest,
        "window_role": "CONSULTED",
        "first_read_utc": read_at,
        "execution_target": "research only: no order path is reachable from this package",
        "risk_contract": {
            "file": "config/risk.yaml",
            "sha256": facts["source_digests"].get("config/risk.yaml"),
            "modified_by_this_package": False,
        },
        "cost_contract": {
            "model": "EXECUTION_COST_MODEL_V4 (admission scenario)",
            "scenario": SCENARIOS_COMPARED[0],
            "venv_specs": "COST_MODEL_V3 venue specs",
        },
        "verifier_id": "scripts/edge09_verify.py",
        "promotion": "NONE",
        "pnl_usd": None,
        "pnl_unavailable_reason": (
            "no PnL backtest exists for these arms: the F2/F3 cost filters stopped them before a "
            "simulator was invoked, which is the gate the RFC asks for before simulation"
        ),
    }
    rows: list[dict[str, Any]] = []
    for hypothesis in HYPOTHESES:
        outcome = registry.get(hypothesis.id) or {}
        rows.append(
            {
                "experiment_id": f"EDGE09-{hypothesis.id}-SUMMARY",
                "hypothesis_id": hypothesis.id,
                "level": "hypothesis",
                "dataset_fingerprints": [
                    {
                        "path": "reports/edge-recovery/WP-EDGE-09/panel/PANEL_SECONDS.csv",
                        "sha256": panel_digest,
                    }
                ],
                "classification": outcome.get("classification"),
                "failed_filter": outcome.get("failed_filter"),
                "failure_reason": outcome.get("reason"),
                "n": None,
                **contracts,
            }
        )
    cell_map = {
        "E-01": "E-01_imbalance",
        "E-05": "E-05_frequency",
        "E-07": "E-07_negative_control",
    }
    for hypothesis_id, bucket in cell_map.items():
        for cell in (experiments.get("experiments") or {}).get(bucket) or []:
            key = f"{cell['market']}|{cell['symbol']}"
            cost = admission.get(key)
            gross = (cell.get("stats") or {}).get("long_only_mean_bps")
            rows.append(
                {
                    "experiment_id": (
                        f"EDGE09-{hypothesis_id}-{cell['run']}-{cell['market']}-{cell['symbol']}"
                        f"-h{cell['horizon_seconds']}"
                    ),
                    "hypothesis_id": hypothesis_id,
                    "level": "cell",
                    "run": cell["run"],
                    "market": cell["market"],
                    "symbol": cell["symbol"],
                    "horizon_seconds": cell["horizon_seconds"],
                    "window_id": f"EDGE09-FORWARD-{cell['run']}",
                    "dataset_fingerprints": [
                        {
                            "path": "reports/edge-recovery/WP-EDGE-09/panel/PANEL_SECONDS.csv",
                            "sha256": panel_digest,
                        }
                    ],
                    "trade_count": cell.get("n") or cell.get("selected"),
                    "ic": cell.get("ic"),
                    "gross_bps": gross if gross is not None else cell.get("opportunities_per_day"),
                    "cost_bps": cost,
                    "net_bps": None if gross is None or cost is None else round(gross - cost, 6),
                    "fees_bps": None
                    if cost is None
                    else next(
                        (
                            row["components_bps"]["fee"]
                            for row in gates.get("barriers") or []
                            if row.get("market") == cell["market"]
                            and row.get("symbol") == cell["symbol"]
                            and row.get("scenario") == SCENARIOS_COMPARED[0]
                        ),
                        None,
                    ),
                    "pit": cell.get("pit"),
                    "classification": (cell.get("verdict") or {}).get("classification"),
                    "failure_reason": (cell.get("verdict") or {}).get("reason"),
                    **contracts,
                }
            )
    rows.append(
        {
            "experiment_id": "EDGE09-MULTIPLICITY",
            "hypothesis_id": None,
            "level": "family",
            "attempts_registered": len(HYPOTHESES),
            "attempts_run": len(HYPOTHESES),
            "attempts_rejected": sum(
                1
                for row in registry.values()
                if row.get("classification") not in (None, "ADMIT_RESEARCH", "OBSERVED")
            ),
            "multiple_testing_family": prereg.get("multiple_testing_family", "EDGE09"),
            "ladder": [row["id"] for row in LADDER],
            "note": (
                "every registered hypothesis is in this ledger, including the negative control "
                "and the ones that failed; nothing was re-parameterised and re-run"
            ),
            **contracts,
        }
    )
    return rows


def results_matrix(facts: dict[str, Any]) -> dict[str, Any]:
    experiments = facts["experiments"]
    registry = {row["id"]: row for row in facts["registry"]}
    rows = []
    for hypothesis in HYPOTHESES:
        outcome = registry.get(hypothesis.id) or {}
        rows.append(
            {
                "hypothesis_id": hypothesis.id,
                "track": hypothesis.track,
                "registered_criterion": hypothesis.falsified_if,
                "measured": outcome.get("reason"),
                "classification": outcome.get("classification"),
                "failed_filter": outcome.get("failed_filter"),
                "evidence": "reports/edge-recovery/WP-EDGE-09/experiments/EXPERIMENTS.json",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09E",
        "artifact": "RESULTS_MATRIX",
        "as_of_utc": facts["as_of_utc"],
        "rows": rows,
        "comparison_current_vs_proposed": {
            "status": "NOT_PRODUCIBLE",
            "why": (
                "no arm reached simulation: the registered F2/F3 cost filters rejected every "
                "hypothesis before a backtest, so there is no PROPOSED trade list and therefore "
                "no paired CURRENT/PROPOSED PnL to publish. Producing one would require inventing "
                "trades the gate forbade."
            ),
            "what_is_comparable_today": (
                "the measured cost barrier against the measured best gross and against the tape's "
                "own frequency bound, all on the same panel and the same cost model"
            ),
        },
        "best_measured_long_only_gross_bps": max(
            (
                cell["stats"]["long_only_mean_bps"]
                for cell in (experiments.get("experiments") or {}).get("E-01_imbalance") or []
                if cell.get("stats")
            ),
            default=None,
        ),
        "negative_control": {
            "classifications": sorted(
                set(experiments.get("negative_control_classification") or [])
            ),
            "false_success": experiments.get("false_success"),
        },
        "false_success": experiments.get("false_success"),
        "promotion": "NONE",
        "order_sent": False,
        "derived_from": facts["derived_from"],
        "derived_no_new_measurement": True,
    }


# ------------------------------------------------------------------ rendering


def render_capability(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09A/B — data capability registry",
        "",
        f"*`{payload['as_of_utc']}`. Derived from the audit and the source viability artifact; "
        "nothing here is re-measured. A field the package did not measure is null.*",
        "",
        "| Dataset | Venue | Market | Resolution | First second (UTC) | Last second (UTC) | "
        "Quotes | Trades | Gaps (s) | Truncated | PIT | Verdict |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in payload["records"]:
        coverage = row["coverage"]
        gaps = row["gaps"]
        lines.append(
            f"| `{row['dataset_id']}` | {row['venue']} | {row['market_type']} | "
            f"{row['resolution']} | {row['first_event_time_utc']} | {row['last_event_time_utc']} | "
            f"{coverage['quotes']} | {coverage['trades']} | {gaps['missing_seconds']} | "
            f"{gaps['truncated_segments']} | {row['point_in_time']} | **{row['quality_verdict']}** |"
        )
    lines += [
        "",
        "## Declared as not measured",
        "",
    ]
    for item in payload["unmeasured_fields"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def render_feasibility(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09B — data feasibility matrix",
        "",
        f"*`{payload['as_of_utc']}`. A family is feasible only if the data its minimum "
        "specification names exists here with the availability semantics it needs.*",
        "",
        "| Family | Minimum data | Available | Status | Why |",
        "| --- | --- | :-: | --- | --- |",
    ]
    for row in payload["families"]:
        lines.append(
            f"| {row['family']} | {row['minimum_data']} | {row['data_available']} | "
            f"**{row['status']}** | {row['why']} |"
        )
    capture = payload["capture"]
    lines += [
        "",
        f"Capture held: {capture['roots']} roots, {capture['total_hours']} h total, longest "
        f"{capture['longest_seconds']} s.",
        "",
        "## Probes",
        "",
        "| Probe | URL | Status | Reachable |",
        "| --- | --- | ---: | :-: |",
    ]
    for row in payload["probes"] or []:
        lines.append(
            f"| {row['id']} | `{row.get('url', '')}` | {row.get('status')} | {row.get('reachable')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_economic(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09D — economic feasibility report",
        "",
        f"*`{payload['as_of_utc']}`. Decision: **{payload['decision']}**.",
        "",
        f"{payload['decision_scope']}",
        "",
        "## 1. The barrier against the best measured gross",
        "",
        "| Market | Symbol | Round trip (bps) | Required 1.5x (bps) | Best gross (bps) | "
        "Net at best gross (bps) | Gap to break-even (bps) | Survives |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | :-: |",
    ]
    for row in payload["per_asset"]:
        lines.append(
            f"| {row['market']} | {row['symbol']} | {row['admission_round_trip_bps']} | "
            f"{row['required_1_5x_bps']} | {row['best_measured_long_only_gross_bps']} | "
            f"{row['net_at_best_gross_bps']} | {row['gap_to_break_even_bps']} | "
            f"{row['survives']} |"
        )
    lines += [
        "",
        f"Mean fee component {payload['mean_fee_bps']} bps of a mean barrier "
        f"{payload['mean_barrier_bps']} bps "
        f"({payload['fee_share_of_barrier']} of the round trip).",
        "",
        "## 2. Frequency",
        "",
        "| Source | Horizon (s) | Long-only opp/day | Any direction opp/day | Meets target |",
        "| --- | ---: | ---: | ---: | :-: |",
    ]
    for row in payload["frequency_measured"] or []:
        lines.append(
            f"| selector | {row['horizon_seconds']} | {row.get('opportunities_per_day')} | "
            f"{row.get('opportunities_per_day_any_direction')} | {row.get('meets_target')} |"
        )
    for row in payload["frequency_bound"] or []:
        lines.append(
            f"| tape bound | {row['horizon_seconds']} | {row.get('clearing_per_day')} | — | "
            f"{row.get('meets_target')} |"
        )
    lines += [
        "",
        "## 3. What would change the answer",
        "",
    ]
    for item in payload["what_would_change_the_answer"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 4. What is not measured",
        "",
    ]
    for item in payload["what_is_not_measured"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def render_matrix(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09D — cost, capacity and frequency, per stream",
        "",
        f"*`{payload['as_of_utc']}`. Quote size {payload['quote_size_usd']} USD, grid "
        f"{payload['grid_seconds']} s, ACTIVE target {payload['active_target_trades_per_day']}/day.*",
        "",
        "| Run | Market | Symbol | Spread (bps) | Round trip (bps) | Capacity median (USD, 5 bps) | "
        "Absorbs 1,000 USD | Tape clearing/day: 1 s / 5 s / 60 s | Selector opp/day: 1 s / 5 s / 60 s |",
        "| --- | --- | --- | ---: | ---: | ---: | :-: | --- | --- |",
    ]
    for row in payload["rows"]:
        tape = " / ".join(
            str(row.get(f"tape_clearing_per_day_h{horizon}s")) for horizon in (1, 5, 60)
        )
        selector = " / ".join(
            str(row.get(f"selector_opportunities_per_day_h{horizon}s")) for horizon in (1, 5, 60)
        )
        lines.append(
            f"| `{row['run']}` | {row['market']} | {row['symbol']} | "
            f"{row['measured_spread_median_bps']} | {row['admission_round_trip_bps']} | "
            f"{row['capacity_median_bid_notional_within_5bps_usd']} | {row['absorbs_1000_usd']} | "
            f"{tape} | {selector} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_results(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09E — results matrix",
        "",
        f"*`{payload['as_of_utc']}`. Every registered hypothesis appears here, rejected ones included.*",
        "",
        "| Hypothesis | Track | Registered criterion | Measured | Classification |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        criterion = row["registered_criterion"].replace("|", "\\|")
        measured = str(row["measured"]).replace("|", "\\|")
        lines.append(
            f"| `{row['hypothesis_id']}` | {row['track']} | {criterion} | {measured} | "
            f"**{row['classification']}** |"
        )
    comparison = payload["comparison_current_vs_proposed"]
    lines += [
        "",
        "## CURRENT vs PROPOSED",
        "",
        f"Status: **{comparison['status']}** — {comparison['why']}",
        "",
        f"{comparison['what_is_comparable_today']}",
        "",
        f"Negative control: {payload['negative_control']['classifications']}, "
        f"`false_success = {payload['negative_control']['false_success']}`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    if not GATES_JSON.is_file() or not EXP_JSON.is_file():
        print("the gate and experiment payloads must exist before the deliverables")
        return 2
    facts: dict[str, Any] = {
        "as_of_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audit": read_json(AUDIT_JSON),
        "sources": read_json(SOURCES_JSON),
        "prereg": read_json(PREREG_JSON),
        "panel_meta": read_json(PANEL_JSON),
        "gates": read_json(GATES_JSON),
        "experiments": read_json(EXP_JSON),
        "registry": read_json(REGISTRY_JSON).get("registry") or [],
        "verification": read_json(VERIFY_JSON),
        "audit_time": mtime_utc(AUDIT_JSON),
        "sources_time": mtime_utc(SOURCES_JSON),
        "experiments_time": mtime_utc(EXP_JSON),
    }
    facts["source_digests"] = source_digests(
        (
            REPO_ROOT / "config" / "risk.yaml",
            REPO_ROOT / "config" / "runtime.yaml",
            REPO_ROOT / "docs" / "COST_MODEL_V3.json",
            REPO_ROOT / "docs" / "EXECUTION_COST_MODEL_V4.json",
            REPO_ROOT / "docs" / "FORWARD_DATA_CONTRACT.json",
            REPO_ROOT / "docs" / "source_registry.md",
            PANEL_CSV,
            GATES_JSON,
            EXP_JSON,
            REGISTRY_JSON,
            PREREG_JSON,
            PREREG_JSON.with_suffix(".md"),
        )
    )
    facts["derived_from"] = facts["source_digests"]

    artifacts: dict[str, Any] = {
        "BASELINE.json": baseline(facts),
        "DATA_CAPABILITY_REGISTRY.json": data_capability_registry(facts),
        "DATA_FEASIBILITY_MATRIX.json": data_feasibility_matrix(facts),
        "HYPOTHESIS_REGISTRY.json": hypothesis_registry(facts),
        "ECONOMIC_FEASIBILITY_REPORT.json": economic_feasibility_report(facts),
        "COST_CAPACITY_FREQUENCY_MATRIX.json": cost_capacity_frequency_matrix(facts),
        "RESULTS_MATRIX.json": results_matrix(facts),
    }
    for name, payload in artifacts.items():
        write_json(WP / name, payload)
    write_jsonl(WP / "WINDOW_LEDGER.jsonl", window_ledger(facts))
    write_jsonl(WP / "EXPERIMENT_LEDGER.jsonl", experiment_ledger(facts))
    (WP / "EXPERIMENT_PLAN.md").write_text(render_experiment_plan(facts), encoding="utf-8")
    (WP / "DATA_CAPABILITY_REGISTRY.md").write_text(
        render_capability(artifacts["DATA_CAPABILITY_REGISTRY.json"]), encoding="utf-8"
    )
    (WP / "DATA_FEASIBILITY_MATRIX.md").write_text(
        render_feasibility(artifacts["DATA_FEASIBILITY_MATRIX.json"]), encoding="utf-8"
    )
    (WP / "ECONOMIC_FEASIBILITY_REPORT.md").write_text(
        render_economic(artifacts["ECONOMIC_FEASIBILITY_REPORT.json"]), encoding="utf-8"
    )
    (WP / "COST_CAPACITY_FREQUENCY_MATRIX.md").write_text(
        render_matrix(artifacts["COST_CAPACITY_FREQUENCY_MATRIX.json"]), encoding="utf-8"
    )
    (WP / "RESULTS_MATRIX.md").write_text(
        render_results(artifacts["RESULTS_MATRIX.json"]), encoding="utf-8"
    )
    written = [
        *artifacts,
        "DATA_CAPABILITY_REGISTRY.md",
        "DATA_FEASIBILITY_MATRIX.md",
        "ECONOMIC_FEASIBILITY_REPORT.md",
        "COST_CAPACITY_FREQUENCY_MATRIX.md",
        "RESULTS_MATRIX.md",
        "EXPERIMENT_PLAN.md",
        "WINDOW_LEDGER.jsonl",
        "EXPERIMENT_LEDGER.jsonl",
    ]
    write_json(
        FOLLOW_UP_JSON,
        {
            "schema_version": SCHEMA_VERSION,
            "work_package": "WP-EDGE-09",
            "as_of_utc": facts["as_of_utc"],
            "artifacts": sorted(written),
            "digests": {name: sha256_file(WP / name) for name in sorted(written)},
            "derived_from": facts["derived_from"],
            "derived_no_new_measurement": True,
        },
    )
    print(f"deliverables written under {WP.relative_to(REPO_ROOT)}")
    print(f"  window ledger rows: {len(window_ledger(facts))}")
    print(f"  experiment ledger rows: {len(experiment_ledger(facts))}")
    print(f"  capability records: {len(artifacts['DATA_CAPABILITY_REGISTRY.json']['records'])}")
    print(f"  matrix rows: {len(artifacts['COST_CAPACITY_FREQUENCY_MATRIX.json']['rows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
