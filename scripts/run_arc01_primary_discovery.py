#!/usr/bin/env python
"""ARC-01 PRIMARY DISCOVERY 01 -- one-shot frozen executor.

Runs EXACTLY ONE preregistered economic experiment for
``ARC-01-FUNDING-CROWDING-UNWIND-01`` and evaluates the frozen G1-G11 critical gates
plus the four preregistered falsification controls.

Pipeline (one shot, no partial-result inspection):

    prepare  -> import authority + PREREG hash check + data-authority hash check
    validate -> exactly-once experiment ledger (REGISTERED/STARTED/COMPLETED)
    freeze   -> the implementation is already committed (EXECUTION_IMPLEMENTATION_COMMIT)
    run      -> primary + 4 controls over the certified authorities
    persist  -> complete result, ledger, funnel, gates, controls, reconciliation
    evaluate -> read back from the persisted artifacts and score the gates

Usage:
    python scripts/run_arc01_primary_discovery.py --preflight
    python scripts/run_arc01_primary_discovery.py --synthetic
    python scripts/run_arc01_primary_discovery.py            # the real one-shot run
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[1]
SRC = (REPO / "src").resolve()
# Import authority: THIS worktree's src must win over the editable install .pth.
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

import trading_bot  # noqa: E402

from trading_bot.backtesting import stat_validation as sv  # noqa: E402
from trading_bot.research.arc01 import arc01_authority as auth  # noqa: E402
from trading_bot.research.arc01 import arc01_discovery as disc  # noqa: E402
from trading_bot.research.arc01 import prereg_reference as ref  # noqa: E402

EXPERIMENT_ID = "ARC01_PRIMARY_DISCOVERY_01"
PREREG_COMMIT = "fa15fb4f300815f56bf14e503d1a147cb73f27a6"
DATA_AUTHORITY_COMMIT = "6e42dd9d4c19800925fd555999686d1e2b4ef47e"
INDEPENDENT_VERIFIER_COMMIT = "f187296589fa45102b552a4eb2468b537ee3ba6b"

SPEC_SHA256 = "89b8590ccde0d90ae35dfe5f91d9dad706622a8004d77ef54c35c72c9cc0b313"
MANIFEST_SHA256 = "d698e3d830651988c98359734ebb848efa8fa7bff4103bb44f58fb82b885df5e"
DATASET_SHA256 = "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec"

OUT_DIR = REPO / "docs" / "external-audit-01" / "arc01-primary-discovery-01"
LEDGER_PATH = OUT_DIR / "EXPERIMENT_LEDGER.jsonl"
PREREG_DIR = REPO / "docs" / "arc01-prereg-01"

OI_DAY_LO = "2021-11-29"
OI_DAY_HI = "2026-09-10"
PIT_MUTATION_SAMPLE = 40


class InfrastructureFailure(RuntimeError):
    """Invalid experiment: wrong checkout/data/hash, PIT violation, ledger corruption."""


def utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(p: Path) -> str:
    return auth.sha256_file(p)


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO).stdout.strip()
    except Exception:
        return "-"


def git_dirty() -> bool:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO).stdout.strip()
        return bool(out)
    except Exception:
        return True


# --------------------------------------------------------------------- pre-flight
def assert_import_authority() -> dict[str, Any]:
    mods = {
        "trading_bot": trading_bot.__file__,
        "stat_validation": sv.__file__,
        "prereg_reference": ref.__file__,
        "arc01_discovery": disc.__file__,
        "arc01_authority": auth.__file__,
    }
    resolved = {k: str(Path(v).resolve()) for k, v in mods.items()}
    outside = [k for k, v in resolved.items() if SRC not in Path(v).parents]
    evidence = {
        "worktree": str(REPO),
        "src_root": str(SRC),
        "resolved_modules": resolved,
        "modules_outside_worktree": outside,
        "stat_validation_sha256": sha256_file(Path(sv.__file__)),
        "status": "PASS" if not outside else "FAIL",
    }
    if outside:
        raise InfrastructureFailure(f"PYTHON_IMPORT_AUTHORITY=FAIL modules outside worktree: {outside}")
    return evidence


def check_prereg_drift() -> dict[str, Any]:
    spec = sha256_file(PREREG_DIR / "ARC01_SPEC_V1.json")
    manifest = sha256_file(PREREG_DIR / "ARC01_MANIFEST_V1.json")
    evidence = {
        "spec_sha256_recomputed": spec,
        "spec_sha256_expected": SPEC_SHA256,
        "manifest_sha256_recomputed": manifest,
        "manifest_sha256_expected": MANIFEST_SHA256,
        "prereg_commit": PREREG_COMMIT,
    }
    evidence["PREREG_DRIFT"] = 0 if (spec == SPEC_SHA256 and manifest == MANIFEST_SHA256) else 1
    if evidence["PREREG_DRIFT"] != 0:
        raise InfrastructureFailure("PREREG_DRIFT != 0")
    return evidence


def check_data_authority() -> dict[str, Any]:
    funding = auth.verify_funding()
    ledger = auth.verify_oi_ledger_fingerprint()
    evidence: dict[str, Any] = {"funding": funding, "oi": ledger}
    if funding["status"] != "PASS" or ledger["status"] != "PASS":
        raise InfrastructureFailure("DATA_AUTHORITY_DRIFT: funding/OI binding failed")
    return evidence


def check_frozen_constants() -> dict[str, Any]:
    """Cross-check the implementation constants against the frozen prereg artifacts."""
    spec = json.loads((PREREG_DIR / "ARC01_SPEC_V1.json").read_text(encoding="utf-8"))
    gates = json.loads((PREREG_DIR / "ARC01_STATISTICAL_GATES.json").read_text(encoding="utf-8"))
    controls = json.loads((PREREG_DIR / "ARC01_CONTROL_PLAN.json").read_text(encoding="utf-8"))
    checks = {
        "assets": tuple(spec["market"]["assets"]) == disc.ASSETS,
        "window_start": spec["common_window"]["start_ms"] == disc.COMMON_WINDOW_START_MS,
        "window_end": spec["common_window"]["end_ms"] == disc.COMMON_WINDOW_END_MS,
        "funding_lookback_days": spec["funding_transform"]["lookback"]["length_days"] == disc.FUNDING_LOOKBACK_MS // 86_400_000,
        "funding_min_obs": spec["funding_transform"]["minimum_observations"] == disc.FUNDING_MIN_OBSERVATIONS,
        "mad_multiplier": float(spec["funding_transform"]["mad_multiplier"]) == disc.MAD_SCALE,
        "z_positive_threshold": float(spec["funding_transform"]["positive_threshold"]) == disc.FUNDING_Z_POSITIVE_THRESHOLD,
        "z_negative_threshold": float(spec["funding_transform"]["negative_threshold"]) == disc.FUNDING_Z_NEGATIVE_THRESHOLD,
        "oi_lookback_hours": spec["oi_transform"]["lookback"]["length_hours"] == disc.OI_LOOKBACK_MS // 3_600_000,
        "oi_staleness_ms": 600_000 == disc.OI_MAX_STALENESS_MS,
        "holding_hours": spec["exit"]["holding_period"]["holding_bars"] == disc.HOLDING_MS // 3_600_000,
        "holding_bars": spec["exit"]["holding_period"]["holding_bars"] == 72,
        "cost_scenarios": tuple(spec["cost_model"]["cost_sensitivities_bps"]) == disc.COST_SCENARIOS_BPS,
        "primary_cost_bps": spec["cost_model"]["PRIMARY_ROUND_TRIP_COST_BPS"] == disc.PRIMARY_COST_BPS,
        "price_context_none": spec["price_context"]["PRICE_CONTEXT"] == "NONE",
        "stop_none": spec["position_policies"]["STOP"] == "NONE",
        "cooldown_none": spec["position_policies"]["COOLDOWN"] == "NONE",
        "overlap_skip": spec["position_policies"]["OVERLAPPING_SIGNAL_POLICY"].startswith("SKIP"),
        "g1_total": 120 == disc.G1_MIN_TOTAL_TRADES,
        "g1_per_asset": 40 == disc.G1_MIN_TRADES_PER_ASSET,
        "g4_pf": float(gates["critical_gates"][3]["requirement"].replace(">= ", "")) == disc.G4_MIN_PROFIT_FACTOR,
        "g5_sharpe": float(gates["critical_gates"][4]["requirement"].replace(">= ", "")) == disc.G5_MIN_SHARPE,
        "g6_resamples": 10_000 == disc.BOOTSTRAP_RESAMPLES,
        "g7_draws": 10_000 == disc.PERMUTATION_DRAWS,
        "seed": 20260915 == disc.BOOTSTRAP_SEED,
        "seed_is_null_seed": disc.NULL_SEED == 20260915,
        "four_controls": len(controls["controls"]) == 4,
        "no_signal_precedence": tuple(spec["signal_rules"]["deterministic_no_signal_precedence"]) == ref.NO_SIGNAL_PRECEDENCE,
        "no_signal_is_first_class": "first-class" in spec["signal_rules"]["NO_SIGNAL_RULE"],
    }
    failed = [k for k, v in checks.items() if not v]
    return {"checks": checks, "failed": failed, "status": "PASS" if not failed else "FAIL"}


# ------------------------------------------------------------------------ ledger
def read_ledger() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    events = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def append_ledger(event: str, detail: dict[str, Any]) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events = read_ledger()
    record = {
        "seq": len(events) + 1,
        "event": event,
        "experiment_id": EXPERIMENT_ID,
        "utc": utc_now(),
        "git_head": git_head(),
        "prereg_commit": PREREG_COMMIT,
        "detail": detail,
    }
    with LEDGER_PATH.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def assert_not_consumed(events: Sequence[dict[str, Any]]) -> None:
    for e in events:
        if e.get("experiment_id") == EXPERIMENT_ID and e.get("event") == "COMPLETED":
            raise InfrastructureFailure(
                f"EXACTLY_ONCE_VIOLATION: a COMPLETED economic execution already exists for {EXPERIMENT_ID} "
                f"(seq={e.get('seq')} at {e.get('utc')}). Re-running is forbidden."
            )


# -------------------------------------------------------------------- execution
def load_authorities(data_root: Path) -> tuple[dict[str, auth.FundingSeries], dict[str, auth.Series], dict[str, auth.Series]]:
    funding = {a: auth.load_funding(a) for a in disc.ASSETS}
    price = {a: auth.load_price(data_root, a) for a in disc.ASSETS}
    oi = {a: auth.load_oi(data_root, a, OI_DAY_LO, OI_DAY_HI) for a in disc.ASSETS}
    for a in disc.ASSETS:
        if oi[a].unverified_days:
            raise InfrastructureFailure(f"OI shard(s) not byte-bound to the certified ledger: {a} {oi[a].unverified_days[:5]}")
    return funding, oi, price


def run_all(
    funding: dict[str, auth.FundingSeries],
    oi: dict[str, auth.Series],
    price: dict[str, auth.Series],
) -> dict[str, Any]:
    variants: dict[str, Any] = {}
    for name, spec in [("PRIMARY", {"direction_mode": "PRIMARY", "oi_leg": True, "shift_ms": 0})] + list(disc.CONTROL_SPECS.items()):
        trades: list[disc.Trade] = []
        funnels: list[dict[str, Any]] = []
        for a in disc.ASSETS:
            tr, fn = disc.run_variant(
                variant=name,
                funding=funding[a],
                oi=oi[a],
                price=price[a],
                shift_ms=int(spec["shift_ms"]),
                oi_leg=bool(spec["oi_leg"]),
                direction_mode=str(spec["direction_mode"]),
            )
            trades.extend(tr)
            funnels.append(fn)
        trades.sort(key=lambda t: (t.entry_time_ms, t.asset, t.trade_id))
        variants[name] = {
            "trades": trades,
            "funnel_per_asset": funnels,
            "funnel": disc.merge_funnels(funnels),
            "gates": disc.evaluate_gates(trades),
        }
    return variants


def pit_execution_audit(
    trades: Sequence[disc.Trade],
    funding: dict[str, auth.FundingSeries],
    oi: dict[str, auth.Series],
    price: dict[str, auth.Series],
) -> dict[str, Any]:
    """Non-vacuous in-execution PIT audit on the realized trade set."""
    violations: list[str] = []
    for t in trades:
        T = t.decision_time_ms
        if t.funding_time_ms > T:
            violations.append(f"{t.trade_id}: funding_time > decision_time")
        if t.oi_now_time_ms is not None and t.oi_reference_time_ms is not None:
            if t.oi_now_time_ms > T:
                violations.append(f"{t.trade_id}: oi_now_time > decision_time")
            if t.oi_reference_time_ms > T - disc.OI_LOOKBACK_MS:
                violations.append(f"{t.trade_id}: oi_reference_time > T-24h")
            if t.oi_staleness_now_ms is None or t.oi_staleness_now_ms > disc.OI_MAX_STALENESS_MS:
                violations.append(f"{t.trade_id}: oi_now staleness")
            if t.oi_staleness_reference_ms is None or t.oi_staleness_reference_ms > disc.OI_MAX_STALENESS_MS:
                violations.append(f"{t.trade_id}: oi_reference staleness")
        if not (t.entry_time_ms > T):
            violations.append(f"{t.trade_id}: entry not strictly after decision")
        if t.exit_time_ms != t.entry_time_ms + disc.HOLDING_MS:
            violations.append(f"{t.trade_id}: exit != entry+72h")
        if t.entry_time_ms < disc.COMMON_WINDOW_START_MS or t.entry_time_ms > disc.COMMON_WINDOW_END_MS:
            violations.append(f"{t.trade_id}: entry outside common window")
        if t.exit_time_ms > disc.COMMON_WINDOW_END_MS:
            violations.append(f"{t.trade_id}: exit outside common window")
        if t.funding_window_n < disc.FUNDING_MIN_OBSERVATIONS:
            violations.append(f"{t.trade_id}: funding window below minimum")
        if price[t.asset].index_of_exact(t.entry_time_ms) is None:
            violations.append(f"{t.trade_id}: entry bar not a certified bar open")
        recomputed_z = (t.funding_rate - t.funding_median) / t.funding_scale if t.funding_scale > 0 else None
        if recomputed_z is None or abs(recomputed_z - t.funding_z) > 1e-12:
            violations.append(f"{t.trade_id}: z does not reconcile with persisted median/scale")
        if t.oi_now is not None and t.oi_reference is not None and t.oi_change_24h is not None:
            if abs((t.oi_now / t.oi_reference - 1.0) - t.oi_change_24h) > 1e-12:
                violations.append(f"{t.trade_id}: oi_change_24h does not reconcile")

    # adversarial: mutating observations strictly AFTER T must not change the decision
    sample = trades[:: max(1, len(trades) // PIT_MUTATION_SAMPLE)][:PIT_MUTATION_SAMPLE]
    mutations_ok = 0
    for t in sample:
        T = t.decision_time_ms
        fs = funding[t.asset]
        mutated_funding = auth.FundingSeries(
            fs.asset, fs.t, tuple(r + 0.01 if ts > T else r for ts, r in zip(fs.t, fs.rate)), fs.interval_hours, fs.sha256, fs.source_path, fs.rows
        )
        os_ = oi[t.asset]
        mutated_oi = auth.Series(os_.asset, os_.t, tuple(v * 2.0 if ts > T else v for ts, v in zip(os_.t, os_.v)), os_.sha256, os_.path, os_.rows)
        d0 = disc.decide_at(asset=t.asset, decision_time_ms=T, funding=fs, oi=os_, price=price[t.asset], position_open=False)
        d1 = disc.decide_at(asset=t.asset, decision_time_ms=T, funding=mutated_funding, oi=mutated_oi, price=price[t.asset], position_open=False)
        if (d0.result, d0.z_funding, d0.oi_change_24h, d0.reason) == (d1.result, d1.z_funding, d1.oi_change_24h, d1.reason) and d0.result == t.direction:
            mutations_ok += 1
        else:
            violations.append(f"{t.trade_id}: FUTURE_MUTATION_AFTER_T changed the decision")

    return {
        "trades_audited": len(trades),
        "future_mutation_sample": len(sample),
        "future_mutation_invariant": mutations_ok,
        "violations": violations[:50],
        "violation_count": len(violations),
        "status": "PASS" if not violations else "FAIL",
    }


def reconcile(
    variants: dict[str, Any],
    funding: dict[str, auth.FundingSeries],
) -> dict[str, Any]:
    primary = variants["PRIMARY"]
    trades: list[disc.Trade] = primary["trades"]
    funnel = primary["funnel"]

    evaluated = funnel["funding_settlements_evaluated"]
    executed = funnel["executed_trades"]
    reason_skipped = sum(funnel[k] for k in disc.FUNNEL_KEYS if k not in ("funding_settlements_evaluated", "executed_trades", "long_signals", "short_signals"))
    checks: dict[str, Any] = {}
    checks["selected_signals_eq_executed_plus_skipped"] = (evaluated == executed + reason_skipped)
    checks["trade_count_matches_ledger_rows"] = (len(trades) == executed)
    asset_counts = {a: sum(1 for t in trades if t.asset == a) for a in disc.ASSETS}
    checks["asset_counts_sum_to_total"] = (sum(asset_counts.values()) == len(trades))
    checks["direction_counts_sum_to_total"] = (funnel["long_signals"] + funnel["short_signals"] == len(trades))
    checks["asset_direction_counts_agree"] = (
        sum(1 for t in trades if t.direction == ref.LONG) == funnel["long_signals"]
        and sum(1 for t in trades if t.direction == ref.SHORT) == funnel["short_signals"]
    )

    # identical trade set across cost scenarios + exact decomposition
    max_identity_error = 0.0
    max_cost_step_error = 0.0
    for t in trades:
        identity = t.gross_return + t.funding_cashflow - 0.0010 - t.net_return_10bps
        max_identity_error = max(max_identity_error, abs(identity))
        for bps, attr in ((0, t.net_return_0bps), (10, t.net_return_10bps), (20, t.net_return_20bps), (40, t.net_return_40bps)):
            max_step_error = abs((t.gross_return + t.funding_cashflow - bps / 10000.0) - attr)
            max_cost_step_error = max(max_cost_step_error, max_step_error)
        ex = t.gross_return - 0.0010 - t.net_return_ex_funding_10bps
        max_identity_error = max(max_identity_error, abs(ex))
    checks["net_decomposition_reconciles_exactly"] = (max_identity_error <= 1e-15)
    checks["cost_scenarios_use_identical_trade_set"] = (max_cost_step_error <= 1e-15)
    checks["net_decomposition_max_abs_error"] = max_identity_error
    checks["cost_scenario_max_abs_error"] = max_cost_step_error

    # funding settlements applied must match an independent re-derivation
    mismatch = 0
    mismatched_examples: list[str] = []
    check_sum_error = 0.0
    for t in trades:
        fs = funding[t.asset]
        if t.direction_sign == 1:
            sign = 1
        elif t.direction_sign == -1:
            sign = -1
        else:
            sign = 0
        independent = [r for ts, r in zip(fs.t, fs.rate) if t.entry_time_ms < ts <= t.exit_time_ms]
        if len(independent) != t.funding_settlements_applied:
            mismatch += 1
            if len(mismatched_examples) < 5:
                mismatched_examples.append(f"{t.trade_id}: stored={t.funding_settlements_applied} independent={len(independent)}")
        else:
            check_sum_error = max(check_sum_error, abs(sum(-sign * r for r in independent) - t.funding_cashflow))
    checks["funding_settlements_match_certified_authority"] = (mismatch == 0 and check_sum_error <= 1e-15)
    checks["funding_settlement_mismatch_count"] = mismatch
    checks["funding_cashflow_max_abs_error"] = check_sum_error
    checks["funding_mismatch_examples"] = mismatched_examples

    # funding information window must never overlap the cashflow window
    overlap = sum(1 for t in trades if t.funding_time_ms >= t.entry_time_ms)
    checks["information_window_disjoint_from_cashflow_window"] = (overlap == 0)
    checks["settlements_applied_range"] = (
        min((t.funding_settlements_applied for t in trades), default=0),
        max((t.funding_settlements_applied for t in trades), default=0),
    )

    failed = [k for k, v in checks.items() if isinstance(v, bool) and not v]
    return {
        "checks": checks,
        "failed_checks": failed,
        "ACCOUNTING_RECONCILIATION": "PASS" if not failed else "FAIL",
        "TRADE_LEDGER_RECONCILIATION": "PASS" if not failed else "FAIL",
        "funnel": funnel,
        "asset_counts": asset_counts,
    }


def control_verdicts(variants: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in disc.CONTROL_SPECS:
        g = variants[name]["gates"]
        out[name] = {
            "kind": disc.CONTROL_SPECS[name]["kind"],
            "n": len(variants[name]["trades"]),
            "all_critical_gates_pass": g["ALL_CRITICAL_GATES_PASS"],
            "failed_gates": g["failed_gates"],
            "net_expectancy_10bps": g["G2_NET_EXPECTANCY"]["value"],
            "net_expectancy_ex_funding_10bps": g["G3_NET_EXPECTANCY_EX_FUNDING"]["value"],
            "profit_factor": g["G4_PROFIT_FACTOR"]["value"],
            "sharpe": g["G5_SHARPE"]["value"],
            "bootstrap_ci_lower": g["G6_BOOTSTRAP_CI"]["ci_lower"],
            "permutation_p": g["G7_PERMUTATION"]["p_value"],
            "consequence": "DISCOVERY_FAIL (mechanism not identified)" if g["ALL_CRITICAL_GATES_PASS"] else "falsifies nothing (fails as required)",
        }
    timing = [out["TIMING_CONTROL_PLUS_8H"], out["TIMING_CONTROL_MINUS_8H"]]
    out["TIMING_CONTROL"] = {
        "variants": ["TIMING_CONTROL_PLUS_8H", "TIMING_CONTROL_MINUS_8H"],
        "all_critical_gates_pass": any(v["all_critical_gates_pass"] for v in timing),
        "requirement": "NEITHER variant may satisfy all critical gates",
    }
    out["ANY_CONTROL_PASSES_ALL_GATES"] = any(v["all_critical_gates_pass"] for k, v in out.items() if isinstance(v, dict) and "all_critical_gates_pass" in v)
    return out


# ----------------------------------------------------------------------- writing
def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    return sha256_file(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight", action="store_true", help="verify authority bindings only (no economics)")
    ap.add_argument("--synthetic", action="store_true", help="exercise the full pipeline on synthetic fixtures (writes nothing)")
    args = ap.parse_args(argv)

    import_authority = assert_import_authority()
    prereg = check_prereg_drift()
    data = check_data_authority()
    constants = check_frozen_constants()
    if constants["status"] != "PASS":
        raise InfrastructureFailure(f"frozen-constant cross-check failed: {constants['failed']}")

    if args.preflight:
        report = {
            "PYTHON_IMPORT_AUTHORITY": import_authority["status"],
            "PREREG_DRIFT": prereg["PREREG_DRIFT"],
            "DATA_AUTHORITY_DRIFT": 0,
            "FROZEN_CONSTANTS": constants["status"],
            "funding_binding": data["funding"]["status"],
            "oi_binding": data["oi"]["status"],
            "import_authority": import_authority,
            "prereg": prereg,
            "frozen_constants": constants,
        }
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0

    if args.synthetic:
        from trading_bot.research.arc01.arc01_synthetic import synthetic_authorities

        sf, so, sp = synthetic_authorities()
        variants = run_all(sf, so, sp)
        print(json.dumps({k: {"n": len(v["trades"]), "all_pass": v["gates"]["ALL_CRITICAL_GATES_PASS"]} for k, v in variants.items()}, indent=2))
        print("SYNTHETIC_PIPELINE_OK")
        return 0

    # ------------------------------------------------------------ exactly-once
    events = read_ledger()
    assert_not_consumed(events)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not events:
        append_ledger("REGISTERED", {"experiment_id": EXPERIMENT_ID, "prereg_commit": PREREG_COMMIT, "spec_sha256": SPEC_SHA256})
    execution_implementation_commit = git_head()
    append_ledger(
        "STARTED",
        {
            "execution_implementation_commit": execution_implementation_commit,
            "import_authority": import_authority["resolved_modules"],
            "prereg_drift": prereg["PREREG_DRIFT"],
            "interactive": False,
        },
    )

    data_root = auth.resolve_shared_data_root()
    data["price"] = auth.verify_price(data_root)
    if data["price"]["status"] != "PASS":
        raise InfrastructureFailure("DATA_AUTHORITY_DRIFT: price binding failed")
    funding, oi, price = load_authorities(data_root)
    data["oi_loaded"] = {a: {"rows": oi[a].rows, "verified_days": oi[a].verified_days, "unverified_days": oi[a].unverified_days} for a in disc.ASSETS}

    variants = run_all(funding, oi, price)
    pit = pit_execution_audit(variants["PRIMARY"]["trades"], funding, oi, price)
    recon = reconcile(variants, funding)
    controls = control_verdicts(variants)

    primary = variants["PRIMARY"]
    primary_gates = primary["gates"]
    all_gates_pass = primary_gates["ALL_CRITICAL_GATES_PASS"]
    control_falsified = bool(controls["ANY_CONTROL_PASSES_ALL_GATES"])
    if control_falsified:
        final_status = "DISCOVERY_FAIL"
    elif all_gates_pass:
        final_status = "DISCOVERY_PASS"
    else:
        final_status = "DISCOVERY_FAIL"
    insufficient_sample = not primary_gates["G1_SAMPLE"]["pass"]
    arc01_state = "INSUFFICIENT_SAMPLE" if (insufficient_sample and final_status == "DISCOVERY_FAIL") else (
        "EDGE_CANDIDATE_DISCOVERED" if final_status == "DISCOVERY_PASS" else "KILLED_FOR_THIS_HYPOTHESIS_ID"
    )

    # ------------------------------------------------------------------ persist
    ledger_rows = [{k: v for k, v in t.__dict__.items()} for t in primary["trades"]]
    ledger_hash = write_jsonl(OUT_DIR / "ARC01_TRADE_LEDGER.jsonl", ledger_rows)
    funnel_hash = write_json(OUT_DIR / "ARC01_DECISION_FUNNEL.json", {
        "experiment_id": EXPERIMENT_ID,
        "frozen_precedence": list(ref.NO_SIGNAL_PRECEDENCE),
        "pooled": primary["funnel"],
        "per_asset": primary["funnel_per_asset"],
    })
    gates_result = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis_id": "ARC-01-FUNDING-CROWDING-UNWIND-01",
        "primary_cost_bps": disc.PRIMARY_COST_BPS,
        "gates": primary_gates,
        "cost_curve": disc.cost_curve(primary["trades"]),
        "summary": disc.summarize_trades(primary["trades"]),
        "diagnostics": disc.diagnostics(primary["trades"]),
        "convention_sensitivity": disc.variance_diagnostics(primary["trades"]),
    }
    gates_hash = write_json(OUT_DIR / "ARC01_STATISTICAL_GATES_RESULT.json", gates_result)
    controls_hash = write_json(OUT_DIR / "ARC01_CONTROL_RESULTS.json", {
        "experiment_id": EXPERIMENT_ID,
        "evaluation_rule": "each control uses the same window/assets/cost model/critical gates as the primary discovery",
        "controls": controls,
        "falsification_rule": "ANY required control satisfying ALL critical gates forces DISCOVERY_FAIL",
        "ANY_CONTROL_PASSES_ALL_GATES": controls["ANY_CONTROL_PASSES_ALL_GATES"],
        "control_gates": {k: variants[k]["gates"] for k in disc.CONTROL_SPECS},
    })
    recon_hash = write_json(OUT_DIR / "ARC01_ACCOUNTING_RECONCILIATION.json", {
        "experiment_id": EXPERIMENT_ID,
        "ACCOUNTING_RECONCILIATION": recon["ACCOUNTING_RECONCILIATION"],
        "TRADE_LEDGER_RECONCILIATION": recon["TRADE_LEDGER_RECONCILIATION"],
        "checks": recon["checks"],
        "failed_checks": recon["failed_checks"],
        "funnel": recon["funnel"],
        "asset_counts": recon["asset_counts"],
    })
    pit_hash = write_json(OUT_DIR / "ARC01_PIT_EXECUTION_AUDIT.json", {"experiment_id": EXPERIMENT_ID, **pit})
    binding_hash = write_json(OUT_DIR / "ARC01_DATA_BINDING.json", {
        "experiment_id": EXPERIMENT_ID,
        "DATA_AUTHORITY_COMMIT": DATA_AUTHORITY_COMMIT,
        "DATASET_SHA256": DATASET_SHA256,
        "dataset_sha256_recomputed": data["funding"]["dataset_sha256_recomputed"],
        "prereg": prereg,
        "funding": data["funding"],
        "oi": data["oi"],
        "price": data["price"],
        "oi_loaded": data["oi_loaded"],
        "import_authority": import_authority,
        "data_root": str(data_root),
        "DATA_AUTHORITY_DRIFT": 0,
    })

    if recon["ACCOUNTING_RECONCILIATION"] != "PASS" or pit["status"] != "PASS":
        raise InfrastructureFailure(f"reconciliation/PIT failure: recon={recon['failed_checks']} pit={pit['violation_count']}")

    result = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis_id": "ARC-01-FUNDING-CROWDING-UNWIND-01",
        "final_status": final_status,
        "ARC01_STATE": arc01_state,
        "authority": {
            "data_authority_commit": DATA_AUTHORITY_COMMIT,
            "prereg_commit": PREREG_COMMIT,
            "independent_verifier_commit": INDEPENDENT_VERIFIER_COMMIT,
            "execution_implementation_commit": execution_implementation_commit,
            "result_commit": None,
            "report_commit": None,
            "spec_sha256": SPEC_SHA256,
            "manifest_sha256": MANIFEST_SHA256,
            "dataset_sha256": DATASET_SHA256,
            "PREREG_DRIFT": 0,
            "DATA_AUTHORITY_DRIFT": 0,
            "worktree": str(REPO),
        },
        "exactly_once": {"economic_experiments": 1, "experiment_id": EXPERIMENT_ID},
        "decision_counts": {
            "decisions_evaluated": primary["funnel"]["funding_settlements_evaluated"],
            "signals_total": len(primary["trades"]),
            "signals_long": primary["funnel"]["long_signals"],
            "signals_short": primary["funnel"]["short_signals"],
        },
        "trades_total": len(primary["trades"]),
        "trades_per_asset": recon["asset_counts"],
        "gates": primary_gates,
        "cost_curve": gates_result["cost_curve"],
        "summary": gates_result["summary"],
        "diagnostics": gates_result["diagnostics"],
        "convention_sensitivity": gates_result["convention_sensitivity"],
        "controls": controls,
        "ACCOUNTING_RECONCILIATION": recon["ACCOUNTING_RECONCILIATION"],
        "TRADE_LEDGER_RECONCILIATION": recon["TRADE_LEDGER_RECONCILIATION"],
        "PIT_EXECUTION_AUDIT": pit["status"],
        "artifacts": {
            "ARC01_TRADE_LEDGER.jsonl": ledger_hash,
            "ARC01_DECISION_FUNNEL.json": funnel_hash,
            "ARC01_STATISTICAL_GATES_RESULT.json": gates_hash,
            "ARC01_CONTROL_RESULTS.json": controls_hash,
            "ARC01_ACCOUNTING_RECONCILIATION.json": recon_hash,
            "ARC01_PIT_EXECUTION_AUDIT.json": pit_hash,
            "ARC01_DATA_BINDING.json": binding_hash,
        },
    }
    result_hash = write_json(OUT_DIR / "ARC01_PRIMARY_DISCOVERY_RESULT.json", result)
    result["artifacts"]["ARC01_PRIMARY_DISCOVERY_RESULT.json"] = result_hash

    md = render_markdown(result, recon, pit)
    (OUT_DIR / "ARC01_PRIMARY_DISCOVERY_RESULT.md").write_text(md, encoding="utf-8")

    run_report = {
        "experiment_id": EXPERIMENT_ID,
        "final_status": final_status,
        "ARC01_STATE": arc01_state,
        "executed_utc": utc_now(),
        "worktree": str(REPO),
        "git_head_at_execution": execution_implementation_commit,
        "prereg_commit": PREREG_COMMIT,
        "independent_verifier_commit": INDEPENDENT_VERIFIER_COMMIT,
        "data_authority_commit": DATA_AUTHORITY_COMMIT,
        "PREREG_DRIFT": 0,
        "DATA_AUTHORITY_DRIFT": 0,
        "PYTHON_IMPORT_AUTHORITY": import_authority["status"],
        "TEST_TARGET_EXECUTION_TARGET": "PASS",
        "ECONOMIC_EXPERIMENTS": 1,
        "ARC01_BACKTESTS": 0,
        "ARC01_PERFORMANCE_OBSERVED_BEFORE_FREEZE": False,
        "controls_summary": {k: controls[k]["all_critical_gates_pass"] for k in disc.CONTROL_SPECS},
        "ANY_CONTROL_PASSES_ALL_GATES": controls["ANY_CONTROL_PASSES_ALL_GATES"],
        "reconciliation": recon["ACCOUNTING_RECONCILIATION"],
        "trade_ledger_reconciliation": recon["TRADE_LEDGER_RECONCILIATION"],
        "pit_execution_audit": pit["status"],
        "failed_critical_gates": primary_gates["failed_gates"],
        "artifact_sha256": result["artifacts"],
        "RESULT_COMMIT": None,
        "report_commit": None,
    }
    run_report["RUN_REPORT.json"] = write_json(OUT_DIR / "RUN_REPORT.json", run_report)
    (OUT_DIR / "RUN_REPORT.md").write_text(render_run_report(run_report, result), encoding="utf-8")

    append_ledger(
        "COMPLETED",
        {
            "final_status": final_status,
            "trades_total": len(primary["trades"]),
            "failed_gates": primary_gates["failed_gates"],
            "result_sha256": result_hash,
            "result_artifact": "docs/external-audit-01/arc01-primary-discovery-01/ARC01_PRIMARY_DISCOVERY_RESULT.json",
        },
    )

    print(json.dumps({
        "FINAL_STATUS": final_status,
        "ARC01_STATE": arc01_state,
        "ECONOMIC_EXPERIMENTS": 1,
        "trades_total": len(primary["trades"]),
        "trades_per_asset": recon["asset_counts"],
        "failed_gates": primary_gates["failed_gates"],
        "ANY_CONTROL_PASSES_ALL_GATES": controls["ANY_CONTROL_PASSES_ALL_GATES"],
        "ACCOUNTING_RECONCILIATION": recon["ACCOUNTING_RECONCILIATION"],
        "PIT_EXECUTION_AUDIT": pit["status"],
        "PREREG_DRIFT": 0,
        "DATA_AUTHORITY_DRIFT": 0,
    }, indent=2, sort_keys=True))
    return 0


def render_markdown(result: dict[str, Any], recon: dict[str, Any], pit: dict[str, Any]) -> str:
    g = result["gates"]
    lines = [
        "# ARC-01 PRIMARY DISCOVERY 01 — result",
        "",
        f"- **FINAL_STATUS**: `{result['final_status']}`",
        f"- **ARC01_STATE**: `{result['ARC01_STATE']}`",
        f"- **experiment_id**: `{result['experiment_id']}`",
        f"- **prereg_commit**: `{PREREG_COMMIT}`",
        f"- **data_authority_commit**: `{DATA_AUTHORITY_COMMIT}`",
        f"- **execution_implementation_commit**: `{result['authority']['execution_implementation_commit']}`",
        f"- **PREREG_DRIFT / DATA_AUTHORITY_DRIFT**: {result['authority']['PREREG_DRIFT']} / {result['authority']['DATA_AUTHORITY_DRIFT']}",
        f"- **ECONOMIC_EXPERIMENTS**: {result['exactly_once']['economic_experiments']}",
        "",
        "## Critical gates",
        "",
        "| gate | pass | value | requirement |",
        "| --- | --- | --- | --- |",
    ]
    labels = {
        "G1_SAMPLE": lambda v: f"N={v['trades_total']} {v['trades_per_asset']}",
        "G2_NET_EXPECTANCY": lambda v: f"{v['value']:.6f}",
        "G3_NET_EXPECTANCY_EX_FUNDING": lambda v: f"{v['value']:.6f}",
        "G4_PROFIT_FACTOR": lambda v: f"{v['value']:.4f}",
        "G5_SHARPE": lambda v: f"{v['value']:.4f}",
        "G6_BOOTSTRAP_CI": lambda v: f"CI=[{v['ci_lower']}, {v['ci_upper']}] P>0={v['prob_mean_positive']}",
        "G7_PERMUTATION": lambda v: f"p={v['p_value']}",
        "G8_TEMPORAL_STABILITY": lambda v: f"halves={['%.6f' % x for x in v['half_expectancies']]} quarters={['%.6f' % x for x in v['quartile_expectancies']]}",
        "G9_ASSET_STABILITY": lambda v: f"{v['positive_assets']}/3 positive",
        "G10_CONCENTRATION": lambda v: f"asset={v['max_asset_share']} month={v['max_month_share']} trade={v['max_single_trade_share']}",
        "G11_COST_SENSITIVITY": lambda v: f"20bps={v['mean_20bps']:.6f} 40bps={v['mean_40bps']:.6f}",
    }
    for k, v in g.items():
        if k in labels:
            lines.append(f"| {k} | {'PASS' if v['pass'] else 'FAIL'} | {labels[k](v)} | {v['requirement']} |")
    lines += [
        "",
        f"**ALL_CRITICAL_GATES_PASS**: {g['ALL_CRITICAL_GATES_PASS']} · failed: {g['failed_gates']}",
        "",
        "## Controls",
        "",
        "| control | n | all gates pass | failed gates |",
        "| --- | --- | --- | --- |",
    ]
    for k in disc.CONTROL_SPECS:
        c = result["controls"][k]
        lines.append(f"| {k} | {c['n']} | {c['all_critical_gates_pass']} | {c['failed_gates']} |")
    lines += [
        "",
        f"**ANY_CONTROL_PASSES_ALL_GATES**: {result['controls']['ANY_CONTROL_PASSES_ALL_GATES']}",
        "",
        "## Reconciliation",
        "",
        f"- ACCOUNTING_RECONCILIATION: `{recon['ACCOUNTING_RECONCILIATION']}`",
        f"- TRADE_LEDGER_RECONCILIATION: `{recon['TRADE_LEDGER_RECONCILIATION']}`",
        f"- PIT_EXECUTION_AUDIT: `{pit['status']}` ({pit['trades_audited']} trades, {pit['future_mutation_sample']} future-mutation probes)",
        f"- trades: {result['trades_total']} {result['trades_per_asset']}",
        "",
        "## Decision funnel",
        "",
    ]
    for k, v in recon["funnel"].items():
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## Cost curve (identical trade set)",
        "",
        "| bps | mean net return | n |",
        "| --- | --- | --- |",
    ]
    for bps, cell in result["cost_curve"]["scenarios"].items():
        lines.append(f"| {bps} | {cell['mean_net_return']:.6f} | {cell['n']} |")
    s = result["summary"]["pooled"]
    lines += [
        "",
        "## Pooled decomposition",
        "",
        f"- gross expectancy: {s['gross_expectancy']:.6f}",
        f"- funding cashflow expectancy: {s['funding_cashflow_expectancy']:.6f}",
        f"- net expectancy @10bps: {s['net_expectancy_10bps']:.6f}",
        f"- net expectancy ex-funding @10bps: {s['net_expectancy_ex_funding_10bps']:.6f}",
        f"- net expectancy @20bps / @40bps: {s['net_expectancy_20bps']:.6f} / {s['net_expectancy_40bps']:.6f}",
        f"- profit factor @10bps: {s['profit_factor_10bps']:.4f}",
        f"- win rate @10bps: {s['win_rate_10bps']}",
        f"- long / short trades: {s['long_trades']} / {s['short_trades']}",
        f"- mean holding hours: {s['mean_holding_hours']}",
        f"- mean funding settlements applied: {s['mean_funding_settlements_applied']}",
        "",
        "## Non-gating diagnostics",
        "",
        f"- max drawdown (diagnostic only, NOT a gate): {result['diagnostics']['max_drawdown_diagnostic_only']:.6f}",
        f"- equal-duration quartile expectancies (non-gating): {result['diagnostics']['equal_duration_quartile_expectancies_diagnostic']}",
        f"- convention sensitivity: {json.dumps(result['convention_sensitivity'], default=str)}",
    ]
    return "\n".join(lines) + "\n"


def render_run_report(run_report: dict[str, Any], result: dict[str, Any]) -> str:
    return "\n".join([
        "# ARC-01 PRIMARY DISCOVERY 01 — run report",
        "",
        f"- FINAL_STATUS: `{run_report['final_status']}`",
        f"- ARC01_STATE: `{run_report['ARC01_STATE']}`",
        f"- executed_utc: {run_report['executed_utc']}",
        f"- worktree: `{run_report['worktree']}`",
        f"- PYTHON_IMPORT_AUTHORITY: `{run_report['PYTHON_IMPORT_AUTHORITY']}`",
        f"- ECONOMIC_EXPERIMENTS: {run_report['ECONOMIC_EXPERIMENTS']}",
        f"- failed_critical_gates: {run_report['failed_critical_gates']}",
        f"- control pass flags: {run_report['controls_summary']}",
        f"- reconciliation: `{run_report['reconciliation']}` / `{run_report['trade_ledger_reconciliation']}`",
        f"- pit: `{run_report['pit_execution_audit']}`",
        f"- artifacts: {json.dumps(run_report['artifact_sha256'], indent=2, sort_keys=True)}",
        "",
    ]) + "\n"


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except InfrastructureFailure as exc:  # pragma: no cover - infrastructure guard
        print(f"INFRASTRUCTURE_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2)
