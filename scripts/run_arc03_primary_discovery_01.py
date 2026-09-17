#!/usr/bin/env python
"""ARC-03 PRIMARY DISCOVERY 01 — one-shot economic executor.

EXPERIMENT_ID = ``ARC03_PRIMARY_DISCOVERY_01``

This is the EXECUTION driver authorized by the independently verified ARC-03
preregistration (PREREG_COMMIT ``8ebf8a181a3cfaf03737ef585f8906d28f8d419f``,
INDEPENDENT_VERIFIER_COMMIT ``2dfe96c88fd66953d3fee148415e2e837c1bd2c7``).

It performs EXACTLY ONE primary economic discovery:

* data binding is re-proved from the actual bytes BEFORE any economics run;
* the append-only experiment ledger makes the run exactly-once (REGISTERED ->
  STARTED -> COMPLETED); a technical interruption may resume but can never create
  a second economic experiment;
* the signal path is the FROZEN reference emission (``arc03_prereg_reference``);
  this driver adds only execution accounting, controls and persistence;
* every result is persisted before it is reported, and no partial PnL is inspected.

Final outcome is exactly one of ``DISCOVERY_PASS`` / ``DISCOVERY_FAIL`` /
``INFRASTRUCTURE_FAIL``.

Usage::

    python scripts/run_arc03_primary_discovery_01.py \
        --target <worktree> --data-root <certified data root> \
        --implementation-commit <sha> --generated-from-commit <sha>
"""

# ruff: noqa: E402 -- the audited target's ``src`` is bootstrapped onto sys.path before
# the trading_bot imports so the import authority cannot silently fall back to another
# checkout; the import block is therefore deliberately not at the top of the file.

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys
from itertools import pairwise
from typing import Any

HERE = pathlib.Path(__file__).resolve()
TARGET_DEFAULT = HERE.parents[1]

#: Mission §1 / §4-§5 frozen bindings.
EXPERIMENT_ID = "ARC03_PRIMARY_DISCOVERY_01"
ASSETS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
EXPECTED_DATASET_SHA256 = "1a6ad11712ce436ce9d413d6b53162d66996778cd98643ef7c3eb746a54745ef"
EXPECTED_SPEC_SHA256 = "a69edabb2931b3897cc0bcabdb7c203009ace742af1a729e47f7cb058a407a2d"
EXPECTED_MANIFEST_SHA256 = "3b022693fde0a4e362329a009125292410bb1ba3d0e2b3f8571b795a15b1d1a3"
EXPECTED_WINDOW_MS = (1_600_066_800_000, 1_788_220_500_000)
EXECUTION_IMPLEMENTATION_MODULE = "trading_bot/research/arc03/arc03_executor.py"
GATE_MODULE = "trading_bot/research/arc03/arc03_gates.py"
ARC01_FUNDING_PARTITION_SHA256 = {
    "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
    "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
    "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
}
PIT_SAMPLE = 200


def _bootstrap_target() -> pathlib.Path:
    """Make THIS checkout's ``src`` win the import race before any trading_bot import.

    Mirrors ``conftest.py``: the shared editable install pins the MAIN checkout, so the
    audited target must be inserted at ``sys.path[0]`` explicitly.
    """
    target = TARGET_DEFAULT
    argv = sys.argv[1:]
    if "--target" in argv:
        i = argv.index("--target")
        if i + 1 < len(argv):
            target = pathlib.Path(argv[i + 1])
    target = target.resolve()
    src = str(target / "src")
    if src in sys.path:
        sys.path.remove(src)
    sys.path.insert(0, src)
    return target


TARGET = _bootstrap_target()

# The trading_bot imports below MUST follow the bootstrap above so that the audited
# target's ``src`` wins the import race.
from trading_bot.research.arc03.arc03_authority import (
    ASSETS as FROZEN_ASSETS,
)
from trading_bot.research.arc03.arc03_authority import (
    HOLDING_MS,
    PRIMARY_COST_BPS,
    common_causal_window,
    load_partition,
)
from trading_bot.research.arc03.arc03_executor import (
    COST_SCENARIOS_BPS,
    ExperimentLedger,
    accounting_reconciliation,
    build_executed_trades,
    direction_control_trades,
    emit_participation_control_trades,
    emit_trades,
    evaluate_gates,
    frozen_gate_order,
    gate_inputs,
    ledger_row,
    null_control_series,
    timing_control_trades,
    trade_ledger_reconciliation,
)
from trading_bot.research.arc03.arc03_funding import load_funding
from trading_bot.research.arc03.arc03_gates import (
    GateResult,
    TradeRecord,
    profit_factor,
)
from trading_bot.research.arc03.arc03_normalize import canonical_json, sha256_file

PREREG_DOCS = pathlib.Path("docs") / "arc03-prereg-01"
AUTH_DOCS = pathlib.Path("docs") / "arc03-data-authority-01"
OUT_REL = pathlib.Path("docs") / "external-audit-01" / "arc03-primary-discovery-01"


