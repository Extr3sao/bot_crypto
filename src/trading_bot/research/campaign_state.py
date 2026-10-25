"""CAP-004 — campaign state machine, population accounting and raw evidence.

A campaign that runs unattended for weeks has to be able to say, at any moment
and without guessing, *where every decision is* and *what still has to happen*.
Two habits make that possible and both are refusal-first:

* **Never use one denominator.**  ``sealed``, ``pending``, ``matured``,
  ``settled``, ``evaluated`` and ``verified`` are counted separately, because
  "4 decisions" and "4 evaluated decisions" are different experiments.  A
  decision that has matured but not been settled is reported as *overdue*, never
  folded into a flattering total, and a horizon that has not closed is never
  extrapolated, marked flat or settled early.
* **Never recreate missing evidence.**  The raw OHLCV behind a snapshot is
  registered in ``RAW_EVIDENCE_MANIFEST.jsonl`` with its row range and digest.
  If the local file is gone the status is ``RAW_EVIDENCE_MISSING``; re-fetching
  would silently substitute a different market history for the one the analyst
  actually saw.

``NO_TRADE`` is a first-class decision here, not a missing row: it is counted in
the population, scored through counterfactual comparators, and offered a
selectivity diagnostic that asks whether the analyst avoids bad windows more
often than the base rate.

Everything derived here is labelled a diagnostic.  The primary metric is the
frozen CAP-003 scorecard and is never redefined.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import campaign_manifest as cm
from trading_bot.research import decision_ledger as dl
from trading_bot.research import decision_outcomes as do

__all__ = [
    "CAMPAIGN_STATUSES",
    "CONFIDENCE_BUCKETS",
    "ERROR_STATES",
    "FORBIDDEN_STATUS_WORDS",
    "MISSED_DECISION_SLOT",
    "NO_TRADE_SELECTIVITY_MIN_SAMPLE",
    "RAW_EVIDENCE_MANIFEST_FILENAME",
    "RAW_EVIDENCE_MANIFEST_VERSION",
    "STATE_DECISION_SEALED",
    "STATE_EVALUATED",
    "STATE_OUTCOME_SETTLED",
    "STATE_PENDING_MATURITY",
    "STATE_SCHEDULED",
    "STATE_VERIFIED",
    "append_raw_evidence",
    "campaign_counters",
    "campaign_metrics",
    "campaign_status_name",
    "canonical_content_digest",
    "confidence_bucket_for",
    "decision_states",
    "maturity_state",
    "no_trade_analysis",
    "no_trade_counterfactual",
    "raw_evidence_entry",
    "raw_evidence_status",
    "read_raw_evidence",
    "register_unregistered_raw_evidence",
    "replay_extended",
]

# --------------------------------------------------------------------------- #
# §1 — the state machine
# --------------------------------------------------------------------------- #

STATE_SCHEDULED = "SCHEDULED"
STATE_DECISION_SEALED = "DECISION_SEALED"
STATE_PENDING_MATURITY = "PENDING_MATURITY"
STATE_OUTCOME_SETTLED = "OUTCOME_SETTLED"
STATE_EVALUATED = "EVALUATED"
STATE_VERIFIED = "VERIFIED"

MISSED_DECISION_SLOT = "MISSED_DECISION_SLOT"

ERROR_STATES: tuple[str, ...] = (
    "DATA_BLOCKED",
    "ANALYST_FAILED",
    "OUTCOME_BLOCKED",
    "EVALUATION_FAILED",
    "EVIDENCE_FAILED",
)

CAMPAIGN_STATUSES: tuple[str, ...] = (
    "INITIALIZING",
    "RUNNING",
    "DEGRADED",
    "BLOCKED",
    "INTEGRITY_FAILURE",
    "COMPLETE_100",
)

#: No promotional vocabulary exists in this vocabulary, on purpose.
FORBIDDEN_STATUS_WORDS: tuple[str, ...] = (
    "PROFITABLE",
    "EDGE_CONFIRMED",
    "STRATEGY_VALIDATED",
    "PAPER_READY",
    "LIVE_READY",
)



def maturity_state(*, decision_time: int, horizon: str, now: int) -> dict[str, Any]:
    """Whether a horizon has closed.  Never a partial or extrapolated outcome."""
    seconds = do.horizon_seconds(horizon)
    maturity_time = int(decision_time) + seconds
    matured = int(now) >= maturity_time
    return {
        "maturity_time": maturity_time,
        "maturity": "MATURED" if matured else STATE_PENDING_MATURITY,
        "matured": matured,
        "seconds_to_maturity": 0 if matured else maturity_time - int(now),
        "overdue_seconds": maturity_time - int(now) if matured else 0,
    }


def decision_states(
    ledger: dl.DecisionLedger, *, now: int, chain_verified: bool = True
) -> list[dict[str, Any]]:
    """Resolve every decision's position in the state machine."""
    outcome_by_key: dict[tuple[str, str], Mapping[str, Any]] = {
        (str(item["decision_id"]), str(item["horizon"])): item for item in ledger.outcomes()
    }
    evaluation_by_key: dict[tuple[str, str], Mapping[str, Any]] = {
        (str(item["decision_id"]), str(item["horizon"])): item for item in ledger.evaluations()
    }
    expected_model = cm.MODEL_POLICY["model"]
    states: list[dict[str, Any]] = []
    for entry in ledger.decisions():
        decision_id = str(entry["decision_id"])
        horizon = str(entry["horizon"])
        key = (decision_id, horizon)
        maturity = maturity_state(
            decision_time=int(entry["decision_time"]), horizon=horizon, now=now
        )
        outcome = outcome_by_key.get(key)
        evaluation = evaluation_by_key.get(key)
        if not chain_verified:
            state = "EVIDENCE_FAILED"
        elif evaluation is not None:
            state = STATE_VERIFIED
        elif outcome is not None:
            state = STATE_OUTCOME_SETTLED
        else:
            state = STATE_PENDING_MATURITY if maturity["matured"] else STATE_DECISION_SEALED
        states.append(
            {
                "decision_id": decision_id,
                "asset": str(entry["asset"]),
                "horizon": horizon,
                "decision": str(entry["decision"]),
                "decision_time": int(entry["decision_time"]),
                "cohort": cm.cohort_of(entry, expected_model=expected_model),
                "state": state,
                "maturity": maturity["maturity"],
                "maturity_time": maturity["maturity_time"],
                "overdue": bool(maturity["matured"] and outcome is None),
                "outcome_hash": None if outcome is None else outcome["outcome_hash"],
                "evaluation_hash": None if evaluation is None else evaluation["evaluation_hash"],
                "slot_key": cm.decision_key(
                    asset=str(entry["asset"]),
                    decision_time=int(entry["decision_time"]),
                    horizon=horizon,
                    analyst_version=str(entry.get("prompt_version", "")),
                ),
            }
        )
    return states


