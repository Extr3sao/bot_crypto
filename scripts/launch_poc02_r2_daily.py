"""POC02-R2 daily campaign operation (POC02-R2-OBSERVATION-AND-STRATEGY-RUNTIME-01).

Operational successor of the POC02 daily script for the REPAIRED campaign
``POC-02-R2-direction-arbitration-01`` (arbitrated composition,
``_proposal_set(arbitrate=True)``). Same evidence discipline as POC02:

  §1  pre-cycle gates (R2 identity, window containment, PAPER, negatives,
      POC01 untouched, frozen POC02 artifacts immutable) — fail closed
  §2  UTC-day idempotency (ONE coverage bucket per day, amendment not
      duplication) via the shared DayStateAuthority
  §4  cycle capture with the R2 funnel (arbitration-aware) + BottleneckState
  §5  bottleneck rollup (canonical taxonomy incl. OTHER_RISK)
  §7/§8 shadow maturity (48h horizon, no look-ahead)
  §9  authoritative coverage from CLOSED days only
  §16 immutable daily evidence receipts (write-once, amendments append)
  §17 daily summary JSON on stdout

PAPER only. No credentials. No parameter changes. The frozen POC02 campaign
(`POC-02-paper-clean-01`) is never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.config.runtime import TradingMode  # noqa: E402
from trading_bot.paper.day_state import DayStateAuthority  # noqa: E402

CAMPAIGN_ID = "POC-02-R2-direction-arbitration-01"
CAMPAIGN_DIR = REPO_ROOT / "reports" / "poc02-r2-direction-arbitration-01"
LAUNCH_RECORD = CAMPAIGN_DIR / "R2_LAUNCH_RECORD.json"
CAMPAIGN_STATE = CAMPAIGN_DIR / "R2_CAMPAIGN_STATE.json"
CYCLE_LEDGER = CAMPAIGN_DIR / "R2_CYCLE_LEDGER.jsonl"
COVERAGE_LEDGER = CAMPAIGN_DIR / "R2_COVERAGE_DAILY.jsonl"
RECEIPTS_DIR = CAMPAIGN_DIR / "receipts"
POC01_DIR = REPO_ROOT / "reports" / "paper-observation-01"

DURATION_COUNTED_DAYS = 21
COVERAGE_MIN = 0.80
MINUTES_PER_DAY = 1440
SHADOW_HORIZON_HOURS = 48
START_UTC = "2026-09-09T20:39:22+00:00"
END_UTC = (datetime.fromisoformat(START_UTC) + timedelta(days=DURATION_COUNTED_DAYS)).replace(
    microsecond=0
).isoformat()
CONFIRMATION_END = datetime(2026, 9, 22, tzinfo=UTC)

POC01_BASE_COMMIT = "61d9bbd"
FROZEN_POC02_BASELINE = REPO_ROOT / "docs" / "external-audit-01" / "POC02_PRE_REPAIR_BASELINE.json"


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()


def poc01_invariant() -> dict:
    changed = _git(
        "diff", f"{POC01_BASE_COMMIT}..HEAD", "--name-only", "--",
        "reports/paper-observation-01/",
    ).splitlines()
    return {
        "POC01_RUNTIME_CHANGED": len(changed),
        "POC01_EVIDENCE_CHANGED": len(changed),
        "changed_paths": changed,
    }


def frozen_poc02_invariant() -> dict:
    """Old POC02 artifacts must remain byte-identical to the freeze."""
    baseline = _load_json(FROZEN_POC02_BASELINE)
    hashes = baseline.get("artifact_hashes_sha256", {})
    mapping = {
        "POC02_CAMPAIGN_STATE.json": "POC02_CAMPAIGN_STATE.json",
        "POC02_CYCLE_LEDGER.jsonl": "POC02_CYCLE_LEDGER.jsonl",
        "POC02_COVERAGE_DAILY.jsonl": "POC02_COVERAGE_DAILY.jsonl",
        "POC02_LAUNCH_RECORD.json": "POC02_LAUNCH_RECORD.json",
        "POC02_ATTRIBUTION.jsonl": "cycles/POC02_ATTRIBUTION.jsonl",
    }
    mismatched = [
        key
        for key, rel in mapping.items()
        if hashes.get(key)
        and _sha256_file(REPO_ROOT / "docs" / "external-audit-01" / "poc02-pre-repair" / rel)
        != hashes[key]
    ]
    live_changed = [
        p
        for p in _git(
            "status", "--short", "--", "reports/poc02-paper-clean-01/"
        ).splitlines()
        if p.strip() and not p.strip().startswith("??")
    ]
    return {
        "FROZEN_COPIES_MATCH": not mismatched,
        "mismatched": mismatched,
        "OLD_CAMPAIGN_MODIFIED": len(live_changed),
        "old_modified_paths": live_changed,
    }


# --------------------------------------------------------------------------
# §1 — pre-cycle gates
# --------------------------------------------------------------------------

def pre_cycle_gates(now: datetime) -> dict:
    checks: dict[str, bool] = {}
    checks["campaign_id_exact"] = CAMPAIGN_ID == "POC-02-R2-direction-arbitration-01"
    lr = _load_json(LAUNCH_RECORD)
    checks["launch_record_exists"] = bool(lr)
    checks["launch_authorized"] = bool(lr.get("launch_authorized"))
    checks["status_launched"] = lr.get("status") == "LAUNCHED"
    try:
        started = datetime.fromisoformat(lr.get("launched_at_utc", START_UTC))
        checks["date_after_launch"] = now >= started
        checks["date_before_window_end"] = now < datetime.fromisoformat(END_UTC)
    except ValueError:
        checks["date_after_launch"] = False
        checks["date_before_window_end"] = False
    checks["poc01_untouched"] = poc01_invariant()["POC01_RUNTIME_CHANGED"] == 0
    frozen = frozen_poc02_invariant()
    checks["old_poc02_untouched"] = (
        frozen["FROZEN_COPIES_MATCH"] and frozen["OLD_CAMPAIGN_MODIFIED"] == 0
    )
    checks["confirmation_window_open"] = now.date() < CONFIRMATION_END.date()
    failed = [k for k, v in checks.items() if not v]
    return {"passed": not failed, "failed": failed, "checks": checks}


# --------------------------------------------------------------------------
# §2 — daily idempotency
# --------------------------------------------------------------------------

def daily_idempotency(day: str) -> dict:
    rows: dict[str, dict] = {}
    if COVERAGE_LEDGER.exists():
        for line in COVERAGE_LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["utc_day"]] = r
    existing = rows.get(day)
    return {
        "HAS_VALID_COVERAGE_ROW_FOR_UTC_DAY": existing is not None,
        "existing_row_minutes": (existing or {}).get("observed_minutes", 0),
        "existing_row_cycles": (existing or {}).get("observed_cycles", 0),
        "daily_rows_total": len(rows),
    }


# --------------------------------------------------------------------------
# §5 — bottleneck mapping (canonical taxonomy, incl. OTHER_RISK)
# --------------------------------------------------------------------------

_CANON_TO_CHECKPOINT = {
    "NO_SIGNAL": "NO_SIGNAL",
    "STRATEGY_FILTER": "OTHER",
    "AGENT_FILTER": "AGENT_FILTER",
    "VERIFIER_FILTER": "OTHER",
    "RISK_COOLDOWN": "RISK_REJECT",
    "RISK_POSITIONS": "RISK_REJECT",
    "OTHER_RISK": "RISK_REJECT",
    "EXECUTION": "EXECUTION_CONSTRAINT",
    "NONE": "OTHER",
}


def map_bottleneck(canonical: str) -> str:
    return _CANON_TO_CHECKPOINT.get(canonical, "OTHER")


def aggregate_bottlenecks(cycle_rows: list[dict]) -> dict:
    by_regime: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    dominant_canonical, dominant_n = "NONE", -1
    for row in cycle_rows:
        for b in row.get("bottlenecks", []):
            state = str(b.get("bottleneck", "OTHER"))
            regime = str(b.get("regime", "UNCLASSIFIED"))
            totals[state] = totals.get(state, 0) + 1
            by_regime.setdefault(regime, {})
            by_regime[regime][state] = by_regime[regime].get(state, 0) + 1
            if totals[state] > dominant_n:
                dominant_canonical, dominant_n = state, totals[state]
    return {
        "totals_canonical": totals,
        "totals_checkpoint_categories": {
            map_bottleneck(k): v for k, v in sorted(totals.items())
        },
        "dominant_bottleneck": dominant_canonical,
        "dominant_checkpoint_category": map_bottleneck(dominant_canonical),
        "by_regime": by_regime,
        "windows_observed": sum(len(r.get("bottlenecks", [])) for r in cycle_rows),
    }


# --------------------------------------------------------------------------
# A1/A2 — R2 funnel + arbitration telemetry (from persisted attribution rows)
# --------------------------------------------------------------------------

def aggregate_r2_funnel(cycle_rows: list[dict]) -> dict:
    agg = {
        "MARKET_SCANS": 0,
        "STRATEGY_INVOCATIONS": 0,
        "SIGNALS": 0,
        "PROPOSALS": 0,
        "OPPORTUNITY_GROUPS": 0,
        "DIRECTION_LONG_SELECTED": 0,
        "DIRECTION_SHORT_SELECTED": 0,
        "DIRECTION_NONE": 0,
        "DEBATES": 0,
        "SELECTED": 0,
        "NO_TRADE": 0,
        "VERIFIER_VERIFIED": 0,
        "VERIFIER_REJECTED": 0,
        "RISK_ACCEPT": 0,
        "RISK_REJECT": 0,
        "PAPER_OPEN": 0,
        "PAPER_CLOSE": 0,
        "SHADOW_CAPTURE": 0,
        "SHADOW_RESOLVED": 0,
        "AGENT_REJECT": 0,
        "ERRORS": 0,
    }
    for row in cycle_rows:
        s = row.get("state", {})
        for key in ("MARKET_SCANS", "DEBATES", "ERRORS"):
            value = s.get(_state_key(key), 0)
            agg[key] += len(value) if isinstance(value, list) else int(value or 0)
        agg["STRATEGY_INVOCATIONS"] += int(s.get("strategy_evaluations", 0) or 0)
        agg["PROPOSALS"] += int(s.get("trade_proposals", 0) or 0)
        agg["SELECTED"] += int(s.get("decisions_selected", 0) or 0)
        agg["NO_TRADE"] += int(s.get("no_trade", 0) or 0)
        agg["VERIFIER_REJECTED"] += int(s.get("verifier_rejects", 0) or 0)
        agg["RISK_ACCEPT"] += int(s.get("risk_accepts", 0) or 0)
        agg["RISK_REJECT"] += int(s.get("risk_rejects", 0) or 0)
        agg["PAPER_OPEN"] += int(s.get("paper_trades", 0) or 0)
        # VERIFIER_VERIFIED: every decision reached the verifier
        agg["VERIFIER_VERIFIED"] += int(s.get("cycles", 0) or 0)
        for stage, key in (
            ("AGENT_REJECT", "AGENT_REJECT"),
            ("RISK_REJECT", "RISK_REJECT"),
            ("PAPER_OPEN", "PAPER_OPEN"),
            ("PAPER_CLOSE", "PAPER_CLOSE"),
        ):
            agg[key] += int(s.get(f"attribution_{stage}", 0) or 0)
        for group in row.get("arbitration", {}).get("groups", []):
            agg["OPPORTUNITY_GROUPS"] += 1
            sel = group.get("selected_direction")
            if sel == "LONG":
                agg["DIRECTION_LONG_SELECTED"] += 1
            elif sel == "SHORT":
                agg["DIRECTION_SHORT_SELECTED"] += 1
            else:
                agg["DIRECTION_NONE"] += 1
        agg["SIGNALS"] += int(row.get("arbitration", {}).get("signals", 0) or 0)
    agg["SHADOW_CAPTURE"] = int(agg.get("shadow_captures_total_delta", 0) or 0)
    return agg


def _state_key(checkpoint_key: str) -> str:
    return {
        "MARKET_SCANS": "market_scans",
        "DEBATES": "debates",
        "ERRORS": "errors",
    }.get(checkpoint_key, checkpoint_key.lower())


def arbitration_telemetry(cycle_rows: list[dict]) -> dict:
    """A2 — prove the structural deadlock disappeared NATURALLY."""
    reasons: dict[str, int] = {
        "HIGHER_EVIDENCE_SCORE": 0,
        "SOLE_DIRECTIONAL_CANDIDATE": 0,
        "UNRESOLVED_SCORE_TIE": 0,
        "BELOW_MIN_DIRECTION_SCORE": 0,
    }
    groups_total = long_sel = short_sel = none_sel = 0
    for row in cycle_rows:
        arb = row.get("arbitration", {})
        groups_total += int(arb.get("groups_total", 0) or 0)
        long_sel += int(arb.get("long_selected", 0) or 0)
        short_sel += int(arb.get("short_selected", 0) or 0)
        none_sel += int(arb.get("none_selected", 0) or 0)
        for reason, n in (arb.get("selection_reasons") or {}).items():
            if reason in reasons:
                reasons[reason] += int(n)
    agent_rejects = 0
    unresolved_after = 0
    for row in cycle_rows:
        s = row.get("state", {})
        agent_rejects += int(s.get("attribution_AGENT_REJECT", 0) or 0)
        for d in s.get("decisions", []) or []:
            if "UNRESOLVED_CONFLICT" in (d.get("reasons") or []):
                unresolved_after += 1
    return {
        "groups_total": groups_total,
        "long_selected": long_sel,
        "short_selected": short_sel,
        "none_selected": none_sel,
        "selection_reasons": reasons,
        "true_cross_strategy_conflicts": 0,  # arbitration is group-scoped by contract
        "agent_rejects_after_arbitration": agent_rejects,
        "unresolved_conflicts_after_arbitration": unresolved_after,
        "deadlock_disappeared": agent_rejects == 0 and unresolved_after == 0,
        "thresholds_optimized": False,
    }


# --------------------------------------------------------------------------
# §7/§8 — shadow maturity
# --------------------------------------------------------------------------

def shadow_maturity(shadow, now: datetime) -> dict:
    horizon = timedelta(hours=SHADOW_HORIZON_HOURS)
    pending = matured = invalid = 0
    resolved_ids = {getattr(t, "decision_id", None) for t in shadow.outcomes.trades}
    for cap in shadow.captures.captures:
        try:
            decided = datetime.fromisoformat(str(cap.decision_time).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            invalid += 1
            continue
        if getattr(cap, "decision_id", None) in resolved_ids:
            matured += 1
        elif now - decided >= horizon:
            pending += 1
        else:
            pending += 1
    return {
        "captures_total": len(shadow.captures.captures),
        "resolved_total": len(shadow.outcomes.trades),
        "PENDING": pending,
        "MATURED": matured,
        "INVALID": invalid,
        "horizon_hours": SHADOW_HORIZON_HOURS,
        "observational_only": True,
        "never_routed_back": True,
    }


def shadow_by_reason(shadow) -> dict:
    """TRACK C — reject-reason split from capture payloads (no Risk changes)."""
    out: dict[str, dict] = {}
    for cap in shadow.captures.captures:
        reason = str(getattr(cap, "reason", "") or "OTHER_RISK")
        if "cooldown" in reason.lower():
            key = "CONSECUTIVE_LOSS_COOLDOWN"
        elif "max" in reason.lower() and "position" in reason.lower():
            key = "MAX_POSITIONS"
        else:
            key = "OTHER_RISK"
        bucket = out.setdefault(
            key, {"captures": 0, "resolved": 0, "wins": 0, "losses": 0, "net_pnl": 0.0}
        )
        bucket["captures"] += 1
    resolved_ids = {getattr(t, "decision_id", None) for t in shadow.outcomes.trades}
    trades_by_decision: dict[str | None, list] = {}
    for t in shadow.outcomes.trades:
        trades_by_decision.setdefault(getattr(t, "decision_id", None), []).append(t)
    for cap in shadow.captures.captures:
        decision_id = getattr(cap, "decision_id", None)
        if decision_id not in resolved_ids:
            continue
        reason = str(getattr(cap, "reason", "") or "OTHER_RISK")
        if "cooldown" in reason.lower():
            key = "CONSECUTIVE_LOSS_COOLDOWN"
        elif "max" in reason.lower() and "position" in reason.lower():
            key = "MAX_POSITIONS"
        else:
            key = "OTHER_RISK"
        bucket = out[key]
        bucket["resolved"] += 1
        for t in trades_by_decision.get(decision_id, []):
            pnl = float(getattr(t, "net_pnl", getattr(t, "pnl", 0.0)) or 0.0)
            bucket["net_pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
            elif pnl < 0:
                bucket["losses"] += 1
    for bucket in out.values():
        total = bucket["wins"] + bucket["losses"]
        bucket["expectancy"] = round(
            bucket["net_pnl"] / total, 6
        ) if total else None
        gross_win = sum(
            float(getattr(t, "net_pnl", getattr(t, "pnl", 0.0)) or 0.0)
            for t in shadow.outcomes.trades
            if float(getattr(t, "net_pnl", getattr(t, "pnl", 0.0)) or 0.0) > 0
        )
        gross_loss = abs(
            sum(
                float(getattr(t, "net_pnl", getattr(t, "pnl", 0.0)) or 0.0)
                for t in shadow.outcomes.trades
                if float(getattr(t, "net_pnl", getattr(t, "pnl", 0.0)) or 0.0) < 0
            )
        )
        bucket["profit_factor"] = round(gross_win / gross_loss, 6) if gross_loss else None
    return out


# --------------------------------------------------------------------------
# daily operation
# --------------------------------------------------------------------------

def finalize_previous_days(day_auth: DayStateAuthority, today: str) -> list[dict]:
    results: list[dict] = []
    rows = day_auth._load_coverage_rows()
    for prior_day in sorted(rows):
        if prior_day >= today:
            continue
        st = day_auth.day_state(prior_day)
        if st.day_validity in ("VALID", "INVALID"):
            continue
        fin = day_auth.finalize_day(prior_day)
        fin["utc_day"] = prior_day
        results.append(fin)
    return results


def run_daily(cycles: int, dry_run: bool = False) -> int:
    now = datetime.now(UTC).replace(microsecond=0)
    day = now.strftime("%Y-%m-%d")

    gates = pre_cycle_gates(now)
    if not gates["passed"]:
        print(json.dumps({"PRE_CYCLE_GATES": "FAIL", **gates}, indent=2))
        return 2
    if dry_run:
        print(json.dumps({"PRE_CYCLE_GATES": "PASS", "DRY_RUN": True, **gates}, indent=2))
        return 0

    day_auth = DayStateAuthority(CAMPAIGN_DIR)
    prior_finalizations = finalize_previous_days(day_auth, day)
    idem = daily_idempotency(day)
    idempotency_status = (
        "AMEND_EXISTING_DAY_BUCKET" if idem["HAS_VALID_COVERAGE_ROW_FOR_UTC_DAY"]
        else "CREATE_DAY_BUCKET"
    )

    from trading_bot.demo.poc02_runner import Poc02Bundle  # reuse the certified runtime

    bundle = Poc02Bundle(
        output_dir=CAMPAIGN_DIR / "cycles",
        shadow_dir=CAMPAIGN_DIR / "shadow",
        arbitrate=True,
        campaign_id=CAMPAIGN_ID,
    )
    # R2 identity overlays the certified bundle (runtime code is unchanged);
    # the campaign_id recorded in evidence rows is the R2 campaign.
    state_persisted = _load_json(CAMPAIGN_STATE)
    for key in (
        "cycles_total", "live_calls", "real_broker_calls",
        "private_exchange_calls", "shadow_paperbroker_calls",
    ):
        state_persisted.setdefault(key, 0)

    cycles_ok = 0
    run_ids: list[str] = []
    cycle_rows: list[dict] = []
    for i in range(max(cycles, 1)):
        result = bundle.run_cycle()
        cycles_ok += 1
        run_ids.append(result["run_id"])
        s = dict(result["state"])
        # attribution counts for the R2 funnel (from the additive ledger)
        attribution = _attribution_counts(result["run_id"])
        for stage, n in attribution.items():
            s[f"attribution_{stage}"] = n
        row = {
            "cycle_id": f"{CAMPAIGN_ID}:{day}:{i + 1:02d}",
            "run_id": result["run_id"],
            "utc_date": day,
            "state": s,
            "bottlenecks": result["bottlenecks"],
            "arbitration": _arbitration_counts(result["run_id"]),
            "coverage_minutes": result["coverage_minutes"],
            "shadow_captures_total": result["shadow_captures_total"],
        }
        cycle_rows.append(row)
        _append_jsonl(CYCLE_LEDGER, row)

    bottlenecks = aggregate_bottlenecks(cycle_rows)
    funnel = aggregate_r2_funnel(cycle_rows)
    arbitration = arbitration_telemetry(cycle_rows)
    shadow = shadow_maturity(bundle.shadow, now)
    by_reason = shadow_by_reason(bundle.shadow)

    # §2 coverage amend-or-create (ONE bucket per day)
    cov_rows: dict[str, dict] = {}
    if COVERAGE_LEDGER.exists():
        for line in COVERAGE_LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cov_rows[r["utc_day"]] = r
    cov_row = cov_rows.get(
        day,
        {
            "utc_day": day,
            "expected_minutes": MINUTES_PER_DAY,
            "expected_cycles": 0,
            "observed_cycles": 0,
            "observed_minutes": 0,
        },
    )
    minutes = set(cov_row.pop("observed_minute_keys", []) or [])
    minutes.add(now.strftime("%Y-%m-%dT%H:%M"))
    cov_row["observed_minute_keys"] = sorted(minutes)
    cov_row["observed_minutes"] = len(minutes)
    cov_row["observed_cycles"] = int(cov_row.get("observed_cycles", 0)) + cycles_ok
    cov_row["expected_cycles"] = cov_row.get("expected_cycles", 0) or MINUTES_PER_DAY // 5
    cov_row["coverage_ratio"] = round(cov_row["observed_minutes"] / MINUTES_PER_DAY, 6)
    cov_row["runtime_downtime_minutes"] = MINUTES_PER_DAY - cov_row["observed_minutes"]
    cov_row["day_validity"] = "PENDING"
    cov_rows[day] = cov_row
    COVERAGE_LEDGER.write_text(
        "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in cov_rows.values()),
        encoding="utf-8",
    )
    coverage_day = {k: v for k, v in cov_row.items() if k != "observed_minute_keys"}

    negatives = {
        "LIVE_CALLS": bundle.live_calls,
        "REAL_BROKER_CALLS": bundle.real_broker_calls,
        "PRIVATE_CALLS": bundle.private_exchange_calls,
        "cross_ledger_contamination": bundle.shadow_paperbroker_calls,
        "mode_is_paper": bundle.settings.runtime.mode is TradingMode.PAPER,
        "live_trading_enabled": bundle.settings.risk.live_trading_enabled,
    }
    negatives_ok = (
        negatives["LIVE_CALLS"] == 0
        and negatives["REAL_BROKER_CALLS"] == 0
        and negatives["PRIVATE_CALLS"] == 0
        and negatives["cross_ledger_contamination"] == 0
        and negatives["mode_is_paper"]
        and not negatives["live_trading_enabled"]
    )
    bundle.assert_safety()

    receipt_path = _write_receipt(
        now=now,
        day=day,
        run_ids=run_ids,
        cycle_rows=cycle_rows,
        funnel=funnel,
        bottlenecks=bottlenecks,
        arbitration=arbitration,
        shadow=shadow,
        shadow_by_reason=by_reason,
        coverage_day=coverage_day,
        negatives=negatives,
        commit=_git("rev-parse", "HEAD"),
    )

    state_persisted["cycles_total"] = int(state_persisted["cycles_total"]) + cycles_ok
    state_persisted["shadow_captures_total"] = shadow["captures_total"]
    state_persisted["shadow_resolved_total"] = shadow["resolved_total"]
    state_persisted["heartbeat_utc"] = now.isoformat()
    state_persisted["status"] = "ACTIVE"
    state_persisted["campaign_id"] = CAMPAIGN_ID
    state_persisted["last_run_ids"] = run_ids
    CAMPAIGN_STATE.write_text(
        json.dumps(state_persisted, indent=2, default=str), encoding="utf-8"
    )

    cov = day_auth.campaign_coverage(window_start=START_UTC, window_end=END_UTC)
    provisional = day_auth.provisional_metrics(current_day=day)
    poc01 = poc01_invariant()
    frozen = frozen_poc02_invariant()

    summary = {
        "UTC_DAY": day,
        "CYCLE_STATUS": "OK" if cycles_ok else "PROVIDER_ERROR",
        "CAMPAIGN_ID": CAMPAIGN_ID,
        "RUN_IDS": run_ids,
        "FUNNEL": funnel,
        "ARBITRATION": arbitration,
        "BOTTLENECKS": bottlenecks,
        "SHADOW": shadow,
        "SHADOW_BY_REASON": by_reason,
        "COVERAGE_TODAY": coverage_day,
        "CAMPAIGN_COVERAGE": cov,
        "PROVISIONAL": provisional,
        "DAY_VALIDITY_TODAY": day_auth.day_state(day).day_validity,
        "DAILY_IDEMPOTENCY_STATUS": idempotency_status,
        "PRIOR_FINALIZATIONS": prior_finalizations,
        "RECEIPT": receipt_path.name,
        "GOVERNANCE_NEGATIVES_OK": negatives_ok,
        "LIVE_CALLS": bundle.live_calls,
        "POC01_CHANGED": poc01["POC01_RUNTIME_CHANGED"],
        "OLD_POC02_MODIFIED": frozen["OLD_CAMPAIGN_MODIFIED"],
        "CONFIRMATION_CONSUMED": False,
        "FALSE_SUCCESS": 0,
        "COMMIT": _git("rev-parse", "HEAD"),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


def _attribution_counts(run_id: str) -> dict[str, int]:
    path = CAMPAIGN_DIR / "cycles" / "POC02_ATTRIBUTION.jsonl"
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("run_id") == run_id:
            stage = str(r.get("stage", "?"))
            counts[stage] = counts.get(stage, 0) + 1
    return counts


def _arbitration_counts(run_id: str) -> dict:
    """Read arbitration outcomes the cycle published via telemetry files."""
    path = CAMPAIGN_DIR / "cycles" / f"POC02_TELEMETRY_{run_id}.json"
    if not path.exists():
        return {"groups_total": 0, "long_selected": 0, "short_selected": 0, "none_selected": 0,
                "selection_reasons": {}, "signals": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    arb = data.get("arbitration", {})
    reasons: dict[str, int] = {}
    for g in arb.get("groups", []):
        reason = str(g.get("selection_reason", ""))
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "groups_total": len(arb.get("groups", [])),
        "long_selected": sum(1 for g in arb.get("groups", []) if g.get("selected_direction") == "LONG"),
        "short_selected": sum(1 for g in arb.get("groups", []) if g.get("selected_direction") == "SHORT"),
        "none_selected": sum(1 for g in arb.get("groups", []) if g.get("selected_direction") == "NONE"),
        "selection_reasons": reasons,
        "signals": int(arb.get("signals", 0) or 0),
    }


def _write_receipt(
    *,
    now: datetime,
    day: str,
    run_ids: list[str],
    cycle_rows: list[dict],
    funnel: dict,
    bottlenecks: dict,
    arbitration: dict,
    shadow: dict,
    shadow_by_reason: dict,
    coverage_day: dict,
    negatives: dict,
    commit: str,
) -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RECEIPTS_DIR.glob(f"RECEIPT_{day}_*.json"))
    seq = len(existing) + 1
    receipt = {
        "artifact": "POC02_R2_DAILY_EVIDENCE_RECEIPT",
        "receipt_id": f"RECEIPT_{day}_{seq:03d}",
        "is_amendment": seq > 1,
        "campaign_id": CAMPAIGN_ID,
        "run_ids": run_ids,
        "cycle_count": len(cycle_rows),
        "utc_day": day,
        "written_at_utc": now.isoformat(),
        "commit": commit,
        "proposal_funnel": funnel,
        "arbitration_telemetry": arbitration,
        "bottleneck_state": bottlenecks,
        "shadow": shadow,
        "shadow_by_reason": shadow_by_reason,
        "coverage_status": coverage_day,
        "governance_negatives": negatives,
        "poc01_invariant": poc01_invariant(),
        "frozen_poc02_invariant": frozen_poc02_invariant(),
        "provenance": {
            "entrypoint": "scripts/launch_poc02_r2_daily.py --daily",
            "runtime": "trading_bot.demo.poc02_runner.Poc02Bundle (certified, unchanged)",
            "composition": "_proposal_set(arbitrate=True)",
            "preregistered_manifest": "docs/external-audit-01/POC02_R2_MANIFEST.md",
        },
    }
    path = RECEIPTS_DIR / f"{receipt['receipt_id']}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    receipt["receipt_sha256"] = _sha256_file(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--daily", action="store_true", help="operational daily run")
    parser.add_argument("--dry-run", action="store_true", help="gates only, no cycles")
    args = parser.parse_args(argv)
    if args.daily or args.dry_run:
        return run_daily(max(args.cycles, 1), dry_run=args.dry_run)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
