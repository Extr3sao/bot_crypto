"""CAP-004 — heartbeat, campaign status, daily rollup and checkpoints.

Unattended running is only trustworthy if the run can be observed and its
milestones are immutable:

* **Heartbeat** — a small, atomically replaced file that says whether the runner
  is alive, when it last sealed / settled / scored / verified, and what it is
  waiting for.  An absent or stale heartbeat must read as "not running", never as
  "probably fine".
* **Status** — the campaign dashboard at ``reports/cap004/``: age, every
  population counted separately, checkpoint progress, the next slot, the next
  maturity, the analyst's direction mix, errors and chain status.
* **Daily rollup** — per UTC day: decisions sealed, outcomes matured, evaluations
  completed, failures, drift and verification.  Derived from the ledger plus the
  cycle journal, so it is reproducible rather than remembered.
* **Checkpoints** — ``CHECKPOINT_020/050/100`` are written **once per population**.
  Both the file and its markdown mirror carry ``decision_set_hash``; a later run
  that finds a different population under the same checkpoint reports
  ``CHECKPOINT_CONFLICT`` instead of silently rewriting history.

Reports live under ``reports/`` (regenerable, gitignored); checkpoints live under
``evidence/real_decisions/checkpoints/`` because they are evidence.  No status
vocabulary here contains a promotional word.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import decision_outcomes as do

__all__ = [
    "CHECKPOINT_DIRNAME",
    "CHECKPOINT_JSON_VERSION",
    "CYCLE_JOURNAL_FILENAME",
    "HEARTBEAT_FILENAME",
    "build_checkpoint_payload",
    "checkpoint_decision_set_hash",
    "checkpoint_decision_set_hash_from_records",
    "checkpoint_dir",
    "checkpoint_md",
    "daily_report",
    "heartbeat_age_seconds",
    "heartbeat_payload",
    "read_checkpoint",
    "read_cycle_journal",
    "read_heartbeat",
    "render_status_md",
    "status_payload",
    "utc_day",
    "write_checkpoint",
    "write_cycle_record",
    "write_daily_report",
    "write_heartbeat",
    "write_json_atomic",
]

HEARTBEAT_FILENAME = "heartbeat.json"
CHECKPOINT_DIRNAME = "checkpoints"
CYCLE_JOURNAL_FILENAME = "cycles.jsonl"
CHECKPOINT_JSON_VERSION = "CAMPAIGN_CHECKPOINT_V1"


# --------------------------------------------------------------------------- #
# §1 — atomic writes
# --------------------------------------------------------------------------- #


def write_json_atomic(path: Path, payload: Any) -> Path:
    """Write via a temp file + replace, so a crash never leaves a half report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    return path


def utc_day(moment: int) -> str:
    return dt.datetime.fromtimestamp(int(moment), dt.UTC).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# §2 — heartbeat
# --------------------------------------------------------------------------- #


