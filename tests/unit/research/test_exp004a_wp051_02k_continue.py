"""Tests for the WP-051-02K continuation harness.

The dangerous parts of this program are the decisions, not the file I/O: what counts as obsolete,
what counts as stale, what may never be named in a manifest. Each of those is a pure function, so
each is tested without touching a real browser cache, a real scratch tree or the real volume.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import exp004a_wp051_02k_continue as cont  # noqa: E402


# --------------------------------------------------------------------------- #
# what a browser revision is
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("chromium-1243", "1243"),
        ("chromium_headless_shell-1243", "1243"),
        ("firefox-1495", "1495"),
        ("webkit-2215", "2215"),
        ("ffmpeg-1011", None),
        ("winldd-1007", None),
        ("chromium", None),
    ],
)
def test_revision_of_reads_the_family_and_the_number(name: str, expected: str | None) -> None:
    assert cont._revision_of(name) == expected


# --------------------------------------------------------------------------- #
# what may never be deleted
# --------------------------------------------------------------------------- #
def test_denied_blocks_user_documents() -> None:
    assert cont.denied(cont.HOME / "Documents" / "anything.pdf")


def test_denied_blocks_the_trees_the_owner_withheld() -> None:
    assert cont.denied(cont.HERMES_ROOT / "cache.bin")
    assert cont.denied(cont.DENIED_WORKTREE / "src" / "x.py")


def test_denied_allows_the_authorised_targets() -> None:
    # The mandate names these three; a blanket ban on AppData would silently block it.
    assert cont.denied(cont.TEMP_ROOT / "old.tmp") is None
    assert cont.denied(cont.PLAYWRIGHT_ROOT / "chromium-1243" / "chrome.exe") is None
    assert cont.denied(cont.CACHE_ROOT / "codex-runtimes") is None


# --------------------------------------------------------------------------- #
# the budget is carried, not lowered
# --------------------------------------------------------------------------- #
def test_budget_without_a_store_keeps_the_frozen_figure(tmp_path: Path) -> None:
    plan = cont.budget(tmp_path / "missing-store")
    assert plan["source"] == "FROZEN_02J_P90"
    assert plan["recomputable"] is False
    assert plan["required_gib"] == pytest.approx(14.564, abs=1e-9)
    assert plan["required_bytes"] == cont.FROZEN_REQUIRED_BYTES


def test_budget_recomputes_when_readings_exist(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    rows = []
    base = 1_800_000_000_000
    for day in range(4):
        start = 60 * 60 * 1000
        rows.append({"started_at_ms": base + day * 86_400_000 + start, "disk": {"free_bytes": 20 * cont.GIB}})
        rows.append({"started_at_ms": base + day * 86_400_000 + 2 * start, "disk": {"free_bytes": 10 * cont.GIB}})
    (store / "runs.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    plan = cont.budget(store)
    assert plan["source"] == "RECOMPUTED_FROM_OBSERVER"
    assert plan["history_days"] == 4
    # every day falls exactly 10 GiB, so p90 is 10 GiB and the floor is added on top
    assert plan["required_gib"] == pytest.approx(12.0, abs=0.05)


def test_capacity_verdict_is_the_comparison_and_nothing_else() -> None:
    plan = {"required_bytes": 10 * cont.GIB, "required_gib": 10.0}
    passing = cont.capacity_state({"free_bytes": 10 * cont.GIB, "free_gib": 10.0, "instruments_agree": True}, plan)
    failing = cont.capacity_state({"free_bytes": 10 * cont.GIB - 1, "free_gib": 9.99, "instruments_agree": True}, plan)
    assert passing["verdict"] == "PASS"
    assert failing["verdict"] == "INSUFFICIENT"


# --------------------------------------------------------------------------- #
# staleness
# --------------------------------------------------------------------------- #
def test_temp_plan_takes_only_old_files(tmp_path: Path) -> None:
    root = tmp_path / "Temp"
    root.mkdir()
    old = root / "old.tmp"
    fresh = root / "fresh.tmp"
    old.write_bytes(b"x" * 10)
    fresh.write_bytes(b"y" * 20)
    stamp = time.time()
    os.utime(old, (stamp - 10 * 86_400, stamp - 10 * 86_400))
    plan = cont.temp_plan(root, min_age_days=7, reference_ts=stamp)
    names = {Path(row["path"]).name for row in plan["candidates"]}
    assert names == {"old.tmp"}
    assert plan["bytes_reclaimable"] == 10


def test_temp_plan_keeps_another_packages_scratch(tmp_path: Path) -> None:
    root = tmp_path / "Temp"
    (root / "rfc012b-browser-abc").mkdir(parents=True)
    evidence = root / "rfc012b-browser-abc" / "profile.dat"
    evidence.write_bytes(b"z" * 5)
    stamp = time.time()
    os.utime(evidence, (stamp - 20 * 86_400, stamp - 20 * 86_400))
    plan = cont.temp_plan(root, min_age_days=7, reference_ts=stamp)
    assert plan["candidates"] == []
    assert plan["bytes_preserved"] == 5
    assert "another package" in plan["preserved"][0]["why"]


# --------------------------------------------------------------------------- #
# obsolescence is a search, not a guess
# --------------------------------------------------------------------------- #
def _fake_playwright(root: Path, installed: list[str], required_by_consumer: list[str]) -> None:
    for name in installed:
        (root / name).mkdir(parents=True)
        (root / name / "chrome.exe").write_bytes(b"a" * 4)
    links = root / ".links"
    links.mkdir()
    # The consumer lives outside the browser cache, the way a real venv does.
    driver = root.parent / "driver-package"
    driver.mkdir()
    (driver / "browsers.json").write_text(
        json.dumps({"browsers": [{"name": "chromium", "revision": revision} for revision in required_by_consumer]}),
        encoding="utf-8",
    )
    (links / "consumer").write_text(str(driver), encoding="utf-8")


def test_playwright_plan_retires_only_the_unrequested_revision(tmp_path: Path) -> None:
    root = tmp_path / "ms-playwright"
    _fake_playwright(root, ["chromium-1187", "chromium-1243"], ["1187"])
    plan = cont.playwright_plan(root, scan={"manifests": [], "roots": [], "truncated": False})
    assert [row["name"] for row in plan["obsolete"]] == ["chromium-1243"]
    assert [row["name"] for row in plan["kept"]] == ["chromium-1187"]
    assert plan["required_revisions"] == ["1187"]


def test_playwright_plan_keeps_a_revision_only_the_scan_knows_about(tmp_path: Path) -> None:
    root = tmp_path / "ms-playwright"
    _fake_playwright(root, ["chromium-1187", "chromium-1208"], ["1187"])
    plan = cont.playwright_plan(
        root,
        scan={"manifests": [{"path": "elsewhere/browsers.json", "requires": ["1208"]}], "roots": [], "truncated": False},
    )
    assert plan["obsolete"] == []
    assert {row["name"] for row in plan["kept"]} == {"chromium-1187", "chromium-1208"}


def test_playwright_plan_ignores_a_stale_link(tmp_path: Path) -> None:
    root = tmp_path / "ms-playwright"
    _fake_playwright(root, ["chromium-1187"], ["1187"])
    (root / ".links" / "dead").write_text(str(tmp_path / "gone"), encoding="utf-8")
    plan = cont.playwright_plan(root, scan={"manifests": [], "roots": [], "truncated": False})
    statuses = {row["link"]: row["status"] for row in plan["consumers"]}
    assert statuses["dead"] == "STALE_LINK"
    assert plan["obsolete"] == []


# --------------------------------------------------------------------------- #
# the cache refuses what a running tool may need
# --------------------------------------------------------------------------- #
def test_cache_plan_refuses_a_runtime_a_running_tool_uses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".cache"
    entry = root / "codex-runtimes" / "codex-primary-runtime"
    entry.mkdir(parents=True)
    (entry / "node.exe").write_bytes(b"n" * 8)
    monkeypatch.setattr(cont, "process_table", lambda: [{"pid": 42, "name": "codex", "write_bytes": 0, "read_bytes": 0}])
    plan = cont.cache_plan(root, handles={"paths": []})
    assert plan["bytes_reclaimable"] == 0
    assert plan["entries"][0]["eligible"] is False
    assert "running" in plan["entries"][0]["why"]


def test_cache_plan_accepts_a_downloaded_runtime_nothing_is_using(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".cache"
    entry = root / "some-tool" / "node_modules"
    entry.mkdir(parents=True)
    (entry / "index.js").write_bytes(b"j" * 6)
    monkeypatch.setattr(cont, "process_table", lambda: [])
    plan = cont.cache_plan(root, handles={"paths": []})
    assert plan["entries"][0]["eligible"] is True
    assert plan["bytes_reclaimable"] == 6


# --------------------------------------------------------------------------- #
# deletion
# --------------------------------------------------------------------------- #
def test_apply_target_deletes_only_inside_its_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "a.tmp"
    inside.write_bytes(b"1234")
    outside = tmp_path / "outside.tmp"
    outside.write_bytes(b"5678")
    monkeypatch.setattr(cont, "denied", lambda path: None)
    evidence = tmp_path / "evidence" / "manifest.jsonl"
    target = {
        "key": "temp-stale",
        "root": str(root),
        "bytes_reclaimable": 8,
        "candidates": [{"path": str(inside), "bytes": 4}, {"path": str(outside), "bytes": 4}],
    }
    result = cont.apply_target(target, evidence_path=evidence, dry_run=False)
    assert not inside.exists()
    assert outside.exists(), "a path outside the authorised root must not be removed"
    assert result["deleted_files"] == 1
    assert result["skipped_count"] == 1
    assert "outside the authorised root" in result["skipped"][0]["why"]
    rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    assert [Path(row["path"]).name for row in rows] == ["a.tmp"]
    assert rows[0]["bytes"] == 4


def test_apply_target_records_before_unlinking_and_honours_a_protected_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    keep = root / "keep.bin"
    keep.write_bytes(b"keep")
    victim = root / "victim.tmp"
    victim.write_bytes(b"victim")
    monkeypatch.setattr(cont, "denied", lambda path: "protected for the test" if path.name == "keep.bin" else None)
    evidence = tmp_path / "manifest.jsonl"
    target = {
        "key": "temp-stale",
        "root": str(root),
        "bytes_reclaimable": 10,
        "candidates": [{"path": str(keep), "bytes": 4}, {"path": str(victim), "bytes": 6}],
    }
    result = cont.apply_target(target, evidence_path=evidence, dry_run=False)
    assert keep.exists() and not victim.exists()
    assert result["deleted_bytes"] == 6
    assert any("protected" in row["why"] for row in result["skipped"])


def test_apply_target_dry_run_deletes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    keep = root / "a.bin"
    keep.write_bytes(b"abcd")
    monkeypatch.setattr(cont, "denied", lambda path: None)
    target = {"key": "temp-stale", "root": str(root), "bytes_reclaimable": 4, "candidates": [{"path": str(keep), "bytes": 4}]}
    result = cont.apply_target(target, evidence_path=tmp_path / "m.jsonl", dry_run=True)
    assert keep.exists()
    assert result["dry_run"] is True
    assert result["deleted_bytes"] == 4


# --------------------------------------------------------------------------- #
# integrity
# --------------------------------------------------------------------------- #
def _integrity(files: dict[str, dict], store_exists: bool, experiment: dict[str, bool]) -> dict:
    return {
        "files": files,
        "store": {"root": "x", "exists": store_exists},
        "experiment": {name: {"path": name, "exists": ok} for name, ok in experiment.items()},
        "record": {"files": {}},
    }


def test_compare_integrity_passes_when_nothing_moved() -> None:
    files = {"a": {"sha256": "1", "bytes": 1}}
    experiment = {"contract": True, "store": True}
    before = _integrity(files, True, experiment)
    after = _integrity(files, True, experiment)
    after["store"] = {"root": "x", "exists": True, "daily": {"d": 1}, "append_only": {"runs.jsonl": 1}}
    before["store"] = dict(after["store"])
    result = cont.compare_integrity(before, after)
    assert result["verdict"] == "PASS"


def test_compare_integrity_fails_on_one_altered_byte() -> None:
    before = _integrity({"a": {"sha256": "1", "bytes": 1}}, True, {"store": True})
    after = _integrity({"a": {"sha256": "2", "bytes": 1}}, True, {"store": True})
    after["store"] = {**before["store"], "daily": {}, "append_only": {}}
    before["store"] = {**before["store"], "daily": {}, "append_only": {}}
    result = cont.compare_integrity(before, after)
    assert result["verdict"] == "FAIL"
    failed = [check["id"] for check in result["checks"] if check["status"] == "FAIL"]
    assert "EXPERIMENT_FILES_IDENTICAL" in failed


def test_compare_integrity_reports_a_missing_store_as_failure() -> None:
    files = {"a": {"sha256": "1", "bytes": 1}}
    before = _integrity(files, False, {"store": False})
    after = _integrity(files, False, {"store": False})
    result = cont.compare_integrity(before, after)
    statuses = {check["id"]: check["status"] for check in result["checks"]}
    assert statuses["STORE_PRESENT"] == "FAIL"
    assert statuses["LIVE_EXPERIMENT_PRESENT"] == "FAIL"
    assert result["verdict"] == "FAIL"


# --------------------------------------------------------------------------- #
# the report says what the numbers say
# --------------------------------------------------------------------------- #
def test_render_markdown_carries_the_sections_the_mandate_asks_for() -> None:
    report = {
        "package": "WP-051-02K",
        "generated_at_utc": "2026-10-23T00:00:00Z",
        "verdict": "BLOCKED",
        "capacity": {
            "before": {"free_gib": 1.0, "required_gib": 14.564, "margin_gib": -13.5, "instruments_agree": True},
            "after": {"free_gib": 2.0, "required_gib": 14.564, "margin_gib": -12.5, "instruments_agree": True},
        },
        "budget": {"source": "FROZEN_02J_P90", "basis": "p90 drawdown"},
        "cleanup": {"targets": [], "total_deleted_gib": 0.0, "volume_delta_bytes": 0},
        "refused": [{"path": "C:/x", "bytes": 1, "why": "not authorised"}],
        "observed_growth": {"seconds": 60, "dropped_bytes": 0, "writers": [], "share_explained_percent": None, "caveat": "caveat"},
        "integrity": {"checks": [{"id": "X", "status": "FAIL", "detail": "d"}]},
        "guard": {"state": "ABSENT_IN_THIS_TREE", "script_present": False, "process_running": [], "store_present": False, "note": "n"},
        "blockers": ["CAMPAIGN_STORE_ABSENT"],
    }
    text = cont.render_markdown(report)
    for heading in ("## Espacio", "## Limpieza", "## Crecimiento observado", "## Integridad", "## Guard", "## Bloqueos"):
        assert heading in text
    assert "CAMPAIGN_STORE_ABSENT" in text
    assert "total_deleted_gib" not in text
