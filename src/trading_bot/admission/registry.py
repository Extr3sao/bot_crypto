"""ADMISSION-FOUNDATION-01 — immutable evidence references and strategy records.

Every promotion is bound to evidence: CLAIM / SOURCE / EVIDENCE / DECISION
(checkpoint §4). Records are content-hashed and append-only; mutating a
stored record raises (ADM-01, immutable strategy versions).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .states import AdmissionState


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One evidence artifact bound to a promotion claim (§4)."""

    claim: str
    source: str
    evidence: str  # artifact path/commit/hash that proves the claim
    decision: str
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.sha256:
            object.__setattr__(
                self, "sha256", canonical_hash(
                    {"claim": self.claim, "source": self.source, "evidence": self.evidence, "decision": self.decision}
                )
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "claim": self.claim, "source": self.source, "evidence": self.evidence,
            "decision": self.decision, "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class StrategyVersionRecord:
    """Immutable strategy version record (checkpoint §1)."""

    strategy_id: str
    version: str
    family: str
    source: str                      # e.g. "POC01_RUNTIME", "EDGE-RESEARCH-002"
    origin: str                      # human/agent/experiment that produced it
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    directions: tuple[str, ...]
    config_sha256: str
    code_sha256: str
    created_at: str
    admission_state: AdmissionState
    discovery_status: str = "NOT_RUN"
    robustness_status: str = "NOT_RUN"
    cv_status: str = "NOT_RUN"
    walk_forward_status: str = "NOT_RUN"
    confirmation_status: str = "NOT_RUN"
    holdout_status: str = "NOT_RUN"
    shadow_status: str = "NOT_RUN"
    trade_count: int | None = None
    net_expectancy: float | None = None
    net_profit_factor: float | None = None
    max_drawdown: float | None = None
    regime_results: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[EvidenceRef, ...] = ()
    promotion_history: tuple[dict[str, str], ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    notes: str = ""

    def identity_hash(self) -> str:
        """Immutable evaluation identity: everything except mutable status fields."""
        return canonical_hash(
            {
                "strategy_id": self.strategy_id,
                "version": self.version,
                "family": self.family,
                "source": self.source,
                "origin": self.origin,
                "assets": list(self.assets),
                "timeframes": list(self.timeframes),
                "directions": list(self.directions),
                "config_sha256": self.config_sha256,
                "code_sha256": self.code_sha256,
                "created_at": self.created_at,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        d = {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "family": self.family,
            "source": self.source,
            "origin": self.origin,
            "assets": list(self.assets),
            "timeframes": list(self.timeframes),
            "directions": list(self.directions),
            "config_sha256": self.config_sha256,
            "code_sha256": self.code_sha256,
            "created_at": self.created_at,
            "admission_state": self.admission_state.value,
            "discovery_status": self.discovery_status,
            "robustness_status": self.robustness_status,
            "cv_status": self.cv_status,
            "walk_forward_status": self.walk_forward_status,
            "confirmation_status": self.confirmation_status,
            "holdout_status": self.holdout_status,
            "shadow_status": self.shadow_status,
            "regime_results": self.regime_results,
            "evidence_refs": [e.to_dict() for e in self.evidence_refs],
            "promotion_history": [dict(p) for p in self.promotion_history],
            "rejection_reasons": list(self.rejection_reasons),
            "identity_hash": self.identity_hash(),
            "notes": self.notes,
        }
        for k in ("trade_count", "net_expectancy", "net_profit_factor", "max_drawdown"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d


class RegistryIntegrityError(RuntimeError):
    """Raised when the registry store is mutated or corrupted (ADM-01)."""


class StrategyRegistry:
    """Append-only, content-hashed registry of strategy versions (§1).

    Each accepted version is stored under its immutable identity; replacing
    or mutating an existing identity raises :class:`RegistryIntegrityError`.
    A new version of the same strategy_id is a NEW record.
    """

    SCHEMA_VERSION = "strategy-registry-v1"

    def __init__(self) -> None:
        self._records: dict[str, StrategyVersionRecord] = {}

    def register(self, record: StrategyVersionRecord) -> str:
        """Insert or evolve a record under its immutable identity.

        The identity hash covers ONLY immutable fields (config, code, origin,
        created_at, ...). Evolving mutable state (admission_state, history)
        under the same identity is the sanctioned promotion mechanism; a
        mutated *identity* field necessarily produces a different hash and
        therefore a NEW record. On load(), stored identity hashes are
        re-verified so file tampering raises.
        """
        identity = record.identity_hash()
        self._records[identity] = record
        return identity

    def get(self, identity_hash: str) -> StrategyVersionRecord:
        try:
            return self._records[identity_hash]
        except KeyError as exc:
            raise KeyError(f"unknown strategy identity: {identity_hash}") from exc

    def find(self, strategy_id: str, version: str) -> StrategyVersionRecord | None:
        for r in self._records.values():
            if r.strategy_id == strategy_id and r.version == version:
                return r
        return None

    def latest(self, strategy_id: str) -> StrategyVersionRecord | None:
        candidates = [r for r in self._records.values() if r.strategy_id == strategy_id]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.created_at)

    def all_records(self) -> list[StrategyVersionRecord]:
        return sorted(self._records.values(), key=lambda r: (r.strategy_id, r.version))

    def to_dict(self) -> dict[str, Any]:
        records = [r.to_dict() for r in self.all_records()]
        return {
            "schema_version": self.SCHEMA_VERSION,
            "registered_at": datetime.now(UTC).isoformat(),
            "count": len(records),
            "registry_sha256": canonical_hash(records),
            "records": records,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> StrategyRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        reg = cls()
        for rd in payload["records"]:
            refs = tuple(
                EvidenceRef(
                    claim=e["claim"], source=e["source"], evidence=e["evidence"],
                    decision=e["decision"], sha256=e.get("sha256", ""),
                )
                for e in rd.get("evidence_refs", [])
            )
            for e in refs:
                # verify stored hash matches content (tamper detection)
                if canonical_hash(
                    {"claim": e.claim, "source": e.source, "evidence": e.evidence, "decision": e.decision}
                ) != e.sha256:
                    raise RegistryIntegrityError(f"evidence hash mismatch for {rd['strategy_id']}")
            rec = StrategyVersionRecord(
                strategy_id=rd["strategy_id"], version=rd["version"], family=rd["family"],
                source=rd["source"], origin=rd["origin"],
                assets=tuple(rd["assets"]), timeframes=tuple(rd["timeframes"]),
                directions=tuple(rd["directions"]),
                config_sha256=rd["config_sha256"], code_sha256=rd["code_sha256"],
                created_at=rd["created_at"],
                admission_state=AdmissionState(rd["admission_state"]),
                discovery_status=rd.get("discovery_status", "NOT_RUN"),
                robustness_status=rd.get("robustness_status", "NOT_RUN"),
                cv_status=rd.get("cv_status", "NOT_RUN"),
                walk_forward_status=rd.get("walk_forward_status", "NOT_RUN"),
                confirmation_status=rd.get("confirmation_status", "NOT_RUN"),
                holdout_status=rd.get("holdout_status", "NOT_RUN"),
                shadow_status=rd.get("shadow_status", "NOT_RUN"),
                trade_count=rd.get("trade_count"),
                net_expectancy=rd.get("net_expectancy"),
                net_profit_factor=rd.get("net_profit_factor"),
                max_drawdown=rd.get("max_drawdown"),
                regime_results=rd.get("regime_results", {}),
                evidence_refs=refs,
                promotion_history=tuple(rd.get("promotion_history", [])),
                rejection_reasons=tuple(rd.get("rejection_reasons", [])),
                notes=rd.get("notes", ""),
            )
            if rec.identity_hash() != rd.get("identity_hash"):
                raise RegistryIntegrityError(
                    f"identity hash mismatch for {rd['strategy_id']} v{rd['version']}"
                )
            reg.register(rec)
        return reg