def heartbeat_payload(
    *,
    campaign_id: str,
    campaign_version: str,
    now: int,
    process_status: str,
    counters: Mapping[str, Any],
    cycle: int,
    interval_seconds: int,
    next_decision_slot: int,
    next_maturity: int | None,
    last_successful_seal: int | None = None,
    last_successful_settle: int | None = None,
    last_successful_score: int | None = None,
    last_successful_verify: int | None = None,
    errors: Sequence[Mapping[str, Any]] = (),
    modes_completed: Sequence[str] = (),
) -> dict[str, Any]:
    """The liveness record: what the runner is, and what it is waiting for."""
    return {
        "campaign_id": campaign_id,
        "campaign_version": campaign_version,
        "timestamp": int(now),
        "timestamp_utc": dt.datetime.fromtimestamp(int(now), dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "process_status": process_status,
        "cycle": int(cycle),
        "interval_seconds": int(interval_seconds),
        "modes_completed": list(modes_completed),
        "last_successful_seal": last_successful_seal,
        "last_successful_settle": last_successful_settle,
        "last_successful_score": last_successful_score,
        "last_successful_verify": last_successful_verify,
        "next_decision_slot": int(next_decision_slot),
        "next_decision_slot_utc": dt.datetime.fromtimestamp(
            int(next_decision_slot), dt.UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "next_maturity": next_maturity,
        "pending_maturities": int(counters.get("pending_decisions", 0)),
        "matured_unsettled": int(counters.get("matured_unsettled", 0)),
        "population": {
            key: counters.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "errors": [dict(item) for item in errors],
    }


def write_heartbeat(root: Path, payload: Mapping[str, Any]) -> Path:
    return write_json_atomic(Path(root) / HEARTBEAT_FILENAME, payload)


def read_heartbeat(root: Path) -> dict[str, Any] | None:
    path = Path(root) / HEARTBEAT_FILENAME
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def heartbeat_age_seconds(payload: Mapping[str, Any] | None, *, now: int) -> int | None:
    if payload is None or payload.get("timestamp") is None:
        return None
    return int(now) - int(payload["timestamp"])


# --------------------------------------------------------------------------- #
# §3 — cycle journal
# --------------------------------------------------------------------------- #


def write_cycle_record(root: Path, record: Mapping[str, Any]) -> None:
    """Append one cycle to the local journal that the daily rollup reads."""
    path = Path(root) / CYCLE_JOURNAL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(record), sort_keys=True, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def read_cycle_journal(root: Path) -> list[dict[str, Any]]:
    path = Path(root) / CYCLE_JOURNAL_FILENAME
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# --------------------------------------------------------------------------- #
# §4 — campaign status
# --------------------------------------------------------------------------- #


def status_payload(
    *,
    manifest: Mapping[str, Any],
    counters: Mapping[str, Any],
    scorecard: Mapping[str, Any],
    drift: Mapping[str, Any],
    model_drift: Mapping[str, Any],
    raw_evidence: Mapping[str, Any],
    chain: Mapping[str, Any],
    status: str,
    now: int,
    next_decision_slot: int | None = None,
    errors: Sequence[Mapping[str, Any]] = (),
    heartbeat: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The campaign dashboard payload (requirement: no single denominator)."""
    states = counters.get("decision_states") or []
    maturity_times = [
        int(item["maturity_time"]) for item in states if item["maturity"] != "MATURED"
    ]
    evaluated = int(counters.get("evaluated_decisions", 0))
    reached = [point for point in asc.CHECKPOINTS if evaluated >= point]
    campaign_start = int(manifest.get("campaign_start", now))
    return {
        "campaign_id": manifest.get("campaign_id"),
        "campaign_version": manifest.get("campaign_version"),
        "campaign_status": status,
        "as_of": int(now),
        "as_of_utc": dt.datetime.fromtimestamp(int(now), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "campaign_age_seconds": int(now) - campaign_start,
        "campaign_age_days": round((int(now) - campaign_start) / 86_400, 3),
        "population": {
            "sealed_decisions": counters.get("sealed_decisions"),
            "pending_decisions": counters.get("pending_decisions"),
            "matured_decisions": counters.get("matured_decisions"),
            "matured_unsettled": counters.get("matured_unsettled"),
            "settled_outcomes": counters.get("settled_outcomes"),
            "evaluated_decisions": counters.get("evaluated_decisions"),
            "verified_evaluations": counters.get("verified_evaluations"),
        },
        "denominator_note": (
            "sealed, matured, settled and evaluated are different populations; none of them is "
            "the campaign total"
        ),
        "analyst_distribution": {
            "LONG": counters.get("long_count"),
            "SHORT": counters.get("short_count"),
            "NO_TRADE": counters.get("no_trade_count"),
        },
        # Canonical counter names, so a consumer never has to translate the
        # display distribution back to the machine vocabulary.
        "direction_counts": {
            "long_count": counters.get("long_count"),
            "short_count": counters.get("short_count"),
            "no_trade_count": counters.get("no_trade_count"),
        },
        "cohorts": counters.get("by_cohort"),
        "by_asset": counters.get("by_asset"),
        "by_horizon": counters.get("by_horizon"),
        "checkpoint_progress": {
            "checkpoints": list(asc.CHECKPOINTS),
            "checkpoint_reached": max(reached) if reached else 0,
            "next_checkpoint": scorecard.get("sample", {}).get("next_checkpoint"),
            "min_evaluable_decisions": asc.MIN_EVALUABLE_DECISIONS,
        },
        "next_decision_slot": next_decision_slot,
        "next_maturity": min(maturity_times) if maturity_times else None,
        "next_maturity_utc": (
            dt.datetime.fromtimestamp(min(maturity_times), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if maturity_times
            else None
        ),
        "chain_status": chain.get("status"),
        "chain_broken": chain.get("broken"),
        "provenance_status": (
            "COMPLETE" if model_drift.get("status") == "NO_DRIFT" else str(model_drift.get("status"))
        ),
        "drift_status": drift.get("status"),
        "drift_knobs": drift.get("drifted"),
        "model_drift": model_drift,
        "raw_evidence_status": raw_evidence.get("status"),
        "raw_evidence_counts": raw_evidence.get("counts"),
        "primary_metric": manifest.get("primary_metric"),
        "g_agentic_edge": scorecard.get("gate"),
        "alpha_claimed": scorecard.get("alpha_claimed"),
        "profitability_status": scorecard.get("profitability_status"),
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "economic_state_note": "docs/research/ECONOMIC_STATE.json is never written by the campaign",
        "heartbeat_age_seconds": heartbeat_age_seconds(heartbeat, now=now),
        "errors": [dict(item) for item in errors],
    }


def render_status_md(payload: Mapping[str, Any], *, metrics: Mapping[str, Any]) -> str:
    """A one-screen markdown view of the campaign."""
    population = payload.get("population") or {}
    ages = payload.get("campaign_age_days")
    lines = [
        f"# Campaign status — {payload.get('campaign_id')}",
        "",
        f"- status: **{payload.get('campaign_status')}**",
        f"- age: {ages} days",
        f"- as of: {payload.get('as_of_utc')}",
        f"- chain: {payload.get('chain_status')}   drift: {payload.get('drift_status')}",
        f"- raw evidence: {payload.get('raw_evidence_status')}",
        "",
        "## Population (never one denominator)",
        "",
        "| population | count |",
        "| --- | --- |",
    ]
    for key, value in population.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Analyst distribution",
            "",
            "| direction | count |",
            "| --- | --- |",
        ]
    )
    for key, value in (payload.get("analyst_distribution") or {}).items():
        lines.append(f"| {key} | {value} |")
    progress = payload.get("checkpoint_progress") or {}
    lines.extend(
        [
            "",
            "## Progress",
            "",
            f"- checkpoints: {progress.get('checkpoints')}",
            f"- reached: {progress.get('checkpoint_reached')}",
            f"- next: {progress.get('next_checkpoint')}",
            f"- floor for any edge verdict: {progress.get('min_evaluable_decisions')}",
            f"- next decision slot: {payload.get('next_decision_slot')}",
            f"- next maturity: {payload.get('next_maturity_utc')}",
            "",
            "## G_AGENTIC_EDGE",
            "",
            f"- {(payload.get('g_agentic_edge') or {}).get('status')} "
            f"({(payload.get('g_agentic_edge') or {}).get('conclusion')})",
            f"- alpha claimed: {payload.get('alpha_claimed')}",
            f"- profitability: {payload.get('profitability_status')}",
            f"- trades authorized: {payload.get('trades_authorized')}",
            "",
            "## Diagnostics (not the primary metric)",
            "",
            f"- net mean: {(metrics.get('net') or {}).get('mean')}",
            f"- net median: {(metrics.get('net') or {}).get('median')}",
            f"- direction accuracy: {metrics.get('direction_accuracy')}",
            f"- per-decision sharpe: {(metrics.get('net') or {}).get('per_decision_sharpe')} "
            f"({(metrics.get('net') or {}).get('sharpe_status')})",
            f"- sample warnings: {metrics.get('sample_warnings')}",
            "",
        ]
    )
    errors = payload.get("errors") or []
    lines.append("## Errors")
    lines.append("")
    if errors:
        for item in errors:
            lines.append(f"- {item}")
    else:
        lines.append("- none recorded this cycle")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# §5 — daily rollup
# --------------------------------------------------------------------------- #


def daily_report(
    *,
    day: str,
    ledger: Any,
    cycles: Sequence[Mapping[str, Any]],
    chain: Mapping[str, Any],
    drift: Mapping[str, Any],
    verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Per UTC day: what was sealed, what matured, what was evaluated, what failed."""
    decisions = ledger.decisions()
    outcomes = ledger.outcomes()
    evaluations = ledger.evaluations()
    day_cycles = [dict(item) for item in cycles if str(item.get("day")) == day]
    failures = [item for item in day_cycles if item.get("errors")]
    settled_keys = {(str(item["decision_id"]), str(item["horizon"])) for item in outcomes}
    matured_today = [
        item
        for item in decisions
        if utc_day(int(item["decision_time"]) + do.HORIZON_SECONDS[str(item["horizon"])]) == day
    ]
    return {
        "day": day,
        "decisions_sealed": len(
            [item for item in decisions if utc_day(int(item["decision_time"])) == day]
        ),
        "outcomes_matured": len(
            [item for item in outcomes if utc_day(int(item["exit_close_time"])) == day]
        ),
        "evaluations_completed": len(
            [item for item in evaluations if utc_day(int(item["evaluation_time"])) == day]
        ),
        "matured_today": len(matured_today),
        "matured_unsettled": len(
            [
                item
                for item in matured_today
                if (str(item["decision_id"]), str(item["horizon"])) not in settled_keys
            ]
        ),
        "cycles": day_cycles,
        "cycle_count": len(day_cycles),
        "failures": failures,
        "drift": {"status": drift.get("status"), "drifted": drift.get("drifted")},
        "verification": verification,
        "chain_status": chain.get("status"),
    }


def write_daily_report(root: Path, payload: Mapping[str, Any]) -> Path:
    day = str(payload.get("day"))
    return write_json_atomic(Path(root) / "daily" / f"{day}.json", payload)


# --------------------------------------------------------------------------- #
# §6 — checkpoints
# --------------------------------------------------------------------------- #


def checkpoint_decision_set_hash(performances: Sequence[do.DecisionPerformance]) -> str:
    """Identifies the population a checkpoint describes.

    A sorted list of ``[decision_id, outcome_hash, evaluation_hash]`` triples, so
    the digest is order-independent but duplicate-sensitive — a checkpoint can
    never claim the same population twice.
    """
    return ac.payload_digest(
        sorted(
            [item.decision_id, item.outcome_hash, item.evaluation_hash]
            for item in performances
        )
    )


def checkpoint_decision_set_hash_from_records(entries: Sequence[Mapping[str, Any]]) -> str:
    """Same digest, computed from raw evaluation dicts (verifier-side helper)."""
    return ac.payload_digest(
        sorted(
            [
                str(item["decision_id"]),
                str(item["outcome_hash"]),
                str(item["evaluation_hash"]),
            ]
            for item in entries
        )
    )


def checkpoint_json_path(root: Path, checkpoint: int) -> Path:
    return Path(root) / CHECKPOINT_DIRNAME / f"CHECKPOINT_{checkpoint:03d}.json"


def checkpoint_md_path(root: Path, checkpoint: int) -> Path:
    return Path(root) / CHECKPOINT_DIRNAME / f"CHECKPOINT_{checkpoint:03d}.md"


def read_checkpoint(root: Path, checkpoint: int) -> dict[str, Any] | None:
    path = checkpoint_json_path(root, checkpoint)
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def build_checkpoint_payload(
    *,
    checkpoint: int,
    performances: Sequence[do.DecisionPerformance],
    scorecard: Mapping[str, Any],
    metrics: Mapping[str, Any],
    no_trade: Mapping[str, Any],
    counters: Mapping[str, Any],
    drift: Mapping[str, Any],
    model_drift: Mapping[str, Any],
    now: int,
    errors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """A checkpoint's content: A/B/C/D, populations, selectivity, drift, errors."""
    return {
        "checkpoint_version": CHECKPOINT_JSON_VERSION,
        "checkpoint": checkpoint,
        "created_at": int(now),
        "created_at_utc": dt.datetime.fromtimestamp(int(now), dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "decision_set_hash": checkpoint_decision_set_hash(performances),
        "n_evaluated": len(performances),
        "population": {
            key: counters.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "matured_unsettled",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "cohorts": counters.get("by_cohort"),
        "analyst_vs_baselines": {
            "agent": scorecard.get("agent"),
            "comparators": scorecard.get("comparators"),
            "incremental_edges": scorecard.get("incremental_edges"),
        },
        "direction_accuracy": metrics.get("direction_accuracy"),
        "net_performance": metrics.get("net"),
        "no_trade": {
            "rate": (metrics.get("distribution") or {}).get("no_trade_rate"),
            "count": (metrics.get("distribution") or {}).get("no_trade_count"),
            "selectivity": no_trade,
        },
        "confidence_buckets": metrics.get("confidence_buckets"),
        "per_asset": metrics.get("per_asset"),
        "sample_warnings": metrics.get("sample_warnings"),
        "gate": scorecard.get("gate"),
        "edge_verdict": (
            "NOT_PERMITTED_BELOW_SAMPLE_FLOOR"
            if int(scorecard.get("n_decisions_evaluated", 0)) < asc.MIN_EVALUABLE_DECISIONS
            else "PERMITTED_AT_OR_ABOVE_SAMPLE_FLOOR"
        ),
        "drift": {"status": drift.get("status"), "drifted": drift.get("drifted")},
        "model_drift": {"status": model_drift.get("status")},
        "errors": [dict(item) for item in errors],
        "is_diagnostic_only": True,
    }


def checkpoint_md(payload: Mapping[str, Any]) -> str:
    edges = payload.get("incremental_edges") or {}
    lines = [
        f"# CHECKPOINT_{int(payload['checkpoint']):03d}",
        "",
        f"- created: {payload.get('created_at_utc')}",
        f"- population: {payload.get('n_evaluated')} evaluated",
        f"- decision_set_hash: `{payload.get('decision_set_hash')}`",
        f"- edge verdict: {payload.get('edge_verdict')}",
        f"- gate: {(payload.get('gate') or {}).get('status')}",
        "",
        "## Incremental edges (A vs comparators)",
        "",
        "| comparator | edge |",
        "| --- | --- |",
    ]
    for key, value in edges.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Populations",
            "",
            "| population | count |",
            "| --- | --- |",
        ]
    )
    for key, value in (payload.get("population") or {}).items():
        lines.append(f"| {key} | {value} |")
    selectivity = (payload.get("no_trade") or {}).get("selectivity") or {}
    lines.extend(
        [
            "",
            "## NO_TRADE selectivity",
            "",
            f"- status: {selectivity.get('status')}",
            f"- rate: {(payload.get('no_trade') or {}).get('rate')}",
            f"- no_trade bad-window rate: {selectivity.get('no_trade_bad_window_rate')}",
            f"- base bad-window rate: {selectivity.get('base_bad_window_rate')}",
            f"- lift: {selectivity.get('selectivity_lift')}",
            f"- avoided loss: {selectivity.get('total_avoided_loss')}",
            f"- missed gain: {selectivity.get('total_missed_gain')}",
            "",
            "Diagnostic only. The primary metric is unchanged and no profitability is claimed.",
            "",
        ]
    )
    return "\n".join(lines)


def write_checkpoint(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Write a checkpoint exactly once for its population."""
    checkpoint = int(payload["checkpoint"])
    path = checkpoint_json_path(root, checkpoint)
    existing = read_checkpoint(root, checkpoint)
    if existing is not None:
        same = existing.get("decision_set_hash") == payload.get("decision_set_hash")
        return {
            "status": "ALREADY_EXISTS" if same else "CHECKPOINT_CONFLICT",
            "path": str(path),
            "checkpoint": checkpoint,
            "decision_set_hash": payload.get("decision_set_hash"),
            "existing_decision_set_hash": existing.get("decision_set_hash"),
        }
    write_json_atomic(path, payload)
    checkpoint_md_path(root, checkpoint).write_text(checkpoint_md(payload), encoding="utf-8")
    return {
        "status": "CREATED",
        "path": str(path),
        "checkpoint": checkpoint,
        "decision_set_hash": payload.get("decision_set_hash"),
    }


def checkpoint_dir(root: Path) -> Path:
    return Path(root) / CHECKPOINT_DIRNAME
