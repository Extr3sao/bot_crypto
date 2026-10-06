"""CAP-003 — the real decision ledger: an explicit, immutable research store.

``reports/`` is gitignored scratch space; two decisions can live there, three
hundred cannot.  The campaign's scientific record needs a durable, append-only
store outside ``reports/``, with a hash chain that lets anyone re-derive *what
the system knew* and *what happened* without trusting the runner:

.. code-block:: text

    evidence/real_decisions/
        decisions.jsonl     snapshot_hash -> decision_hash
        outcomes.jsonl      decision_hash -> outcome_hash
        evaluations.jsonl   outcome_hash  -> evaluation_hash
        raw_evidence/       per-cycle OHLCV behind each snapshot (hash-verified)

Rules enforced here, not merely documented:

* a decision is only appended with **complete** analyst provenance, so an
  unreproducible run can never become a campaign observation (this is why the
  CAP-002 pilot decisions stay out of the campaign);
* a decision is only appended if its sealed hash still recomputes;
* the snapshot embedded in the ledger is re-digested and must match the
  ``snapshot_hash`` the decision was sealed against;
* nothing is ever rewritten: duplicates are refused, and every record carries
  its own hash so tampering is detectable with :meth:`DecisionLedger.verify_chain`;
* :meth:`DecisionLedger.replay` reconstructs one decision's full chain, so a
  later analysis can rebuild exactly what the analyst saw.

No LLM runs here and no decision is ever re-scored in place: an outcome is a
*new* record that points back at the seal.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import analyst_provenance as ap
from trading_bot.research import decision_outcomes as do

__all__ = [
    "DECISIONS_FILENAME",
    "EVALUATIONS_FILENAME",
    "LEDGER_VERSION",
    "OUTCOMES_FILENAME",
    "RAW_EVIDENCE_DIRNAME",
    "DecisionLedger",
    "LedgerError",
    "decision_entry",
    "record_from_entry",
    "replay_artifact",
]

LEDGER_VERSION = "REAL_DECISION_LEDGER_V1"
DECISIONS_FILENAME = "decisions.jsonl"
OUTCOMES_FILENAME = "outcomes.jsonl"
EVALUATIONS_FILENAME = "evaluations.jsonl"
RAW_EVIDENCE_DIRNAME = "raw_evidence"

_TOLERANCE = 1e-12


class LedgerError(ValueError):
    """Raised when an append would break the ledger's integrity rules."""


# --------------------------------------------------------------------------- #
# §1 — building a decision entry from a sealed record + real snapshot artefact
# --------------------------------------------------------------------------- #


def decision_entry(
    *,
    record: ac.DecisionRecord,
    snapshot_artifact: Mapping[str, Any],
    provenance: Mapping[str, Any],
    raw_evidence_path: str = "",
    recorded_at: int | None = None,
) -> dict[str, Any]:
    """Assemble the immutable ledger entry for one sealed real decision.

    Refuses: an unsealed/tampered record, incomplete provenance, a snapshot that
    does not re-digest to its declared hash, a record sealed against a different
    snapshot, a horizon outside the frozen contract, or a decision-time mismatch.
    """
    if not record.is_verified():
        raise LedgerError("refusing to record an unsealed or tampered decision record")

    missing = ap.provenance_missing(provenance)
    if missing:
        raise LedgerError(f"refusing to record a decision without complete provenance: {missing}")

    snapshot = snapshot_artifact["snapshot"]
    snapshot_hash = str(snapshot_artifact["snapshot_hash"])
    if ac.payload_digest(snapshot) != snapshot_hash:
        raise LedgerError("the snapshot artefact does not re-digest to its declared hash")
    if record.evidence_snapshot_hash != snapshot_hash:
        raise LedgerError("the sealed record was not sealed against this snapshot")

    analyst = do.analyst_payload(record)
    horizon = str(analyst.get("horizon", ""))
    if horizon not in do.HORIZON_SECONDS:
        raise LedgerError(f"the sealed answer carries an unknown horizon: {horizon!r}")
    if int(analyst.get("decision_time", 0)) != record.timestamp:
        raise LedgerError("the sealed answer's decision_time does not match the seal")

    return {
        "ledger_version": LEDGER_VERSION,
        "decision_id": ab.decision_id_for(record),
        "decision_hash": record.decision_hash,
        "snapshot_hash": snapshot_hash,
        "raw_evidence_hash": str(snapshot_artifact["raw_evidence_hash"]),
        "raw_evidence_path": raw_evidence_path,
        "asset": str(snapshot_artifact["asset"]),
        "provider": str(snapshot_artifact["provider"]),
        "source_type": str(snapshot_artifact["source_type"]),
        "decision_time": record.timestamp,
        "horizon": horizon,
        "horizon_seconds": do.HORIZON_SECONDS[horizon],
        "decision": record.decision,
        "confidence": do.analyst_confidence(record),
        "prompt_version": record.prompt_version,
        "snapshot": snapshot,
        "technicals": snapshot_artifact.get("technicals", {}),
        "derived": snapshot_artifact.get("derived", {}),
        "agent_output": record.agent_output,
        "critic_output": record.critic_output,
        "provenance": dict(provenance),
        "provenance_digest": ap.provenance_digest(provenance),
        "recorded_at": int(time.time()) if recorded_at is None else int(recorded_at),
    }