# --------------------------------------------------------------------------- #
# §2 — population accounting (never one denominator)
# --------------------------------------------------------------------------- #


def campaign_counters(
    ledger: dl.DecisionLedger, *, now: int, chain_verified: bool = True
) -> dict[str, Any]:
    """The populations the campaign must never merge into a single number."""
    states = decision_states(ledger, now=now, chain_verified=chain_verified)
    evaluated = ledger.rebuilt_evaluations()
    verified_evaluations = sum(1 for item in evaluated if item.is_verified())
    matured = [item for item in states if item["maturity"] == "MATURED"]

    cohorts: dict[str, int] = {}
    for item in states:
        cohorts[item["cohort"]] = cohorts.get(item["cohort"], 0) + 1
    by_asset: dict[str, int] = {}
    by_horizon: dict[str, int] = {}
    directions = {direction: 0 for direction in ac.DIRECTIONS}
    for item in states:
        by_asset[item["asset"]] = by_asset.get(item["asset"], 0) + 1
        by_horizon[item["horizon"]] = by_horizon.get(item["horizon"], 0) + 1
        directions[item["decision"]] += 1

    return {
        "sealed_decisions": len(states),
        "pending_decisions": len(
            [item for item in states if item["maturity"] == STATE_PENDING_MATURITY]
        ),
        "matured_decisions": len(matured),
        "matured_unsettled": len([item for item in states if item["overdue"]]),
        "settled_outcomes": len(ledger.outcomes()),
        "evaluated_decisions": len(ledger.evaluations()),
        "verified_evaluations": verified_evaluations,
        "long_count": directions["LONG"],
        "short_count": directions["SHORT"],
        "no_trade_count": directions["NO_TRADE"],
        "by_cohort": cohorts,
        "by_asset": by_asset,
        "by_horizon": by_horizon,
        "horizons": dict(do.HORIZON_SECONDS),
        "chain_verified": chain_verified,
        "as_of": int(now),
        "decision_states": states,
    }


