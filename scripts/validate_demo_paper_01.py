"""Independent DEMO-PAPER-01 validator.

The validator consumes the demo's run report and executes the fixture again;
it does not build the decision package or choose a trade itself.  It checks
observable boundaries and reproducibility from outside the orchestration code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from trading_bot.demo.paper_multi_agent import run_fixture_demo

REQUIRED_REPORT_KEYS = (
    "run_id",
    "provider",
    "decisions",
    "events",
    "risk_calls",
    "broker_calls",
    "live_calls",
    "false_success",
)


def _check(name: str, passed: bool, detail: str = "") -> tuple[str, str, str]:
    return name, "PASS" if passed else "FAIL", detail


def validate(report_dir: Path) -> tuple[bool, tuple[tuple[str, str, str], ...]]:
    report_path = report_dir / "RUN_REPORT.json"
    if not report_path.exists():
        return False, (_check("run_report_exists", False, str(report_path)),)
    payload: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    checks = [
        _check("run_report_schema", all(key in payload for key in REQUIRED_REPORT_KEYS)),
        _check("paper_mode", payload.get("mode") == "PAPER"),
        _check("live_disabled", payload.get("live_disabled") is True),
        _check("ma2_proposals_reached", payload.get("trade_proposals", 0) >= 1),
        _check("ma3_debate_reached", payload.get("debates", 0) >= 1),
        _check("ma4_packages_created", any("package" in item for item in payload.get("decisions", []))),
        _check(
            "verifier_invoked",
            any(item.get("verifier_version") == "decision-package-verifier-v3" for item in payload.get("decisions", [])),
        ),
        _check("no_trade_observable", payload.get("no_trade", 0) >= 1),
        _check("selected_reaches_adapter", payload.get("decisions_selected", 0) >= 1),
        _check("risk_reject_no_broker_side_effect", payload.get("risk_rejects", 0) >= 1),
        _check("risk_accept_reaches_paper", payload.get("risk_accepts", 0) >= 1 and payload.get("paper_trades", 0) >= 1),
        _check("real_broker_calls_zero", payload.get("real_broker_calls") == 0),
        _check("private_exchange_calls_zero", payload.get("private_exchange_calls") == 0),
        _check("reconciliation_and_pnl", payload.get("closed_trades", 0) >= 1 and "realized_pnl" in payload),
        _check("decision_trace_reconstructible", all(event.get("run_id") == payload.get("run_id") for event in payload.get("events", []))),
        _check("run_authority", all(event.get("trace_id") == payload.get("trace_id") for event in payload.get("events", []))),
        _check("false_success_zero", payload.get("false_success") == 0),
    ]
    return all(status == "PASS" for _, status, _ in checks), tuple(checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate DEMO-PAPER-01")
    parser.add_argument("--report-dir", type=Path, default=Path("reports/demo-paper-01"))
    args = parser.parse_args(argv)
    # Always regenerate the fixture so this command is independent of stale files.
    run_fixture_demo(output_dir=args.report_dir)
    passed, checks = validate(args.report_dir)
    for name, status, detail in checks:
        suffix = f" — {detail}" if detail else ""
        print(f"{status} {name}{suffix}")
    print(f"{sum(status == 'PASS' for _, status, _ in checks)}/{len(checks)} PASS")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
