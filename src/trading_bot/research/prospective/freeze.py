"""Corpus freeze — a manifest that can be checked, a copy that can be restored.

The 15m corpus of EXP004A was lost and could not be re-fetched, because its last row was
written while that bar was still open and nothing recorded which bytes were in it.  The
lesson is not "be careful": it is that a corpus without three things cannot be defended.

* **a manifest** — every shard's ``sha256`` and size, plus one ``corpus_digest`` over the
  whole set, written at freeze time and committed somewhere that outlives the data;
* **a closed-bar rule** — a shard may only be frozen when its last bar has actually closed,
  because a row captured mid-bar is a value the venue will never publish again;
* **a mirror that has been restored from** — redundancy nobody has exercised is a hope, not
  a copy.

This module implements those three and nothing else.  It reuses the manifest vocabulary the
repository already publishes (``data/edge08/universe-1h/_FETCH_MANIFEST.json``: ``source``,
``interval``, ``normalization``, per-symbol stats, ``corpus_digest``) and the hashing primitive
from :mod:`trading_bot.research.edge01.data`, so there is one way to say "these bytes" in this
tree rather than two.

What it deliberately does *not* do: fetch anything, decide what corpus is right, or touch a
pin.  Freezing is an operation on bytes that already exist.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from trading_bot.research.edge01.data import BAR_MS, os_sha256

__all__ = [
    "DEFAULT_MANIFEST_NAME",
    "SCHEMA_VERSION",
    "CorpusFreezeError",
    "bar_instant_ms",
    "freeze",
    "manifest_digest",
    "mirror",
    "restore_drill",
    "verify",
]

#: Same file name shape the tree already uses for fetch manifests (``_FETCH_MANIFEST.json``),
#: so a reader finds it where they expect and loaders that skip ``_``-prefixed names ignore it.
DEFAULT_MANIFEST_NAME = "_FREEZE_MANIFEST.json"

SCHEMA_VERSION = "CORPUS_FREEZE_V1"


class CorpusFreezeError(RuntimeError):
    """A corpus could not be frozen, or a frozen corpus no longer matches its manifest."""


def bar_instant_ms(row: Any) -> int:
    """The open time of one row, whichever of the two shapes this tree stores."""
    if isinstance(row, dict):
        return int(row["ts"])
    return int(row[0])


def _rows(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    return raw.get("bars") or raw.get("data") or []


def manifest_digest(shards: dict[str, dict[str, Any]]) -> str:
    """One digest over the whole set: ``sha256(name + sha256 + bytes)`` per shard, in order.

    The name is included so that a shard cannot be renamed into or out of the set without the
    digest moving; the size is included so a truncation that happens to keep the hash of the
    prefix is not the only thing standing between a reader and a wrong corpus.
    """
    combined = hashlib.sha256()
    for name in sorted(shards):
        shard = shards[name]
        combined.update(name.encode("utf-8"))
        combined.update(str(shard["sha256"]).encode("utf-8"))
        combined.update(str(shard["bytes"]).encode("utf-8"))
    return combined.hexdigest()


def _shard_names(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.glob("*.json")
        if path.is_file() and not path.name.startswith("_")
    )


def freeze(
    root: Path,
    *,
    interval: str,
    source: str,
    normalization: str,
    expected_shards: Iterable[str] | None = None,
    now_ms: int | None = None,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
) -> dict[str, Any]:
    """Write a manifest for ``root``, refusing anything that is not closed, complete data.

    Refusals, each with its own message because each means a different repair:

    * a shard whose last row has not closed yet (``UNCLOSED_BAR``) — the EXP004A failure;
    * a shard whose timestamps are not strictly increasing or off the grid
      (``BAD_GRID``), which would make a later read silently resequence the past;
    * an empty or unparsable shard (``EMPTY_SHARD``);
    * a shard named in ``expected_shards`` that is not there (``MISSING_SHARD``).
    """
    root = Path(root)
    if not root.is_dir():
        raise CorpusFreezeError(f"MISSING_CORPUS: {root} is not a directory")
    step = BAR_MS.get(interval)
    if step is None:
        raise CorpusFreezeError(f"UNKNOWN_INTERVAL: {interval!r} has no bar length in BAR_MS")
    now = int(now_ms if now_ms is not None else time.time() * 1000)

    paths = _shard_names(root)
    present = {path.name for path in paths}
    missing = sorted(set(expected_shards or ()) - present)
    if missing:
        raise CorpusFreezeError(f"MISSING_SHARD: {', '.join(missing)} not found under {root}")
    if not paths:
        raise CorpusFreezeError(f"EMPTY_CORPUS: no shard under {root}")

    shards: dict[str, dict[str, Any]] = {}
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = _rows(raw)
        if not rows:
            raise CorpusFreezeError(f"EMPTY_SHARD: {path.name} holds no row")
        stamps = [bar_instant_ms(row) for row in rows]
        if any(later <= earlier for earlier, later in pairwise(stamps)):
            raise CorpusFreezeError(f"BAD_GRID: {path.name} is not strictly increasing in time")
        off_grid = [stamp for stamp in stamps if stamp % step]
        if off_grid:
            raise CorpusFreezeError(
                f"BAD_GRID: {path.name} has {len(off_grid)} bar(s) off the {interval} grid"
            )
        last = stamps[-1]
        if last + step > now:
            raise CorpusFreezeError(
                f"UNCLOSED_BAR: {path.name} ends at {last}, whose {interval} bar closes at "
                f"{last + step} — after the freeze instant {now}. A row captured mid-bar is a "
                f"value the venue will not publish again, which is exactly how the EXP004A "
                f"corpus was lost."
            )
        shards[path.name] = {
            "sha256": os_sha256(path),
            "bytes": path.stat().st_size,
            "bars": len(rows),
            "first_ts": stamps[0],
            "last_ts": last,
            "last_close_ts": last + step,
        }

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now / 1000)),
        "frozen_at_ms": now,
        "root_name": root.name,
        "interval": interval,
        "interval_ms": step,
        "source": source,
        "normalization": normalization,
        "closed_bar_rule": (
            "every shard's last_ts + interval_ms <= frozen_at_ms; a shard ending on an open bar "
            "is refused rather than frozen"
        ),
        "shards": shards,
        "totals": {
            "shards": len(shards),
            "bars": sum(shard["bars"] for shard in shards.values()),
            "bytes": sum(shard["bytes"] for shard in shards.values()),
        },
        "corpus_digest": manifest_digest(shards),
    }
    (root / manifest_name).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def verify(
    root: Path, *, manifest: dict[str, Any] | None = None, manifest_name: str = DEFAULT_MANIFEST_NAME
) -> dict[str, Any]:
    """Recompute everything the manifest claims.  Returns the differences, not a boolean.

    ``ok`` is true only when every shard named by the manifest is present with the recorded
    size and hash, no extra shard appeared, and the combined digest recomputes.  A corpus that
    grew is also a difference: a reader pinned to the digest cannot tell a new bar from a
    rewritten one unless the set is closed.
    """
    root = Path(root)
    if manifest is None:
        path = root / manifest_name
        if not path.is_file():
            raise CorpusFreezeError(f"MISSING_MANIFEST: {path} does not exist")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = manifest["shards"]
    found = {path.name for path in _shard_names(root)}
    problems: list[dict[str, Any]] = []

    for name in sorted(set(expected) - found):
        problems.append({"shard": name, "kind": "MISSING"})
    for name in sorted(found - set(expected)):
        problems.append({"shard": name, "kind": "UNEXPECTED"})
    for name in sorted(set(expected) & found):
        path = root / name
        size = path.stat().st_size
        digest = os_sha256(path)
        if size != expected[name]["bytes"] or digest != expected[name]["sha256"]:
            problems.append(
                {
                    "shard": name,
                    "kind": "CHANGED",
                    "expected_bytes": expected[name]["bytes"],
                    "found_bytes": size,
                    "expected_sha256": expected[name]["sha256"],
                    "found_sha256": digest,
                }
            )
    recomputed = manifest_digest(expected)
    if recomputed != manifest["corpus_digest"]:
        problems.append(
            {
                "kind": "MANIFEST_SELF_INCONSISTENT",
                "expected": manifest["corpus_digest"],
                "recomputed": recomputed,
            }
        )
    return {
        "root": str(root),
        "interval": manifest["interval"],
        "shards_expected": len(expected),
        "shards_found": len(found),
        "corpus_digest": manifest["corpus_digest"],
        "ok": not problems,
        "problems": problems,
    }


def mirror(
    root: Path,
    destination: Path,
    *,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy a frozen corpus to a second root and prove the copy answers to the same manifest."""
    root, destination = Path(root), Path(destination)
    manifest = json.loads((root / manifest_name).read_text(encoding="utf-8"))
    if destination.exists() and not overwrite:
        raise CorpusFreezeError(
            f"MIRROR_EXISTS: {destination} already holds something; pass overwrite=True to replace it"
        )
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name in sorted(manifest["shards"]):
        shutil.copyfile(root / name, destination / name)
    shutil.copyfile(root / manifest_name, destination / manifest_name)
    checked = verify(destination, manifest=manifest, manifest_name=manifest_name)
    if not checked["ok"]:
        raise CorpusFreezeError(f"MIRROR_MISMATCH: {checked['problems']}")
    return {
        "source": str(root),
        "destination": str(destination),
        "shards": len(manifest["shards"]),
        "bytes": manifest["totals"]["bytes"],
        "corpus_digest": manifest["corpus_digest"],
        "verified": True,
    }


