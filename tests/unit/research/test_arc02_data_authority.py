"""ARC-02 data-authority tests.

Fast, hermetic where possible: the projection/manifest/determinism/mutation logic is exercised
on synthetic fixtures, and the checks that need the real 400 MB reused partitions are skipped
automatically when the data root does not carry them (e.g. in a fresh detached worktree).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from trading_bot.research.arc02 import arc02_funding as F
from trading_bot.research.arc02 import arc02_normalize as N
from trading_bot.research.arc02.arc02_authority import (
    COMMON_WINDOW_SPAN_DAYS,
    PARTITION_RELPATH,
    common_causal_window,
    load_partition,
    resolve_partition_dir,
)

REPO = pathlib.Path(__file__).resolve().parents[3]
DOCS = REPO / "docs" / "arc02-data-authority-01"
DATA_OK = resolve_partition_dir().is_dir() and all(
    (resolve_partition_dir() / f"{s}.jsonl").exists() for s in N.ASSETS
)


def _records(n: int = 5, symbol: str = "BTCUSDT") -> list[dict]:
    return [
        {
            "t": 1_700_000_000_000 + i * N.BAR_MS,
            "ct": 1_700_000_000_000 + i * N.BAR_MS + N.BAR_MS - 1,
            "o": str(100 + i),
            "h": str(101 + i),
            "l": str(99 + i),
            "c": str(100.5 + i),
            "v": str(10 + i),
            "qv": str(1000 + i),
            "n": i,
            "tb": str(4 + i),
            "tq": str(400 + i),
            "sym": symbol,
            "ms": "2024-01",
        }
        for i in range(n)
    ]


def test_projection_carries_only_the_admitted_field_set() -> None:
    rows = N.project_records(_records())
    assert set(rows[0]) == {"t", "ct", "o", "c", "sym", "ms"}
    assert set(N.PROJECTED_FIELDS) == {"t", "ct", "o", "c"}
    assert {"h", "l", "v", "qv", "n", "tb", "tq"} == set(N.DROPPED_FIELDS)


def test_projection_is_order_independent_and_deterministic() -> None:
    a = N.project_records(_records())
    b = N.project_records(list(reversed(_records())))
    assert a == b
    payload_a = b"".join(N.canonical_json(r) + b"\n" for r in a)
    payload_b = b"".join(N.canonical_json(r) + b"\n" for r in b)
    assert N.sha256_bytes(payload_a) == N.sha256_bytes(payload_b)


def test_projection_stats_detect_gaps_and_duplicates() -> None:
    rows = N.project_records(_records())
    stats = N.projection_stats(rows)
    assert stats["internal_cadence_breaks"] == 0
    assert stats["duplicate_open_slots"] == 0
    assert stats["monotonic_open_time"] is True
    gapped = rows[:2] + rows[3:]
    assert N.projection_stats(gapped)["internal_cadence_breaks"] == 1
    assert N.projection_stats(rows + [rows[0]])["duplicate_open_slots"] == 1


def test_manifest_identity_excludes_paths_and_is_content_based(tmp_path: pathlib.Path) -> None:
    entries = []
    for symbol in N.ASSETS:
        payload = b"".join(N.canonical_json(r) + b"\n" for r in N.project_records(_records(3, symbol)))
        entries.append(
            {
                "symbol": symbol,
                "source_partition_sha256": N.SOURCE_PARTITION_SHA256[symbol],
                "projection_sha256": N.sha256_bytes(payload),
                **N.projection_stats(N.project_records(_records(3, symbol))),
            }
        )
    m1 = N.build_manifest(entries)
    m2 = N.build_manifest(list(reversed(entries)))
    assert m1["dataset_sha256"] == m2["dataset_sha256"]
    assert str(tmp_path) not in json.dumps(m1)
    assert m1["dataset_sha256"] == N.build_manifest(entries)["dataset_sha256"]


def test_reuse_identity_is_fail_closed(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "BTCUSDT.jsonl").write_bytes(b"".join(N.canonical_json(r) + b"\n" for r in N.project_records(_records())))
    with pytest.raises(ValueError, match="REUSE_IDENTITY_MISMATCH"):
        N.project_symbol("BTCUSDT", source_dir=src, out_dir=tmp_path / "out", write=False)


def test_missing_partition_dir_fails_closed(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_partition("BTCUSDT", partition_dir=tmp_path / "nope")


def test_duplicate_slot_fails_closed(tmp_path: pathlib.Path) -> None:
    row = N.canonical_json({"t": 1, "ct": 2, "o": "1", "c": "1", "sym": "BTCUSDT", "ms": "2024-01"})
    (tmp_path / "BTCUSDT.jsonl").write_bytes(row + b"\n" + row + b"\n")
    with pytest.raises(ValueError, match="CONFLICTING_OR_DUPLICATE_SLOT"):
        load_partition("BTCUSDT", partition_dir=tmp_path)


def test_partition_relpath_is_repo_relative() -> None:
    assert not PARTITION_RELPATH.is_absolute()
    assert str(PARTITION_RELPATH).startswith("data")


def test_funding_reader_fails_closed_on_missing_and_non_monotonic(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        F.load_funding("BTCUSDT", funding_dir=tmp_path)
    row = json.dumps({"funding_time_ms": 10, "funding_rate": "0.001", "funding_interval_hours": 8})
    (tmp_path / "BTCUSDT_funding.jsonl").write_bytes((row + "\n" + row + "\n").encode())
    with pytest.raises(ValueError, match="not strictly monotonic"):
        F.load_funding("BTCUSDT", funding_dir=tmp_path)


def test_funding_cashflow_boundary_semantics() -> None:
    series = F.FundingSeries(
        symbol="ETHUSDT",
        funding_time_ms=(100, 200, 300),
        funding_rate=(0.001, 0.001, 0.001),
        funding_interval_hours=(8, 8, 8),
        sha256="synthetic",
        path="synthetic",
        rows=3,
    )
    assert [t for t, _ in series.settlements_in(100, 300)] == [200, 300]
    assert series.cashflow_return(1, 100, 300) == pytest.approx(-0.002)
    assert series.cashflow_return(-1, 100, 300) == pytest.approx(0.002)


# --------------------------------------------------------------------- data-backed
@pytest.mark.skipif(not DATA_OK, reason="reused ARC-02 partitions not present in this data root")
def test_reused_source_partitions_reproduce_certified_digests() -> None:
    src = resolve_partition_dir().parent / "arc03_klines_5m"
    for symbol, digest in N.SOURCE_PARTITION_SHA256.items():
        assert N.sha256_file(src / f"{symbol}.jsonl") == digest


@pytest.mark.skipif(not DATA_OK, reason="reused ARC-02 partitions not present in this data root")
def test_on_disk_projections_reproduce_recorded_partition_digests() -> None:
    recorded = json.loads((DOCS / "ARC02_DATA_MANIFEST.json").read_text(encoding="utf-8"))["partition_sha256"]
    observed = {s: N.sha256_file(resolve_partition_dir() / f"{s}.jsonl") for s in recorded}
    assert observed == recorded


@pytest.mark.skipif(not DATA_OK, reason="reused ARC-02 partitions not present in this data root")
def test_common_window_matches_recorded_and_frozen_span() -> None:
    partitions = {s: load_partition(s) for s in N.ASSETS}
    window = common_causal_window(partitions)
    recorded = json.loads((DOCS / "ARC02_COMMON_CAUSAL_WINDOW.json").read_text(encoding="utf-8"))
    assert (window["start_ms"], window["end_ms"]) == (recorded["start_ms"], recorded["end_ms"])
    assert window["window_span_days_inclusive"] == COMMON_WINDOW_SPAN_DAYS


@pytest.mark.skipif(not DATA_OK, reason="reused ARC-02 partitions not present in this data root")
def test_funding_partitions_reproduce_certified_arc01_digests() -> None:
    funding_dir = F.resolve_funding_dir()
    for symbol, digest in F.ARC01_FUNDING_PARTITION_SHA256.items():
        assert N.sha256_file(funding_dir / f"{symbol}_funding.jsonl") == digest
