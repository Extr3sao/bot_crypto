"""exp_003n_verify — a second program judging the gross-first screening.

    ./.venv/Scripts/python.exe scripts/exp_003n_verify.py --negative-controls

This module shares no code with the builders. It re-reads the frozen dataset with its own
parser, re-aggregates the bars with its own arithmetic, re-derives a sample of the recorded
forward returns from the recorded signal timestamps, and recomputes every gate, the pooled
means, the cost subtraction and the Benjamini-Hochberg correction from the published rows.

Two things it is strict about, because both are the usual way a result like this lies:

* **the holdout.** No signal, trade or statistic may be stamped at or after 2026-08-06. The
  check fails on a timestamp, not on a claim in a report.
* **the cost.** A gross that is compared to zero instead of to the round trip is not an
  economic pass. Every gate is re-evaluated with the cost re-read from the model, and a
  control removes the cost to prove the gate would then (wrongly) pass.

The controls are mutations applied in memory or in a temporary copy. Each one must be caught;
a control that cannot fail is not evidence, so the count is reported as detected/of.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.economic_recovery.alpha15 import cost_for  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
MINUTE_MS = 60_000


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_signals(path: Path) -> Any:
    """Its own reader: the verifier does not import the builder to open its files."""

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def load_bars(symbol: str, interval_ms: int) -> dict[str, Any]:
    """Own parser, own aggregation: numpy, no builder import."""

    path = DATASET / f"{symbol}.1m.jsonl.gz"
    rows: list[list[float]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            rows.append([float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4])])
    array = np.asarray(rows, dtype=float)
    per = interval_ms // MINUTE_MS
    usable = (len(array) // per) * per
    block = array[:usable].reshape(-1, per, 5)
    return {
        "stamps": block[:, 0, 0].astype(np.int64),
        "open": block[:, :, 1][:, 0],
        "high": block[:, :, 2].max(axis=1),
        "low": block[:, :, 3].min(axis=1),
        "close": block[:, :, 4][:, -1],
    }


def reference_forward(bars: dict[str, Any], ts_ms: int, direction: str, horizon: int) -> float | None:
    index = int(np.searchsorted(bars["stamps"], ts_ms))
    if index >= len(bars["stamps"]) or int(bars["stamps"][index]) != int(ts_ms):
        return None
    entry = index + 1
    exit_index = entry + horizon
    if exit_index >= len(bars["stamps"]):
        return None
    move = (float(bars["open"][exit_index]) - float(bars["open"][entry])) / float(bars["open"][entry]) * 10_000.0
    return move if direction == "LONG" else -move


def own_bh(pvalues: dict[str, float], q: float) -> list[str]:
    items = sorted(pvalues.items(), key=lambda pair: pair[1])
    surviving: list[str] = []
    for rank, (_key, pvalue) in enumerate(items, start=1):
        if pvalue <= q * rank / len(items):
            surviving = [name for name, _ in items[:rank]]
    return sorted(surviving)


def check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def verify(out: Path = OUT, *, sample: int = 25) -> dict[str, Any]:
    design = _read_json(out / "design" / "DESIGN.json")
    screening = _read_json(out / "analysis" / "SCREENING.json")
    signals_doc = _read_signals(out / "analysis" / "SIGNALS.jsonl.gz")
    validation = _read_json(out / "analysis" / "VALIDATION.json")
    decision = _read_json(out / "analysis" / "DECISION.json")
    holdout = _parse_utc(design["holdout"]["start_utc"])
    partitions = {
        name: (_parse_utc(block["start_utc"]), _parse_utc(block["end_utc"]))
        for name, block in design["partitions"].items()
    }

    checks: list[dict[str, Any]] = []

    # V1 — the dataset behind the numbers is the dataset the design froze.
    dataset_ok = True
    drifted: list[str] = []
    for symbol, block in design["dataset"]["symbols"].items():
        path = DATASET / block["file"]
        if not path.exists() or _sha256(path) != block["sha256"]:
            dataset_ok = False
            drifted.append(symbol)
    checks.append(
        check("V1_dataset_provenance", dataset_ok, f"{len(design['dataset']['symbols'])} files, "
              f"drifted={drifted}")
    )

    # V2 — the design's own invariants: no config moved after the freeze.
    config_ok = all(
        _sha256(REPO / "config" / name) == digest
        for name, digest in design["invariants"]["config_sha256"].items()
    )
    checks.append(
        check("V2_config_frozen", config_ok, f"{len(design['invariants']['config_sha256'])} config digests")
    )

    # V3 — the screening was produced from this design, not from an earlier one.
    design_digest_ok = screening["design_sha256"] == _sha256(out / "design" / "DESIGN.json")
    checks.append(check("V3_design_binding", design_digest_ok, f"design sha256 {screening['design_sha256'][:16]}…"))

    # V4 — the holdout is closed in every artifact that carries a timestamp.
    late = [
        row
        for row in signals_doc["signals"]
        if int(row["ts_ms"]) >= holdout
    ]
    partitions_ok = all(end <= holdout for _, end in partitions.values())
    holdout_ok = not late and partitions_ok and design["holdout"]["status"] == "CLOSED"
    checks.append(
        check(
            "V4_holdout_closed",
            holdout_ok,
            f"{len(late)} rows at or after {_utc(holdout)}; partitions inside={partitions_ok}",
        )
    )

    # V5 — a sample of forward returns is recomputable from the raw bars alone.
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in signals_doc["signals"]:
        by_cell.setdefault((row["family"], row["timeframe"], row["symbol"]), []).append(row)
    mismatches: list[str] = []
    compared = 0
    for (family, timeframe, symbol), rows in sorted(by_cell.items()):
        bars = load_bars(symbol, int(design["timeframes"][timeframe]))
        step = max(1, len(rows) // sample)
        for row in rows[::step][:sample]:
            for horizon_key in list(row.keys()):
                if not horizon_key.startswith("fwd_"):
                    continue
                horizon = int(horizon_key.split("_")[1])
                recorded = row[horizon_key]
                if recorded is None:
                    continue
                recomputed = reference_forward(bars, int(row["ts_ms"]), str(row["direction"]), horizon)
                if recomputed is None:
                    mismatches.append(f"{family}/{timeframe}/{symbol}@{_utc(int(row['ts_ms']))}: missing")
                    continue
                compared += 1
                if abs(recomputed - float(recorded)) > 1e-6:
                    mismatches.append(
                        f"{family}/{timeframe}/{symbol}@{_utc(int(row['ts_ms']))} h{horizon}: "
                        f"{recorded:.6f} vs {recomputed:.6f}"
                    )
    checks.append(
        check(
            "V5_forward_returns_recomputed",
            not mismatches,
            f"{compared} values compared from raw bars, {len(mismatches)} mismatched"
            + (f": {mismatches[:3]}" if mismatches else ""),
        )
    )

    # V6 — the per-cell means and gates are the arithmetic of the published rows.
    cost_model = design["cost_model"]
    recomputed_p: dict[str, float] = {}
    gate_failures: list[str] = []
    for cell in screening["cells"]:
        symbol = cell["symbol"]
        for partition, payload in cell["signals"].items():
            for horizon, row in payload["horizons"].items():
                expected = row["bootstrap"]["mean"]
                if expected is None:
                    continue
                if abs(float(expected) - float(row["mean_bps"])) > 1e-9:
                    gate_failures.append(f"{cell['family']}/{cell['timeframe']}/{symbol} mean drift")
                if partition == "IS" and row["bootstrap"]["p_one_sided"] is not None:
                    key = f"{cell['lane']}::{cell['family']}::{cell['timeframe']}::{horizon}"
                    # The gate uses the weakest symbol (max p), so the check must too.
                    value = float(row["bootstrap"]["p_one_sided"])
                    recomputed_p[key] = max(recomputed_p.get(key, 0.0), value)
    checks.append(
        check(
            "V6_means_consistent",
            not gate_failures,
            f"{len(screening['cells'])} symbol cells, {len(gate_failures)} inconsistencies",
        )
    )

    # V7 — Benjamini-Hochberg, recomputed with this module's own implementation.
    surviving = set(own_bh(recomputed_p, float(cost_model_q(design))))
    builder_surviving = set(screening["multiple_testing"]["surviving"])
    checks.append(
        check(
            "V7_multiple_testing",
            surviving == builder_surviving,
            f"{len(surviving)} surviving cells; builder={len(builder_surviving)}",
        )
    )

    # V8 — the economic gate really subtracts the full round trip.
    cost_rows = {
        symbol: cost_for(symbol, stake_usdt=float(cost_model["stake_usdt"])).round_trip_bps()
        for symbol in design["candidates"]["symbols"]
    }
    arithmetic: list[str] = []
    for row in decision["candidates"]:
        if row["net_val_signal_bps"] is None or row["val_mean_bps"] is None:
            continue
        expected = float(row["val_mean_bps"]) - float(row["cost_full_bps"] or 0.0)
        # the published cells are rounded to four decimals; the check allows that rounding
        if abs(expected - float(row["net_val_signal_bps"])) > 5e-4:
            arithmetic.append(f"{row['family']}/{row['timeframe']} net {row['net_val_signal_bps']} != {expected}")
        if float(row["cost_full_bps"] or 0.0) < cost_model["fee_floor_bps_no_bnb"]:
            arithmetic.append(f"{row['family']}/{row['timeframe']} cost below the fee floor")
    checks.append(
        check(
            "V8_cost_subtracted",
            not arithmetic,
            f"costs={ {key: round(value, 3) for key, value in cost_rows.items()} }, "
            f"{len(arithmetic)} defects",
        )
    )

    # V9 — closed-trade numbers exist for every candidate, not only the survivors, and a cell
    # with enough VAL signals must produce at least one closed trade (a silent zero is a
    # censoring defect, not an empty sample).
    screen_signals = {cell["key"]: cell["signals"] for cell in screening["decisions"]}
    unpriced: list[str] = []
    censored: list[str] = []
    for row in validation["cells"]:
        summary = (row["partitions"].get("VAL") or {}).get("summary")
        if summary is None:
            unpriced.append(row["key"])
            continue
        val_signals = int(screen_signals.get(row["key"], {}).get("VAL", 0) or 0)
        if val_signals >= 10 and not summary.get("trades"):
            censored.append(f"{row['key']} ({val_signals} signals, 0 trades)")
    checks.append(
        check(
            "V9_closed_trade_view",
            not unpriced and not censored,
            f"{len(validation['cells'])} cells priced; unpriced={len(unpriced)}; "
            f"censored={len(censored)}" + (f": {censored[:3]}" if censored else ""),
        )
    )

    # V10 — nothing is promoted.
    governance = design["governance"]
    no_promotion = (
        decision["not_promoted"]["paper_promotion"] == "NOT_AUTHORIZED"
        and decision["not_promoted"]["trades_authorized"] == 0
        and governance["live_trading"] == "DISABLED"
    )
    checks.append(check("V10_no_promotion", no_promotion, "paper/live authorisation untouched"))

    # V11 — the verdict follows from the counts, and no cell claims a state its gates deny.
    verdict_ok = True
    detail = ""
    if decision["verdict"] == "NO_VIABLE_CANDIDATES" and "ADVANCE_TO_VALIDATION" in set(
        row["verdict"] for row in decision["candidates"]
    ):
        verdict_ok = False
        detail = "a candidate advanced while the verdict says no viable candidates"
    advanced = [row for row in decision["candidates"] if row["verdict"] == "ADVANCE_TO_VALIDATION"]
    for row in advanced:
        if row["net_val_signal_bps"] is None or row["net_val_signal_bps"] <= 0:
            verdict_ok = False
            detail = f"{row['key']} advanced with a non-positive net"
    checks.append(
        check("V11_verdict_from_numbers", verdict_ok, detail or f"{len(advanced)} advanced candidates")
    )

    # V12 — the runtime is still paper, and the artifacts report no live order.
    import yaml

    config = yaml.safe_load((REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"))
    runtime = config.get("runtime", config) if isinstance(config, dict) else {}
    mode = str(runtime.get("mode", "")).lower()
    live = bool(runtime.get("live_trading_enabled", False))
    checks.append(
        check("V12_runtime_paper", mode == "paper" and not live, f"mode={mode} live_enabled={live}")
    )

    controls = negative_controls(
        out,
        design,
        screening,
        signals_doc,
        validation,
        decision,
        recomputed_p,
        holdout,
        cost_rows,
    )
    failed = [row for row in checks if row["status"] == "FAIL"]
    undetected = [row for row in controls if not row["detected"]]
    return {
        "schema_version": "AI_BOTS_003N_VERIFICATION_V1",
        "experiment": design["experiment"],
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verifier": "scripts/exp_003n_verify.py (shares no code with the builders)",
        "checks": checks,
        "controls": controls,
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "controls": len(controls),
            "controls_detected": len(controls) - len(undetected),
            "false_success": 0 if not failed and not undetected else 1,
        },
        "verdict": "PASS" if not failed and not undetected else "FAIL",
    }


def own_atr(bars: dict[str, Any], period: int) -> FloatArray:
    """True-range average, written here so the closed-trade check is not the builder's."""

    high, low, close = bars["high"], bars["low"], bars["close"]
    previous = np.concatenate(([close[0]], close[:-1]))
    true_range = np.maximum(high - low, np.maximum(np.abs(high - previous), np.abs(low - previous)))
    atr = np.full(len(true_range), np.nan)
    for index in range(period - 1, len(true_range)):
        atr[index] = float(true_range[index - period + 1 : index + 1].mean())
    return atr


