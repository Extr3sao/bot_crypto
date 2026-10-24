"""Tests for the corpus freeze mechanism.

The interesting cases are the refusals: a mechanism that only ever says yes would have
frozen the EXP004A corpus happily, with an open bar at the end, and nobody would have known
until the data was gone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.research.prospective import freeze

HOUR = 3_600_000
#: 2026-10-07T12:00Z, exactly on the hour: the grid check is `ts % interval_ms == 0`, so a
#: fixture that lands mid-hour would be testing the wrong refusal.
NOW = 1_791_374_400_000


def write_shard(root: Path, name: str, stamps: list[int], *, base: float = 100.0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    rows = [[stamp, base, base + 1, base - 1, base + 0.5, 10.0] for stamp in stamps]
    path = root / name
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def corpus(root: Path, *, last_open: int = NOW - 2 * HOUR) -> Path:
    """A two-shard, 1h corpus whose last bar closed two hours before ``NOW``."""
    stamps = [last_open - 2 * HOUR, last_open - HOUR, last_open]
    write_shard(root, "AAAUSDT_1h.json", stamps)
    write_shard(root, "BBBUSDT_1h.json", stamps, base=50.0)
    return root


def frozen(root: Path, **kwargs) -> dict:
    return freeze.freeze(
        root,
        interval="1h",
        source="TEST",
        normalization="list of [ts,open,high,low,close,volume]",
        now_ms=NOW,
        **kwargs,
    )


def test_freeze_records_every_shard_and_a_combined_digest(tmp_path: Path) -> None:
    manifest = frozen(corpus(tmp_path / "corpus"))

    assert manifest["schema_version"] == freeze.SCHEMA_VERSION
    assert sorted(manifest["shards"]) == ["AAAUSDT_1h.json", "BBBUSDT_1h.json"]
    shard = manifest["shards"]["AAAUSDT_1h.json"]
    assert shard["bars"] == 3
    assert shard["last_ts"] + HOUR == shard["last_close_ts"]
    assert manifest["totals"] == {
        "shards": 2,
        "bars": 6,
        "bytes": sum(s["bytes"] for s in manifest["shards"].values()),
    }
    assert (tmp_path / "corpus" / freeze.DEFAULT_MANIFEST_NAME).is_file()
    # The manifest must not describe itself: the digest is over shards only, so writing it
    # cannot move the value it just recorded.
    assert freeze.manifest_digest(manifest["shards"]) == manifest["corpus_digest"]


def test_open_bar_is_refused_with_the_reason_the_loss_taught(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus", last_open=NOW)  # its 1h bar closes at NOW + 1h

    with pytest.raises(freeze.CorpusFreezeError) as caught:
        frozen(root)

    message = str(caught.value)
    assert message.startswith("UNCLOSED_BAR")
    assert "AAAUSDT_1h.json" in message
    assert not (root / freeze.DEFAULT_MANIFEST_NAME).exists()


def test_a_bar_closing_exactly_now_is_accepted(tmp_path: Path) -> None:
    """The boundary is the close instant, not a comfortable margin after it."""
    root = corpus(tmp_path / "corpus", last_open=NOW - HOUR)
    manifest = frozen(root)
    assert manifest["shards"]["AAAUSDT_1h.json"]["last_close_ts"] == NOW


def test_unsorted_or_off_grid_shard_is_refused(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")
    write_shard(root, "CCCUSDT_1h.json", [NOW - 3 * HOUR, NOW - HOUR, NOW - 2 * HOUR])

    with pytest.raises(freeze.CorpusFreezeError, match="BAD_GRID"):
        frozen(root)


def test_missing_expected_shard_is_refused(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")

    with pytest.raises(freeze.CorpusFreezeError, match="MISSING_SHARD"):
        frozen(root, expected_shards=["AAAUSDT_1h.json", "ZZZUSDT_1h.json"])


def test_empty_shard_is_refused(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")
    (root / "CCCUSDT_1h.json").write_text("[]", encoding="utf-8")

    with pytest.raises(freeze.CorpusFreezeError, match="EMPTY_SHARD"):
        frozen(root)


def test_verify_accepts_untouched_bytes_and_names_each_kind_of_drift(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")
    manifest = frozen(root)
    assert freeze.verify(root, manifest=manifest)["ok"] is True

    # 1. a shard's bytes move (the EXP004A-shaped failure)
    path = root / "AAAUSDT_1h.json"
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("100.0", "100.5", 1), encoding="utf-8")
    changed = freeze.verify(root, manifest=manifest)
    assert changed["ok"] is False
    assert changed["problems"][0]["kind"] == "CHANGED"

    # 2. restored, then one shard disappears
    path.write_text(original, encoding="utf-8")
    assert freeze.verify(root, manifest=manifest)["ok"] is True
    (root / "BBBUSDT_1h.json").unlink()
    missing = freeze.verify(root, manifest=manifest)
    assert [p["kind"] for p in missing["problems"]] == ["MISSING"]

    # 3. and a shard that was never frozen appears
    write_shard(root, "AAAUSDT_1h.json", [NOW - 2 * HOUR, NOW - HOUR, NOW - 2 * HOUR])
    write_shard(root, "CCCUSDT_1h.json", [NOW - HOUR, NOW])
    extra = freeze.verify(root, manifest=manifest)
    kinds = {p["kind"] for p in extra["problems"]}
    assert "UNEXPECTED" in kinds and "CHANGED" in kinds


def test_a_hand_edited_manifest_is_caught_by_its_own_digest(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")
    manifest = frozen(root)
    manifest["shards"]["AAAUSDT_1h.json"]["bars"] = 999  # no effect on the digest
    manifest["shards"]["AAAUSDT_1h.json"]["bytes"] += 1  # this one moves it

    checked = freeze.verify(root, manifest=manifest)
    kinds = {problem["kind"] for problem in checked["problems"]}
    assert "MANIFEST_SELF_INCONSISTENT" in kinds
    assert "CHANGED" in kinds


def test_mirror_is_verified_and_protects_an_existing_destination(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")
    manifest = frozen(root)
    dest = tmp_path / "elsewhere" / "mirror"

    receipt = freeze.mirror(root, dest)
    assert receipt["verified"] is True
    assert receipt["corpus_digest"] == manifest["corpus_digest"]
    with pytest.raises(freeze.CorpusFreezeError, match="MIRROR_EXISTS"):
        freeze.mirror(root, dest)


def test_restore_drill_loses_and_restores_in_a_throwaway_root(tmp_path: Path) -> None:
    root = corpus(tmp_path / "corpus")
    manifest = frozen(root)
    mirror = tmp_path / "mirror"
    freeze.mirror(root, mirror)
    read_root = tmp_path / "corpus"

    def reader(path: Path) -> tuple:
        """What a loader would see: bar count, span, and the bytes of every shard.

        ``edge01.data.load_1h`` is not used here on purpose: it records each source as a path
        relative to the checkout, so it cannot read a corpus in a throwaway root at all.  That
        coupling is real and is noted in the module docstring rather than papered over.
        """
        from trading_bot.research.edge01.data import os_sha256

        shards = sorted(p for p in path.glob("*.json") if not p.name.startswith("_"))
        bars = 0
        last = 0
        for shard in shards:
            rows = json.loads(shard.read_text(encoding="utf-8"))
            bars += len(rows)
            last = max(last, int(rows[-1][0]))
        return (len(shards), bars, last, tuple(os_sha256(shard) for shard in shards))

    drill = freeze.restore_drill(root, mirror, scratch=tmp_path / "drill", reader=reader)

    assert drill["restored"] is True
    assert drill["during_loss"]["ok"] is False
    assert set(drill["during_loss"]["problems"]) == {"MISSING"}
    assert drill["before"]["corpus_digest"] == drill["after_restore"]["corpus_digest"]
    assert drill["reader_agrees"] is True
    # the real corpus and its mirror are untouched by the drill
    assert freeze.verify(root, manifest=manifest)["ok"] is True
    assert freeze.verify(mirror, manifest=manifest)["ok"] is True
    assert not (read_root / "drill").exists()
