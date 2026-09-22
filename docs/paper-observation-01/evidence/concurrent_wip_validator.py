"""Independent validator for the paper observation campaign setup.

This validator checks the durable campaign shell, report generation, and the
paper-only guardrails without claiming that seven real-market days are complete.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.demo.paper_multi_agent import run_campaign_observation


def _check(name: str, passed: bool, detail: str = "") -> tuple[str, str, str]:
    return name, "PASS" if passed else "FAIL", detail


def validate(report_dir: Path) -> tuple[bool, tuple[tuple[str, str, str], ...]]:
    campaign_dir = report_dir
    campaign_dir.mkdir(parents=True, exist_ok=True)
    state_path = campaign_dir / "CAMPAIGN_STATE.json"
    report_json = campaign_dir / "CAMPAIGN_REPORT.json"
    daily_json = next(
        (
            campaign_dir / date
            for date in sorted(p.name for p in campaign_dir.iterdir() if p.is_dir())
            if (campaign_dir / date / "DAILY_REPORT.json").exists()
        ),
        None,
    )
    daily_report = daily_json / "DAILY_REPORT.json" if daily_json is not None else None

    checks = [
        _check("campaign_state_written", state_path.exists(), str(state_path)),
        _check("campaign_report_written", report_json.exists(), str(report_json)),
        _check(
            "daily_report_written",
            daily_report is not None and daily_report.exists(),
            str(daily_report),
        ),
    ]

    if state_path.exists():
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        checks.extend(
            [
                _check(
                    "campaign_id_present",
                    bool(payload.get("campaign_id")),
                    payload.get("campaign_id") or "",
                ),
                _check(
                    "candidate_ids_unique",
                    len(payload.get("decision_ids", []))
                    == len(set(payload.get("decision_ids", []))),
                ),
                _check("live_calls_zero", int(payload.get("live_calls") or 0) == 0),
                _check("real_broker_calls_zero", int(payload.get("real_broker_calls") or 0) == 0),
                _check(
                    "private_exchange_calls_zero",
                    int(payload.get("private_exchange_calls") or 0) == 0,
                ),
                _check("false_success_zero", int(payload.get("false_success") or 0) == 0),
            ]
        )

    return all(status == "PASS" for _, status, _ in checks), tuple(checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the paper observation campaign setup")
    parser.add_argument("--report-dir", type=Path, default=Path("reports/paper-observation-01"))
    parser.add_argument("--campaign", default="paper-observation-01")
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args(argv)

    first, _ = run_campaign_observation(
        provider="fake",
        assets=("BTC", "ETH", "SOL"),
        output_dir=args.report_dir,
        cycles=args.cycles,
        campaign=args.campaign,
        resume=False,
    )
    assert first.state.mode == "PAPER"
    assert first.state.live_calls == 0
    assert first.state.false_success == 0

    second, _ = run_campaign_observation(
        provider="fake",
        assets=("BTC", "ETH", "SOL"),
        output_dir=args.report_dir,
        cycles=args.cycles,
        campaign=args.campaign,
        resume=True,
    )
    assert second.status == "READY"

    passed, checks = validate(args.report_dir)
    for name, status, detail in checks:
        suffix = f" — {detail}" if detail else ""
        print(f"{status} {name}{suffix}")
    print(f"{sum(status == 'PASS' for _, status, _ in checks)}/{len(checks)} PASS")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
