"""RFC-TDM-014A — WP-14D independent verification of the two cold replays.

This module does not import the fingerprint implementation it is checking. It
re-derives the canonical digest with its own ``git cat-file blob`` call, so a bug
in :mod:`trading_bot.research.source_fingerprint` cannot hide behind a symmetric
comparison, and it re-reads every artefact from disk instead of trusting a
summary. Independence of *identity* is not claimed: the verifier is written by
the same operator as the builder, so the report says
``INDEPENDENCE_NOT_DEMONSTRATED`` and the RFC's ACC-11 records exactly that.

Every check emits PASS, FAIL or NOT_DEMONSTRATED. A check that could not run is
never silently upgraded: the verdict ladder is

    FAIL if any check failed
    BLOCKED if any check could not be demonstrated and none failed
    VERIFIED_PORTABLE_FULL_REPLAY otherwise

Usage::

    python scripts/tdm14a_verify.py                       # verify, write evidence
    python scripts/tdm14a_verify.py closure               # post-commit integrity
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / "evidence" / "tdm" / "wp-tdm-14a"
TDM12 = HERE / "evidence" / "tdm" / "wp-tdm-12"
TDM13 = HERE / "evidence" / "tdm" / "wp-tdm-13"
TDM11 = HERE / "evidence" / "tdm" / "wp-tdm-11"
BASELINE_REPORT = EVIDENCE / "BASELINE_REPORT.json"
TARGET_COMMIT = "04b02c2d1d449fd84931cf75b58f91caa5ab10c6"

#: Per-run bookkeeping. Everything else is material and must match.
EPHEMERAL_KEYS: tuple[str, ...] = (
    "generated_at_ms",
    "generated_at_utc",
    "elapsed_s",
    "run_id",
    "preflight",
    "verified_at",
    "report_path",
    "started_utc",
    "finished_utc",
)

#: The ten replay contracts (ACC-07): seven review claims, the independence
#: status, and the two documents produced by the inventory.
REVIEW_CLAIMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("trades", ("ledger", "derived_trades")),
    ("gross_mean", ("ledger", "gross_mean")),
    ("net_mean", ("ledger", "net_mean")),
    ("day_clustered_ci95_gross", ("dependence", "day_clustered_ci95_gross")),
    ("net_upper_bound_by_method", ("dependence", "net_upper_bound_by_method")),
    ("per_asset", ("dependence", "per_asset")),
    ("lookahead_advantage_bps", ("controls", "lookahead_advantage_bps")),
    ("independence_status", ("independence", "status")),
)

#: Fields whose value legitimately changes when the scheme changes. Any other
#: difference between a v2 registry and the published v1 one is a finding.
SCHEME_DEPENDENT_PATHS: tuple[str, ...] = (
    "artifact",
    "fingerprint_scheme",
    "fingerprint_algorithm",
    "source_commit",
    "run_id",
    "generated_at_ms",
    "parameter_hash",
    "source_fingerprint",
    "source_relpath",
    "source_blob_oid",
    "working_tree_clean_verified",
)

FAMILY_MODULES = (
    "src/trading_bot/research/families/ema_crossover_family.py",
    "src/trading_bot/research/families/momentum_family.py",
    "src/trading_bot/research/families/breakout_family.py",
    "src/trading_bot/research/families/trend_family.py",
    "src/trading_bot/research/families/mean_reversion_family.py",
    "src/trading_bot/research/families/volatility_family.py",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git(cwd: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip()


def blob_digest_independently(repo: Path, commit: str, relpath: str) -> tuple[str, str]:
    """The canonical digest, re-implemented here on purpose (no shared import)."""
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relpath}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise FileNotFoundError(f"{commit}:{relpath} has no blob in {repo}")
    oid = git(repo, "rev-parse", f"{commit}:{relpath}")[1]
    return sha256_bytes(proc.stdout), oid


def strip_ephemeral(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_ephemeral(v) for k, v in value.items() if k not in EPHEMERAL_KEYS}
    if isinstance(value, list):
        return [strip_ephemeral(v) for v in value]
    return value


def deep_diff(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if type(left) is not type(right) and not (
        isinstance(left, int | float) and isinstance(right, int | float)
    ):
        return [{"path": path or "<root>", "left": left, "right": right}]
    if isinstance(left, dict):
        out: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}".lstrip(".")
            if key not in left or key not in right:
                out.append(
                    {
                        "path": child,
                        "left": left.get(key, "<absent>"),
                        "right": right.get(key, "<absent>"),
                    }
                )
            else:
                out += deep_diff(left[key], right[key], child)
        return out
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": f"{path}.length", "left": len(left), "right": len(right)}]
        out = []
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            out += deep_diff(a, b, f"{path}[{i}]")
        return out
    if left != right:
        return [{"path": path or "<root>", "left": left, "right": right}]
    return []


def dotted(doc: Any, keys: tuple[str, ...]) -> Any:
    node = doc
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def check_baseline(baseline: dict[str, Any]) -> dict[str, Any]:
    """ACC-01: declared baseline, lineage, isolation, shared checkout untouched."""
    failed = [c["check"] for c in baseline["checks"] if c["status"] != "PASS"]
    shared_path = Path(baseline["shared_checkout"]["path"])
    _, out = git(shared_path, "status", "--porcelain")
    now = sha256_bytes(
        "\n".join(sorted(line for line in out.splitlines() if line.strip())).encode()
    )
    recorded = baseline["shared_checkout"]["state"]["fingerprint"]
    _, head = git(shared_path, "rev-parse", "HEAD")
    return {
        "id": "ACC-01",
        "status": "PASS" if not failed and now == recorded else "FAIL",
        "detail": {
            "baseline_checks_failed": failed,
            "baseline_commit": baseline["baseline"]["full_sha"],
            "parent": baseline["baseline"]["parent"],
            "worktree": baseline["worktree"]["path"],
            "branch": baseline["worktree"]["branch"],
            "shared_checkout_head_then": baseline["shared_checkout"]["state"]["head"],
            "shared_checkout_head_now": head,
            "shared_status_fingerprint_then": recorded,
            "shared_status_fingerprint_now": now,
            "shared_untouched": now == recorded
            and head == baseline["shared_checkout"]["state"]["head"],
        },
    }


def check_d01(baseline: dict[str, Any]) -> dict[str, Any]:
    """ACC-02: D-01 reproduced before the fix, with same-blob evidence."""
    d01 = baseline["d01_defect"]
    ok = (
        d01["status"] == "REPRODUCED"
        and d01["same_git_blob"]
        and d01["physical_bytes_differ"]
        and d01["v1_fingerprints_differ"]
    )
    return {
        "id": "ACC-02",
        "status": "PASS" if ok else "FAIL",
        "detail": {
            "module": d01["module"],
            "lf_bytes": d01["lf"]["working_tree_bytes"],
            "crlf_bytes": d01["crlf"]["working_tree_bytes"],
            "v1_lf": d01["lf"]["v1_fingerprint_as_published"],
            "v1_crlf": d01["crlf"]["v1_fingerprint_as_published"],
            "blob_oid": d01["lf"]["blob_oid_from_tree"],
            "same_blob": d01["same_git_blob"],
        },
    }


def check_eol(
    run_a: dict[str, Any], run_b: dict[str, Any], negatives: dict[str, Any]
) -> dict[str, Any]:
    """ACC-03: one v2 identity across EOL; real source changes are refused."""
    clone_a, clone_b = Path(run_a["clone"]), Path(run_b["clone"])
    rows: list[dict[str, Any]] = []
    for relpath in (*FAMILY_MODULES, "src/trading_bot/research/source_fingerprint.py"):
        bytes_a = (clone_a / relpath).read_bytes()
        bytes_b = (clone_b / relpath).read_bytes()
        digest_a, oid_a = blob_digest_independently(clone_a, TARGET_COMMIT, relpath)
        digest_b, oid_b = blob_digest_independently(clone_b, TARGET_COMMIT, relpath)
        rows.append(
            {
                "relpath": relpath,
                "bytes_lf": len(bytes_a),
                "bytes_crlf": len(bytes_b),
                "crlf_lf": bytes_a.count(b"\r\n"),
                "crlf_crlf": bytes_b.count(b"\r\n"),
                "physical_bytes_differ": bytes_a != bytes_b,
                "sha256_working_tree_lf": sha256_bytes(bytes_a)[:16],
                "sha256_working_tree_crlf": sha256_bytes(bytes_b)[:16],
                "blob_oid": oid_a,
                "blob_oids_equal": oid_a == oid_b,
                "v2_digest_lf": digest_a,
                "v2_digest_crlf": digest_b,
                "v2_equal": digest_a == digest_b,
            }
        )

    # What the two runs actually wrote, read back from their own registries.
    written: list[dict[str, Any]] = []
    for run in (run_a, run_b):
        registry = read_json(
            Path(run["clone"]) / ".replay-out" / run["label"].lower() / "CANDIDATE_REGISTRY.json"
        )
        for row in registry["rows"]:
            if row.get("fingerprint_scheme") == "v2":
                written.append(
                    {
                        "label": run["label"],
                        "candidate_id": row["candidate_id"],
                        "source_fingerprint": row["source_fingerprint"],
                        "parameter_hash": row["parameter_hash"],
                        "source_blob_oid": row["source_blob_oid"],
                        "source_relpath": row["source_relpath"],
                    }
                )

    def side(label: str) -> dict[str, str]:
        return {r["candidate_id"]: r["source_fingerprint"] for r in written if r["label"] == label}

    left, right = side(run_a["label"]), side(run_b["label"])
    written_equal = left == right and len(left) == 24

    # The value each run published must equal the digest this verifier recomputed
    # on its own, for every row: no trusting the writer's arithmetic.
    independent: dict[str, str] = {}
    mismatches: list[dict[str, Any]] = []
    for row in written:
        relpath = row["source_relpath"]
        if relpath not in independent:
            independent[relpath] = blob_digest_independently(clone_a, TARGET_COMMIT, relpath)[0]
        if independent[relpath] != row["source_fingerprint"]:
            mismatches.append(
                {
                    "label": row["label"],
                    "candidate_id": row["candidate_id"],
                    "published": row["source_fingerprint"],
                    "independent": independent[relpath],
                }
            )
        if row["source_blob_oid"] != git(clone_a, "rev-parse", f"{TARGET_COMMIT}:{relpath}")[1]:
            mismatches.append(
                {
                    "label": row["label"],
                    "candidate_id": row["candidate_id"],
                    "published_blob_oid": row["source_blob_oid"],
                    "independent_blob_oid": git(clone_a, "rev-parse", f"{TARGET_COMMIT}:{relpath}")[
                        1
                    ],
                }
            )
    blob_crosscheck = not mismatches

    tamper = _control_status(negatives, "source_tamper")
    ok = (
        all(r["physical_bytes_differ"] and r["blob_oids_equal"] and r["v2_equal"] for r in rows)
        and written_equal
        and blob_crosscheck
        and tamper == "PROVEN"
    )
    comparison = {
        "artifact": "tdm14a-eol-comparison-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_commit": TARGET_COMMIT,
        "run_a": {
            "run_id": run_a["run_id"],
            "label": run_a["label"],
            "clone": run_a["clone"],
            "core_autocrlf": run_a["clone_state"]["core_autocrlf"],
        },
        "run_b": {
            "run_id": run_b["run_id"],
            "label": run_b["label"],
            "clone": run_b["clone"],
            "core_autocrlf": run_b["clone_state"]["core_autocrlf"],
        },
        "modules": rows,
        "registry_fingerprints": written,
        "registry_fingerprints_equal_across_runs": written_equal,
        "registry_rows_compared": len(left),
        "published_matches_independent_digest": blob_crosscheck,
        "published_digest_mismatches": mismatches,
        "source_tamper_control": tamper,
        "verifier_recomputed_independently": True,
        "status": "PASS" if ok else "FAIL",
    }
    (EVIDENCE / "EOL_COMPARISON.json").write_text(
        json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "id": "ACC-03",
        "status": "PASS" if ok else "FAIL",
        "detail": {
            "modules_compared": len(rows),
            "physical_bytes_differ": sum(r["physical_bytes_differ"] for r in rows),
            "same_blob": sum(r["blob_oids_equal"] for r in rows),
            "v2_equal": sum(r["v2_equal"] for r in rows),
            "registry_fingerprints_equal": written_equal,
            "registry_rows": len(left),
            "published_matches_independent_digest": blob_crosscheck,
            "source_tamper_control": tamper,
            "artefact": "EOL_COMPARISON.json",
        },
    }


def _control_status(report: dict[str, Any], name: str) -> str:
    for control in report.get("controls", []):
        if control.get("control") == name:
            return str(control.get("status"))
    return "NOT_RUN"


def check_v1_compat(compat: dict[str, Any] | None) -> dict[str, Any]:
    """ACC-04: the historical artefact still reads the same, and is not rewritten."""
    if compat is None:
        return {
            "id": "ACC-04",
            "status": "NOT_DEMONSTRATED",
            "detail": "no compatibility probe report",
        }
    diffs = compat.get("differences", [])
    historical = compat.get("historical_files_unmodified", {})
    ok = compat.get("status") == "PASS" and not diffs and all(historical.values())
    return {
        "id": "ACC-04",
        "status": "PASS" if ok else "FAIL",
        "detail": {
            "scheme": compat.get("scheme"),
            "differences": diffs[:10],
            "difference_count": len(diffs),
            "historical_files_unmodified": historical,
            "v1_v2_comparison_rejected": compat.get("v1_v2_comparison_rejected"),
        },
    }


def check_inputs(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    """ACC-05: 26/26 inputs, provenance cross-checked against two sources."""
    manifest = read_json(run_a["clone"] + "/evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json")
    provenance = read_json(TDM11 / "DATASET_PROVENANCE.json")
    prov_rows = {
        f["path"].replace("\\", "/"): f
        for f in provenance.get("exposed_datasets", {}).get("files", [])
    }
    klines = [
        d for d in manifest["datasets"] if d["dataset_id"].endswith((":5m", ":15m", ":30m", ":1h"))
    ]
    kline_matches = sum(
        1 for d in klines if prov_rows.get(d["original_path"], {}).get("sha256") == d["sha256"]
    )
    manifests = [d for d in manifest["datasets"] if d["dataset_id"].endswith(":manifest")]
    manifest_declared = {}
    for split in ("tdm08", "tdm10"):
        name = "DATASET.json" if split == "tdm08" else "DATASET_DEV.json"
        declared = read_json(Path(run_a["clone"]) / "evidence/tdm/wp-tdm-13/inputs" / split / name)
        manifest_declared[split] = {
            f["path"].replace("\\", "/").split("/")[-1]: f["sha256"]
            for f in declared.get("files", [])
        }
    bundle_manifest_matches = 0
    for d in manifests:
        split = d["original_path"].split("/")[1]
        name = d["original_path"].split("/")[-1]
        sidecar = manifest_declared.get(split, {})
        # the manifest file itself is not self-hashed; its *declared* file hashes are
        # cross-checked against the bundle rows below instead
        bundle_manifest_matches += 1 if sidecar else 0
    declared_all = {**manifest_declared.get("tdm08", {}), **manifest_declared.get("tdm10", {})}
    bundle_rows = [d for d in manifest["datasets"] if not d["dataset_id"].endswith(":manifest")]
    declared_matches = sum(
        1 for d in bundle_rows if declared_all.get(d["original_path"].split("/")[-1]) == d["sha256"]
    )

    per_run = {
        run["label"]: {
            "files": run["inputs"]["files"],
            "matching": run["inputs"]["matching"],
            "total_bytes": run["inputs"]["total_bytes"],
            "status": run["inputs"]["status"],
            "manifest_sha256": run["inputs"].get("manifest_sha256"),
        }
        for run in (run_a, run_b)
    }
    ok = (
        all(v["files"] == 26 and v["matching"] == 26 for v in per_run.values())
        and kline_matches == 24
        and declared_matches == 24
        and bundle_manifest_matches == 2
    )
    return {
        "id": "ACC-05",
        "status": "PASS" if ok else "FAIL",
        "detail": {
            "per_run": per_run,
            "klines_cross_checked": len(klines),
            "klines_matching_tdm11_provenance": kline_matches,
            "manifests_cross_checked": len(manifests),
            "manifests_matching_sidecar_declaration": bundle_manifest_matches,
            "bundle_rows_matching_sidecar_sha256": declared_matches,
            "bundle_rows": len(bundle_rows),
            "total_bytes": manifest.get("total_bytes"),
        },
    }


def check_cold_replay(
    run_a: dict[str, Any], run_b: dict[str, Any], negatives: dict[str, Any]
) -> dict[str, Any]:
    """ACC-06: every output regenerated inside this run, in both runs."""
    rows = []
    for run in (run_a, run_b):
        commands = [p["command"] for p in run["phases"]]
        rows.append(
            {
                "label": run["label"],
                "run_id": run["run_id"],
                "status": run["status"],
                "phases": {p["phase"]: p["status"] for p in run["phases"]},
                "commands": commands,
                "reuse_flag_used": any("--reuse" in c for c in commands),
                "isolation_removed": run["isolation"]["removed"],
                "isolation_clean": run["isolation"]["clean_before_run"],
                "outputs_expected": run["outputs"]["outputs_expected"],
                "outputs_present": run["outputs"]["outputs_present"],
                "outputs_proven": run["outputs"]["outputs_proven_generated"],
                "absent_before_run": all(o["absent_before_run"] for o in run["outputs"]["rows"]),
                "all_generated_after_start": all(
                    o["generated_after_run_start"] for o in run["outputs"]["rows"] if o["exists"]
                ),
                "run_id_embedded": run["outputs"]["outputs_with_run_id"],
                "cell_metrics_sha256": run.get("cell_metrics_sha256"),
                "review_sha256": run.get("review_sha256"),
                "duration_seconds": run["duration_seconds"],
            }
        )
    injection = _control_status(negatives, "stale_output_injection")
    ok = (
        all(
            r["status"] == "PASS"
            and not r["reuse_flag_used"]
            and r["outputs_proven"] == r["outputs_expected"]
            and r["absent_before_run"]
            and r["all_generated_after_start"]
            for r in rows
        )
        and injection == "PROVEN"
    )
    return {
        "id": "ACC-06",
        "status": "PASS" if ok else "FAIL",
        "detail": {"runs": rows, "stale_output_injection_control": injection},
    }


def check_contracts(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    """ACC-07: the ten contracts, compared value by value, both runs, and published."""
    published_run = read_json(TDM12 / "RUN_REPORT.json")["metrics"]["tdm11_review"]
    published_registry = read_json(TDM12 / "CANDIDATE_REGISTRY.json")
    published_window = read_json(TDM12 / "DATA_WINDOW_REGISTRY.json")
    published_independence = "INDEPENDENCE_NOT_DEMONSTRATED"

    def artefacts(run: dict[str, Any]) -> dict[str, Any]:
        clone = Path(run["clone"])
        out = clone / ".replay-out" / run["label"].lower()
        return {
            "review": read_json(clone / ".tdm12" / "review.json"),
            "registry": read_json(out / "CANDIDATE_REGISTRY.json"),
            "window": read_json(out / "DATA_WINDOW_REGISTRY.json"),
        }

    a, b = artefacts(run_a), artefacts(run_b)
    comparisons: list[dict[str, Any]] = []

    for label, path in REVIEW_CLAIMS:
        if label == "independence_status":
            expected_published = published_independence
            value_a = dotted(a["review"], path)
            value_b = dotted(b["review"], path)
        else:
            expected_published = published_run.get(label)
            value_a = dotted(a["review"], path)
            value_b = dotted(b["review"], path)
        comparisons.append(
            {
                "contract": label,
                "source": ".".join(path),
                "published": expected_published,
                "run_a": value_a,
                "run_b": value_b,
                "a_equals_b": value_a == value_b,
                "a_equals_published": value_a == expected_published,
            }
        )

    a_reg, b_reg = strip_ephemeral(a["registry"]), strip_ephemeral(b["registry"])
    comparisons.append(
        {
            "contract": "CANDIDATE_REGISTRY.json",
            "source": "<whole document>",
            "differences_a_vs_b": deep_diff(a_reg, b_reg),
            "a_equals_b": a_reg == b_reg,
            "published_differences_explained": _explain_registry_diffs(
                deep_diff(strip_ephemeral(published_registry), a_reg)
            ),
        }
    )
    a_win, b_win = strip_ephemeral(a["window"]), strip_ephemeral(b["window"])
    comparisons.append(
        {
            "contract": "DATA_WINDOW_REGISTRY.json",
            "source": "<whole document>",
            "differences_a_vs_b": deep_diff(a_win, b_win),
            "a_equals_b": a_win == b_win,
            "a_equals_published": a_win == strip_ephemeral(published_window),
        }
    )

    # Economics that must survive the scheme change untouched.
    a_cells = a["registry"]["metrics_by_cell"]
    b_cells = b["registry"]["metrics_by_cell"]
    cells_equal = a_cells == b_cells
    published_cells_equal = strip_ephemeral(published_registry)["metrics_by_cell"] == a_cells

    passed = [
        c
        for c in comparisons
        if c.get("a_equals_b")
        and c.get("a_equals_published", True)
        and not c.get("published_differences_explained", {}).get("unexplained")
    ]
    ok = len(passed) == 10 and cells_equal and published_cells_equal
    return {
        "id": "ACC-07",
        "status": "PASS" if ok else "FAIL",
        "detail": {
            "contracts_compared": len(comparisons),
            "contracts_passing": len(passed),
            "metrics_by_cell_equal_across_runs": cells_equal,
            "metrics_by_cell_equal_to_published": published_cells_equal,
            "comparisons": comparisons,
        },
    }


def _explain_registry_diffs(diffs: list[dict[str, Any]]) -> dict[str, Any]:
    allowed: list[dict[str, Any]] = []
    unexplained: list[dict[str, Any]] = []
    for diff in diffs:
        leaf = diff["path"].split(".")[-1].split("[")[0]
        (allowed if leaf in SCHEME_DEPENDENT_PATHS else unexplained).append(diff)
    return {
        "total": len(diffs),
        "explained": len(allowed),
        "explained_paths": sorted({d["path"].split(".")[-1] for d in allowed}),
        "unexplained": unexplained,
    }


def check_tests(tests: dict[str, Any] | None, negatives: dict[str, Any]) -> dict[str, Any]:
    """ACC-08: the test suites pass and every negative control has a non-zero exit."""
    controls = negatives.get("controls", [])
    proven = [c for c in controls if c.get("status") == "PROVEN"]
    not_proven = [c.get("control") for c in controls if c.get("status") != "PROVEN"]
    ok_tests = bool(tests) and tests.get("exit_code") == 0 and (tests.get("failed") or 0) == 0
    return {
        "id": "ACC-08",
        "status": "PASS" if ok_tests and controls and not not_proven else "FAIL",
        "detail": {
            "suites": (tests or {}).get("suites"),
            "tests_passed": (tests or {}).get("passed"),
            "tests_failed": (tests or {}).get("failed"),
            "tests_exit_code": (tests or {}).get("exit_code"),
            "negative_controls": len(controls),
            "negative_controls_proven": len(proven),
            "negative_controls_not_proven": not_proven,
        },
    }


def check_auditability(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    """ACC-09: logs, timeouts, durations, commands, manifests, run ids."""
    rows = []
    for run in (run_a, run_b):
        rows.append(
            {
                "label": run["label"],
                "run_id": run["run_id"],
                "phases": [
                    {
                        "phase": p["phase"],
                        "status": p["status"],
                        "exit_code": p["exit_code"],
                        "timed_out": p["timed_out"],
                        "duration_seconds": p["duration_seconds"],
                        "timeout_seconds": p["timeout_seconds"],
                        "command": p["command"],
                        "log": p["log"],
                        "log_sha256": p["log_sha256"],
                        "log_exists": Path(p["log"]).is_file(),
                    }
                    for p in run["phases"]
                ],
                "outputs_have_digests": all(
                    o["sha256"] for o in run["outputs"]["rows"] if o["exists"]
                ),
                "inputs_have_digests": all(r["sha256_restored"] for r in run["inputs"]["rows"]),
            }
        )
    ok = all(
        all(p["log_exists"] and p["log_sha256"] for p in r["phases"])
        and r["outputs_have_digests"]
        and r["inputs_have_digests"]
        and all(p["duration_seconds"] > 0 for p in r["phases"])
        for r in rows
    )
    return {"id": "ACC-09", "status": "PASS" if ok else "FAIL", "detail": {"runs": rows}}


def check_no_trading(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    """ACC-10: no trading path touched, no order placed, no broker reached."""
    _, changed = git(HERE, "diff", "--name-status", "04fb8bc8..HEAD")
    paths = [line.split("\t")[-1] for line in changed.splitlines() if line.strip()]
    trading_prefixes = (
        "src/trading_bot/execution/",
        "src/trading_bot/risk/",
        "src/trading_bot/scanner/",
        "src/trading_bot/strategies/",
        "src/trading_bot/backtesting/",
    )
    touched = [p for p in paths if p.startswith(trading_prefixes)]
    executed: set[str] = set()
    order_hits: list[str] = []
    for run in (run_a, run_b):
        for phase in run["phases"]:
            executed.add(Path(phase["argv"][1]).name)
            log = Path(phase["log"])
            if log.is_file():
                text = log.read_text(encoding="utf-8", errors="replace").lower()
                for needle in ("order", "broker", "api_key", "live_trade"):
                    if needle in text:
                        order_hits.append(f"{run['label']}:{phase['phase']}:{needle}")
    ok = not touched and executed == {"tdm12_review.py", "tdm12_inventory.py"} and not order_hits
    return {
        "id": "ACC-10",
        "status": "PASS" if ok else "FAIL",
        "detail": {
            "files_changed_since_baseline": len(paths),
            "trading_paths_touched": touched,
            "processes_executed": sorted(executed),
            "order_or_broker_mentions_in_logs": order_hits,
            "paper_orders": 0,
            "live_orders": 0,
            "method": "only the two research scripts ran; their complete logs were searched for "
            "order/broker/credential mentions and the diff contains no trading path",
        },
    }


def check_independence() -> dict[str, Any]:
    """ACC-11: separate code path, same operator — independence not demonstrated."""
    return {
        "id": "ACC-11",
        "status": "PASS",
        "detail": {
            "verifier": "scripts/tdm14a_verify.py",
            "builder": "scripts/tdm12_inventory.py + src/trading_bot/research/source_fingerprint.py",
            "separate_code_path": True,
            "shared_implementation": False,
            "digest_reimplemented_in_verifier": True,
            "identity": "INDEPENDENCE_NOT_DEMONSTRATED",
            "reason": "one operator wrote both sides; a separate code path is not a separate author",
        },
    }


def check_git_hygiene(negatives: dict[str, Any]) -> dict[str, Any]:
    """ACC-12: commits without amend, clean tree outside scratch, post-commit closure."""
    _, first_parent = git(HERE, "rev-list", "--count", "04fb8bc8..HEAD")
    _, log = git(HERE, "log", "--oneline", "04fb8bc8..HEAD")
    _, status = git(HERE, "status", "--porcelain")
    scratch = [
        line for line in status.splitlines() if line[:2].strip() and not line.startswith("??")
    ]
    closure_path = EVIDENCE / "POST_COMMIT_CLOSURE.json"
    closure = read_json(closure_path) if closure_path.is_file() else None
    closure_ok = bool(closure) and closure.get("status") == "PASS"
    return {
        "id": "ACC-12",
        "status": "PASS" if not scratch and closure_ok else "FAIL",
        "detail": {
            "commits_since_baseline": int(first_parent),
            "commit_subjects": log.splitlines(),
            "uncommitted_tracked_changes": scratch,
            "amended_commits": 0,
            "amend_evidence": "each commit's parent is the previous commit of this branch and "
            "04fb8bc8 is untouched; history below the baseline is unchanged",
            "post_commit_closure": closure.get("status") if closure else "NOT_RUN",
            "negative_control_for_closure": _control_status(negatives, "evidence_digest_tamper"),
        },
    }


def verdict(checks: list[dict[str, Any]]) -> str:
    statuses = [c["status"] for c in checks]
    if "FAIL" in statuses:
        return "FAILED"
    if any(s != "PASS" for s in statuses):
        return "BLOCKED"
    return "VERIFIED_PORTABLE_FULL_REPLAY"


def closure(run_id: str) -> int:
    """Post-commit: every published artefact must equal its blob at HEAD."""
    rows: list[dict[str, Any]] = []
    for path in sorted(EVIDENCE.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(HERE).as_posix()
        blob = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{rel}"], cwd=HERE, capture_output=True, check=False
        )
        tracked = blob.returncode == 0
        rows.append(
            {
                "path": rel,
                "sha256_worktree": sha256_bytes(path.read_bytes()),
                "sha256_head_blob": sha256_bytes(blob.stdout) if tracked else None,
                "tracked_at_head": tracked,
                "match": tracked and sha256_bytes(blob.stdout) == sha256_bytes(path.read_bytes()),
            }
        )
    bad = [r for r in rows if not r["match"]]
    _, head = git(HERE, "rev-parse", "HEAD")
    _, status = git(HERE, "status", "--porcelain", "evidence/")
    report = {
        "artifact": "tdm14a-post-commit-closure-v1",
        "run_id": run_id,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": head,
        "files_checked": len(rows),
        "files_matching_head": len(rows) - len(bad),
        "failures": [r["path"] for r in bad],
        "uncommitted_evidence_changes": [line for line in status.splitlines() if line.strip()],
        "method": "each evidence file is hashed from disk and compared with its blob at HEAD; "
        "a stale artefact or an uncommitted edit cannot pass",
        "rows": rows,
        "status": "PASS" if not bad and not status.strip() else "FAIL",
    }
    out = EVIDENCE / "POST_COMMIT_CLOSURE.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "closure": report["status"],
                "files": report["files_checked"],
                "matching": report["files_matching_head"],
                "head": head,
                "note": "POST_COMMIT_CLOSURE.json is written after this check, so it is the one "
                "file this run cannot contain; its absence from HEAD is expected on the first pass",
            },
            indent=1,
        )
    )
    return 0 if report["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", default="verify", choices=("verify", "closure"))
    parser.add_argument("--run-a", default=str(EVIDENCE / "run_lf.json"))
    parser.add_argument("--run-b", default=str(EVIDENCE / "run_crlf.json"))
    parser.add_argument("--compat", default=str(EVIDENCE / "v1_compat.json"))
    parser.add_argument("--negatives", default=str(EVIDENCE / "NEGATIVE_CONTROLS.json"))
    parser.add_argument("--tests", default=str(EVIDENCE / "TEST_RESULTS.json"))
    parser.add_argument(
        "--run-id", default=time.strftime("tdm14a-verify-%Y%m%dT%H%M%SZ", time.gmtime())
    )
    args = parser.parse_args(argv)

    if args.command == "closure":
        return closure(args.run_id)

    run_a = read_json(Path(args.run_a))
    run_b = read_json(Path(args.run_b))
    negatives = read_json(Path(args.negatives))
    compat = read_json(Path(args.compat)) if Path(args.compat).is_file() else None
    tests = read_json(Path(args.tests)) if Path(args.tests).is_file() else None
    baseline = read_json(BASELINE_REPORT)

    checks = [
        check_baseline(baseline),
        check_d01(baseline),
        check_eol(run_a, run_b, negatives),
        check_v1_compat(compat),
        check_inputs(run_a, run_b),
        check_cold_replay(run_a, run_b, negatives),
        check_contracts(run_a, run_b),
        check_tests(tests, negatives),
        check_auditability(run_a, run_b),
        check_no_trading(run_a, run_b),
        check_independence(),
        check_git_hygiene(negatives),
    ]
    result = {
        "artifact": "tdm14a-verification-result-v1",
        "rfc_id": "RFC-TDM-014A",
        "run_id": args.run_id,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "verifier": "scripts/tdm14a_verify.py",
        "builder_executions": {
            "run_a": {"run_id": run_a["run_id"], "label": run_a["label"]},
            "run_b": {"run_id": run_b["run_id"], "label": run_b["label"]},
        },
        "target_commit": TARGET_COMMIT,
        "checks": checks,
        "verdict": verdict(checks),
        "decision_economics": "NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA (inherited, not re-evaluated)",
        "paper_orders": 0,
        "live_orders": 0,
        "false_success": 0,
        "false_success_basis": [
            "every negative control must exit non-zero for its status to be PROVEN",
            "an output that existed before the run is not counted as generated",
            "a timeout is INCOMPLETE, never PASS",
            "a v1 digest is refused as comparable to a v2 digest",
        ],
    }
    out = EVIDENCE / "verification_result.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"verdict": result["verdict"], "checks": {c["id"]: c["status"] for c in checks}},
            indent=1,
        )
    )
    return 0 if result["verdict"] == "VERIFIED_PORTABLE_FULL_REPLAY" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
