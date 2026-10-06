"""CAP-004 — the autonomous campaign runner.

One process, four phases, one frozen experiment:

    SEAL -> SETTLE -> SCORE -> VERIFY

and a mode for each: ``--seal``, ``--settle``, ``--score``, ``--verify``,
``--once`` (all four) and ``--continuous`` (poll, execute only due work, sleep).
``--status`` and ``--verify-only`` never write to the ledger.

What the runner refuses to do, by construction rather than by care:

* **seal twice.**  A slot is identified by ``decision_key`` over campaign, asset,
  decision time, horizon and analyst version.  A slot already in the ledger — the
  four adopted CAP-003 decisions included — is never sealed again, however many
  times the process restarts.
* **backfill.**  A slot older than the declared seal window is
  ``MISSED_DECISION_SLOT``.  The runner will not reconstruct a decision hours
  later and pretend it belonged to the slot, because the analyst would have been
  answering with information the slot never contained.
* **settle early.**  A horizon that has not closed is ``PENDING_MATURITY``.  There
  is no partial outcome and no last-candle substitute; a matured horizon whose bar
  is unavailable is ``OUTCOME_BLOCKED_DATA`` and stays retryable.
* **invent state.**  Every failure lands in a named ``*_BLOCKED`` / ``*_FAILED``
  state, is recorded, and stops the phase that needed it.  Nothing is filled in.
* **write on a broken chain.**  If the ledger does not re-derive, the campaign
  goes ``INTEGRITY_FAILURE`` and the runner stops writing.
* **change the experiment.**  A moved prompt digest, feature/schema version or
  rule version blocks sealing; a changed model splits the cohort instead of being
  folded into the same variant.

The analyst remains the LLM client: this runner writes the prompt package for a
due slot and seals the answer file when it exists.  The repository never
synthesises a decision, so that single file write is the only out-of-band step.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cap001_run as c1  # noqa: E402

from trading_bot.research import agentic_contracts as ac  # noqa: E402
from trading_bot.research import alpha_scorecard as asc  # noqa: E402
from trading_bot.research import campaign_lock as cl  # noqa: E402
from trading_bot.research import campaign_manifest as cm  # noqa: E402
from trading_bot.research import campaign_reporting as cr  # noqa: E402
from trading_bot.research import campaign_state as cs  # noqa: E402
from trading_bot.research import decision_ledger as dl  # noqa: E402
from trading_bot.research import decision_outcomes as do  # noqa: E402
from trading_bot.research import market_analyst_v1 as mav  # noqa: E402
from trading_bot.research import real_market_context as rmc  # noqa: E402

LEDGER_ROOT = REPO / "evidence" / "real_decisions"
REPORT_ROOT = REPO / "reports" / "cap004"
SLOT_DIR = REPORT_ROOT / "slots"
VERIFIER = REPO / "scripts" / "cap004_verify.py"
VERIFICATION_JSON = REPORT_ROOT / "CAP004_VERIFICATION.json"

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_STALE_FACTOR = 4

PHASES: tuple[str, ...] = ("seal", "settle", "score", "verify")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def now_seconds() -> int:
    return int(time.time())


def utc_iso(moment: int | None) -> str | None:
    if moment is None:
        return None
    return dt.datetime.fromtimestamp(int(moment), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_output(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return proc.stdout.strip()


def asset_key(asset: str) -> str:
    return asset.split(":")[-1]


def slot_answer_path(slot: int, asset: str, *, analyst: str = mav.PROMPT_VERSION) -> Path:
    return SLOT_DIR / f"ANALYST_ANSWER_{slot}_{asset_key(asset)}_{analyst}.json"


def slot_package_path(slot: int, asset: str) -> Path:
    return SLOT_DIR / f"ANALYST_PACKAGE_{slot}_{asset_key(asset)}.json"


def load_or_init_manifest(*, now: int) -> tuple[dict[str, Any], str]:
    manifest = cm.load_manifest(LEDGER_ROOT)
    if manifest is not None:
        return manifest, "LOADED"
    manifest = cm.build_manifest(created_at=now, code_commit=git_output("rev-parse", "HEAD"))
    cm.write_manifest(LEDGER_ROOT, manifest)
    return manifest, "CREATED"


def campaigns_assets_to_fetch(ledger: dl.DecisionLedger, *, need_seal: bool, now: int) -> list[str]:
    wanted: set[str] = set()
    if need_seal:
        wanted |= set(cm.CAMPAIGN_ASSETS)
    for item in ledger.decisions():
        pending = not ledger.has_outcome(str(item["decision_id"]), str(item["horizon"]))
        if pending and cs.maturity_state(
            decision_time=int(item["decision_time"]),
            horizon=str(item["horizon"]),
            now=now,
        )["matured"]:
            wanted.add(str(item["asset"]))
    return sorted(wanted)


def fetch_rows(assets: list[str], *, need_seal: bool) -> dict[str, dict[str, list[Any]]]:
    connector = rmc.make_connector()
    intervals = list(rmc.CONTRACT_INTERVALS) if need_seal else ["4h", "1D"]
    return {
        asset: {key: rmc.fetch_provider_ohlcv(connector, asset, key) for key in intervals}
        for asset in assets
    }


# --------------------------------------------------------------------------- #
# SEAL
# --------------------------------------------------------------------------- #


def seal_phase(
    ledger: dl.DecisionLedger,
    *,
    manifest: dict[str, Any],
    slot: int,
    now: int,
    sealing_allowed: bool,
    drift: dict[str, Any],
) -> dict[str, Any]:
    """Seal the due slot's answers, exactly once, inside the seal window."""
    result: dict[str, Any] = {
        "slot": slot,
        "slot_utc": utc_iso(slot),
        "sealed": [],
        "already_used": [],
        "missed": [],
        "pending_answers": [],
        "errors": [],
        "packages": [],
    }
    if not sealing_allowed:
        result["blocked"] = drift.get("status")
        return result

    delay = now - slot
    occupied = cm.occupied_decision_keys(ledger.decisions())
    within_window = delay <= cm.SEAL_WINDOW_SECONDS
    result["delay_seconds"] = delay
    result["within_seal_window"] = within_window

    for asset in cm.CAMPAIGN_ASSETS:
        key = cm.decision_key(
            asset=asset,
            decision_time=slot,
            horizon=cm.HORIZON,
            analyst_version=mav.PROMPT_VERSION,
        )
        if key in occupied:
            result["already_used"].append({"asset": asset, "slot_key": key})
            continue
        if not within_window:
            result["missed"].append(
                {
                    "asset": asset,
                    "reasons": ["SEAL_WINDOW_EXPIRED"],
                    "required_action": "MISSED_DECISION_SLOT",
                    "slot": slot,
                }
            )
            continue
        if not slot_answer_path(slot, asset).is_file():
            result["pending_answers"].append(
                {"asset": asset, "expected_answer_path": str(slot_answer_path(slot, asset))}
            )
    if not within_window:
        return result
    # A fully consumed slot has nothing to answer and costs no market data call.
    if not result["pending_answers"]:
        return result

    # Build the real context for the due slot and write the prompt packages.
    assets = sorted({item["asset"] for item in result["pending_answers"]})
    rows_by_asset = fetch_rows(assets, need_seal=True)
    decision_time = slot
    decision_ms = slot * 1_000
    btc_rows_4h = rmc.completed_rows(
        rows_by_asset["BINANCE:BTCUSDT"]["4h"], decision_ms=decision_ms, interval_key="4h"
    )
    artifacts: dict[str, Any] = {}
    for asset in assets:
        rows = {
            key: rmc.completed_rows(rows_by_asset[asset][key], decision_ms=decision_ms, interval_key=key)
            for key in rmc.CONTRACT_INTERVALS
        }
        artifacts[asset] = rmc.build_real_snapshot_artifact(
            asset=asset,
            decision_time=decision_time,
            rows_by_interval=rows,
            reference_rows_4h=btc_rows_4h,
        )
    result["gate"] = {
        asset: rmc.evaluate_g_real_market_context(
            artifacts[asset], snapshot_at=decision_time
        )["status"]
        for asset in artifacts
    }
    if any(status != "PASS" for status in result["gate"].values()):
        result["errors"].append(
            {
                "code": "DATA_BLOCKED",
                "detail": "G_REAL_MARKET_CONTEXT failed for at least one asset",
                "gate": result["gate"],
            }
        )

    for asset in assets:
        artifact = artifacts[asset]
        c1.write_json(slot_package_path(slot, asset), _package(slot, asset, artifact, delay))
        result["packages"].append(str(slot_package_path(slot, asset)))
        if result["gate"].get(asset) != "PASS":
            continue
        answer = slot_answer_path(slot, asset)
        payload = json.loads(answer.read_text(encoding="utf-8"))
        if int(payload.get("decision_time", 0)) != slot:
            result["errors"].append(
                {
                    "code": "ANALYST_FAILED",
                    "asset": asset,
                    "detail": "answer decision_time does not match the due slot",
                    "answer_decision_time": payload.get("decision_time"),
                    "required_action": "MISSED_DECISION_SLOT",
                }
            )
            continue
        provenance = cm.build_campaign_provenance(code_commit=git_output("rev-parse", "HEAD"))
        record = mav.seal_analyst_decision(
            payload,
            snapshot_hash=artifact["snapshot_hash"],
            raw_data_hash=artifact["raw_evidence_hash"],
            critic_output={"note": "single-analyst campaign; no separate critic model in V1"},
            provenance=provenance,
        )
        if ledger.has_decision(record.decision_hash):
            result["already_used"].append({"asset": asset, "decision_id": None})
            continue
        entry = dl.decision_entry(
            record=record,
            snapshot_artifact=artifact,
            provenance=provenance,
            raw_evidence_path=f"{dl.RAW_EVIDENCE_DIRNAME}/{artifact['snapshot_hash']}.json",
            recorded_at=now,
            scheduled_decision_time=slot,
            actual_execution_time=now,
        )
        (ledger.root / dl.RAW_EVIDENCE_DIRNAME).mkdir(parents=True, exist_ok=True)
        c1.write_json(ledger.root / entry["raw_evidence_path"], artifact["raw_evidence"])
        cs.append_raw_evidence(
            ledger.root,
            cs.raw_evidence_entry(
                raw_evidence=artifact["raw_evidence"],
                snapshot_hash=artifact["snapshot_hash"],
                asset=asset,
                raw_evidence_hash=artifact["raw_evidence_hash"],
                local_path=entry["raw_evidence_path"],
                recorded_at=now,
            ),
        )
        ledger.append_decision(entry)
        result["sealed"].append(
            {
                "asset": asset,
                "decision_id": entry["decision_id"],
                "decision": record.decision,
                "horizon": entry["horizon"],
                "delay_seconds": delay,
                "slot_key": cm.decision_key(
                    asset=asset,
                    decision_time=slot,
                    horizon=cm.HORIZON,
                    analyst_version=mav.PROMPT_VERSION,
                ),
                "raw_evidence_manifest": cs.RAW_EVIDENCE_MANIFEST_FILENAME,
            }
        )
    return result


