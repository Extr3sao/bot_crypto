"""POC02 daily coverage authority (DAILY COVERAGE AUTHORITY RECONCILIATION).

Separates, permanently and explicitly:

    DAY_BUCKET_EXISTS        a coverage bucket row exists for the UTC day
    DAY_HAS_VALID_EVIDENCE   successful cycles + receipts recorded in it
    DAY_CLOSED               the UTC day boundary has passed
    DAY_VALIDITY             OPEN | PENDING_VALIDATION | VALID | INVALID
    DAY_COUNTS_FOR_COVERAGE  only CLOSED + VALID days

Canonical day states (§2):

    OPEN                current UTC day, still accumulating
    PENDING_VALIDATION  bucket exists, boundary passed, finalizer not run
    VALID               finalized after the boundary; contract satisfied
    INVALID             finalized after the boundary; contract failed

Authoritative coverage (§3/§4):

    CAMPAIGN_COVERAGE = VALID_CLOSED_DAYS / CLOSED_ELIGIBLE_DAYS
    denominator 0  ->  NOT_YET_MEASURABLE (never 1.0)

Provisional metrics (§5: PROVISIONAL_OBSERVED_BUCKETS, CURRENT_DAY_*,
prior "1/1"-style presentations) are observational ONLY and never feed
coverage >= 0.80, certification or campaign validity.

The finalizer (§6/§7/§8) is idempotent: FINALIZATION_COUNT_PER_DAY = 1;
early calls return DAY_NOT_CLOSED; corrections append AMENDMENT receipts
(§9) — the original finalization receipt is never overwritten.

Day validity (§7) applies the PREREGISTERED contract reasons — the
POC01-canonical semantics (FINALIZED ∧ COUNTED ∧ VALID, trade-count
independent, DEF-POC01-OBS-006; outages are coverage evidence, not a
day-invalidation threshold) plus the POC02 manifest contract (>= 0.80
observed/expected minutes is the coverage CONTRACT evidence, zero-trade
days may be valid, governance negatives required).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

__all__ = [
    "DayState",
    "DayStateAuthority",
    "COVERAGE_MIN",
    "MINUTES_PER_DAY",
    "VALIDITY_MIN_RATIO",
]

COVERAGE_MIN = 0.80
MINUTES_PER_DAY = 1440
VALIDITY_MIN_RATIO = COVERAGE_MIN  # preregistered contract; never lowered

OPEN = "OPEN"
PENDING_VALIDATION = "PENDING_VALIDATION"
VALID = "VALID"
INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class DayState:
    """Immutable authoritative view of one UTC campaign day."""

    utc_day: str
    day_bucket_exists: bool
    day_has_valid_evidence: bool
    day_closed: bool
    day_validity: str  # OPEN | PENDING_VALIDATION | VALID | INVALID
    day_counts_for_coverage: bool
    cycles: int
    observed_minutes: int
    validity_reason_codes: tuple[str, ...] = field(default_factory=tuple)
    finalized_at_utc: str | None = None
    finalization_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "utc_day": self.utc_day,
            "DAY_BUCKET_EXISTS": self.day_bucket_exists,
            "DAY_HAS_VALID_EVIDENCE": self.day_has_valid_evidence,
            "DAY_CLOSED": self.day_closed,
            "DAY_VALIDITY": self.day_validity,
            "DAY_COUNTS_FOR_COVERAGE": self.day_counts_for_coverage,
            "cycles": self.cycles,
            "observed_minutes": self.observed_minutes,
            "validity_reason_codes": list(self.validity_reason_codes),
            "finalized_at_utc": self.finalized_at_utc,
            "finalization_count": self.finalization_count,
        }


class DayStateAuthority:
    """Single authority for day states, finalization and coverage math.

    Reads coverage buckets and receipts from the campaign directory; all
    clock access goes through ``clock`` (injected in tests — no local-time
    dependence, no sleeps).
    """

    def __init__(self, campaign_dir: Path | str, *, clock=None) -> None:
        self._dir = Path(campaign_dir)
        self._coverage_path = self._dir / "POC02_COVERAGE_DAILY.jsonl"
        self._finalization_path = self._dir / "POC02_DAY_FINALIZATIONS.json"
        self._receipts_dir = self._dir / "receipts"
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- persistence ---------------------------------------------------------

    def _load_coverage_rows(self) -> dict[str, dict]:
        rows: dict[str, dict] = {}
        if self._coverage_path.exists():
            for line in self._coverage_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    rows[r["utc_day"]] = r
        return rows

    def _load_finalizations(self) -> dict[str, dict]:
        if self._finalization_path.exists():
            return json.loads(self._finalization_path.read_text(encoding="utf-8"))
        return {}

    def _save_finalizations(self, fin: dict[str, dict]) -> None:
        self._finalization_path.write_text(
            json.dumps(fin, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _receipt_count(self, day: str) -> int:
        if not self._receipts_dir.exists():
            return 0
        return len(list(self._receipts_dir.glob(f"RECEIPT_{day}_*.json")))

    # -- day state (§1/§2) ---------------------------------------------------

    def day_state(self, day: str) -> DayState:
        rows = self._load_coverage_rows()
        fin = self._load_finalizations()
        row = rows.get(day)
        now = self._clock()
        bucket_exists = row is not None
        cycles = int((row or {}).get("observed_cycles", 0) or 0)
        minutes = int((row or {}).get("observed_minutes", 0) or 0)
        # §7 valid evidence requires BOTH recorded cycles AND the immutable
        # per-day receipt(s) that bind them (partial artifacts fail closed)
        has_evidence = bucket_exists and cycles > 0 and self._receipt_count(day) > 0
        f = fin.get(day)

        if f is not None:
            # finalized: terminal state, immutable except via amendment
            return DayState(
                utc_day=day,
                day_bucket_exists=bucket_exists,
                day_has_valid_evidence=has_evidence,
                day_closed=True,
                day_validity=f["validity"],
                day_counts_for_coverage=f["validity"] == VALID,
                cycles=cycles,
                observed_minutes=minutes,
                validity_reason_codes=tuple(f.get("reason_codes", [])),
                finalized_at_utc=f["finalized_at_utc"],
                finalization_count=int(f.get("finalization_count", 1)),
            )

        closed = self._is_closed(day, now)
        if not bucket_exists:
            if closed:
                # a day with no bucket and no cycles: not a campaign day
                return DayState(
                    utc_day=day,
                    day_bucket_exists=False,
                    day_has_valid_evidence=False,
                    day_closed=True,
                    day_validity=PENDING_VALIDATION,
                    day_counts_for_coverage=False,
                    cycles=0,
                    observed_minutes=0,
                    validity_reason_codes=("NO_BUCKET_NO_EVIDENCE",),
                )
            return DayState(
                utc_day=day,
                day_bucket_exists=False,
                day_has_valid_evidence=False,
                day_closed=False,
                day_validity=OPEN,
                day_counts_for_coverage=False,
                cycles=0,
                observed_minutes=0,
                validity_reason_codes=(),
            )
        # bucket exists
        if not closed:
            return DayState(
                utc_day=day,
                day_bucket_exists=True,
                day_has_valid_evidence=has_evidence,
                day_closed=False,
                day_validity=OPEN,
                day_counts_for_coverage=False,
                cycles=cycles,
                observed_minutes=minutes,
                validity_reason_codes=(),
            )
        return DayState(
            utc_day=day,
            day_bucket_exists=True,
            day_has_valid_evidence=has_evidence,
            day_closed=True,
            day_validity=PENDING_VALIDATION,
            day_counts_for_coverage=False,
            cycles=cycles,
            observed_minutes=minutes,
            validity_reason_codes=("AWAITING_FINALIZATION",),
        )

    def _is_closed(self, day: str, now: datetime) -> bool:
        """§6/§12: day D closes at D+1 00:00:00 UTC (pure UTC math)."""
        boundary = (
            datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(days=1)
        )
        return now >= boundary

    # -- finalizer (§6/§7/§8) ------------------------------------------------

    def finalize_day(self, day: str) -> dict:
        """Idempotent day finalizer. Early calls NEVER finalize."""
        now = self._clock()
        if not self._is_closed(day, now):
            return {
                "DAY_NOT_CLOSED": True,
                "utc_day": day,
                "finalized": False,
                "finalization_count": 0,
                "now_utc": now.isoformat(),
            }
        fin = self._load_finalizations()
        existing = fin.get(day)
        if existing is not None:
            # idempotent: FINALIZATION_COUNT_PER_DAY stays 1; corrections
            # are amendments, never a second finalization
            return {
                "DAY_NOT_CLOSED": False,
                "utc_day": day,
                "finalized": True,
                "already_finalized": True,
                "FINALIZATION_COUNT_PER_DAY": 1,
                "validity": existing["validity"],
                "reason_codes": existing.get("reason_codes", []),
            }
        st = self.day_state(day)
        validity, reasons = self._evaluate_validity(st)
        record = {
            "utc_day": day,
            "validity": validity,
            "reason_codes": list(reasons),
            "finalized_at_utc": now.isoformat(),
            "finalization_count": 1,
            "cycles": st.cycles,
            "observed_minutes": st.observed_minutes,
            "receipts": self._receipt_count(day),
            "contract": {
                "min_ratio": VALIDITY_MIN_RATIO,
                "zero_trade_day_can_be_valid": True,
                "semantics": (
                    "FINALIZED & COUNTED & VALID (trade-count independent, "
                    "DEF-POC01-OBS-006); outages are coverage evidence, "
                    "not a day-invalidation threshold"
                ),
            },
        }
        fin[day] = record
        self._save_finalizations(fin)
        return {
            "DAY_NOT_CLOSED": False,
            "utc_day": day,
            "finalized": True,
            "FINALIZATION_COUNT_PER_DAY": 1,
            "validity": validity,
            "reason_codes": list(reasons),
        }

    def _evaluate_validity(self, st: DayState) -> tuple[str, tuple[str, ...]]:
        """§7 — the preregistered contract, exact reason codes persisted."""
        reasons: list[str] = []
        if not st.day_bucket_exists:
            reasons.append("NO_BUCKET")
        if not st.day_has_valid_evidence:
            reasons.append("NO_VALID_EVIDENCE")
        if st.observed_minutes <= 0 and st.cycles <= 0:
            reasons.append("NO_OBSERVATION")
        # contract: cycles must have been observed with recorded provenance
        if st.cycles > 0 and st.observed_minutes == 0:
            reasons.append("CYCLES_WITHOUT_MINUTE_STAMPS")
        ok = not reasons
        return (VALID if ok else INVALID), tuple(
            reasons if not ok else ("CONTRACT_SATISFIED",)
        )

    # -- coverage (§3/§4) ----------------------------------------------------

    def campaign_coverage(self, *, window_start: str, window_end: str) -> dict:
        """Authoritative coverage from CLOSED days only (§4)."""
        now = self._clock()
        start = datetime.fromisoformat(window_start)
        end = datetime.fromisoformat(window_end)
        eligible: list[str] = []
        d = start
        while d < end:
            day = d.strftime("%Y-%m-%d")
            if d.date() <= now.date():
                eligible.append(day)
            d += timedelta(days=1)
        closed_eligible: list[str] = []
        valid_closed: list[str] = []
        invalid_closed: list[str] = []
        open_eligible: list[str] = []
        for day in eligible:
            st = self.day_state(day)
            if st.day_validity == OPEN:
                open_eligible.append(day)
            elif st.day_validity == PENDING_VALIDATION:
                closed_eligible.append(day)  # closed but not yet finalized
            elif st.day_validity == VALID:
                closed_eligible.append(day)
                valid_closed.append(day)
            elif st.day_validity == INVALID:
                closed_eligible.append(day)
                invalid_closed.append(day)
        denominator = len(closed_eligible)
        if denominator == 0:
            coverage: str | float = "NOT_YET_MEASURABLE"
        else:
            coverage = round(len(valid_closed) / denominator, 6)
        return {
            "CLOSED_ELIGIBLE_DAYS": denominator,
            "VALID_CLOSED_DAYS": len(valid_closed),
            "INVALID_CLOSED_DAYS": len(invalid_closed),
            "OPEN_ELIGIBLE_DAY": open_eligible,
            "CAMPAIGN_COVERAGE": coverage,
            "TARGET_COVERAGE": COVERAGE_MIN,
            "threshold_lowered": False,
            "numerator_source": "VALID_CLOSED only (§3)",
            "denominator_source": "CLOSED_ELIGIBLE only (§4); future days never counted",
        }

    # -- provisional (§5) ----------------------------------------------------

    def provisional_metrics(self, *, current_day: str | None = None) -> dict:
        """OBSERVATIONAL ONLY — must never feed coverage/certification."""
        rows = self._load_coverage_rows()
        day = current_day or self._clock().strftime("%Y-%m-%d")
        cur = rows.get(day, {})
        return {
            "label": "PROVISIONAL — observational, NOT coverage authority",
            "PROVISIONAL_OBSERVED_BUCKETS": len(rows),
            "CURRENT_DAY_CYCLES": int(cur.get("observed_cycles", 0) or 0),
            "CURRENT_DAY_OBSERVED_MINUTES": int(cur.get("observed_minutes", 0) or 0),
            "never_feeds": ["coverage >= 0.80", "certification", "campaign validity"],
        }

    # -- amendment chain (§9) ------------------------------------------------

    def amendment_chain(self, day: str) -> dict:
        receipts = sorted(self._receipts_dir.glob(f"RECEIPT_{day}_*.json"))
        chain: list[dict] = []
        prev_hash: str | None = None
        for i, p in enumerate(receipts, start=1):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
                sha = payload.get("receipt_sha256")
                is_amendment = bool(payload.get("is_amendment"))
            except (OSError, json.JSONDecodeError):
                sha, is_amendment = None, False
            chain.append(
                {
                    "sequence": i,
                    "receipt": p.name,
                    "is_amendment": is_amendment,
                    "previous_hash": prev_hash,
                    "receipt_sha256": sha,
                }
            )
            prev_hash = sha
        return {
            "utc_day": day,
            "receipt_count": len(chain),
            "chain": chain,
            "canonical_latest": chain[-1]["receipt"] if chain else None,
            "historical_retained": True,
        }
