"""EDGE-04 — the WP-EDGE-03 forward lane read by an unattended, scheduled observer.

WP-EDGE-03 proved the chain: it ingests the closed bars the venue published after the
freeze, walks the frozen rulesets over them, checks the research risk budget against the
real runtime engine, and publishes reports. It ran when a person invoked it. This module
turns *that same pipeline* into an observer that the operating system's own scheduler wakes,
so the days accumulate without an operator and without anybody remembering to poll.

What one tick is
----------------
A tick is one invocation of :func:`trading_bot.research.edge03.run.run_forward_observation`
— the same callable the WP-EDGE-03 tests drive, with the same frozen pin — plus a thin layer
that decides whether to run it at all and records what happened:

1. **the slot**: the instant belongs to a 15-minute UTC bucket on the bar grid. With
   ``--due``, a slot that already produced an observation is not observed twice;
2. **the disk**: measured *before* any market request, against the campaign's own storage
   guard. A ``CRITICAL`` volume stops the tick without a single request; a ``WARNING`` volume
   still ingests (bars missed for a disk warning would be lost for ever) but pauses the heavy
   daily publication;
3. **the lease**: the repository's own ``CampaignLock``, so two ticks cannot overlap and a
   crashed tick cannot wedge the lane (age rules, not pid guesses);
4. **the pipeline**, exactly as WP-EDGE-03 runs it, with its ingest rows going to this lane's
   own ledger;
5. **the expectations**: per series, the bars that had closed by the tick's market instant
   against the bars actually appended — this is what turns "nothing new" and "half of it is
   missing" into different outcomes instead of the same silence;
6. **the classification**: one outcome from a closed vocabulary, chosen from the payload
   itself — never from the exit code of a shell, and never "success" for a tick that
   ingested nothing;
7. **the evidence**: a bounded run log, a per-day evidence file that is the durable record of
   coverage, the health and coverage artefacts, the resource budget, and alert events;
8. **the publication**: the heavy WP-EDGE-03 artefact set is written on the declared daily
   cadence, into a staging directory that is then swapped into place, so a tick killed
   mid-write cannot leave a half-written report behind.

What it deliberately does not do:

* it does **not** re-implement or fork the pipeline — there is one forward pipeline in this
  repository and this module calls it;
* it does **not** add a scheduler of its own: the OS task is registered through the same
  supervisor the CAP-004/ST-6 lanes use (``scripts/cap004_supervisor.py``) and the tick has a
  single portable entry point (``scripts/edge04_observer.py``);
* it does **not** invent resource thresholds: the guard is
  :mod:`trading_bot.research.disk_space`;
* it does **not** tune anything. The ruleset is pinned by WP-EDGE-03's
  ``assert_frozen_params`` on every tick, and a ruleset that moved is a refusal;
* it does **not** place orders. Every fill it publishes is hypothetical, ``order_sent`` is
  fixed false, and no module here has an exchange client.

Research only: public market data, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.campaign_lock import CampaignLock
from trading_bot.research.campaign_reporting import write_json_atomic
from trading_bot.research.disk_space import (
    CRITICAL,
    CRITICAL_FREE_BYTES,
    HEALTHY_FREE_BYTES,
    WARNING,
    GrowthSample,
    disk_report,
    estimate_days_to_threshold,
    growth_rate,
    transition_event,
)
from trading_bot.research.edge01.data import ASSETS, BAR_MS

from . import forward_plan as FP
from .ingest import ForwardStore, default_store_root
from .run import FORWARD_SERIES, run_forward_observation

__all__ = [
    "ALERT_KINDS",
    "ALREADY_OBSERVED",
    "ALREADY_RUNNING",
    "BUDGET_SCHEMA_VERSION",
    "COVERAGE_SCHEMA_VERSION",
    "DAILY_SCHEMA_VERSION",
    "DAY_COMPLETE_COVERAGE",
    "DISK_BUDGET_EXCEEDED",
    "EXIT_ALREADY_RUNNING",
    "EXIT_CODES",
    "EXIT_DISK_BUDGET_EXCEEDED",
    "EXIT_ERROR",
    "EXIT_INCOMPLETE_COLLECTION",
    "EXIT_OK",
    "EXIT_PROVIDER_UNAVAILABLE",
    "EXIT_VERIFICATION_FAILED",
    "FAILED_OUTCOMES",
    "HEALTH_SCHEMA_VERSION",
    "LANE_BUDGET_BYTES",
    "LEGACY_OUTCOMES",
    "MISSING_BARS",
    "NO_NEW_DATA",
    "OBSERVATION_FLOOR_DAYS",
    "OBSERVED",
    "PROSPECTIVE_LAG_BOUND_MS",
    "PROVIDER_UNAVAILABLE",
    "RUNTIME_EXCEPTION",
    "SLOT_MINUTES",
    "SLOT_MS",
    "STALE_DATA",
    "STATE_SCHEMA_VERSION",
    "SUCCESSFUL_OUTCOMES",
    "VERIFICATION_FAILED",
    "ForwardObserver",
    "append_jsonl",
    "day_key",
    "directory_bytes",
    "expected_closed_bars",
    "period_hashes",
    "prospective_days",
    "prune_jsonl",
    "read_jsonl",
    "slot_key",
    "slot_of",
    "stamp",
]

#: One schema tag per artefact family, so a reader can tell which generation wrote a file.
STATE_SCHEMA_VERSION = "EDGE04_TICK_V1"
DAILY_SCHEMA_VERSION = "EDGE04_DAILY_V1"
COVERAGE_SCHEMA_VERSION = "EDGE04_COVERAGE_V1"
BUDGET_SCHEMA_VERSION = "EDGE04_RESOURCE_BUDGET_V1"
HEALTH_SCHEMA_VERSION = "EDGE04_HEALTH_V1"

#: The declared cadence. Fifteen minutes, with the publication lag of a bar (measured at
#: 48.8 s median by WP-EDGE-03) left as margin.
SLOT_MINUTES = 15
SLOT_MS = SLOT_MINUTES * 60_000
MINUTE_MS = 60_000
HOUR_MS = 3_600_000
GIB = 1024**3

#: A tick takes tens of seconds, not minutes, so a lease this short cannot cost a slot and
#: still cannot be outlived by a hard-killed process. The age rule — not a pid guess — is what
#: decides, because this platform cannot always prove a pid is dead.
LEASE_STALE_AFTER_SECONDS = 300

#: The heavy WP-EDGE-03 artefact set is rewritten this often. Every tick would write ~2.3 MB
#: of reports; at ninety-six ticks a day that is 220 MB a day for a quantity that only changes
#: when a bar closes.
PUBLICATION_INTERVAL_SECONDS = 86_400

#: The storage guard's own thresholds, restated as this module's defaults rather than
#: replaced: the campaign and the ST-6 lane already run on exactly these numbers.
DISK_WARNING_BYTES = HEALTHY_FREE_BYTES
DISK_CRITICAL_BYTES = CRITICAL_FREE_BYTES

#: Declared budget for everything this lane writes outside the store, enforced by the
#: pruning rules below and measured in ``RESOURCE_BUDGET.json``.
LANE_BUDGET_BYTES = 256 * 1024 * 1024  # 256 MiB

#: Bounded operational logs. The *durable* record of coverage is ``daily/<date>.json``, which
#: is never rewritten; these are the logs behind it. At the declared cadence 2 880 run rows
#: are thirty days, and 4 032 ingest rows are thirty days of twelve series.
RUNS_KEPT = 2_880
SLOTS_KEPT = 2_880
LEDGER_KEPT = 4_032
DAILY_KEPT = 366
DISK_SAMPLES_KEPT = 1_440
ALERTS_KEPT = 500

#: A bar is *prospectively* observed only if it was stored within this long of closing. A day
#: made of bars fetched months later is a backfill and does not count towards the observation
#: floor, however many bars it holds.
PROSPECTIVE_LAG_BOUND_MS: dict[str, int] = {"1h": 2 * HOUR_MS, "15m": 30 * MINUTE_MS}

#: A series whose newest stored bar closed this long ago is stale: the feed stopped, not the
#: schedule.
STALE_AFTER_MS: dict[str, int] = {"1h": 4 * HOUR_MS, "15m": 4 * HOUR_MS}

#: A day counts as an independently observed day only if every primary asset met this coverage
#: of the bars the calendar expects — the rule WP-EDGE-03 declared, applied to the
#: prospective subset.
DAY_COMPLETE_COVERAGE = FP.OBSERVATION_COVERAGE
EXPECTED_BARS_PER_DAY: dict[str, int] = {"1h": 24, "15m": 96}

#: The observation floor this lane accumulates towards. Reaching it is a REQUIREMENT of a
#: later decision, never that decision: this module cannot promote anything.
OBSERVATION_FLOOR_DAYS = FP.MIN_OBSERVATION_DAYS

#: Bounded retry for a provider that answered nothing at all. One retry, after a declared
#: delay; the ingest path already retries each individual request.
MAX_PIPELINE_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 20.0

#: Consecutive ticks that observed nothing, above which the health reading is BLOCKED rather
#: than DEGRADED. Eight ticks is two hours at the declared cadence.
BLOCKED_AFTER_CONSECUTIVE_FAILURES = 8

#: Silence between two *consuming* ticks that is worth an alert. The schedule fires every slot,
#: so the honest baseline is one interval: two missed intervals is a warning and twelve is an
#: interruption — a machine that was asleep, not a provider that hiccuped in one request.
SCHEDULE_INTERVAL_SECONDS = SLOT_MINUTES * 60
GAP_WARNING_SECONDS = 2 * SCHEDULE_INTERVAL_SECONDS + 300
GAP_CRITICAL_SECONDS = 12 * SCHEDULE_INTERVAL_SECONDS

#: The window the health artefact summarises.
HEALTH_WINDOW_SECONDS = 86_400

# -- the outcome vocabulary (closed; a reader may match on these strings) ---------------
#: A tick that appended at least one new closed bar and read the frozen rulesets over it.
OBSERVED = "OBSERVED"
#: A tick that ran the whole pipeline and found nothing new to append. A recorded result.
NO_NEW_DATA = "NO_NEW_DATA"
#: A tick that found its own slot already observed and made no market request at all.
ALREADY_OBSERVED = "ALREADY_OBSERVED"
#: A tick that found another tick holding the lease and touched nothing.
ALREADY_RUNNING = "ALREADY_RUNNING"
#: Every series failed to fetch: the venue, not the lane, is what is missing.
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
#: The tick ran, but bars that had closed are still missing from the store.
MISSING_BARS = "MISSING_BARS"
#: The tick ran and stored nothing because the newest stored bar is older than the feed should
#: ever leave it.
STALE_DATA = "STALE_DATA"
#: The storage guard refused the tick before it made a market request.
DISK_BUDGET_EXCEEDED = "DISK_BUDGET_EXCEEDED"
#: The frozen pin refused: the corpus or the ruleset moved and the lane will not measure it.
VERIFICATION_FAILED = "VERIFICATION_FAILED"
#: The pipeline raised.
RUNTIME_EXCEPTION = "RUNTIME_EXCEPTION"

#: The two outcomes that consume a slot. A *failed* tick does not: a failure must never block
#: the slot its own retry, or the next tick, needs.
SLOT_CONSUMING_OUTCOMES = (OBSERVED, NO_NEW_DATA)

#: Outcomes that are neither an observation nor a verdict on the pipeline: a slot an earlier
#: trigger already sealed, or a trigger that lost the lease to a live one. They are skipped when
#: counting "ticks since the last observation" — a second trigger inside the same slot is the
#: schedule working, and must not be read as the feed failing.
NEUTRAL_OUTCOMES = (ALREADY_OBSERVED, ALREADY_RUNNING)

#: Outcomes an earlier vocabulary carried, kept so an older row stays readable.
LEGACY_OUTCOMES = ("COLLECTED", "UNKNOWN")

SUCCESSFUL_OUTCOMES = (OBSERVED, NO_NEW_DATA, ALREADY_OBSERVED)
FAILED_OUTCOMES = (
    PROVIDER_UNAVAILABLE,
    MISSING_BARS,
    STALE_DATA,
    DISK_BUDGET_EXCEEDED,
    VERIFICATION_FAILED,
    RUNTIME_EXCEPTION,
    ALREADY_RUNNING,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALREADY_RUNNING = 2
EXIT_INCOMPLETE_COLLECTION = 4
EXIT_DISK_BUDGET_EXCEEDED = 5
EXIT_VERIFICATION_FAILED = 6
EXIT_PROVIDER_UNAVAILABLE = 7

EXIT_CODES: dict[str, int] = {
    OBSERVED: EXIT_OK,
    NO_NEW_DATA: EXIT_OK,
    ALREADY_OBSERVED: EXIT_OK,
    ALREADY_RUNNING: EXIT_ALREADY_RUNNING,
    PROVIDER_UNAVAILABLE: EXIT_PROVIDER_UNAVAILABLE,
    MISSING_BARS: EXIT_INCOMPLETE_COLLECTION,
    STALE_DATA: EXIT_INCOMPLETE_COLLECTION,
    DISK_BUDGET_EXCEEDED: EXIT_DISK_BUDGET_EXCEEDED,
    VERIFICATION_FAILED: EXIT_VERIFICATION_FAILED,
    RUNTIME_EXCEPTION: EXIT_ERROR,
}

MODE_SCHEDULED = "SCHEDULED"
MODE_MANUAL = "MANUAL"

#: Alert kinds. Preparation, not a new channel: each event is appended to ``alerts.jsonl`` in
#: the same shape the host's health watch already reads.
ALERT_KINDS = (
    "DISK_WARNING",
    "DISK_CRITICAL",
    "DISK_RECOVERED",
    "BUDGET_EXCEEDED",
    "PROVIDER_UNAVAILABLE",
    "STALE_DATA",
    "MISSING_BARS",
    "VERIFICATION_FAILED",
    "PUBLICATION_PAUSED",
    "HEALTH_BLOCKED",
    "HEALTH_DEGRADED",
    "HEALTH_RECOVERED",
    "OBSERVATION_GAP",
    "OBSERVATION_STALLED",
    "SIGNALS_DETECTED",
)


# --------------------------------------------------------------------------- pure helpers
def stamp(instant_ms: int) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` for a millisecond instant. One spelling, everywhere."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(instant_ms / 1000))


def day_key(instant_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(instant_ms / 1000))


def slot_of(instant_ms: int) -> int:
    """The 15-minute UTC bucket an instant belongs to, as the bucket's start in ms."""
    return (int(instant_ms) // SLOT_MS) * SLOT_MS


def slot_key(slot_ms: int) -> str:
    """``YYYY-MM-DDTHH:MMZ``: sortable, unambiguous, on the bar grid."""
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(int(slot_ms) / 1000))


