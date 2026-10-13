"""WP-EDGE-04 — the autonomous observer's own regressions.

The observer exists so that days accumulate without an operator, so the tests that matter are
the ones about *restraint and honesty*:

* a slot is observed once, a second tick in it makes no market request at all, and a repeat
  tick inside a drained slot leaves the single seal alone while still recording its own row;
* two triggers at the same time leave the second holding nothing and touching nothing;
* a lease a crashed tick left behind is reclaimed by age, because this platform cannot always
  prove a pid is dead;
* a tick that ingested nothing says so, and a tick whose provider answered nothing does not
  report success;
* bars that closed while the observer was down are recovered by the next tick, and a hole the
  venue returned is *named* rather than smoothed over;
* a moved ruleset is a refusal, not a warning;
* a volume below the critical floor stops the tick before a single request, and a volume below
  the warning floor still ingests while the heavy publication waits;
* the bounded logs are bounded and the daily evidence files are not;
* a publication interrupted mid-write leaves no half-written report and no staging tree;
* a day of backfilled bars is not an observation day, however dense it looks;
* the reports re-render offline, byte for byte, from the observation the tick preserved.

The scheduler-layer tests inject a fake pipeline so they are fast and exact, and pin the clock
completely; the integration tests drive the real frozen pipeline over a scripted venue.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge03 import autonomous as AUTO  # noqa: E402
from trading_bot.research.edge03 import forward_plan as FP  # noqa: E402
from trading_bot.research.edge03 import run as RUN  # noqa: E402
from trading_bot.research.edge03.ingest import ScriptedKlineSource  # noqa: E402

HOUR = 3_600_000
QUARTER = 900_000
FROZEN_1H_END = 1_772_319_600_000
FROZEN_15M_END = 1_791_372_600_000
SERIES = (
    ("1h", "BTC"),
    ("1h", "ETH"),
    ("1h", "SOL"),
    ("15m", "BTC"),
    ("15m", "ETH"),
    ("15m", "SOL"),
)
#: A fixed synthetic instant on a 15-minute boundary. Every clock in these tests is pinned.
INSTANT = 1_792_000_000_000 - (1_792_000_000_000 % QUARTER)


class Clock:
    """A pinned wall clock, so a tick's own clock can be told apart from its market instant."""

    def __init__(self, instant_ms: int) -> None:
        self.ms = int(instant_ms)

    def __call__(self) -> float:
        return self.ms / 1000.0

    def advance_to(self, instant_ms: int) -> None:
        self.ms = int(instant_ms)