def _package(slot: int, asset: str, artifact: dict[str, Any], delay: int) -> dict[str, Any]:
    return {
        "campaign": cm.CAMPAIGN_ID,
        "campaign_version": cm.CAMPAIGN_VERSION,
        "slot": slot,
        "slot_utc": utc_iso(slot),
        "horizon": cm.HORIZON,
        "delay_seconds": delay,
        "asset": asset,
        "prompt_version": mav.PROMPT_VERSION,
        "prompt_digest": mav.prompt_digest(),
        "system_prompt": mav.SYSTEM_PROMPT,
        "output_fields": list(mav.ANALYST_OUTPUT_FIELDS),
        "allowed_decisions": list(mav.ALLOWED_DECISIONS),
        "allowed_horizons": list(mav.HORIZONS),
        "snapshot_hash": artifact["snapshot_hash"],
        "raw_data_hash": artifact["raw_evidence_hash"],
        "snapshot": artifact["snapshot"],
        "provenance_required": list(cm.CAMPAIGN_PROVENANCE_FIELDS),
        "answer_path": str(slot_answer_path(slot, asset)),
        "instruction": (
            "write the frozen analyst's structured answer to answer_path; the runner will seal it "
            "inside the declared seal window and will never fill a missed slot"
        ),
    }


def missed_slots(
    ledger: dl.DecisionLedger, manifest: dict[str, Any], *, now: int
) -> list[dict[str, Any]]:
    """Slots that closed without a decision and can no longer be sealed."""
    occupied = cm.occupied_decision_keys(ledger.decisions())
    start = int(manifest.get("campaign_start", now))
    start_day = dt.datetime.fromtimestamp(start, dt.UTC).date()
    end_day = dt.datetime.fromtimestamp(cm.due_decision_slot(now), dt.UTC).date()
    missed: list[dict[str, Any]] = []
    day = start_day
    while day <= end_day:
        slot = cm.decision_slot_unix(day)
        if slot < start:
            day += dt.timedelta(days=1)
            continue
        if now - slot <= cm.SEAL_WINDOW_SECONDS:
            day += dt.timedelta(days=1)
            continue
        for asset in cm.CAMPAIGN_ASSETS:
            key = cm.decision_key(
                asset=asset,
                decision_time=slot,
                horizon=cm.HORIZON,
                analyst_version=mav.PROMPT_VERSION,
            )
            if key not in occupied:
                missed.append(
                    {
                        "code": cs.MISSED_DECISION_SLOT,
                        "asset": asset,
                        "slot": slot,
                        "slot_utc": utc_iso(slot),
                        "required_action": "NONE_NO_BACKFILL",
                    }
                )
        day += dt.timedelta(days=1)
    return missed