def campaign_status_name(
    *, counters: Mapping[str, Any], chain_verified: bool, drift: Mapping[str, Any]
) -> str:
    """The global campaign status, in a vocabulary with no promotional word."""
    if not chain_verified:
        return "INTEGRITY_FAILURE"
    if str(drift.get("status", "NO_DRIFT")) != "NO_DRIFT":
        return "BLOCKED"
    if int(counters.get("evaluated_decisions", 0)) >= asc.MIN_EVALUABLE_DECISIONS:
        return "COMPLETE_100"
    if int(counters.get("sealed_decisions", 0)) == 0:
        return "INITIALIZING"
    if int(counters.get("matured_unsettled", 0)) > 0:
        return "DEGRADED"
    return "RUNNING"


# --------------------------------------------------------------------------- #
# §3 — NO_TRADE as a first-class decision
# --------------------------------------------------------------------------- #

#: A window is "bad" when the passive comparator lost money in it.  Declared
#: here, before any result, and never tuned.
BAD_WINDOW_COMPARATOR = do.BASELINE_ID_BUY_AND_HOLD
NO_TRADE_SELECTIVITY_MIN_SAMPLE = 20


def no_trade_counterfactual(
    *, net_return: float, comparison_net_return: float
) -> dict[str, Any]:
    """What the analyst avoided or forgone by not taking the comparator's side."""
    return {
        "label": "COUNTERFACTUAL",
        "realized_net_return": net_return,
        "counterfactual_net_return": comparison_net_return,
        "delta_vs_counterfactual": net_return - comparison_net_return,
        "avoided_loss": max(0.0, -comparison_net_return),
        "missed_gain": max(0.0, comparison_net_return),
    }


def no_trade_analysis(performances: Sequence[do.DecisionPerformance]) -> dict[str, Any]:
    """Does inaction concentrate in bad windows more than the base rate?

    Both rates are measured against the same declared rule ("buy-and-hold lost
    money in that window"), so the lift is a comparison of two observed
    frequencies, not a model.  Below the declared sample floor the answer is
    ``INSUFFICIENT_SAMPLE``.
    """
    def comparator_net(item: do.DecisionPerformance) -> float | None:
        comparison = item.comparison(BAD_WINDOW_COMPARATOR)
        if comparison is None or not comparison.available:
            return None
        return comparison.net_return

    no_trade = [item for item in performances if item.decision == "NO_TRADE"]
    directional = [item for item in performances if item.decision != "NO_TRADE"]
    scored = [(item, comparator_net(item)) for item in performances]
    scored = [(item, value) for item, value in scored if value is not None]

    def bad_rate(items: Sequence[do.DecisionPerformance]) -> float | None:
        values = [comparator_net(item) for item in items]
        usable = [value for value in values if value is not None]
        if not usable:
            return None
        return sum(1 for value in usable if value < 0.0) / len(usable)

    no_trade_bad = bad_rate(no_trade)
    base_bad = bad_rate([item for item, _ in scored])
    lift = None if no_trade_bad is None or base_bad is None else no_trade_bad - base_bad

    avoided = 0.0
    missed = 0.0
    counterfactuals: list[dict[str, Any]] = []
    for item in no_trade:
        value = comparator_net(item)
        if value is None:
            continue
        record = no_trade_counterfactual(
            net_return=item.net_return, comparison_net_return=value
        )
        counterfactuals.append({"decision_id": item.decision_id, **record})
        avoided += record["avoided_loss"]
        missed += record["missed_gain"]

    measured = (
        len(no_trade) >= NO_TRADE_SELECTIVITY_MIN_SAMPLE
        and len(directional) >= NO_TRADE_SELECTIVITY_MIN_SAMPLE
    )
    return {
        "status": "MEASURED" if measured else "INSUFFICIENT_SAMPLE",
        "min_sample": NO_TRADE_SELECTIVITY_MIN_SAMPLE,
        "no_trade_count": len(no_trade),
        "directional_count": len(directional),
        "bad_window_comparator": BAD_WINDOW_COMPARATOR,
        "bad_window_definition": "the comparator's net return in that window was negative",
        "no_trade_bad_window_rate": no_trade_bad,
        "base_bad_window_rate": base_bad,
        "selectivity_lift": lift,
        "total_avoided_loss": avoided,
        "total_missed_gain": missed,
        "net_counterfactual_vs_comparator": avoided - missed,
        "counterfactuals": counterfactuals,
        "is_diagnostic_only": True,
        "note": (
            "measured against a passive comparator, never a realised profit-and-loss figure; "
            "it does not feed the frozen primary metric"
        ),
    }


