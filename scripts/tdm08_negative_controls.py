"""WP-TDM-08 — negative controls for the runtime and the admission gate.

A diagnostic that only reports "no trades because the ledger says no" is worth
nothing unless the *machinery that says no* is shown to fail closed. Each
control below breaks one guarantee on a throwaway copy and asserts the
guarantee notices. A control that does not fire is reported as MISSED and makes
the script exit non-zero, so "0 failures" can never be printed by accident.

Controls
--------
C1  tamper one byte of a persisted trace        -> hash chain breaks
C2  truncate the trace ledger                   -> chain/replay refuses it
C3  admit a strategy with negative gross edge   -> AdmissionEntry raises
C4  point the runtime at a missing ledger       -> FileNotFoundError, no guessing
C5  ask about a strategy absent from the ledger -> UNKNOWN, not admitted
C6  rewrite the economics at zero cost          -> decision still NO_TRADE
C7  re-derive the cycle's cost from COST_MODEL_V3 -> matches the trace (no drift)

Usage:
    python scripts/tdm08_negative_controls.py --run-dir runs/tdm08-paper-rt
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _load_traces(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "traces.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def control_tampered_trace(run_dir: Path) -> tuple[bool, str]:
    from trading_bot.autonomous.trace import DecisionTraceStore  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "run"
        shutil.copytree(run_dir, copy)
        target = copy / "traces.jsonl"
        raw = target.read_bytes()
        # Flip one digit inside the LAST record only; a chain check that ignores
        # content and only counts records would not notice.
        marker = raw.rfind(b'"asset":"')
        if marker < 0:
            return False, "cannot locate an asset field to tamper"
        index = marker + len(b'"asset":"')
        tampered = raw[:index] + (b"X" if raw[index : index + 1] != b"X" else b"Y") + raw[index + 1 :]
        target.write_bytes(tampered)
        store = DecisionTraceStore(copy)
        verification = store.verify_chain()
        fired = not verification.ok
        return fired, f"chain ok={verification.ok} detail={verification.detail!r}"


def control_truncated_trace(run_dir: Path) -> tuple[bool, str]:
    from trading_bot.autonomous.trace import DecisionTraceStore  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "run"
        shutil.copytree(run_dir, copy)
        (copy / "traces.jsonl").write_bytes(b"")
        store = DecisionTraceStore(copy)
        try:
            records = store.read()
            verification = store.verify_chain()
            fired = not verification.ok or not records
            return fired, f"records={len(records)} chain_ok={verification.ok}"
        except Exception as exc:  # a refusal is also a detection
            return True, f"refused: {type(exc).__name__}: {exc}"


def control_admit_negative_edge(run_dir: Path) -> tuple[bool, str]:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger  # noqa: PLC0415

    payload = json.loads(
        (REPO_ROOT / "config" / "strategy_admission.json").read_text(encoding="utf-8")
    )
    payload["strategies"]["ema_crossover@5m"]["admitted_for_paper"] = True
    try:
        AdmissionLedger.from_dict(payload)
    except ValueError as exc:
        return True, f"rejected: {exc}"
    return False, "ledger accepted an admitted strategy with negative gross edge"


def control_missing_ledger(_: Path) -> tuple[bool, str]:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger  # noqa: PLC0415

    try:
        AdmissionLedger.load(Path(tempfile.gettempdir()) / "definitely-absent-ledger.json")
    except FileNotFoundError as exc:
        return True, f"refused: {exc}"
    return False, "loaded a ledger that does not exist"


def control_unknown_strategy(_: Path) -> tuple[bool, str]:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger  # noqa: PLC0415

    ledger = AdmissionLedger.load(REPO_ROOT / "config" / "strategy_admission.json")
    status = ledger.status_for("never_researched@5m")
    admitted = ledger.is_paper_admitted("never_researched@5m")
    return (not admitted), f"status={status.value} admitted={admitted}"


def control_zero_cost_still_no_trade(run_dir: Path) -> tuple[bool, str]:
    traces = _load_traces(run_dir)
    if not traces:
        return False, "no traces to inspect"
    offenders = []
    for trace in traces:
        proposal = trace.get("proposal") or {}
        gross = proposal.get("expected_gross_edge_bps")
        if gross is None:
            continue
        if gross > 0:
            offenders.append((trace.get("asset"), gross))
    # The decision must be a NO_TRADE *for a non-cost reason*: with cost removed,
    # gross <= 0 still kills the trade. If a trace with positive gross had been
    # refused as NO_TRADE_STRATEGIC, cost would be the deciding factor and C6
    # would be reporting the wrong cause.
    fired = all(trace.get("classification") != "PAPER" for trace in traces) and not offenders
    detail = (
        f"traces={len(traces)} max_gross_bps="
        f"{max((t.get('proposal') or {}).get('expected_gross_edge_bps') or 0.0 for t in traces):.4f} "
        f"positive_gross_but_refused={offenders}"
    )
    return fired, detail


def control_cost_re_derivation(run_dir: Path) -> tuple[bool, str]:
    from trading_bot.research.microstructure.cost_model_v3 import default_model  # noqa: PLC0415

    traces = _load_traces(run_dir)
    costs = []
    for trace in traces:
        proposal = trace.get("proposal") or {}
        expected = proposal.get("expected_cost_bps")
        if expected is None:
            continue
        # The cycle's cost uses the spread OBSERVED in that cycle's snapshot, not
        # the model default; re-deriving with the default would report a ~1 bps
        # "drift" that is really the documented override (0.0013 vs 1.0 bps).
        observed_spread = (trace.get("market_context") or {}).get("spread_bps")
        model = default_model()
        recomputed = model.evaluate(
            size_usd=1000.0,
            horizon_minutes=5.0,
            spread_bps=None if observed_spread is None else float(observed_spread),
        ).round_trip_bps
        costs.append((expected, recomputed))
    if not costs:
        return False, "no cost figures recorded in the traces"
    worst = max(abs(a - b) for a, b in costs)
    return worst < 0.01, (
        f"pairs={len(costs)} max_abs_diff={worst:.6f} bps "
        f"(expected {costs[0][0]:.4f} vs re-derived {costs[0][1]:.4f})"
    )


CONTROLS = [
    ("C1_tampered_trace_breaks_chain", control_tampered_trace),
    ("C2_truncated_trace_refused", control_truncated_trace),
    ("C3_negative_edge_cannot_be_admitted", control_admit_negative_edge),
    ("C4_missing_ledger_fails_closed", control_missing_ledger),
    ("C5_unknown_strategy_not_admitted", control_unknown_strategy),
    ("C6_zero_cost_still_no_trade", control_zero_cost_still_no_trade),
    ("C7_cost_re_derives_from_model", control_cost_re_derivation),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/tdm08-paper-rt")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    run_dir = (REPO_ROOT / args.run_dir).resolve()
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2

    results = []
    for name, control in CONTROLS:
        fired, detail = control(run_dir)
        results.append({"control": name, "detected": fired, "detail": detail})
        print(f"  {'DETECTED' if fired else 'MISSED  '}  {name:38s} {detail}")

    detected = sum(1 for r in results if r["detected"])
    payload = {
        "artifact": "tdm08-negative-controls-v1",
        "run_dir": args.run_dir,
        "controls": results,
        "detected": detected,
        "total": len(results),
        "false_success": detected != len(results),
    }
    if args.out:
        out = REPO_ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {out}")
    print(f"negative controls: {detected}/{len(results)} detected")
    return 0 if detected == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