# --------------------------------------------------------------------------- #
# SETTLE
# --------------------------------------------------------------------------- #


def settle_phase(
    ledger: dl.DecisionLedger,
    *,
    rows_by_asset: dict[str, dict[str, list[Any]]],
    now: int,
) -> dict[str, Any]:
    """Close every matured horizon with the deterministic evaluator.  Once."""
    settled: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for entry in ledger.pending_decisions():
        decision_id = str(entry["decision_id"])
        horizon = str(entry["horizon"])
        asset = str(entry["asset"])
        maturity = cs.maturity_state(
            decision_time=int(entry["decision_time"]), horizon=horizon, now=now
        )
        if not maturity["matured"]:
            pending.append(
                {
                    "decision_id": decision_id,
                    "horizon": horizon,
                    "state": cs.STATE_PENDING_MATURITY,
                    "maturity_time": maturity["maturity_time"],
                    "seconds_to_maturity": maturity["seconds_to_maturity"],
                }
            )
            continue
        if asset not in rows_by_asset:
            blocked.append({"decision_id": decision_id, "code": "OUTCOME_BLOCKED_DATA"})
            errors.append(
                {
                    "code": "OUTCOME_BLOCKED_DATA",
                    "decision_id": decision_id,
                    "detail": "no market rows were fetched for this asset this cycle",
                }
            )
            continue
        rows = rows_by_asset[asset]["4h"]
        daily = rows_by_asset[asset]["1D"]
        record = dl.record_from_entry(entry)
        try:
            outcome = do.evaluate_decision(
                record=record, asset=asset, horizon=horizon, rows=rows
            )
        except do.HorizonNotMaturedError as exc:
            blocked.append(
                {
                    "decision_id": decision_id,
                    "code": "OUTCOME_BLOCKED_DATA",
                    "detail": str(exc),
                    "required_action": "RETRY_NEXT_CYCLE",
                }
            )
            errors.append(
                {
                    "code": "OUTCOME_BLOCKED_DATA",
                    "decision_id": decision_id,
                    "detail": str(exc),
                }
            )
            continue
        except Exception as exc:
            errors.append(
                {"code": "EVALUATION_FAILED", "decision_id": decision_id, "detail": repr(exc)}
            )
            continue
        try:
            performance = do.build_performance(
                record=record, outcome=outcome, rows_4h=rows, daily_rows=daily
            )
        except Exception as exc:
            errors.append(
                {"code": "EVALUATION_FAILED", "decision_id": decision_id, "detail": repr(exc)}
            )
            continue
        ledger.append_outcome(outcome)
        ledger.append_evaluation(performance)
        settled.append(
            {
                "decision_id": decision_id,
                "asset": asset,
                "horizon": horizon,
                "outcome": outcome.outcome,
                "net_return": outcome.net_return,
                "outcome_hash": outcome.outcome_hash,
                "evaluation_hash": performance.evaluation_hash,
            }
        )
    return {"settled": settled, "pending": pending, "blocked": blocked, "errors": errors}


