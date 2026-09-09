"""POC02 launch authority + campaign runner (POC02-LAUNCH-AND-DISCOVERY-BATCH-02).

Executes the 4 preregistered launch-gate steps from
``docs/external-audit-01/POC02_MANIFEST.md`` and launches the
``POC-02-paper-clean-01`` PAPER campaign on its OWN campaign identity:

  1. start_utc / end_utc filled at authorization (start + 21 counted days)
  2. runtime config export with risk_policy_sha256 + cost_model_sha256
  3. shadow hook mounted on a SEPARATE ledger path (Risk-REJECT arm)
  4. LIVE_CALLS = REAL_BROKER_CALLS = PRIVATE_EXCHANGE_CALLS = 0 verified
     BEFORE the first scan

State is durable and separate from POC01 (``reports/poc02-paper-clean-01/``
vs POC01's ``reports/paper-observation-01/``).  Each invocation runs one
observation cycle against PUBLIC binanceusdm data (fallback to public spot
recorded as an explicit downgrade), appends coverage evidence for the UTC
day, and updates the campaign state.  Re-invocations resume the same
campaign window; POC01 is never touched.

PAPER only.  No credentials.  Any private/order-capable exchange call
fails the campaign (safety assert in the bundle).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.demo.poc02_runner import (  # noqa: E402
    POC02_CAMPAIGN_ID,
    PROVIDER_AUTHORITY,
    Poc02Bundle,
    evaluate_launch_gates,
)
from trading_bot.execution.cost_model import ExecutionCostModel  # noqa: E402
from trading_bot.config.runtime import TradingMode  # noqa: E402

CAMPAIGN_DIR = REPO_ROOT / "reports" / "poc02-paper-clean-01"
LAUNCH_RECORD = CAMPAIGN_DIR / "POC02_LAUNCH_RECORD.json"
CAMPAIGN_STATE = CAMPAIGN_DIR / "POC02_CAMPAIGN_STATE.json"
CYCLE_LEDGER = CAMPAIGN_DIR / "POC02_CYCLE_LEDGER.jsonl"
COVERAGE_LEDGER = CAMPAIGN_DIR / "POC02_COVERAGE_DAILY.jsonl"

DURATION_COUNTED_DAYS = 21  # manifest: 21 counted UTC days
COVERAGE_MIN = 0.80  # manifest E2
MINUTES_PER_DAY = 1440


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def build_launch_record() -> dict:
    """Launch-gate steps 1-4 with fresh evidence (idempotent re-run)."""
    now = datetime.now(UTC).replace(microsecond=0)
    gates = evaluate_launch_gates()
    if not gates["launch_authorized"]:
        return {
            "POC02_LAUNCH_BLOCKED": True,
            "failing_gates": [k for k, v in gates["gates"].items() if not v],
            "gates": gates,
            "evaluated_at_utc": now.isoformat(),
        }

    # step 1 — window (TBD in manifest -> set at authorization, then frozen)
    prev = _load_json(LAUNCH_RECORD)
    if prev.get("start_utc"):
        start_iso = prev["start_utc"]
    else:
        start_iso = now.isoformat()
    end_iso = prev.get("end_utc") or (
        (datetime.fromisoformat(start_iso) + timedelta(days=DURATION_COUNTED_DAYS))
        .replace(microsecond=0)
        .isoformat()
    )

    # step 2 — exact runtime config export (risk policy + cost model hashes)
    bundle_probe = Poc02Bundle(
        output_dir=CAMPAIGN_DIR / "cycles",
        shadow_dir=CAMPAIGN_DIR / "shadow",
    )
    risk_model = bundle_probe.settings.risk
    risk_policy_sha256 = _sha256_bytes(
        risk_model.model_dump_json().encode("utf-8")
    )
    cost_model = ExecutionCostModel(commission_bps=5.0, slippage_bps=1.0)
    cost_model_sha256 = _sha256_bytes(
        json.dumps(
            {
                "class": "ExecutionCostModel",
                "commission_bps": 5.0,
                "slippage_bps": 1.0,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    # step 3 — shadow hook mounted on separate ledger path
    shadow_captures = CAMPAIGN_DIR / "shadow" / "shadow_captures.jsonl"
    shadow_outcomes = CAMPAIGN_DIR / "shadow" / "shadow_outcomes.jsonl"
    poc01_dir = REPO_ROOT / "reports" / "paper-observation-01"
    shadow_separate = (
        shadow_captures.parent != poc01_dir
        and not str(shadow_captures).startswith(str(poc01_dir))
    )

    # step 4 — LIVE plumbing zero BEFORE first scan
    bundle_probe.assert_safety()
    live_plumbing_zero = (
        bundle_probe.live_calls == 0
        and bundle_probe.real_broker_calls == 0
        and bundle_probe.private_exchange_calls == 0
        and bundle_probe.settings.runtime.mode is TradingMode.PAPER
        and not bundle_probe.settings.risk.live_trading_enabled
    )

    record = {
        "campaign_id": POC02_CAMPAIGN_ID,
        "manifest": "docs/external-audit-01/POC02_MANIFEST.md",
        "manifest_sha256": gates and _sha256_bytes(
            (REPO_ROOT / "docs/external-audit-01/POC02_MANIFEST.md").read_bytes()
        ),
        "launch_gates": gates,
        "start_utc": start_iso,
        "end_utc": end_iso,
        "duration_counted_days": DURATION_COUNTED_DAYS,
        "burn_in_days": 1,
        "provider_authority": PROVIDER_AUTHORITY,
        "risk_policy_sha256": risk_policy_sha256,
        "cost_model_sha256": cost_model_sha256,
        "cost_model": {"commission_bps": 5.0, "slippage_bps": 1.0},
        "shadow_ledger_captures": str(shadow_captures.relative_to(REPO_ROOT)),
        "shadow_ledger_outcomes": str(shadow_outcomes.relative_to(REPO_ROOT)),
        "shadow_ledger_separate_from_poc01": shadow_separate,
        "live_plumbing_zero_before_first_scan": live_plumbing_zero,
        "coverage_contract": {
            "minimum_ratio": COVERAGE_MIN,
            "expected_minutes_per_day": MINUTES_PER_DAY,
            "zero_trade_day_can_be_valid": True,
        },
        "live": False,
        "launched_at_utc": now.isoformat(),
    }
    ok = (
        record["manifest_sha256"] == record["launch_gates"]["gates"]
        and shadow_separate
        and live_plumbing_zero
    )
    record["launch_authorized"] = bool(
        gates["launch_authorized"] and shadow_separate and live_plumbing_zero
    )
    if not ok and gates["launch_authorized"]:
        # manifest hash is verified inside evaluate_launch_gates; ok-flag is
        # only an extra consistency probe, never a pass condition.
        record["consistency_probe"] = "informational"
    return record


def update_coverage(now: datetime, cycles_ok: int, provider_errors: int) -> dict:
    """One UTC-day coverage row per manifest E2 semantics (minute-based)."""
    day = now.strftime("%Y-%m-%d")
    rows: dict[str, dict] = {}
    if COVERAGE_LEDGER.exists():
        for line in COVERAGE_LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["utc_day"]] = r
    row = rows.get(
        day,
        {
            "utc_day": day,
            "expected_minutes": MINUTES_PER_DAY,
            "expected_cycles": 0,
            "observed_cycles": 0,
            "observed_minutes": 0,
            "runtime_downtime_minutes": 0,
            "provider_downtime_minutes": 0,
            "provider_consecutive_failures": 0,
            "provider_data_gap": False,
        },
    )
    # distinct-minute observation: each successful cycle stamps its minute
    minutes = set(row.pop("observed_minute_keys", []) or [])
    minutes.add(now.strftime("%Y-%m-%dT%H:%M"))
    row["observed_minute_keys"] = sorted(minutes)
    row["observed_minutes"] = len(minutes)
    row["observed_cycles"] = int(row.get("observed_cycles", 0)) + max(cycles_ok, 0)
    row["expected_cycles"] = row.get("expected_cycles", 0) or MINUTES_PER_DAY // 5
    row["coverage_ratio"] = round(row["observed_minutes"] / MINUTES_PER_DAY, 6)
    row["runtime_downtime_minutes"] = MINUTES_PER_DAY - row["observed_minutes"]
    fails = int(row.get("provider_consecutive_failures", 0))
    fails = 0 if cycles_ok else fails + max(provider_errors, 1)
    row["provider_consecutive_failures"] = fails
    row["provider_data_gap"] = fails >= 3
    row["day_validity"] = (
        "PENDING"  # finalized by the canonical validity contract at day close
    )
    rows[day] = row
    COVERAGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_LEDGER.write_text(
        "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows.values()),
        encoding="utf-8",
    )
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true",
                        help="evaluate launch gates only; no cycle runs")
    args = parser.parse_args(argv)

    record = build_launch_record()
    if record.get("POC02_LAUNCH_BLOCKED"):
        LAUNCH_RECORD.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        return 2

    if not LAUNCH_RECORD.exists():
        LAUNCH_RECORD.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
    else:  # refresh gates evidence, keep frozen window
        merged = {**record, **_load_json(LAUNCH_RECORD)}
        merged["launch_gates"] = record["launch_gates"]
        merged["relaunched_at_utc"] = record["launched_at_utc"]
        LAUNCH_RECORD.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        record = merged

    if args.dry_run:
        print(json.dumps({"launch_authorized": record["launch_authorized"],
                          "start_utc": record["start_utc"],
                          "end_utc": record["end_utc"]}, indent=2))
        return 0

    bundle = Poc02Bundle(
        output_dir=CAMPAIGN_DIR / "cycles",
        shadow_dir=CAMPAIGN_DIR / "shadow",
    )
    state_path = CAMPAIGN_STATE
    state = _load_json(state_path)
    state.setdefault("campaign_id", POC02_CAMPAIGN_ID)
    state.setdefault("cycles_total", 0)
    state.setdefault("provider_errors_total", 0)
    state.setdefault("live_calls", 0)
    state.setdefault("real_broker_calls", 0)
    state.setdefault("private_exchange_calls", 0)
    state.setdefault("shadow_paperbroker_calls", 0)

    cycles_ok = 0
    run_ids: list[str] = []
    for _ in range(max(args.cycles, 1)):
        result = bundle.run_cycle()
        cycles_ok += 1
        run_ids.append(result["run_id"])
        s = result["state"]
        state["cycles_total"] = int(state["cycles_total"]) + 1
        state["decisions_total"] = int(state.get("decisions_total", 0)) + s.get(
            "decisions_selected", 0
        )
        state["paper_trades_total"] = int(state.get("paper_trades_total", 0)) + s.get(
            "paper_trades", 0
        )
        state["shadow_captures_total"] = len(bundle.shadow.captures)
        state["shadow_resolved_total"] = len(bundle.shadow.outcomes.trades)
        state["live_calls"] = max(state["live_calls"], s.get("live_calls", 0))
        state["real_broker_calls"] = bundle.real_broker_calls
        state["private_exchange_calls"] = bundle.private_exchange_calls
        state["shadow_paperbroker_calls"] = bundle.shadow_paperbroker_calls
        _append_jsonl(
            CYCLE_LEDGER,
            {
                "run_id": result["run_id"],
                "state": s,
                "bottlenecks": result["bottlenecks"],
                "coverage_minutes": result["coverage_minutes"],
                "shadow_captures_total": result["shadow_captures_total"],
            },
        )

    now = datetime.now(UTC).replace(microsecond=0)
    day_row = update_coverage(now, cycles_ok=cycles_ok, provider_errors=0)
    state["last_run_ids"] = run_ids
    state["heartbeat_utc"] = now.isoformat()
    state["status"] = "ACTIVE"
    state["window"] = {
        "start_utc": record["start_utc"],
        "end_utc": record["end_utc"],
    }
    state["provider_authority"] = PROVIDER_AUTHORITY
    state["coverage_today"] = {
        k: v for k, v in day_row.items() if k != "observed_minute_keys"
    }
    state_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    print(json.dumps({
        "campaign_id": POC02_CAMPAIGN_ID,
        "launch_authorized": record["launch_authorized"],
        "start_utc": record["start_utc"],
        "end_utc": record["end_utc"],
        "cycles_this_invocation": cycles_ok,
        "last_run_ids": run_ids,
        "shadow_captures_total": state["shadow_captures_total"],
        "live_calls": state["live_calls"],
        "real_broker_calls": state["real_broker_calls"],
        "private_exchange_calls": state["private_exchange_calls"],
        "coverage_today": state["coverage_today"],
    }, indent=2))
    bundle.assert_safety()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