def restore_drill(
    primary: Path,
    backup: Path,
    *,
    scratch: Path,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    reader: Any = None,
) -> dict[str, Any]:
    """Lose the corpus on purpose and put it back from the mirror, in a throwaway root.

    The drill never touches the real corpus: it copies primary and backup into ``scratch``,
    deletes the scratch primary, restores it from the scratch backup, and re-verifies.  When
    ``reader`` is given (a callable ``reader(root) -> digest``), it is called before and after
    so the drill also proves a real consumer still sees the same corpus — a manifest that
    agrees with itself is not evidence that anything can be read.
    """
    scratch = Path(scratch)
    if scratch.exists():
        shutil.rmtree(scratch)
    work = scratch / "primary"
    spare = scratch / "mirror"
    shutil.copytree(primary, work)
    shutil.copytree(backup, spare)
    manifest = json.loads((work / manifest_name).read_text(encoding="utf-8"))

    before = verify(work, manifest=manifest, manifest_name=manifest_name)
    if not before["ok"]:
        raise CorpusFreezeError(f"DRILL_SETUP_INVALID: {before['problems']}")
    read_before = reader(work) if reader else None

    # The loss: the shards and the manifest are gone, which is what happened to EXP004A.
    for path in sorted(work.iterdir()):
        path.unlink()
    lost = verify(work, manifest=manifest, manifest_name=manifest_name)

    # The restore: straight from the mirror, manifest included, no recomputation from wires.
    for path in sorted(spare.iterdir()):
        shutil.copyfile(path, work / path.name)
    after = verify(work, manifest=manifest, manifest_name=manifest_name)
    read_after = reader(work) if reader else None

    deletions = len(manifest["shards"]) + 1
    return {
        "scratch": str(scratch),
        "shards_removed": deletions,
        "before": {"ok": before["ok"], "corpus_digest": before["corpus_digest"]},
        "during_loss": {
            "ok": lost["ok"],
            "problems": [problem["kind"] for problem in lost["problems"]],
        },
        "after_restore": {"ok": after["ok"], "corpus_digest": after["corpus_digest"]},
        "reader_before": read_before,
        "reader_after": read_after,
        "reader_agrees": (read_before == read_after) if reader else None,
        "restored": after["ok"] and not lost["ok"],
    }


@dataclass(frozen=True, slots=True)
class FrozenCorpus:
    """A verified manifest plus the root it describes, for callers that want one object."""

    root: Path
    manifest: dict[str, Any]

    @property
    def corpus_digest(self) -> str:
        return self.manifest["corpus_digest"]

    @property
    def shards(self) -> dict[str, dict[str, Any]]:
        return self.manifest["shards"]

    def check(self) -> dict[str, Any]:
        return verify(self.root, manifest=self.manifest)