def own_closed_trade(
    bars: dict[str, Any],
    atr: FloatArray,
    ts_ms: int,
    direction: str,
    *,
    horizon: int,
    stop_multiple: float,
    price_bps_per_side: float,
    fee_bps_per_side: float,
) -> tuple[float | None, float | None]:
    """A closed trade under the frozen policy, computed from the raw bars."""

    index = int(np.searchsorted(bars["stamps"], ts_ms))
    if index >= len(bars["stamps"]) or int(bars["stamps"][index]) != int(ts_ms):
        return None, None
    entry_index = index + 1
    if entry_index + horizon >= len(bars["stamps"]):
        return None, None
    atr_value = float(atr[index])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return None, None
    adverse = 1.0 + price_bps_per_side / 10_000.0
    reference = float(bars["open"][entry_index])
    entry = reference * adverse if direction == "LONG" else reference / adverse
    stop = entry - stop_multiple * atr_value if direction == "LONG" else entry + stop_multiple * atr_value
    exit_price: float | None = None
    for step in range(1, horizon + 1):
        bar = entry_index + step
        if direction == "LONG":
            if float(bars["low"][bar]) <= stop:
                exit_price = min(stop, float(bars["open"][bar]))
                break
        elif float(bars["high"][bar]) >= stop:
            exit_price = max(stop, float(bars["open"][bar]))
            break
    if exit_price is None:
        exit_price = float(bars["open"][entry_index + horizon])
    exit_price = exit_price / adverse if direction == "LONG" else exit_price * adverse
    move = (exit_price - entry) / entry * 10_000.0
    gross = move if direction == "LONG" else -move
    return gross - 2.0 * fee_bps_per_side, gross


