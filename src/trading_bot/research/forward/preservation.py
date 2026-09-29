"""Data preservation: what must survive before raw may be deleted (§7-§13).

Retention deletes raw segments, so the only defensible question is not "does a
derived file exist" but "can the hypothesis still be measured from what is left".
This module answers that question *before* a deletion, by deriving the hypothesis'
features independently from the raw rows and from the compacted artifact, and
comparing them.

Only what was preregistered
---------------------------

The required resolution is not a matter of taste: it is already on the record in
``config/microstructure_preregistration.json``.

* ``M-03`` (order book imbalance) is preregistered at ``1`` and ``5`` minutes over
  forward book checkpoints plus trade flow.
* ``M-07`` (open interest x price) is preregistered at ``5``, ``15`` and ``30``
  minutes, with an open-interest sampling interval of at most 120 s.

So the comparison below is between the preregistered series computed from raw and
the same series computed from the compact tier. Something that is *not* in the
preregistration — quote-level spread volatility, sub-minute book transitions —
is not silently assumed away: it is named in ``not_covered`` as
``requires_raw_quotes``, because it can only ever come from the raw quote
streams, and a policy that wants it must keep raw.

A mismatch is a refusal
-----------------------

Any difference between the two derivations means the compact artifact is not a
faithful replacement, and the verdict says so by name —
``RAW_NOT_DELETABLE_FOR_M03`` / ``RAW_NOT_DELETABLE_FOR_M07`` — so retention
leaves the raw in place instead of trading evidence for disk space.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from trading_bot.research.forward.storage import iter_segment_rows

__all__ = [
    "M03",
    "M07",
    "PRESERVED",
    "RAW_NOT_DELETABLE_FOR_M03",
    "RAW_NOT_DELETABLE_FOR_M07",
    "FeatureComparison",
    "PreservationPolicy",
    "PreservationReport",
    "compare_features",
    "derive_m03_from_aggregate",
    "derive_m03_from_raw",
    "derive_m07_from_aggregate",
    "derive_m07_from_raw",
    "preservation_for_window",
]

M03: Final[str] = "M-03"
M07: Final[str] = "M-07"
PRESERVED: Final[str] = "PRESERVED_AT_PREREGISTERED_RESOLUTION"
RAW_NOT_DELETABLE_FOR_M03: Final[str] = "RAW_NOT_DELETABLE_FOR_M03"
RAW_NOT_DELETABLE_FOR_M07: Final[str] = "RAW_NOT_DELETABLE_FOR_M07"

BASE_INTERVAL_MINUTES: Final[int] = 1
MINUTE_MS: Final[int] = 60_000

#: Features that are *not* part of the preregistered minimum and can only be
#: reconstructed from the raw quote streams. Named here rather than dropped, so
#: "we chose this resolution" is visible instead of implied.
SUB_MINUTE_FEATURES: Final[tuple[str, ...]] = (
    "quote_level_spread_volatility (book_ticker, every update)",
    "book_transition_count (depth_diff, every update)",
)


def _bucket(ts_ms: int, minutes: int) -> int:
    width = minutes * MINUTE_MS
    return (ts_ms // width) * width


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_event_payload(raw: str | None) -> dict[str, Any] | None:
    """The verbatim payload a row carries, if the capture kept raw (it does)."""
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def evaluate_expression(expression: str, payload: dict[str, Any]) -> Any:
    """A tiny, total accessor for evidence paths like ``detail.spread_bps``.

    Research verdicts must be reproducible from the raw payload alone, so an
    accessor is a lookup — never an eval, and never a silent default.
    """
    node: Any = payload
    for part in expression.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


# --------------------------------------------------------------- raw-side derivation


@dataclass(slots=True)
class _BookCell:
    spreads: list[Decimal] = field(default_factory=list)
    imbalances: list[Decimal] = field(default_factory=list)
    microprice_last: str | None = None
    checkpoints: int = 0
    healthy: int = 0


@dataclass(slots=True)
class _TradeCell:
    buy: Decimal = Decimal(0)
    sell: Decimal = Decimal(0)
    trades: int = 0


@dataclass(slots=True)
class _StateCell:
    oi_last: str | None = None
    oi_values: list[Decimal] = field(default_factory=list)
    mark_last: str | None = None
    index_last: str | None = None


def _iter_rows(paths: list[Path]) -> Any:
    for path in paths:
        if path.suffixes[-2:] == [".jsonl", ".gz"] or path.name.endswith(".jsonl.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        yield row
            continue
        for row, _complete in iter_segment_rows(path):
            if row is not None:
                yield row


def derive_m03_from_raw(
    paths: list[Path], *, interval_minutes: int = BASE_INTERVAL_MINUTES
) -> dict[str, dict[int, dict[str, Any]]]:
    """M-03's book series and trade flow, computed from the raw rows themselves.

    Deliberately a second implementation: it never calls the aggregation module,
    so agreement between the two is evidence instead of a shared bug.
    """
    book: dict[str, dict[int, _BookCell]] = {}
    trades: dict[str, dict[int, _TradeCell]] = {}
    for row in _iter_rows(paths):
        event_type = str(row.get("event_type") or "")
        key = f"{row.get('market')}/{row.get('symbol')}"
        if event_type == "book_checkpoint":
            detail = row.get("detail") or {}
            opened = _bucket(int(row["receive_time"]), interval_minutes)
            cell = book.setdefault(key, {}).setdefault(opened, _BookCell())
            spread = _decimal(evaluate_expression("spread_bps", detail))
            imbalance = _decimal(evaluate_expression("depth_imbalance", detail))
            if spread is not None:
                cell.spreads.append(spread)
            if imbalance is not None:
                cell.imbalances.append(imbalance)
            microprice = evaluate_expression("microprice", detail)
            if microprice is not None:
                cell.microprice_last = str(microprice)
            cell.checkpoints += 1
            if str(detail.get("health")) == "HEALTHY":
                cell.healthy += 1
        elif event_type == "agg_trade":
            if not row.get("exchange_event_time") or row.get("quantity") is None:
                continue
            opened = _bucket(int(row["exchange_event_time"]), interval_minutes)
            cell_trade = trades.setdefault(key, {}).setdefault(opened, _TradeCell())
            quantity = _decimal(row.get("quantity")) or Decimal(0)
            if str(row.get("aggressor_side")) == "buy":
                cell_trade.buy += quantity
            else:
                cell_trade.sell += quantity
            cell_trade.trades += 1

    out_book: dict[str, dict[int, dict[str, Any]]] = {}
    for key, cells in book.items():
        out_book[key] = {
            opened: {
                "spread_bps_mean": _mean(cell.spreads),
                "depth_imbalance_mean": _mean(cell.imbalances),
                "microprice_last": cell.microprice_last,
                "checkpoints": cell.checkpoints,
                "healthy_checkpoints": cell.healthy,
            }
            for opened, cell in sorted(cells.items())
        }
    out_trades: dict[str, dict[int, dict[str, Any]]] = {}
    for key, cells in trades.items():
        out_trades[key] = {
            opened: {
                "taker_imbalance": _imbalance(cell),
                "trade_count": cell.trades,
            }
            for opened, cell in sorted(cells.items())
        }
    return {"book": out_book, "trades": out_trades}


def _mean(values: list[Decimal]) -> str | None:
    if not values:
        return None
    return str(sum(values, Decimal(0)) / Decimal(len(values)))


def _imbalance(cell: _TradeCell) -> str | None:
    total = cell.buy + cell.sell
    if total <= 0:
        return None
    return str((cell.buy - cell.sell) / total)


def derive_m07_from_raw(
    paths: list[Path], *, interval_minutes: int = BASE_INTERVAL_MINUTES
) -> dict[str, dict[int, dict[str, Any]]]:
    """Open interest and the prices it is crossed with, from the raw rows."""
    cells: dict[str, dict[int, _StateCell]] = {}
    for row in _iter_rows(paths):
        event_type = str(row.get("event_type") or "")
        if event_type not in ("open_interest", "mark_price", "funding"):
            continue
        stamp = row.get("exchange_event_time") or row.get("receive_time")
        if stamp is None:
            continue
        key = f"{row.get('market')}/{row.get('symbol')}"
        opened = _bucket(int(stamp), interval_minutes)
        cell = cells.setdefault(key, {}).setdefault(opened, _StateCell())
        if event_type == "open_interest" and row.get("open_interest") is not None:
            cell.oi_last = str(row["open_interest"])
            value = _decimal(row["open_interest"])
            if value is not None:
                cell.oi_values.append(value)
        if event_type == "mark_price":
            if row.get("mark_price") is not None:
                cell.mark_last = str(row["mark_price"])
            if row.get("index_price") is not None:
                cell.index_last = str(row["index_price"])
    return {
        key: {
            opened: {
                "open_interest_last": cell.oi_last,
                "open_interest_mean": _mean(cell.oi_values),
                "open_interest_samples": len(cell.oi_values),
                "mark_price_last": cell.mark_last,
                "index_price_last": cell.index_last,
            }
            for opened, cell in sorted(buckets.items())
        }
        for key, buckets in cells.items()
    }


# ---------------------------------------------------------- compact-side derivation


def _load_aggregation(root: Path, run_id: str, window_start_ms: int) -> dict[str, Any] | None:
    """Read the compact tier's own envelope for one window, from disk."""
    directory = Path(root) / "aggregated" / run_id
    if not directory.exists():
        return None
    for path in sorted(directory.glob(f"{window_start_ms}*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            envelope = json.load(handle)
        aggregation = envelope.get("aggregation")
        if isinstance(aggregation, dict):
            return aggregation
    return None


def derive_m03_from_aggregate(
    aggregation: dict[str, Any], *, interval_minutes: int = BASE_INTERVAL_MINUTES
) -> dict[str, dict[int, dict[str, Any]]]:
    """M-03's series as the compact tier actually stores it."""
    book: dict[str, dict[int, dict[str, Any]]] = {}
    for key, buckets in (aggregation.get("book") or {}).items():
        for bucket in buckets:
            if int(bucket.get("interval_minutes") or 0) != interval_minutes:
                continue
            book.setdefault(key, {})[int(bucket["open_time_ms"])] = {
                "spread_bps_mean": bucket.get("spread_bps_mean"),
                "depth_imbalance_mean": bucket.get("depth_imbalance_mean"),
                "microprice_last": bucket.get("microprice_last"),
                "checkpoints": int(bucket.get("checkpoints") or 0),
                "healthy_checkpoints": int(bucket.get("healthy_checkpoints") or 0),
            }
    trades: dict[str, dict[int, dict[str, Any]]] = {}
    for key, buckets in (aggregation.get("trades") or {}).items():
        for bucket in buckets:
            if int(bucket.get("interval_minutes") or 0) != interval_minutes:
                continue
            trades.setdefault(key, {})[int(bucket["open_time_ms"])] = {
                "taker_imbalance": bucket.get("taker_imbalance"),
                "trade_count": int(bucket.get("trade_count") or 0),
            }
    return {"book": book, "trades": trades}


def derive_m07_from_aggregate(
    aggregation: dict[str, Any], *, interval_minutes: int = BASE_INTERVAL_MINUTES
) -> dict[str, dict[int, dict[str, Any]]]:
    cells: dict[str, dict[int, dict[str, Any]]] = {}
    for key, buckets in (aggregation.get("open_interest") or {}).items():
        for bucket in buckets:
            if int(bucket.get("interval_minutes") or 0) != interval_minutes:
                continue
            cells.setdefault(key, {})[int(bucket["open_time_ms"])] = {
                "open_interest_last": bucket.get("open_interest_last"),
                "open_interest_mean": bucket.get("open_interest_mean"),
                "open_interest_samples": int(bucket.get("open_interest_samples") or 0),
                "mark_price_last": bucket.get("mark_price_last"),
                "index_price_last": bucket.get("index_price_last"),
            }
    return cells


# ------------------------------------------------------------------- comparison


@dataclass(frozen=True, slots=True)
class FeatureComparison:
    feature: str
    compared: int
    mismatches: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "compared": self.compared,
            "mismatches": self.mismatches[:10],
            "mismatch_count": len(self.mismatches),
            "verdict": "MATCH" if self.ok else "MISMATCH",
        }


def _equal(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    left_decimal, right_decimal = _decimal(left), _decimal(right)
    if left_decimal is not None and right_decimal is not None:
        return left_decimal == right_decimal
    return str(left) == str(right)


def compare_features(
    feature: str,
    before: dict[str, dict[int, dict[str, Any]]],
    after: dict[str, dict[int, dict[str, Any]]],
    fields: tuple[str, ...],
) -> FeatureComparison:
    """Compare one feature series bucket by bucket, and name every difference."""
    compared = 0
    mismatches: list[dict[str, Any]] = []
    keys = sorted(set(before) | set(after))
    for key in keys:
        buckets = sorted(set(before.get(key, {})) | set(after.get(key, {})))
        for opened in buckets:
            left = before.get(key, {}).get(opened)
            right = after.get(key, {}).get(opened)
            for name in fields:
                compared += 1
                left_value = None if left is None else left.get(name)
                right_value = None if right is None else right.get(name)
                if not _equal(left_value, right_value):
                    mismatches.append(
                        {
                            "key": key,
                            "bucket_open_ms": opened,
                            "field": name,
                            "raw": left_value,
                            "compact": right_value,
                        }
                    )
    return FeatureComparison(feature=feature, compared=compared, mismatches=mismatches)


@dataclass(frozen=True, slots=True)
class PreservationPolicy:
    """Which hypotheses must survive a deletion, and at what resolution (§12, §13).

    The resolution is a decision, so it is a parameter with the preregistered
    value as its default: asking for sub-minute microstructure is allowed, and it
    fails the preservation check loudly, because no compact tier on this host can
    hold quote-level data for a week.
    """

    require_m03: bool = True
    require_m07: bool = True
    m03_min_resolution_minutes: int = BASE_INTERVAL_MINUTES
    m07_min_resolution_minutes: int = BASE_INTERVAL_MINUTES

    def as_dict(self) -> dict[str, Any]:
        return {
            "require_m03": self.require_m03,
            "require_m07": self.require_m07,
            "m03_min_resolution_minutes": self.m03_min_resolution_minutes,
            "m07_min_resolution_minutes": self.m07_min_resolution_minutes,
            "preregistered_resolution": {"M-03": [1, 5], "M-07": [5, 15, 30]},
            "not_covered_losing_raw_quotes": list(SUB_MINUTE_FEATURES),
        }


@dataclass(slots=True)
class PreservationReport:
    window_start_ms: int
    policy: PreservationPolicy
    comparisons: list[FeatureComparison] = field(default_factory=list)
    verdicts: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def deletion_allowed(self) -> bool:
        return all(verdict == PRESERVED for verdict in self.verdicts.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "forward-preservation-report-v1",
            "window_start_ms": self.window_start_ms,
            "policy": self.policy.as_dict(),
            "comparisons": [comparison.as_dict() for comparison in self.comparisons],
            "verdicts": dict(self.verdicts),
            "reasons": self.reasons[:20],
            "deletion_allowed": self.deletion_allowed,
            "not_covered_without_raw_quotes": list(SUB_MINUTE_FEATURES),
        }


M03_BOOK_FIELDS: Final[tuple[str, ...]] = (
    "spread_bps_mean",
    "depth_imbalance_mean",
    "microprice_last",
    "checkpoints",
)
M03_TRADE_FIELDS: Final[tuple[str, ...]] = ("taker_imbalance",)
M07_FIELDS: Final[tuple[str, ...]] = (
    "open_interest_last",
    "open_interest_mean",
    "open_interest_samples",
    "mark_price_last",
)


def preservation_for_window(
    root: Path | str,
    run_id: str,
    window_start_ms: int,
    raw_paths: list[Path],
    *,
    policy: PreservationPolicy,
) -> PreservationReport:
    """§12/§13 — can this window's raw be deleted without losing M-03 / M-07?"""
    base = Path(root)
    report = PreservationReport(window_start_ms=window_start_ms, policy=policy)
    aggregation = _load_aggregation(base, run_id, window_start_ms)
    if aggregation is None:
        report.reasons.append("no compact artifact found for this window")
        if policy.require_m03:
            report.verdicts[M03] = RAW_NOT_DELETABLE_FOR_M03
        if policy.require_m07:
            report.verdicts[M07] = RAW_NOT_DELETABLE_FOR_M07
        return report

    if policy.require_m03:
        resolution = policy.m03_min_resolution_minutes
        raw = derive_m03_from_raw(raw_paths, interval_minutes=max(1, resolution))
        compact = derive_m03_from_aggregate(
            aggregation, interval_minutes=max(1, resolution)
        )
        book = compare_features("M-03 book series", raw["book"], compact["book"], M03_BOOK_FIELDS)
        flow = compare_features(
            "M-03 trade flow", raw["trades"], compact["trades"], M03_TRADE_FIELDS
        )
        report.comparisons.extend([book, flow])
        if book.compared == 0 and flow.compared == 0:
            # Nothing to compare is not the same as everything matching: a window
            # with no M-03 rows cannot *demonstrate* preservation, so its raw
            # stays. Cheap to keep, and the honest direction to fail in.
            report.verdicts[M03] = RAW_NOT_DELETABLE_FOR_M03
            report.reasons.append(
                "no M-03 rows in this window to compare, so preservation cannot be "
                "demonstrated"
            )
        elif resolution < BASE_INTERVAL_MINUTES:
            report.verdicts[M03] = RAW_NOT_DELETABLE_FOR_M03
            report.reasons.append(
                f"M-03 asked for sub-minute resolution ({resolution} min); no compact "
                "tier preserves quote-level microstructure, so raw must stay"
            )
        elif book.ok and flow.ok:
            report.verdicts[M03] = PRESERVED
        else:
            report.verdicts[M03] = RAW_NOT_DELETABLE_FOR_M03
            report.reasons.append(
                "M-03 does not survive compaction: "
                f"{len(book.mismatches) + len(flow.mismatches)} mismatch(es)"
            )

    if policy.require_m07:
        resolution = policy.m07_min_resolution_minutes
        raw_state = derive_m07_from_raw(raw_paths, interval_minutes=max(1, resolution))
        compact_state = derive_m07_from_aggregate(
            aggregation, interval_minutes=max(1, resolution)
        )
        oi = compare_features("M-07 open interest x price", raw_state, compact_state, M07_FIELDS)
        report.comparisons.append(oi)
        if oi.compared == 0:
            report.verdicts[M07] = RAW_NOT_DELETABLE_FOR_M07
            report.reasons.append(
                "no M-07 rows in this window to compare, so preservation cannot be "
                "demonstrated"
            )
        elif oi.ok:
            report.verdicts[M07] = PRESERVED
        else:
            report.verdicts[M07] = RAW_NOT_DELETABLE_FOR_M07
            report.reasons.append(
                f"M-07 does not survive compaction: {len(oi.mismatches)} mismatch(es)"
            )
    return report