def _decision_hash_from_entry(entry: Mapping[str, Any]) -> str:
    return ac.compute_decision_hash(
        timestamp=int(entry["decision_time"]),
        prompt_version=str(entry["prompt_version"]),
        evidence_snapshot_hash=str(entry["snapshot_hash"]),
        agent_output=entry["agent_output"],
        critic_output=entry["critic_output"],
        decision=str(entry["decision"]),
    )


def record_from_entry(entry: Mapping[str, Any]) -> ac.DecisionRecord:
    """Rebuild the sealed record from a ledger entry (hashes re-derivable)."""
    return ac.DecisionRecord(
        timestamp=int(entry["decision_time"]),
        prompt_version=str(entry["prompt_version"]),
        evidence_snapshot_hash=str(entry["snapshot_hash"]),
        agent_output=entry["agent_output"],
        critic_output=entry["critic_output"],
        decision=str(entry["decision"]),
        decision_hash=str(entry["decision_hash"]),
    )


# --------------------------------------------------------------------------- #
# §2 — the store
# --------------------------------------------------------------------------- #


class DecisionLedger:
    """Append-only JSONL store with a verifiable hash chain."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- reading ---------------------------------------------------------- #

    def _path(self, filename: str) -> Path:
        return self.root / filename

    def _read(self, filename: str) -> list[dict[str, Any]]:
        path = self._path(filename)
        if not path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                entries.append(json.loads(stripped))
        return entries

    def decisions(self) -> list[dict[str, Any]]:
        return self._read(DECISIONS_FILENAME)

    def outcomes(self) -> list[dict[str, Any]]:
        return self._read(OUTCOMES_FILENAME)

    def evaluations(self) -> list[dict[str, Any]]:
        return self._read(EVALUATIONS_FILENAME)

    def decision_hashes(self) -> set[str]:
        return {str(entry["decision_hash"]) for entry in self.decisions()}

    def outcome_hashes(self) -> set[str]:
        return {str(entry["outcome_hash"]) for entry in self.outcomes()}

    def evaluation_hashes(self) -> set[str]:
        return {str(entry["evaluation_hash"]) for entry in self.evaluations()}

    def has_decision(self, decision_hash: str) -> bool:
        return decision_hash in self.decision_hashes()

    def has_outcome(self, decision_id: str, horizon: str) -> bool:
        return self.outcome_for(decision_id, horizon) is not None

    def outcome_for(self, decision_id: str, horizon: str) -> dict[str, Any] | None:
        for entry in self.outcomes():
            if str(entry["decision_id"]) == decision_id and str(entry["horizon"]) == horizon:
                return entry
        return None

    def evaluation_for(self, decision_id: str, horizon: str) -> dict[str, Any] | None:
        for entry in self.evaluations():
            if str(entry["decision_id"]) == decision_id and str(entry["horizon"]) == horizon:
                return entry
        return None

    def pending_decisions(self) -> list[dict[str, Any]]:
        """Decisions whose own horizon has no outcome yet."""
        return [
            entry
            for entry in self.decisions()
            if not self.has_outcome(str(entry["decision_id"]), str(entry["horizon"]))
        ]

    def rebuilt_outcomes(self) -> list[do.DecisionOutcome]:
        return [do.DecisionOutcome(**entry) for entry in self.outcomes()]

    def rebuilt_evaluations(self) -> list[do.DecisionPerformance]:
        rebuilt: list[do.DecisionPerformance] = []
        for entry in self.evaluations():
            payload = dict(entry)
            payload["comparisons"] = tuple(
                do.BaselineComparison(**item) for item in entry.get("comparisons", [])
            )
            rebuilt.append(do.DecisionPerformance(**payload))
        return rebuilt

    # -- writing ---------------------------------------------------------- #

    def _append(self, filename: str, payload: Mapping[str, Any]) -> None:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        with self._path(filename).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def append_decision(self, entry: Mapping[str, Any]) -> str:
        """Append one immutable decision entry, re-validating it on the way in."""
        decision_hash = str(entry["decision_hash"])
        if self.has_decision(decision_hash):
            raise LedgerError(f"decision {decision_hash[:16]} is already in the ledger")
        missing = ap.provenance_missing(entry.get("provenance", {}))
        if missing:
            raise LedgerError(f"incomplete provenance on append: {missing}")
        if ac.payload_digest(entry["snapshot"]) != str(entry["snapshot_hash"]):
            raise LedgerError("snapshot does not re-digest to its declared hash on append")
        if _decision_hash_from_entry(entry) != decision_hash:
            raise LedgerError("the sealed decision hash does not recompute on append")
        expected_id = "DEC-" + decision_hash[:16]
        if str(entry["decision_id"]) != expected_id:
            raise LedgerError(f"decision_id must be {expected_id}")
        self._append(DECISIONS_FILENAME, entry)
        return expected_id

    def append_outcome(self, outcome: do.DecisionOutcome) -> None:
        if not outcome.is_verified():
            raise LedgerError("refusing to append an unverified outcome")
        if not self.has_decision(outcome.decision_hash):
            raise LedgerError("the outcome points at a decision that is not in the ledger")
        if self.has_outcome(outcome.decision_id, outcome.horizon):
            raise LedgerError(f"{outcome.decision_id} {outcome.horizon} already has an outcome")
        self._append(OUTCOMES_FILENAME, outcome.to_dict())

    def append_evaluation(self, performance: do.DecisionPerformance) -> None:
        if not performance.is_verified():
            raise LedgerError("refusing to append an unverified evaluation")
        if performance.outcome_hash not in self.outcome_hashes():
            raise LedgerError("the evaluation points at an outcome that is not in the ledger")
        if self.evaluation_for(performance.decision_id, performance.horizon) is not None:
            raise LedgerError(
                f"{performance.decision_id} {performance.horizon} already has an evaluation"
            )
        self._append(EVALUATIONS_FILENAME, performance.to_dict())

    # -- auditing --------------------------------------------------------- #

    def verify_chain(self) -> dict[str, Any]:
        """Re-derive every hash and link from the written records."""
        decisions = self.decisions()
        outcomes = self.outcomes()
        evaluations = self.evaluations()
        decision_hashes = {str(entry["decision_hash"]) for entry in decisions}
        outcome_hashes = {str(entry["outcome_hash"]) for entry in outcomes}

        broken: list[dict[str, str]] = []
        for entry in decisions:
            decision_id = str(entry["decision_id"])
            if _decision_hash_from_entry(entry) != str(entry["decision_hash"]):
                broken.append({"record": "decision", "id": decision_id, "problem": "hash"})
            if decision_id != "DEC-" + str(entry["decision_hash"])[:16]:
                broken.append({"record": "decision", "id": decision_id, "problem": "id"})
            if ap.provenance_missing(entry.get("provenance", {})):
                broken.append({"record": "decision", "id": decision_id, "problem": "provenance"})
            if ac.payload_digest(entry["snapshot"]) != str(entry["snapshot_hash"]):
                broken.append({"record": "decision", "id": decision_id, "problem": "snapshot"})

        for entry in outcomes:
            decision_id = str(entry["decision_id"])
            if do.outcome_payload_hash(entry) != str(entry["outcome_hash"]):
                broken.append({"record": "outcome", "id": decision_id, "problem": "hash"})
            if str(entry["decision_hash"]) not in decision_hashes:
                broken.append({"record": "outcome", "id": decision_id, "problem": "link"})
            net = float(entry["gross_return"]) - float(entry["costs"])
            if not math.isclose(net, float(entry["net_return"]), rel_tol=_TOLERANCE, abs_tol=_TOLERANCE):
                broken.append({"record": "outcome", "id": decision_id, "problem": "arithmetic"})
            if str(entry["decision"]) == "NO_TRADE" and float(entry["costs"]) != 0.0:
                broken.append({"record": "outcome", "id": decision_id, "problem": "cost_model"})

        for entry in evaluations:
            decision_id = str(entry["decision_id"])
            if do.performance_payload_hash(entry) != str(entry["evaluation_hash"]):
                broken.append({"record": "evaluation", "id": decision_id, "problem": "hash"})
            if str(entry["outcome_hash"]) not in outcome_hashes:
                broken.append({"record": "evaluation", "id": decision_id, "problem": "link"})

        return {
            "ledger_version": LEDGER_VERSION,
            "root": str(self.root),
            "n_decisions": len(decisions),
            "n_outcomes": len(outcomes),
            "n_evaluations": len(evaluations),
            "dup_decision_hashes": _duplicates([str(e["decision_hash"]) for e in decisions]),
            "dup_outcome_keys": _duplicates(
                [f"{e['decision_id']}:{e['horizon']}" for e in outcomes]
            ),
            "dup_evaluation_keys": _duplicates(
                [f"{e['decision_id']}:{e['horizon']}" for e in evaluations]
            ),
            "broken": broken,
            "status": "INTACT" if not broken else "BROKEN",
        }

    def replay(self, decision_id: str) -> dict[str, Any]:
        """Rebuild one decision's full chain: seal -> outcome -> evaluation."""
        entry = next(
            (item for item in self.decisions() if str(item["decision_id"]) == decision_id), None
        )
        if entry is None:
            return replay_artifact(decision_id=decision_id, found=False)
        raw_path = str(entry.get("raw_evidence_path", ""))
        raw_file = self.root / raw_path if raw_path else None
        raw_present = raw_file is not None and raw_file.is_file()
        raw_matches: bool | None = None
        if raw_present and raw_file is not None:
            raw_matches = _digest_file(raw_file) == str(entry["raw_evidence_hash"])
        return replay_artifact(
            decision_id=decision_id,
            found=True,
            entry=entry,
            outcomes=[
                item for item in self.outcomes() if str(item["decision_id"]) == decision_id
            ],
            evaluations=[
                item for item in self.evaluations() if str(item["decision_id"]) == decision_id
            ],
            decision_record_verified=_decision_hash_from_entry(entry) == str(entry["decision_hash"]),
            snapshot_digest_matches=ac.payload_digest(entry["snapshot"]) == str(entry["snapshot_hash"]),
            provenance_complete=not ap.provenance_missing(entry.get("provenance", {})),
            raw_evidence_present=raw_present,
            raw_evidence_hash_matches=raw_matches,
        )