# --------------------------------------------------------------------------- #
# SCORE
# --------------------------------------------------------------------------- #


def score_phase(
    ledger: dl.DecisionLedger, *, manifest: dict[str, Any], now: int, errors: list[dict[str, Any]]
) -> dict[str, Any]:
    performances = ledger.rebuilt_evaluations()
    scorecard = asc.alpha_scorecard(performances)
    metrics = cs.campaign_metrics(performances)
    no_trade = cs.no_trade_analysis(performances)
    counters = cs.campaign_counters(ledger, now=now)
    drift = cm.detect_drift(manifest)
    model_drift = cm.detect_model_drift(manifest, ledger.decisions())
    chain = ledger.verify_chain()
    raw = cs.raw_evidence_status(ledger.root, decisions=ledger.decisions())
    status = cs.campaign_status_name(
        counters=counters, chain_verified=chain["status"] == "INTACT", drift=drift
    )

    c1.write_json(REPORT_ROOT / "CAMPAIGN_METRICS.json", metrics)
    c1.write_json(REPORT_ROOT / "NO_TRADE_SELECTIVITY.json", no_trade)
    c1.write_json(REPORT_ROOT / "ALPHA_SCORECARD.json", scorecard)
    c1.write_md(REPORT_ROOT / "ALPHA_SCORECARD.md", _scorecard_md(scorecard))

    checkpoints: list[dict[str, Any]] = []
    for checkpoint in asc.CHECKPOINTS:
        if len(performances) < checkpoint:
            continue
        payload = cr.build_checkpoint_payload(
            checkpoint=checkpoint,
            performances=performances,
            scorecard=scorecard,
            metrics=metrics,
            no_trade=no_trade,
            counters=counters,
            drift=drift,
            model_drift=model_drift,
            now=now,
            errors=errors,
        )
        checkpoints.append(cr.write_checkpoint(ledger.root, payload))

    return {
        "scorecard": scorecard,
        "metrics": metrics,
        "no_trade": no_trade,
        "counters": counters,
        "drift": drift,
        "model_drift": model_drift,
        "chain": chain,
        "raw_evidence": raw,
        "status": status,
        "checkpoints": checkpoints,
    }


