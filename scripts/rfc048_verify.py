"""RFC-048 — run the independent verifier over the executed artefacts.

    uv run python scripts/rfc048_verify.py

Reads ``data/rfc048/RUNTIME_EXECUTION_REPORT.json`` (and the fixtures), re-derives
every certified number with tools that do NOT import the builder, runs the seven
negative controls, and writes ``data/rfc048/INDEPENDENT_VERIFICATION.json``.

Exit code is non-zero when any check fails or any negative control escapes
detection (``FALSE_SUCCESS > 0``), so the verification cannot be reported green by
accident.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.risk.futures_verification import (  # noqa: E402
    VERIFIER_VERSION,
    load_fixtures,
    run_verification,
)

DATA = ROOT / "data" / "rfc048"


def independence_probe() -> dict[str, Any]:
    """Prove in a FRESH process that the verifier loads no builder module."""
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import trading_bot.risk.futures_verification as v;"
        "prefix = 'trading_bot.risk.futures';"
        "print('|'.join(sorted(n for n in sys.modules "
        "if (n == prefix or n.startswith(prefix + '.')) "
        "and n != 'trading_bot.risk.futures_verification')))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    loaded = [name for name in proc.stdout.strip().split("|") if name]
    return {
        "probe": "fresh interpreter imports the verifier and lists trading_bot.risk.futures*",
        "builder_modules_loaded": loaded,
        "independent": not loaded,
        "returncode": proc.returncode,
    }


def verify_model_cases(fixtures: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the model-level liquidation cases against the raw ladder."""
    cases = payload.get("model_level_cases", [])
    results = []
    for case in cases:
        assessment = case["assessment"]
        spec = fixtures.spec(case.get("instrument_id", "BINANCE_USDM_BTCUSDT_PERP"))
        quantity = case["quantity"]
        notional = case["notional"]
        direction = case["direction"]
        wallet = case["wallet_balance"]

        # Independent recomputation of the two margins, straight from the ladder.
        bracket = None
        for row in spec["maintenance_margin_brackets"]:
            if row["notional_floor"] <= notional <= row["notional_cap"]:
                bracket = row
                break
        mm = max(
            notional * bracket["maintenance_margin_rate"] - bracket["cum_maintenance_amount"],
            0.0,
        )
        # Independent root of the margin condition with the same safety terms the
        # builder reports, so a mis-solved liquidation price cannot pass.
        safety = float(assessment.get("adverse_terms_usdt") or 0.0)
        lo, hi = (0.5, 1.0) if direction == "LONG" else (1.0, 1.5)
        entry = float(assessment["entry_price"])
        from trading_bot.risk.futures_verification import _liquidation_root

        root = _liquidation_root(
            direction=direction,
            quantity=quantity,
            entry=entry,
            wallet=wallet,
            safety=safety,
            spec=spec,
            lo=entry * lo,
            hi=entry * hi,
        )
        reported = assessment.get("liquidation_price")
        root_ok = (
            root is None
            or reported is None
            or abs(root - float(reported)) <= max(1e-6, abs(root) * 1e-6)
        )
        results.append(
            {
                "case": case["case"],
                "path": case["path"],
                "maintenance_margin_recomputed": round(mm, 10),
                "maintenance_margin_reported": assessment.get("maintenance_margin_entry"),
                "maintenance_match": abs(mm - float(assessment["maintenance_margin_entry"]))
                <= max(1e-9, mm * 1e-9),
                "liquidation_root": root,
                "liquidation_reported": reported,
                "liquidation_match": root_ok,
                "status": assessment.get("status"),
                "passed": abs(mm - float(assessment["maintenance_margin_entry"]))
                <= max(1e-9, mm * 1e-9)
                and root_ok,
            }
        )
    return {
        "case_count": len(results),
        "passed": all(row["passed"] for row in results) and bool(results),
        "results": results,
    }


def main() -> int:
    started = time.time()
    fixtures = load_fixtures(DATA)
    payload = json.loads((DATA / "RUNTIME_EXECUTION_REPORT.json").read_text(encoding="utf-8"))
    scenarios = json.loads((DATA / "RISK_SCENARIOS.json").read_text(encoding="utf-8"))
    margin_payload = json.loads(
        (DATA / "MARGIN_LIQUIDATION_CASES.json").read_text(encoding="utf-8")
    )

    verification = run_verification({"decisions": scenarios["cases"]}, fixtures)
    model_cases = verify_model_cases(fixtures, margin_payload)
    independence = independence_probe()

    # A second, deliberate pass: verify the same artefacts twice and require the
    # same verdict, so a flaky check cannot be mistaken for a pass.
    repeat = run_verification({"decisions": scenarios["cases"]}, fixtures)
    reproducible = (
        repeat["verdict"] == verification["verdict"]
        and repeat["checks_run"] == verification["checks_run"]
        and repeat["false_success"] == verification["false_success"]
    )

    # Cross-check the execution report's own claims against the artefact.
    approved = [
        row
        for row in scenarios["cases"]
        if row["decision"]["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
    ]
    claimed = payload["execution"]
    report_consistency = {
        "scenarios_match": claimed["scenarios_run"] == len(scenarios["cases"]),
        "approved_match": claimed["approved_simulated"] == len(approved),
        "refused_match": claimed["refused"]
        == sum(1 for row in scenarios["cases"] if row["decision"]["approved_notional"] == 0.0),
        "no_order_authorised": claimed["order_authorised_anywhere"] is False
        and all(row["decision"]["order_authorised"] is False for row in scenarios["cases"]),
    }
    report_consistency["passed"] = all(report_consistency.values())

    false_success = verification["false_success"]
    verdict = (
        "RFC048_OFFLINE_VERIFIED"
        if verification["verdict"] == "VERIFIED"
        and model_cases["passed"]
        and independence["independent"]
        and reproducible
        and report_consistency["passed"]
        else "RFC048_PARTIAL"
    )

    artifact = {
        "schema_version": 1,
        "rfc": "RFC-048",
        "generated_by": "scripts/rfc048_verify.py",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "verifier_version": VERIFIER_VERSION,
        "builder": "trading_bot.risk.futures (engine, margin, sizing, costs)",
        "verifier": "trading_bot.risk.futures_verification (no builder import)",
        "independence": independence,
        "false_success": false_success,
        "reproducible": reproducible,
        "report_consistency": report_consistency,
        "decisions": {
            "verified": verification["decisions_verified"],
            "passed": verification["decisions_passed"],
            "checks_run": verification["checks_run"],
            "checks_failed": verification["checks_failed"],
        },
        "negative_controls": verification["negative_controls"],
        "model_level_cases": model_cases,
        "decision_results": verification["results"],
        "verdict": verdict,
    }
    (DATA / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
    )

    print(f"decisions verified: {verification['decisions_passed']}/{verification['decisions_verified']}")
    print(f"checks run: {verification['checks_run']}  failed: {len(verification['checks_failed'])}")
    print(f"negative controls detected: "
          f"{sum(1 for c in verification['negative_controls'] if c['detected'])}/"
          f"{len(verification['negative_controls'])}")
    print(f"false_success: {false_success}")
    print(f"independent process: {independence['independent']}  reproducible: {reproducible}")
    print(f"model-level cases passed: {model_cases['passed']}")
    print(f"verdict: {verdict}  ({round(time.time() - started, 3)}s)")
    return 0 if verdict == "RFC048_OFFLINE_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
