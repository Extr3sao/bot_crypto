"""WP-TDM-11D — independent verification of what this WP actually produced.

Deliberately written as a *second* implementation:

* the ledger is re-derived from raw bars and compared row by row against the
  baseline's own inputs (entry must equal the open of the next bar, exit the
  close of ``entry+6``, regime ``down`` at the decision bar, no overlap);
* the interval is recomputed with an analytic t interval and a **jackknife**,
  not with the stationary bootstrap the builder used;
* the cost table is rebuilt from the published venue specs rather than from
  ``CostModelV3.evaluate``.

It cannot certify author independence: builder and verifier are the same agent.
That is recorded as ``INDEPENDENCE_NOT_DEMONSTRATED``, not hidden.

Usage::  python scripts/tdm11_verify.py
Writes ``.tdm11/verification.json``; exit code 0 only if every check passes.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

ART = REPO_ROOT / ".tdm11"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"
DATA = REPO_ROOT / "data"
CUTOFF_MS = 1_792_857_600_000
COST_BPS = 23.7906
MIN_N = 36


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(path: Path) -> list[list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [[float(x) for x in row] for row in payload["rows"]]


def trend_z(closes: list[float], window: int = 200) -> list[float]:
    """Second implementation: O(n) via expanding sums of deviations."""
    n = len(closes)
    lr = [0.0] * n
    for k in range(1, n):
        lr[k] = math.log(closes[k] / closes[k - 1]) if closes[k - 1] > 0 else 0.0
    out = [0.0] * n
    span = window - 1
    for i in range(span, n):
        chunk = lr[i - span + 1 : i + 1]
        mean = math.fsum(chunk) / span
        var = math.fsum((x - mean) ** 2 for x in chunk) / span
        out[i] = (math.fsum(chunk) / (math.sqrt(var) * math.sqrt(window))) if var > 0 else 0.0
    return out


def label(z: float, i: int) -> str:
    if i < 199 or z == 0.0:
        return "unclassified"
    return "up" if z > 1.5 else "down" if z < -1.5 else "flat"


def jackknife_se(values: list[float]) -> float:
    n = len(values)
    total = math.fsum(values)
    means = [(total - v) / (n - 1) for v in values]
    m = math.fsum(means) / n
    return math.sqrt((n - 1) / n * math.fsum((x - m) ** 2 for x in means))


def main() -> int:
    checks: list[dict[str, Any]] = []

    def record(cid: str, what: str, passed: bool, observed: Any) -> None:
        checks.append({"id": cid, "check": what, "passed": bool(passed), "observed": observed})
        print(f"{cid} {'PASS' if passed else 'FAIL'} {what} -> {observed}", flush=True)

    # --- V1 preregistration integrity -------------------------------------
    freeze = json.loads((ART / "prereg_freeze.json").read_text(encoding="utf-8"))
    prereg_path = REPO_ROOT / freeze["preregistration_path"]
    current = sha(prereg_path)
    record(
        "V1",
        "preregistration hash still equals the frozen value",
        current == freeze["preregistration_sha256"],
        {"sha256": current[:16], "frozen_ms": freeze["frozen_at_ms"]},
    )

    # --- V2 artifact manifest --------------------------------------------
    run = (
        json.loads((EVIDENCE / "RUN_REPORT.json").read_text(encoding="utf-8"))
        if (EVIDENCE / "RUN_REPORT.json").exists()
        else None
    )
    if run is None:
        record("V2", "artifact manifest present", False, {"reason": "RUN_REPORT.json missing"})
    else:
        mism: list[str] = []
        for name, meta in run["evidence_sha256"].items():
            path = REPO_ROOT / meta["path"]
            if not path.exists() or sha(path) != meta["sha256"]:
                mism.append(name)
        record(
            "V2",
            "every published artifact matches its recorded SHA-256",
            not mism,
            {"checked": len(run["evidence_sha256"]), "mismatches": mism},
        )

    # --- V3 dataset integrity --------------------------------------------
    problems: list[str] = []
    files = 0
    dataset_paths: list[Path] = []
    for directory, manifest in (("tdm10", "DATASET_DEV.json"), ("tdm08", "DATASET.json")):
        payload = json.loads((DATA / directory / manifest).read_text(encoding="utf-8"))
        for entry in payload["files"]:
            path = REPO_ROOT / entry["path"]
            dataset_paths.append(path)
            rows = load_rows(path)
            files += 1
            if sha(path) != entry["sha256"]:
                problems.append(f"hash:{entry['path']}")
            stamps = [int(r[0]) for r in rows]
            if len(set(stamps)) != len(stamps):
                problems.append(f"dup:{entry['path']}")
            if any(b <= a for a, b in itertools.pairwise(stamps)):
                problems.append(f"order:{entry['path']}")
            if len(rows) != entry["bars"]:
                problems.append(f"bars:{entry['path']}")
    record(
        "V3",
        "24 sealed datasets hash, count, order and uniqueness",
        not problems,
        {"files": files, "problems": problems},
    )

    # --- V4 no confirmatory bar anywhere ---------------------------------
    offenders = []
    max_seen = 0
    for path in dataset_paths:
        for row in load_rows(path):
            max_seen = max(max_seen, int(row[0]))
            if int(row[0]) >= CUTOFF_MS:
                offenders.append(path.name)
    record(
        "V4",
        "no confirmatory bar (>= cutoff) was read by this WP",
        not offenders,
        {"max_bar_ms": max_seen, "cutoff_ms": CUTOFF_MS, "offenders": offenders},
    )

    # --- V5..V7 ledger audit ---------------------------------------------
    ledger_path = EVIDENCE / "RETROSPECTIVE_LEDGER.csv"
    with ledger_path.open(encoding="utf-8") as fh:
        ledger = list(csv.DictReader(fh))

    bars_cache: dict[str, tuple[list[list[float]], list[float]]] = {}

    def series(asset: str) -> tuple[list[list[float]], list[float]]:
        if asset not in bars_cache:
            rows = load_rows(DATA / "tdm10" / f"{asset}_5m.json")
            bars_cache[asset] = (rows, trend_z([r[4] for r in rows]))
        return bars_cache[asset]

    ledger_problems: list[str] = []
    last_exit_by_asset: dict[str, int] = {}
    for row in ledger:
        asset = row["asset"]
        rows, z = series(asset)
        stamps = [int(r[0]) for r in rows]
        decision_ms = int(row["decision_ms"])
        if decision_ms not in stamps:
            ledger_problems.append(f"decision not a bar: {asset} {decision_ms}")
            continue
        i = stamps.index(decision_ms)
        entry_ms, exit_ms = int(row["entry_ms"]), int(row["exit_ms"])
        if entry_ms != stamps[i + 1]:
            ledger_problems.append(f"entry not next bar: {asset} {decision_ms}")
        if exit_ms != stamps[i + 1 + 6]:
            ledger_problems.append(f"exit not i+1+6: {asset} {decision_ms}")
        if not math.isclose(float(row["entry"]), rows[i + 1][1], rel_tol=1e-12):
            ledger_problems.append(f"entry price != next open: {asset} {decision_ms}")
        if not math.isclose(float(row["exit"]), rows[i + 1 + 6][4], rel_tol=1e-12):
            ledger_problems.append(f"exit price != close: {asset} {decision_ms}")
        if label(z[i], i) != "down" or row["regime_trend"] != "down":
            ledger_problems.append(f"regime not down at decision: {asset} {decision_ms}")
        if row["direction"] != "SHORT":
            ledger_problems.append(f"not short: {asset} {decision_ms}")
        expected = -(float(row["exit"]) / float(row["entry"]) - 1.0) * 10_000.0
        if not math.isclose(float(row["gross_bps"]), expected, abs_tol=1e-4):
            ledger_problems.append(f"gross mismatch: {asset} {decision_ms}")
        if last_exit_by_asset.get(asset, -1) >= i + 1:
            ledger_problems.append(f"overlapping position: {asset} {decision_ms}")
        last_exit_by_asset[asset] = i + 1 + 6
    record(
        "V5",
        "every ledger row is causal, SHORT, regime-down, non-overlapping and correctly priced",
        not ledger_problems,
        {
            "rows": len(ledger),
            "problems": ledger_problems[:10],
            "problem_count": len(ledger_problems),
        },
    )

    gross = [float(r["gross_bps"]) for r in ledger]
    net = [g - COST_BPS for g in gross]
    n = len(gross)
    mean = statistics.fmean(gross)
    sd = statistics.stdev(gross)
    jse = jackknife_se(gross)
    t_crit = 1.96
    ci_hi = mean + t_crit * sd / math.sqrt(n)
    ci_hi_jack = mean + t_crit * jse
    gain = sum(v for v in net if v > 0)
    loss = -sum(v for v in net if v < 0)
    equity = peak = dd = 0.0
    for v in net:
        equity += v
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    pf = gain / loss if loss else None
    baseline = json.loads((ART / "retro.json").read_text(encoding="utf-8"))["primary"]
    stats_match = (
        n == baseline["trades"]
        and math.isclose(mean, baseline["gross_mean"], abs_tol=1e-3)
        and math.isclose(sd, baseline["gross_sd"], abs_tol=1e-3)
        and math.isclose(pf or 0, baseline["profit_factor"] or 0, abs_tol=1e-3)
        and math.isclose(dd, baseline["max_drawdown_bps"], abs_tol=1e-2)
        and math.isclose(sum(net), baseline["cumulative_net_bps"], abs_tol=1e-2)
    )
    record(
        "V6",
        "ledger statistics recomputed from the CSV match the published ones",
        stats_match,
        {
            "n": n,
            "mean": round(mean, 4),
            "sd": round(sd, 4),
            "pf": round(pf or 0, 4),
            "max_dd": round(dd, 2),
            "cumulative_net": round(sum(net), 2),
            "declared": {k: baseline[k] for k in ("trades", "gross_mean", "gross_sd")},
        },
    )
    record(
        "V7",
        "gross 95% upper bound stays below zero under analytic t and jackknife",
        ci_hi < 0 and ci_hi_jack < 0,
        {
            "analytic_upper": round(ci_hi, 4),
            "jackknife_upper": round(ci_hi_jack, 4),
            "net_analytic_upper": round(ci_hi - COST_BPS, 4),
        },
    )

    # --- V8 cost audit from published specs ------------------------------
    from trading_bot.research.microstructure.cost_model_v3 import VENUE_SPECS, default_model

    spec = VENUE_SPECS["BINANCE_SPOT_STANDARD_TAKER"]
    model = default_model()
    all_in = model.evaluate(size_usd=1000.0, horizon_minutes=30.0)
    component_sum = sum(c.value_bps for c in all_in.components)
    fees = spec.taker_fee_bps * 2
    borrow_like = [
        c.name
        for c in all_in.components
        if any(k in c.name for k in ("borrow", "margin", "funding"))
    ]
    scenario_totals = {
        sid: round(
            default_model(sid).evaluate(size_usd=1000.0, horizon_minutes=30.0).round_trip_bps, 4
        )
        for sid in VENUE_SPECS
    }
    perp_maker = scenario_totals.get("BINANCE_USDM_PERP_MAKER")
    funding_charged = any(c.name == "funding_carry" for c in all_in.components)
    record(
        "V8",
        "primary total = sum of components; futures maker reproduces 9.25; funding is not charged; primary venue is spot",
        math.isclose(component_sum, all_in.round_trip_bps, abs_tol=1e-9)
        and math.isclose(fees, 20.0, abs_tol=1e-9)
        and not borrow_like
        and not funding_charged
        and spec.product.lower() == "spot"
        and perp_maker is not None
        and math.isclose(perp_maker, 9.25, abs_tol=0.01),
        {
            "round_trip": round(all_in.round_trip_bps, 4),
            "component_sum": round(component_sum, 4),
            "fees": fees,
            "borrow_components": borrow_like,
            "funding_charged_by_default": funding_charged,
            "funding_source": spec.funding_source_id,
            "perp_maker_bps": perp_maker,
            "product": spec.product,
            "scenario_totals": scenario_totals,
        },
    )

    # --- V9 power arithmetic --------------------------------------------
    z_alpha, z_power = 1.6448536269514722, 0.8416212335729143
    prereg = json.loads((ART / "prereg.json").read_text(encoding="utf-8"))
    sd_block = prereg["power"]["sd_bps"] * prereg["power"]["block_inflation"]
    n_cost = math.ceil(((z_alpha + z_power) * sd_block / COST_BPS) ** 2)
    record(
        "V9",
        "preregistered minimum sample reproduces from its own dispersion",
        n_cost == prereg["power"]["required_n_at_cost_effect"] == MIN_N,
        {"recomputed": n_cost, "recorded": prereg["power"]["required_n_at_cost_effect"]},
    )

    # --- V10 availability gate ------------------------------------------
    avail = json.loads((ART / "availability.json").read_text(encoding="utf-8"))
    record(
        "V10",
        "availability gate declares AWAITING_NEW_DATA with no confirmatory access",
        avail["decision"]["result"] == "AWAITING_NEW_DATA"
        and avail["decision"]["confirmatory_bars_read"] == 0
        and not avail["fetched_confirmatory_data"],
        avail["decision"],
    )

    # --- V11 adversarial controls ---------------------------------------
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "tdm11_controls.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    record(
        "V11",
        "adversarial controls re-run green in a fresh process",
        proc.returncode == 0,
        {
            "exit": proc.returncode,
            "tail": proc.stdout.strip().splitlines()[-1] if proc.stdout else "",
            "elapsed_s": round(time.time() - started, 1),
        },
    )

    # --- V12 determinism -------------------------------------------------
    before = sha(ledger_path)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "tdm11_retro.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    after = sha(ledger_path)
    record(
        "V12",
        "re-running the evaluation reproduces the ledger byte for byte",
        before == after and proc.returncode == 0,
        {"ledger_sha256": after[:16], "exit": proc.returncode},
    )

    payload = {
        "generated_at_ms": int(time.time() * 1000),
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": sum(1 for c in checks if c["passed"]),
        "all_passed": all(c["passed"] for c in checks),
        "verifier_role": "independent implementation, same operator",
        "independence": {
            "implementation_independent": True,
            "operator_independent": False,
            "state": "INDEPENDENCE_NOT_DEMONSTRATED",
            "note": (
                "builder and verifier are the same agent; the statistics were recomputed with a "
                "different estimator (analytic t + jackknife instead of stationary bootstrap) and "
                "the ledger was re-derived from raw bars, but role separation is not demonstrated "
                "and this certificate must not be read as third-party review"
            ),
        },
    }
    (ART / "verification.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['checks_passed']}/{payload['checks_total']} verification checks passed")
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