def _scorecard_md(scorecard: dict[str, Any]) -> str:
    lines = ["# ALPHA_SCORECARD (CAP-004 campaign)", ""]
    lines.append(f"- evaluated decisions: {scorecard['n_decisions_evaluated']}")
    lines.append(f"- gate: {scorecard['gate']['status']} ({scorecard['gate']['conclusion']})")
    lines.append(f"- alpha claimed: {scorecard['alpha_claimed']}")
    lines.append(f"- profitability: {scorecard['profitability_status']}")
    lines.append("")
    lines.append("| comparator | n | mean net | edge vs A |")
    lines.append("| --- | --- | --- | --- |")
    for baseline_id in (
        do.BASELINE_ID_DETERMINISTIC,
        do.BASELINE_ID_BUY_AND_HOLD,
        do.BASELINE_ID_RANDOM_MATCHED,
    ):
        stats = scorecard["comparators"].get(baseline_id) or {}
        lines.append(
            f"| {baseline_id} | {stats.get('n', 0)} | {stats.get('mean_net_return')} | "
            f"{scorecard['incremental_edges'].get(baseline_id)} |"
        )
    lines.append("")
    lines.append(f"next step: {scorecard['next_step']}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# VERIFY
# --------------------------------------------------------------------------- #


def verify_phase() -> dict[str, Any]:
    """Run the independent verifier as a separate process (builder != verifier)."""
    if not VERIFIER.is_file():
        return {"status": "NOT_RUN", "reason": "verifier not found"}
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO / 'src'}{os.pathsep}{REPO / 'scripts'}"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(VERIFIER)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if VERIFICATION_JSON.is_file():
        payload = json.loads(VERIFICATION_JSON.read_text(encoding="utf-8"))
        return {
            "status": payload.get("status"),
            "passed": payload.get("passed"),
            "total": payload.get("total"),
            "mismatches": payload.get("mismatches"),
            "false_success": payload.get("false_success"),
            "exit_code": proc.returncode,
        }
    return {
        "status": "NOT_RUN",
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-400:],
        "stderr_tail": proc.stderr[-400:],
    }