# --------------------------------------------------------------------------- #
# §4 — extended diagnostics (never the primary metric)
# --------------------------------------------------------------------------- #

#: Predeclared calibration buckets; no threshold is ever searched.
CONFIDENCE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0.00-0.40", 0.0, 0.40),
    ("0.40-0.60", 0.40, 0.60),
    ("0.60-0.80", 0.60, 0.80),
    ("0.80-1.00", 0.80, 1.01),
)


def confidence_bucket_for(confidence: float) -> str | None:
    for label, low, high in CONFIDENCE_BUCKETS:
        if low <= confidence < high:
            return label
    return None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _per_decision_sharpe(values: Sequence[float]) -> float | None:
    """Non-annualised per-observation ratio; ``None`` when the sample cannot carry it."""
    if len(values) < asc.MIN_EVALUABLE_DECISIONS:
        return None
    spread = statistics.pstdev(values)
    if spread == 0.0:
        return None
    return statistics.fmean(values) / spread


def campaign_metrics(performances: Sequence[do.DecisionPerformance]) -> dict[str, Any]:
    """Diagnostics on top of the frozen scorecard.  Never a verdict."""
    n = len(performances)
    nets = [item.net_return for item in performances]
    directional = [item for item in performances if item.decision != "NO_TRADE"]
    directional_nets = [item.net_return for item in directional]

    def bucket(label: str, items: Sequence[do.DecisionPerformance]) -> dict[str, Any]:
        values = [item.net_return for item in items]
        return {
            "label": label,
            "n": len(items),
            "mean_net_return": statistics.fmean(values) if values else None,
            "median_net_return": _median(values),
            "direction_accuracy": (
                sum(1 for item in items if item.direction_correct) / len(items)
                if items
                else None
            ),
        }

    def grouped(items: Sequence[do.DecisionPerformance], key: str) -> dict[str, Any]:
        groups: dict[str, list[do.DecisionPerformance]] = {}
        for item in items:
            groups.setdefault(str(getattr(item, key)), []).append(item)
        return {name: bucket(name, group) for name, group in groups.items()}

    warning = (
        "INSUFFICIENT_SAMPLE"
        if n < asc.MIN_EVALUABLE_DECISIONS
        else None
    )
    return {
        "n_decisions": n,
        "distribution": {
            "long_count": sum(1 for item in performances if item.decision == "LONG"),
            "short_count": sum(1 for item in performances if item.decision == "SHORT"),
            "no_trade_count": sum(1 for item in performances if item.decision == "NO_TRADE"),
            "long_rate": (sum(1 for i in performances if i.decision == "LONG") / n) if n else None,
            "short_rate": (sum(1 for i in performances if i.decision == "SHORT") / n) if n else None,
            "no_trade_rate": (
                sum(1 for i in performances if i.decision == "NO_TRADE") / n if n else None
            ),
        },
        "net": {
            "mean": statistics.fmean(nets) if nets else None,
            "median": _median(nets),
            "per_decision_sharpe": _per_decision_sharpe(nets),
            "sharpe_status": (
                "COMPUTED_NON_ANNUALISED"
                if len(nets) >= asc.MIN_EVALUABLE_DECISIONS
                else "NOT_COMPUTED_BELOW_SAMPLE_FLOOR"
            ),
        },
        "direction_accuracy": (
            sum(1 for item in directional if item.direction_correct) / len(directional)
            if directional
            else None
        ),
        "excursions": {
            "mean_mfe": statistics.fmean([item.mfe for item in performances]) if performances else None,
            "mean_mae": statistics.fmean([item.mae for item in performances]) if performances else None,
        },
        "confidence_buckets": [
            {"bucket": label, **bucket(label, [i for i in directional if confidence_bucket_for(i.confidence) == label])}
            for label, _low, _high in CONFIDENCE_BUCKETS
        ],
        "per_asset": grouped(performances, "asset"),
        "per_horizon": grouped(performances, "horizon"),
        "sample_warnings": [w for w in (warning,) if w],
        "label": "EXTENDED_DIAGNOSTIC_NOT_THE_PRIMARY_METRIC",
        "directional_net_mean": statistics.fmean(directional_nets) if directional_nets else None,
    }