def parse_slot_key(key: str) -> int:
    parsed = datetime.strptime(key, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def expected_closed_bars(*, high_water_ms: int, span_ms: int, observed_at_ms: int) -> int:
    """How many bars on the grid had closed after ``high_water_ms`` at the tick's instant.

    The newest bar that can have closed is the one that opened at the last whole span
    boundary at or before ``observed_at_ms - span_ms``; anything later is still open. A store
    already at that bar expects nothing, which is why the honest answer for an idle tick is
    zero and not "one".
    """
    if span_ms <= 0:
        raise ValueError("span_ms must be positive")
    last_closed_open = ((int(observed_at_ms) - span_ms) // span_ms) * span_ms
    if last_closed_open <= int(high_water_ms):
        return 0
    return int((last_closed_open - int(high_water_ms)) // span_ms)


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read an append-only log, counting every line that is not a JSON object.

    A tick killed mid-append leaves a truncated last line. That line is *counted*
    (``corrupt``) and skipped: a reader must not crash on it, and must not pretend it was
    never written either.
    """
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    corrupt = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
        else:
            corrupt += 1
    return rows, corrupt


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def prune_jsonl(path: Path, keep: int) -> int:
    """Front-truncate a bounded log. Returns how many rows fell off."""
    rows, _ = read_jsonl(path)
    if len(rows) <= keep:
        return 0
    dropped = len(rows) - keep
    body = "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n"
        for row in rows[-keep:]
    )
    path.write_text(body, encoding="utf-8")
    return dropped


def directory_bytes(path: Path) -> int:
    """Total size of the files under ``path`` (0 when it does not exist)."""
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:  # pragma: no cover - racing deletion
            continue
    return total


def span_ms(timeframe: str) -> int:
    return int(BAR_MS[timeframe])


def _digest_of_rows(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def period_hashes(stored_by_series: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, str]]:
    """One digest per (day, series): the store's own bytes for that day, prefix-16.

    This is what makes a later claim about a day checkable without re-reading the whole store:
    the day's bars are hashed exactly as they are stored.
    """
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key, rows in stored_by_series.items():
        for row in rows:
            buckets.setdefault(day_key(int(row["ts"])), {}).setdefault(key, []).append(row)
    return {
        day: {key: _digest_of_rows(series_rows)[:16] for key, series_rows in sorted(series.items())}
        for day, series in sorted(buckets.items())
    }


def prospective_days(
    *,
    stored_by_series: dict[str, list[dict[str, Any]]],
    timeframes: dict[str, str],
    primary_assets: Sequence[str],
    coverage: float = DAY_COMPLETE_COVERAGE,
) -> dict[str, Any]:
    """Split the days the store covers into days observed live and days backfilled.

    WP-EDGE-03 counted an observation day from bar *coverage* alone, which is right for a
    window and wrong for a floor: the first run of this lane backfilled months of bars that had
    closed before anybody was watching, and counting those as independent forward days would
    let a single afternoon manufacture a sixty-day observation. A day therefore counts here
    only when every primary asset met the declared coverage of the hourly bars the calendar
    expects for it *and* those bars were stored within
    :data:`PROSPECTIVE_LAG_BOUND_MS` of the instant they closed — the lane was running when
    they closed.
    """
    expected = EXPECTED_BARS_PER_DAY["1h"]
    seen: dict[str, dict[str, int]] = {}
    live: dict[str, dict[str, int]] = {}
    for key, rows in stored_by_series.items():
        timeframe = timeframes[key]
        bound = PROSPECTIVE_LAG_BOUND_MS[timeframe]
        span = span_ms(timeframe)
        for row in rows:
            ts = int(row["ts"])
            day = day_key(ts)
            counts = seen.setdefault(key, {})
            counts[day] = counts.get(day, 0) + 1
            lag = int(row.get("fetched_at_ms") or 0) - (ts + span)
            if 0 <= lag <= bound:
                live_counts = live.setdefault(key, {})
                live_counts[day] = live_counts.get(day, 0) + 1

    primary_keys = [f"1h:{asset}" for asset in primary_assets]
    days = sorted({day for counts in seen.values() for day in counts})
    by_day: list[dict[str, Any]] = []
    valid: list[str] = []
    backfilled: list[str] = []
    for day in days:
        counts = {key: seen.get(key, {}).get(day, 0) for key in primary_keys}
        live_counts = {key: live.get(key, {}).get(day, 0) for key in primary_keys}
        ratio = {key: round(live_counts[key] / expected, 6) for key in primary_keys}
        dense = bool(counts) and all(counts[key] >= coverage * expected for key in primary_keys)
        complete = dense and all(ratio[key] >= coverage for key in primary_keys)
        by_day.append(
            {
                "day": day,
                "stored_bars": counts,
                "prospectively_observed_bars": live_counts,
                "expected_bars": expected,
                "coverage": ratio,
                "densely_covered": dense,
                "prospectively_observed": complete,
                "class": (
                    "PROSPECTIVELY_OBSERVED"
                    if complete
                    else "DENSE_BUT_BACKFILLED"
                    if dense
                    else "INCOMPLETE"
                ),
            }
        )
        if complete:
            valid.append(day)
        elif dense:
            backfilled.append(day)
    return {
        "rule": (
            f"a day counts only if every primary asset holds at least {coverage:.0%} of the 24 "
            "hourly bars the calendar expects for it, and every one of those bars was stored "
            f"within its timeframe's lag bound of closing ({PROSPECTIVE_LAG_BOUND_MS})"
        ),
        "primary_assets": list(primary_assets),
        "primary_series": primary_keys,
        "coverage_required": coverage,
        "days": by_day,
        "prospectively_observed_days": valid,
        "prospectively_observed": len(valid),
        "densely_covered_but_backfilled_days": backfilled,
        "densely_covered_but_backfilled": len(backfilled),
        "days_with_any_data": len(days),
        "not_counted": (
            "days before the observation epoch, and days whose bars arrived long after they "
            "closed, are not forward observation days: a backfill is history, not an observation"
        ),
    }


# --------------------------------------------------------------------------- the observer
class ForwardObserver:
    """One process, one tick at a time, reading the frozen lane forward.

    The class holds no market client: ``source`` is handed to the pipeline by the caller,
    which is what lets the tests drive the real pipeline over a scripted venue.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        state_root: Path | None = None,
        store_root: Path | None = None,
        publication_dir: Path | None = None,
        pipeline: Callable[..., dict[str, Any]] | None = None,
        series: Sequence[tuple[str, str]] | None = None,
        host: str | None = None,
        lease_stale_seconds: int = LEASE_STALE_AFTER_SECONDS,
        budget_bytes: int = LANE_BUDGET_BYTES,
        warning_bytes: int = DISK_WARNING_BYTES,
        critical_bytes: int = DISK_CRITICAL_BYTES,
        publication_interval_seconds: int = PUBLICATION_INTERVAL_SECONDS,
        runs_kept: int = RUNS_KEPT,
        slots_kept: int = SLOTS_KEPT,
        ledger_kept: int = LEDGER_KEPT,
        daily_kept: int = DAILY_KEPT,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.state_root = (
            Path(state_root)
            if state_root is not None
            else self.repo_root / "data" / "forward" / "edge04"
        )
        self.store_root = (
            Path(store_root) if store_root is not None else default_store_root(self.repo_root)
        )
        self.publication_dir = (
            Path(publication_dir)
            if publication_dir is not None
            else self.state_root / "publication"
        )
        self.pipeline = pipeline or run_forward_observation
        self.series: tuple[tuple[str, str], ...] = tuple(series or FORWARD_SERIES)
        self.host = host or socket.gethostname()
        self.lease_stale_seconds = int(lease_stale_seconds)
        self.budget_bytes = int(budget_bytes)
        self.warning_bytes = int(warning_bytes)
        self.critical_bytes = int(critical_bytes)
        self.publication_interval_seconds = int(publication_interval_seconds)
        self.runs_kept = int(runs_kept)
        self.slots_kept = int(slots_kept)
        self.ledger_kept = int(ledger_kept)
        self.daily_kept = int(daily_kept)
        self._sleep = sleep
        self._clock = clock
        self.pruned: dict[str, int] = {}

    def _now_ms(self) -> int:
        """The tick's own wall clock. Injected, so a rehearsal can pin time completely."""
        return int(self._clock() * 1000)

    # -- layout ------------------------------------------------------------ #
    @property
    def runs_path(self) -> Path:
        return self.state_root / "runs.jsonl"

    @property
    def slots_path(self) -> Path:
        return self.state_root / "slots.jsonl"

    @property
    def alerts_path(self) -> Path:
        return self.state_root / "alerts.jsonl"

    @property
    def daily_dir(self) -> Path:
        return self.state_root / "daily"

    @property
    def ledger_dir(self) -> Path:
        return self.state_root / "ledger"

    @property
    def budget_path(self) -> Path:
        return self.state_root / "resource_budget.json"

    @property
    def health_path(self) -> Path:
        return self.state_root / "health.json"

    @property
    def coverage_path(self) -> Path:
        return self.state_root / "coverage.json"

    @property
    def install_path(self) -> Path:
        return self.state_root / "install.json"

    @property
    def ledger_path(self) -> Path:
        return self.ledger_dir / "INGEST_LEDGER.jsonl"

    def daily_path(self, day: str) -> Path:
        return self.daily_dir / f"{day}.json"

    def lease(self) -> CampaignLock:
        """The repository's own renewable lease, reused instead of a second lock idiom."""
        return CampaignLock(
            self.state_root / "lock",
            campaign_id="EDGE04_FORWARD_OBSERVER",
            stale_after_seconds=self.lease_stale_seconds,
            host=self.host,
        )

    # -- readings ---------------------------------------------------------- #
    def disk(self) -> dict[str, Any]:
        return disk_report(
            self.state_root, warning_bytes=self.warning_bytes, critical_bytes=self.critical_bytes
        )

    def runs(self) -> tuple[list[dict[str, Any]], int]:
        return read_jsonl(self.runs_path)

    def observed_slots(self) -> tuple[set[str], int]:
        rows, corrupt = read_jsonl(self.slots_path)
        return {str(row.get("slot_key")) for row in rows}, corrupt

    def install(self) -> dict[str, Any]:
        if not self.install_path.is_file():
            return {}
        try:
            loaded = json.loads(self.install_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"corrupt": True}
        return loaded if isinstance(loaded, dict) else {}

    def sample_trees(self) -> dict[str, Any]:
        """Bytes under each tree this lane owns. The store is evidence; the rest is state."""
        state = directory_bytes(self.state_root)
        store = directory_bytes(self.store_root)
        inside = True
        try:
            self.publication_dir.relative_to(self.state_root)
        except ValueError:
            inside = False
        publication = 0 if inside else directory_bytes(self.publication_dir)
        return {
            "store": store,
            "state": state,
            "publication": publication,
            "lane": state + publication,
            "publication_inside_state": inside,
        }

    def stored_by_series(self) -> dict[str, list[dict[str, Any]]]:
        store = ForwardStore(self.store_root)
        return {
            f"{timeframe}:{symbol}": store.read(timeframe, symbol)
            for timeframe, symbol in self.series
        }

    # -- one tick ---------------------------------------------------------- #
    def tick(
        self,
        *,
        observed_at_ms: int | None = None,
        source: Any = None,
        due_only: bool = False,
        force_publication: bool = False,
        mode: str = MODE_MANUAL,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        """Run one observation tick and return its record (also written to the run log).

        The record is the artefact: the exit code the entry point returns is derived from it,
        never the other way round.
        """
        started_ms = int(now_ms if now_ms is not None else self._now_ms())
        slot = slot_of(started_ms)
        record: dict[str, Any] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "run_id": f"FWD-EDGE04-{stamp(slot).replace('-', '').replace(':', '')}",
            "mode": mode,
            "host": self.host,
            "pid": os.getpid(),
            "python": sys.executable,
            "started_at_utc": stamp(started_ms),
            "started_at_ms": started_ms,
            "slot_key": slot_key(slot),
            "slot_start_utc": slot_key(slot),
            "slot_end_utc": slot_key(slot + SLOT_MS),
            "due_only": bool(due_only),
            "new_bars": 0,
            "market_requests": 0,
            "errors": [],
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        seen_slots, corrupt_slots = self.observed_slots()
        _runs, corrupt_runs = self.runs()
        record["slot_already_observed"] = record["slot_key"] in seen_slots
        # A tick killed mid-append leaves a torn last line in either log. Both are counted:
        # a reader must not crash on them, and must not pretend they were never written.
        record["corrupt_log_lines"] = corrupt_slots + corrupt_runs
        if due_only and record["slot_already_observed"]:
            return self._finish(
                record,
                ALREADY_OBSERVED,
                f"slot {record['slot_key']} already produced an observation",
                started_ms=started_ms,
            )

        disk = self.disk()
        record["disk"] = disk
        if disk["status"] == CRITICAL:
            return self._finish(
                record,
                DISK_BUDGET_EXCEEDED,
                (
                    f"{disk['free_gib']} GiB free is below the {self.critical_bytes} byte critical "
                    "floor: the tick refused before making a market request"
                ),
                started_ms=started_ms,
            )

        lock = self.lease()
        acquired = lock.acquire(now=started_ms // 1000)
        record["lease"] = acquired
        if not acquired.get("acquired"):
            # The reason is the lease's own arithmetic and nothing more. Whether that pid is still
            # alive is exactly what this platform cannot always be asked, so the record says what
            # was true: who holds the lease, how long ago they renewed it, and that the bound has
            # not passed.
            held = acquired.get("holder") or {}
            return self._finish(
                record,
                ALREADY_RUNNING,
                (
                    f"lease held by pid {held.get('pid')} on {held.get('host')}, renewed "
                    f"{acquired.get('lease_age_seconds')}s ago, inside the "
                    f"{held.get('stale_after_seconds')}s bound"
                ),
                started_ms=started_ms,
            )
        try:
            payload: dict[str, Any] | None = None
            attempts = 0
            while attempts < MAX_PIPELINE_ATTEMPTS:
                attempts += 1
                try:
                    payload = self._run_pipeline(source=source, observed_at_ms=observed_at_ms)
                    record["payload_error"] = None
                    break
                except AssertionError as exc:
                    # The frozen pin speaks for itself: retrying would only measure the same
                    # moved ruleset again.
                    record["payload_error"] = repr(exc)
                    record["error_class"] = "ASSERTION"
                    record["attempts"] = attempts
                    return self._finish(
                        record, VERIFICATION_FAILED, str(exc), started_ms=started_ms
                    )
                except Exception as exc:
                    record["payload_error"] = repr(exc)
                    record["error_class"] = type(exc).__name__
                    if attempts >= MAX_PIPELINE_ATTEMPTS:
                        break
                    self._sleep(RETRY_DELAY_SECONDS)
            record["attempts"] = attempts
            if payload is None:
                return self._finish(
                    record,
                    RUNTIME_EXCEPTION,
                    str(record.get("payload_error")),
                    started_ms=started_ms,
                )
            try:
                return self._with_payload(
                    record, payload, started_ms, force_publication=force_publication
                )
            except Exception as exc:  # the pipeline ran but the evidence write did not
                record["payload_error"] = repr(exc)
                record["error_class"] = type(exc).__name__
                return self._finish(
                    record,
                    RUNTIME_EXCEPTION,
                    f"writing the evidence failed: {exc!r}",
                    started_ms=started_ms,
                )
        finally:
            if record.get("lease", {}).get("acquired") and "lease_release" not in record:
                record["lease_release"] = lock.release()

    def _run_pipeline(self, *, source: Any, observed_at_ms: int | None) -> dict[str, Any]:
        return self.pipeline(
            repo_root=self.repo_root,
            source=source,
            observed_at_ms=observed_at_ms,
            ledger_dir=self.ledger_dir,
            store_root=self.store_root,
        )

    def _with_payload(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        started_ms: int,
        *,
        force_publication: bool,
    ) -> dict[str, Any]:
        stored = self.stored_by_series()
        payload["forward_expectation"] = self.expectations(payload, now_ms=started_ms)
        payload["prospective"] = self.prospective(payload, stored=stored)
        outcome, reason = self.classify(payload)
        record["market_instant_utc"] = payload.get("observed_at_utc")
        record["market_requests"] = self._market_requests(payload)
        record["new_bars"] = int(payload["health"]["new_bars"])
        record["expected_new_bars"] = int(payload["forward_expectation"]["expected"])
        record["missing_bars"] = int(payload["forward_expectation"]["missing"])
        record["stale_series"] = payload["forward_expectation"]["stale_series"]
        record["window_observation_days"] = payload["health"]["observation_days"]
        record["prospective_observation_days"] = int(
            payload["prospective"]["prospectively_observed"]
        )
        record["captured_decisions"] = payload["shadow"]["captured_decisions"]
        record["decisions_digest"] = payload["shadow"]["decisions_digest"]
        record["parity_verdict"] = payload["parity"]["verdict"]
        record["ruleset"] = {
            "params_hash": payload["frozen_params"]["params_hash"],
            "agrees_with_publication": payload["frozen_params"]["agrees_with_publication"],
        }
        record["store"] = {
            "total_bars": payload["manifest"]["total_bars"],
            "series": {
                key: {
                    "bars": body["bars"],
                    "last_ts": body["last_ts"],
                    "sha256": str(body["sha256"])[:16],
                }
                for key, body in sorted(payload["manifest"]["files"].items())
            },
        }
        record["latency"] = {
            key: {
                "fresh_bars": body["fresh_bars"],
                "fresh_median_seconds": body["fresh_median_seconds"],
                "fresh_max_seconds": body["fresh_max_seconds"],
            }
            for key, body in sorted(payload["latency"].items())
        }
        record["errors"] = list(payload["health"]["errors"])
        # Per-series expectations, published so a reader can recompute the aggregate numbers
        # instead of trusting them.
        record["expectation_series"] = list(payload["forward_expectation"]["series"])
        record["store_root"] = str(self.store_root)
        record["state_root"] = str(self.state_root)
        economics = self._economics(payload)
        record["signals"] = economics["signals"]
        record["trades"] = economics["trades"]
        record["refusals"] = economics["refusals"]
        record["hypothetical_net_usdt"] = economics["window_totals"]["primary_net_usdt"]
        signals_today, trades_today = self._rows_for_day(
            payload, day_key(int(payload["observed_at_ms"]))
        )
        record["signals_today"] = len(signals_today)
        record["trades_today"] = len(trades_today)
        record["signals_this_publication"] = len(signals_today)
        record["daily"] = self._write_daily(
            self._daily_update(payload, stored, economics, signals_today, trades_today)
        )
        write_json_atomic(self.coverage_path, payload["prospective"])
        record["publication"] = self._maybe_publish(
            payload, started_ms, force=force_publication, disk_status=str(record["disk"]["status"])
        )
        return self._finish(record, outcome, reason, started_ms=started_ms)

    # -- classification ---------------------------------------------------- #
    def classify(self, payload: dict[str, Any]) -> tuple[str, str]:
        """The outcome of a tick that ran the pipeline, from the payload alone.

        Ordered by severity, and the order *is* the declaration: a lane that fetched nothing
        and a lane that fetched everything and lost half of it are not the same result.
        """
        ledger: list[dict[str, Any]] = list(payload["ingest"]["ledger"])
        errored = [row for row in ledger if row.get("outcome") == "error"]
        if errored and len(errored) == len(ledger):
            return (
                PROVIDER_UNAVAILABLE,
                f"every series failed to fetch: {errored[0].get('reason')}",
            )
        expectation = payload["forward_expectation"]
        if int(expectation["missing"]) > 0:
            return (
                MISSING_BARS,
                (
                    f"{expectation['missing']} bar(s) that had closed are not in the store "
                    f"(expected {expectation['expected']}, appended {expectation['appended']})"
                ),
            )
        if expectation["stale_series"] and len(expectation["stale_series"]) == len(self.series):
            return (
                STALE_DATA,
                (
                    "no series holds a bar that closed within its staleness bound: "
                    f"{expectation['stale_series']}"
                ),
            )
        if int(payload["health"]["new_bars"]) > 0:
            return OBSERVED, f"{payload['health']['new_bars']} new closed bar(s) stored"
        return NO_NEW_DATA, "no bar had closed since the last stored bar of every series"

    @staticmethod
    def _market_requests(payload: dict[str, Any]) -> int:
        """How many market requests this tick spent, counted from its own record."""
        total = 1  # the venue's own server time, which stamps the run's market instant
        for row in payload["ingest"]["ledger"]:
            total += len(row.get("requests") or [])
        return total

    def expectations(self, payload: dict[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
        """Per series: the bars that had closed, the bars appended, and whether the feed is stale.

        Two different questions are answered here and they must not be confused. *Expected and
        missing* are measured against the tick's own **market instant**: a bar that closed and
        is not in the store is missing, whatever the wall clock says. *Stale* is measured
        against the tick's own **wall clock**: the newest stored bar has not moved for longer
        than its bound, which is what it looks like when the market instant itself is behind.
        """
        observed_at = int(payload["observed_at_ms"])
        wall_now = int(now_ms if now_ms is not None else self._now_ms())
        rows: list[dict[str, Any]] = []
        expected_total = appended_total = missing_total = 0
        for row in payload["ingest"]["ledger"]:
            timeframe = str(row["timeframe"])
            span = span_ms(timeframe)
            high_water = row.get("high_water_ts")
            origin = int(high_water) if high_water is not None else int(row["frozen_end_ms"])
            expected = expected_closed_bars(
                high_water_ms=origin, span_ms=span, observed_at_ms=observed_at
            )
            appended = int(row.get("appended") or 0)
            missing = max(0, expected - appended)
            rows.append(
                {
                    "series": f"{timeframe}:{row['symbol']}",
                    "outcome": row.get("outcome"),
                    "expected": expected,
                    "appended": appended,
                    "missing": missing,
                    "high_water_ts": high_water,
                }
            )
            expected_total += expected
            appended_total += appended
            missing_total += missing

        last_closed: dict[str, Any] = {}
        stale: list[str] = []
        for key, body in sorted(payload["manifest"]["files"].items()):
            timeframe = key.split(":", 1)[0]
            last_ts = body["last_ts"]
            lag_ms = None if last_ts is None else wall_now - (int(last_ts) + span_ms(timeframe))
            last_closed[key] = {
                "last_ts": last_ts,
                "closed_ago_seconds": None if lag_ms is None else round(lag_ms / 1000.0, 3),
            }
            if lag_ms is None or lag_ms > STALE_AFTER_MS[timeframe]:
                stale.append(key)
        return {
            "rule": (
                "expected = the bars on the grid that had closed after the stored high-water mark "
                "at the tick's market instant; missing = expected - appended; stale = the newest "
                "stored bar is older than its bound measured against the tick's own clock"
            ),
            "series": rows,
            "expected": expected_total,
            "appended": appended_total,
            "missing": missing_total,
            "stale_series": sorted(stale),
            "last_closed": last_closed,
        }

    # -- evidence ---------------------------------------------------------- #
    def _rows_for_day(self, payload: dict[str, Any], day: str) -> tuple[list[Any], list[Any]]:
        signals: list[Any] = []
        trades: list[Any] = []
        for body in payload["shadow"]["arm_summaries"].values():
            if body.get("status") != "observed":
                continue
            signals.extend(
                row
                for row in body.get("signals_detail", [])
                if day_key(int(row["decision_ts"])) == day
            )
            trades.extend(
                row for row in body.get("trades_detail", []) if day_key(int(row["entry_ts"])) == day
            )
        return signals, trades

    @staticmethod
    def _economics(payload: dict[str, Any]) -> dict[str, Any]:
        arms = payload["shadow"]["arm_summaries"]
        observed = {arm: body for arm, body in arms.items() if body.get("status") == "observed"}
        primary_key = str(payload["shadow"]["primary_arm"])
        primary = observed.get(primary_key, {})
        metrics = primary.get("metrics") or {}
        evaluated = primary.get("candidate_bars_evaluated")
        return {
            "arms": sorted(observed),
            "signals": sum(int(body.get("signal_count") or 0) for body in observed.values()),
            "trades": sum(
                int((body.get("metrics") or {}).get("trades") or 0) for body in observed.values()
            ),
            "refusals": sum(
                sum(int(count) for count in (body.get("refusal_mix") or {}).values())
                for body in observed.values()
            ),
            "window_totals": {
                "primary_arm": primary_key,
                "primary_available": bool(payload["shadow"]["primary_available"]),
                "primary_trades": int(metrics.get("trades") or 0),
                "primary_net_usdt": float(metrics.get("net_usdt") or 0.0),
                "primary_gross_usdt": float(metrics.get("gross_usdt") or 0.0),
                "primary_fees_usdt": float(metrics.get("fees_usdt") or 0.0),
                "primary_price_costs_usdt": float(metrics.get("price_costs_usdt") or 0.0),
                "primary_max_drawdown_pct": float(metrics.get("max_drawdown_pct") or 0.0),
                "primary_no_trade_bars": max(
                    0, int(evaluated) - int(primary.get("signal_count") or 0)
                )
                if evaluated is not None
                else None,
                "hypothetical": True,
                "order_sent": False,
            },
            "note": "hypothetical: no order was sent and no capital was at risk",
        }

    def _daily_update(
        self,
        payload: dict[str, Any],
        stored: dict[str, list[dict[str, Any]]],
        economics: dict[str, Any],
        signals_today: list[Any],
        trades_today: list[Any],
    ) -> dict[str, Any]:
        """Fold this tick into the day's durable evidence file."""
        observed_at = int(payload["observed_at_ms"])
        day = day_key(observed_at)
        existing: dict[str, Any] = {}
        path = self.daily_path(day)
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                existing = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                existing = {"corrupt_previous": True}
        outcome, _reason = self.classify(payload)
        expectation = payload["forward_expectation"]
        key = slot_key(slot_of(observed_at))
        measurement = {
            "outcome": outcome,
            "new_bars": int(payload["health"]["new_bars"]),
            "expected": int(expectation["expected"]),
            "missing": int(expectation["missing"]),
            "market_requests": self._market_requests(payload),
            "at_utc": payload["generated_at_utc"],
        }
        # The day's slot table is a function of the ledger, not a diary of whoever wrote last.
        # Every slot the ledger seals on this day is written here from the seal and from the run row
        # the seal names, so a tick that merely *re-read* a slot the ledger already sealed cannot
        # replace that interval's numbers with its own smaller ones. A slot nothing has sealed yet
        # takes this tick's reading — and that reading is what the seal will name. Rebuilding rather
        # than merging also means a day file written by an older rule is corrected by the next tick
        # instead of staying wrong forever. An entry the ledger can no longer explain — its seal has
        # been front-truncated, the day kept longer than the slot log — is left exactly as it is.
        slots: dict[str, Any] = dict(existing.get("slots") or {})
        sealed_keys: set[str] = set()
        for seal_row in self.slot_seals_for_day(day):
            sealed = str(seal_row.get("slot_key"))
            owner = self._sealing_run(sealed, seal_row.get("run_id"))
            derived: dict[str, Any] = {
                "outcome": seal_row.get("outcome"),
                "new_bars": int(seal_row.get("new_bars") or 0),
                "expected": int(owner.get("expected_new_bars") or 0),
                "missing": int(owner.get("missing_bars") or 0),
                "market_requests": int(seal_row.get("market_requests") or 0),
                "at_utc": seal_row.get("at_utc"),
            }
            previous = slots.get(sealed)
            if isinstance(previous, dict):
                for annotation in ("repeats", "last_repeat"):
                    if annotation in previous:
                        derived[annotation] = previous[annotation]
            slots[sealed] = derived
            sealed_keys.add(sealed)
        if key in sealed_keys:
            # The slot is sealed: this tick is a repeat inside it. It gets its own record, and the
            # interval keeps the numbers the ledger's seal names.
            if outcome in SLOT_CONSUMING_OUTCOMES:
                entry = slots[key]
                entry["repeats"] = int(entry.get("repeats") or 0) + 1
                entry["last_repeat"] = {
                    "outcome": outcome,
                    "new_bars": measurement["new_bars"],
                    "market_requests": measurement["market_requests"],
                    "at_utc": measurement["at_utc"],
                }
        else:
            slots[key] = measurement
        return {
            "schema_version": DAILY_SCHEMA_VERSION,
            "day": day,
            "first_tick_utc": existing.get("first_tick_utc") or payload["generated_at_utc"],
            "last_tick_utc": payload["generated_at_utc"],
            "ticks": int(existing.get("ticks", 0)) + 1,
            "slots": dict(sorted(slots.items())),
            "market_instant_utc": payload["observed_at_utc"],
            "new_bars": int(existing.get("new_bars", 0)) + int(payload["health"]["new_bars"]),
            "expected_new_bars": int(existing.get("expected_new_bars", 0))
            + int(expectation["expected"]),
            "missing_bars": int(existing.get("missing_bars", 0)) + int(expectation["missing"]),
            "per_series_appended": _merge_counts(
                existing.get("per_series_appended") or {}, payload["ingest"]["ledger"]
            ),
            "economics_hypothetical": {
                "arms": economics["arms"],
                "signals_window": economics["signals"],
                "trades_window": economics["trades"],
                "refusals_window": economics["refusals"],
                "window_totals": economics["window_totals"],
                "signals_today": len(signals_today),
                "trades_today": len(trades_today),
                "note": (
                    "the shadow re-reads the whole forward window on every tick, so the window "
                    "totals are the hypothetical reading of the window and the *_today figures "
                    "are the rows whose own timestamps fall on this date; nothing here is a "
                    "realised result"
                ),
            },
            "observation": payload["prospective"],
            "window_observation_days": payload["health"]["observation_days"],
            "latency_seconds": _fresh_latency(payload),
            "errors": list(payload["health"]["errors"]),
            "ruleset_params_hash": payload["frozen_params"]["params_hash"],
            "parity_verdict": payload["parity"]["verdict"],
            "store": {
                "total_bars": payload["manifest"]["total_bars"],
                "series_digests": {
                    key: str(body["sha256"])[:16]
                    for key, body in sorted(payload["manifest"]["files"].items())
                },
            },
            "day_hashes": period_hashes(stored).get(day, {}),
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }

    def _write_daily(self, record: dict[str, Any]) -> str:
        path = self.daily_path(str(record["day"]))
        write_json_atomic(path, record)
        return str(path)

    def prospective(
        self, payload: dict[str, Any], *, stored: dict[str, list[dict[str, Any]]] | None = None
    ) -> dict[str, Any]:
        """The forward coverage reading: days observed live, days backfilled, and the hashes."""
        rows = self.stored_by_series() if stored is None else stored
        timeframes = {f"{timeframe}:{symbol}": timeframe for timeframe, symbol in self.series}
        reading = prospective_days(
            stored_by_series=rows, timeframes=timeframes, primary_assets=ASSETS
        )
        reading["schema_version"] = COVERAGE_SCHEMA_VERSION
        reading["store_root"] = str(self.store_root)
        reading["state_root"] = str(self.state_root)
        reading["generated_at_utc"] = payload.get("generated_at_utc")
        reading["market_instant_utc"] = payload.get("observed_at_utc")
        reading["required_days"] = OBSERVATION_FLOOR_DAYS
        reading["remaining_days"] = max(
            0, OBSERVATION_FLOOR_DAYS - int(reading["prospectively_observed"])
        )
        reading["epoch_utc"] = _first_stored_utc(rows)
        reading["freeze"] = {
            "frozen_1h_end_utc": stamp(FP.FROZEN_1H_END_MS),
            "frozen_15m_end_utc": stamp(FP.FROZEN_15M_END_MS),
            "params_hash": str(payload.get("frozen_params", {}).get("params_hash") or ""),
            "reading": (
                "the frozen corpora end at these instants; every stored bar is strictly later, "
                "and no day before the epoch is a forward observation day"
            ),
        }
        reading["store_digests"] = {
            key: _digest_of_rows(series_rows)[:16] for key, series_rows in sorted(rows.items())
        }
        # The per-period hashes of the last few days only: the whole history would make this
        # artefact grow with the observation, and the daily evidence file already carries the
        # hashes of its own day.
        reading["period_hashes"] = _recent_period_hashes(rows, keep=3)
        reading["window_observation_days"] = int(payload["health"]["observation_days"])
        reading["window_vs_prospective"] = (
            "the window figure counts every stored bar after the freeze, the prospectively "
            "observed figure counts only days whose bars were stored as they closed: only the "
            "second one is an observation of the future"
        )
        reading["promotion"] = "NONE"
        reading["not_an_admission"] = (
            "reaching the floor makes a later decision possible; it does not make it, and this "
            "lane cannot promote a strategy"
        )
        return reading

    # -- health, budget, alerts -------------------------------------------- #
    def health(
        self, *, now_ms: int | None = None, pending: Sequence[dict[str, Any]] = ()
    ) -> dict[str, Any]:
        """The observer's own state, derived from its own run log and the disk.

        ``pending`` is the tick being closed, considered as if it were already in the log: the
        health artefact and the run row must describe the same moment, so the row is computed
        first and appended afterwards.
        """
        now = int(now_ms if now_ms is not None else self._now_ms())
        stored_runs, corrupt_runs = self.runs()
        _slots, corrupt_slots = self.observed_slots()
        corrupt = corrupt_runs + corrupt_slots
        runs = [*stored_runs, *pending]
        window = [
            row
            for row in runs
            if int(row.get("started_at_ms") or 0) >= now - HEALTH_WINDOW_SECONDS * 1000
        ]
        outcomes: dict[str, int] = {}
        for row in window:
            outcomes[str(row.get("outcome"))] = outcomes.get(str(row.get("outcome")), 0) + 1
        observations = [row for row in window if row.get("outcome") in SLOT_CONSUMING_OUTCOMES]
        consecutive = 0
        for row in reversed(runs):
            outcome = str(row.get("outcome"))
            if outcome in SLOT_CONSUMING_OUTCOMES:
                break
            if outcome in NEUTRAL_OUTCOMES:
                continue
            consecutive += 1
        disk = self.disk()
        budget = self.budget_reading(now_ms=now)
        reasons: list[str] = []
        if disk["status"] == CRITICAL:
            reasons.append("the volume is below the critical floor")
        if consecutive >= BLOCKED_AFTER_CONSECUTIVE_FAILURES:
            reasons.append(f"{consecutive} consecutive ticks observed nothing")
        if budget["over_budget"]:
            reasons.append("the lane tree is over its declared byte budget")
        if reasons:
            status = "BLOCKED"
        else:
            degraded: list[str] = []
            if disk["status"] == WARNING:
                degraded.append(
                    "the volume is below the warning floor: the heavy publication waits"
                )
            if consecutive:
                degraded.append(f"{consecutive} tick(s) since the last observation")
            if budget["growth"]["status"] == "VOLATILE":
                degraded.append("the measured growth rate is volatile")
            status = "DEGRADED" if degraded else "HEALTHY"
            reasons = degraded
        return {
            "schema_version": HEALTH_SCHEMA_VERSION,
            "generated_at_utc": stamp(now),
            "status": status,
            "reasons": reasons,
            "ticks_in_window": len(window),
            "expected_ticks_in_window": HEALTH_WINDOW_SECONDS // (SLOT_MINUTES * 60),
            "observations_in_window": len(observations),
            "outcomes_in_window": dict(sorted(outcomes.items())),
            "consecutive_non_observations": consecutive,
            "last_observation_utc": observations[-1].get("finished_at_utc")
            if observations
            else None,
            "last_tick_utc": runs[-1].get("finished_at_utc") if runs else None,
            "corrupt_log_lines": corrupt,
            "disk": disk,
            "budget": budget,
            "hypothetical": True,
            "order_sent": False,
        }

    def budget_reading(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Measured occupancy, measured growth, and the declared policy that follows."""
        now = int(now_ms if now_ms is not None else self._now_ms())
        trees = self.sample_trees()
        samples, dropped = self._disk_samples()
        lane_bytes = int(trees["lane"])
        growth = growth_rate(
            [
                # The shared helper's unit is seconds; this lane stamps milliseconds. Converted
                # once, here, rather than redefining the helper's unit for every other reader.
                GrowthSample(timestamp=int(s["ts_ms"]) // 1000, bytes=int(s["bytes"]))
                for s in samples
                if isinstance(s.get("bytes"), int)
            ]
        )
        growth["dropped_foreign_unit_samples"] = dropped
        if dropped:
            growth["unit_reading"] = (
                "samples written before the stamp was named are in milliseconds and would be "
                "read as seconds, which turns a per-second rate into a per-day one; they are "
                "dropped and counted instead of being mixed into this reading"
            )
        rates = growth.get("bytes_per_day")
        disk = self.disk()
        return {
            "schema_version": BUDGET_SCHEMA_VERSION,
            "generated_at_utc": stamp(now),
            "declared": {
                "lane_bytes": self.budget_bytes,
                "runs_kept": self.runs_kept,
                "slots_kept": self.slots_kept,
                "ledger_kept": self.ledger_kept,
                "daily_kept": self.daily_kept,
                "publication_interval_seconds": self.publication_interval_seconds,
            },
            "measured": {**trees, "lane_bytes": lane_bytes},
            "growth": growth,
            "forecast": {
                "days_to_warning_free": estimate_days_to_threshold(
                    free_bytes=disk["free_bytes"],
                    threshold_bytes=self.warning_bytes,
                    growth_bytes_per_day=rates,
                ),
                "days_to_critical_free": estimate_days_to_threshold(
                    free_bytes=disk["free_bytes"],
                    threshold_bytes=self.critical_bytes,
                    growth_bytes_per_day=rates,
                ),
                "lane_days_to_budget": None
                if not rates
                else round(max(0.0, (self.budget_bytes - lane_bytes) / float(rates)), 3),
                "reading": (
                    "a forecast is published only when the measured rate is stable; otherwise it "
                    "is null, because an invented number is worse than no number"
                ),
            },
            "policy": {
                "healthy": "full tick, and the heavy publication when its cadence is due",
                "warning": (
                    f"below {self.warning_bytes} free bytes: ingest continues, the heavy "
                    "publication waits"
                ),
                "critical": (
                    f"below {self.critical_bytes} free bytes: the tick records "
                    "DISK_BUDGET_EXCEEDED and makes no market request at all"
                ),
                "pruning": (
                    "only the bounded operational logs are front-truncated; the store, the daily "
                    "evidence files and every published report are never rewritten or deleted"
                ),
            },
            "over_budget": bool(lane_bytes > self.budget_bytes),
            "disk": disk,
        }

    def _disk_samples(self) -> tuple[list[dict[str, Any]], int]:
        """The samples of the current unit, and how many older ones were dropped."""
        if not self.budget_path.is_file():
            return [], 0
        try:
            loaded = json.loads(self.budget_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [], 0
        samples = loaded.get("samples") if isinstance(loaded, dict) else None
        rows = list(samples) if isinstance(samples, list) else []
        kept = [row for row in rows if isinstance(row.get("ts_ms"), int)]
        return kept, len(rows) - len(kept)

    def _write_budget_sample(self, now_ms: int) -> dict[str, Any]:
        samples, _dropped = self._disk_samples()
        samples.append({"ts_ms": now_ms, "bytes": int(self.sample_trees()["lane"])})
        reading = self.budget_reading(now_ms=now_ms)
        reading["samples"] = samples[-DISK_SAMPLES_KEPT:]
        write_json_atomic(self.budget_path, reading)
        return reading

    def _silence_seconds(self, record: dict[str, Any]) -> float | None:
        """Seconds since the previous tick that consumed a slot, or ``None`` if there is none.

        Read from the run log rather than from a counter the lane keeps in memory: a restart must
        not restart the clock on how long the lane has been silent. A tick replaying a slot at or
        behind the last one observed is a rerun, not silence, and raises nothing.
        """
        runs, _ = read_jsonl(self.runs_path)
        finished = int(
            record.get("finished_at_ms") or record.get("started_at_ms") or self._now_ms()
        )
        here = str(record.get("slot_key") or "")
        for row in reversed(runs):
            if str(row.get("outcome")) not in SLOT_CONSUMING_OUTCOMES:
                continue
            previous = row.get("finished_at_ms")
            if not isinstance(previous, int):
                continue
            if here and str(row.get("slot_key") or "") >= here:
                return None
            record["previous_consuming_run_id"] = row.get("run_id")
            return max(0.0, (finished - previous) / 1000.0)
        return None

    def alerts(self, record: dict[str, Any], health: dict[str, Any]) -> list[dict[str, Any]]:
        """Emit the events the host's health watch can read — and only on a transition."""
        now = int(record.get("started_at_ms") or self._now_ms())
        existing, _ = read_jsonl(self.alerts_path)
        last: dict[str, dict[str, Any]] = {}
        for row in existing:
            kind = str(row.get("kind"))
            last[kind] = row
            if kind in ("HEALTH_BLOCKED", "HEALTH_DEGRADED", "HEALTH_RECOVERED"):
                last["HEALTH_STATE"] = {"state": row.get("state")}
        emitted: list[dict[str, Any]] = []

        def raise_alert(kind: str, detail: dict[str, Any], *, key: str | None = None) -> None:
            # ``key`` is what the suppression is remembered under. The health family shares one
            # key: deduplicating a recovery against the last *recovery* would mean only the first
            # degradation of a lane's life is ever announced as healed.
            slot = key or kind
            previous = last.get(slot)
            if previous and previous.get("state") == detail.get("state"):
                return
            append_jsonl(
                self.alerts_path,
                {
                    "schema_version": STATE_SCHEMA_VERSION,
                    "kind": kind,
                    "at_utc": stamp(now),
                    "slot_key": record.get("slot_key"),
                    "run_id": record.get("run_id"),
                    "hypothetical": True,
                    "order_sent": False,
                    **detail,
                },
            )
            last[slot] = {**detail, "kind": kind}
            emitted.append({"kind": kind, **detail})

        transition = transition_event(
            previous_status=self._previous_disk_status(),
            status=str(health["disk"]["status"]),
            report=health["disk"],
            timestamp=now,
        )
        if transition is not None:
            raise_alert(
                str(transition["event"]),
                {
                    "state": health["disk"]["status"],
                    "severity": (
                        "INFO"
                        if transition["event"] == "DISK_RECOVERED"
                        else "WARNING"
                        if transition["event"] == "DISK_WARNING"
                        else "CRITICAL"
                    ),
                    "free_gib": health["disk"]["free_gib"],
                },
            )
        previous_health = str((last.get("HEALTH_STATE") or {}).get("state") or "")
        if health["status"] == "BLOCKED":
            raise_alert(
                "HEALTH_BLOCKED",
                {"state": "BLOCKED", "severity": "CRITICAL", "reasons": health["reasons"]},
                key="HEALTH_STATE",
            )
        elif health["status"] == "DEGRADED":
            raise_alert(
                "HEALTH_DEGRADED",
                {"state": "DEGRADED", "severity": "WARNING", "reasons": health["reasons"]},
                key="HEALTH_STATE",
            )
        elif previous_health in ("BLOCKED", "DEGRADED"):
            # Only an actual recovery is called one: a healthy tick after a healthy tick is not
            # news, and a lane that was never unhealthy has nothing to have recovered from.
            raise_alert(
                "HEALTH_RECOVERED", {"state": "HEALTHY", "severity": "INFO"}, key="HEALTH_STATE"
            )
        last["HEALTH_STATE"] = {"state": str(health["status"])}

        gap = self._silence_seconds(record)
        if gap is None:
            last.pop("OBSERVATION_GAP", None)
            last.pop("OBSERVATION_STALLED", None)
        elif gap >= GAP_CRITICAL_SECONDS:
            raise_alert(
                "OBSERVATION_STALLED",
                {
                    "state": "OPEN",
                    "severity": "CRITICAL",
                    "silence_minutes": round(gap / 60.0, 1),
                    "since_run_id": record.get("previous_consuming_run_id"),
                },
            )
        elif gap >= GAP_WARNING_SECONDS:
            raise_alert(
                "OBSERVATION_GAP",
                {
                    "state": "OPEN",
                    "severity": "WARNING",
                    "silence_minutes": round(gap / 60.0, 1),
                    "since_run_id": record.get("previous_consuming_run_id"),
                },
            )
        else:
            last.pop("OBSERVATION_GAP", None)
            last.pop("OBSERVATION_STALLED", None)
        outcome = record.get("outcome")
        if outcome == PROVIDER_UNAVAILABLE:
            raise_alert(
                "PROVIDER_UNAVAILABLE",
                {
                    "state": "PROVIDER_UNAVAILABLE",
                    "severity": "WARNING",
                    "reason": record.get("outcome_reason"),
                },
            )
        if outcome == STALE_DATA:
            raise_alert(
                "STALE_DATA",
                {
                    "state": "STALE_DATA",
                    "severity": "WARNING",
                    "reason": record.get("outcome_reason"),
                },
            )
        if outcome == MISSING_BARS:
            raise_alert(
                "MISSING_BARS",
                {
                    "state": "MISSING_BARS",
                    "severity": "WARNING",
                    "reason": record.get("outcome_reason"),
                },
            )
        if outcome == VERIFICATION_FAILED:
            raise_alert(
                "VERIFICATION_FAILED",
                {
                    "state": "VERIFICATION_FAILED",
                    "severity": "CRITICAL",
                    "reason": record.get("outcome_reason"),
                },
            )
        publication = record.get("publication") or {}
        if publication.get("paused"):
            raise_alert(
                "PUBLICATION_PAUSED",
                {"state": "PAUSED", "severity": "WARNING", "reason": publication.get("reason")},
            )
        if health["budget"]["over_budget"]:
            raise_alert(
                "BUDGET_EXCEEDED",
                {
                    "state": "OVER",
                    "severity": "CRITICAL",
                    "measured": health["budget"]["measured"],
                },
            )
        if int(record.get("signals_this_publication") or 0):
            raise_alert(
                "SIGNALS_DETECTED",
                {
                    "state": "EMITTED",
                    "severity": "INFO",
                    "signals": int(record["signals_this_publication"]),
                },
            )
        if emitted:
            prune_jsonl(self.alerts_path, ALERTS_KEPT)
        return emitted

    def _previous_disk_status(self) -> str | None:
        """The status the last *recorded* tick saw, so a transition is a transition."""
        runs, _ = self.runs()
        for row in reversed(runs):
            disk = row.get("disk")
            if isinstance(disk, dict) and disk.get("status"):
                return str(disk["status"])
        return None

    # -- publication ------------------------------------------------------- #
    def _maybe_publish(
        self,
        payload: dict[str, Any],
        started_ms: int,
        *,
        force: bool,
        disk_status: str,
    ) -> dict[str, Any]:
        """Write the heavy WP-EDGE-03 artefact set when the declared cadence says so."""
        pointer = self.publication_dir / "LATEST.json"
        last_published_ms: int | None = None
        if pointer.is_file():
            try:
                loaded = json.loads(pointer.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("published_at_ms") is not None:
                    last_published_ms = int(loaded["published_at_ms"])
            except (json.JSONDecodeError, TypeError, ValueError):
                last_published_ms = None
        due = (
            force
            or last_published_ms is None
            or started_ms - last_published_ms >= self.publication_interval_seconds * 1000
        )
        if not due:
            return {
                "ran": False,
                "reason": "the publication cadence has not elapsed",
                "last_published_ms": last_published_ms,
                "next_due_ms": (last_published_ms or started_ms)
                + self.publication_interval_seconds * 1000,
            }
        if disk_status == CRITICAL:
            return {
                "ran": False,
                "paused": True,
                "reason": "the volume is below the critical floor",
            }
        if disk_status == WARNING and not force:
            return {
                "ran": False,
                "paused": True,
                "reason": "the volume is below the warning floor: the heavy publication waits",
            }
        try:
            written = self.publish(payload)
        except Exception:
            # Whatever a writer leaves behind, the publication must never hold a half-written
            # tree: the pointer is only ever replaced by a complete set of artefacts.
            for leftover in self.publication_dir.glob(".staging-*"):
                shutil.rmtree(leftover, ignore_errors=True)
            raise
        # The pointer is written by the caller of the swap, not by the writer: whatever
        # publishes (the real artefact set, or a stand-in in a rehearsal) leaves the same
        # record, and a publication whose files were written but whose pointer was not is a
        # publication the next tick would repeat.
        pointer = self.publication_dir / "LATEST.json"
        write_json_atomic(
            pointer,
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "published_at_ms": int(payload["observed_at_ms"]),
                "published_at_utc": payload["observed_at_utc"],
                "recorded_at_ms": started_ms,
                "run_id": payload["run_id"],
                "params_hash": payload["frozen_params"]["params_hash"],
                "artifacts": {
                    name: {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}
                    for name, path in sorted(written.items())
                    if path.is_file()
                },
                "hypothetical": True,
                "order_sent": False,
            },
        )
        return {
            "ran": True,
            "at_ms": started_ms,
            "at_utc": stamp(started_ms),
            "artifacts": len(written),
            "bytes": sum(path.stat().st_size for path in written.values() if path.is_file()),
            "digests": {
                name: _sha256_file(path)[:16]
                for name, path in sorted(written.items())
                if path.is_file()
            },
            "pointer": str(pointer),
            "staged_then_swapped": True,
        }

    def publish(self, payload: dict[str, Any]) -> dict[str, Path]:
        """Write the pipeline's own artefact set into a staging tree, then swap it in.

        A tick killed while writing must not leave a half-written report behind, so the heavy
        files are written elsewhere and moved into place one by one (same volume, so each move
        is atomic).
        """
        from .parity import write_parity_artifacts
        from .run import write_forward_artifacts

        self.publication_dir.mkdir(parents=True, exist_ok=True)
        staging = self.publication_dir / f".staging-{self._now_ms()}"
        if staging.exists():
            shutil.rmtree(staging)
        swapped: dict[str, Path] = {}
        try:
            written = write_forward_artifacts(payload, staging)
            written.update(write_parity_artifacts(payload["parity"], staging / "risk-parity"))
            for name, path in written.items():
                relative = Path(path).relative_to(staging)
                target = self.publication_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
                swapped[name] = target
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return swapped

    def snapshot(self, outdir: Path) -> dict[str, Path]:
        """Copy the live state root into a versioned directory, digests and all.

        The copy is *whole*. Every file under the state root, at its live name, so the independent
        verifier can be pointed at the snapshot with the same command it would use on the live tree
        — and, above all, so the byte budget is checked against the same set of files the reading
        describes. A curated list of what to copy looks harmless and is not: it silently makes the
        snapshot a smaller tree than the one measured, and from the inside that bias is
        indistinguishable from a reading that is too large.

        Dot-entries are left out on purpose: a half-written temp file is evidence of nothing, and
        the staging tree of an interrupted publication is not a lane artefact.
        """
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        copied: dict[str, Path] = {}
        if self.state_root.is_dir():
            for source in sorted(self.state_root.rglob("*")):
                relative = source.relative_to(self.state_root)
                if not source.is_file() or any(part.startswith(".") for part in relative.parts):
                    continue
                target = outdir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied[relative.as_posix()] = target
        inside_state = self.publication_dir.is_relative_to(self.state_root)
        if not inside_state and self.publication_dir.is_dir():
            publication_out = outdir / "publication"
            for source in sorted(self.publication_dir.rglob("*")):
                if not source.is_file() or source.name.startswith("."):
                    continue
                relative = source.relative_to(self.publication_dir)
                target = publication_out / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied[f"publication/{relative.as_posix()}"] = target
        write_json_atomic(
            outdir / "SNAPSHOT.json",
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "generated_at_utc": stamp(self._now_ms()),
                "files": {
                    name: {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}
                    for name, path in sorted(copied.items())
                },
                "reading": (
                    "a dated snapshot of the whole live state root: the run log and the daily "
                    "evidence are the durable record, the digests here pin the bytes that were "
                    "live when the snapshot was taken, and the copy is whole so the byte budget "
                    "can be checked against the same tree the reading describes"
                ),
                "hypothetical": True,
                "order_sent": False,
            },
        )
        return copied

    # -- closing a tick ---------------------------------------------------- #
    def _finish(
        self, record: dict[str, Any], outcome: str, reason: str, *, started_ms: int
    ) -> dict[str, Any]:
        """Close the tick: fill every field, then append it once.

        The order matters and is the reason this is one method: the row that reaches the run
        log must be the row the caller returns, health must be computed *including* this tick,
        and the bounded logs must be truncated before the append so the file ends at its
        declared cap instead of one row over it.
        """
        if record.get("lease", {}).get("acquired") and "lease_release" not in record:
            record["lease_release"] = self.lease().release()
        finished = self._now_ms()
        record["finished_at_utc"] = stamp(finished)
        record["finished_at_ms"] = finished
        record["duration_seconds"] = round((finished - started_ms) / 1000.0, 3)
        record["outcome"] = outcome
        record["outcome_reason"] = reason
        record["exit_code"] = EXIT_CODES[outcome]
        record["published_at_utc"] = record["finished_at_utc"]
        if not record.get("errors") and outcome in FAILED_OUTCOMES:
            record["errors"] = [
                {"stage": "tick", "outcome": outcome, "reason": reason, "series": None}
            ]
        record["disk_after"] = self.disk()

        consuming = outcome in SLOT_CONSUMING_OUTCOMES
        # A slot is sealed once, by the tick that drained it. A repeat trigger inside a slot the
        # ledger already holds — an operator re-running the entry point, a probe, a retry that
        # outlived its slot — records its own run row and leaves the seal alone. Two rows for one
        # slot would make the ledger claim the same interval was observed twice, and put two
        # different run rows behind a single seal. The file is read here rather than trusting the
        # flag taken at the start: the seal that matters is the one on disk at the moment of it.
        sealing = False
        if consuming:
            sealed, _corrupt_slots = self.observed_slots()
            sealing = record["slot_key"] not in sealed
            record["slot_sealed"] = sealing
            if not sealing:
                record["slot_seal_held_by"] = self._slot_seal(record["slot_key"])
        self.pruned["runs"] = prune_jsonl(self.runs_path, max(0, self.runs_kept - 1))
        if sealing:
            self.pruned["slots"] = prune_jsonl(self.slots_path, max(0, self.slots_kept - 1))
        self.pruned["ledger"] = prune_jsonl(self.ledger_path, self.ledger_kept)
        dropped_daily = self._prune_daily()
        if dropped_daily:
            self.pruned["daily"] = dropped_daily
        record["pruned_rows"] = {key: value for key, value in self.pruned.items() if value}

        health = self.health(now_ms=finished, pending=[record])
        record["health_status"] = health["status"]
        record["alerts"] = self.alerts(record, health)

        append_jsonl(self.runs_path, record)
        if sealing:
            append_jsonl(
                self.slots_path,
                {
                    "schema_version": STATE_SCHEMA_VERSION,
                    "slot_key": record["slot_key"],
                    "run_id": record["run_id"],
                    "outcome": outcome,
                    "new_bars": record.get("new_bars", 0),
                    "market_requests": record.get("market_requests", 0),
                    "observed_at_utc": record.get("market_instant_utc"),
                    "at_utc": record["finished_at_utc"],
                },
            )
        self._write_budget_sample(started_ms)
        # Health is read *after* this tick's run row, its slot row and its budget sample are on
        # disk — not before them. A reading taken earlier reports a lane smaller than the tree
        # that holds it, by exactly the bytes of the row describing the tick that took it, and a
        # byte budget that cannot account for its own record is not a budget.
        health["budget"] = self.budget_reading(now_ms=finished)
        health["last_tick"] = {
            "run_id": record["run_id"],
            "outcome": outcome,
            "duration_seconds": record["duration_seconds"],
        }
        write_json_atomic(self.health_path, health)
        return record

    def _slot_seal(self, key: str) -> dict[str, Any] | None:
        """The seal the ledger already holds for a slot: who consumed it, and when."""
        rows, _corrupt = read_jsonl(self.slots_path)
        for row in rows:
            if str(row.get("slot_key")) == key:
                return {
                    "run_id": row.get("run_id"),
                    "outcome": row.get("outcome"),
                    "at_utc": row.get("at_utc"),
                }
        return None

    def slot_seals_for_day(self, day: str) -> list[dict[str, Any]]:
        """The ledger's seals whose slot falls on ``day``, in the order the ledger holds them."""
        rows, _corrupt = read_jsonl(self.slots_path)
        seals: list[dict[str, Any]] = []
        for row in rows:
            text = str(row.get("slot_key") or "")
            try:
                when = parse_slot_key(text)
            except ValueError:
                continue
            if day_key(when) == day:
                seals.append(row)
        return seals

    def _sealing_run(self, key: str, run_id: Any) -> dict[str, Any]:
        """The consuming run row the seal names, when the run log still holds it."""
        rows, _corrupt = read_jsonl(self.runs_path)
        for row in rows:
            if (
                str(row.get("run_id")) == str(run_id)
                and str(row.get("slot_key")) == key
                and str(row.get("outcome")) in SLOT_CONSUMING_OUTCOMES
            ):
                return row
        return {}

    def dedupe_slots(self) -> dict[str, Any]:
        """Keep the first seal of each slot and drop the rest, reporting exactly what went.

        A maintenance operation, not a tick. It rewrites one bounded operational log — and only
        that log — so a reader of ``slots.jsonl`` can treat it as the set it is meant to be. The
        first row of a slot is the seal; a later row for the same slot is what a duplicate is.

        Returns a receipt (digests of both sides, and every dropped row) that is also written
        next to the state root, because a repair nobody can audit is just a rewrite.
        """
        before = self.slots_path.read_bytes() if self.slots_path.is_file() else b""
        rows, corrupt = read_jsonl(self.slots_path)
        kept: list[dict[str, Any]] = []
        seen: set[str] = set()
        dropped: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("slot_key"))
            if key in seen:
                dropped.append(
                    {
                        "slot_key": key,
                        "run_id": row.get("run_id"),
                        "outcome": row.get("outcome"),
                        "at_utc": row.get("at_utc"),
                    }
                )
                continue
            seen.add(key)
            kept.append(row)
        receipt: dict[str, Any] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "at_utc": stamp(self._now_ms()),
            "slots_path": str(self.slots_path),
            "rows_before": len(rows),
            "rows_after": len(kept),
            "dropped": dropped,
            "corrupt_lines": corrupt,
            "sha256_before": hashlib.sha256(before).hexdigest() if before else None,
            "sha256_after": None,
            "reading": (
                "the seal of a slot is its first row; the seal of the consumed slot is never "
                "dropped, only a repeat row for a slot that already had one"
            ),
        }
        if dropped:
            payload = "".join(
                json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n"
                for row in kept
            )
            self.slots_path.write_text(payload, encoding="utf-8")
            receipt["sha256_after"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        else:
            receipt["sha256_after"] = receipt["sha256_before"]
        write_json_atomic(self.state_root / "slot_ledger_repair.json", receipt)
        return receipt

    def _prune_daily(self) -> int:
        if not self.daily_dir.is_dir():
            return 0
        files = sorted(self.daily_dir.glob("*.json"))
        if len(files) <= self.daily_kept:
            return 0
        dropped = 0
        for path in files[: len(files) - self.daily_kept]:
            path.unlink()
            dropped += 1
        return dropped


def _merge_counts(existing: dict[str, Any], ledger: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {str(key): int(value) for key, value in existing.items()}
    for row in ledger:
        key = f"{row['timeframe']}:{row['symbol']}"
        counts[key] = counts.get(key, 0) + int(row.get("appended") or 0)
    return dict(sorted(counts.items()))


def _fresh_latency(payload: dict[str, Any]) -> dict[str, Any]:
    medians = sorted(
        float(body["fresh_median_seconds"])
        for body in payload["latency"].values()
        if body.get("fresh_median_seconds") is not None
    )
    maxima = [
        float(body["fresh_max_seconds"])
        for body in payload["latency"].values()
        if body.get("fresh_max_seconds") is not None
    ]
    return {
        "series": {
            key: {
                "fresh_bars": body["fresh_bars"],
                "median_seconds": body["fresh_median_seconds"],
                "max_seconds": body["fresh_max_seconds"],
            }
            for key, body in sorted(payload["latency"].items())
        },
        "median_of_medians_seconds": round(medians[len(medians) // 2], 3) if medians else None,
        "max_seconds": round(max(maxima), 3) if maxima else None,
        "rule": (
            "close → store, of the bars THIS tick pulled; the window reading is in the publication"
        ),
    }


def _recent_period_hashes(
    stored: dict[str, list[dict[str, Any]]], *, keep: int
) -> dict[str, dict[str, str]]:
    """Per-day store hashes, newest ``keep`` days only, so the artefact stays bounded."""
    hashes = period_hashes(stored)
    days = sorted(hashes)[-keep:]
    return {day: hashes[day] for day in days}


def _first_stored_utc(stored: dict[str, list[dict[str, Any]]]) -> str | None:
    stamps = [int(row["ts"]) for rows in stored.values() for row in rows]
    return stamp(min(stamps)) if stamps else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