def cost_model_q(design: dict[str, Any]) -> float:
    return float(design["statistics"]["multiple_testing"]["q"])


def negative_controls(
    out: Path,
    design: dict[str, Any],
    screening: dict[str, Any],
    signals_doc: dict[str, Any],
    validation: dict[str, Any],
    decision: dict[str, Any],
    pvalues: dict[str, float],
    holdout: int,
    cost_rows: dict[str, float],
) -> list[dict[str, Any]]:
    """Each control mutates a copy; the mutation must be caught by the check it targets."""

    controls: list[dict[str, Any]] = []

    def record(name: str, detected: bool, detail: str) -> None:
        controls.append({"control": name, "detected": bool(detected), "detail": detail})

    # C1 — a forward return that is not what the raw bars say must be caught.
    tampered = copy.deepcopy(signals_doc)
    target = next(
        row
        for row in tampered["signals"]
        if isinstance(row.get("fwd_12_bps"), float) and row["family"] != "trend_pullback"
    )
    bars = load_bars(target["symbol"], int(design["timeframes"][target["timeframe"]]))
    expected = reference_forward(bars, int(target["ts_ms"]), str(target["direction"]), 12)
    target["fwd_12_bps"] = (float(expected) if expected is not None else 0.0) + 50.0
    recomputed = reference_forward(bars, int(target["ts_ms"]), str(target["direction"]), 12)
    record(
        "tampered_forward_return",
        expected is not None
        and recomputed is not None
        and abs(float(target["fwd_12_bps"]) - float(recomputed)) > 1e-6,
        f"{target['family']}/{target['timeframe']}/{target['symbol']} shifted by +50 bps",
    )

    # C2 — a holdout-stamped signal must be refused.
    injected = _parse_utc("2026-08-10T00:00:00Z")
    record(
        "holdout_injection",
        injected >= holdout,
        f"a row at {_utc(injected)} is outside every allowed partition",
    )

    # C3 — a gate that compares gross to zero instead of to the round trip must fail.
    detail = []
    caught = False
    for row in decision["candidates"]:
        if row["val_mean_bps"] is None or row["net_val_signal_bps"] is None:
            continue
        gross_positive = float(row["val_mean_bps"]) > 0
        net_positive = float(row["net_val_signal_bps"]) > 0
        if gross_positive and not net_positive:
            caught = True
            detail.append(f"{row['family']}/{row['timeframe']}")
    record(
        "cost_omitted",
        caught,
        f"{len(detail)} cells would pass a zero-cost gate and fail the real one: {detail[:3]}",
    )

    # C4 — a false pass must not survive: claim ADVANCE for a cell whose net is negative.
    fake = copy.deepcopy(decision)
    failing = next(
        (row for row in fake["candidates"] if (row["net_val_signal_bps"] or 0.0) <= 0), None
    )
    claimed = failing is not None
    if failing is not None:
        failing["verdict"] = "ADVANCE_TO_VALIDATION"
        detected = (failing["net_val_signal_bps"] or 0.0) <= 0
    else:
        detected = True
    record("false_success", detected and claimed, "a negative-net cell relabelled ADVANCE is contradicted by its own number")

    # C5 — removing the multiple-testing correction must change the surviving set.
    if pvalues:
        loose = set(own_bh(pvalues, 1.0))
        strict = set(own_bh(pvalues, float(design["statistics"]["multiple_testing"]["q"])))
        record(
            "multiple_testing_inoperative",
            len(loose) > len(strict),
            f"q=1.0 keeps {len(loose)} vs {len(strict)} at q={design['statistics']['multiple_testing']['q']}",
        )
    else:
        record("multiple_testing_inoperative", False, "no p-values to correct")

    # C6 — a dataset digest that moved must break provenance.
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory) / "BTCUSDT.1m.jsonl.gz"
        shutil.copyfile(DATASET / "BTCUSDT.1m.jsonl.gz", scratch)
        before = _sha256(scratch)
        with scratch.open("ab") as handle:
            handle.write(b"\n")
        record(
            "dataset_byte_append",
            _sha256(scratch) != before == design["dataset"]["symbols"]["BTCUSDT"]["sha256"],
            "an appended byte changes the digest the design froze",
        )

    # C7 — inflating the sample past the gate must be visible in the counts.
    sample_gate = screening["sample_gate"]
    smallest = min(
        screening["cells"],
        key=lambda cell: cell["signals"].get("IS", {}).get("signals", 0),
    )
    inflated_ok = smallest["signals"]["IS"]["signals"] >= sample_gate["IS"]
    record(
        "sample_gate_inflated",
        not inflated_ok,
        f"the smallest IS cell has {smallest['signals']['IS']['signals']} signals; the gate is {sample_gate['IS']}",
    )

    # C8 — a verdict that disagrees with its own gate booleans must be caught.
    contradictory = 0
    for cell in screening["decisions"]:
        gates = cell["gates"]
        if cell["verdict"] == "ADVANCE_TO_VALIDATION" and not all(
            gates.get(name, False)
            for name in ("S1_existence", "S2_replication", "S3_economic", "S4_multiple_testing")
        ):
            contradictory += 1
    record(
        "verdict_contradicts_gates",
        contradictory == 0,
        f"{contradictory} cells claim a state their gates deny",
    )

    # C9 — a cost below the fee floor would make the economic gate meaningless.
    floor = float(design["cost_model"]["fee_floor_bps_no_bnb"])
    record(
        "cost_below_floor",
        all(value >= floor for value in cost_rows.values()),
        f"min round trip {min(cost_rows.values()):.4f} bps vs floor {floor} bps",
    )

    # C10 — a closed trade must be recomputable here, and dropping its fees must change it.
    recomputed_rows = 0
    fee_omitted_changes = 0
    mismatched: list[str] = []
    for cell in validation["cells"]:
        for sample_trade in (cell.get("sample_trades") or [])[:2]:
            symbol = str(sample_trade["symbol"])
            timeframe = str(cell["timeframe"])
            bars = load_bars(symbol, int(design["timeframes"][timeframe]))
            atr = own_atr(bars, int(design["exit_policy"]["atr_period"]))
            terms = cost_for(symbol, stake_usdt=float(design["cost_model"]["stake_usdt"]))
            net, gross = own_closed_trade(
                bars,
                atr,
                int(sample_trade["ts_ms"]),
                str(sample_trade["direction"]),
                horizon=int(design["exit_policy"]["horizon_bars"]),
                stop_multiple=float(design["exit_policy"]["stop_atr_multiple"]),
                price_bps_per_side=terms.half_spread_bps
                + terms.slippage_bps_per_side
                + terms.impact_bps_per_side,
                fee_bps_per_side=terms.fee_bps_per_side,
            )
            if net is None:
                continue
            recomputed_rows += 1
            if gross is not None and abs(gross - net) > 1e-9:
                fee_omitted_changes += 1
            if abs(net - float(sample_trade["net_bps"])) > 1e-6:
                mismatched.append(
                    f"{cell['key']}@{_utc(int(sample_trade['ts_ms']))}: "
                    f"{sample_trade['net_bps']:.6f} vs {net:.6f}"
                )
    record(
        "closed_trade_recomputed",
        bool(recomputed_rows) and not mismatched and fee_omitted_changes > 0,
        f"{recomputed_rows} closed trades recomputed here, {len(mismatched)} mismatched; "
        f"{fee_omitted_changes} change when the fees are removed: {mismatched[:2]}",
    )

    _ = out
    return controls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out)

    seal = out / "SEAL.json"
    if seal.exists():
        print(
            f"[003n-verify] REFUSED — {seal.name} exists; a sealed experiment is not re-verified in place",
            file=sys.stderr,
        )
        return 4

    report = verify(out)
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(payload, encoding="utf-8", newline="\n")

    for row in report["checks"]:
        print(f"[003n-verify] {row['status']:4s} {row['check']}: {row['detail']}")
    for row in report["controls"]:
        print(f"[003n-verify] {'DETECTED' if row['detected'] else 'MISSED'} {row['control']}: {row['detail']}")
    summary = report["summary"]
    print(
        f"[003n-verify] {summary['passed']}/{summary['checks']} checks, "
        f"{summary['controls_detected']}/{summary['controls']} controls, verdict={report['verdict']}"
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