# --------------------------------------------------------------------------- #
# §5 — raw evidence manifest
# --------------------------------------------------------------------------- #

RAW_EVIDENCE_MANIFEST_VERSION = "RAW_EVIDENCE_MANIFEST_V1"
RAW_EVIDENCE_MANIFEST_FILENAME = "RAW_EVIDENCE_MANIFEST.jsonl"


def _interval_digest(bars: Sequence[Any]) -> str:
    text = json.dumps(bars, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_content_digest(payload: Any) -> str:
    """Digest of the *content*, independent of how the file was pretty-printed.

    ``raw_evidence_hash`` in the ledger is a canonical digest, not a byte digest,
    so verification must canonicalise before comparing — otherwise a harmless
    change of JSON indentation would look like tampering, and a real change of
    one price would look like nothing.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def raw_evidence_entry(
    *,
    raw_evidence: Mapping[str, Any],
    snapshot_hash: str,
    asset: str,
    raw_evidence_hash: str,
    local_path: str,
    recorded_at: int,
) -> dict[str, Any]:
    """Register one snapshot's raw bars by range and digest, without the bars."""
    raw = raw_evidence
    intervals: list[dict[str, Any]] = []
    for name in sorted(raw["intervals"]):
        block = raw["intervals"][name]
        bars = block["bars"]
        intervals.append(
            {
                "timeframe": name,
                "bar_seconds": block["bar_seconds"],
                "start_open_time": block["first_open_time"],
                "end_open_time": block["last_open_time"],
                "row_count": len(bars),
                "sha256": _interval_digest(bars),
            }
        )
    return {
        "manifest_version": RAW_EVIDENCE_MANIFEST_VERSION,
        "snapshot_hash": str(snapshot_hash),
        "raw_evidence_hash": str(raw_evidence_hash),
        "source": str(raw["provider"]),
        "asset": str(asset),
        "local_path": local_path,
        "recorded_at": int(recorded_at),
        "intervals": intervals,
    }


def append_raw_evidence(root: Path, entry: Mapping[str, Any]) -> None:
    path = Path(root) / RAW_EVIDENCE_MANIFEST_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(entry), sort_keys=True, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def read_raw_evidence(root: Path) -> list[dict[str, Any]]:
    path = Path(root) / RAW_EVIDENCE_MANIFEST_FILENAME
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def register_unregistered_raw_evidence(
    root: Path, *, decisions: Sequence[Mapping[str, Any]], now: int
) -> list[dict[str, Any]]:
    """Register raw files that exist for decisions the manifest does not cover.

    This adopts local evidence (the CAP-003 pilot files included) into the
    campaign's manifest.  It never re-downloads: a decision whose file is gone is
    reported ``RAW_EVIDENCE_MISSING`` and stays that way.
    """
    registered = {str(item["snapshot_hash"]) for item in read_raw_evidence(root)}
    outcome: list[dict[str, Any]] = []
    for entry in decisions:
        snapshot_hash = str(entry["snapshot_hash"])
        if snapshot_hash in registered:
            continue
        relative = str(entry.get("raw_evidence_path", "")).strip()
        if not relative:
            outcome.append({"snapshot_hash": snapshot_hash, "status": "NO_RAW_EVIDENCE_PATH"})
            continue
        path = Path(root) / relative
        if not path.is_file():
            # Record the *expectation*, never fabricated bars: the manifest
            # remembers that this decision declared local evidence which is not
            # here, so the absence stays visible instead of silently vanishing.
            append_raw_evidence(
                root,
                {
                    "manifest_version": RAW_EVIDENCE_MANIFEST_VERSION,
                    "snapshot_hash": snapshot_hash,
                    "raw_evidence_hash": str(entry["raw_evidence_hash"]),
                    "source": str(entry.get("provider", "")),
                    "asset": str(entry["asset"]),
                    "local_path": relative,
                    "recorded_at": int(now),
                    "intervals": [],
                },
            )
            registered.add(snapshot_hash)
            outcome.append({"snapshot_hash": snapshot_hash, "status": "RAW_EVIDENCE_MISSING"})
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        append_raw_evidence(
            root,
            raw_evidence_entry(
                raw_evidence=raw,
                snapshot_hash=snapshot_hash,
                asset=str(entry["asset"]),
                raw_evidence_hash=str(entry["raw_evidence_hash"]),
                local_path=relative,
                recorded_at=int(now),
            ),
        )
        registered.add(snapshot_hash)
        outcome.append({"snapshot_hash": snapshot_hash, "status": "REGISTERED"})
    return outcome


def raw_evidence_status(root: Path, *, decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per snapshot: verified locally, missing, or mismatching.  Never re-fetches."""
    registered = {str(item["snapshot_hash"]): item for item in read_raw_evidence(root)}
    per_snapshot: dict[str, dict[str, Any]] = {}
    for entry in decisions:
        snapshot_hash = str(entry["snapshot_hash"])
        record = registered.get(snapshot_hash)
        if record is None:
            per_snapshot[snapshot_hash] = {"status": "RAW_EVIDENCE_UNREGISTERED"}
            continue
        path = Path(root) / str(record["local_path"])
        if not path.is_file():
            per_snapshot[snapshot_hash] = {
                "status": "RAW_EVIDENCE_MISSING",
                "local_path": record["local_path"],
            }
            continue
        digest = canonical_content_digest(json.loads(path.read_text(encoding="utf-8")))
        per_snapshot[snapshot_hash] = {
            "status": (
                "PRESENT_VERIFIED"
                if digest == str(record["raw_evidence_hash"])
                else "RAW_EVIDENCE_HASH_MISMATCH"
            ),
            "local_path": record["local_path"],
            "expected_sha256": record["raw_evidence_hash"],
            "observed_sha256": digest,
        }
    counts: dict[str, int] = {}
    for item in per_snapshot.values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "manifest_version": RAW_EVIDENCE_MANIFEST_VERSION,
        "registered_snapshots": len(registered),
        "counts": counts,
        "per_snapshot": per_snapshot,
        "status": (
            "RAW_EVIDENCE_COMPLETE"
            if counts.get("PRESENT_VERIFIED", 0) == len(per_snapshot) and per_snapshot
            else ("NO_DECISIONS" if not per_snapshot else "RAW_EVIDENCE_INCOMPLETE")
        ),
    }


# --------------------------------------------------------------------------- #
# §6 — extended replay (read-only)
# --------------------------------------------------------------------------- #


def replay_extended(
    ledger: dl.DecisionLedger, decision_id: str, *, now: int, chain_verified: bool = True
) -> dict[str, Any]:
    """``ledger.replay`` plus comparators, D's assignment and the state machine."""
    base = ledger.replay(decision_id)
    if not base["found"]:
        return {**base, "campaign": {"state": None, "reason": "NOT_IN_LEDGER"}}

    evaluations = ledger.rebuilt_evaluations()
    order = [item.decision_id for item in evaluations]
    assigned = (
        do.matched_random_directions(
            [item.decision for item in evaluations], seed=asc.RANDOM_BASELINE_SEED
        )
        if evaluations
        else ()
    )
    random_by_id = dict(zip(order, assigned, strict=True)) if order else {}

    evaluation = next(
        (item for item in evaluations if item.decision_id == decision_id), None
    )
    state = next(
        (item for item in decision_states(ledger, now=now, chain_verified=chain_verified)
         if item["decision_id"] == decision_id),
        None,
    )

    payload: dict[str, Any] = {
        **base,
        "campaign": {
            "state": None if state is None else state["state"],
            "maturity": None if state is None else state["maturity"],
            "maturity_time": None if state is None else state["maturity_time"],
            "cohort": None if state is None else state["cohort"],
            "slot_key": None if state is None else state["slot_key"],
        },
        "baselines": None,
        "random_assignment": random_by_id.get(decision_id),
        "score_contribution": None,
        "counterfactuals": None,
    }
    if evaluation is None:
        return payload

    comparisons = {
        item.baseline_id: item.to_dict() for item in evaluation.comparisons
    }
    contribution: dict[str, Any] = {}
    for baseline_id, comparison in comparisons.items():
        contribution[baseline_id] = evaluation.net_return - comparison["net_return"]
    payload["baselines"] = comparisons
    payload["score_contribution"] = contribution
    if evaluation.decision == "NO_TRADE":
        payload["counterfactuals"] = {
            baseline_id: no_trade_counterfactual(
                net_return=evaluation.net_return, comparison_net_return=comparison["net_return"]
            )
            for baseline_id, comparison in comparisons.items()
        }
    return payload