def load_script(relative: str):
    """Import a ``scripts/`` file by path, with the module registered before it runs."""
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(f"edge04_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def kline(ts: int, price: float = 100.0):
    """One Binance-shaped row: ``[open_ts, o, h, l, c, v, close_ts, ...]``."""
    return [
        ts,
        price,
        price + 1,
        price - 1,
        price + 0.5,
        10.0,
        ts + HOUR - 1,
        "0",
        "0",
        "0",
        "0",
        "0",
    ]


def fake_payload(
    *,
    observed_at_ms: int,
    append_per_series: int = 1,
    series_behind: int = 1,
    error_series: int = 0,
    signals: int = 0,
    trades: int = 2,
) -> dict[str, Any]:
    """A payload shaped exactly like the frozen pipeline's, for the scheduler layer's tests.

    The bookkeeping is *coherent*: the ledger's high-water mark is where the store ended before
    the tick, the manifest's last instant is where it ends after it, and the bars the tick
    appended are the difference. A fake that could not be checked the way the real payload is
    checked would test nothing.
    """
    ledger = []
    files: dict[str, Any] = {}
    appended_total = 0
    for index, (timeframe, symbol) in enumerate(SERIES):
        span = QUARTER if timeframe == "15m" else HOUR
        last_closed_open = ((observed_at_ms // span) * span) - span
        high_water = last_closed_open - series_behind * span
        appended = 0 if index < error_series else append_per_series
        appended_total += appended
        ledger.append(
            {
                "timeframe": timeframe,
                "symbol": symbol,
                "frozen_end_ms": FROZEN_15M_END if timeframe == "15m" else FROZEN_1H_END,
                "high_water_ts": high_water,
                "outcome": "error"
                if index < error_series
                else ("ingested" if appended else "no_new_data"),
                "appended": appended,
                "requests": [f"/api/v3/klines?{timeframe}:{symbol}"],
                "reason": "scripted: the venue answered nothing" if index < error_series else None,
            }
        )
        files[f"{timeframe}:{symbol}"] = {
            "path": f"{symbol}.jsonl",
            "relative_path": f"{timeframe}/{symbol}.jsonl",
            "bars": 10 + appended,
            "first_ts": FROZEN_1H_END + HOUR,
            "last_ts": high_water + appended * span if appended else high_water,
            "sha256": f"{symbol.lower()}{index}" * 8,
            "bytes": 1000,
        }
    arms = {
        "edge_trend_01_4h:BASE": {
            "status": "observed",
            "arm": "edge_trend_01_4h:BASE",
            "timeframe": "4h",
            "signal_count": signals,
            "metrics": {
                "trades": trades,
                "net_usdt": -44.307497,
                "gross_usdt": -9.087451,
                "fees_usdt": 29.608409,
                "price_costs_usdt": 5.611636,
                "max_drawdown_pct": 2.776571,
                "hypothetical": True,
                "order_sent": False,
            },
            "refusal_mix": {"MAX_POSITION_SIZE": 2},
            "candidate_bars_evaluated": 4002,
            "signals_detail": [
                {"decision_ts": observed_at_ms - 2 * HOUR, "candidate": "edge_trend_01_4h"}
            ][:signals],
            "trades_detail": [
                {"entry_ts": observed_at_ms - 3 * HOUR, "arm": "edge_trend_01_4h:BASE"}
            ][:trades],
            "refusals_detail": [],
            "orders_detail": [],
        },
        "edge_intra_01:BASE": {
            "status": "no_forward_bars",
            "reason": "no 15m forward bars",
            "timeframe": "15m",
            "scenario": "BASE",
            "metrics": {"trades": 0, "net_usdt": 0.0},
            "signal_count": 0,
            "refusal_mix": {},
        },
    }
    return {
        "run_id": "FWD-EDGE03-TEST",
        "generated_at_utc": AUTO.stamp(observed_at_ms + 20_000),
        "observed_at_ms": observed_at_ms,
        "observed_at_utc": AUTO.stamp(observed_at_ms),
        "frozen_params": {
            "params_hash": "f" * 64,
            "agrees_with_publication": True,
            "published_params_hash": "f" * 64,
        },
        "ingest": {"ledger": ledger, "ledger_path": "ledger/INGEST_LEDGER.jsonl"},
        "manifest": {
            "files": files,
            "series": len(files),
            "total_bars": sum(body["bars"] for body in files.values()),
        },
        "health": {
            "new_bars": 0 if error_series == len(SERIES) else appended_total,
            "stored_bars": 100,
            "observation_days": 226,
            "observation_days_detail": {"common_days": 226},
            "ingest_runs": len(SERIES),
            "ingest_outcomes": {"ingested": len(SERIES)},
            "no_new_data_series": [],
            "errors": [
                {"series": f"{tf}:{sym}", "stage": "ingest", "error": "scripted failure"}
                for tf, sym in SERIES[:error_series]
            ],
            "primary_trades": trades,
        },
        "shadow": {
            "primary_arm": "edge_trend_01_4h:BASE",
            "primary_available": True,
            "context_note": "scripted",
            "provenance": {},
            "decisions_digest": "d" * 64,
            "captured_decisions": 7,
            "arm_summaries": arms,
            "start_equity": 10_000.0,
            "hypothetical": True,
            "order_sent": False,
        },
        "latency": {
            key: {
                "samples": 10,
                "min_seconds": 1.0,
                "median_seconds": 5.0,
                "max_seconds": 9.0,
                "fresh_bars": 1,
                "fresh_samples": 1,
                "fresh_min_seconds": 1.0,
                "fresh_median_seconds": 2.0,
                "fresh_max_seconds": 2.5,
                "fetch_instants": 1,
            }
            for key in files
        },
        "parity": {"verdict": "PARITY_PASS", "counts": {}, "defects": []},
        "verdict": {"state": "OBSERVATION_RUNNING", "promotion": "NONE"},
    }


def stub_publish(seen: AUTO.ForwardObserver, payload: dict[str, Any]) -> dict[str, Path]:
    """A stand-in for the heavy artefact set: one file the pointer can answer for."""
    path = seen.publication_dir / "CUMULATIVE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"stub {payload.get('run_id')}\n", encoding="utf-8")
    return {"cumulative": path}


def fake_pipeline(**options: Any):
    """A fake pipeline coherent with whatever market instant the tick asks for.

    It runs the frozen pin first, exactly as the real pipeline does, so a test that tunes the
    ruleset exercises the refusal rather than a stub that never looks at it.
    """

    def pipeline(**call: Any) -> dict[str, Any]:
        FP.assert_frozen_params()
        return fake_payload(observed_at_ms=int(call.get("observed_at_ms") or INSTANT), **options)

    return pipeline


def counting_pipeline(calls: list[dict[str, Any]], **options: Any):
    inner = fake_pipeline(**options)

    def pipeline(**call: Any) -> dict[str, Any]:
        calls.append(call)
        return inner(**call)

    return pipeline


def observer(
    tmp_path: Path,
    *,
    clock: Clock | None = None,
    stub: bool = True,
    **kwargs: Any,
) -> AUTO.ForwardObserver:
    """An observer over a scratch state root, with a coherent fake pipeline unless given one."""
    kwargs.setdefault("pipeline", fake_pipeline())
    kwargs.setdefault("sleep", lambda seconds: None)
    kwargs.setdefault("clock", clock or Clock(INSTANT))
    # The volume is pinned HEALTHY so that this host's free space cannot decide an assertion: a
    # machine that happens to be near its floors must not turn a tick test green or red. The tests
    # that are about the disk policy itself pin their own floors, as they do above.
    kwargs.setdefault("warning_bytes", 1)
    kwargs.setdefault("critical_bytes", 1)
    seen = AUTO.ForwardObserver(
        repo_root=tmp_path,
        state_root=tmp_path / "state",
        store_root=tmp_path / "store",
        **kwargs,
    )
    if stub:
        seen.publish = lambda payload: stub_publish(seen, payload)  # type: ignore[method-assign]
    return seen


# --------------------------------------------------------------------------- slot discipline
def test_a_tick_records_its_outcome_slot_and_evidence(tmp_path):
    seen = observer(tmp_path)
    record = seen.tick(observed_at_ms=INSTANT, mode=AUTO.MODE_SCHEDULED)
    assert record["outcome"] == AUTO.OBSERVED
    assert record["exit_code"] == AUTO.EXIT_OK
    assert record["mode"] == AUTO.MODE_SCHEDULED
    assert record["slot_key"] == AUTO.slot_key(AUTO.slot_of(INSTANT))
    assert record["market_requests"] == 7  # one server time plus one request per series
    assert record["new_bars"] == 6
    assert record["expected_new_bars"] == 6 and record["missing_bars"] == 0
    assert record["order_sent"] is False and record["promotion"] == "NONE"
    assert record["duration_seconds"] == 0.0  # the clock is pinned
    assert seen.runs_path.is_file() and seen.slots_path.is_file()
    assert seen.health_path.is_file() and seen.coverage_path.is_file()
    daily = json.loads(seen.daily_path(AUTO.day_key(INSTANT)).read_text(encoding="utf-8"))
    assert daily["ticks"] == 1 and daily["new_bars"] == 6
    assert list(daily["slots"]) == [record["slot_key"]]
    assert daily["ruleset_params_hash"] == "f" * 64
    assert daily["hypothetical"] is True and daily["order_sent"] is False
    assert record["health_status"] == "HEALTHY"


def test_a_second_tick_in_an_observed_slot_makes_no_market_request(tmp_path):
    """``--due`` is the whole point of a 15-minute cadence: one observation per slot."""
    calls: list[dict[str, Any]] = []
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=counting_pipeline(calls))
    first = seen.tick(observed_at_ms=INSTANT, due_only=True)
    second = seen.tick(observed_at_ms=INSTANT + 60_000, due_only=True)
    assert first["outcome"] == AUTO.OBSERVED
    assert second["outcome"] == AUTO.ALREADY_OBSERVED
    assert second["market_requests"] == 0
    assert second["exit_code"] == AUTO.EXIT_OK
    assert len(calls) == 1, "the pipeline was called for a slot that was already observed"
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_repeat_tick_in_a_drained_slot_leaves_the_single_seal_alone(tmp_path):
    """The seal belongs to the tick that drained the slot; a later one records and spends nothing.

    A manual re-run, a probe, a trigger that arrived after the schedule: each of them really ran,
    so each of them gets a run row. None of them may add a second row to a slot ledger that has
    to behave like a set — that extra row is exactly what "the lane observed the same interval
    twice" looks like to a reader, and it is a duplicate by construction.
    """
    seen = observer(tmp_path, pipeline=counting_pipeline([], append_per_series=3, series_behind=3))
    first = seen.tick(observed_at_ms=INSTANT)
    seen.pipeline = counting_pipeline([], append_per_series=0, series_behind=0)
    second = seen.tick(observed_at_ms=INSTANT + 60_000)  # the clock is pinned: same slot
    assert first["outcome"] == AUTO.OBSERVED and first["slot_sealed"] is True
    assert second["slot_key"] == first["slot_key"]
    assert second["outcome"] == AUTO.NO_NEW_DATA
    assert second["slot_sealed"] is False
    assert second["slot_seal_held_by"]["run_id"] == first["run_id"]
    assert second["slot_seal_held_by"]["outcome"] == AUTO.OBSERVED
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 1
    assert len(seen.runs_path.read_text(encoding="utf-8").splitlines()) == 2, (
        "the second tick really ran, so it really gets a row"
    )


def test_the_slot_ledger_can_be_repaired_and_says_what_it_dropped(tmp_path):
    """A duplicate seal that already reached the log is removable, audibly and only once."""
    seen = observer(tmp_path)
    seen.tick(observed_at_ms=INSTANT)
    seal = seen.slots_path.read_text(encoding="utf-8")
    with seen.slots_path.open("a", encoding="utf-8") as handle:
        handle.write(seal)  # a second row for a slot that already carried one
    receipt = seen.dedupe_slots()
    assert receipt["rows_before"] == 2 and receipt["rows_after"] == 1
    assert receipt["dropped"][0]["slot_key"] == AUTO.slot_key(AUTO.slot_of(INSTANT))
    assert receipt["dropped"][0]["outcome"] == AUTO.OBSERVED
    assert receipt["sha256_before"] != receipt["sha256_after"]
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 1
    again = seen.dedupe_slots()
    assert again["dropped"] == []
    assert again["sha256_before"] == again["sha256_after"], "a clean ledger is left byte for byte"
    assert (tmp_path / "state" / "slot_ledger_repair.json").is_file()


def test_a_repeat_tick_does_not_rewrite_the_days_slot_entry(tmp_path):
    """The day file has to agree with the slot ledger, so the seal's numbers survive a re-run.

    A repeat tick inside a drained slot really measured something, and that measurement is kept —
    under ``last_repeat``. What it may not do is replace the slot's entry with its own, because
    that entry is the one the slot ledger seals, and the two artefacts would then disagree about
    the same interval.
    """
    seen = observer(tmp_path, pipeline=counting_pipeline([], append_per_series=3, series_behind=3))
    first = seen.tick(observed_at_ms=INSTANT)
    seen.pipeline = counting_pipeline([], append_per_series=0, series_behind=0)
    seen.tick(observed_at_ms=INSTANT)
    day = json.loads(seen.daily_path(AUTO.day_key(INSTANT)).read_text(encoding="utf-8"))
    entry = day["slots"][first["slot_key"]]
    assert first["outcome"] == AUTO.OBSERVED and first["new_bars"] == 3 * len(SERIES)
    assert entry["outcome"] == AUTO.OBSERVED
    assert entry["new_bars"] == first["new_bars"], "the re-run overwrote the numbers the seal names"
    assert entry["repeats"] == 1
    assert entry["last_repeat"]["outcome"] == AUTO.NO_NEW_DATA
    assert day["ticks"] == 2, "both ticks ran, so both are counted"
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_day_that_disagrees_with_the_ledger_is_corrected_by_the_next_tick(tmp_path):
    """The day's slot table is derived from the seal, so a day written wrong is repaired later.

    Nothing exotic is needed to produce the wrong day: an older rule that let whoever wrote last
    own the interval is enough, and it is exactly what a manual re-run produced here. The next
    tick rebuilds the table from the ledger, and the interval the seal names wins.
    """
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=counting_pipeline([], append_per_series=3, series_behind=3))
    first = seen.tick(observed_at_ms=INSTANT)
    path = seen.daily_path(AUTO.day_key(INSTANT))
    day = json.loads(path.read_text(encoding="utf-8"))
    day["slots"][first["slot_key"]] = {
        "outcome": AUTO.NO_NEW_DATA,
        "new_bars": 0,
        "expected": 0,
        "missing": 0,
        "market_requests": 1,
        "at_utc": "2026-01-01T00:00:00Z",
    }
    path.write_text(json.dumps(day, sort_keys=True), encoding="utf-8")
    clock.advance_to(INSTANT + QUARTER)
    seen.tick(observed_at_ms=INSTANT + QUARTER)
    repaired = json.loads(path.read_text(encoding="utf-8"))["slots"][first["slot_key"]]
    assert repaired["outcome"] == AUTO.OBSERVED
    assert repaired["new_bars"] == first["new_bars"]
    assert repaired["expected"] == first["expected_new_bars"]
    assert repaired["market_requests"] == first["market_requests"], "the seal's own cost"
    assert repaired["missing"] == 0
    # And the derivation is stable: a second pass changes nothing.
    before = path.read_text(encoding="utf-8")
    clock.advance_to(INSTANT + 2 * QUARTER)
    seen.tick(observed_at_ms=INSTANT + 2 * QUARTER)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(before)["slots"][first["slot_key"]] == after["slots"][first["slot_key"]]


def test_the_snapshot_is_the_whole_state_root_and_not_a_curated_subset(tmp_path):
    """A snapshot that omits a lane file is a smaller tree than the reading describes.

    The budget check compares the reading against the snapshot, so a curated copy would fail it
    for a reason that has nothing to do with the lane — and it fails in the direction that looks
    like an inflated reading, which is the worst possible misdiagnosis.
    """
    seen = observer(tmp_path)
    seen.tick(observed_at_ms=INSTANT)
    (tmp_path / "state" / "slot_ledger_repair.json").write_text(
        json.dumps({"dropped": []}), encoding="utf-8"
    )
    out = tmp_path / "snap"
    copied = seen.snapshot(out)
    root = tmp_path / "state"
    live = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    }
    assert set(copied) == live
    assert "slot_ledger_repair.json" in copied, "a lane file the list forgot"
    manifest = json.loads((out / "SNAPSHOT.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == live
    assert sum(body["bytes"] for body in manifest["files"].values()) == sum(
        (root / name).stat().st_size for name in live
    )


def test_the_budget_reading_covers_the_tree_the_tick_left_behind(tmp_path):
    """The reading carries the tick's own row: a measurement that excludes its record is not one."""
    seen = observer(tmp_path)
    seen.tick(observed_at_ms=INSTANT)
    budget = json.loads(seen.budget_path.read_text(encoding="utf-8"))
    measured = int(budget["measured"]["lane_bytes"])
    tree = int(seen.sample_trees()["lane"])
    carriers = sum(
        (tmp_path / "state" / name).stat().st_size
        for name in ("health.json", "resource_budget.json")
    )
    delta = tree - measured
    assert delta >= 0, "the published reading is larger than the tree that holds it"
    assert delta <= carriers, (
        f"the reading is {delta} bytes below the tree, more than the {carriers} bytes written "
        "after it"
    )


def test_the_next_slot_is_observed_again(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=fake_pipeline())
    first = seen.tick(observed_at_ms=INSTANT, due_only=True)
    clock.advance_to(INSTANT + QUARTER)
    second = seen.tick(observed_at_ms=INSTANT + QUARTER, due_only=True)
    assert first["slot_key"] != second["slot_key"]
    assert second["outcome"] == AUTO.OBSERVED
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 2


def test_a_tick_with_nothing_new_is_a_recorded_result_not_a_failure(tmp_path):
    seen = observer(tmp_path, pipeline=counting_pipeline([], append_per_series=0, series_behind=0))
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.NO_NEW_DATA
    assert record["exit_code"] == AUTO.EXIT_OK
    assert record["new_bars"] == 0
    assert record["expected_new_bars"] == 0 and record["missing_bars"] == 0
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 1


# --------------------------------------------------------------------------- one writer
def test_two_triggers_at_once_leave_the_second_untouched(tmp_path):
    calls: list[dict[str, Any]] = []
    seen = observer(tmp_path, pipeline=counting_pipeline(calls))
    held = seen.lease().acquire(now=INSTANT // 1000)
    assert held["acquired"] is True
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.ALREADY_RUNNING
    assert record["exit_code"] == AUTO.EXIT_ALREADY_RUNNING
    assert record["market_requests"] == 0
    assert calls == [], "the second trigger ran the pipeline anyway"
    assert not seen.slots_path.exists(), "a refused tick consumed a slot"


def test_a_lease_left_by_a_crashed_tick_is_reclaimed(tmp_path):
    """The age rule decides, not a pid probe: this platform cannot always answer one."""
    seen = observer(tmp_path, pipeline=counting_pipeline([]), lease_stale_seconds=60)
    (tmp_path / "state" / "lock").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "lock" / "CAMPAIGN_LOCK.json").write_text(
        json.dumps(
            {
                "lease_version": "CAMPAIGN_LEASE_V1",
                "campaign_id": "EDGE04_FORWARD_OBSERVER",
                "pid": 999_999,
                "host": "gone",
                "acquired_at": (INSTANT // 1000) - 3600,
                "renewed_at": (INSTANT // 1000) - 3600,
                "stale_after_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["lease"]["status"] == "STALE_LEASE_RECLAIMED"
    assert record["outcome"] == AUTO.OBSERVED
    assert record["lease_release"]["released"] is True


def test_a_crashed_write_is_counted_and_the_lane_still_runs(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=fake_pipeline())
    seen.tick(observed_at_ms=INSTANT)
    with seen.runs_path.open("a", encoding="utf-8") as handle:
        handle.write('{"run_id": "FWD-EDGE04-torn", "outcome": "OBSERV')  # a killed append
    clock.advance_to(INSTANT + QUARTER)
    record = seen.tick(observed_at_ms=INSTANT + QUARTER)
    assert record["corrupt_log_lines"] == 1
    assert record["outcome"] == AUTO.OBSERVED


def test_a_restart_after_a_crash_does_not_duplicate_a_bar(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(
        tmp_path,
        clock=clock,
        pipeline=counting_pipeline([], append_per_series=3, series_behind=3),
    )
    first = seen.tick(observed_at_ms=INSTANT)
    seen.pipeline = counting_pipeline([], append_per_series=0, series_behind=0)
    clock.advance_to(INSTANT + QUARTER)
    after_restart = seen.tick(observed_at_ms=INSTANT + QUARTER)
    assert first["new_bars"] == 18
    assert after_restart["new_bars"] == 0
    assert after_restart["outcome"] == AUTO.NO_NEW_DATA


# --------------------------------------------------------------------------- honest failures
def test_a_provider_that_answers_nothing_is_not_a_success(tmp_path):
    seen = observer(tmp_path, pipeline=counting_pipeline([], error_series=len(SERIES)))
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.PROVIDER_UNAVAILABLE
    assert record["exit_code"] == AUTO.EXIT_PROVIDER_UNAVAILABLE
    assert not seen.slots_path.exists(), "a tick that observed nothing consumed a slot"
    assert any(alert["kind"] == "PROVIDER_UNAVAILABLE" for alert in record["alerts"])


def test_bars_that_closed_while_the_observer_was_down_are_recovered(tmp_path):
    """The next tick fetches from the stored high-water mark: a gap in ticks is not a gap in
    the store. Three spans behind, three bars per series, nothing missing."""
    seen = observer(tmp_path, pipeline=counting_pipeline([], append_per_series=3, series_behind=3))
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["expected_new_bars"] == 18
    assert record["missing_bars"] == 0
    assert record["outcome"] == AUTO.OBSERVED


def test_a_hole_the_venue_returned_is_named_as_missing(tmp_path):
    seen = observer(tmp_path, pipeline=counting_pipeline([], append_per_series=0, series_behind=3))
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.MISSING_BARS
    assert record["exit_code"] == AUTO.EXIT_INCOMPLETE_COLLECTION
    assert record["missing_bars"] == 18
    assert record["expected_new_bars"] == 18
    assert not seen.slots_path.exists(), "a short collection consumed a slot"
    assert any(alert["kind"] == "MISSING_BARS" for alert in record["alerts"])


def test_a_feed_whose_market_instant_is_behind_is_named_stale(tmp_path):
    """A tick reading an instant behind its own store is not an observation: the store has not
    moved, and the reading is of a stale market."""
    stale_at = INSTANT - 9 * HOUR
    seen = observer(tmp_path, pipeline=counting_pipeline([], append_per_series=0, series_behind=0))
    record = seen.tick(observed_at_ms=stale_at)
    assert record["market_instant_utc"] == AUTO.stamp(stale_at)
    assert record["outcome"] == AUTO.STALE_DATA
    assert record["exit_code"] == AUTO.EXIT_INCOMPLETE_COLLECTION
    assert record["stale_series"] == sorted(f"{tf}:{sym}" for tf, sym in SERIES)
    assert any(alert["kind"] == "STALE_DATA" for alert in record["alerts"])


def test_a_pipeline_that_fails_once_is_retried_after_the_declared_delay(tmp_path):
    """The declared retry, exercised: one more attempt after RETRY_DELAY_SECONDS, then the record."""
    attempts = {"n": 0}
    calls: list[dict[str, Any]] = []
    sleeps: list[float] = []

    def flaky(**call: Any) -> dict[str, Any]:
        calls.append(call)
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("scripted: the socket dropped mid-fetch")
        return fake_payload(observed_at_ms=int(call["observed_at_ms"]))

    seen = observer(tmp_path, pipeline=flaky, sleep=lambda seconds: sleeps.append(seconds))
    record = seen.tick(observed_at_ms=INSTANT, mode=AUTO.MODE_SCHEDULED)
    assert record["outcome"] == AUTO.OBSERVED and record["exit_code"] == AUTO.EXIT_OK
    assert AUTO.MAX_PIPELINE_ATTEMPTS == 2, "the declared retry budget moved"
    assert record["attempts"] == 2 and len(calls) == 2
    assert sleeps == [AUTO.RETRY_DELAY_SECONDS], "the retry did not wait the declared delay"
    # Both attempts are one tick: the slot was consumed once, not once per attempt.
    assert len(seen.slots_path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_runtime_exception_is_recorded_and_the_lease_is_freed(tmp_path):
    def explode(**kwargs: Any) -> dict[str, Any]:
        raise ValueError("scripted runtime failure")

    seen = observer(tmp_path, pipeline=explode)
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.RUNTIME_EXCEPTION
    assert record["exit_code"] == AUTO.EXIT_ERROR
    assert record["attempts"] == AUTO.MAX_PIPELINE_ATTEMPTS
    assert record["error_class"] == "ValueError"
    assert record["lease_release"]["released"] is True
    assert not (tmp_path / "state" / "lock" / "CAMPAIGN_LOCK.json").exists()


def test_a_moved_ruleset_is_a_refusal_not_a_warning(tmp_path, monkeypatch):
    seen = observer(tmp_path)
    monkeypatch.setitem(FP.FROZEN_PARAMS["edge_intra_01"], "resistance_lookback", 21)
    store_before = seen.stored_by_series()
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.VERIFICATION_FAILED
    assert record["exit_code"] == AUTO.EXIT_VERIFICATION_FAILED
    assert record["error_class"] == "ASSERTION"
    assert seen.stored_by_series() == store_before
    assert any(alert["kind"] == "VERIFICATION_FAILED" for alert in record["alerts"])


# --------------------------------------------------------------------------- resource policy
def test_a_critical_volume_stops_the_tick_before_any_request(tmp_path):
    calls: list[dict[str, Any]] = []
    seen = observer(tmp_path, pipeline=counting_pipeline(calls), critical_bytes=10**15)
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.DISK_BUDGET_EXCEEDED
    assert record["exit_code"] == AUTO.EXIT_DISK_BUDGET_EXCEEDED
    assert record["market_requests"] == 0
    assert calls == []
    assert record["disk"]["critical_free_bytes"] == 10**15
    assert record["disk"]["status"] == "CRITICAL"


def test_a_warning_volume_ingests_and_pauses_the_publication(tmp_path):
    seen = observer(
        tmp_path,
        pipeline=counting_pipeline([]),
        warning_bytes=10**15,
        critical_bytes=1,
    )
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["outcome"] == AUTO.OBSERVED
    assert record["publication"]["ran"] is False
    assert record["publication"]["paused"] is True
    assert record["health_status"] == "DEGRADED"
    assert any(alert["kind"] == "PUBLICATION_PAUSED" for alert in record["alerts"])
    assert not (seen.publication_dir / "LATEST.json").exists()


def test_a_healthy_volume_publishes_and_reports_its_budget(tmp_path):
    seen = observer(tmp_path, pipeline=counting_pipeline([]))
    record = seen.tick(observed_at_ms=INSTANT)
    assert record["publication"]["ran"] is True
    assert record["publication"]["staged_then_swapped"] is True
    assert (seen.publication_dir / "LATEST.json").is_file()
    budget = json.loads(seen.budget_path.read_text(encoding="utf-8"))
    assert budget["measured"]["lane_bytes"] > 0
    assert budget["over_budget"] is False
    assert budget["policy"]["critical"].startswith("below")
    assert budget["growth"]["status"] in ("UNKNOWN", "MEASURED", "STATIONARY", "VOLATILE")
    health = json.loads(seen.health_path.read_text(encoding="utf-8"))
    assert health["last_tick"]["run_id"] == record["run_id"]


def test_a_growth_rate_is_a_rate_and_not_a_thousandfold_underestimate(tmp_path):
    """The stamp's unit is named, converted once, and a foreign unit is dropped and counted.

    A sample stamped in milliseconds and read as seconds turns a per-second rate into a per-day
    one: a lane that grows megabytes a day would be forecast at kilobytes a day, and the
    resource budget would say the volume lasts decades. This test is that arithmetic.
    """
    seen = observer(tmp_path, sleep=lambda seconds: None)
    seen.state_root.mkdir(parents=True, exist_ok=True)
    seen.budget_path.write_text(
        json.dumps(
            {
                "samples": [
                    {"ts_ms": INSTANT - HOUR, "bytes": 900_000},
                    {"ts_ms": INSTANT, "bytes": 1_000_000},
                    {"ts_ms": INSTANT + HOUR, "bytes": 1_100_000},
                    {"ts_ms": INSTANT + 2 * HOUR, "bytes": 1_200_000},
                    {"ts": INSTANT - 2 * HOUR, "bytes": 800_000},
                ]
            }
        ),
        encoding="utf-8",
    )
    reading = seen.budget_reading(now_ms=INSTANT + 2 * HOUR)
    growth = reading["growth"]
    assert growth["status"] == "MEASURED"
    assert growth["bytes_per_day"] == 2_400_000.0, "100 KB an hour is 2.4 MB a day"
    assert growth["samples"] == 4, "the foreign-unit sample was mixed into the rate"
    assert growth["interval_seconds"] == [3_600.0, 3_600.0, 3_600.0]
    assert growth["dropped_foreign_unit_samples"] == 1
    assert "unit_reading" in growth


def test_each_tick_names_the_unit_of_its_own_sample(tmp_path):
    seen = observer(tmp_path, clock=Clock(INSTANT), pipeline=counting_pipeline([]))
    seen.tick(observed_at_ms=INSTANT, mode=AUTO.MODE_SCHEDULED)
    budget = json.loads(seen.budget_path.read_text(encoding="utf-8"))
    sample = budget["samples"][-1]
    assert sample["ts_ms"] == INSTANT and "ts" not in sample


def test_the_publication_cadence_holds_until_it_is_due(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=fake_pipeline())
    first = seen.tick(observed_at_ms=INSTANT)
    clock.advance_to(INSTANT + QUARTER)
    second = seen.tick(observed_at_ms=INSTANT + QUARTER)
    clock.advance_to(INSTANT + 2 * QUARTER)
    third = seen.tick(observed_at_ms=INSTANT + 2 * QUARTER, force_publication=True)
    assert first["publication"]["ran"] is True
    assert second["publication"]["ran"] is False
    assert "cadence" in second["publication"]["reason"]
    assert third["publication"]["ran"] is True


def test_a_publication_interrupted_mid_write_leaves_no_half_report(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=fake_pipeline(), stub=False)
    seen.publish = lambda payload: stub_publish(seen, payload)  # type: ignore[method-assign]
    seen.tick(observed_at_ms=INSTANT)
    pointer_before = (seen.publication_dir / "LATEST.json").read_bytes()

    def half_write(payload: dict[str, Any]) -> dict[str, Path]:
        staging = seen.publication_dir / ".staging-torn"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "HALF_WRITTEN.md").write_text("torn", encoding="utf-8")
        raise OSError("scripted interruption while publishing")

    seen.publish = half_write  # type: ignore[method-assign]
    clock.advance_to(INSTANT + QUARTER)
    record = seen.tick(observed_at_ms=INSTANT + QUARTER, force_publication=True)
    assert record["outcome"] == AUTO.RUNTIME_EXCEPTION
    assert "evidence" in record["outcome_reason"] or "publishing" in record["outcome_reason"]
    assert not list(seen.publication_dir.glob(".staging-*")), "the staging tree survived"
    assert (seen.publication_dir / "LATEST.json").read_bytes() == pointer_before
    assert not (seen.publication_dir / "HALF_WRITTEN.md").exists()


def test_the_bounded_logs_are_bounded_and_the_daily_evidence_is_not(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(
        tmp_path,
        clock=clock,
        pipeline=fake_pipeline(),
        runs_kept=3,
        slots_kept=3,
        ledger_kept=2,
    )
    for step in range(6):
        at = INSTANT + step * QUARTER
        clock.advance_to(at)
        seen.tick(observed_at_ms=at)
    runs = seen.runs_path.read_text(encoding="utf-8").splitlines()
    slots = seen.slots_path.read_text(encoding="utf-8").splitlines()
    ledger = (
        seen.ledger_path.read_text(encoding="utf-8").splitlines()
        if seen.ledger_path.exists()
        else []
    )
    daily = seen.daily_path(AUTO.day_key(INSTANT))
    assert len(runs) == 3 and len(slots) == 3 and len(ledger) <= 2
    assert daily.is_file(), "the day's evidence file was pruned with the operational logs"
    assert json.loads(daily.read_text(encoding="utf-8"))["ticks"] == 6
    record = json.loads(runs[-1])
    # Truncation happens before the append, so the last tick dropped exactly one row.
    assert record["pruned_rows"].get("runs") == 1


def test_the_health_reading_blocks_after_the_declared_run_of_failures(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock, pipeline=counting_pipeline([], error_series=len(SERIES)))
    raised: list[dict[str, Any]] = []
    record: dict[str, Any] = {}
    for step in range(AUTO.BLOCKED_AFTER_CONSECUTIVE_FAILURES + 1):
        at = INSTANT + step * QUARTER
        clock.advance_to(at)
        record = seen.tick(observed_at_ms=at)
        raised.extend(record["alerts"])
    assert record["outcome"] == AUTO.PROVIDER_UNAVAILABLE
    assert record["health_status"] == "BLOCKED"
    blocked = [alert for alert in raised if alert["kind"] == "HEALTH_BLOCKED"]
    # An alert is a transition, not a heartbeat: the streak raises it once.
    assert len(blocked) == 1 and blocked[0]["severity"] == "CRITICAL"
    healed_at = INSTANT + 20 * QUARTER
    clock.advance_to(healed_at)
    seen.pipeline = counting_pipeline([])
    healed = seen.tick(observed_at_ms=healed_at)
    assert healed["outcome"] == AUTO.OBSERVED
    assert healed["health_status"] in ("HEALTHY", "DEGRADED")
    assert any(alert["kind"] == "HEALTH_RECOVERED" for alert in healed["alerts"])


def test_a_second_trigger_in_one_slot_does_not_read_as_a_failure_to_observe(tmp_path):
    """The schedule firing twice in a slot is the schedule working, not the feed failing."""
    clock = Clock(INSTANT)
    calls: list[dict[str, Any]] = []
    # The disk floors are pinned out of the way: this test is about the alert vocabulary, and a
    # host whose volume happens to be low must not be able to turn its assertions green or red.
    seen = observer(
        tmp_path,
        clock=clock,
        pipeline=counting_pipeline(calls),
        warning_bytes=1,
        critical_bytes=1,
    )
    first = seen.tick(observed_at_ms=INSTANT, mode=AUTO.MODE_SCHEDULED)
    assert first["outcome"] == AUTO.OBSERVED and first["health_status"] == "HEALTHY"
    clock.advance_to(INSTANT + 60_000)
    second = seen.tick(observed_at_ms=INSTANT + 60_000, due_only=True, mode=AUTO.MODE_SCHEDULED)
    assert second["outcome"] == AUTO.ALREADY_OBSERVED
    assert second["market_requests"] == 0 and len(calls) == 1, "a second trigger spent a request"
    assert second["health_status"] == "HEALTHY", "a no-op trigger degraded the health reading"
    assert second["alerts"] == [], "a no-op trigger raised an alarm"
    reading = json.loads(seen.health_path.read_text(encoding="utf-8"))
    assert reading["consecutive_non_observations"] == 0


def test_a_degraded_tick_is_announced_as_degraded_and_only_a_real_recovery_as_one(tmp_path):
    clock = Clock(INSTANT)
    failing = observer(
        tmp_path,
        clock=clock,
        pipeline=counting_pipeline([], error_series=len(SERIES)),
        warning_bytes=1,
        critical_bytes=1,
    )
    failed = failing.tick(observed_at_ms=INSTANT, mode=AUTO.MODE_SCHEDULED)
    assert failed["outcome"] == AUTO.PROVIDER_UNAVAILABLE
    assert failed["health_status"] == "DEGRADED"
    kinds = [alert["kind"] for alert in failed["alerts"]]
    assert "HEALTH_DEGRADED" in kinds and "HEALTH_RECOVERED" not in kinds
    assert "HEALTH_BLOCKED" not in kinds, "one empty tick is not a blocked lane"
    failing.pipeline = counting_pipeline([])
    clock.advance_to(INSTANT + QUARTER)
    healed = failing.tick(observed_at_ms=INSTANT + QUARTER, mode=AUTO.MODE_SCHEDULED)
    assert healed["health_status"] == "HEALTHY"
    assert [a["kind"] for a in healed["alerts"]] == ["HEALTH_RECOVERED"]
    clock.advance_to(INSTANT + 2 * QUARTER)
    steady = failing.tick(observed_at_ms=INSTANT + 2 * QUARTER, mode=AUTO.MODE_SCHEDULED)
    assert steady["health_status"] == "HEALTHY" and steady["alerts"] == [], (
        "a healthy tick after a healthy tick is not news"
    )


def test_silence_raises_one_alert_per_episode_and_a_replay_raises_none(tmp_path):
    clock = Clock(INSTANT)
    seen = observer(tmp_path, clock=clock)
    seen.tick(observed_at_ms=INSTANT, mode=AUTO.MODE_SCHEDULED)
    late = INSTANT + 45 * 60_000
    clock.advance_to(late)
    gap = seen.tick(observed_at_ms=late, mode=AUTO.MODE_SCHEDULED)
    opened = [a for a in gap["alerts"] if a["kind"] == "OBSERVATION_GAP"]
    assert len(opened) == 1 and opened[0]["severity"] == "WARNING"
    assert opened[0]["silence_minutes"] == 45.0
    persisted = json.loads(seen.alerts_path.read_text(encoding="utf-8").splitlines()[-1])
    assert persisted["kind"] == "OBSERVATION_GAP" and persisted["order_sent"] is False
    assert persisted["hypothetical"] is True
    # A rerun of a slot behind the newest observation is a replay, not silence.
    clock.advance_to(late + 60_000)
    replay = seen.tick(observed_at_ms=INSTANT, due_only=True, mode=AUTO.MODE_MANUAL)
    assert replay["outcome"] == AUTO.ALREADY_OBSERVED and replay["alerts"] == []
    # The lane catches up, then goes quiet again: the second episode is announced too.
    clock.advance_to(late + QUARTER)
    caught_up = seen.tick(observed_at_ms=late + QUARTER, mode=AUTO.MODE_SCHEDULED)
    quiet = [a for a in caught_up["alerts"] if a["kind"].startswith("OBSERVATION")]
    assert quiet == [], "the closed episode stayed open"
    stalled_at = late + QUARTER + 4 * HOUR
    clock.advance_to(stalled_at)
    stalled = seen.tick(observed_at_ms=stalled_at, mode=AUTO.MODE_SCHEDULED)
    kinds = [a["kind"] for a in stalled["alerts"] if a["kind"].startswith("OBSERVATION")]
    assert kinds == ["OBSERVATION_STALLED"], "a four-hour silence is an interruption"
    stalled_alert = next(a for a in stalled["alerts"] if a["kind"] == "OBSERVATION_STALLED")
    assert stalled_alert["severity"] == "CRITICAL" and stalled_alert["silence_minutes"] == 240.0


# --------------------------------------------------------------------------- coverage rules
def test_expected_closed_bars_is_the_grid_and_not_the_wall_clock():
    span = HOUR
    high = FROZEN_1H_END
    assert (
        AUTO.expected_closed_bars(high_water_ms=high, span_ms=span, observed_at_ms=high + 2 * span)
        == 1
    )
    assert (
        AUTO.expected_closed_bars(
            high_water_ms=high, span_ms=span, observed_at_ms=high + span + 30_000
        )
        == 0
    )
    assert (
        AUTO.expected_closed_bars(high_water_ms=high, span_ms=span, observed_at_ms=high + 24 * span)
        == 23
    )
    assert AUTO.expected_closed_bars(high_water_ms=high, span_ms=span, observed_at_ms=high) == 0


def test_a_backfilled_day_is_not_an_observation_day():
    """The first tick backfilled months of bars; none of those days is an observation."""
    span = HOUR
    day_start = 1_791_000_000_000 - (1_791_000_000_000 % 86_400_000)

    def rows(lag_ms: int, count: int = 24):
        return [
            {
                "ts": day_start + index * span,
                "fetched_at_ms": day_start + index * span + span + lag_ms,
            }
            for index in range(count)
        ]

    series = {f"1h:{asset}": rows(30 * 60_000) for asset in ("BTC", "ETH", "SOL")}
    timeframes = {key: "1h" for key in series}
    live = AUTO.prospective_days(
        stored_by_series=series, timeframes=timeframes, primary_assets=("BTC", "ETH", "SOL")
    )
    assert live["prospectively_observed"] == 1, live
    assert live["densely_covered_but_backfilled"] == 0

    late = {key: rows(30 * 24 * HOUR) for key in series}
    backfilled = AUTO.prospective_days(
        stored_by_series=late, timeframes=timeframes, primary_assets=("BTC", "ETH", "SOL")
    )
    assert backfilled["prospectively_observed"] == 0
    assert backfilled["densely_covered_but_backfilled"] == 1
    assert backfilled["days"][0]["class"] == "DENSE_BUT_BACKFILLED"

    thin = {key: rows(30 * 60_000, count=12) for key in series}
    incomplete = AUTO.prospective_days(
        stored_by_series=thin, timeframes=timeframes, primary_assets=("BTC", "ETH", "SOL")
    )
    assert incomplete["prospectively_observed"] == 0
    assert incomplete["days"][0]["class"] == "INCOMPLETE"


def test_a_partially_observed_day_does_not_count(tmp_path):
    """One asset half missing is not a day the portfolio could have been observed on."""
    span = HOUR
    day = "2026-10-13"
    start = int(
        __import__("datetime").datetime(2026, 10, 13, tzinfo=__import__("datetime").UTC).timestamp()
        * 1000
    )

    def series(count: int):
        return [
            {"ts": start + index * span, "fetched_at_ms": start + index * span + span + 60_000}
            for index in range(count)
        ]

    stored = {"1h:BTC": series(24), "1h:ETH": series(24), "1h:SOL": series(10)}
    reading = AUTO.prospective_days(
        stored_by_series=stored,
        timeframes={key: "1h" for key in stored},
        primary_assets=("BTC", "ETH", "SOL"),
    )
    assert reading["prospectively_observed"] == 0
    assert reading["days"][0]["day"] == day
    assert reading["days"][0]["coverage"]["1h:SOL"] < 0.90


def test_the_coverage_artefact_declares_the_freeze_and_the_floor(tmp_path):
    seen = observer(tmp_path, pipeline=counting_pipeline([]))
    seen.tick(observed_at_ms=INSTANT)
    coverage = json.loads(seen.coverage_path.read_text(encoding="utf-8"))
    assert coverage["required_days"] == FP.MIN_OBSERVATION_DAYS
    assert coverage["coverage_required"] == FP.OBSERVATION_COVERAGE
    assert coverage["freeze"]["frozen_1h_end_utc"] == AUTO.stamp(FP.FROZEN_1H_END_MS)
    assert coverage["freeze"]["frozen_15m_end_utc"] == AUTO.stamp(FP.FROZEN_15M_END_MS)
    assert coverage["primary_series"] == ["1h:BTC", "1h:ETH", "1h:SOL"]
    assert coverage["promotion"] == "NONE"
    assert "not an observation" in coverage["not_counted"]
    assert coverage["store_root"].endswith("store")


def test_reading_a_log_with_a_torn_line_counts_it(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\nnot json\n{"a": 2}\n', encoding="utf-8")
    rows, corrupt = AUTO.read_jsonl(path)
    assert [row["a"] for row in rows] == [1, 2]
    assert corrupt == 1


def test_pruning_a_log_that_is_within_its_cap_changes_nothing(tmp_path):
    path = tmp_path / "log.jsonl"
    AUTO.append_jsonl(path, {"a": 1})
    assert AUTO.prune_jsonl(path, 5) == 0
    assert len(AUTO.read_jsonl(path)[0]) == 1


# --------------------------------------------------------------------------- the real lane
def scripted_source(*, bars: int = 8, step: int = HOUR, start: int = FROZEN_1H_END + HOUR):
    rows = {
        asset: [kline(start + index * step, 100.0 + index) for index in range(bars)]
        for asset in ("BTC", "ETH", "SOL")
    }
    return ScriptedKlineSource(rows_by_symbol=rows, server_time=start + bars * step)


def real_pipeline(**kwargs: Any) -> dict[str, Any]:
    return RUN.run_forward_observation(**{**kwargs, "scenarios": ("BASE",), "sweep_cases": 4})


def real_observer(
    tmp_path: Path, *, clock: Clock | None = None, **kwargs: Any
) -> AUTO.ForwardObserver:
    # Same as ``observer``: the volume is pinned HEALTHY so this host's free space is not a hidden
    # input to a test that is about the observation, not about the disk policy.
    kwargs.setdefault("warning_bytes", 1)
    kwargs.setdefault("critical_bytes", 1)
    return AUTO.ForwardObserver(
        repo_root=tmp_path,
        state_root=tmp_path / "state",
        store_root=tmp_path / "store",
        pipeline=real_pipeline,
        sleep=lambda seconds: None,
        clock=clock or Clock(INSTANT),
        **kwargs,
    )


def test_the_tick_drives_the_frozen_pipeline_and_pins_the_ruleset(tmp_path):
    """The observer calls the same callable the WP-EDGE-03 tests drive, over a scripted venue."""
    source = scripted_source()
    now = source.server_time
    seen = real_observer(tmp_path, clock=Clock(now))
    record = seen.tick(source=source, observed_at_ms=now)
    assert record["outcome"] == AUTO.OBSERVED
    assert record["new_bars"] == 24, record
    assert record["ruleset"]["params_hash"] == FP.assert_frozen_params()["params_hash"]
    assert record["ruleset"]["agrees_with_publication"] is True
    assert record["parity_verdict"] == "PARITY_PASS"
    assert record["hypothetical_net_usdt"] is not None
    assert record["lease_release"]["released"] is True
    assert len(record["expectation_series"]) == 6
    coverage = json.loads(seen.coverage_path.read_text(encoding="utf-8"))
    assert coverage["store_digests"]["1h:BTC"]
    # One run cannot observe a whole day prospectively: the scripted venue stamps every bar
    # with this run's instant, so only the bars that had just closed are live. The rule
    # itself is exercised by the dedicated coverage tests; here what matters is that a day
    # was recorded with a class and a coverage the reader can recompute.
    assert coverage["days"], coverage
    assert coverage["prospectively_observed"] == len(coverage["prospectively_observed_days"])
    assert coverage["days"][-1]["class"] in (
        "INCOMPLETE",
        "DENSE_BUT_BACKFILLED",
        "PROSPECTIVELY_OBSERVED",
    )
    daily = json.loads(seen.daily_path(AUTO.day_key(now)).read_text(encoding="utf-8"))
    assert daily["day_hashes"]["1h:BTC"]


def test_the_observer_is_reproducible_from_scratch(tmp_path):
    def run_once(root: Path) -> dict[str, Any]:
        source = scripted_source()
        now = source.server_time
        seen = real_observer(root, clock=Clock(now))
        return seen.tick(source=source, observed_at_ms=now)

    first = run_once(tmp_path / "a")
    second = run_once(tmp_path / "b")
    assert first["decisions_digest"] == second["decisions_digest"]
    assert first["new_bars"] == second["new_bars"]
    assert first["store"]["series"] == second["store"]["series"]
    assert first["outcome"] == second["outcome"] == AUTO.OBSERVED
    assert first["expectation_series"] == second["expectation_series"]


def test_the_reports_re_render_offline_from_the_preserved_observation(tmp_path):
    """A report is a reading of a stored observation, so it must not need the venue."""
    script = load_script("scripts/edge04_observer.py")
    source = scripted_source()
    now = source.server_time
    seen = real_observer(tmp_path, clock=Clock(now))
    record = seen.tick(source=source, observed_at_ms=now, force_publication=True)
    assert record["publication"]["ran"] is True
    outdir = tmp_path / "rerender"
    code = script._report_only(outdir, publication=seen.publication_dir, compare=True)
    assert code == 0, "the re-rendered reports differ from the published ones"
    assert (outdir / "CUMULATIVE.md").is_file()
    assert (outdir / f"DAILY_{AUTO.day_key(now)}.md").is_file()


def test_the_entrypoint_registers_the_declared_task_and_flags():
    script = load_script("scripts/edge04_observer.py")
    assert script.TASK_NAME == "TradingAgentic-EDGE04-Forward"
    assert script._arguments().endswith("--scheduled --due")
    dry = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "edge04_observer.py"), "--install", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert dry.returncode == 0, dry.stderr
    body = json.loads(dry.stdout)
    assert body["task_name"] == script.TASK_NAME
    assert "--scheduled --due" in body["arguments"]
    assert "edge04_observer.py" in body["arguments"]


def test_the_task_definition_the_installer_writes_carries_the_safety_settings():
    """The observer's task is the supervisor's XML: IgnoreNew, start-when-available, one hour."""
    supervisor = load_script("scripts/cap004_supervisor.py")
    xml = supervisor.build_task_xml(
        start_boundary="2026-10-13T00:00:00",
        interval_minutes=15,
        user_id="DOMAIN\\user",
        command="python.exe",
        arguments='"edge04_observer.py" --scheduled --due',
        working_dir="C:\\repo",
        author="test",
    )
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<Interval>PT15M</Interval>" in xml
    assert "<ExecutionTimeLimit>PT1H</ExecutionTimeLimit>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "edge04_observer.py" in xml


@pytest.mark.slow
def test_the_independent_verifier_accepts_a_live_state_and_its_sabotages_are_detected(tmp_path):
    """The verifier reads the artefacts, not the code, and its sabotage self-test is paid for."""
    verifier = load_script("scripts/edge04_verify.py")
    install = tmp_path / "install.json"
    install.write_text(
        json.dumps(
            {
                "schema_version": "EDGE04_TICK_V1",
                "task_name": "TradingAgentic-EDGE04-Forward",
                "installed": True,
                "enabled": True,
                "interval_minutes": 15,
                "arguments": f'"{ROOT.as_posix()}/scripts/edge04_observer.py" --scheduled --due',
                "task": {"installed": True, "enabled": True, "state": "Ready"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    source = scripted_source()
    now = source.server_time
    seen = real_observer(tmp_path, clock=Clock(now))
    record = seen.tick(source=source, observed_at_ms=now, force_publication=True)
    assert record["publication"]["ran"] is True
    report = verifier.run_checks(
        verifier.load_bundle(seen.state_root, repo=tmp_path, install=install)
    )
    assert report["verdict"] == "VERIFY_PASS", report["failures"]
    self_test = verifier.self_test(state_root=seen.state_root, repo=tmp_path, install=install)
    assert self_test["detected"] == self_test["applied"], self_test["sabotages"]
    assert self_test["applied"] + self_test["skipped"] == len(verifier._sabotages())
    assert self_test["undetected"] == 0
    assert self_test["verdict"] == "SELF_TEST_PASS", self_test
