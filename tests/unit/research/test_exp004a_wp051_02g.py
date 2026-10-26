"""WP-051-02G: the incremental capture must earn every bar it keeps.

The phase-2 extractor writes a dataset once, so a mid-window capture froze fourteen bars of a
two-thousand-bar promise for ever. The mechanism these tests describe removes that ceiling without
loosening anything: a day is captured when it has closed, into a shard that is never rewritten, and
the declaration's own denominator decides whether coverage may be called complete.

Every test here is an attempt to make the package say more than it holds. A shard that remembers a
day and holds another; a manifest that calls a late bar admissible; a shard published before its
last bar closed; a repetition that rewrites evidence; an interruption that leaves half a file; a
consolidation that repairs instead of reporting; a rehearsal that leaks into the phase's coverage.
None of them may end in a pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import exp004a_wp051_02g_capture as builder  # noqa: E402
import exp004a_wp051_02g_verify as verifier  # noqa: E402

from trading_bot.research.prospective import incremental as engine  # noqa: E402

HOUR = 3_600_000
DAY = 86_400_000
STORE_START = "2026-01-01T00:00:00Z"
WINDOW_START = "2026-01-03T00:00:00Z"
WINDOW_END = "2026-01-05T00:00:00Z"
REHEARSAL_START = "2026-01-01T00:00:00Z"
REHEARSAL_END = "2026-01-02T00:00:00Z"
#: A clock after the window has closed, so that "the day has not finished yet" is not the reason a
#: plan is refused in most tests.
AS_OF = "2026-01-07T00:00:00Z"

CAPTURE = REPO / "scripts" / "exp004a_wp051_02g_capture.py"
VERIFY = REPO / "scripts" / "exp004a_wp051_02g_verify.py"


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def all_opens(start: str, end: str, interval: str = "1h") -> list[int]:
    span = engine.INTERVAL_MS[interval]
    return list(range(ms(start), ms(end), span))


# --------------------------------------------------------------------------- #
# a world
# --------------------------------------------------------------------------- #


@dataclass
class World:
    """A synthetic repository: a forward store, a declaration, and a capture root."""

    root: Path
    declaration_path: Path
    declaration: engine.Declaration
    stores: dict[str, Path]

    @property
    def capture_root(self) -> Path:
        return self.root / "capture"

    @property
    def rehearsal_root(self) -> Path:
        return self.root / "rehearsal"

    @property
    def out(self) -> Path:
        return self.root / "out"

    def shard(self, day: str, asset: str = "BTC", interval: str = "1h") -> tuple[Path, Path]:
        base = self.capture_root / f"{interval}_{asset}" / day
        return base.with_suffix(".jsonl"), base.with_suffix(".MANIFEST.json")

    def rehabilitation_shard(self, day: str, asset: str = "BTC") -> tuple[Path, Path]:
        base = self.rehearsal_root / f"1h_{asset}" / day
        return base.with_suffix(".jsonl"), base.with_suffix(".MANIFEST.json")


def _row(open_ms: int, *, lag_ms: int = 60_000, closed: bool = True, interval: str = "1h") -> bytes:
    span = engine.INTERVAL_MS[interval]
    record = {
        "ts": open_ms,
        "interval": interval,
        "closed": closed,
        "fetched_at_ms": open_ms + span + lag_ms,
        "open": "100.0",
        "high": "101.0",
        "low": "99.0",
        "close": "100.5",
        "payload_sha256": f"{open_ms:x}",
    }
    return json.dumps(record).encode("utf-8") + b"\n"


def make_world(
    root: Path,
    *,
    assets: tuple[str, ...] = ("BTC",),
    start: str = WINDOW_START,
    end: str = WINDOW_END,
    lag_ms: int = 60_000,
    lag_bound_ms: int = 2 * HOUR,
    coverage_required: float = 0.9,
    omit: tuple[int, ...] = (),
    overrides: dict[int, bytes] | None = None,
    rehearsal: bool = True,
    rehearsal_counts: bool = False,
    granularity: str = "UTC_DAY",
    row_count: int | None = None,
    extra_entry: dict[str, Any] | None = None,
    store_missing: bool = False,
) -> World:
    """Build a store and a declaration that name each other.

    The declaration is the authority for everything: window, timeframe, denominator, lag bound. The
    store is only ever data. When the two disagree the declaration wins and the disagreement is the
    test.
    """
    store_dir = root / "data" / "forward" / "1h"
    store_dir.mkdir(parents=True, exist_ok=True)
    stores: dict[str, Path] = {}
    for asset in assets:
        path = store_dir / f"{asset}.jsonl"
        rows = []
        for open_ms in all_opens(STORE_START, end):
            if open_ms in omit and asset == assets[0]:
                continue
            rows.append((overrides or {}).get(open_ms) or _row(open_ms, lag_ms=lag_ms))
        if not store_missing:
            path.write_bytes(b"".join(rows))
        stores[asset] = path

    declaration_path = root / "config" / "preregistrations" / "EXP-004A-test.json"
    declaration_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for asset in assets:
        entries.append(
            {
                "dataset_id": f"EXP-004A-TEST-1H-{asset}",
                "asset": asset,
                "timeframe": "1h",
                "source_path": f"data/forward/1h/{asset}.jsonl",
                "period_start_utc": start,
                "period_end_utc": end,
                "row_count": row_count if row_count is not None else len(all_opens(start, end)),
                "generator_parameters": {
                    "lag_bound_ms": lag_bound_ms,
                    "coverage_required": coverage_required,
                },
                "generator_command": "python scripts/exp004a_wp051_02g_capture.py --once",
            }
        )
    if extra_entry is not None:
        entries.append(extra_entry)
    document: dict[str, Any] = {
        "declaration_id": "EXP-004A.datasets.test/v1",
        "experiment_id": "EXP-004A",
        "phase": 3,
        "schema_version": "1.0",
        "governance_status": "AUTHORIZED_FOR_CAPTURE",
        "effective_from_utc": start,
        "capture_window": {"start_utc": start, "end_utc": end},
        "lag_policy": {
            "definition": "lag_ms = fetched_at_ms - (ts + interval_ms)",
            "action": "a day holding a bar outside [0, lag_bound_ms] is quarantined",
        },
        "shard_policy": {"granularity": granularity, "write_once": True},
        "shard_root": "capture",
        "entries": entries,
    }
    if rehearsal:
        document["rehearsal"] = {
            "start_utc": REHEARSAL_START,
            "end_utc": REHEARSAL_END,
            "counts_toward_coverage": rehearsal_counts,
            "shard_root": "rehearsal",
            "note": "one day of the same store, historical, non-prospective",
        }
    declaration_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return World(
        root=root,
        declaration_path=declaration_path,
        declaration=engine.load_declaration(declaration_path),
        stores=stores,
    )


def plan_for(world: World, *, at: str = AS_OF, rehearsal: bool = False) -> engine.PlanSummary:
    entries, start, end, _ = engine.resolve_window(world.declaration, rehearsal=rehearsal)
    return engine.capture_plan(entries, at_ms=ms(at), window_start_ms=start, window_end_ms=end)


def capture_all(world: World, *, at: str = AS_OF, rehearsal: bool = False) -> list[Any]:
    entries, start, end, counts = engine.resolve_window(world.declaration, rehearsal=rehearsal)
    summary = engine.capture_plan(entries, at_ms=ms(at), window_start_ms=start, window_end_ms=end)
    written = []
    cache: dict[Path, Any] = {}
    for plan in summary.of(engine.SHARD_CAPTURED):
        index = cache.get(plan.entry.source)
        if index is None:
            from trading_bot.research.prospective.store import index_series

            index = index_series(plan.entry.source, plan.entry.asset, plan.entry.interval)
            cache[plan.entry.source] = index
        written.append(
            engine.write_shard(
                plan.entry,
                plan,
                index=index,
                declaration=world.declaration,
                at_ms=ms(at),
                capture_id="capture/test",
                prospective=not rehearsal,
                counts_toward_coverage=counts,
                generator={"script": "test", "script_sha256": "0" * 64, "argv": []},
            )
        )
    return written


def consolidate(world: World, *, at: str = AS_OF, rehearsal: bool = False) -> engine.Consolidation:
    entries, start, _, counts = engine.resolve_window(world.declaration, rehearsal=rehearsal)
    return engine.consolidate(
        entries,
        at_ms=ms(at),
        prospective=not rehearsal,
        counts_toward_coverage=counts,
        window_start_ms=start,
    )


def run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=environment,
    )


# --------------------------------------------------------------------------- #
# the contract itself
# --------------------------------------------------------------------------- #


def test_the_grid_comes_from_the_window_and_the_timeframe_not_from_the_store(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    entry = world.declaration.entries[0]
    assert entry.declared_rows == 48
    assert entry.declared_days == 2
    assert len(engine.expected_opens(entry.period_start_ms, entry.period_end_ms, HOUR)) == 48
    engine.shard_paths(entry, "2026-01-04")[0].unlink(missing_ok=True)
    assert engine.shard_days(entry.period_start_ms, entry.period_end_ms, HOUR) == (
        "2026-01-03",
        "2026-01-04",
    )


def test_a_declared_row_count_that_contradicts_the_window_is_refused(tmp_path: Path) -> None:
    with pytest.raises(engine.DeclarationError, match="denominator is not negotiable"):
        make_world(tmp_path, row_count=49)


def test_a_declaration_without_a_lag_bound_is_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    document = json.loads(world.declaration_path.read_text(encoding="utf-8"))
    document["entries"][0]["generator_parameters"] = {"coverage_required": 0.9}
    world.declaration_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(engine.DeclarationError, match="lag bound"):
        engine.load_declaration(world.declaration_path)


def test_a_shard_granularity_other_than_a_day_is_refused(tmp_path: Path) -> None:
    with pytest.raises(engine.DeclarationError, match="not supported"):
        make_world(tmp_path, granularity="HOUR")


def test_an_entry_that_leaves_the_declared_window_is_refused(tmp_path: Path) -> None:
    with pytest.raises(engine.DeclarationError, match="leaves the declared capture window"):
        make_world(
            tmp_path,
            extra_entry={
            "dataset_id": "EXP-004A-TEST-OUTSIDE",
            "asset": "ETH",
            "timeframe": "1h",
            "source_path": "data/forward/1h/BTC.jsonl",
            "period_start_utc": WINDOW_START,
            "period_end_utc": "2026-01-06T00:00:00Z",
                "generator_parameters": {"lag_bound_ms": 7_200_000},
            },
        )


def test_a_rehearsal_that_counts_toward_coverage_is_refused(tmp_path: Path) -> None:
    with pytest.raises(engine.DeclarationError, match="may not count toward coverage"):
        make_world(tmp_path, rehearsal_counts=True)


# --------------------------------------------------------------------------- #
# capture, idempotence, conflict
# --------------------------------------------------------------------------- #


def test_a_capture_writes_one_shard_per_day_holding_the_stores_own_lines(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    written = capture_all(world)
    assert [item.day for item in written] == ["2026-01-03", "2026-01-04"]
    store_lines = world.stores["BTC"].read_bytes().splitlines(keepends=True)
    day_lines = [
        line
        for line in store_lines
        if ms("2026-01-03T00:00:00Z") <= json.loads(line)["ts"] < ms("2026-01-04T00:00:00Z")
    ]
    day_one = world.shard("2026-01-03")[0].read_bytes()
    assert len(day_lines) == 24
    assert day_one == b"".join(day_lines)
    manifest = json.loads(world.shard("2026-01-03")[1].read_text(encoding="utf-8"))
    assert manifest["sha256"] == engine.hashlib.sha256(day_one).hexdigest()
    assert manifest["row_count"] == 24
    assert manifest["admissible"] is True
    assert manifest["counts_toward_coverage"] is True
    assert manifest["prospective"] is True


def test_a_second_capture_writes_nothing_and_changes_nothing(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    before = {path.name: path.stat().st_mtime_ns for path in world.capture_root.rglob("*") if path.is_file()}
    summary = plan_for(world)
    assert summary.counts() == {engine.SHARD_ALREADY_HELD: 2}
    assert capture_all(world) == []
    after = {path.name: path.stat().st_mtime_ns for path in world.capture_root.rglob("*") if path.is_file()}
    assert before == after


def test_a_shard_whose_bytes_contradict_its_manifest_is_a_conflict_not_a_rewrite(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    data_path, manifest_path = world.shard("2026-01-03")
    original = data_path.read_bytes()
    tampered = original.replace(b'"100.5"', b'"999.5"', 1)
    assert tampered != original
    data_path.write_bytes(tampered)
    summary = plan_for(world)
    assert summary.counts() == {engine.SHARD_CONFLICT: 1, engine.SHARD_ALREADY_HELD: 1}
    assert data_path.read_bytes() == tampered, "the capture did not repair the shard behind our back"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["sha256"] != engine.hashlib.sha256(
        tampered
    ).hexdigest()


def test_a_payload_without_a_manifest_is_never_adopted(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    data_path, manifest_path = world.shard("2026-01-04")
    manifest_path.unlink()
    summary = plan_for(world)
    conflicts = [plan for plan in summary.plans if plan.action == engine.SHARD_CONFLICT]
    assert len(conflicts) == 1
    from trading_bot.research.prospective.store import index_series

    with pytest.raises(engine.ShardConflict):
        engine.write_shard(
            conflicts[0].entry,
            conflicts[0],
            index=index_series(conflicts[0].entry.source, "BTC", "1h"),
            declaration=world.declaration,
            at_ms=ms(AS_OF),
            capture_id="capture/test",
            prospective=True,
            counts_toward_coverage=True,
            generator={},
        )
    assert data_path.is_file(), "the orphan payload was left exactly where it was found"
    assert not manifest_path.exists()


def test_an_interrupted_write_leaves_nothing_visible_and_resume_removes_the_partial(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path)
    data_path, _ = world.shard("2026-01-03")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    partial = data_path.with_name(data_path.name + ".part")
    partial.write_bytes(b'{"ts": 1, "fetched_at_ms": 2}\n')
    assert plan_for(world).counts() == {engine.SHARD_CAPTURED: 2}
    removed = engine.recover_partials(world.capture_root)
    assert removed and removed[0].endswith(".part")
    assert not partial.exists()
    assert not data_path.exists()
    written = capture_all(world)
    assert [item.day for item in written] == ["2026-01-03", "2026-01-04"]


# --------------------------------------------------------------------------- #
# the clock
# --------------------------------------------------------------------------- #


def test_a_day_whose_last_bar_has_not_closed_is_never_published(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    summary = plan_for(world, at="2026-01-04T12:00:00Z")
    actions = {(plan.day, plan.action) for plan in summary.plans}
    assert ("2026-01-03", engine.SHARD_CAPTURED) in actions
    assert ("2026-01-04", engine.SHARD_INCOMPLETE) in actions
    written = capture_all(world, at="2026-01-04T12:00:00Z")
    assert [item.day for item in written] == ["2026-01-03"]


def test_a_bar_that_opens_at_the_capture_instant_is_a_future_bar(tmp_path: Path) -> None:
    """A shard hand-built for a day that has not started must be inadmissible, not "captured"."""
    from trading_bot.research.prospective.store import index_series

    world = make_world(tmp_path)
    entry = world.declaration.entries[0]
    plan = engine.Plan(
        entry,
        "2026-01-04",
        engine.SHARD_CAPTURED,
        "crafted by the test",
        engine.day_opens("2026-01-04", HOUR),
    )
    shard = engine.write_shard(
        entry,
        plan,
        index=index_series(entry.source, "BTC", "1h"),
        declaration=world.declaration,
        at_ms=ms("2026-01-04T00:00:00Z"),
        capture_id="capture/test",
        prospective=True,
        counts_toward_coverage=True,
        generator={},
    )
    codes = {defect["code"] for defect in shard.manifest["defects"]}
    assert engine.DEFECT_FUTURE in codes
    assert shard.manifest["admissible"] is False
    assert consolidate(world).admissible_rows == 0


def test_a_missing_bar_makes_the_day_not_due_and_names_the_open(tmp_path: Path) -> None:
    missing = ms("2026-01-04T05:00:00Z")
    world = make_world(tmp_path, omit=(missing,))
    summary = plan_for(world)
    held = [plan for plan in summary.plans if plan.day == "2026-01-04"]
    assert len(held) == 1
    assert held[0].action == engine.SHARD_NOT_DUE
    assert held[0].missing == (missing,)
    assert "1 bar(s) not in the store" in held[0].reason


# --------------------------------------------------------------------------- #
# the lag policy
# --------------------------------------------------------------------------- #


def test_a_late_bar_quarantines_its_day_and_never_reaches_the_dataset(tmp_path: Path) -> None:
    late_open = ms("2026-01-04T03:00:00Z")
    world = make_world(tmp_path, overrides={late_open: _row(late_open, lag_ms=3 * HOUR)})
    capture_all(world)
    manifest = json.loads(world.shard("2026-01-04")[1].read_text(encoding="utf-8"))
    assert manifest["admissible"] is False
    assert manifest["lag"]["over_bound"] == 1
    assert [defect["code"] for defect in manifest["defects"]] == [engine.DEFECT_LATE]
    result = consolidate(world)
    assert result.admissible_rows == 24
    assert [item.quarantined for item in result.slices] == [("2026-01-04",)]
    assert result.status == engine.COVERAGE_BELOW_DECLARED
    dataset = result.slices[0].payload
    assert dataset.count(b"\n") == 24
    assert str(ms("2026-01-04T03:00:00Z")).encode() not in dataset


def test_a_bar_stored_before_it_closed_is_a_forged_timestamp(tmp_path: Path) -> None:
    open_ms = ms("2026-01-03T04:00:00Z")
    world = make_world(tmp_path, overrides={open_ms: _row(open_ms, lag_ms=-HOUR)})
    capture_all(world)
    manifest = json.loads(world.shard("2026-01-03")[1].read_text(encoding="utf-8"))
    assert manifest["admissible"] is False
    assert engine.DEFECT_NEGATIVE_LAG in {defect["code"] for defect in manifest["defects"]}
    assert consolidate(world).status == engine.COVERAGE_BELOW_DECLARED


def test_a_bar_the_store_says_is_not_closed_blocks_the_day(tmp_path: Path) -> None:
    open_ms = ms("2026-01-03T09:00:00Z")
    world = make_world(tmp_path, overrides={open_ms: _row(open_ms, closed=False)})
    summary = plan_for(world)
    incomplete = [plan for plan in summary.plans if plan.action == engine.SHARD_INCOMPLETE]
    assert incomplete and incomplete[0].day == "2026-01-03"


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #


def test_coverage_never_completes_while_a_day_is_missing_even_above_the_required_fraction(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path, coverage_required=0.4)
    written = capture_all(world)
    world.shard("2026-01-04")[0].unlink()
    world.shard("2026-01-04")[1].unlink()
    assert len(written) == 2
    result = consolidate(world)
    assert result.admissible_rows == 24
    assert result.declared_rows == 48
    assert result.fraction == pytest.approx(0.5)
    assert result.fraction >= result.required_fraction, "the floor is met and the dataset is still short"
    assert result.status == engine.COVERAGE_BELOW_DECLARED
    assert {defect["code"] for defect in result.defects} == {engine.DEFECT_MISSING_DAY}


def test_coverage_completes_only_when_every_declared_bar_is_admissible(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    result = consolidate(world)
    assert result.admissible_rows == result.declared_rows == 48
    assert result.status == engine.COVERAGE_COMPLETE


def test_before_the_window_opens_the_status_is_pending_and_not_complete(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    result = consolidate(world, at="2025-12-31T00:00:00Z")
    assert result.status == engine.COVERAGE_PENDING_WINDOW_OPEN


def test_a_rehearsal_that_is_complete_leaves_the_phase_pending(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world, rehearsal=True)
    rehearsal = consolidate(world, rehearsal=True)
    phase = consolidate(world)
    assert rehearsal.status == engine.COVERAGE_COMPLETE
    assert rehearsal.counts_toward_coverage is False
    assert phase.admissible_rows == 0
    # An elapsed day with no shard is a hole, not a pending coincidence: either word is honest,
    # the complete one is not.
    assert phase.status in (engine.COVERAGE_PENDING, engine.COVERAGE_BELOW_DECLARED)
    assert phase.status != engine.COVERAGE_COMPLETE


def test_a_rehearsal_shard_is_stamped_non_prospective(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world, rehearsal=True)
    manifest = json.loads(world.rehabilitation_shard("2026-01-01")[1].read_text(encoding="utf-8"))
    assert manifest["prospective"] is False
    assert manifest["counts_toward_coverage"] is False
    assert not world.capture_root.exists()


# --------------------------------------------------------------------------- #
# consolidation
# --------------------------------------------------------------------------- #


def test_consolidation_is_deterministic_in_the_shard_bytes(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    first = consolidate(world)
    second = consolidate(world, at="2026-01-09T00:00:00Z")
    assert first.slices[0].payload == second.slices[0].payload
    assert engine.hashlib.sha256(first.slices[0].payload).hexdigest() == engine.hashlib.sha256(
        second.slices[0].payload
    ).hexdigest()


def test_a_tampered_shard_is_excluded_and_named(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    data_path, _ = world.shard("2026-01-03")
    payload = bytearray(data_path.read_bytes())
    payload[10] ^= 0xFF
    data_path.write_bytes(bytes(payload))
    result = consolidate(world)
    assert result.admissible_rows == 24
    assert engine.DEFECT_SHARD_DIGEST in {defect["code"] for defect in result.defects}
    assert result.status == engine.COVERAGE_BELOW_DECLARED


def test_a_second_day_holding_the_first_days_bars_is_reported_as_gap_and_duplicate(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path)
    capture_all(world)
    day_one_payload = world.shard("2026-01-03")[0].read_bytes()
    data_path, manifest_path = world.shard("2026-01-04")
    data_path.write_bytes(day_one_payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = engine.hashlib.sha256(day_one_payload).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    result = consolidate(world)
    codes = {defect["code"] for defect in result.defects}
    assert engine.DEFECT_GAP in codes
    assert engine.DEFECT_DUPLICATE in codes
    assert result.status == engine.COVERAGE_BELOW_DECLARED


def test_a_shard_claiming_coverage_inside_a_rehearsal_is_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    capture_all(world, rehearsal=True)
    _, manifest_path = world.rehabilitation_shard("2026-01-01")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts_toward_coverage"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    result = consolidate(world, rehearsal=True)
    assert engine.DEFECT_REHEARSAL_IN_COVERAGE in {defect["code"] for defect in result.defects}
    assert result.status == engine.COVERAGE_BELOW_DECLARED


# --------------------------------------------------------------------------- #
# the builder as a process
# --------------------------------------------------------------------------- #


def test_the_builder_captures_and_reports_without_certifying(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    completed = run(
        CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)
    )
    assert completed.returncode == builder.EXIT_OK, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["state"] == builder.STATE_CAPTURE_COMPLETE
    assert payload["shards_written"] == 2
    assert payload["coverage"]["status"] == engine.COVERAGE_COMPLETE
    report = json.loads(
        (world.out / "evidence" / payload["run_id"] / "RUN_REPORT.json").read_text(encoding="utf-8")
    )
    assert report["certifiable"] is False
    assert report["gates"]["orders_placed"] == "0"
    assert report["gates"]["certification"] == "NOT_CLAIMED_BY_BUILDER"
    assert report["prospective"] is True


def test_a_repeated_tick_writes_no_shard_and_says_so(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    first = run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out))
    second = run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out))
    assert first.returncode == builder.EXIT_OK
    assert second.returncode == builder.EXIT_PENDING, second.stderr
    payload = json.loads(second.stdout)
    assert payload["shards_written"] == 0
    assert payload["state"] == builder.STATE_NOT_DUE


def test_resume_reports_the_shards_it_found_healthy_and_rewrites_none(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out))
    digest = engine.hashlib.sha256(world.shard("2026-01-03")[0].read_bytes()).hexdigest()
    completed = run(
        CAPTURE, "--resume", "--declaration", str(world.declaration_path), "--out", str(world.out)
    )
    assert completed.returncode == builder.EXIT_PENDING, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["state"] == builder.STATE_RESUMED
    report = json.loads(
        (world.out / "evidence" / payload["run_id"] / "RUN_REPORT.json").read_text(encoding="utf-8")
    )
    reconciliation = report["reconciliation"]
    assert reconciliation["shards_seen"] == 2
    assert reconciliation["healthy"] == 2
    assert reconciliation["conflicts"] == []
    assert engine.hashlib.sha256(world.shard("2026-01-03")[0].read_bytes()).hexdigest() == digest


def test_check_writes_nothing_at_all(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    before = sorted(path.as_posix() for path in world.root.rglob("*"))
    completed = run(CAPTURE, "--check", "--declaration", str(world.declaration_path), "--out", str(world.out))
    after = sorted(path.as_posix() for path in world.root.rglob("*"))
    assert completed.returncode == builder.EXIT_OK, completed.stderr
    assert before == after
    payload = json.loads(completed.stdout)
    assert payload["phase"]["coverage"]["status"] in (
        engine.COVERAGE_PENDING,
        engine.COVERAGE_BELOW_DECLARED,
    )
    assert payload["phase"]["coverage"]["admissible_rows"] == 0
    assert payload["state_present"] is False


def test_the_scheduler_runs_a_bounded_number_of_ticks(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    completed = run(
        CAPTURE,
        "--schedule",
        "--max-ticks",
        "2",
        "--interval-seconds",
        "0",
        "--declaration",
        str(world.declaration_path),
        "--out",
        str(world.out),
    )
    assert completed.returncode in (builder.EXIT_OK, builder.EXIT_PENDING), completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ticks"] == 2
    assert len(payload["exit_codes"]) == 2
    state = json.loads(
        (world.capture_root / "state" / "scheduler.json").read_text(encoding="utf-8")
    )
    assert len(state["runs"]) == 2
    assert state["slices"]["1h:BTC"]["days"] == ["2026-01-03", "2026-01-04"]


def _hold_the_lock_for_a_moment(path: Path) -> None:
    with builder.Lock(path):
        pass


def test_the_lock_refuses_a_second_concurrent_capture(tmp_path: Path) -> None:
    path = tmp_path / "state" / "capture.lock"
    with builder.Lock(path), pytest.raises(builder.LockHeld):
        _hold_the_lock_for_a_moment(path)


def test_an_abandoned_lock_is_taken_over_and_the_takeover_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "state" / "capture.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": 1, "acquired_at_utc": "2020-01-01T00:00:00Z"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(path, (old, old))
    with builder.Lock(path) as lock:
        assert lock.taken_over is not None
        assert lock.taken_over["age_seconds"] > 900


def test_two_attempts_never_share_a_run_id() -> None:
    at_ms = 1_767_225_600_000
    ids = {builder.new_run_id(at_ms) for _ in range(50)}
    assert len(ids) == 50


# --------------------------------------------------------------------------- #
# the verifier as a process
# --------------------------------------------------------------------------- #


def _verify(world: World, run_id: str, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    out = world.root / f"verdict-{run_id}.json"
    completed = run(
        VERIFY,
        "--claim",
        str(world.out / "evidence" / run_id / "RUN_REPORT.json"),
        "--declaration",
        str(world.declaration_path),
        "--repo",
        str(REPO),
        "--out",
        str(out),
        *extra,
    )
    return completed, json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}


def test_the_independent_verifier_reproduces_a_complete_capture(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_PASS, (completed.stdout, completed.stderr)
    assert verdict["verdict"] == "PASS_COVERAGE_COMPLETE"
    assert verdict["certification_allowed"] is True
    assert verdict["certification_blocked_by"] is None
    assert verdict["experiment_certified"] is False
    assert verdict["coverage"]["admissible_rows"] == 48
    names = {check["name"] for check in verdict["checks"] if check["ok"]}
    assert {
        "DECLARATION_SHA256",
        "DECLARATION_ARITHMETIC",
        "COVERAGE_RECOMPUTED",
        "CONSOLIDATED_IS_THE_SHARDS",
        "NO_DUPLICATE_OPENS",
        "TEMPORAL_POLICY_IN_THE_DATASET",
        "QUARANTINE_IS_DISCLOSED",
        "GENERATOR_CONSISTENT",
        "GENERATOR_BLOB_RECORDED",
        "BUILDER_DID_NOT_CERTIFY",
        "VERIFIER_IS_INDEPENDENT",
        "FROZEN_PACKAGES_INTACT",
    } <= names


def test_the_verifier_refuses_to_call_an_incomplete_capture_a_pass(tmp_path: Path) -> None:
    """The second day has not closed yet when the capture runs, so half the window is missing."""
    world = make_world(tmp_path)
    captured = json.loads(
        run(
            CAPTURE,
            "--once",
            "--as-of",
            "2026-01-04T12:00:00Z",
            "--declaration",
            str(world.declaration_path),
            "--out",
            str(world.out),
        ).stdout
    )
    assert captured["coverage"]["status"] == engine.COVERAGE_BELOW_DECLARED
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_INCOMPLETE
    assert verdict["verdict"] == "PASS_COVERAGE_INCOMPLETE"
    assert verdict["coverage"]["status"] == engine.COVERAGE_BELOW_DECLARED
    assert verdict["coverage"]["admissible_rows"] == 24
    assert verdict["coverage"]["declared_rows"] == 48
    assert verdict["certification_allowed"] is False
    assert verdict["independent_verification"] == "PASS"


def test_a_published_shard_removed_after_the_claim_makes_the_verifier_fail(tmp_path: Path) -> None:
    """Evidence that changes underneath the reader is a failure, not an update."""
    world = make_world(tmp_path)
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    world.shard("2026-01-04")[0].unlink()
    world.shard("2026-01-04")[1].unlink()
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert "CONSOLIDATED_IS_THE_SHARDS" in verdict["failed_checks"]
    assert verdict["certification_allowed"] is False


def test_the_verifier_and_the_builder_agree_on_the_coverage_word(tmp_path: Path) -> None:
    world = make_world(tmp_path, overrides={ms("2026-01-04T03:00:00Z"): _row(ms("2026-01-04T03:00:00Z"), lag_ms=3 * HOUR)})
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    assert captured["coverage"]["status"] == engine.COVERAGE_BELOW_DECLARED
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_INCOMPLETE
    assert verdict["coverage"]["status"] == engine.COVERAGE_BELOW_DECLARED
    assert verdict["coverage"]["admissible_rows"] == 24


def test_the_verifier_fails_a_shard_whose_bytes_no_longer_hash_to_its_manifest(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path)
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    data_path, _ = world.shard("2026-01-03")
    payload = bytearray(data_path.read_bytes())
    payload[12] ^= 0x01
    data_path.write_bytes(bytes(payload))
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert verdict["verdict"] == "FAIL"
    assert "SHARD_BYTES_MATCH_MANIFESTS" in verdict["failed_checks"]


def test_the_verifier_fails_a_manifest_that_calls_an_inadmissible_day_admissible(
    tmp_path: Path,
) -> None:
    late = ms("2026-01-04T03:00:00Z")
    world = make_world(tmp_path, overrides={late: _row(late, lag_ms=3 * HOUR)})
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    _, manifest_path = world.shard("2026-01-04")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["admissible"] is False
    manifest["admissible"] = True
    manifest["defects"] = []
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert "QUARANTINE_IS_DISCLOSED" in verdict["failed_checks"]


def test_the_verifier_fails_a_shard_published_before_its_last_bar_closed(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    _, manifest_path = world.shard("2026-01-03")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["captured_at_utc"] = "2026-01-01T12:00:00.000Z"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert "TEMPORAL_POLICY_IN_THE_DATASET" in verdict["failed_checks"]


def test_the_verifier_fails_a_shard_written_under_another_declaration(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    _, manifest_path = world.shard("2026-01-03")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["declaration"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert verdict["verdict"] == "FAIL"


def test_the_verifier_accepts_a_rehearsal_and_never_lets_it_move_the_phase(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    captured = json.loads(
        run(
            CAPTURE,
            "--once",
            "--rehearsal",
            "--declaration",
            str(world.declaration_path),
            "--out",
            str(world.out),
        ).stdout
    )
    assert captured["rehearsal"] is True
    completed, verdict = _verify(world, captured["run_id"], "--rehearsal")
    assert completed.returncode == verifier.EXIT_PASS, (completed.stdout, verdict.get("failed_checks"))
    assert verdict["verdict"] == "PASS_COVERAGE_COMPLETE"
    assert verdict["prospective"] is False
    assert verdict["coverage"]["declared_rows"] == 24
    assert verdict["certification_allowed"] is False
    assert verdict["certification_blocked_by"] == "REHEARSAL_IS_NOT_EVIDENCE"
    assert verdict["experiment_certified"] is False


def test_the_verifier_does_not_let_the_rehearsal_move_the_phase(tmp_path: Path) -> None:
    """Twenty-four verified rehearsal rows exist on disk and the phase still has none."""
    world = make_world(tmp_path)
    rehearsal = json.loads(
        run(
            CAPTURE,
            "--once",
            "--rehearsal",
            "--declaration",
            str(world.declaration_path),
            "--out",
            str(world.out),
        ).stdout
    )
    assert rehearsal["coverage"]["status"] == engine.COVERAGE_COMPLETE
    phase = json.loads(
        run(
            CAPTURE,
            "--once",
            "--as-of",
            "2025-12-31T00:00:00Z",
            "--declaration",
            str(world.declaration_path),
            "--out",
            str(world.out),
        ).stdout
    )
    assert phase["shards_written"] == 0
    assert phase["coverage"]["status"] == engine.COVERAGE_PENDING_WINDOW_OPEN
    completed, verdict = _verify(world, phase["run_id"], "--as-of", "2025-12-31T00:00:00Z")
    assert verdict["coverage"]["declared_rows"] == 48
    assert verdict["coverage"]["admissible_rows"] == 0
    assert verdict["coverage"]["status"] == engine.COVERAGE_PENDING_WINDOW_OPEN
    assert completed.returncode == verifier.EXIT_INCOMPLETE
    assert verdict["certification_allowed"] is False


def test_the_verifier_fails_two_different_generators_in_one_package(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    _, manifest_path = world.shard("2026-01-04")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capture"]["generator"]["script_sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert "GENERATOR_CONSISTENT" in verdict["failed_checks"]


def test_the_verifier_checks_the_programs_against_the_declaration(tmp_path: Path) -> None:
    """The declaration names a commit and three blobs; a different program must fail the control."""
    world = make_world(tmp_path)
    document = json.loads(world.declaration_path.read_text(encoding="utf-8"))
    document["generator"] = {
        "program": "scripts/exp004a_wp051_02g_capture.py",
        "engine": "src/trading_bot/research/prospective/incremental.py",
        "verifier": "scripts/exp004a_wp051_02g_verify.py",
        "code_commit": "0" * 40,
        "program_blob": "0" * 40,
        "verifier_blob": "0" * 40,
        "engine_block": "0" * 40,
    }
    world.declaration_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    world = World(
        root=world.root,
        declaration_path=world.declaration_path,
        declaration=engine.load_declaration(world.declaration_path),
        stores=world.stores,
    )
    captured = json.loads(
        run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out)).stdout
    )
    completed, verdict = _verify(world, captured["run_id"])
    assert completed.returncode == verifier.EXIT_FAIL
    assert "GENERATOR_BLOB_RECORDED" in verdict["failed_checks"]


def test_the_verifier_is_a_separate_implementation(tmp_path: Path) -> None:
    source = VERIFY.read_text(encoding="utf-8")
    assert "incremental" not in source.split('"""', 2)[2].split("\n\n", 1)[1] or "incremental" not in [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert not any(
        line.startswith(("import trading_bot", "from trading_bot"))
        for line in source.splitlines()
    )
    assert "exp004a_wp051_02g_capture" not in [
        line.split()[1] for line in source.splitlines() if line.startswith(("import ", "from "))
    ]


def test_the_builder_names_no_way_to_trade() -> None:
    source = CAPTURE.read_text(encoding="utf-8")
    for token in ("create_order", "binance_order", "api_key", "secret_key", "private_key"):
        assert token not in source


def test_the_builder_never_claims_a_verification(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    completed = run(CAPTURE, "--once", "--declaration", str(world.declaration_path), "--out", str(world.out))
    payload = json.loads(completed.stdout)
    report = json.loads(
        (world.out / "evidence" / payload["run_id"] / "RUN_REPORT.json").read_text(encoding="utf-8")
    )
    assert report["state"] != "CAPTURED_VERIFIED"
    assert report["state"] in {
        builder.STATE_CAPTURE_COMPLETE,
        builder.STATE_PENDING_DATA,
        builder.STATE_NOT_DUE,
        builder.STATE_PENDING_WINDOW_OPEN,
    }
    assert "CAPTURED_VERIFIED" not in json.dumps(report)
