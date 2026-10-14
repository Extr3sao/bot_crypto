"""WP-EDGE-05 — the independent watchdog's own regressions.

The watchdog exists because the lane cannot report its own silence. So the tests that matter are
the ones about *detection and restraint*:

* a scheduler that is missing, disabled or reporting a failure is a finding, and the scheduler's
  own last-result field is translated through the lane's declared vocabulary;
* a lane that has gone quiet is told from a market that has nothing new, in both directions:
  bars pending the next trigger are not a failure, bars that closed before the last tick and are
  not stored are;
* a tick that started and never finished is a dead process, not a slow one;
* a torn line, a duplicate seal, an attempt with no run row and a broken restart proof are each
  named, and none of them is rounded to "fine";
* a volume below the floor and a growth rate above the threshold raise the alert and delete
  nothing;
* alerts are per *transition*: a recovery is announced only after a real trouble, and a healthy
  check after a healthy check is not news;
* the watchdog writes nothing inside the lane's state root, makes no market request and holds no
  lease;
* its own bounded log is bounded, and a snapshot it has already taken is refused as redundant.

``Lane`` below builds a synthetic lane that is shaped exactly like the live one: a store per
series, a two-pass ingest ledger, a run log and a slot ledger, advanced one tick at a time — so a
test can interrupt it at any single point of persistence and see what the watchdog says.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge05 import watchdog as WD  # noqa: E402

QUARTER = 900_000
HOUR = 3_600_000
T0 = 1_792_000_000_000 - (1_792_000_000_000 % QUARTER)
SERIES = (
    ("1h", "BTC"),
    ("1h", "ETH"),
    ("1h", "SOL"),
    ("15m", "BTC"),
    ("15m", "ETH"),
    ("15m", "SOL"),
)


def span_of(timeframe: str) -> int:
    return HOUR if timeframe == "1h" else QUARTER


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def stamp_ms(instant_ms: int) -> str:
    return WD.stamp(int(instant_ms))


class Lane:
    """A synthetic forward lane, advanced one tick at a time.

    ``tick`` writes the four things a real tick writes — bars, ledger rows, a run row and a slot
    seal — and every one of them can be suppressed, which is how an interruption at one point of
    persistence is rehearsed without a real process being killed.
    """

    def __init__(self, root: Path, *, series: tuple[tuple[str, str], ...] = SERIES) -> None:
        self.root = Path(root)
        self.store = self.root / "store"
        self.state = self.root / "lane"
        self.series = series
        # The store's high-water mark is always ON the bar grid: a stored bar is grid-aligned, so
        # an initial mark that was not would make the first appended bar off-grid too.
        self.hwm = {
            f"{tf}:{sym}": ((((T0 - span_of(tf)) // span_of(tf)) * span_of(tf)))
            for tf, sym in series
        }
        self.stored_per_series = {f"{tf}:{sym}": 0 for tf, sym in series}
        self.stored_bars = 0
        self.runs: list[dict[str, Any]] = []
        self.decisions_digest = "d" * 64
        self.captured = 7
        self.tick_index = 0

    # -- files ------------------------------------------------------------ #
    @property
    def runs_path(self) -> Path:
        return self.state / "runs.jsonl"

    @property
    def slots_path(self) -> Path:
        return self.state / "slots.jsonl"

    @property
    def ledger_path(self) -> Path:
        return self.state / "ledger" / "INGEST_LEDGER.jsonl"

    def bar(self, timeframe: str, symbol: str, ts: int, fetched_at_ms: int) -> None:
        path = self.store / timeframe / f"{symbol}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": ts,
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 10.0,
                        "interval": timeframe,
                        "source": "SCRIPTED",
                        "fetched_at_ms": fetched_at_ms,
                        "payload_sha256": "0" * 64,
                        "closed": True,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        self.stored_bars += 1
        self.stored_per_series[f"{timeframe}:{symbol}"] = (
            self.stored_per_series.get(f"{timeframe}:{symbol}", 0) + 1
        )

    # -- one tick --------------------------------------------------------- #
    def tick(
        self,
        instant_ms: int,
        *,
        # A tick ingests *every* bar that closed after its high-water mark, not one per tick: a
        # tick after a gap therefore recovers the whole gap, which is the lane's declared
        # recovery property and the thing a watchdog must not read as a failure.
        append: int = 8,
        store: bool = True,
        ledger: bool = True,
        run: bool = True,
        seal: bool = True,
        outcome: str = "OBSERVED",
        inflight: bool = False,
        pid: int = 4242,
        slot_sealed: bool = True,
        append_on_second_pass: int = 0,
    ) -> dict[str, Any]:
        self.tick_index += 1
        run_id = f"FWD-EDGE04-{stamp_ms(instant_ms).replace('-', '').replace(':', '')}"
        new_bars = 0
        for timeframe, symbol in self.series:
            key = f"{timeframe}:{symbol}"
            span = span_of(timeframe)
            high_water = self.hwm[key]
            # Only a *closed* bar can be ingested: the newest one that can have closed at this
            # tick's market instant. A tick at :22 therefore appends one 15m bar and no 1h bar,
            # and a tick at :07 appends both — the ratio the live lane shows, reproduced here.
            newest_closed = ((int(instant_ms) // span) * span) - span
            bars: list[int] = []
            candidate = high_water
            while candidate + span <= newest_closed and len(bars) < max(0, append):
                candidate += span
                bars.append(candidate)
            appended = len(bars)
            stored_before = self.stored_per_series[key]
            if store:
                for ts in bars:
                    self.bar(timeframe, symbol, ts, instant_ms)
            if ledger:
                _append_jsonl(
                    self.ledger_path,
                    {
                        "run_at_ms": instant_ms,
                        "timeframe": timeframe,
                        "symbol": symbol,
                        "frozen_end_ms": T0 - HOUR,
                        "high_water_ts": high_water,
                        "next_expected_ts": high_water + span,
                        "stored_before": stored_before,
                        "outcome": "ingested" if appended else "no_new_data",
                        "appended": appended,
                        "requests": ["/api/v3/klines"],
                        "audit": {"last_ts": high_water + appended * span},
                    },
                )
            self.hwm[key] = high_water + appended * span
            new_bars += appended
            if ledger and append_on_second_pass:
                _append_jsonl(
                    self.ledger_path,
                    {
                        "run_at_ms": instant_ms,
                        "timeframe": timeframe,
                        "symbol": symbol,
                        "high_water_ts": self.hwm[key],
                        "outcome": "ingested",
                        "appended": append_on_second_pass,
                        "audit": {"last_ts": self.hwm[key] + append_on_second_pass * span},
                    },
                )
                self.hwm[key] += append_on_second_pass * span
                new_bars += append_on_second_pass
            elif ledger:
                _append_jsonl(
                    self.ledger_path,
                    {
                        "run_at_ms": instant_ms,
                        "timeframe": timeframe,
                        "symbol": symbol,
                        "high_water_ts": self.hwm[key],
                        "outcome": "no_new_data",
                        "appended": 0,
                        "audit": {"last_ts": self.hwm[key]},
                    },
                )
        record: dict[str, Any] = {
            "schema_version": "EDGE04_TICK_V1",
            "run_id": run_id,
            "outcome": outcome,
            "slot_key": WD.slot_key(int(instant_ms)),
            "market_instant_utc": stamp_ms(instant_ms),
            "new_bars": new_bars,
            "market_requests": 4 if outcome == "OBSERVED" else 1,
            "started_at_ms": instant_ms - 30_000,
            "finished_at_ms": None if inflight else instant_ms + 5_000,
            "started_at_utc": stamp_ms(instant_ms - 30_000),
            "finished_at_utc": None if inflight else stamp_ms(instant_ms + 5_000),
            "pid": pid,
            "slot_sealed": slot_sealed,
            "captured_decisions": self.captured,
            "decisions_digest": self.decisions_digest,
            "store": {"total_bars": self.stored_bars},
            "hypothetical": True,
            "order_sent": False,
        }
        if run:
            _append_jsonl(self.runs_path, record)
        if seal and outcome in ("OBSERVED", "NO_NEW_DATA"):
            _append_jsonl(
                self.slots_path,
                {
                    "slot_key": record["slot_key"],
                    "run_id": run_id,
                    "outcome": outcome,
                    "new_bars": new_bars,
                    "market_requests": record["market_requests"],
                    "observed_at_utc": record["market_instant_utc"],
                    "at_utc": record["finished_at_utc"] or stamp_ms(instant_ms),
                },
            )
        self.runs.append(record)
        self.write_budget(instant_ms)
        return record

    def write_budget(self, instant_ms: int, *, lane_bytes: int = 3_000_000) -> None:
        """The lane's own resource artefact, which the watchdog reads rather than measuring."""
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "resource_budget.json").write_text(
            json.dumps(
                {
                    "schema_version": "EDGE04_RESOURCE_BUDGET_V1",
                    "generated_at_utc": stamp_ms(instant_ms),
                    "measured": {"lane_bytes": lane_bytes, "store": 5_000_000},
                    "growth": {
                        "status": "VOLATILE",
                        "bytes_per_day": None,
                        "mean_bytes_per_day": 1_761_656.9,
                        "coefficient_of_variation": 0.6,
                        "samples": 29,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def healthy_lane(tmp_path: Path, *, ticks: int = 6, **tick_kwargs: Any) -> Lane:
    lane = Lane(tmp_path)
    for index in range(ticks):
        lane.tick(T0 + index * QUARTER, **tick_kwargs)
    return lane


def scheduler(**overrides: Any) -> dict[str, Any]:
    reading = {
        "available": True,
        "scheduler_type": "windows_task_scheduler",
        "task_name": WD.TASK_NAME,
        "installed": True,
        "enabled": True,
        "state": "Ready",
        "multiple_instances": "IgnoreNew",
        "start_when_available": "True",
        "last_run_time": "10/13/2026 20:40:54",
        "last_task_result": 0,
        "next_run_time": "10/13/2026 20:55:53",
        "missed_runs": 0,
    }
    reading.update(overrides)
    return reading


def instants(
    *,
    now_ms: int = T0 + 5 * QUARTER,
    next_run_ms: int | None = None,
    missed: int = 0,
    result: int | None = 0,
) -> dict[str, Any]:
    """The scheduler's own reporting, with its instants read off the watchdog's own clock.

    How far behind the reading its own probe answered is a *finding* the watchdog raises, so a
    fixture that got it wrong would turn every test into a probe-lag test. Here both sides read
    the same pinned clock, which puts the lag at zero.
    """
    return {
        "available": True,
        "task_name": WD.TASK_NAME,
        "state": "Ready",
        "next_run_utc": stamp_ms(next_run_ms if next_run_ms is not None else now_ms + 900_000),
        "last_run_utc": stamp_ms(now_ms - 900_000),
        "last_task_result": result,
        "missed_runs": missed,
        "queried_at_utc": stamp_ms(now_ms),
        "local_offset_minutes": 0,
        "local_utc_offset_minutes": 0,
    }


def watchdog(
    tmp_path: Path,
    lane: Lane | None = None,
    *,
    now_ms: int | None = None,
    clock: Any = None,
    scheduler_probe: Any = None,
    instant_probe: Any = None,
    **kwargs: Any,
) -> WD.ForwardWatchdog:
    lane = lane or Lane(tmp_path)
    clock_fn = clock or (lambda: (now_ms or T0 + 5 * QUARTER) / 1000.0)
    kwargs.setdefault("process_probe", lambda: {"available": True, "processes": []})
    # The volume is pinned HEALTHY by default, for the same reason as the lane's own tests: the
    # host's momentary free space must not be able to flip a verdict. The resource tests below pass
    # their own probe to state a specific volume.
    kwargs.setdefault("disk_probe", lambda path: disk_reading(WD.HEALTHY, 50 * 1024**3))
    seen = WD.ForwardWatchdog(
        repo_root=tmp_path,
        lane_state_root=lane.state,
        store_root=lane.store,
        state_root=tmp_path / "watch",
        series=lane.series,
        scheduler_probe=scheduler_probe or (lambda: scheduler()),
        scheduler_instant_probe=instant_probe
        or (lambda: instants(now_ms=int(clock_fn() * 1000))),
        clock=clock_fn,
        **kwargs,
    )
    return seen


# --------------------------------------------------------------------------- a healthy lane
def test_a_healthy_lane_reads_ok(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(tmp_path, lane).check(persist=False)
    assert row["verdict"] == WD.WATCH_OK
    assert row["operational_failure"] is False
    assert row["market_quiet"] is True
    assert row["market_requests"] == 0
    assert row["order_sent"] is False
    assert row["promotion"] == "NONE"
    assert row["findings"] == []


def test_a_lane_that_has_stopped_reading_is_a_failure_and_a_quiet_market_is_not(tmp_path):
    lane = healthy_lane(tmp_path)
    # (b) the market is quiet: the store already holds the newest bar that has closed
    quiet = watchdog(tmp_path, lane).check(persist=False)
    assert quiet["market_quiet"] is True
    assert quiet["checks"]["market_expectation"]["pending_since_last_tick"] == 0
    # (c) bars closed since the last tick: pending the next trigger, still not a failure
    pending = watchdog(tmp_path, lane, now_ms=T0 + 7 * QUARTER).check(persist=False)
    assert pending["market_quiet"] is False
    assert pending["verdict"] == WD.WATCH_OK
    assert pending["checks"]["market_expectation"]["missing_at_last_tick"] == 0
    # (a) the lane went quiet for longer than the alarm threshold: seven slots of silence
    silent = watchdog(tmp_path, lane, now_ms=T0 + 5 * QUARTER + 7 * 900_000).check(persist=False)
    assert silent["checks"]["lane_cadence"]["status"] == WD.STATUS_ALARM
    assert silent["verdict"] == WD.WATCH_ALARM
    assert silent["operational_failure"] is True
    assert "TICK_OVERDUE" in {alert["kind"] for alert in silent["alerts"]}
    # and long enough that "late" is no longer the right word
    stalled = watchdog(
        tmp_path, lane, now_ms=T0 + 5 * QUARTER + 13 * 900_000
    ).check(persist=False)
    assert stalled["verdict"] == WD.WATCH_BLOCKED
    assert stalled["category"] in (WD.CATEGORY_LANE_OVERDUE, WD.CATEGORY_INGEST_FAILURE)


def test_bars_that_had_closed_before_the_last_tick_and_are_not_stored_are_a_failure(tmp_path):
    lane = healthy_lane(tmp_path, ticks=4)
    # The tick ran, its ledger says it ingested, and the bars never reached the store: exactly
    # what a process killed between the fetch and the write looks like from the outside.
    lane.tick(T0 + 4 * QUARTER, store=False)
    row = watchdog(tmp_path, lane, now_ms=T0 + 4 * QUARTER + 5_000).check(persist=False)
    assert row["verdict"] == WD.WATCH_ALARM
    assert row["operational_failure"] is True
    expectation = row["checks"]["market_expectation"]
    assert expectation["missing_at_last_tick"] >= 1
    assert any(
        body["series"] == "15m:BTC" and body["missing_at_last_tick"] == 1
        for body in expectation["series"]
    )
    assert any("INGEST_STALLED" == alert["kind"] for alert in row["alerts"])


def test_the_market_being_quiet_is_named_as_a_category_and_not_as_a_failure(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(tmp_path, lane).check(persist=False)
    assert row["category"] == WD.CATEGORY_MARKET_QUIET
    assert row["checks"]["market_expectation"]["pending_since_last_tick"] == 0
    assert any(alert["kind"] == "MARKET_QUIET" for alert in row["alerts"])
    pending = watchdog(tmp_path, lane, now_ms=T0 + 7 * QUARTER).check(persist=False)
    assert pending["market_quiet"] is False
    assert pending["checks"]["market_expectation"]["pending_since_last_tick"] >= 1
    assert pending["checks"]["market_expectation"]["missing_at_last_tick"] == 0


# --------------------------------------------------------------------------- the scheduler
def test_a_missing_task_is_a_blocked_watchdog_and_names_what_is_missing(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path,
        lane,
        scheduler_probe=lambda: scheduler(installed=False, enabled=False, state=None),
    ).check(persist=False)
    assert row["verdict"] == WD.WATCH_BLOCKED
    assert row["category"] == WD.CATEGORY_SCHEDULER_FAILURE
    assert row["operational_failure"] is True
    assert "SCHEDULER_MISSING" in {alert["kind"] for alert in row["alerts"]}


def test_a_disabled_task_is_an_alarm_not_an_unknown(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path, lane, scheduler_probe=lambda: scheduler(enabled=False, state="Disabled")
    ).check(persist=False)
    assert row["verdict"] == WD.WATCH_ALARM
    assert row["checks"]["scheduler_task"]["status"] == WD.STATUS_ALARM
    assert "SCHEDULER_DISABLED" in {alert["kind"] for alert in row["alerts"]}


def test_the_schedulers_own_last_result_is_translated_through_the_lanes_vocabulary(tmp_path):
    lane = healthy_lane(tmp_path)
    # 5 is the lane's DISK_BUDGET_EXCEEDED: the tick refused before a market request.
    row = watchdog(tmp_path, lane, scheduler_probe=lambda: scheduler(last_task_result=5)).check(
        persist=False
    )
    assert row["checks"]["scheduler_last_result"]["lane_outcome"] == WD.DISK_BUDGET_EXCEEDED
    assert row["verdict"] == WD.WATCH_ALARM
    # A code nobody declared is not guessed: it is an alarm that says so.
    unknown = watchdog(tmp_path, lane, scheduler_probe=lambda: scheduler(last_task_result=1234)).check(
        persist=False
    )
    assert unknown["checks"]["scheduler_last_result"]["lane_outcome"] is None
    assert unknown["verdict"] == WD.WATCH_ALARM
    assert "not in the lane's vocabulary" in unknown["checks"]["scheduler_last_result"]["reason"]


# --------------------------------------------------------------------------- the cause
def test_the_six_causes_are_closed_and_cover_every_outcome_the_lane_produces():
    """Where a failure is *noticed* is not what it *is*, so the causes are named and counted."""
    assert set(WD.FAILURE_CLASSES) == {
        WD.FAILURE_RESOURCE,
        WD.FAILURE_PROVIDER,
        WD.FAILURE_DATA_QUALITY,
        WD.FAILURE_RUNTIME,
        WD.FAILURE_SCHEDULER,
        WD.FAILURE_EXPECTED_NO_NEW_DATA,
    }
    # Every cause that is trouble is shown as a category; the expected one is not trouble.
    assert set(WD.CATEGORY_BY_FAILURE_CLASS) == set(WD.FAILURE_CLASSES) - {
        WD.FAILURE_EXPECTED_NO_NEW_DATA
    }
    from trading_bot.research.edge03.autonomous import EXIT_CODES

    for outcome in EXIT_CODES:
        if outcome == "OBSERVED":
            continue  # a tick that observed something is not a failure of any kind
        assert outcome in WD.FAILURE_CLASS_BY_OUTCOME, f"{outcome} has no cause"
        assert WD.FAILURE_CLASS_BY_OUTCOME[outcome] in WD.FAILURE_CLASSES


def test_a_tick_the_lane_refused_on_disk_is_resource_pressure_and_never_a_scheduler_failure(
    tmp_path,
):
    """The finding: a scheduler that fired on time, a lane that declined, and a wrong accusation.

    The scheduler's result code is non-zero, so the old rule read it as the task failing and sent
    the reader to repair the scheduler. The cause is the volume, and that is where the remedy is.
    """
    lane = healthy_lane(tmp_path)
    # 5 is the lane's DISK_BUDGET_EXCEEDED; the volume itself is not even low in this reading, so
    # the only thing that can explain the non-zero result is the refusal the lane wrote down.
    row = watchdog(tmp_path, lane, scheduler_probe=lambda: scheduler(last_task_result=5)).check(
        persist=False
    )
    assert row["checks"]["scheduler_last_result"]["failure_class"] == WD.FAILURE_RESOURCE
    assert row["cause"] == WD.FAILURE_RESOURCE
    assert row["category"] == WD.CATEGORY_RESOURCE_PRESSURE
    assert row["category"] != WD.CATEGORY_SCHEDULER_FAILURE
    assert row["operational_failure"] is True, "a refused tick is a tick that did not observe"
    assert row["checks"]["scheduler_task"]["status"] == WD.STATUS_OK
    kinds = {alert["kind"]: alert for alert in row["alerts"]}
    # The refusal is still an alarm — filed against the volume.
    assert kinds["TICK_REFUSED_RESOURCE"]["state"] == "RESULT:DISK_BUDGET_EXCEEDED"
    assert kinds["TICK_REFUSED_RESOURCE"]["severity"] == "CRITICAL"
    # The scheduler is cleared in words, not merely left unmentioned.
    assert kinds["SCHEDULER_TASK_FAILED"]["state"] == "CLEAR"
    assert kinds["SCHEDULER_TASK_FAILED"]["severity"] == "INFO"


@pytest.mark.parametrize(
    ("exit_code", "expected_class", "expected_category", "expected_verdict"),
    (
        (5, WD.FAILURE_RESOURCE, WD.CATEGORY_RESOURCE_PRESSURE, WD.WATCH_ALARM),
        (7, WD.FAILURE_PROVIDER, WD.CATEGORY_PROVIDER_FAILURE, WD.WATCH_DEGRADED),
        (4, WD.FAILURE_DATA_QUALITY, WD.CATEGORY_DATA_QUALITY_FAILURE, WD.WATCH_DEGRADED),
        (6, WD.FAILURE_DATA_QUALITY, WD.CATEGORY_DATA_QUALITY_FAILURE, WD.WATCH_ALARM),
        (1, WD.FAILURE_RUNTIME, WD.CATEGORY_RUNTIME_FAILURE, WD.WATCH_ALARM),
    ),
)
def test_each_cause_is_named_and_the_category_follows_the_cause(
    tmp_path, exit_code, expected_class, expected_category, expected_verdict
):
    """The lane's own exit code names the cause, and the cause picks the category."""
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path, lane, scheduler_probe=lambda: scheduler(last_task_result=exit_code)
    ).check(persist=False)
    result = row["checks"]["scheduler_last_result"]
    assert result["exit_code"] == exit_code
    assert result["failure_class"] == expected_class
    assert row["cause"] == expected_class
    assert row["category"] == expected_category
    assert row["expected_no_new_data"] is False
    assert expected_class in row["failure_classes"]
    assert row["verdict"] == expected_verdict
    # Only a genuine scheduler fault may be filed as one.
    if expected_class != WD.FAILURE_SCHEDULER:
        assert row["category"] != WD.CATEGORY_SCHEDULER_FAILURE


def test_a_warning_volume_is_resource_pressure_and_not_a_healthy_reading(tmp_path):
    """The live log produced this contradiction once, at 21:17:33Z, and the verifier caught it.

    Below the *warning* floor the lane still ingests and the heavy publication waits: the reading
    is degraded, and a degraded reading may not be filed as healthy.
    """
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path, lane, disk_probe=lambda path: disk_reading(WD.WARNING, 3 * 1024**3)
    ).check(persist=False)
    assert row["verdict"] == WD.WATCH_DEGRADED
    assert row["category"] == WD.CATEGORY_RESOURCE_PRESSURE
    assert row["category"] != WD.CATEGORY_HEALTHY


def test_a_non_ok_verdict_is_never_filed_as_healthy(tmp_path):
    """The invariant the verifier enforces, held by the chain itself rather than by luck.

    Every check is forced, one at a time, to each status that is not OK; whatever the reading then
    says about the lane, it may not claim the lane is healthy.
    """
    lane = healthy_lane(tmp_path)
    for name in WD.CHECK_NAMES:
        for status in (WD.STATUS_UNKNOWN, WD.STATUS_WARN, WD.STATUS_ALARM, WD.STATUS_BLOCKED):
            seen = watchdog(tmp_path, lane)
            original = getattr(seen, f"check_{name}")

            def forced(*args: Any, _original: Any = original, _status: str = status, **kwargs: Any):
                return {**_original(*args, **kwargs), "status": _status}

            setattr(seen, f"check_{name}", forced)
            row = seen.check(persist=False)
            assert row["verdict"] != WD.WATCH_OK, (name, status, row["verdict"])
            assert row["category"] != WD.CATEGORY_HEALTHY, (name, status, row["category"])


def test_a_tick_with_nothing_to_do_is_named_as_expected_rather_than_as_trouble(tmp_path):
    """A second trigger losing the lease to a live tick is the schedule working, and says so."""
    lane = healthy_lane(tmp_path)
    # 2 is the lane's ALREADY_RUNNING: the trigger arrived while a tick was already in flight.
    row = watchdog(tmp_path, lane, scheduler_probe=lambda: scheduler(last_task_result=2)).check(
        persist=False
    )
    result = row["checks"]["scheduler_last_result"]
    assert result["failure_class"] == WD.FAILURE_EXPECTED_NO_NEW_DATA
    assert row["expected_no_new_data"] is True
    assert WD.FAILURE_EXPECTED_NO_NEW_DATA in row["failure_classes"]
    # It is not an alarm, so it is not a cause, and nothing in it accuses the scheduler.
    assert row["cause"] is None
    assert WD.CATEGORY_SCHEDULER_FAILURE not in {row["category"]}


def test_a_platform_that_cannot_be_read_is_unknown_and_never_a_pass(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path,
        lane,
        scheduler_probe=lambda: {"available": False, "reason": "no task scheduler here"},
        instant_probe=lambda: {"available": False, "reason": "no Task Scheduler on this platform"},
    ).check(persist=False)
    assert row["checks"]["scheduler_task"]["status"] == WD.STATUS_UNKNOWN
    assert row["checks"]["scheduler_cadence"]["status"] == WD.STATUS_UNKNOWN
    assert row["verdict"] == WD.WATCH_DEGRADED


def test_a_local_instant_is_never_read_as_utc(tmp_path):
    lane = healthy_lane(tmp_path)
    # The supervisor's spelling of the instant is unlabelled local time. Only the round-trip UTC
    # form is read, and the platform's own spelling is kept verbatim for a reader.
    row = watchdog(
        tmp_path,
        lane,
        now_ms=T0 + 6 * QUARTER,
        scheduler_probe=lambda: scheduler(next_run_time="10/13/2026 20:55:53"),
        instant_probe=lambda: instants(now_ms=T0 + 6 * QUARTER, next_run_ms=T0 + 7 * QUARTER),
    ).check(persist=False)
    cadence = row["checks"]["scheduler_cadence"]
    assert cadence["next_run_utc"] == stamp_ms(T0 + 7 * QUARTER)
    assert cadence["scheduler_spelling"] == "10/13/2026 20:55:53"
    assert cadence["status"] == WD.STATUS_OK


def test_a_next_trigger_that_was_due_and_did_not_fire_is_a_stalled_schedule(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path,
        lane,
        instant_probe=lambda: instants(next_run_ms=T0 - 900_000, missed=2),
    ).check(persist=False)
    assert row["checks"]["scheduler_cadence"]["status"] == WD.STATUS_ALARM
    assert row["checks"]["scheduler_cadence"]["missed_runs"] == 2
    assert row["verdict"] == WD.WATCH_ALARM


def test_a_probe_that_answers_long_after_the_reading_is_reported_as_a_late_probe(tmp_path):
    """A lag is elapsed time and is named as one: the finding is about the probe, not the clocks."""
    lane = healthy_lane(tmp_path)
    late = instants(next_run_ms=T0 + 900_000)
    late["queried_at_utc"] = stamp_ms(T0 + 4 * HOUR)
    row = watchdog(tmp_path, lane, instant_probe=lambda: late).check(persist=False)
    cadence = row["checks"]["scheduler_cadence"]
    assert cadence["status"] == WD.STATUS_ALARM
    assert cadence["probe_answer_lag_seconds"] == (4 * HOUR - 5 * QUARTER) / 1000.0
    assert "elapsed time" in cadence["reason"]
    assert "clock skew" not in cadence["reason"]


def test_a_probe_answering_before_the_reading_it_followed_is_a_clock_disagreement(tmp_path):
    """The one direction elapsed time cannot produce, and the test says why it cannot."""
    lane = healthy_lane(tmp_path)
    early = instants(next_run_ms=T0 + 900_000)
    early["queried_at_utc"] = stamp_ms(T0 - 4 * HOUR)
    row = watchdog(tmp_path, lane, instant_probe=lambda: early).check(persist=False)
    cadence = row["checks"]["scheduler_cadence"]
    assert cadence["status"] == WD.STATUS_ALARM
    assert cadence["probe_answer_lag_seconds"] == -(4 * HOUR + 5 * QUARTER) / 1000.0
    assert "one clock cannot" in cadence["reason"]
    assert cadence["reading_stamped_at_utc"] and cadence["probe_reported_now_utc"]


# --------------------------------------------------------------------------- the process
def test_a_tick_that_started_and_never_finished_is_a_dead_process(tmp_path):
    lane = healthy_lane(tmp_path, ticks=4)
    lane.tick(T0 + 4 * QUARTER, inflight=True)
    row = watchdog(tmp_path, lane).check(persist=False)
    assert row["checks"]["lane_process"]["status"] == WD.STATUS_ALARM
    assert row["checks"]["lane_process"]["unfinished_runs"][0]["pid"] == 4242
    assert "TICK_DIED_MID_WRITE" in {alert["kind"] for alert in row["alerts"]}


def test_a_tick_the_scheduler_launched_is_told_from_one_a_person_launched(tmp_path):
    lane = healthy_lane(tmp_path)
    from_scheduler = watchdog(
        tmp_path,
        lane,
        process_probe=lambda: {
            "available": True,
            "processes": [
                {"pid": 11, "parent_pid": 900, "name": "python.exe", "parent_name": "svchost.exe"}
            ],
        },
    ).check(persist=False)
    assert from_scheduler["checks"]["lane_process"]["observer_running"] is True
    assert (
        from_scheduler["checks"]["lane_process"]["observer_processes"][0][
            "launched_by_task_scheduler"
        ]
        is True
    )
    from_a_shell = watchdog(
        tmp_path,
        lane,
        process_probe=lambda: {
            "available": True,
            "processes": [
                {"pid": 11, "parent_pid": 900, "name": "python.exe", "parent_name": "bash.exe"}
            ],
        },
    ).check(persist=False)
    assert (
        from_a_shell["checks"]["lane_process"]["observer_processes"][0][
            "launched_by_task_scheduler"
        ]
        is False
    )


# --------------------------------------------------------------------------- evidence
def test_a_torn_line_in_the_lanes_log_is_an_alarm_and_counted(tmp_path):
    lane = healthy_lane(tmp_path)
    with lane.runs_path.open("a", encoding="utf-8") as handle:
        handle.write('{"run_id": "half a row"\n')
    row = watchdog(tmp_path, lane).check(persist=False)
    assert row["checks"]["evidence_integrity"]["corrupt_lines"]["runs"] == 1
    assert row["checks"]["evidence_integrity"]["status"] == WD.STATUS_ALARM
    assert "EVIDENCE_CORRUPT" in {alert["kind"] for alert in row["alerts"]}


def test_a_seal_the_ledger_no_longer_explains_is_named_and_not_rounded_away(tmp_path):
    lane = healthy_lane(tmp_path)
    _append = lane.slots_path.read_text(encoding="utf-8")
    lane.slots_path.write_text(_append + _append.splitlines()[0] + "\n", encoding="utf-8")
    row = watchdog(tmp_path, lane).check(persist=False)
    integrity = row["checks"]["evidence_integrity"]
    assert integrity["duplicate_seals"]
    assert integrity["status"] == WD.STATUS_WARN
    assert row["verdict"] == WD.WATCH_DEGRADED


def test_an_attempt_with_no_run_row_is_reported_and_asks_for_a_reconciliation(tmp_path):
    lane = healthy_lane(tmp_path)
    lane.tick(T0 + 6 * QUARTER, run=False)
    row = watchdog(tmp_path, lane, now_ms=T0 + 6 * QUARTER + 5_000).check(persist=False)
    integrity = row["checks"]["evidence_integrity"]
    assert len(integrity["attempts_without_a_run"]) == 1
    assert integrity["attempts_without_a_run"][0]["bars"] >= 1
    assert integrity["unattributed_bars"] == integrity["attempts_without_a_run"][0]["bars"]
    kinds = {alert["kind"] for alert in row["alerts"]}
    assert "RECONCILIATION_REQUIRED" in kinds
    assert row["verdict"] != WD.WATCH_OK


def test_a_second_pass_that_appends_a_bar_breaks_the_restart_proof(tmp_path):
    lane = healthy_lane(tmp_path)
    lane.tick(T0 + 6 * QUARTER, append_on_second_pass=1)
    row = watchdog(tmp_path, lane, now_ms=T0 + 6 * QUARTER + 5_000).check(persist=False)
    proof = row["checks"]["restart_proof"]
    assert proof["status"] == WD.STATUS_BLOCKED
    assert proof["broken"]
    assert row["verdict"] == WD.WATCH_BLOCKED
    assert row["category"] == WD.CATEGORY_EVIDENCE_BROKEN


def test_a_lease_left_behind_by_a_dead_tick_is_read_as_arithmetic(tmp_path):
    lane = healthy_lane(tmp_path)
    lock_dir = lane.state / "lock"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "CAMPAIGN_LOCK.json").write_text(
        json.dumps(
            {
                "lease_version": "CAMPAIGN_LEASE_V1",
                "campaign_id": "EDGE04_FORWARD_OBSERVER",
                # This process's own pid: the lease's own rule consults the process table before
                # the age bound when the holder is somebody else, and a fixture that depended on
                # a pid existing would be testing the host rather than the watchdog.
                "pid": os.getpid(),
                "host": "HOST",
                "acquired_at": int((T0 + 5 * QUARTER) / 1000),
                "renewed_at": int((T0 + 5 * QUARTER) / 1000),
                "stale_after_seconds": 300,
            }
        ),
        encoding="utf-8",
    )
    fresh = watchdog(tmp_path, lane, now_ms=T0 + 5 * QUARTER).check(persist=False)
    assert fresh["checks"]["lane_lease"]["status"] == WD.STATUS_OK
    assert fresh["checks"]["lane_lease"]["held"] is True
    # the lease is renewed when the last tick finished and nothing renews it after: 900 s later it
    # is past its own 300 s bound, and the tick that would have renewed it has already finished.
    stale = watchdog(tmp_path, lane, now_ms=T0 + 6 * QUARTER).check(persist=False)
    assert stale["checks"]["lane_lease"]["stale"] is True
    assert stale["checks"]["lane_lease"]["abandoned_by_a_finished_tick"] is True
    assert stale["verdict"] == WD.WATCH_DEGRADED


# --------------------------------------------------------------------------- resources
def disk_reading(status: str, free: int) -> dict[str, Any]:
    return {
        "path": "lane",
        "free_bytes": free,
        "free_gib": round(free / 1024**3, 4),
        "total_bytes": 100 * 1024**3,
        "total_gib": 100.0,
        "used_percent": 99.0,
        "warning_free_bytes": 5 * 1024**3,
        "critical_free_bytes": 2 * 1024**3,
        "status": status,
    }


def _lane_tree(lane: Lane) -> dict[str, bytes]:
    """The lane's own files only: the store and the lane's state root, never the watchdog's."""
    out: dict[str, bytes] = {}
    for base in (lane.state, lane.store):
        for path in base.rglob("*"):
            if path.is_file():
                out[path.relative_to(lane.root).as_posix()] = path.read_bytes()
    return out


def test_a_volume_below_the_critical_floor_is_blocked_and_nothing_is_deleted(tmp_path):
    lane = healthy_lane(tmp_path)
    before = _lane_tree(lane)
    row = watchdog(
        tmp_path,
        lane,
        disk_probe=lambda path: disk_reading(WD.CRITICAL, 1 * 1024**3),
    ).check(persist=False)
    assert row["checks"]["resource_disk"]["status"] == WD.STATUS_BLOCKED
    assert row["verdict"] == WD.WATCH_BLOCKED
    assert row["category"] == WD.CATEGORY_RESOURCE_PRESSURE
    assert "DISK_CRITICAL" in {alert["kind"] for alert in row["alerts"]}
    assert _lane_tree(lane) == before, "the watchdog must not touch the lane's tree at all"


def test_a_volume_below_the_warning_floor_degrades_without_stopping_anything(tmp_path):
    lane = healthy_lane(tmp_path)
    row = watchdog(
        tmp_path, lane, disk_probe=lambda path: disk_reading(WD.WARNING, 3 * 1024**3)
    ).check(persist=False)
    assert row["checks"]["resource_disk"]["status"] == WD.STATUS_WARN
    assert row["verdict"] == WD.WATCH_DEGRADED
    assert row["operational_failure"] is False


def test_growth_above_the_declared_thresholds_raises_an_alert_and_creates_no_forecast(tmp_path):
    lane = healthy_lane(tmp_path)
    lane.state.mkdir(parents=True, exist_ok=True)
    (lane.state / "resource_budget.json").write_text(
        json.dumps(
            {
                "generated_at_utc": stamp_ms(T0),
                "measured": {"lane_bytes": 3_000_000},
                "growth": {"status": "STABLE", "bytes_per_day": 100 * 1024 * 1024},
            }
        ),
        encoding="utf-8",
    )
    row = watchdog(tmp_path, lane).check(persist=False)
    growth = row["checks"]["resource_growth"]
    assert growth["status"] == WD.STATUS_ALARM
    assert growth["deletes_evidence"] is False
    assert "GROWTH_BUDGET_EXCEEDED" in {alert["kind"] for alert in row["alerts"]}
    # A volatile rate is not turned into a verdict, and a missing reading is not a pass either.
    (lane.state / "resource_budget.json").write_text(
        json.dumps({"growth": {"status": "VOLATILE", "bytes_per_day": None}}), encoding="utf-8"
    )
    volatile = watchdog(tmp_path, lane).check(persist=False)
    assert volatile["checks"]["resource_growth"]["status"] == WD.STATUS_OK
    assert "not invented" in volatile["checks"]["resource_growth"]["reason"]


# --------------------------------------------------------------------------- transitions
def test_alerts_are_per_transition_and_a_recovery_names_the_tick_that_ended_it(tmp_path):
    lane = healthy_lane(tmp_path)
    clock = {"now": T0 + 6 * QUARTER}
    state = {"disabled": False}
    seen = watchdog(
        tmp_path,
        lane,
        scheduler_probe=lambda: scheduler(
            enabled=not state["disabled"], state="Disabled" if state["disabled"] else "Ready"
        ),
        clock=lambda: clock["now"] / 1000.0,
    )
    first = seen.check()
    assert first["verdict"] == WD.WATCH_OK
    # the outage
    state["disabled"] = True
    clock["now"] = T0 + 6 * QUARTER + 60_000
    second = seen.check()
    assert second["verdict"] == WD.WATCH_ALARM
    assert "SCHEDULER_DISABLED" in {alert["kind"] for alert in second["alerts"]}
    # a second check in the same state is not news
    third = seen.check()
    assert third["alerts"] == []
    # the lane ticks again and the scheduler is back
    lane.tick(T0 + 6 * QUARTER)
    state["disabled"] = False
    clock["now"] = T0 + 6 * QUARTER + 5_000
    recovered = seen.check()
    assert recovered["verdict"] == WD.WATCH_OK
    kinds = {alert["kind"] for alert in recovered["alerts"]}
    assert "WATCHDOG_RECOVERED" in kinds
    recovery = next(alert for alert in recovered["alerts"] if alert["kind"] == "WATCHDOG_RECOVERED")
    assert recovery["recovered_from"] == WD.WATCH_ALARM
    assert recovery["recovered_by_run_id"] == lane.runs[-1]["run_id"]
    assert recovery["recovered_by_tick_utc"] == lane.runs[-1]["finished_at_utc"]
    assert recovered["history"]["episodes_of_trouble"] == 1
    assert recovered["history"]["recoveries"] == 1
    assert recovered["history"]["episode_open"] is False
    # a healthy check after a healthy check writes nothing at all
    clock["now"] = T0 + 6 * QUARTER + 6_000
    assert seen.check()["alerts"] == []


def test_the_scheduler_going_down_and_coming_back_is_one_episode_and_one_recovery(tmp_path):
    """The detection the work package asks for, as a sequence rather than as a sentence."""
    lane = healthy_lane(tmp_path)
    clock = {"now": T0 + 6 * QUARTER}
    state = {"installed": True, "enabled": True}
    seen = watchdog(
        tmp_path,
        lane,
        scheduler_probe=lambda: scheduler(
            installed=state["installed"],
            enabled=state["enabled"],
            state="Ready" if state["enabled"] else "Disabled",
        ),
        clock=lambda: clock["now"] / 1000.0,
    )
    assert seen.check()["verdict"] == WD.WATCH_OK
    # the task is removed entirely
    state.update(installed=False, enabled=False)
    clock["now"] = T0 + 6 * QUARTER + 30_000
    removed = seen.check()
    assert removed["verdict"] == WD.WATCH_BLOCKED
    assert removed["history"]["episode_open"] is True
    assert removed["history"]["episodes_of_trouble"] == 1
    # it is registered again and fires
    state.update(installed=True, enabled=True)
    lane.tick(T0 + 7 * QUARTER)
    clock["now"] = T0 + 7 * QUARTER + 5_000
    back = seen.check()
    assert back["verdict"] == WD.WATCH_OK
    assert back["history"]["recoveries"] == 1
    assert "WATCHDOG_RECOVERED" in {alert["kind"] for alert in back["alerts"]}


def test_the_watchdog_announces_its_own_silence(tmp_path):
    lane = healthy_lane(tmp_path)
    clock = {"now": T0 + 6 * QUARTER}
    seen = watchdog(tmp_path, lane, clock=lambda: clock["now"] / 1000.0)
    seen.check()
    clock["now"] = T0 + 6 * QUARTER + 7 * 900_000
    row = seen.check()
    assert row["checks"]["watchdog_cadence"]["status"] == WD.STATUS_ALARM
    assert "WATCHDOG_SELF_GAP" in {alert["kind"] for alert in row["alerts"]}


def test_a_recovery_is_only_announced_after_a_real_trouble(tmp_path):
    lane = healthy_lane(tmp_path)
    clock = {"now": T0 + 6 * QUARTER}
    seen = watchdog(tmp_path, lane, clock=lambda: clock["now"] / 1000.0)
    assert seen.check()["alerts"], "the first check announces the state it found"
    clock["now"] = T0 + 6 * QUARTER + 1000
    assert seen.check()["alerts"] == []


# --------------------------------------------------------------------------- restraint
def test_the_watchdog_never_writes_inside_the_lane_and_never_asks_the_market(tmp_path):
    lane = healthy_lane(tmp_path)
    before = _lane_tree(lane)
    seen = watchdog(tmp_path, lane)
    row = seen.check()
    assert row["wrote_to_lane"] is False
    assert row["market_requests"] == 0
    assert row["checks"]["lane_lease"]["status"] == WD.STATUS_OK
    assert _lane_tree(lane) == before, "the lane's own tree must be byte-identical after a check"
    # and everything it did write is under its own root
    assert seen.latest_path.is_file()
    assert seen.watch_path.is_file()


def test_the_watchdogs_own_log_is_bounded(tmp_path):
    lane = healthy_lane(tmp_path)
    seen = watchdog(tmp_path, lane, watch_kept=3)
    for index in range(6):
        seen.check(now_ms=T0 + 5 * QUARTER + index * 1000)
    rows, corrupt = WD.read_jsonl(seen.watch_path)
    assert len(rows) == 3
    assert corrupt == 0


def test_a_snapshot_that_would_repeat_itself_is_refused(tmp_path):
    lane = healthy_lane(tmp_path)
    seen = watchdog(tmp_path, lane)
    seen.check()
    first = seen.snapshot(tmp_path / "snap1")
    assert first["status"] == "WRITTEN"
    assert first["files"] >= 1
    second = seen.snapshot(tmp_path / "snap2")
    assert second["status"] == "SKIPPED_IDENTICAL"
    assert not (tmp_path / "snap2" / "SNAPSHOT.json").exists()
    forced = seen.snapshot(tmp_path / "snap3", force=True)
    assert forced["status"] == "WRITTEN"


def test_the_worst_status_wins_everywhere(tmp_path):
    lane = healthy_lane(tmp_path)
    seen = watchdog(tmp_path, lane, disk_probe=lambda path: disk_reading(WD.CRITICAL, 1))
    row = seen.check(persist=False)
    assert row["verdict"] == WD.WATCH_BLOCKED
    statuses = {body["status"] for body in row["checks"].values()}
    assert WD.STATUS_BLOCKED in statuses
    assert row["category"] == WD.CATEGORY_RESOURCE_PRESSURE
