"""Prospective evidence: what the repository *watched happen*, as opposed to what it backfilled.

The distinction this package exists for is the one that cost the previous missions their
most expensive mistake. ``data/forward/edge04/coverage.json`` reports 235 days of dense bars
and only **5** of them were stored while they were happening; the other 229 arrived in bulk
after their own close. A day that is dense is not a day that was observed, and no amount of
row counting can tell the two apart — only the ingest timestamp can.

Three pieces, each with one job:

* :mod:`.store` reads the append-only JSONL bar store and turns ``fetched_at_ms`` into a lag
  for every bar, with the byte offset of each day's last bar so that a day can be sealed to
  an exact prefix of exact bytes.
* :mod:`.admission` classifies a day as ``PROSPECTIVELY_OBSERVED`` only when every declared
  series holds its coverage of bars *and* every one of those bars was stored inside its lag
  bound. Nothing else is an observation.
* :mod:`.ledger` seals those classifications into a hash-chained, append-only attestation
  file, so a count that has been quoted cannot be changed by editing the store afterwards.

:mod:`.independence` counts **observation days**, not experiments: two experiments reading
the same day produce one observation, and the module says so in numbers.

:mod:`.provenance` answers a question the three pieces above cannot: *which declaration
 authorised this capture, under which commit, and was it in force before the bar was fetched?*
 A slice can be a perfect projection of stored bytes and still be ineligible.

Read-only with respect to market data; nothing here places an order or changes a verdict.
"""

from __future__ import annotations

from .admission import (
    ADMISSIBLE,
    DENSE_BUT_BACKFILLED,
    INCOMPLETE,
    PENDING,
    Accumulation,
    DayAdmission,
    accumulate,
    classify_day,
    expected_bars,
    intersection_epoch,
    utc_date,
)
from .independence import (
    DuplicateUsage,
    ObservationBook,
    experiments_sharing,
    independent_day_count,
)
from .ledger import ATT_LEDGER_VERSION, AttestationLedger, LedgerVerification
from .provenance import (
    Declaration,
    DeclarationError,
    Defect,
    ProvenanceRecord,
    authorize,
    eligibility_defects,
)
from .store import (
    DEFAULT_LAG_BOUND_MS,
    INTERVAL_MS,
    Bar,
    SeriesIndex,
    StoreError,
    index_series,
    prefix_digest,
    read_series,
)

__all__ = [
    "ADMISSIBLE",
    "ATT_LEDGER_VERSION",
    "DEFAULT_LAG_BOUND_MS",
    "DENSE_BUT_BACKFILLED",
    "INCOMPLETE",
    "INTERVAL_MS",
    "PENDING",
    "Accumulation",
    "AttestationLedger",
    "Bar",
    "DayAdmission",
    "Declaration",
    "DeclarationError",
    "Defect",
    "DuplicateUsage",
    "LedgerVerification",
    "ObservationBook",
    "ProvenanceRecord",
    "SeriesIndex",
    "StoreError",
    "accumulate",
    "authorize",
    "classify_day",
    "eligibility_defects",
    "expected_bars",
    "experiments_sharing",
    "independent_day_count",
    "index_series",
    "intersection_epoch",
    "prefix_digest",
    "read_series",
    "utc_date",
]