def _duplicates(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for value in values:
        if value in seen and value not in dups:
            dups.append(value)
        seen.add(value)
    return dups


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay_artifact(
    *,
    decision_id: str,
    found: bool,
    entry: Mapping[str, Any] | None = None,
    outcomes: Sequence[Mapping[str, Any]] = (),
    evaluations: Sequence[Mapping[str, Any]] = (),
    decision_record_verified: bool = False,
    snapshot_digest_matches: bool = False,
    provenance_complete: bool = False,
    raw_evidence_present: bool = False,
    raw_evidence_hash_matches: bool | None = None,
) -> dict[str, Any]:
    """The replay payload: what the analyst saw, and what was measured from it."""
    return {
        "decision_id": decision_id,
        "found": found,
        "reconstructed_input": None if entry is None else entry.get("snapshot"),
        "decision": None if entry is None else dict(entry),
        "chain": {
            "snapshot_hash": None if entry is None else entry.get("snapshot_hash"),
            "decision_hash": None if entry is None else entry.get("decision_hash"),
            "raw_evidence_hash": None if entry is None else entry.get("raw_evidence_hash"),
            "outcomes": [
                {
                    "horizon": item["horizon"],
                    "outcome_hash": item["outcome_hash"],
                    "outcome": item["outcome"],
                    "net_return": item["net_return"],
                    "evidence_hash": item["evidence_hash"],
                }
                for item in outcomes
            ],
            "evaluations": [
                {
                    "horizon": item["horizon"],
                    "evaluation_hash": item["evaluation_hash"],
                    "net_return": item["net_return"],
                }
                for item in evaluations
            ],
        },
        "checks": {
            "decision_record_verified": decision_record_verified,
            "snapshot_digest_matches": snapshot_digest_matches,
            "provenance_complete": provenance_complete,
            "outcomes_linked": bool(outcomes),
            "evaluations_linked": bool(evaluations),
            "raw_evidence_present": raw_evidence_present,
            "raw_evidence_hash_matches": raw_evidence_hash_matches,
        },
        "settled": bool(outcomes),
    }
