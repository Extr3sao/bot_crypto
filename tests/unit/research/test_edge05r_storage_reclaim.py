"""WP-EDGE-05R — the reclaim's sentence and its figures, held to each other.

The defect this pins is real and dated: the sweep of 2026-10-13T22:22:02Z reclaimed 43.23 MiB and
printed ``reaches_the_critical_floor: False`` beside a sentence asserting that caches "take the
volume across the 2 GiB line the lane refuses below". Both strings were built at the same instant
from the same measurement; only one of them was derived from it.

So these tests do not read the prose and approve of it. They drive ``main`` with a volume of a known
size and require the sentence to say what the flags say — in each of the three bands.
"""

from __future__ import annotations

import collections
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GIB = 1024**3
MIB = 1024**2

Usage = collections.namedtuple("Usage", "total used free")


def _load(name: str) -> Any:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reclaim() -> Any:
    return _load("edge05r_storage_reclaim")


@pytest.mark.parametrize(
    ("free_gib", "critical", "healthy"),
    ((0.8, False, False), (3.0, True, False), (6.0, True, True)),
)
def test_the_sentence_agrees_with_the_flags_it_is_printed_beside(
    reclaim: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    free_gib: float,
    critical: bool,
    healthy: bool,
) -> None:
    free_after = int(free_gib * GIB)

    def fake_usage(_path: Any) -> Usage:
        return Usage(total=238 * GIB, used=238 * GIB - free_after, free=free_after)

    monkeypatch.setattr(reclaim.shutil, "disk_usage", fake_usage)
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    assert reclaim.main(["--root", str(root), "--out", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    reading = payload["reading"]

    assert payload["reaches_the_critical_floor"] is critical
    assert payload["reaches_the_healthy_floor"] is healthy
    if healthy:
        assert "clears both declared floors" in reading
    elif critical:
        assert "clears the 2 GiB" in reading
        assert "short of the 5 GiB" in reading
    else:
        # the exact claim the old literal made, which its own table denied
        assert "resumes ingestion" not in reading
        assert "do not take the volume across the 2 GiB" in reading
        assert f"{round((reclaim.CRITICAL_FLOOR_BYTES - free_after) / MIB, 1)} MiB short" in reading
    # and the figure the sentence cites is the figure the payload carries
    figures = {row["figure"]: row["value"] for row in payload["figures"]}
    assert figures["volume_free_bytes_after"] == free_after


def test_the_below_floor_sentence_names_the_shortfall_and_its_owner(reclaim: Any) -> None:
    free_after = 900 * MIB
    reading = reclaim.floor_reading(
        free_after=free_after, reclaimed_bytes=45_325_522, would_reclaim_bytes=45_325_522
    )
    assert f"{round((reclaim.CRITICAL_FLOOR_BYTES - free_after) / MIB, 1)} MiB short" in reading
    assert "43.23 MiB" in reading  # 45325522 bytes, the whole reclaim, in MiB
    assert "volume owner's decision" in reading
    assert "which resumes ingestion" not in reading
