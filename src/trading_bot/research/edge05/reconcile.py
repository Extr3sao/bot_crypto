"""EDGE-05 — the auditable correspondence between stored bars, ticks and decisions.

The forward lane writes three things that have to agree with each other: bars in the store, run
rows in its log, and seals in its slot ledger. WP-EDGE-04's own rehearsal produced the case that
makes this module necessary — a tick that was killed between two writes. It had already appended
six bars and appended twelve ledger rows, and it died before it could record itself, so the store
grew by six bars that **no run row claims**. Nothing was lost and nothing was duplicated: the next
tick found the high-water mark where the dead one left it. But from the outside, "the store moved
and no tick says it moved" looks exactly like a bug, and it stays that way for ever unless
something reconstructs the attribution.

This module reconstructs it, and it is explicit about what it could not reconstruct:

* **the chain.** For every series, the lane's own ingest ledger is a high-water chain:
  ``high_water[i] + appended[i] * span == high_water[i+1]``. A chain that does not hold is named
  with both sides of the arithmetic.
* **the claims.** A ledger row that appended *n* bars claims the *n* grid instants immediately
  after its high-water mark. Every bar in the store above the chain's epoch is matched to the row
  that claims it — including the rows of an attempt with no run row, which is what makes the six
  bars attributable to a *process* even though no run recorded it.
* **what has no author.** A stored bar no row claims, a claimed instant the store does not hold,
  an attempt with no run row, a seal naming a run the log no longer holds. Each is a named state,
  never a silent skip.
* **the decisions.** The lane re-reads the whole window on every tick, so two ticks that saw the
  same store must have produced the same decisions. That is a checkable property, and it is
  checked: same ``store.total_bars`` ⇒ same ``decisions_digest`` and same ``captured_decisions``.
  The pipeline's own restart proof — the second ingest pass at one instant — is re-derived here
  as well, from the ledger, because a duplicate bar is the one error a bar-count check cannot see.

The reconciliation never repairs by rewriting. It marks: a register of attributions, a register of
incomplete states, and the recovering tick that ended each episode. The lane's run log, slot
ledger, daily evidence files and store are read and never written — a second process editing the
first process's evidence is how a run log stops being a run log.

Research only: no orders, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research.campaign_reporting import write_json_atomic
from trading_bot.research.edge01.data import BAR_MS
from trading_bot.research.edge03.autonomous import SLOT_CONSUMING_OUTCOMES
from trading_bot.research.edge03.autonomous import read_jsonl as _lane_read_jsonl
from trading_bot.research.edge03.autonomous import stamp

from .watchdog import _parse_ms as parse_instant_ms

__all__ = ["RECONCILIATION_SCHEMA_VERSION", "MARKER_SCHEMA_VERSION", "Reconciler"]

RECONCILIATION_SCHEMA_VERSION = "EDGE05_RECONCILIATION_V1"
MARKER_SCHEMA_VERSION = "EDGE05_INCOMPLETE_STATE_V1"

#: The named states a bar, an attempt or a seal can be in. A reader may match on these strings;
#: there is no "unknown" and no silent skip.
ATTRIBUTED = "ATTRIBUTED"
UNATTRIBUTED_BAR = "UNATTRIBUTED_BAR"
UNATTRIBUTED_ATTEMPT = "UNATTRIBUTED_ATTEMPT"
CLAIMED_BUT_ABSENT = "CLAIMED_BUT_ABSENT"
DOUBLE_CLAIM = "DOUBLE_CLAIM"
CHAIN_BROKEN = "CHAIN_BROKEN"
PRE_EPOCH_BAR = "PRE_EPOCH_BAR"
SEAL_ORPHANED = "SEAL_ORPHANED"
SEAL_MISSING = "SEAL_MISSING"
DECISION_DIVERGENCE = "DECISION_DIVERGENCE"
RESTART_PROOF_BROKEN = "RESTART_PROOF_BROKEN"

#: The states that mean "something is wrong" as opposed to "something is explained".
DEFECT_STATES = (
    UNATTRIBUTED_BAR,
    UNATTRIBUTED_ATTEMPT,
    CLAIMED_BUT_ABSENT,
    DOUBLE_CLAIM,
    CHAIN_BROKEN,
    SEAL_ORPHANED,
    SEAL_MISSING,
    DECISION_DIVERGENCE,
    RESTART_PROOF_BROKEN,
)

#: A bar nobody claims is still reconstructable: the attempt that fetched it is named by the bar's
#: own ``fetched_at_ms`` and by the ledger instant it belongs to. That is the difference between
#: *incomplete* and *lost*.
INCOMPLETE_BUT_RECONSTRUCTED = "RECONSTRUCTED"
INCOMPLETE_AND_ABSENT = "ABSENT"


def _digest_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_rows(rows: Iterable[dict[str, Any]]) -> str:
    blob = "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n" for row in rows
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Reconciler:
    """Reads the lane's evidence and states, bar by bar, who claimed what — or that nobody did.

    Every input is injectable so the rules can be driven over the store's real shape in a test:
    the shipped defaults read the live lane.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        lane_state_root: Path | None = None,
        store_root: Path | None = None,
        state_root: Path | None = None,
        series: Sequence[tuple[str, str]] | None = None,
        clock: Callable[[], float] | None = None,
        ledger_kept: int = 4_032,
    ) -> None:
        import time

        self.repo_root = Path(repo_root).resolve()
        self.lane_state_root = Path(
            lane_state_root
            if lane_state_root is not None
            else self.repo_root / "data" / "forward" / "edge04"
        )
        self.store_root = Path(
            store_root
            if store_root is not None
            else self.repo_root / "data" / "forward" / "edge03"
        )
        self.state_root = Path(
            state_root if state_root is not None else self.repo_root / "data" / "forward" / "edge05"
        )
        self.series: tuple[tuple[str, str], ...] = tuple(
            series
            or (
                ("1h", "BTC"),
                ("1h", "ETH"),
                ("1h", "SOL"),
                ("15m", "BTC"),
                ("15m", "ETH"),
                ("15m", "SOL"),
            )
        )
        self._clock = clock or time.time
        self.ledger_kept = int(ledger_kept)

    # -- layout ------------------------------------------------------------ #
    @property
    def out_dir(self) -> Path:
        return self.state_root / "reconciliation"

    @property
    def report_path(self) -> Path:
        return self.out_dir / "RECONCILIATION.json"

    @property
    def markdown_path(self) -> Path:
        return self.out_dir / "RECONCILIATION.md"

    @property
    def attribution_path(self) -> Path:
        return self.out_dir / "BAR_ATTRIBUTION.json"

    @property
    def markers_path(self) -> Path:
        return self.out_dir / "INCOMPLETE_STATES.jsonl"

    # -- readings ---------------------------------------------------------- #
    def lane_runs(self) -> list[dict[str, Any]]:
        rows, _corrupt = _lane_read_jsonl(self.lane_state_root / "runs.jsonl")
        return rows

    def lane_slots(self) -> list[dict[str, Any]]:
        rows, _corrupt = _lane_read_jsonl(self.lane_state_root / "slots.jsonl")
        return rows

    def lane_ledger(self) -> list[dict[str, Any]]:
        rows, _corrupt = _lane_read_jsonl(self.lane_state_root / "ledger" / "INGEST_LEDGER.jsonl")
        return rows

    def stored(self, timeframe: str, symbol: str) -> list[dict[str, Any]]:
        path = self.store_root / timeframe / f"{symbol.upper()}.jsonl"
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            loaded = json.loads(line)
            if isinstance(loaded, dict):
                rows.append(loaded)
        return rows

    # -- the reconciliation ------------------------------------------------- #
    def reconcile(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Name every stored bar's author, and every state that has none. Reads only."""
        now = int(now_ms if now_ms is not None else self._clock() * 1000)
        runs = self.lane_runs()
        seals = self.lane_slots()
        ledger = self.lane_ledger()
        # The run log stamps its market instant to the second; the ingest ledger stamps the same
        # instant to the millisecond. The correspondence is therefore established at millisecond
        # precision when the log allows it and at second precision otherwise — and the granularity
        # that was used is recorded, because "the same instant" is a claim a reader must be able
        # to check rather than believe.
        runs_by_instant: dict[int, dict[str, Any]] = {}
        runs_by_second: dict[int, dict[str, Any]] = {}
        for row in runs:
            instant = parse_instant_ms(row.get("market_instant_utc"))
            if instant is None:
                continue
            runs_by_instant.setdefault(int(instant), row)
            runs_by_second.setdefault(int(instant) // 1000, row)
        runs_by_id = {str(row.get("run_id")): row for row in runs}

        def run_for_attempt(instant: int) -> tuple[dict[str, Any] | None, str | None]:
            exact = runs_by_instant.get(int(instant))
            if exact is not None:
                return exact, "millisecond"
            coarse = runs_by_second.get(int(instant) // 1000)
            if coarse is not None:
                return coarse, "second"
            return None, None

        # -- the attempts: ledger rows grouped by the market instant they ran at -------------
        attempts: dict[int, list[dict[str, Any]]] = {}
        unattributed_rows: list[dict[str, Any]] = []
        for index, row in enumerate(ledger):
            instant = row.get("run_at_ms")
            if instant is None:
                unattributed_rows.append({"ledger_index": index, "reason": "the row names no instant"})
                continue
            attempts.setdefault(int(instant), []).append({**row, "_ledger_index": index})

        series_names = [f"{timeframe}:{symbol}" for timeframe, symbol in self.series]
        chain: dict[str, dict[str, Any]] = {}
        claims: dict[str, dict[int, dict[str, Any]]] = {name: {} for name in series_names}
        stored_ts_by_series: dict[str, set[int]] = {name: set() for name in series_names}
        defects: list[dict[str, Any]] = []

        for timeframe, symbol in self.series:
            name = f"{timeframe}:{symbol}"
            span = BAR_MS[timeframe]
            rows = [row for row in ledger if f"{row.get('timeframe')}:{row.get('symbol')}" == name]
            rows.sort(key=lambda row: (int(row.get("run_at_ms") or 0), int(row.get("_ledger_index") or 0)))
            stored = self.stored(timeframe, symbol)
            stored_ts = sorted(int(row["ts"]) for row in stored)
            stored_by_ts = {int(row["ts"]): row for row in stored}
            stored_ts_by_series[name] = set(stored_ts)
            epoch = None if not rows else rows[0].get("high_water_ts")
            epoch = int(epoch) if epoch is not None else None
            stored_before_first = int(rows[0].get("stored_before") or 0) if rows else 0
            previous_ts: int | None = None
            broken: list[dict[str, Any]] = []
            for row in rows:
                high_water = row.get("high_water_ts")
                appended = int(row.get("appended") or 0)
                high_water = int(high_water) if high_water is not None else None
                if previous_ts is not None and high_water is not None and high_water != previous_ts:
                    broken.append(
                        {
                            "series": name,
                            "expected_high_water_ts": previous_ts,
                            "expected_high_water_utc": stamp(previous_ts),
                            "observed_high_water_ts": high_water,
                            "observed_high_water_utc": stamp(high_water),
                            "at_utc": stamp(int(row.get("run_at_ms") or 0)),
                            "gap_bars": (high_water - previous_ts) // span,
                        }
                    )
                if high_water is not None:
                    for step in range(1, appended + 1):
                        claimed_ts = high_water + step * span
                        existing = claims[name].get(claimed_ts)
                        if existing is not None:
                            defects.append(
                                {
                                    "state": DOUBLE_CLAIM,
                                    "series": name,
                                    "bar_ts": claimed_ts,
                                    "bar_utc": stamp(claimed_ts),
                                    "first_claim": existing,
                                    "second_claim": {
                                        "run_at_ms": row.get("run_at_ms"),
                                        "at_utc": stamp(int(row.get("run_at_ms") or 0)),
                                        "attributed_run_id": (
                                            run_for_attempt(int(row.get("run_at_ms") or 0))[0] or {}
                                        ).get("run_id"),
                                    },
                                    "reading": (
                                        "two ledger rows claim the same bar: a bar appended twice "
                                        "is a duplicate, whatever the bar count says"
                                    ),
                                }
                            )
                        claims[name][claimed_ts] = {
                            "run_at_ms": row.get("run_at_ms"),
                            "at_utc": stamp(int(row.get("run_at_ms") or 0)),
                            "attributed_run_id": (
                                run_for_attempt(int(row.get("run_at_ms") or 0))[0] or {}
                            ).get("run_id"),
                            "fetched_at_ms": stored_by_ts.get(claimed_ts, {}).get("fetched_at_ms"),
                        }
                    previous_ts = high_water + appended * span
            pre_epoch = [ts for ts in stored_ts if epoch is not None and ts <= epoch]
            post_epoch = [ts for ts in stored_ts if epoch is None or ts > epoch]
            if epoch is not None and stored_before_first and len(pre_epoch) != stored_before_first:
                defects.append(
                    {
                        "state": CHAIN_BROKEN,
                        "series": name,
                        "kind": "EPOCH_MISMATCH",
                        "epoch_ts": epoch,
                        "epoch_utc": stamp(epoch),
                        "stored_before_the_chain_started": stored_before_first,
                        "stored_at_or_below_the_epoch": len(pre_epoch),
                        "reading": (
                            "the first ledger row on file says how many bars existed before it, "
                            "and the store disagrees: the ledger was front-truncated, so the bars "
                            "below the epoch are not this lane's to attribute"
                        ),
                    }
                )
            absent = [ts for ts in claims[name] if ts not in stored_by_ts]
            for ts in sorted(absent):
                defects.append(
                    {
                        "state": CLAIMED_BUT_ABSENT,
                        "series": name,
                        "bar_ts": ts,
                        "bar_utc": stamp(ts),
                        "claim": claims[name][ts],
                        "reading": (
                            "a ledger row claims a bar the store does not hold: the ledger and the "
                            "store disagree about what was written"
                        ),
                    }
                )
            orphan_bars: list[dict[str, Any]] = []
            for ts in post_epoch:
                if ts in claims[name]:
                    continue
                bar = stored_by_ts[ts]
                fetched = bar.get("fetched_at_ms")
                attempt = None
                if isinstance(fetched, int):
                    # The bar carries its own fetch instant. The attempt whose market instant is
                    # closest to it is the attempt that wrote it — that is the reconstruction.
                    nearest = min(
                        attempts,
                        key=lambda instant: abs(instant - int(fetched)),
                        default=None,
                    )
                    if nearest is not None:
                        attributed, granularity = run_for_attempt(int(nearest))
                        attempt = {
                            "attempt_at_ms": int(nearest),
                            "attempt_at_utc": stamp(int(nearest)),
                            "distance_seconds": round(abs(int(nearest) - int(fetched)) / 1000.0, 3),
                            "attributed_run_id": (attributed or {}).get("run_id"),
                            "attempt_has_run_row": attributed is not None,
                            "match_granularity": granularity,
                        }
                entry = {
                    "state": UNATTRIBUTED_BAR,
                    "series": name,
                    "bar_ts": ts,
                    "bar_utc": stamp(ts),
                    "fetched_at_utc": stamp(int(fetched)) if isinstance(fetched, int) else None,
                    "attempt": attempt,
                    "reconstruction": (
                        "the bar is in the store and no ledger row claims it; the attempt that "
                        "fetched it is named by the bar's own fetch instant"
                    ),
                    "removed": False,
                }
                orphan_bars.append(entry)
                defects.append(entry)
            chain[name] = {
                "series": name,
                "span_ms": span,
                "epoch_ts": epoch,
                "epoch_utc": stamp(epoch) if epoch is not None else None,
                "ledger_rows": len(rows),
                "distinct_instants": len({int(row.get("run_at_ms") or 0) for row in rows}),
                "claimed_bars": len(claims[name]),
                "stored_bars": len(stored),
                "pre_epoch_bars": len(pre_epoch),
                "post_epoch_bars": len(post_epoch),
                "post_epoch_attributed": len(post_epoch) - len(orphan_bars),
                "unattributed_bars": len(orphan_bars),
                "unattributed_detail": orphan_bars,
                "claimed_but_absent": len(absent),
                "chain_breaks": broken,
                "chain_holds": not broken,
            }
            for item in broken:
                defects.append({"state": CHAIN_BROKEN, **item})

        # -- attempts with no run row --------------------------------------------------------
        attempts_without_run: list[dict[str, Any]] = []
        for instant in sorted(attempts):
            pass_rows = attempts[instant]
            attributed, granularity = run_for_attempt(instant)
            if attributed is not None:
                continue
            appended = sum(int(row.get("appended") or 0) for row in pass_rows)
            bars: list[dict[str, Any]] = []
            for row in pass_rows:
                span = BAR_MS[str(row.get("timeframe"))]
                high_water = row.get("high_water_ts")
                for step in range(1, int(row.get("appended") or 0) + 1):
                    ts = int(high_water) + step * span
                    bars.append(
                        {
                            "series": f"{row.get('timeframe')}:{row.get('symbol')}",
                            "bar_ts": ts,
                            "bar_utc": stamp(ts),
                        }
                    )
            record = {
                "state": UNATTRIBUTED_ATTEMPT,
                "attempt_at_ms": instant,
                "attempt_at_utc": stamp(instant),
                "ledger_rows": len(pass_rows),
                "bars_appended": appended,
                "match_granularity": None,
                "bars": bars,
                "next_attempt_with_a_run": None,
                "next_run_id": None,
                "reading": (
                    "the lane's ingest ledger holds an attempt at this market instant and the run "
                    "log holds no run that names it: the process wrote bars and died before it "
                    "recorded itself"
                ),
            }
            # An attempt that appended nothing has no interval to cover; one that appended bars is
            # covered only if every bar it claims is actually in the store. Anything less is a
            # bar the ledger says was written and the store does not hold, which is its own defect
            # (CLAIMED_BUT_ABSENT) and keeps this attempt open rather than historical.
            record["interval_covered"] = all(
                bar["bar_ts"] in stored_ts_by_series.get(bar["series"], set()) for bar in bars
            )
            record["bars_present_in_store"] = sum(
                1 for bar in bars if bar["bar_ts"] in stored_ts_by_series.get(bar["series"], set())
            )
            later = [i for i in sorted(runs_by_second) if i * 1000 > instant]
            if later:
                recorder = runs_by_second[later[0]]
                record["next_attempt_with_a_run"] = stamp(later[0] * 1000)
                record["next_run_id"] = recorder.get("run_id")
                record["next_run_appended_bars"] = recorder.get("new_bars")
                record["next_run_stored_total"] = (recorder.get("store") or {}).get("total_bars")
                if not bars:
                    record["recovery"] = (
                        "the attempt appended no bar, so there is no interval to recover: its "
                        "ledger rows are the record of an ingest that found nothing new, and the "
                        "missing run row means the process ended between the pipeline and its own "
                        "record of itself"
                    )
                elif int(recorder.get("new_bars") or 0) == 0:
                    record["recovery"] = (
                        "the first later run found the bars already above its high-water mark and "
                        "appended none of them again: the interval is covered exactly once, by the "
                        "attempt that never recorded itself"
                    )
                else:
                    record["recovery"] = (
                        "the first later run appended bars of its own, above the bars this attempt "
                        "had already stored: the interval is covered exactly once"
                    )
            attempts_without_run.append(record)
            defects.append(record)

        # -- seals against runs ---------------------------------------------------------------
        consuming = [row for row in runs if str(row.get("outcome")) in SLOT_CONSUMING_OUTCOMES]
        attempt_seconds = {int(instant) // 1000 for instant in attempts}
        seals_orphaned: list[dict[str, Any]] = []
        seals_of_unrecorded_runs: list[dict[str, Any]] = []
        for row in seals:
            if str(row.get("run_id")) in runs_by_id:
                continue
            instant = parse_instant_ms(row.get("observed_at_utc")) or parse_instant_ms(
                row.get("at_utc")
            )
            entry = {
                "slot_key": row.get("slot_key"),
                "run_id": row.get("run_id"),
                "outcome": row.get("outcome"),
                "at_utc": row.get("at_utc"),
                "observed_at_utc": row.get("observed_at_utc"),
            }
            if instant is not None and int(instant) // 1000 in attempt_seconds:
                # The seal belongs to a tick that ingested and never recorded itself: the seal is
                # the second half of the same episode, and the attempt it belongs to is named
                # below. Counting it twice would make one dead tick look like two faults.
                seals_of_unrecorded_runs.append({**entry, "belongs_to_attempt": stamp(int(instant))})
                continue
            seals_orphaned.append(
                {
                    "state": SEAL_ORPHANED,
                    **entry,
                    "reading": (
                        "the slot ledger holds a seal naming a run the run log no longer holds, and "
                        "no ingest attempt matches its instant: the run log was front-truncated "
                        "past it, and the seal is the durable record"
                    ),
                }
            )
        sealed_by_run: dict[str, str] = {}
        for row in seals:
            sealed_by_run.setdefault(str(row.get("run_id")), str(row.get("slot_key")))
        seals_missing = [
            {
                "state": SEAL_MISSING,
                "run_id": row.get("run_id"),
                "slot_key": row.get("slot_key"),
                "outcome": row.get("outcome"),
                "slot_sealed": row.get("slot_sealed"),
                "reading": (
                    "a tick consumed a slot and the slot ledger holds no seal for its run: either "
                    "the seal was truncated or the tick sealed a slot the ledger already had"
                ),
            }
            for row in consuming
            if str(row.get("run_id")) not in sealed_by_run
            and row.get("slot_sealed") is not False
            and not row.get("slot_seal_held_by")
        ]
        defects.extend(seals_orphaned)
        defects.extend(seals_missing)
        # The seals of an unrecorded run belong to the attempt that wrote them: attached here, so
        # one dead tick reads as one episode with two pieces of evidence instead of two faults.
        for record in attempts_without_run:
            record["seals_of_this_attempt"] = [
                item
                for item in seals_of_unrecorded_runs
                if item["belongs_to_attempt"] == record["attempt_at_utc"]
            ]

        # -- decisions: the same store must produce the same decisions ------------------------
        divergence: list[dict[str, Any]] = []
        comparable = [row for row in consuming if isinstance((row.get("store") or {}).get("total_bars"), int)]
        for previous, current in zip(comparable, comparable[1:]):
            same_store = (previous["store"]["total_bars"]) == (current["store"]["total_bars"])
            same_digest = str(previous.get("decisions_digest")) == str(current.get("decisions_digest"))
            same_captured = int(previous.get("captured_decisions") or 0) == int(
                current.get("captured_decisions") or 0
            )
            if same_store and not (same_digest and same_captured):
                divergence.append(
                    {
                        "state": DECISION_DIVERGENCE,
                        "store_bars": previous["store"]["total_bars"],
                        "previous_run_id": previous.get("run_id"),
                        "previous_outcome": previous.get("outcome"),
                        "previous_decisions_digest": previous.get("decisions_digest"),
                        "previous_captured_decisions": previous.get("captured_decisions"),
                        "current_run_id": current.get("run_id"),
                        "current_outcome": current.get("outcome"),
                        "current_decisions_digest": current.get("decisions_digest"),
                        "current_captured_decisions": current.get("captured_decisions"),
                        "reading": (
                            "two ticks read a store of the same size and produced different "
                            "decisions: the evaluation is not a function of the store"
                        ),
                    }
                )
        defects.extend(divergence)

        # -- the restart proof, re-derived ----------------------------------------------------
        restart_broken: list[dict[str, Any]] = []
        restart_proofs = 0
        for instant in sorted(attempts):
            rows = attempts[instant]
            seen: set[str] = set()
            positions: dict[str, int] = {}
            for row in rows:
                key = f"{row.get('timeframe')}:{row.get('symbol')}"
                positions[key] = positions.get(key, 0) + 1
            if max(positions.values(), default=0) < 2:
                continue
            restart_proofs += 1
            for row in rows:
                key = f"{row.get('timeframe')}:{row.get('symbol')}"
                if key in seen and int(row.get("appended") or 0):
                    restart_broken.append(
                        {
                            "state": RESTART_PROOF_BROKEN,
                            "series": key,
                            "attempt_at_utc": stamp(instant),
                            "appended_on_the_second_pass": int(row.get("appended") or 0),
                            "reading": (
                                "the second ingest pass at one market instant appended a bar: the "
                                "restart proof the pipeline claims does not hold"
                            ),
                        }
                    )
                seen.add(key)
        defects.extend(restart_broken)

        ordered = sorted(defects, key=lambda item: (str(item.get("state")), str(item.get("bar_ts") or "")))
        # A defect that is a *closed* episode must not keep an alarm ringing for ever, and it must
        # not be re-labelled as clean either: an attempt that died, whose bars are all present and
        # whose interval no later tick rewrote, is a historical fact. Anything else is open.
        def _closed_episode(item: dict[str, Any]) -> bool:
            """An attempt that died is a closed episode when a later tick found it covered.

            Both halves matter: a run row must record the next attempt (or the whole thing is
            unattributed and unattributed *now*), and every bar the dead attempt claims must be in
            the store. A bar it claims and the store does not hold keeps the episode open.
            """
            return (
                str(item.get("state")) == UNATTRIBUTED_ATTEMPT
                and bool(item.get("next_run_id"))
                and bool(item.get("interval_covered", True))
            )

        for item in ordered:
            if str(item.get("state")) == UNATTRIBUTED_ATTEMPT:
                item["episode"] = "CLOSED" if _closed_episode(item) else "OPEN"
        historical = [item for item in ordered if _closed_episode(item)]
        open_defects = [item for item in ordered if not _closed_episode(item)]
        status = "CLEAN" if not ordered else "HISTORICAL_ONLY" if not open_defects else "OPEN_DEFECTS"
        verdict = "RECONCILIATION_CLEAN" if not ordered else "RECONCILIATION_INCOMPLETE"
        report: dict[str, Any] = {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "generated_at_utc": stamp(now),
            "generated_at_ms": now,
            "verdict": verdict,
            "inputs": {
                "lane_state_root": str(self.lane_state_root),
                "store_root": str(self.store_root),
                "runs_path": str(self.lane_state_root / "runs.jsonl"),
                "slots_path": str(self.lane_state_root / "slots.jsonl"),
                "ledger_path": str(self.lane_state_root / "ledger" / "INGEST_LEDGER.jsonl"),
                "digests": {
                    "runs_jsonl": _digest_file(self.lane_state_root / "runs.jsonl"),
                    "slots_jsonl": _digest_file(self.lane_state_root / "slots.jsonl"),
                    "ingest_ledger_jsonl": _digest_file(
                        self.lane_state_root / "ledger" / "INGEST_LEDGER.jsonl"
                    ),
                },
                "counts": {
                    "runs": len(runs),
                    "consuming_runs": len(consuming),
                    "seals": len(seals),
                    "ledger_rows": len(ledger),
                    "ingest_attempts": len(attempts),
                },
                "ledger_row_cap": self.ledger_kept,
                "ledger_truncated": len(ledger) >= self.ledger_kept,
            },
            "rule": (
                "each ingest ledger row claims the grid instants immediately after its high-water "
                "mark; every stored bar above the chain's epoch must be claimed by exactly one "
                "row, and every row's high-water mark must be the previous row's end"
            ),
            "chains": chain,
            "attempts": {
                "total": len(attempts),
                "with_a_run": len(attempts) - len(attempts_without_run),
                "without_a_run": len(attempts_without_run),
                "without_a_run_detail": attempts_without_run,
            },
            "seals": {
                "total": len(seals),
                "orphaned": seals_orphaned,
                "of_an_unrecorded_run": seals_of_unrecorded_runs,
                "missing_for_a_consuming_run": seals_missing,
            },
            "decisions": {
                "comparable_pairs": max(0, len(comparable) - 1),
                "divergences": divergence,
                "rule": (
                    "two consecutive consuming ticks that read a store of the same size must have "
                    "produced the same decisions digest and the same captured count"
                ),
                "captured_total": sum(int(row.get("captured_decisions") or 0) for row in consuming),
                "digests_seen": sorted({str(row.get("decisions_digest")) for row in consuming}),
            },
            "restart_proof": {
                "instants_with_two_passes": restart_proofs,
                "broken": restart_broken,
                "reading": (
                    "the pipeline ingests twice at one market instant on purpose; the second pass "
                    "must append nothing"
                ),
            },
            "status": status,
            "defects": ordered,
            "open_defects": open_defects,
            "historical_defects": historical,
            "defect_counts": {
                state: sum(1 for item in ordered if str(item.get("state")) == state)
                for state in DEFECT_STATES
            },
            "open_defect_counts": {
                state: sum(1 for item in open_defects if str(item.get("state")) == state)
                for state in DEFECT_STATES
            },
            "reconstruction": {
                "every_stored_bar_has_an_author_or_a_name": all(
                    body["post_epoch_attributed"] + body["unattributed_bars"]
                    == body["post_epoch_bars"]
                    for body in chain.values()
                ),
                "bars_removed": 0,
                "lane_files_rewritten": [],
                "reading": (
                    "a bar with no claiming row is not deleted and is not silently attributed: it "
                    "is named, with the attempt that fetched it, and preserved"
                ),
            },
            "lane_writes": 0,
            "market_requests": 0,
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        return report

    # -- writing the artefacts --------------------------------------------------------------- #
    def write(self, report: dict[str, Any]) -> dict[str, Path]:
        """Write the register, the report and the marked incomplete states. Never the lane's."""
        import shutil

        self.out_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.report_path, {**report, "artifacts": None})
        attribution = {
            "schema_version": "EDGE05_BAR_ATTRIBUTION_V1",
            "generated_at_utc": report["generated_at_utc"],
            "store_root": report["inputs"]["store_root"],
            "chains": {
                name: {key: value for key, value in body.items() if key != "unattributed_detail"}
                for name, body in report["chains"].items()
            },
            "rule": report["rule"],
            "unattributed_bars": [
                item for item in report["defects"] if str(item.get("state")) == UNATTRIBUTED_BAR
            ],
            "attempts_without_a_run": report["attempts"]["without_a_run_detail"],
            "removed": [],
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        write_json_atomic(self.attribution_path, attribution)
        # The incomplete states are a log, not a rewrite: one row per state, appended in the same
        # order they are reported, so a reader can diff two reconciliations.
        markers = self._markers(report)
        existing, _ = _lane_read_jsonl(self.markers_path)
        if [dict(row) for row in existing] != markers:
            if existing:
                shutil.copyfile(self.markers_path, self.markers_path.with_suffix(".previous.jsonl"))
            blob = "".join(
                json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n"
                for row in markers
            )
            self.markers_path.write_text(blob, encoding="utf-8")
        self.markdown_path.write_text(self.render(report), encoding="utf-8")
        return {
            "reconciliation": self.report_path,
            "attribution": self.attribution_path,
            "markers": self.markers_path,
            "markdown": self.markdown_path,
        }

    def _markers(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        markers: list[dict[str, Any]] = []
        for item in report["attempts"]["without_a_run_detail"]:
            markers.append(
                {
                    "schema_version": MARKER_SCHEMA_VERSION,
                    "state": "ATTEMPT_WITHOUT_A_RUN",
                    "attempt_at_utc": item["attempt_at_utc"],
                    "bars_appended": item["bars_appended"],
                    "reconstruction": INCOMPLETE_BUT_RECONSTRUCTED,
                    "recovered_by_run_id": item.get("next_run_id"),
                    "bars": item["bars"],
                }
            )
        for item in report["defects"]:
            if str(item.get("state")) != UNATTRIBUTED_BAR:
                continue
            markers.append(
                {
                    "schema_version": MARKER_SCHEMA_VERSION,
                    "state": "BAR_WITHOUT_AN_AUTHOR",
                    "series": item["series"],
                    "bar_utc": item["bar_utc"],
                    "reconstruction": INCOMPLETE_BUT_RECONSTRUCTED,
                    "attempt": item.get("attempt"),
                    "preserved_in_store": True,
                }
            )
        return markers

    def render(self, report: dict[str, Any]) -> str:
        counts = report["defect_counts"]
        chains = report["chains"]
        lines = [
            "# WP-EDGE-05 — reconciliation of the forward lane (store ↔ ticks ↔ decisions)",
            "",
            f"*Generated {report['generated_at_utc']} · verdict **{report['verdict']}** · "
            f"status **{report['status']}** · {len(report['defects'])} finding(s), "
            f"{len(report['open_defects'])} open, {len(report['historical_defects'])} historical · "
            f"stored bars: {sum(int(body['stored_bars']) for body in chains.values())}*",
            "",
            "Reads only: the lane's run log, slot ledger, ingest ledger and the store. Nothing here "
            "is rewritten, nothing is deleted, and no strategy is promoted.",
            "",
            "## Counts",
            "",
            "| | |",
            "| --- | --- |",
        ]
        for key, value in report["inputs"]["counts"].items():
            lines.append(f"| {key} | {value} |")
        lines += [
            f"| ingest attempts without a run row | {report['attempts']['without_a_run']} |",
            f"| stored bars with no claiming row | {counts[UNATTRIBUTED_BAR]} |",
            f"| claimed bars absent from the store | {counts[CLAIMED_BUT_ABSENT]} |",
            f"| bars claimed twice | {counts[DOUBLE_CLAIM]} |",
            f"| chain breaks | {counts[CHAIN_BROKEN]} |",
            f"| decision divergences | {counts[DECISION_DIVERGENCE]} |",
            f"| restart-proof breaks | {counts[RESTART_PROOF_BROKEN]} |",
            f"| restart proofs re-derived | {report['restart_proof']['instants_with_two_passes']} |",
            "",
            "## Chains",
            "",
            "| series | epoch | ledger rows | claimed | stored | unattributed | holds |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for name, body in sorted(chains.items()):
            lines.append(
                f"| {name} | {body['epoch_utc']} | {body['ledger_rows']} | {body['claimed_bars']} | "
                f"{body['stored_bars']} | {body['unattributed_bars']} | "
                f"{'yes' if body['chain_holds'] else 'no'} |"
            )
        if report["attempts"]["without_a_run_detail"]:
            lines += ["", "## Attempts with no run row", ""]
            for item in report["attempts"]["without_a_run_detail"]:
                lines += [
                    f"* **{item['attempt_at_utc']}** — {item['ledger_rows']} ledger rows, "
                    f"{item['bars_appended']} bar(s) appended, no run row.",
                    f"  * {item['reading']}",
                    f"  * recovered by `{item.get('next_run_id')}` at "
                    f"{item.get('next_attempt_with_a_run')}: {item.get('recovery')}",
                ]
                for bar in item["bars"]:
                    lines.append(f"  * bar `{bar['series']}` @ `{bar['bar_utc']}`")
        if report["defects"]:
            lines += ["", "## Every finding", ""]
            for item in report["defects"]:
                lines.append(f"* `{item['state']}` — {json.dumps(item, sort_keys=True, default=str)}")
        if report["open_defects"]:
            lines += ["", "## Open findings (what needs a person)", ""]
            for item in report["open_defects"]:
                lines.append(f"* `{item['state']}` — {json.dumps(item, sort_keys=True, default=str)}")
        lines += [
            "",
            "## What is *not* here",
            "",
            "* no promotion, no threshold change, no strategy ranking;",
            "* no order, no capital, no exchange client;",
            "* no rewrite of the lane's logs and no deletion of a bar.",
            "",
        ]
        return "\n".join(lines)