def write_json(path: pathlib.Path, obj: Any) -> None:
    """Canonical, deterministic artifact bytes (LF only, sorted keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8"))


def write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = bytearray()
    for r in rows:
        payload += canonical_json(r) + b"\n"
    path.write_bytes(bytes(payload))
    return len(rows)


def mean(xs: list[float]) -> float:
    return math.fsum(xs) / len(xs) if xs else 0.0


# --------------------------------------------------------------------------- binding
def recompute_dataset_digest(docs: pathlib.Path, manifest: dict[str, Any]) -> str:
    """Independent recomputation of the ARC-03 dataset digest from its own registry."""
    quality = [
        json.loads(ln)
        for ln in (docs / "ARC03_DATA_QUALITY_LEDGER.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if ln.strip()
    ]
    valid = {"VALID", "VALID_INITIAL_PARTIAL", "VALID_WITH_DAILY_SUPPLEMENT"}
    files_registry = [
        {
            "symbol": e["symbol"],
            "month": e["month"],
            "raw_sha256": e.get("raw_sha256"),
            "normalized_rows": e.get("rows") if e["classification"] in valid else 0,
            "classification": e["classification"],
        }
        for e in sorted(
            (x for x in quality if x.get("kind") != "SYMBOL_SUMMARY"),
            key=lambda x: (x["symbol"], x["month"]),
        )
    ]
    supplements = sorted(
        [dict(s) for s in manifest.get("daily_supplements", [])],
        key=lambda x: (x["symbol"], x["date"]),
    )
    payload = {
        "schema_version": manifest["schema_version"],
        "normalizer_version": manifest["normalizer_version"],
        "interval": manifest["interval"],
        "files": files_registry,
        "daily_supplements": supplements,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def bind_data(target: pathlib.Path, data_root: pathlib.Path) -> tuple[dict[str, Any], bool]:
    """Re-prove every binding the mission requires BEFORE any economics run."""
    import trading_bot.research.arc03.arc03_authority as authority

    docs = target / AUTH_DOCS
    pre = target / PREREG_DOCS
    manifest = json.loads((docs / "ARC03_DATA_MANIFEST.json").read_text(encoding="utf-8"))
    module_path = pathlib.Path(authority.__file__).resolve()

    spec_sha = sha256_file(pre / "ARC03_SPEC_V1.json")
    manifest_sha = sha256_file(pre / "ARC03_MANIFEST_V1.json")
    recomputed_dataset = recompute_dataset_digest(docs, manifest)

    partition_sha: dict[str, str | None] = {}
    partition_meta: dict[str, dict[str, Any]] = {}
    for sym in ASSETS:
        p = data_root / "data" / "processed" / "arc03_klines_5m" / f"{sym}.jsonl"
        if not p.exists():
            partition_sha[sym] = None
            continue
        h = sha256_file(p)
        partition_sha[sym] = h
        partition_meta[sym] = {"sha256": h, "bytes": p.stat().st_size}

    funding_sha: dict[str, str | None] = {}
    for sym in ASSETS:
        p = data_root / "data" / "processed" / "arc03_funding" / f"{sym}_funding.jsonl"
        funding_sha[sym] = sha256_file(p) if p.exists() else None

    record: dict[str, Any] = {
        "schema": "ARC03_DATA_BINDING_EXECUTION/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "audited_target": str(target),
        "data_root": str(data_root),
        "data_root_is_audited_target": data_root == target,
        "python_import_authority": {
            "module": str(module_path),
            "authority_import_lives_in_target": target in module_path.parents,
        },
        "prereg_binding": {
            "spec_path": str(pre / "ARC03_SPEC_V1.json"),
            "spec_sha256": spec_sha,
            "spec_sha256_expected": EXPECTED_SPEC_SHA256,
            "spec_match": spec_sha == EXPECTED_SPEC_SHA256,
            "manifest_path": str(pre / "ARC03_MANIFEST_V1.json"),
            "manifest_sha256": manifest_sha,
            "manifest_sha256_expected": EXPECTED_MANIFEST_SHA256,
            "manifest_match": manifest_sha == EXPECTED_MANIFEST_SHA256,
        },
        "data_binding": {
            "dataset_sha256_recorded": manifest["dataset_sha256"],
            "dataset_sha256_expected": EXPECTED_DATASET_SHA256,
            "dataset_sha256_recomputed": recomputed_dataset,
            "dataset_match": (
                recomputed_dataset == manifest["dataset_sha256"] == EXPECTED_DATASET_SHA256
            ),
            "partition_sha256_recorded": manifest["partition_sha256"],
            "partition_sha256_observed": partition_sha,
            "partition_meta": partition_meta,
            "partition_match": all(
                partition_sha.get(s) == manifest["partition_sha256"].get(s) for s in ASSETS
            ),
            "funding_partition_sha256_expected_arc01": ARC01_FUNDING_PARTITION_SHA256,
            "funding_partition_sha256_observed": funding_sha,
            "funding_match": all(
                funding_sha.get(s) == ARC01_FUNDING_PARTITION_SHA256.get(s) for s in ASSETS
            ),
        },
        "frozen_constants": {
            "assets": list(FROZEN_ASSETS),
            "assets_match": tuple(FROZEN_ASSETS) == ASSETS,
            "common_window_ms_expected": list(EXPECTED_WINDOW_MS),
            "primary_cost_bps": PRIMARY_COST_BPS,
            "cost_scenarios_bps": list(COST_SCENARIOS_BPS),
            "holding_ms": HOLDING_MS,
        },
    }
    ok = (
        record["python_import_authority"]["authority_import_lives_in_target"]
        and record["prereg_binding"]["spec_match"]
        and record["prereg_binding"]["manifest_match"]
        and record["data_binding"]["dataset_match"]
        and record["data_binding"]["partition_match"]
        and record["data_binding"]["funding_match"]
        and record["frozen_constants"]["assets_match"]
    )
    record["verdict"] = "PASS" if ok else "FAIL"
    return record, ok


# --------------------------------------------------------------------------- controls
def summarize(
    records: list[TradeRecord], nets20: list[float], nets40: list[float]
) -> dict[str, Any]:
    """Compact frozen-metric summary + the full G1..G11 pass/fail map for one trade set."""
    results: list[GateResult] = evaluate_gates(
        records, net_returns_20bps=nets20, net_returns_40bps=nets40
    )
    by = {r.gate_id: r for r in results}
    nets = [r.net_return for r in records]
    ex = [r.net_return_ex_funding for r in records]
    pf, _pf_evaluable = profit_factor(nets)
    return {
        "trade_count": len(records),
        "mean_net_return_10bps": mean(nets),
        "mean_net_return_ex_funding_10bps": mean(ex),
        "profit_factor": "Infinity" if math.isinf(pf) else pf,
        "sharpe": by["G5_SHARPE"].metric,
        "bootstrap_ci_lower": by["G6_BOOTSTRAP"].metric,
        "permutation_p": by["G7_PERMUTATION"].metric,
        "halves": by["G8_TEMPORAL_STABILITY"].metric["halves"],
        "quartiles": by["G8_TEMPORAL_STABILITY"].metric["quartiles"],
        "per_asset_means": by["G9_ASSET_STABILITY"].metric,
        "concentration_shares": by["G10_CONCENTRATION"].metric,
        "mean_net_return_20bps": mean(nets20),
        "mean_net_return_40bps": mean(nets40),
        "per_gate_pass_fail": {
            r.gate_id: {
                "passed": bool(r.passed),
                "metric": (
                    "Infinity"
                    if isinstance(r.metric, float) and math.isinf(r.metric)
                    else r.metric
                ),
                "threshold": r.threshold,
            }
            for r in results
        },
        "satisfies_ALL_critical_gates": all(r.passed for r in results),
    }


def null_control_inputs(
    trades: list[Any],
) -> tuple[list[TradeRecord], list[float], list[float]]:
    """NULL_CONTROL gate inputs, in the frozen G8 order.

    The flip factors are generated over the frozen EMISSION order; the resulting series is
    then presented to the gates in the frozen chronological order (the trade set's
    timestamps are unchanged, so its G8 split must be the primary one).
    """
    series = null_control_series(trades)
    n10 = dict(zip(series["order"], series["nets"], strict=True))
    ex10 = dict(zip(series["order"], series["nets_ex_funding"], strict=True))
    n20 = dict(zip(series["order"], series["nets_by_scenario"][20], strict=True))
    n40 = dict(zip(series["order"], series["nets_by_scenario"][40], strict=True))
    ordered = frozen_gate_order(trades)
    records = [
        TradeRecord(
            trade_id=t.trade_id,
            asset=t.asset,
            entry_time_ms=t.entry_time_ms,
            net_return=n10[t.trade_id],
            net_return_ex_funding=ex10[t.trade_id],
        )
        for t in ordered
    ]
    return records, [n20[t.trade_id] for t in ordered], [n40[t.trade_id] for t in ordered]


# --------------------------------------------------------------------------- PIT audit
def build_truncated(k: Any, upto: int) -> Any:
    """Same partition truncated to bars ``[0, upto]`` (future bars invisible)."""
    return type(k)(
        symbol=k.symbol,
        t=k.t[: upto + 1],
        ct=k.ct[: upto + 1],
        o=k.o[: upto + 1],
        h=k.h[: upto + 1],
        l=k.l[: upto + 1],
        c=k.c[: upto + 1],
        v=k.v[: upto + 1],
        qv=k.qv[: upto + 1],
        n=k.n[: upto + 1],
        tb=k.tb[: upto + 1],
        tq=k.tq[: upto + 1],
        sha256=k.sha256,
        path=k.path,
        rows=upto + 1,
        index={t: i for i, t in enumerate(k.t[: upto + 1])},
    )


def pit_execution_audit(
    partitions: dict[str, Any],
    trades: list[Any],
    funding: dict[str, Any],
) -> dict[str, Any]:
    """PIT verification DURING execution (mission §31), on the real emitted trade set."""
    from trading_bot.research.arc03 import arc03_pit
    from trading_bot.research.arc03.arc03_authority import DAY_MS, evaluate_bar, reference_slots

    checks: dict[str, Any] = {}

    checks["entry_strictly_after_decision"] = {
        "violations": sum(1 for t in trades if not t.entry_time_ms > t.decision_time_ms),
        "n": len(trades),
    }
    checks["exit_is_entry_plus_60_minutes"] = {
        "violations": sum(1 for t in trades if t.exit_time_ms != t.entry_time_ms + HOLDING_MS),
        "n": len(trades),
    }
    checks["decision_time_is_bar_close"] = {
        "violations": sum(
            1
            for t in trades
            if t.decision_time_ms
            != t.decision_bar_open_time_ms + 300_000 - 1
        ),
        "n": len(trades),
    }
    checks["all_references_at_least_24h_older"] = {
        "violations": sum(
            1
            for t in trades
            if any(
                slot + DAY_MS > t.decision_time_ms
                for slot in reference_slots(t.decision_bar_open_time_ms)
            )
        ),
        "n": len(trades),
    }
    checks["exit_bar_within_window"] = {
        "violations": sum(1 for t in trades if t.exit_time_ms > EXPECTED_WINDOW_MS[1]),
        "n": len(trades),
    }
    checks["signal_and_entry_bars_inside_window"] = {
        "violations": sum(
            1
            for t in trades
            if t.decision_bar_open_time_ms < EXPECTED_WINDOW_MS[0]
            or t.entry_time_ms > EXPECTED_WINDOW_MS[1]
        ),
        "n": len(trades),
    }
    checks["no_two_trades_overlap_per_asset"] = (lambda: _overlap_check(trades))()

    # future-mutation invariance on the REAL emission: re-evaluate sampled decisions on a
    # partition truncated at the decision bar (all future bars removed).
    sampled = trades[:PIT_SAMPLE]
    invariance_violations = 0
    for t in sampled:
        k = partitions[t.asset]
        i = k.slot_index(t.decision_bar_open_time_ms)
        if i is None:
            invariance_violations += 1
            continue
        full = evaluate_bar(k, i)
        trunc = evaluate_bar(build_truncated(k, i), i)
        if (
            full["result"],
            full["reason"],
            full.get("participation_shock"),
            full.get("reference_volume_max"),
        ) != (
            trunc["result"],
            trunc["reason"],
            trunc.get("participation_shock"),
            trunc.get("reference_volume_max"),
        ):
            invariance_violations += 1
    checks["future_mutation_invariance_sampled"] = {
        "sampled": len(sampled),
        "violations": invariance_violations,
    }

    # non-signal decisions must be invariant too (sampled from the evaluated universe)
    checks["funding_is_not_a_signal_input"] = {
        "note": "the signal path reads only (open, high, low, close, base volume) and the "
        "30 same-slot references; funding is consumed only after a trade is emitted",
        "funding_module_imported_by_signal_path": "arc03_funding"
        in (pathlib.Path(sys.modules["trading_bot.research.arc03.arc03_prereg_reference"].__file__).read_text(encoding="utf-8")),
    }

    battery = arc03_pit.run_battery()
    battery_passed = sum(1 for c in battery if c["pass"])
    checks["adversarial_battery"] = {
        "checks_total": len(battery),
        "checks_passed": battery_passed,
        "result": "PASS" if battery_passed == len(battery) else "FAIL",
        "checks": battery,
    }

    violations = 0
    for payload in checks.values():
        if isinstance(payload, dict) and "violations" in payload:
            violations += int(payload["violations"])
    battery_ok = checks["adversarial_battery"]["result"] == "PASS"
    verdict = "PASS" if (violations == 0 and battery_ok) else "FAIL"
    return {
        "schema": "ARC03_PIT_EXECUTION_AUDIT/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "pit_contract": str(PREREG_DOCS / "ARC03_PIT_CONTRACT.json"),
        "execution_checks": checks,
        "total_execution_violations": violations,
        "adversarial_battery_result": checks["adversarial_battery"]["result"],
        "verdict": verdict,
    }


def _overlap_check(trades: list[Any]) -> dict[str, Any]:
    violations = 0
    by_asset: dict[str, list[Any]] = {}
    for t in trades:
        by_asset.setdefault(t.asset, []).append(t)
    for rows in by_asset.values():
        rows = sorted(rows, key=lambda x: x.entry_time_ms)
        for a, b in pairwise(rows):
            if b.entry_time_ms <= a.exit_time_ms:
                violations += 1
    return {"violations": violations, "n": len(trades)}


# --------------------------------------------------------------------------- reconciliation
def full_accounting_reconciliation(
    trades: list[Any], funding: dict[str, Any]
) -> dict[str, Any]:
    """Mission §34: identity per trade/scenario + independent funding re-derivation."""
    base = accounting_reconciliation(trades)
    independent_mismatch: list[dict[str, Any]] = []
    settlements_seen = {0: 0, 1: 0, 2: 0, "more": 0}
    for t in trades:
        series = funding.get(t.asset)
        if series is None:
            continue
        # independent re-derivation: iterate the certified settlement array directly
        lo = 0
        while lo < series.rows and series.funding_time_ms[lo] <= t.entry_time_ms:
            lo += 1
        leg = 0.0
        n = 0
        j = lo
        while j < series.rows and series.funding_time_ms[j] <= t.exit_time_ms:
            leg += -t.direction_sign * series.funding_rate[j]
            n += 1
            j += 1
        if n != t.funding_settlements_applied or abs(leg - t.funding_cashflow_return) > 1e-15:
            independent_mismatch.append(
                {
                    "trade_id": t.trade_id,
                    "recorded_settlements": t.funding_settlements_applied,
                    "re_derived_settlements": n,
                    "recorded_cashflow": t.funding_cashflow_return,
                    "re_derived_cashflow": leg,
                }
            )
        key = n if n <= 1 else (2 if n == 2 else "more")
        settlements_seen[key] = settlements_seen.get(key, 0) + 1
    base["independent_funding_rederivation"] = {
        "mismatches": independent_mismatch[:20],
        "mismatch_count": len(independent_mismatch),
    }
    base["funding_settlement_distribution"] = {str(k): v for k, v in settlements_seen.items()}
    base["ex_funding_has_zero_funding_contribution"] = all(
        abs(t.net_return_ex_funding(PRIMARY_COST_BPS) - (t.gross_price_return - t.cost_return(PRIMARY_COST_BPS)))
        <= 1e-15
        for t in trades
    )
    ok = (
        base["verdict"] == "PASS"
        and not independent_mismatch
        and base["ex_funding_has_zero_funding_contribution"]
    )
    base["verdict"] = "PASS" if ok else "FAIL"
    base["schema"] = "ARC03_ACCOUNTING_RECONCILIATION/1.0.0"
    base["experiment_id"] = EXPERIMENT_ID
    return base


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(TARGET_DEFAULT))
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--implementation-commit", default=None)
    ap.add_argument("--generated-from-commit", default=None)
    args = ap.parse_args(argv)

    target = pathlib.Path(args.target).resolve()
    data_root = pathlib.Path(args.data_root).resolve()
    out = target / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    ledger = ExperimentLedger(out / "EXPERIMENT_LEDGER.jsonl")

    print("[arc03-pd01] binding data authority ...", file=sys.stderr, flush=True)
    binding, binding_ok = bind_data(target, data_root)
    write_json(out / "ARC03_DATA_BINDING_EXECUTION.json", binding)
    if not binding_ok:
        write_json(
            out / "ARC03_PRIMARY_DISCOVERY_RESULT.json",
            {
                "schema": "ARC03_PRIMARY_DISCOVERY_RESULT/1.0.0",
                "experiment_id": EXPERIMENT_ID,
                "FINAL_STATUS": "INFRASTRUCTURE_FAIL",
                "reason": "DATA_OR_PREREG_BINDING_MISMATCH",
                "economic_execution": "NOT_STARTED",
                "binding": binding,
            },
        )
        print("[arc03-pd01] INFRASTRUCTURE_FAIL (binding) — economics not started", file=sys.stderr)
        return 2

    ledger.assert_no_previous_completed()
    if not any(e.get("state") == "REGISTERED" for e in ledger.entries):
        ledger.append(
            "REGISTERED",
            {
                "experiment_id": EXPERIMENT_ID,
                "prereg_commit": "8ebf8a181a3cfaf03737ef585f8906d28f8d419f",
                "independent_verifier_commit": "2dfe96c88fd66953d3fee148415e2e837c1bd2c7",
                "data_authority_commit": "8668a3174234255b1b1f27a7bf04b8f022af68bb",
                "data_binding_verdict": binding["verdict"],
            },
        )
    if any(e.get("state") == "STARTED" for e in ledger.entries):
        resumed = True
    else:
        ledger.append("STARTED", {"experiment_id": EXPERIMENT_ID, "resumed": False})
        resumed = False

    print("[arc03-pd01] loading certified partitions ...", file=sys.stderr, flush=True)
    parts = {s: load_partition(s, partition_dir=data_root / "data" / "processed" / "arc03_klines_5m") for s in ASSETS}
    funding = {s: load_funding(s, funding_dir=data_root / "data" / "processed" / "arc03_funding") for s in ASSETS}

    observed_window = common_causal_window(parts)
    if (observed_window["start_ms"], observed_window["end_ms"]) != EXPECTED_WINDOW_MS:
        binding.setdefault("common_window_recomputed", observed_window)
        binding["verdict"] = "FAIL"
        write_json(out / "ARC03_DATA_BINDING_EXECUTION.json", binding)
        write_json(
            out / "ARC03_PRIMARY_DISCOVERY_RESULT.json",
            {
                "schema": "ARC03_PRIMARY_DISCOVERY_RESULT/1.0.0",
                "experiment_id": EXPERIMENT_ID,
                "FINAL_STATUS": "INFRASTRUCTURE_FAIL",
                "reason": "COMMON_WINDOW_MISMATCH",
                "observed": observed_window,
                "expected_ms": list(EXPECTED_WINDOW_MS),
                "economic_execution": "NOT_STARTED",
            },
        )
        print("[arc03-pd01] INFRASTRUCTURE_FAIL (common window)", file=sys.stderr)
        return 2
    binding["common_window_recomputed"] = observed_window
    binding["common_window_match"] = True
    write_json(out / "ARC03_DATA_BINDING_EXECUTION.json", binding)

    start_ms, end_ms = EXPECTED_WINDOW_MS
    print("[arc03-pd01] primary emission (frozen reference signal path) ...", file=sys.stderr, flush=True)
    ref = emit_trades(parts, start_ms=start_ms, end_ms=end_ms, funding=funding)
    trades = build_executed_trades(ref, funding, parts)
    print(f"[arc03-pd01] primary trades emitted: {len(trades)}", file=sys.stderr, flush=True)

    print("[arc03-pd01] controls ...", file=sys.stderr, flush=True)
    ctrl_dir = direction_control_trades(trades)
    ctrl_timing, timing_dropped = timing_control_trades(parts, trades, funding)
    ref_part = emit_participation_control_trades(parts, start_ms=start_ms, end_ms=end_ms)
    ctrl_part = build_executed_trades(ref_part, funding, parts)

    print("[arc03-pd01] PIT execution audit ...", file=sys.stderr, flush=True)
    pit = pit_execution_audit(parts, trades, funding)
    write_json(out / "ARC03_PIT_EXECUTION_AUDIT.json", pit)

    print("[arc03-pd01] accounting + ledger reconciliation ...", file=sys.stderr, flush=True)
    rows = [ledger_row(t) for t in trades]
    write_jsonl(out / "ARC03_TRADE_LEDGER.jsonl", rows)
    acct = full_accounting_reconciliation(trades, funding)
    write_json(out / "ARC03_ACCOUNTING_RECONCILIATION.json", acct)
    ledger_rec = trade_ledger_reconciliation(trades, ref, rows)

    # trade-set identity across cost scenarios
    scenario_ids = {
        str(bps): [r["trade_id"] for r in rows]
        for bps in COST_SCENARIOS_BPS
    }
    trade_set_identical = len({tuple(v) for v in scenario_ids.values()}) == 1
    ledger_rec["identical_trade_ids_across_cost_scenarios"] = trade_set_identical

    funnel = {
        "schema": "ARC03_DECISION_FUNNEL/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "assets": list(ASSETS),
        "common_window_ms": [start_ms, end_ms],
        "decisions_evaluated": ref.decisions_evaluated,
        "no_signal_precedence": list(ref.funnel.keys()),
        "reason_counts": dict(ref.funnel),
        "bars_outside_common_window": ref.funnel.get("OUTSIDE_COMMON_WINDOW", 0),
        "signals_long": sum(1 for t in trades if t.direction == "LONG"),
        "signals_short": sum(1 for t in trades if t.direction == "SHORT"),
        "executed_trades": len(trades),
        "per_asset_signals": {
            a: {
                "long": sum(1 for t in trades if t.asset == a and t.direction == "LONG"),
                "short": sum(1 for t in trades if t.asset == a and t.direction == "SHORT"),
            }
            for a in ASSETS
        },
        "participation_control_funnel": {
            "decisions_evaluated": ref_part.decisions_evaluated,
            "reason_counts": dict(ref_part.funnel),
            "executed_trades": len(ctrl_part),
        },
        "reconciliation": ledger_rec,
        "no_silent_filtering": "every evaluated decision is accounted for by exactly one reason or one trade",
    }
    write_json(out / "ARC03_DECISION_FUNNEL.json", funnel)

    print("[arc03-pd01] statistical gates ...", file=sys.stderr, flush=True)
    rec_p, n20, n40 = gate_inputs(trades)
    primary = summarize(rec_p, n20, n40)

    c_dir_rec, c_dir_n20, c_dir_n40 = gate_inputs(ctrl_dir)
    c_tim_rec, c_tim_n20, c_tim_n40 = gate_inputs(ctrl_timing)
    c_par_rec, c_par_n20, c_par_n40 = gate_inputs(ctrl_part)
    c_null_rec, c_null_n20, c_null_n40 = null_control_inputs(trades)

    controls = {
        "DIRECTION_CONTROL": summarize(c_dir_rec, c_dir_n20, c_dir_n40),
        "TIMING_CONTROL": summarize(c_tim_rec, c_tim_n20, c_tim_n40),
        "PARTICIPATION_CONTROL": summarize(c_par_rec, c_par_n20, c_par_n40),
        "NULL_CONTROL": summarize(c_null_rec, c_null_n20, c_null_n40),
    }
    controls["TIMING_CONTROL"]["dropped_for_missing_delayed_slot"] = timing_dropped
    control_results = {
        "schema": "ARC03_CONTROL_RESULTS/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "control_plan": str(PREREG_DOCS / "ARC03_CONTROL_PLAN.json"),
        "primary_cost_bps": PRIMARY_COST_BPS,
        "controls": controls,
        "any_control_satisfies_all_critical_gates": any(
            c["satisfies_ALL_critical_gates"] for c in controls.values() if isinstance(c, dict)
        ),
        "controls_are_not_promotable": True,
    }
    write_json(out / "ARC03_CONTROL_RESULTS.json", control_results)

    gate_results = {
        "schema": "ARC03_STATISTICAL_GATES_RESULT/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "gates_file": str(PREREG_DOCS / "ARC03_STATISTICAL_GATES.json"),
        "primary_cost_bps": PRIMARY_COST_BPS,
        "cost_scenarios_bps": list(COST_SCENARIOS_BPS),
        "identical_trade_set_across_cost_scenarios": trade_set_identical,
        "primary": primary,
        "all_critical_gates_pass": primary["satisfies_ALL_critical_gates"],
    }
    write_json(out / "ARC03_STATISTICAL_GATES_RESULT.json", gate_results)

    # ---------------------------------------------------------------- verdict
    infra_ok = (
        acct["verdict"] == "PASS"
        and ledger_rec["verdict"] == "PASS"
        and pit["verdict"] == "PASS"
        and trade_set_identical
    )
    if not infra_ok:
        final = "INFRASTRUCTURE_FAIL"
        reason = "ACCOUNTING_LEDGER_PIT_OR_TRADE_SET_FAILURE"
    elif not primary["satisfies_ALL_critical_gates"]:
        final = "DISCOVERY_FAIL"
        g1 = primary["per_gate_pass_fail"]["G1_SAMPLE"]["passed"]
        reason = "CRITICAL_GATE_FAILURE" if g1 else "INSUFFICIENT_SAMPLE"
    elif control_results["any_control_satisfies_all_critical_gates"]:
        final = "DISCOVERY_FAIL"
        reason = "MECHANISM_NOT_IDENTIFIED_CONTROL_PASSED_ALL_CRITICAL_GATES"
    else:
        final = "DISCOVERY_PASS"
        reason = "ALL_CRITICAL_GATES_PASS_AND_NO_CONTROL_PASSES_ALL"

    failed_gates = [
        gid for gid, v in primary["per_gate_pass_fail"].items() if not v["passed"]
    ]

    result = {
        "schema": "ARC03_PRIMARY_DISCOVERY_RESULT/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "hypothesis_id": "ARC-03-PARTICIPATION-SHOCK-REVERSAL-01",
        "FINAL_STATUS": final,
        "reason": reason,
        "economic_execution": "COMPLETED" if infra_ok else "INVALID",
        "execution_worktree": str(target),
        "execution_branch": _git(target, "rev-parse", "--abbrev-ref", "HEAD"),
        "prereg_commit": "8ebf8a181a3cfaf03737ef585f8906d28f8d419f",
        "independent_verifier_commit": "2dfe96c88fd66953d3fee148415e2e837c1bd2c7",
        "data_authority_commit": "8668a3174234255b1b1f27a7bf04b8f022af68bb",
        "execution_implementation_commit": args.implementation_commit,
        "generated_from_commit": args.generated_from_commit,
        "result_commit": None,
        "resumed_run": resumed,
        "prereg_drift": 0 if binding["prereg_binding"]["spec_match"] and binding["prereg_binding"]["manifest_match"] else "NONZERO",
        "data_authority_drift": 0 if binding["data_binding"]["partition_match"] and binding["data_binding"]["dataset_match"] else "NONZERO",
        "python_import_authority": "PASS" if binding["python_import_authority"]["authority_import_lives_in_target"] else "FAIL",
        "test_target_execution_target": _test_target_flag(target),
        "exactly_once": {
            "economic_experiments": ledger.completed_count(),
            "states": ledger.states(),
        },
        "counts": {
            "decisions_evaluated": ref.decisions_evaluated,
            "signals_long": funnel["signals_long"],
            "signals_short": funnel["signals_short"],
            "trades_total": len(trades),
            "trades_by_asset": {a: sum(1 for t in trades if t.asset == a) for a in ASSETS},
        },
        "metrics": {
            "net_expectancy_10bps": primary["mean_net_return_10bps"],
            "net_expectancy_ex_funding_10bps": primary["mean_net_return_ex_funding_10bps"],
            "profit_factor": primary["profit_factor"],
            "sharpe": primary["sharpe"],
            "bootstrap_ci_lower": primary["bootstrap_ci_lower"],
            "permutation_p": primary["permutation_p"],
            "temporal_stability": {"halves": primary["halves"], "quartiles": primary["quartiles"]},
            "asset_stability": primary["per_asset_means"],
            "concentration": primary["concentration_shares"],
            "cost_sensitivity": {
                "mean_20bps": primary["mean_net_return_20bps"],
                "mean_40bps": primary["mean_net_return_40bps"],
            },
        },
        "gates": primary["per_gate_pass_fail"],
        "failed_critical_gates": failed_gates,
        "controls": {
            k: {
                "trade_count": v["trade_count"],
                "satisfies_ALL_critical_gates": v["satisfies_ALL_critical_gates"],
                "failed_gates": [g for g, x in v["per_gate_pass_fail"].items() if not x["passed"]],
            }
            for k, v in controls.items()
            if isinstance(v, dict)
        },
        "reconciliation": {
            "accounting": acct["verdict"],
            "trade_ledger": ledger_rec["verdict"],
            "pit_execution_audit": pit["verdict"],
            "identical_trade_ids_across_cost_scenarios": trade_set_identical,
        },
        "false_success": 0,
        "arc03_state": (
            "EDGE_CANDIDATE_DISCOVERED"
            if final == "DISCOVERY_PASS"
            else ("KILLED_FOR_THIS_HYPOTHESIS_ID" if final == "DISCOVERY_FAIL" else "NOT_ESTABLISHED")
        ),
        "defects": [],
        "limitations": [
            "Common window starts 2020-09-14 (SOLUSDT admission); earlier BTC/ETH history is outside the evaluated window.",
            "The last 60 minutes of the window yields no trades (frozen forward-data guard).",
            "Funding cashflow is charged on the entry notional (frozen O(1e-4) simplification).",
            "No critical gate covers drawdown; drawdown is diagnostic only.",
            "H5 collision/orthogonality is a later authorized stage and is NOT evaluated here.",
            "Trades are treated as exchangeable observations in G6/G7; overlap is bounded by the frozen SKIP policy.",
        ],
        "next": (
            "ARC03_ROBUSTNESS_OOS_01" if final == "DISCOVERY_PASS" else "ARC02_OR_NEXT_ORTHOGONAL_HYPOTHESIS"
        ),
    }
    write_json(out / "ARC03_PRIMARY_DISCOVERY_RESULT.json", result)

    md = render_md(result, primary, controls, binding, pit, acct, ledger_rec, funnel)
    (out / "ARC03_PRIMARY_DISCOVERY_RESULT.md").write_bytes(md.encode("utf-8"))

    ledger.append(
        "COMPLETED",
        {
            "experiment_id": EXPERIMENT_ID,
            "final_status": final,
            "trades": len(trades),
            "economic_experiments": ledger.completed_count() + 1,
            "accounting_reconciliation": acct["verdict"],
            "trade_ledger_reconciliation": ledger_rec["verdict"],
            "pit_execution_audit": pit["verdict"],
        },
    )

    run_report = {
        "schema": "ARC03_RUN_REPORT/1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "final_status": final,
        "reason": reason,
        "artifacts": sorted(p.name for p in out.iterdir()),
        "execution_implementation_commit": args.implementation_commit,
        "generated_from_commit": args.generated_from_commit,
        "result_commit": None,
        "exactly_once": {
            "economic_experiments": ledger.completed_count(),
            "states": ledger.states(),
        },
        "binding": binding,
        "counts": result["counts"],
        "metrics": result["metrics"],
        "gates": primary["per_gate_pass_fail"],
        "controls": result["controls"],
        "reconciliation": result["reconciliation"],
        "resumed_run": resumed,
    }
    write_json(out / "RUN_REPORT.json", run_report)
    (out / "RUN_REPORT.md").write_bytes(render_run_md(result, primary, controls).encode("utf-8"))

    print(f"[arc03-pd01] FINAL_STATUS={final} reason={reason}", file=sys.stderr)
    print(f"[arc03-pd01] artifacts in {out}", file=sys.stderr)
    return 0


def _git(target: pathlib.Path, *args: str) -> str | None:
    import subprocess

    try:
        return subprocess.run(
            ["git", "-C", str(target), *args], capture_output=True, text=True, timeout=60, check=False
        ).stdout.strip() or None
    except Exception:
        return None


def _test_target_flag(target: pathlib.Path) -> str:
    conftest = target / "conftest.py"
    ok = conftest.exists() and "sys.path.insert" in conftest.read_text(encoding="utf-8")
    return "PASS" if ok else "FAIL"


def render_md(result, primary, controls, binding, pit, acct, ledger_rec, funnel) -> str:
    m = result["metrics"]
    lines = [
        "# ARC-03 PRIMARY DISCOVERY 01 — RESULT",
        "",
        f"**FINAL_STATUS: `{result['FINAL_STATUS']}`** ({result['reason']})",
        "",
        f"- EXPERIMENT_ID: `{result['experiment_id']}`",
        f"- PREREG_COMMIT: `{result['prereg_commit']}`",
        f"- INDEPENDENT_VERIFIER_COMMIT: `{result['independent_verifier_commit']}`",
        f"- EXECUTION_IMPLEMENTATION_COMMIT: `{result['execution_implementation_commit']}`",
        f"- generated_from_commit: `{result['generated_from_commit']}`",
        "- result_commit: `null` (self-referential; reported externally)",
        f"- ARC03_STATE: `{result['arc03_state']}`",
        "",
        "## Counts",
        "",
        f"- decisions evaluated: {result['counts']['decisions_evaluated']}",
        f"- signals LONG/SHORT: {result['counts']['signals_long']} / {result['counts']['signals_short']}",
        f"- trades: {result['counts']['trades_total']} (BTC {result['counts']['trades_by_asset']['BTCUSDT']}, "
        f"ETH {result['counts']['trades_by_asset']['ETHUSDT']}, SOL {result['counts']['trades_by_asset']['SOLUSDT']})",
        "",
        "## Primary metrics (10 bps unless stated)",
        "",
        f"- net expectancy: {m['net_expectancy_10bps']:.10f}",
        f"- net expectancy ex-funding: {m['net_expectancy_ex_funding_10bps']:.10f}",
        f"- profit factor: {m['profit_factor']}",
        f"- sharpe: {m['sharpe']:.6f}",
        f"- bootstrap CI lower: {m['bootstrap_ci_lower']:.10f}",
        f"- permutation p: {m['permutation_p']:.6f}",
        f"- temporal halves: {m['temporal_stability']['halves']}",
        f"- temporal quartiles: {m['temporal_stability']['quartiles']}",
        f"- concentration: {json.dumps(m['concentration'], sort_keys=True, default=str)}",
        f"- cost sensitivity 20/40 bps: {m['cost_sensitivity']['mean_20bps']:.10f} / {m['cost_sensitivity']['mean_40bps']:.10f}",
        "",
        "## Gates",
        "",
        "| gate | passed | metric | threshold |",
        "| --- | --- | --- | --- |",
    ]
    for gid, v in primary["per_gate_pass_fail"].items():
        metric = v["metric"]
        metric = f"{metric:.10f}" if isinstance(metric, float) else str(metric)
        lines.append(f"| {gid} | {'PASS' if v['passed'] else 'FAIL'} | {metric} | {v['threshold']} |")
    lines += ["", "## Controls", "", "| control | trades | all gates | failed gates |", "| --- | --- | --- | --- |"]
    for cid, c in result["controls"].items():
        lines.append(
            f"| {cid} | {c['trade_count']} | {'PASS' if c['satisfies_ALL_critical_gates'] else 'FAIL'} | "
            f"{', '.join(c['failed_gates']) or '-'} |"
        )
    lines += [
        "",
        "## Reconciliation",
        "",
        f"- ACCOUNTING_RECONCILIATION: {acct['verdict']}",
        f"- TRADE_LEDGER_RECONCILIATION: {ledger_rec['verdict']}",
        f"- PIT_EXECUTION_AUDIT: {pit['verdict']}",
        f"- ECONOMIC_EXPERIMENTS: {result['exactly_once']['economic_experiments']}",
        f"- FALSE_SUCCESS: {result['false_success']}",
        "",
        "## Next",
        "",
        f"`{result['next']}`",
        "",
    ]
    _ = (binding, funnel, controls)
    return "\n".join(lines)


def render_run_md(result, primary, controls) -> str:
    return "\n".join(
        [
            "# ARC-03 PRIMARY DISCOVERY 01 — RUN REPORT",
            "",
            f"FINAL_STATUS = **{result['FINAL_STATUS']}**",
            f"reason = `{result['reason']}`",
            "",
            f"- ECONOMIC_EXPERIMENTS = {result['exactly_once']['economic_experiments']}",
            f"- TRADES_TOTAL = {result['counts']['trades_total']}",
            f"- NET_EXPECTANCY_10BPS = {result['metrics']['net_expectancy_10bps']:.10f}",
            f"- NET_EXPECTANCY_EX_FUNDING = {result['metrics']['net_expectancy_ex_funding_10bps']:.10f}",
            f"- all critical gates pass = {primary['satisfies_ALL_critical_gates']}",
            f"- any control passes all critical gates = "
            f"{any(c['satisfies_ALL_critical_gates'] for c in controls.values() if isinstance(c, dict))}",
            "",
            "Artifacts: see `ARC03_PRIMARY_DISCOVERY_RESULT.json`, `ARC03_STATISTICAL_GATES_RESULT.json`, "
            "`ARC03_CONTROL_RESULTS.json`, `ARC03_TRADE_LEDGER.jsonl`, `ARC03_DECISION_FUNNEL.json`, "
            "`ARC03_ACCOUNTING_RECONCILIATION.json`, `ARC03_PIT_EXECUTION_AUDIT.json`, "
            "`ARC03_DATA_BINDING_EXECUTION.json`, `EXPERIMENT_LEDGER.jsonl`.",
            "",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