# --------------------------------------------------------------------------- #
# the cycle
# --------------------------------------------------------------------------- #


def run_cycle(
    *,
    modes: tuple[str, ...],
    now: int,
    cycle: int,
    store: dict[str, int],
) -> dict[str, Any]:
    manifest, manifest_action = load_or_init_manifest(now=now)
    ledger = dl.DecisionLedger(LEDGER_ROOT)
    drift = cm.detect_drift(manifest)
    model_drift = cm.detect_model_drift(manifest, ledger.decisions())
    chain = ledger.verify_chain()

    errors: list[dict[str, Any]] = []
    chain_ok = chain["status"] == "INTACT"
    sealing_allowed = chain_ok and drift["status"] == "NO_DRIFT"
    if not chain_ok:
        errors.append(
            {"code": "INTEGRITY_FAILURE", "detail": "ledger chain does not re-derive", "broken": chain["broken"]}
        )
    if drift["status"] != "NO_DRIFT":
        errors.append(
            {"code": drift["status"], "detail": "frozen manifest knob changed", "drifted": drift["drifted"]}
        )

    result: dict[str, Any] = {
        "cycle": cycle,
        "day": cr.utc_day(now),
        "started_at": now,
        "started_at_utc": utc_iso(now),
        "modes": list(modes),
        "manifest_action": manifest_action,
        "manifest_digest": cm.manifest_digest(manifest),
        "errors": errors,
    }

    slot = cm.due_decision_slot(now)
    need_seal = "seal" in modes and sealing_allowed
    assets = campaigns_assets_to_fetch(ledger, need_seal=need_seal, now=now)
    rows_by_asset: dict[str, dict[str, list[Any]]] = {}
    if assets:
        try:
            rows_by_asset = fetch_rows(assets, need_seal=need_seal)
        except Exception as exc:
            errors.append({"code": "DATA_BLOCKED", "detail": repr(exc)})
            result["data_blocked"] = True

    # Adopt any local raw evidence the manifest does not cover yet (never re-fetched).
    result["raw_evidence_registration"] = cs.register_unregistered_raw_evidence(
        ledger.root, decisions=ledger.decisions(), now=now
    )

    if "seal" in modes:
        result["seal"] = seal_phase(
            ledger,
            manifest=manifest,
            slot=slot,
            now=now,
            sealing_allowed=sealing_allowed,
            drift=drift,
        )
        result["errors"].extend(result["seal"]["errors"])
        result["missed_slots"] = missed_slots(ledger, manifest, now=now)
        result["errors"].extend(result["missed_slots"])
        if result["seal"]["sealed"]:
            store["last_seal"] = now

    if "settle" in modes and "data_blocked" not in result:
        result["settle"] = settle_phase(ledger, rows_by_asset=rows_by_asset, now=now)
        result["errors"].extend(result["settle"]["errors"])
        if result["settle"]["settled"]:
            store["last_settle"] = now

    if "score" in modes:
        result["score"] = score_phase(ledger, manifest=manifest, now=now, errors=result["errors"])
        store["last_score"] = now
    else:
        result["score"] = {
            "status": cs.campaign_status_name(
                counters=cs.campaign_counters(ledger, now=now, chain_verified=chain_ok),
                chain_verified=chain_ok,
                drift=drift,
            ),
            "chain": chain,
            "counters": cs.campaign_counters(ledger, now=now, chain_verified=chain_ok),
            "drift": drift,
            "model_drift": model_drift,
            "scorecard": asc.alpha_scorecard(ledger.rebuilt_evaluations()),
            "metrics": cs.campaign_metrics(ledger.rebuilt_evaluations()),
            "raw_evidence": cs.raw_evidence_status(ledger.root, decisions=ledger.decisions()),
            "checkpoints": [],
        }

    score = result["score"]
    counters = score["counters"]
    status = score["status"]
    maturity_times = [
        int(item["maturity_time"])
        for item in counters["decision_states"]
        if item["maturity"] != "MATURED"
    ]

    heartbeat = cr.heartbeat_payload(
        campaign_id=cm.CAMPAIGN_ID,
        campaign_version=cm.CAMPAIGN_VERSION,
        now=now,
        process_status="RUNNING" if status in ("RUNNING", "INITIALIZING") else status,
        counters=counters,
        cycle=cycle,
        interval_seconds=store["interval_seconds"],
        next_decision_slot=cm.next_decision_slot(now),
        next_maturity=min(maturity_times) if maturity_times else None,
        last_successful_seal=store.get("last_seal"),
        last_successful_settle=store.get("last_settle"),
        last_successful_score=store.get("last_score"),
        last_successful_verify=store.get("last_verify"),
        errors=result["errors"],
        modes_completed=list(modes),
    )
    cr.write_heartbeat(LEDGER_ROOT, heartbeat)

    status_payload = cr.status_payload(
        manifest=manifest,
        counters=counters,
        scorecard=score["scorecard"],
        drift=score["drift"],
        model_drift=score["model_drift"],
        raw_evidence=score["raw_evidence"],
        chain=score.get("chain") or chain,
        status=status,
        now=now,
        next_decision_slot=cm.next_decision_slot(now),
        errors=result["errors"],
        heartbeat=heartbeat,
    )
    c1.write_json(REPORT_ROOT / "CAMPAIGN_STATUS.json", status_payload)
    c1.write_md(REPORT_ROOT / "CAMPAIGN_STATUS.md", cr.render_status_md(status_payload, metrics=score["metrics"]))

    daily = cr.daily_report(
        day=cr.utc_day(now),
        ledger=ledger,
        cycles=cr.read_cycle_journal(REPORT_ROOT),
        chain=score.get("chain") or chain,
        drift=score["drift"],
        verification=None,
    )
    cr.write_daily_report(REPORT_ROOT, daily)

    # The independent verifier runs last: it must observe every artifact this
    # cycle produced (heartbeat, status, daily), never a half-written state.
    if "verify" in modes:
        result["verify"] = verify_phase()
        if result["verify"].get("status") == "PASS":
            store["last_verify"] = now
        daily = cr.daily_report(
            day=cr.utc_day(now),
            ledger=ledger,
            cycles=cr.read_cycle_journal(REPORT_ROOT),
            chain=score.get("chain") or chain,
            drift=score["drift"],
            verification=result["verify"],
        )
        cr.write_daily_report(REPORT_ROOT, daily)

    result["campaign_status"] = status
    result["counters"] = counters
    result["heartbeat"] = heartbeat
    result["daily"] = daily
    result["finished_at"] = now_seconds()
    cr.write_cycle_record(REPORT_ROOT, result)
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CAP-004 autonomous campaign runner")
    parser.add_argument("--once", action="store_true", help="run seal, settle, score and verify once")
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--settle", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--status", action="store_true", help="print the campaign status and exit")
    parser.add_argument("--verify-only", action="store_true", help="read-only integrity check")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-cycles", type=int, default=0, help="0 = unbounded")
    return parser.parse_args(argv)


