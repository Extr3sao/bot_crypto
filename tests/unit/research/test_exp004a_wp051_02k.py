"""WP-051-02K — the capacity decision must be able to say no.

These tests cover the two things that make a capacity report trustworthy: the arithmetic never
turns a shortfall into a pass, and the inventory never turns somebody else's bytes into a delete
list. Filesystem tests run inside ``tmp_path``; nothing here reads the real campaign store.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

GIB = 1024**3
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "exp004a_wp051_02k_capacity.py"


def load_module():
    spec = importlib.util.spec_from_file_location("wp051_02k", SCRIPTS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wp = load_module()


# --------------------------------------------------------------------------- #
# the decision: only the budget can promote capacity
# --------------------------------------------------------------------------- #
def test_a_pass_requires_the_whole_budget():
    required = 14 * GIB
    assert wp.capacity_verdict(required, required) == "PASS"
    assert wp.capacity_verdict(required - 1, required) == "INSUFFICIENT"
    assert wp.shortfall(required - 1, required) == 1
    assert wp.shortfall(required, required) == 0


def test_free_space_alone_never_hides_a_shortfall():
    """Three quarters of the budget is still a shortfall, however healthy it looks."""
    required = wp.CRITICAL_FREE_BYTES + 12 * GIB
    assert wp.capacity_verdict(int(required * 0.75), required) == "INSUFFICIENT"


def test_the_floor_is_the_observer_floor():
    assert wp.CRITICAL_FREE_BYTES == 2 * GIB
    assert wp.WARNING_FREE_BYTES == 5 * GIB


def test_percentile_uses_nearest_rank():
    values = [float(n) for n in range(1, 12)]
    assert wp.percentile(values, 0.90) == 10.0
    assert wp.percentile(values, 0.50) == 6.0
    assert wp.percentile([], 0.9) == 0.0


# --------------------------------------------------------------------------- #
# the budget: p90 plus floor plus own growth, never the maximum
# --------------------------------------------------------------------------- #
def write_runs(root: Path, days: int, drop_gib: list[float]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    start = 1_792_713_600_000  # 2026-10-23T00:00:00Z
    for index in range(days):
        high = 40 * GIB
        low = high - int(drop_gib[index % len(drop_gib)] * GIB)
        for hour, free in ((0, high), (6, low), (23, high)):
            rows.append(
                {
                    "started_at_ms": start + index * 86_400_000 + hour * 3_600_000,
                    "outcome": "OBSERVED",
                    "disk_after": {"free_bytes": free},
                }
            )
    (root / "runs.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (root / "resource_budget.json").write_text(
        json.dumps({"samples": [{"ts_ms": start, "bytes": 0}, {"ts_ms": start + 10 * 86_400_000, "bytes": 10_000_000}]}),
        encoding="utf-8",
    )


def test_budget_is_p90_not_the_worst_day(tmp_path: Path):
    drops = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 15.0]
    write_runs(tmp_path, 11, drops)
    plan = wp.budget(tmp_path)
    assert plan["history_days"] == 11
    assert plan["drawdown_max_bytes"] == 15 * GIB
    assert plan["required_bytes"] == int(5 * GIB) + wp.CRITICAL_FREE_BYTES + plan["own_window_bytes"]
    assert plan["required_bytes"] < plan["required_at_max_bytes"]


def test_budget_counts_the_campaigns_own_growth(tmp_path: Path):
    write_runs(tmp_path, 3, [1.0])
    plan = wp.budget(tmp_path)
    assert plan["own_window_bytes"] > 0
    assert plan["required_bytes"] == int(plan["drawdown_p90_bytes"]) + wp.CRITICAL_FREE_BYTES + plan["own_window_bytes"]


def test_a_refused_tick_is_history_not_a_present_tense_decision(tmp_path: Path):
    write_runs(tmp_path, 2, [1.0])
    with (tmp_path / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"started_at_ms": 1_792_713_600_000, "outcome": "DISK_BUDGET_EXCEEDED",
                                 "disk_after": {"free_bytes": 0}}) + "\n")
    audit = wp.refusals(tmp_path)
    assert audit["total"] == 1
    assert audit["last"]["free_bytes"] == 0
    # the refusal is reported, and it does not silently become a capacity verdict by itself
    assert wp.capacity_verdict(20 * GIB, 14 * GIB) == "PASS"


# --------------------------------------------------------------------------- #
# the store: an append is not an edit, and a rewrite is not an append
# --------------------------------------------------------------------------- #
def test_appended_rows_keep_the_prefix(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    runs = store / "runs.jsonl"
    runs.write_text('{"a": 1}\n', encoding="utf-8")
    before = wp.store_fingerprint(store)
    runs.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    after = wp.store_fingerprint(store)
    result = wp.compare_fingerprints(before, after, store)
    assert result["verdict"] == "PASS", result


def test_a_rewritten_row_is_caught(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    runs = store / "runs.jsonl"
    runs.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    before = wp.store_fingerprint(store)
    runs.write_text('{"a": 1}\n{"b": 999}\n{"c": 3}\n', encoding="utf-8")
    after = wp.store_fingerprint(store)
    result = wp.compare_fingerprints(before, after, store)
    assert result["verdict"] == "FAIL"
    assert any(check["id"] == "APPEND_ONLY_PREFIX_INTACT" and check["status"] == "FAIL" for check in result["checks"])


def test_a_shrunk_append_only_file_is_caught(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "slots.jsonl").write_text("one\ntwo\nthree\n", encoding="utf-8")
    before = wp.store_fingerprint(store)
    (store / "slots.jsonl").write_text("one\n", encoding="utf-8")
    after = wp.store_fingerprint(store)
    assert wp.compare_fingerprints(before, after, store)["verdict"] == "FAIL"


def test_write_once_shards_may_not_move(tmp_path: Path):
    store = tmp_path / "store"
    (store / "daily").mkdir(parents=True)
    shard = store / "daily" / "2026-10-23.json"
    shard.write_text('{"rows": 24}', encoding="utf-8")
    before = wp.store_fingerprint(store)
    same = wp.compare_fingerprints(before, wp.store_fingerprint(store), store)
    assert same["verdict"] == "PASS"
    shard.write_text('{"rows": 72}', encoding="utf-8")
    changed = wp.compare_fingerprints(before, wp.store_fingerprint(store), store)
    assert changed["verdict"] == "FAIL"


def test_rewritten_files_keep_their_contract_but_not_their_bytes(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    health = store / "health.json"
    payload = {"disk": {"critical_free_bytes": wp.CRITICAL_FREE_BYTES, "warning_free_bytes": wp.WARNING_FREE_BYTES},
               "declared": {"daily_kept": 366}, "generated_at_utc": "t0"}
    health.write_text(json.dumps(payload), encoding="utf-8")
    before = wp.store_fingerprint(store)
    payload["generated_at_utc"] = "t1"  # every tick rewrites this line, by design
    health.write_text(json.dumps(payload), encoding="utf-8")
    assert wp.compare_fingerprints(before, wp.store_fingerprint(store), store)["verdict"] == "PASS"
    payload["disk"]["critical_free_bytes"] = 1
    health.write_text(json.dumps(payload), encoding="utf-8")
    assert wp.compare_fingerprints(before, wp.store_fingerprint(store), store)["verdict"] == "FAIL"


# --------------------------------------------------------------------------- #
# the inventory: a candidate is named, never ordered
# --------------------------------------------------------------------------- #
def test_foreign_trees_are_never_safe_owned(tmp_path: Path):
    foreign = tmp_path / "somebody-elses-cache" / "__pycache__"
    foreign.mkdir(parents=True)
    klass, reason = wp.classify(foreign, age_hours=100.0, tracked=None, own_family=False)
    assert klass == wp.REQUIRES_APPROVAL
    assert "owner" in reason


def test_a_recently_written_tree_is_protected(tmp_path: Path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    klass, _ = wp.classify(cache, age_hours=0.1, tracked=False, own_family=True)
    assert klass == wp.ACTIVE_OR_PROTECTED


def test_a_tracked_cache_is_protected(tmp_path: Path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    klass, reason = wp.classify(cache, age_hours=100.0, tracked=True, own_family=True)
    assert klass == wp.ACTIVE_OR_PROTECTED
    assert "tracked" in reason.lower() or "Git" in reason


def test_git_failure_is_unknown_not_deletable(tmp_path: Path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    klass, _ = wp.classify(cache, age_hours=100.0, tracked=None, own_family=True)
    assert klass == wp.UNKNOWN


def test_classification_never_calls_a_junction_safe():
    assert hasattr(wp, "is_reparse_entry")


def test_options_never_include_something_this_package_deletes():
    options = [
        wp.option(key="own", path="r/x", bytes_=1 * GIB, owner="me", kind="OWN_CACHE",
                  risk="-", recovery="-", reversible=True, needs_admin=False,
                  frees_without_authorisation=True),
        wp.option(key="wsl", path="C:/wsl", bytes_=6 * GIB, owner="user", kind="MOVE_OR_COMPACT",
                  risk="-", recovery="-", reversible=False, needs_admin=True),
    ]
    plan = wp.coverage_plan(options, 5 * GIB)
    assert "own" not in plan["selected"]
    assert plan["selected"] == ["wsl"]
    assert plan["covers_gap"] is True


def test_coverage_plan_reports_when_it_cannot_cover_the_gap():
    options = [
        wp.option(key="small", path="x", bytes_=1 * GIB, owner="u", kind="REBUILDABLE",
                  risk="-", recovery="-", reversible=True, needs_admin=False),
    ]
    plan = wp.coverage_plan(options, 13 * GIB)
    assert plan["covers_gap"] is False
    assert plan["spare_after_gap_gib"] < 0


def test_coverage_prefers_reversible_over_larger_irreversible():
    options = [
        wp.option(key="big-lossy", path="a", bytes_=9 * GIB, owner="u", kind="TEMP_RUN_LEFTOVER",
                  risk="-", recovery="-", reversible=False, needs_admin=True),
        wp.option(key="small-safe", path="b", bytes_=7 * GIB, owner="u", kind="REPROVISIONABLE",
                  risk="-", recovery="-", reversible=True, needs_admin=False),
    ]
    plan = wp.coverage_plan(options, 6 * GIB)
    assert plan["selected"] == ["small-safe"]


def test_the_ask_adds_a_margin_over_the_gap():
    options = [
        wp.option(key="exact", path="x", bytes_=6 * GIB, owner="u", kind="REPROVISIONABLE",
                  risk="-", recovery="-", reversible=True, needs_admin=False),
    ]
    plan = wp.coverage_plan(options, 6 * GIB)
    assert plan["target_bytes"] == 6 * GIB + wp.FIX_MARGIN_BYTES
    assert plan["covers_gap"] is False  # 6 GiB against a 7 GiB target is not a fix


def test_cheaper_recovery_beats_a_bigger_system_change():
    options = [
        wp.option(key="pagefile", path="C:/pagefile.sys", bytes_=26 * GIB, owner="Windows",
                  kind="MOVE_OR_COMPACT", risk="-", recovery="-", reversible=True, needs_admin=True),
        wp.option(key="browsers", path="C:/browsers", bytes_=4 * GIB, owner="u",
                  kind="REPROVISIONABLE", risk="-", recovery="-", reversible=True, needs_admin=False),
        wp.option(key="scratch", path="C:/temp", bytes_=8 * GIB, owner="u",
                  kind="TEMP_RUN_LEFTOVER", risk="-", recovery="-", reversible=False, needs_admin=False),
    ]
    plan = wp.coverage_plan(options, 11 * GIB)
    # both are tier 1, so the reversible one is asked for first; neither is the system change
    assert plan["selected"] == ["browsers", "scratch"]
    assert "pagefile" not in plan["selected"]


def test_a_parent_and_its_child_are_never_counted_twice():
    options = [
        wp.option(key="temp", path="C:/Temp", bytes_=6 * GIB, owner="u", kind="TEMP_RUN_LEFTOVER",
                  risk="-", recovery="-", reversible=False, needs_admin=False),
        wp.option(key="inside-temp", path="C:/Temp/runs", bytes_=4 * GIB, owner="u",
                  kind="TEMP_RUN_LEFTOVER", risk="-", recovery="-", reversible=False, needs_admin=False),
    ]
    plan = wp.coverage_plan(options, 6 * GIB)
    assert plan["selected"] == ["temp"]
    assert plan["selected_bytes"] == 6 * GIB


def test_a_document_folder_is_never_a_candidate(tmp_path: Path):
    rows = [
        {"path": str(Path("C:/Users/GVLLFR0035/AppData")), "bytes": 60 * GIB, "depth": 2},
        {"path": str(Path("C:/Users/GVLLFR0035/Downloads")), "bytes": 19 * GIB, "depth": 2},
        {"path": str(Path("C:/Users/GVLLFR0035/AppData/Local/Temp")), "bytes": 6 * GIB, "depth": 3},
    ]
    keys = {Path(row["path"]).name for row in wp.build_options(rows)}
    assert "Temp" in keys
    assert "AppData" not in keys
    assert "Downloads" not in keys


def test_only_experiment_worktrees_are_offered_for_bundling(tmp_path: Path):
    homework = tmp_path / "Deures Dylan"
    homework.mkdir()
    (homework / ".git").mkdir()
    assert wp.is_experiment_worktree(homework) is False
    worktree = tmp_path / "bot-freebuff-wp003j"
    worktree.mkdir()
    (worktree / ".git").mkdir()
    assert wp.is_experiment_worktree(worktree) is True
    plain = tmp_path / "bot-not-a-repo"
    plain.mkdir()
    assert wp.is_experiment_worktree(plain) is False


def test_the_request_carries_paths_sizes_and_a_way_back():
    options = [
        wp.option(key="k", path="C:/somewhere", bytes_=7 * GIB, owner="user", kind="REPROVISIONABLE",
                  risk="re-download", recovery="re-run the installer", reversible=True, needs_admin=False),
    ]
    plan = wp.coverage_plan(options, 6 * GIB)
    request = wp.authorisation_request(options, plan)
    assert request["items"][0]["path"] == "C:/somewhere"
    assert request["items"][0]["recovery"]
    assert request["items"][0]["gib"] > 0
    assert any("--after" in step for step in request["procedure"])


# --------------------------------------------------------------------------- #
# scanning and cleaning
# --------------------------------------------------------------------------- #
def test_scan_counts_bytes_and_skips_junctions(tmp_path: Path):
    """A junction must not be walked: ``AppData`` points at itself and the walk would not end."""
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "blob.bin").write_bytes(b"x" * 4096)
    link = tmp_path / "a" / "loop"
    junction = None
    try:
        link.symlink_to(tmp_path / "a", target_is_directory=True)
        junction = link
    except (OSError, NotImplementedError):
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(tmp_path / "a")],
            capture_output=True,
            text=True,
            check=False,
        )
        junction = link if made.returncode == 0 else None
    if junction is None:
        pytest.skip("this host allows neither symlinks nor junctions without elevation")
    row = wp.scan_tree(tmp_path, max_seconds=10.0)
    assert row["bytes"] == 4096
    assert row["skipped_junctions"] >= 1


def test_clean_only_removes_untracked_caches_inside_a_repository(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"0" * 128)
    kept = repo / "src" / "__pycache__"
    kept.mkdir(parents=True)
    (kept / "y.pyc").write_bytes(b"0" * 64)
    subprocess.run(["git", "add", "src/__pycache__"], cwd=repo, check=True, capture_output=True)
    out = tmp_path / "out"
    out.mkdir()
    payload = wp.clean_own(out, [repo])
    removed = {Path(row["path"]).name for row in payload["removed"]}
    kept_paths = {Path(row["path"]).name for row in payload["kept"]}
    assert cache.exists() is False
    assert kept.exists() is True
    assert removed and kept_paths
    assert payload["deleted_bytes"] >= 128


def test_report_keeps_blocked_when_the_gap_survives(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    volume = {"free_gib": 1.5, "free_bytes": int(1.5 * GIB), "used_bytes": 236 * GIB,
              "instruments_agree": True}
    before = {"label": "before", "volume": volume,
              "budget": {"required_gib": 14.564, "required_bytes": 15_637_000_000},
              "capacity": "INSUFFICIENT", "shortfall_bytes": 13 * GIB, "shortfall_gib": 13.0}
    (out / "SNAPSHOT_BEFORE.json").write_text(json.dumps(before), encoding="utf-8")
    (out / "SNAPSHOT_AFTER.json").write_text(json.dumps({**before, "label": "after"}), encoding="utf-8")
    (out / "VOLUME_INVENTORY.json").write_text(
        json.dumps({"rows": [{"path": "C:/Users/x/Downloads/tree", "bytes": 12 * GIB,
                              "newest_age_hours": 50.0}],
                    "volume": {"used_bytes": 236 * GIB}, "truncations": []}),
        encoding="utf-8",
    )
    (out / "CLEANUP_EVIDENCE.json").write_text(json.dumps({"deleted_gib": 0.001, "removed": [{"path": "x"}]}),
                                               encoding="utf-8")
    final = wp.report(out)
    assert final["verdict"] == "BLOCKED"
    assert final["capacity"]["verdict"] == "INSUFFICIENT"
    assert final["coverage_plan"]["gap_gib"] > 0


def test_report_passes_only_when_the_volume_holds_the_budget(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    volume = {"free_gib": 20.0, "free_bytes": 20 * GIB, "used_bytes": 200 * GIB, "instruments_agree": True}
    snapshot = {"label": "after", "volume": volume,
                "budget": {"required_gib": 14.564, "required_bytes": 15_637_000_000},
                "capacity": "PASS", "shortfall_bytes": 0, "shortfall_gib": 0.0, "headroom_bytes": 5 * GIB}
    (out / "SNAPSHOT_BEFORE.json").write_text(json.dumps({**snapshot, "label": "before"}), encoding="utf-8")
    (out / "SNAPSHOT_AFTER.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (out / "VOLUME_INVENTORY.json").write_text(
        json.dumps({"rows": [], "volume": {"used_bytes": 200 * GIB}, "truncations": []}), encoding="utf-8"
    )
    final = wp.report(out)
    assert final["verdict"] == "PASS"
    assert final["coverage_plan"]["selected"] == []


def test_final_report_keeps_the_defects_open(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "CAPACITY_RECOVERY.json").write_text(
        json.dumps({"verdict": "BLOCKED", "capacity": {"verdict": "INSUFFICIENT", "free_gib": 1.5,
                                                        "required_gib": 14.564, "shortfall_gib": 13.066},
                    "coverage_plan": {"selected": [], "selected_gib": 0, "gap_gib": 13.066,
                                      "target_gib": 14.066},
                    "authorisation_request": {"items": []}}),
        encoding="utf-8",
    )
    payload = wp.final_report(out)
    ids = {row["id"] for row in payload["open_defects"]}
    assert {"DEF-02I-07", "DEF-02I-08", "ALERT_REMOTE"}.issubset(ids)
    assert all(row["status"] == "OPEN" for row in payload["open_defects"])
    assert payload["verdict"] == "BLOCKED"


def test_contract_reads_the_frozen_window():
    state = wp.contract_state()
    assert state["window_matches"] is True
    assert state["rows_match"] is True
    assert state["git_diff_empty"] is True
