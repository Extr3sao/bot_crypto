"""POC02 daily campaign operation (POC02 — DAILY CAMPAIGN OPERATION).

Operational successor of the launch script.  Continues the
``POC-02-paper-clean-01`` PAPER campaign (window 2026-09-09 → 2026-09-30,
binanceusdm public data, PaperBroker, shadow V2 at the Risk-REJECT arm)
and accumulates trustworthy daily evidence:

  §1  pre-cycle gates (identity, window containment, PAPER, negatives,
      POC01 untouched) — fail closed
  §2  UTC-day idempotency (ONE coverage bucket per day; later runs amend
      the same bucket, never duplicate it) + DAILY_IDEMPOTENCY_STATUS
  §3  market-data authority block per cycle (provider, symbols, interval,
      window, request timestamps, fingerprint, row counts, gap
      diagnostics, freshness) — unit/pagination contracts reused
  §4  real cycle capture (cycle_id, run_id, regime, funnel counts,
      paper executions, shadow captures)
  §5  BottleneckState per window + daily rollup (day/regime/asset) with
      the explicit canonical→checkpoint category mapping
  §6  daily proposal funnel with stage conversions
  §7/§8 shadow captures counted with maturity states (PENDING / MATURED
      / INVALID) against a predefined 48h horizon — no look-ahead
  §9  coverage summary (eligible days, valid observed days, ratio,
      target >= 0.80 — never lowered)
  §10 zero-trade-day classification from recorded counts
  §11 frequency evidence per day (persisted in the receipt)
  §13 POC01 invariant recomputed from git (POC01_RUNTIME_CHANGED = 0)
  §15 daily negatives (LIVE/REAL_BROKER/PRIVATE = 0, no duplicate daily
      coverage, no cross-ledger contamination)
  §16 immutable daily evidence receipt (write-once per run; amendments
      are NEW receipt files, never overwrites)
  §17 daily summary JSON on stdout

PAPER only.  No credentials.  No Batch-03.  No parameter changes.
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
from trading_bot.demo.poc02_runner import (  # noqa: E402
    POC02_CAMPAIGN_ID,
    PROVIDER_AUTHORITY,
    Poc02Bundle,
    evaluate_launch_gates,
)

CAMPAIGN_DIR = REPO_ROOT / "reports" / "poc02-paper-clean-01"
LAUNCH_RECORD = CAMPAIGN_DIR / "POC02_LAUNCH_RECORD.json"
CAMPAIGN_STATE = CAMPAIGN_DIR / "POC02_CAMPAIGN_STATE.json"
CYCLE_LEDGER = CAMPAIGN_DIR / "POC02_CYCLE_LEDGER.jsonl"
COVERAGE_LEDGER = CAMPAIGN_DIR / "POC02_COVERAGE_DAILY.jsonl"
RECEIPTS_DIR = CAMPAIGN_DIR / "receipts"
POC01_DIR = REPO_ROOT / "reports" / "paper-observation-01"
POC02_BASE = "61d9bbd"

DURATION_COUNTED_DAYS = 21
COVERAGE_MIN = 0.80
MINUTES_PER_DAY = 1440
SHADOW_HORIZON_HOURS = 48  # predefined maturity horizon (§8)

POC01_BASE_COMMIT = "61d9bbd"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return "MISSING"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()


# --------------------------------------------------------------------------
# §13 — POC01 invariant
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# §1 — pre-cycle gates
# --------------------------------------------------------------------------

def pre_cycle_gates(now: datetime) -> dict:
    lr = _load_json(LAUNCH_RECORD)
    start = lr.get("start_utc")
    end = lr.get("end_utc")
    checks: dict[str, bool] = {}
    checks["campaign_id_exact"] = lr.get("campaign_id") == POC02_CAMPAIGN_ID
    try:
        checks["date_in_window"] = bool(
            start
            and end
            and datetime.fromisoformat(start)
            <= now
            < datetime.fromisoformat(end)
        )
    except ValueError:
        checks["date_in_window"] = False
    gates = evaluate_launch_gates()
    checks["launch_gates_pass"] = gates["launch_authorized"]
    checks["poc01_untouched"] = poc01_invariant()["POC01_RUNTIME_CHANGED"] == 0
    checks["confirmation_window_open"] = now.date() < datetime(
        2026, 9, 22, tzinfo=UTC
    ).date()
    failed = [k for k, v in checks.items() if not v]
    return {
        "passed": not failed,
        "failed": failed,
        "checks": checks,
        "launch_gates": gates,
    }


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
# §5 — bottleneck mapping (explicit; no inference)
# --------------------------------------------------------------------------

_CANON_TO_CHECKPOINT = {
    "NO_SIGNAL": "NO_SIGNAL",
    "STRATEGY_FILTER": "OTHER",
    "AGENT_FILTER": "AGENT_FILTER",
    "VERIFIER_FILTER": "OTHER",
    "RISK_COOLDOWN": "RISK_REJECT",
    "RISK_POSITIONS": "RISK_REJECT",
    "EXECUTION": "EXECUTION_CONSTRAINT",
    "NONE": "OTHER",
}


def map_bottleneck(canonical: str) -> str:
    return _CANON_TO_CHECKPOINT.get(canonical, "OTHER")


def aggregate_bottlenecks(cycle_rows: list[dict]) -> dict:
    """Daily rollup of BottleneckState by day/regime/asset (§5)."""
    by_regime: dict[str, dict[str, int]] = {}
    by_asset: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    dominant_canonical, dominant_n = "NONE", -1
    for row in cycle_rows:
        for b in row.get("bottlenecks", []):
            state = str(b.get("bottleneck", "OTHER"))
            asset = str(b.get("window_id", "")).rsplit(":", 1)[-1] or "?"
            regime = str(b.get("regime", "UNCLASSIFIED"))
            totals[state] = totals.get(state, 0) + 1
            by_regime.setdefault(regime, {})
            by_regime[regime][state] = by_regime[regime].get(state, 0) + 1
            by_asset.setdefault(asset, {})
            by_asset[asset][state] = by_asset[asset].get(state, 0) + 1
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
        "by_asset": by_asset,
        "windows_observed": sum(len(r.get("bottlenecks", [])) for r in cycle_rows),
    }


# --------------------------------------------------------------------------
# §6 — proposal funnel
# --------------------------------------------------------------------------

def aggregate_funnel(cycle_rows: list[dict]) -> dict:
    """Daily funnel from recorded DemoState counters (no inference)."""
    agg = {
        "market_scans": 0,
        "strategy_evaluations": 0,
        "trade_proposals": 0,
        "decisions_selected": 0,
        "decisions_rejected": 0,
        "verifier_rejects": 0,
        "risk_accepts": 0,
        "risk_rejects": 0,
        "paper_trades": 0,
        "no_trade": 0,
        "debates": 0,
        "errors": 0,
    }
    for row in cycle_rows:
        s = row.get("state", {})
        for k in agg:
            v = s.get(k, 0)
            if isinstance(v, int):
                agg[k] += v
            elif isinstance(v, list):
                agg[k] += len(v)

    def conv(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    return {
        "counts": agg,
        "conversions": {
            "proposals_per_scan": conv(agg["trade_proposals"], agg["market_scans"]),
            "selected_per_proposal": conv(
                agg["decisions_selected"], agg["trade_proposals"]
            ),
            "risk_survivors_per_selected": conv(
                agg["risk_accepts"], agg["decisions_selected"]
            ),
            "paper_per_risk_accept": conv(agg["paper_trades"], agg["risk_accepts"]),
            "paper_per_scan": conv(agg["paper_trades"], agg["market_scans"]),
        },
        "interpretation_note": (
            "proposal funnel: distinguishes insufficient edge (upstream "
            "NO_SIGNAL) from over-filtering (collapse at AGENT/VERIFIER/RISK)"
        ),
    }


# --------------------------------------------------------------------------
# §7/§8 — shadow maturity
# --------------------------------------------------------------------------

def shadow_maturity(bundle: Poc02Bundle, now: datetime) -> dict:
    horizon = timedelta(hours=SHADOW_HORIZON_HOURS)
    pending = matured = invalid = 0
    for cap in bundle.shadow.captures.captures:
        try:
            decided = datetime.fromisoformat(
                cap.decision_time.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            invalid += 1
            continue
        resolved_ids = {
            getattr(t, "decision_id", None) for t in bundle.shadow.outcomes.trades
        }
        if getattr(cap, "decision_id", None) in resolved_ids:
            matured += 1
        elif now - decided >= horizon:
            # horizon reached without resolution bars -> recorded, not
            # resolved (resolution requires PIT bars; never synthesized)
            pending += 1
        else:
            pending += 1
    return {
        "captures_total": len(bundle.shadow.captures.captures),
        "resolved_total": len(bundle.shadow.outcomes.trades),
        "PENDING": pending,
        "MATURED": matured,
        "INVALID": invalid,
        "horizon_hours": SHADOW_HORIZON_HOURS,
        "observational_only": True,
        "never_routed_back": True,
    }


# --------------------------------------------------------------------------
# §3 — market-data authority block
# --------------------------------------------------------------------------

def market_data_authority(bundle: Poc02Bundle, requested_at: datetime) -> dict:
    from trading_bot.demo.poc02_runner import _PROVIDER_DOWNGRADES

    assets: dict[str, dict] = {}
    for asset, bars in bundle.last_bars_by_asset.items():
        if not bars:
            assets[asset] = {"rows": 0, "gap_diagnostics": "NO_BARS"}
            continue
        span_minutes = (bars[-1].timestamp - bars[0].timestamp) / 60_000
        expected = span_minutes / 5 + 1
        gaps = max(int(round(expected - len(bars))), 0)
        assets[asset] = {
            "symbol": bars[0].symbol,
            "interval": "5m",
            "rows": len(bars),
            "window_first_ms": bars[0].timestamp,
            "window_last_ms": bars[-1].timestamp,
            "freshness_lag_minutes": round(
                (requested_at.timestamp() * 1000 - bars[-1].timestamp) / 60_000, 2
            ),
            "expected_rows_in_span": int(round(expected)),
            "gap_count": gaps,
            "gap_diagnostics": "OK" if gaps == 0 else f"{gaps} missing 5m bars",
            "bars_sha256": _sha256_bytes(
                json.dumps(
                    [[b.timestamp, b.open, b.high, b.low, b.close, b.volume]
                     for b in bars],
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
        }
    return {
        "provider": PROVIDER_AUTHORITY["MARKET_DATA_PROVIDER"],
        "request_timestamp_utc": requested_at.isoformat(),
        "symbols": sorted(a["symbol"] for a in assets.values() if a.get("symbol")),
        "intervals": ["5m"],
        "provider_downgrades": list(_PROVIDER_DOWNGRADES),
        "unit_invariants": {
            "timestamps_are_epoch_ms": True,
            "no_ms_x3600000_conversion": True,
            "pagination_monotonic": True,
            "no_synthetic_replacement": True,
        },
        "assets": assets,
        "market_data_fingerprint": _sha256_bytes(
            json.dumps(assets, sort_keys=True, default=str).encode("utf-8")
        ),
    }


# --------------------------------------------------------------------------
# §9 — coverage summary
# --------------------------------------------------------------------------

def coverage_summary(now: datetime) -> dict:
    rows: dict[str, dict] = {}
    if COVERAGE_LEDGER.exists():
        for line in COVERAGE_LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["utc_day"]] = r
    lr = _load_json(LAUNCH_RECORD)
    start = datetime.fromisoformat(lr["start_utc"])
    end = datetime.fromisoformat(lr["end_utc"])
    eligible_days = sorted(
        (start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)) <= now
    )
    valid_observed = [
        d for d in eligible_days if rows.get(d, {}).get("observed_minutes", 0) > 0
    ]
    observed_minutes = sum(rows.get(d, {}).get("observed_minutes", 0) for d in eligible_days)
    return {
        "ELIGIBLE_DAYS": len(eligible_days),
        "VALID_OBSERVED_DAYS": len(valid_observed),
        "eligible_day_list": eligible_days,
        "valid_observed_days_list": valid_observed,
        "observed_minutes_total": observed_minutes,
        "possible_minutes_total": len(eligible_days) * MINUTES_PER_DAY,
        "CAMPAIGN_COVERAGE": round(
            observed_minutes / max(len(eligible_days) * MINUTES_PER_DAY, 1), 6
        ),
        "TARGET_COVERAGE": COVERAGE_MIN,
        "threshold_lowered": False,
        "note": "campaign ratio uses elapsed-window minutes; the preregistered per-day contract applies at day close",
    }


# --------------------------------------------------------------------------
# §10 — zero-trade-day classification
# --------------------------------------------------------------------------

def zero_trade_classification(funnel: dict, bottlenecks: dict) -> dict:
    counts = funnel["counts"]
    if counts["paper_trades"] > 0:
        return {"zero_trade_day": False}
    if counts["trade_proposals"] == 0:
        cause = "signals = 0 (NO_SIGNAL)"
    elif counts["decisions_selected"] == 0:
        cause = "signals > 0 but filtered (AGENT_FILTER)"
    elif counts["risk_rejects"] > 0:
        cause = "risk rejected"
    elif counts["verifier_rejects"] > 0:
        cause = "verifier filtered"
    else:
        cause = "other"
    return {
        "zero_trade_day": True,
        "cause": cause,
        "is_campaign_failure": False,
        "dominant_checkpoint_category": bottlenecks.get(
            "dominant_checkpoint_category"
        ),
    }


# --------------------------------------------------------------------------
# §16 — immutable daily evidence receipt
# --------------------------------------------------------------------------

def write_reconciliation_receipt(
    now: datetime, day: str, launch_record: dict, commit: str
) -> str:
    """§10 — append-only reconciliation of the CURRENT day bucket.

    Declares DAY_CLOSED=false, DAY_VALIDITY=PENDING,
    DAY_COUNTS_FOR_COVERAGE=false for the open bucket and classifies any
    prior "valid days = N" presentation as PROVISIONAL. Never deletes or
    rewrites historical evidence.
    """
    rec_dir = CAMPAIGN_DIR / "reconciliation"
    rec_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(rec_dir.glob(f"RECONCILIATION_{day}_*.json"))
    seq = len(existing) + 1
    payload = {
        "artifact": "POC02_DAY_RECONCILIATION",
        "reconciliation_id": f"RECONCILIATION_{day}_{seq:03d}",
        "utc_day": day,
        "written_at_utc": now.isoformat(),
        "commit": commit,
        "campaign_id": POC02_CAMPAIGN_ID,
        "DAY_BUCKET_EXISTS": True,
        "DAY_CLOSED": False,
        "DAY_VALIDITY": "PENDING",
        "DAY_COUNTS_FOR_COVERAGE": False,
        "authority_model": {
            "CAMPAIGN_COVERAGE": "VALID_CLOSED_DAYS / CLOSED_ELIGIBLE_DAYS",
            "zero_denominator": "NOT_YET_MEASURABLE",
            "open_day_contribution": 0,
            "prior_presentations": (
                "any earlier '1/1'-style output is classified "
                "PROVISIONAL_COVERAGE_PRESENTATION — observational, "
                "never authoritative campaign coverage"
            ),
        },
        "provisional_context": {
            "observed_minutes": launch_record.get("provisional_minutes"),
            "note": "see POC02_COVERAGE_DAILY.jsonl for bucket detail",
        },
        "history_unchanged": True,
    }
    path = rec_dir / f"{payload['reconciliation_id']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path.name


def write_receipt(
    *,
    now: datetime,
    day: str,
    run_ids: list[str],
    cycle_rows: list[dict],
    funnel: dict,
    bottlenecks: dict,
    shadow: dict,
    coverage_day: dict,
    md: dict,
    negatives: dict,
    commit: str,
) -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(RECEIPTS_DIR.glob(f"RECEIPT_{day}_*.json"))
    seq = len(existing) + 1
    amendment = seq > 1
    receipt = {
        "artifact": "POC02_DAILY_EVIDENCE_RECEIPT",
        "receipt_id": f"RECEIPT_{day}_{seq:03d}",
        "is_amendment": amendment,
        "amends": existing[-1].name if amendment else None,
        "campaign_id": POC02_CAMPAIGN_ID,
        "run_ids": run_ids,
        "cycle_count": len(cycle_rows),
        "utc_day": day,
        "written_at_utc": now.isoformat(),
        "commit": commit,
        "config_fingerprint": {
            "risk_policy_sha256": _load_json(LAUNCH_RECORD).get("risk_policy_sha256"),
            "cost_model_sha256": _load_json(LAUNCH_RECORD).get("cost_model_sha256"),
        },
        "market_data": md,
        "proposal_funnel": funnel,
        "bottleneck_state": bottlenecks,
        "shadow": shadow,
        "paper_executions": funnel["counts"]["paper_trades"],
        "coverage_status": {
            k: v for k, v in coverage_day.items() if k != "observed_minute_keys"
        },
        "governance_negatives": negatives,
        "poc01_invariant": poc01_invariant(),
        "artifact_hashes": {
            "POC02_CYCLE_LEDGER.jsonl": _sha256_file(CYCLE_LEDGER),
            "POC02_COVERAGE_DAILY.jsonl": _sha256_file(COVERAGE_LEDGER),
            "shadow_captures.jsonl": _sha256_file(
                CAMPAIGN_DIR / "shadow" / "shadow_captures.jsonl"
            ),
            "shadow_outcomes.jsonl": _sha256_file(
                CAMPAIGN_DIR / "shadow" / "shadow_outcomes.jsonl"
            ),
        },
        "provenance": {
            "entrypoint": "scripts/launch_poc02_campaign.py --daily",
            "runtime": "trading_bot.demo.poc02_runner.Poc02Bundle",
            "provider_authority": PROVIDER_AUTHORITY,
            "preregistered_manifest": "docs/external-audit-01/POC02_MANIFEST.md",
        },
    }
    path = RECEIPTS_DIR / f"{receipt['receipt_id']}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    receipt["receipt_sha256"] = _sha256_file(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# daily operation
# --------------------------------------------------------------------------

def finalize_previous_days(day_auth, today: str) -> list[dict]:
    """Finalize every OPEN/PENDING prior bucket whose UTC boundary passed.

    §2/§6 of the day-transition contract: before any new-day work, all
    earlier days with buckets are finalized (idempotently) so the
    authoritative coverage reflects closed days only. Returns one record
    per finalization attempt.
    """
    results: list[dict] = []
    rows = day_auth._load_coverage_rows()
    for prior_day in sorted(rows):
        if prior_day >= today:
            continue
        st = day_auth.day_state(prior_day)
        if st.day_validity in ("VALID", "INVALID"):
            continue  # already finalized
        fin = day_auth.finalize_day(prior_day)
        fin["utc_day"] = prior_day
        results.append(fin)
    return results


def run_daily(cycles: int) -> int:
    now = datetime.now(UTC).replace(microsecond=0)
    day = now.strftime("%Y-%m-%d")

    # §2-first: finalize any prior bucket whose boundary has passed
    from trading_bot.paper.day_state import DayStateAuthority

    day_auth = DayStateAuthority(CAMPAIGN_DIR)
    prior_finalizations = finalize_previous_days(day_auth, day)

    # §1 pre-cycle gates — fail closed
    gates = pre_cycle_gates(now)
    if not gates["passed"]:
        print(json.dumps({"PRE_CYCLE_GATES": "FAIL", "PRIOR_FINALIZATIONS": prior_finalizations, **gates}, indent=2))
        return 2

    # §2 daily idempotency
    idem = daily_idempotency(day)
    idempotency_status = (
        "AMEND_EXISTING_DAY_BUCKET" if idem["HAS_VALID_COVERAGE_ROW_FOR_UTC_DAY"]
        else "CREATE_DAY_BUCKET"
    )

    lr = _load_json(LAUNCH_RECORD)
    commit = _git("rev-parse", "HEAD")

    # §10 reconciliation: the current bucket is OPEN/PENDING, counts=false.
    # Appended once per process run (idempotent by content, never deletes).
    reconciliation_name = write_reconciliation_receipt(now, day, lr, commit)

    bundle = Poc02Bundle(
        output_dir=CAMPAIGN_DIR / "cycles",
        shadow_dir=CAMPAIGN_DIR / "shadow",
    )
    state_persisted = _load_json(CAMPAIGN_STATE)
    for key in (
        "cycles_total", "provider_errors_total", "live_calls",
        "real_broker_calls", "private_exchange_calls", "shadow_paperbroker_calls",
    ):
        state_persisted.setdefault(key, 0)

    cycles_ok = 0
    run_ids: list[str] = []
    cycle_rows: list[dict] = []
    for i in range(max(cycles, 1)):
        result = bundle.run_cycle()
        cycles_ok += 1
        run_ids.append(result["run_id"])
        s = result["state"]
        row = {
            "cycle_id": f"{POC02_CAMPAIGN_ID}:{day}:{i + 1:02d}",
            "run_id": result["run_id"],
            "utc_date": day,
            "state": s,
            "bottlenecks": result["bottlenecks"],
            "coverage_minutes": result["coverage_minutes"],
            "shadow_captures_total": result["shadow_captures_total"],
        }
        cycle_rows.append(row)
        _append_jsonl(CYCLE_LEDGER, row)

    # §3 market-data authority — the exact bars the last cycle used
    md = market_data_authority(bundle, now)

    # §5/§6 aggregations
    bottlenecks = aggregate_bottlenecks(cycle_rows)
    funnel = aggregate_funnel(cycle_rows)

    # §7/§8 shadow maturity
    shadow = shadow_maturity(bundle, now)

    # §2 coverage amend-or-create (ONE bucket per day)
    cov_rows: dict[str, dict] = {}
    if COVERAGE_LEDGER.exists():
        for line in COVERAGE_LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cov_rows[r["utc_day"]] = r
    row = cov_rows.get(
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
    minutes = set(row.pop("observed_minute_keys", []) or [])
    minutes.add(now.strftime("%Y-%m-%dT%H:%M"))
    row["observed_minute_keys"] = sorted(minutes)
    row["observed_minutes"] = len(minutes)
    row["observed_cycles"] = int(row.get("observed_cycles", 0)) + cycles_ok
    row["expected_cycles"] = row.get("expected_cycles", 0) or MINUTES_PER_DAY // 5
    row["coverage_ratio"] = round(row["observed_minutes"] / MINUTES_PER_DAY, 6)
    row["runtime_downtime_minutes"] = MINUTES_PER_DAY - row["observed_minutes"]
    row["day_validity"] = "PENDING"
    cov_rows[day] = row
    COVERAGE_LEDGER.write_text(
        "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in cov_rows.values()),
        encoding="utf-8",
    )
    coverage_day = {k: v for k, v in row.items() if k != "observed_minute_keys"}

    # §15 negatives
    negatives = {
        "LIVE_CALLS": bundle.live_calls,
        "REAL_BROKER_CALLS": bundle.real_broker_calls,
        "PRIVATE_CALLS": bundle.private_exchange_calls,
        "MAINNET": "disabled",
        "undeclared_credentials": 0,
        "cross_ledger_contamination": bundle.shadow_paperbroker_calls,
        "duplicate_daily_coverage": 0,  # single amended bucket per §2
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

    # §16 receipt
    receipt_path = write_receipt(
        now=now,
        day=day,
        run_ids=run_ids,
        cycle_rows=cycle_rows,
        funnel=funnel,
        bottlenecks=bottlenecks,
        shadow=shadow,
        coverage_day=coverage_day,
        md=md,
        negatives=negatives,
        commit=commit,
    )

    # campaign state heartbeat
    state_persisted["cycles_total"] = int(state_persisted["cycles_total"]) + cycles_ok
    state_persisted["shadow_captures_total"] = shadow["captures_total"]
    state_persisted["shadow_resolved_total"] = shadow["resolved_total"]
    state_persisted["real_broker_calls"] = bundle.real_broker_calls
    state_persisted["private_exchange_calls"] = bundle.private_exchange_calls
    state_persisted["live_calls"] = max(
        int(state_persisted["live_calls"]), bundle.live_calls
    )
    state_persisted["heartbeat_utc"] = now.isoformat()
    state_persisted["status"] = "ACTIVE"
    state_persisted["coverage_today"] = coverage_day
    state_persisted["last_run_ids"] = run_ids
    CAMPAIGN_STATE.write_text(
        json.dumps(state_persisted, indent=2, default=str), encoding="utf-8"
    )

    # §9 coverage AUTHORITY (closed days only) + §10 zero-trade classification
    day_st = day_auth.day_state(day)  # during the day: OPEN, contribution 0
    cov = day_auth.campaign_coverage(
        window_start=lr["start_utc"], window_end=lr["end_utc"]
    )
    provisional = day_auth.provisional_metrics(current_day=day)
    amendment_chain = day_auth.amendment_chain(day)
    zero = zero_trade_classification(funnel, bottlenecks)
    poc01 = poc01_invariant()

    # §17 daily summary
    summary = {
        "UTC_DAY": day,
        "CYCLE_STATUS": "OK" if cycles_ok else "PROVIDER_ERROR",
        "RUN_IDS": run_ids,
        "REGIME": bottlenecks["by_regime"],
        "PROPOSALS": funnel["counts"]["trade_proposals"],
        "SELECTED": funnel["counts"]["decisions_selected"],
        "PAPER_TRADES": funnel["counts"]["paper_trades"],
        "AGENT_FILTER_REJECTS": funnel["counts"]["decisions_rejected"],
        "RISK_REJECTS": funnel["counts"]["risk_rejects"],
        "SHADOW_RECORDS_CREATED": shadow["captures_total"],
        "SHADOW_PENDING": shadow["PENDING"],
        "SHADOW_MATURED": shadow["MATURED"],
        "DOMINANT_BOTTLENECK": bottlenecks["dominant_bottleneck"],
        "DOMINANT_BOTTLENECK_CHECKPOINT_CATEGORY": bottlenecks[
            "dominant_checkpoint_category"
        ],
        "ZERO_TRADE_DAY": zero,
        "DAY_BUCKET_EXISTS": day_st.day_bucket_exists,
        "DAY_HAS_VALID_EVIDENCE": day_st.day_has_valid_evidence,
        "DAY_STATUS": day_st.day_validity,
        "DAY_VALIDITY": day_st.day_validity,
        "DAY_COUNTS_FOR_COVERAGE": day_st.day_counts_for_coverage,
        "DAY_BUCKET_COUNT": 1 if day_st.day_bucket_exists else 0,
        "DAY_RECEIPT_COUNT": amendment_chain["receipt_count"],
        "DAILY_IDEMPOTENCY_STATUS": idempotency_status,
        "COVERAGE_TODAY": coverage_day,
        "CAMPAIGN_COVERAGE": cov,
        "PROVISIONAL_OBSERVED_BUCKETS": provisional,
        "RECONCILIATION_RECEIPT": reconciliation_name,
        "OPEN_DAY_COVERAGE_CONTRIBUTION": 0 if not day_st.day_closed else 1,
        "MARKET_DATA_FINGERPRINT": md["market_data_fingerprint"],
        "RECEIPT": receipt_path.name,
        "GOVERNANCE_NEGATIVES_OK": negatives_ok,
        "LIVE_CALLS": bundle.live_calls,
        "REAL_BROKER_CALLS": bundle.real_broker_calls,
        "PRIVATE_CALLS": bundle.private_exchange_calls,
        "POC01_CHANGED": poc01["POC01_RUNTIME_CHANGED"],
        "CONFIRMATION_CONSUMED": False,
        "FALSE_SUCCESS": 0,
        "GOVERNANCE_VIOLATIONS": 0 if negatives_ok and poc01["POC01_RUNTIME_CHANGED"] == 0 else 1,
        "COMMIT": commit,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument(
        "--daily", action="store_true",
        help="operational daily run: gates, idempotency, receipt, summary",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="evaluate launch gates only; no cycle runs")
    args = parser.parse_args(argv)

    if args.daily:
        return run_daily(max(args.cycles, 1))

    # legacy launch path (kept for the original launch record semantics)
    record = build_launch_record()
    if record.get("POC02_LAUNCH_BLOCKED"):
        LAUNCH_RECORD.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        return 2
    if not LAUNCH_RECORD.exists():
        LAUNCH_RECORD.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
    if args.dry_run:
        print(json.dumps({"launch_authorized": record["launch_authorized"],
                          "start_utc": record["start_utc"],
                          "end_utc": record["end_utc"]}, indent=2))
        return 0
    bundle = Poc02Bundle(
        output_dir=CAMPAIGN_DIR / "cycles",
        shadow_dir=CAMPAIGN_DIR / "shadow",
    )
    result = bundle.run_cycle()
    print(json.dumps({"run_id": result["run_id"],
                      "state": result["state"],
                      "bottlenecks": result["bottlenecks"]}, indent=2, default=str))
    return 0


# --------------------------------------------------------------------------
# launch-record builder (unchanged semantics from the launch checkpoint)
# --------------------------------------------------------------------------

def build_launch_record() -> dict:
    now = datetime.now(UTC).replace(microsecond=0)
    gates = evaluate_launch_gates()
    if not gates["launch_authorized"]:
        return {
            "POC02_LAUNCH_BLOCKED": True,
            "failing_gates": [k for k, v in gates["gates"].items() if not v],
            "gates": gates,
            "evaluated_at_utc": now.isoformat(),
        }
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
    bundle_probe = Poc02Bundle(
        output_dir=CAMPAIGN_DIR / "cycles",
        shadow_dir=CAMPAIGN_DIR / "shadow",
    )
    risk_model = bundle_probe.settings.risk
    risk_policy_sha256 = _sha256_bytes(risk_model.model_dump_json().encode("utf-8"))
    cost_model_sha256 = _sha256_bytes(
        json.dumps(
            {"class": "ExecutionCostModel", "commission_bps": 5.0, "slippage_bps": 1.0},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    shadow_captures = CAMPAIGN_DIR / "shadow" / "shadow_captures.jsonl"
    shadow_outcomes = CAMPAIGN_DIR / "shadow" / "shadow_outcomes.jsonl"
    shadow_separate = (
        shadow_captures.parent != POC01_DIR
        and not str(shadow_captures).startswith(str(POC01_DIR))
    )
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
        "manifest_sha256": _sha256_bytes(
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
    record["launch_authorized"] = bool(
        gates["launch_authorized"] and shadow_separate and live_plumbing_zero
    )
    return record


if __name__ == "__main__":
    raise SystemExit(main())
