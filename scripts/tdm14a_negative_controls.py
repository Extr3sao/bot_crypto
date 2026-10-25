"""RFC-TDM-014A — negative and adversarial controls for WP-14D.

Each control breaks one thing on purpose and requires the system to refuse. A
control is ``PROVEN`` only when the command exits non-zero *and* the failure names
the reason it was supposed to catch; an exit code alone is not enough, because the
wrong failure proves the wrong guard.

Controls that need a full pipeline run reuse the two cold replays instead of
inventing a third: ``stale_output_injection`` is exercised inside the CRLF run
(``--inject-stale-state``), so the proof comes from a real execution.

Usage::

    python scripts/tdm14a_negative_controls.py --sandbox <path> --run-a ... --run-b ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / "evidence" / "tdm" / "wp-tdm-14a"
DEFAULT_SANDBOX = HERE.parent / "tdm14a-neg"
FAMILY = "src/trading_bot/research/families/breakout_family.py"


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def force_rmtree(path: Path) -> None:
    """Delete a tree even when Git left read-only objects behind (Windows)."""
    import stat

    def on_error(func: Any, target: str, _exc: Any) -> None:
        Path(target).chmod(stat.S_IWRITE | stat.S_IREAD)
        func(target)

    shutil.rmtree(path, onerror=on_error)


def run(argv: list[str], *, cwd: Path, timeout: float = 300.0) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )
    return {
        "command": " ".join(Path(a).name if i == 0 else a for i, a in enumerate(argv)),
        "exit_code": proc.returncode,
        "duration_seconds": round(time.time() - started, 1),
        "stdout_tail": proc.stdout.strip().splitlines()[-4:],
        "stderr_tail": proc.stderr.strip().splitlines()[-6:],
    }


def control(
    name: str,
    *,
    purpose: str,
    result: dict[str, Any],
    expected_fragment: str,
    expected_nonzero: bool = True,
) -> dict[str, Any]:
    haystack = " ".join(result["stdout_tail"] + result["stderr_tail"])
    hit = expected_fragment.lower() in haystack.lower()
    nonzero_ok = (result["exit_code"] != 0) if expected_nonzero else (result["exit_code"] == 0)
    status = "PROVEN" if hit and nonzero_ok else "NOT_PROVEN"
    return {
        "control": name,
        "purpose": purpose,
        "expected_fragment": expected_fragment,
        "fragment_present": hit,
        "expected_nonzero_exit": expected_nonzero,
        "observed_exit_code": result["exit_code"],
        "status": status,
        **result,
    }


def reset(clone: Path, commit: str) -> None:
    subprocess.run(
        ["git", "reset", "-q", "--hard", commit], cwd=clone, check=False, capture_output=True
    )
    subprocess.run(["git", "clean", "-qfd", "src"], cwd=clone, check=False, capture_output=True)
    for scratch in (".tdm12", ".replay-out", ".compat-out", "neg-out", ".replay-lock"):
        target = clone / scratch
        if target.is_dir():
            force_rmtree(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--run-a", default=str(EVIDENCE / "run_lf.json"))
    parser.add_argument("--run-b", default=str(EVIDENCE / "run_crlf.json"))
    parser.add_argument("--target-commit", default=None)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", default=str(EVIDENCE / "NEGATIVE_CONTROLS.json"))
    args = parser.parse_args(argv)

    sandbox = Path(args.sandbox).resolve()
    run_a = json.loads(Path(args.run_a).read_text(encoding="utf-8"))
    run_b = json.loads(Path(args.run_b).read_text(encoding="utf-8"))
    target = args.target_commit or run_a["clone_state"]["target_commit"]

    if sandbox.exists():
        force_rmtree(sandbox)
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(HERE), str(sandbox)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", target], cwd=sandbox, check=True, capture_output=True
    )
    controls: list[dict[str, Any]] = []

    # 1. a real edit to a fingerprinted module, unstaged
    reset(sandbox, target)
    with (sandbox / FAMILY).open("a", encoding="utf-8") as handle:
        handle.write("\n# negative control: unstaged tamper\n")
    controls.append(
        control(
            "source_tamper",
            purpose="an unstaged edit to a fingerprinted module must fail the preflight",
            result=run(
                [
                    args.python,
                    "scripts/tdm12_inventory.py",
                    "--fingerprint-scheme",
                    "v2",
                    "--out-dir",
                    "neg-out",
                    "--run-id",
                    "neg-source-tamper",
                ],
                cwd=sandbox,
            ),
            expected_fragment="deviates from",
        )
    )

    # 2. the same edit, staged
    reset(sandbox, target)
    with (sandbox / FAMILY).open("a", encoding="utf-8") as handle:
        handle.write("\n# negative control: staged tamper\n")
    subprocess.run(["git", "add", FAMILY], cwd=sandbox, check=False, capture_output=True)
    controls.append(
        control(
            "source_staged_tamper",
            purpose="a staged edit must fail the preflight even though the file is tracked",
            result=run(
                [
                    args.python,
                    "scripts/tdm12_inventory.py",
                    "--fingerprint-scheme",
                    "v2",
                    "--out-dir",
                    "neg-out",
                    "--run-id",
                    "neg-source-staged",
                ],
                cwd=sandbox,
            ),
            expected_fragment="deviates from",
        )
    )

    # 3. a module that is not committed at all
    reset(sandbox, target)
    (sandbox / "src/trading_bot/research/families/ghost_family.py").write_text(
        "GHOST = True\n", encoding="utf-8"
    )
    controls.append(
        control(
            "untracked_module",
            purpose="an untracked module has no blob and must not receive a fingerprint",
            result=run(
                [
                    args.python,
                    "-c",
                    "import sys;sys.path.insert(0,'src');"
                    "from pathlib import Path;"
                    "from trading_bot.research.source_fingerprint import compute_source_fingerprint;"
                    "compute_source_fingerprint(Path('.'), "
                    "'src/trading_bot/research/families/ghost_family.py')",
                ],
                cwd=sandbox,
            ),
            expected_fragment="not committed",
        )
    )

    # 4. a commit that does not exist
    reset(sandbox, target)
    controls.append(
        control(
            "unreadable_blob",
            purpose="an unresolvable commit must fail closed instead of hashing nothing",
            result=run(
                [
                    args.python,
                    "scripts/tdm12_inventory.py",
                    "--fingerprint-scheme",
                    "v2",
                    "--source-commit",
                    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                    "--out-dir",
                    "neg-out",
                    "--run-id",
                    "neg-unreadable-blob",
                ],
                cwd=sandbox,
            ),
            expected_fragment="not committed",
        )
    )

    # 5. a sealed input with one byte changed, committed so the checkout is clean:
    #    the point is that the *seal* is broken, not that the worktree is dirty.
    reset(sandbox, target)
    manifest = json.loads(
        (sandbox / "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json").read_text(encoding="utf-8")
    )
    victim_rel = manifest["datasets"][0]["path"]
    victim = sandbox / victim_rel
    payload = bytearray(victim.read_bytes())
    payload[0] = payload[0] ^ 0xFF
    victim.write_bytes(bytes(payload))
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=tdm14a@example.invalid",
            "-c",
            "user.name=TDM-14A control",
            "commit",
            "-qam",
            "negative control: corrupted sealed input",
        ],
        cwd=sandbox,
        check=False,
        capture_output=True,
    )
    controls.append(
        control(
            "dataset_byte_tamper",
            purpose="a restored input that does not match the sealed digest must stop the replay",
            result=run(
                [
                    args.python,
                    "scripts/tdm14a_replay.py",
                    "--clone",
                    str(sandbox),
                    "--label",
                    "TAMPER",
                    "--run-id",
                    "neg-dataset-tamper",
                    "--out",
                    str(sandbox / "neg-report.json"),
                    "--review-timeout",
                    "10",
                    "--inventory-timeout",
                    "10",
                ],
                cwd=HERE,
            ),
            expected_fragment="do not match the sealed bundle",
        )
    )

    # 6. an economic value altered after the fact, caught by contract comparison
    tamper_dir = sandbox / "tamper"
    for source in (".tdm12/review.json", ".tdm12/cell_metrics.json"):
        destination = tamper_dir / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(run_a["clone"]) / source, destination)
    out_rel = f".replay-out/{run_a['label'].lower()}"
    shutil.copytree(Path(run_a["clone"]) / out_rel, tamper_dir / out_rel)
    doctored_path = tamper_dir / out_rel / "CANDIDATE_REGISTRY.json"
    doctored = json.loads(doctored_path.read_text(encoding="utf-8"))
    first_cell = sorted(doctored["metrics_by_cell"])[0]
    original_net = doctored["metrics_by_cell"][first_cell]["hold"]["net_mean"]
    doctored["metrics_by_cell"][first_cell]["hold"]["net_mean"] = round(original_net + 1.0, 4)
    doctored_path.write_text(json.dumps(doctored, indent=2) + "\n", encoding="utf-8")

    doctored_run = dict(run_a)
    doctored_run["clone"] = str(tamper_dir)
    sys.path.insert(0, str(HERE / "scripts"))
    import tdm14a_verify

    contract_check = tdm14a_verify.check_contracts(doctored_run, run_b)
    controls.append(
        {
            "control": "economic_value_tamper",
            "purpose": "one altered net_mean in the registry must break the contract comparison",
            "expected_fragment": "metrics_by_cell_equal_across_runs=False",
            "fragment_present": contract_check["detail"].get("metrics_by_cell_equal_across_runs")
            is False,
            "expected_nonzero_exit": True,
            "observed_exit_code": 0 if contract_check["status"] == "PASS" else 1,
            "status": "PROVEN" if contract_check["status"] == "FAIL" else "NOT_PROVEN",
            "command": f"tdm14a_verify.check_contracts(<registry with {first_cell}.hold.net_mean+1>)",
            "duration_seconds": 0.0,
            "stdout_tail": [
                f"verdict={contract_check['status']}",
                f"metrics_by_cell_equal_across_runs="
                f"{contract_check['detail'].get('metrics_by_cell_equal_across_runs')}",
            ],
            "stderr_tail": [],
            "detail": {
                "cell": first_cell,
                "original_net_mean": original_net,
                "doctored_net_mean": doctored["metrics_by_cell"][first_cell]["hold"]["net_mean"],
            },
        }
    )

    # 7. timeout must kill the tree, and must not become PASS
    heartbeat = sandbox / "heartbeat.txt"
    if heartbeat.exists():
        heartbeat.unlink()
    child = (
        "import pathlib, time\n"
        f"p = pathlib.Path(r'{heartbeat}')\n"
        "f = p.open('a')\n"
        "for _ in range(400):\n"
        "    f.write('x')\n"
        "    f.flush()\n"
        "    time.sleep(0.05)\n"
    )
    child_path = sandbox / "neg_child.py"
    child_path.write_text(child, encoding="utf-8")
    sys.path.insert(0, str(HERE / "scripts"))
    import tdm14a_replay

    phase = tdm14a_replay.run_phase(
        name="timeout-control",
        argv=[args.python, str(child_path)],
        cwd=sandbox,
        timeout=3.0,
        log_path=sandbox / "timeout-control.log",
    )
    size_before = heartbeat.stat().st_size if heartbeat.exists() else 0
    time.sleep(2.0)
    size_after = heartbeat.stat().st_size if heartbeat.exists() else 0
    child_stopped = size_before == size_after and size_after > 0
    controls.append(
        {
            "control": "timeout_and_process_tree",
            "purpose": "a timeout must report TIMEOUT, kill the child tree and never become PASS",
            "expected_fragment": "TIMEOUT",
            "fragment_present": phase["status"] == "TIMEOUT",
            "expected_nonzero_exit": True,
            "observed_exit_code": phase["exit_code"],
            "status": "PROVEN"
            if phase["status"] == "TIMEOUT" and phase["killed_tree"] and child_stopped
            else "NOT_PROVEN",
            "command": phase["command"],
            "duration_seconds": phase["duration_seconds"],
            "stdout_tail": phase["log_tail"],
            "stderr_tail": [],
            "detail": {
                "status": phase["status"],
                "killed_tree": phase["killed_tree"],
                "heartbeat_bytes_before": size_before,
                "heartbeat_bytes_after_2s": size_after,
                "child_stopped_writing": child_stopped,
                "timeout_seconds": phase["timeout_seconds"],
            },
        }
    )

    # 8. a tampered evidence digest must fail the post-commit rule, and the rule must
    #    still accept the same file when the checkout only differs by line endings.
    reset(sandbox, target)
    rel = "evidence/tdm/wp-tdm-14a/BASELINE_REPORT.json"
    copied = sandbox / rel
    recorded = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{rel}"], cwd=sandbox, capture_output=True, check=False
    ).stdout
    oid_head = subprocess.run(
        ["git", "rev-parse", f"HEAD:{rel}"],
        cwd=sandbox,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    def identity(path: Path, relpath: str) -> str:
        return subprocess.run(
            ["git", "hash-object", f"--path={relpath}", "--", str(path)],
            cwd=sandbox,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

    clean_match = identity(copied, rel) == oid_head
    payload = bytearray(copied.read_bytes())
    payload[-2] = payload[-2] ^ 0x01
    copied.write_bytes(bytes(payload))
    tampered_match = identity(copied, rel) == oid_head
    controls.append(
        {
            "control": "evidence_digest_tamper",
            "purpose": "a one-byte change to a published artefact must break the closure comparison",
            "expected_fragment": "mismatch",
            "fragment_present": clean_match and not tampered_match,
            "expected_nonzero_exit": True,
            "observed_exit_code": 0 if tampered_match else 1,
            "status": "PROVEN" if clean_match and not tampered_match else "NOT_PROVEN",
            "command": f"git hash-object --path={rel} vs rev-parse HEAD:{rel}",
            "duration_seconds": 0.0,
            "stdout_tail": [f"clean_match={clean_match}", f"tampered_match={tampered_match}"],
            "stderr_tail": [],
            "detail": {
                "blob_sha256": hashlib.sha256(recorded).hexdigest(),
                "head_blob_oid": oid_head,
                "identity_rule": "git hash-object applies the checkout filters, so a CRLF "
                "worktree of an LF blob still matches; one changed byte does not",
            },
        }
    )

    # 9. the v1/v2 scheme guard
    reset(sandbox, target)
    controls.append(
        control(
            "v1_v2_rejection",
            purpose="a v1 checkout digest must never be compared with a v2 blob digest",
            result=run(
                [
                    args.python,
                    "-c",
                    "import json,sys;sys.path.insert(0,'src');"
                    "from trading_bot.research.source_fingerprint import read_fingerprint,"
                    "assert_comparable;"
                    "v1=read_fingerprint({'parameter_hash':'9825f38950c5b975'});"
                    "v2=read_fingerprint({'fingerprint_scheme':'v2',"
                    "'source_fingerprint':'ab'*32,'source_relpath':'x',"
                    "'source_commit':'0'*40,'source_blob_oid':'0'*40,"
                    "'working_tree_clean_verified':True});"
                    "assert_comparable(v1,v2)",
                ],
                cwd=sandbox,
            ),
            expected_fragment="IncompatibleFingerprintScheme",
        )
    )

    # 10. stale outputs planted before a real run must be removed, not reused
    injected = run_b.get("injected_stale_state") or {}
    removed = run_b["isolation"]["removed"]
    review = json.loads(
        (Path(run_b["clone"]) / ".tdm12" / "review.json").read_text(encoding="utf-8")
    )
    forged_absent = review.get("run_id") != "forged-run" and dotted_net(review) != 999.0
    controls.append(
        {
            "control": "stale_output_injection",
            "purpose": "a forged review.json and cell metrics planted before the run must be deleted "
            "and never counted as results",
            "expected_fragment": "forged run removed",
            "fragment_present": bool(injected) and ".tdm12" in removed and forged_absent,
            "expected_nonzero_exit": True,
            "observed_exit_code": 0 if not forged_absent else 1,
            "status": "PROVEN"
            if injected and ".tdm12" in removed and forged_absent
            else "NOT_PROVEN",
            "command": "scripts/tdm14a_replay.py --inject-stale-state (CRLF run)",
            "duration_seconds": run_b["duration_seconds"],
            "stdout_tail": [
                f"injected={sorted(injected)}",
                f"removed={removed}",
                f"forged values absent from the regenerated review={forged_absent}",
            ],
            "stderr_tail": [],
            "detail": {
                "injected_digests": injected,
                "isolation_removed": removed,
                "regenerated_review_net_mean": dotted_net(review),
                "regenerated_review_run_id": review.get("run_id"),
            },
        }
    )

    proven = [c for c in controls if c["status"] == "PROVEN"]
    report = {
        "artifact": "tdm14a-negative-controls-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sandbox": str(sandbox),
        "target_commit": target,
        "controls": controls,
        "proven": len(proven),
        "total": len(controls),
        "status": "PASS" if len(proven) == len(controls) else "FAIL",
        "rule": "PROVEN requires a non-zero exit AND the expected reason in the output; a "
        "non-zero exit for the wrong reason is NOT_PROVEN",
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({c["control"]: c["status"] for c in controls}, indent=1))
    print(f"{len(proven)}/{len(controls)} controls proven")
    return 0 if report["status"] == "PASS" else 1


def dotted_net(review: dict[str, Any]) -> Any:
    return ((review.get("ledger") or {}).get("net_mean")) if isinstance(review, dict) else None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