def selected_modes(args: argparse.Namespace) -> tuple[str, ...]:
    chosen = tuple(name for name in PHASES if getattr(args, name))
    if args.once or args.continuous or not chosen:
        return PHASES
    return chosen


def print_status(now: int) -> int:
    ledger = dl.DecisionLedger(LEDGER_ROOT)
    manifest = cm.load_manifest(LEDGER_ROOT)
    if manifest is None:
        print("CAMPAIGN STATUS = NOT_INITIALIZED")
        return 0
    counters = cs.campaign_counters(ledger, now=now)
    drift = cm.detect_drift(manifest)
    status = cs.campaign_status_name(
        counters=counters, chain_verified=ledger.verify_chain()["status"] == "INTACT", drift=drift
    )
    heartbeat = cr.read_heartbeat(LEDGER_ROOT)
    print(f"campaign = {cm.CAMPAIGN_ID} v{cm.CAMPAIGN_VERSION}")
    print(f"status = {status}   chain = {ledger.verify_chain()['status']}   drift = {drift['status']}")
    for key in (
        "sealed_decisions",
        "pending_decisions",
        "matured_decisions",
        "matured_unsettled",
        "settled_outcomes",
        "evaluated_decisions",
        "verified_evaluations",
    ):
        print(f"  {key} = {counters[key]}")
    print(
        f"  analyst: LONG={counters['long_count']} SHORT={counters['short_count']} "
        f"NO_TRADE={counters['no_trade_count']}"
    )
    print(
        f"  next slot = {utc_iso(cm.next_decision_slot(now))}   "
        f"heartbeat age = {cr.heartbeat_age_seconds(heartbeat, now=now)}s"
    )
    print(f"  trades authorized = {ac.TRADES_AUTHORIZED}   alpha claimed = {ac.ALPHA_CLAIMED}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = now_seconds()

    if args.status:
        return print_status(now)
    if args.verify_only:
        result = verify_phase()
        print(f"VERIFY_ONLY = {result.get('status')}  {result}")
        return 0 if result.get("status") == "PASS" else 1

    lock = cl.CampaignLock(
        LEDGER_ROOT,
        campaign_id=cm.CAMPAIGN_ID,
        stale_after_seconds=max(
            args.interval_seconds * DEFAULT_STALE_FACTOR, cl.DEFAULT_STALE_AFTER_SECONDS
        ),
    )
    acquisition = lock.acquire(now=now)
    if not acquisition["acquired"]:
        print(f"ALREADY_RUNNING holder={acquisition.get('holder')}")
        return 0
    store: dict[str, int] = {"interval_seconds": args.interval_seconds}
    modes = selected_modes(args)
    cycles_done = 0
    index = 0
    try:
        while True:
            index += 1
            cycle_now = now_seconds()
            result = run_cycle(modes=modes, now=cycle_now, cycle=index, store=store)
            cycles_done += 1
            _print_cycle(result)
            lock.renew(now=now_seconds())
            if not args.continuous:
                break
            if lock.stop_requested():
                print("STOP requested; leaving continuous mode at a cycle boundary")
                break
            if args.max_cycles and cycles_done >= args.max_cycles:
                break
            time.sleep(max(1, args.interval_seconds))
    finally:
        lock.release()
    return 0


def _print_cycle(result: dict[str, Any]) -> None:
    print(f"CAP-004 CAMPAIGN CYCLE {result['cycle']}  modes={result['modes']}")
    seal = result.get("seal") or {}
    if seal:
        print(f"  slot={seal.get('slot_utc')} delay={seal.get('delay_seconds')}s")
        print(f"  sealed={len(seal.get('sealed', []))} already_used={len(seal.get('already_used', []))}")
        print(
            f"  awaiting_answer={len(seal.get('pending_answers', []))} "
            f"missed={len(seal.get('missed', []))}"
        )
    settle = result.get("settle") or {}
    if settle:
        print(
            f"  settled={len(settle.get('settled', []))} "
            f"pending_maturity={len(settle.get('pending', []))} "
            f"blocked={len(settle.get('blocked', []))}"
        )
    counters = result.get("counters") or {}
    print(f"  status={result.get('campaign_status')}")
    print(
        "  population: "
        + " ".join(
            f"{key}={counters.get(key)}"
            for key in ("sealed_decisions", "matured_decisions", "settled_outcomes", "evaluated_decisions")
        )
    )
    score = result.get("score") or {}
    checkpoints = score.get("checkpoints") or []
    if checkpoints:
        print(f"  checkpoints={[item['status'] for item in checkpoints]}")
    verify = result.get("verify")
    if verify:
        print(f"  verify={verify.get('status')} checks={verify.get('passed')}/{verify.get('total')}")
    errors = result.get("errors") or []
    print(f"  errors={[item.get('code') for item in errors]}")


if __name__ == "__main__":
    raise SystemExit(main())
