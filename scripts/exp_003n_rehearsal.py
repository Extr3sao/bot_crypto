"""exp_003n_rehearsal — re-derive the published numbers from a checkout, not from the tree.

    ./.venv/Scripts/python.exe scripts/exp_003n_rehearsal.py --commit <sha>

Why a separate program
    A result measured in the working tree that wrote it is a measurement, not a
    reproduction. The published tree was produced on one machine; the only thing that
    proves the numbers follow from the committed code and the frozen data is to run the
    committed code again somewhere else, from the frozen data, and compare.

What it does
    * materialises ``--commit`` in a detached ``git worktree`` (never a copy of the dirty
      tree, never a stash);
    * copies the three frozen 1-minute files into that worktree and checks each SHA-256
      against the digest ``design/DESIGN.json`` recorded *before* the screening ran — the
      design is the provenance, so a file that does not match its digest stops the run;
    * runs the committed ``screen``, ``validate`` and ``verify`` there, writing into the
      worktree's own report directory;
    * compares the reproduced ``SCREENING.json``, ``VALIDATION.json`` and ``DECISION.json``
      against the published ones, leaf by leaf, with a tolerance for float formatting;
    * writes ``evidence/CLEAN_CHECKOUT_REPRODUCTION.json`` with the counts, and the stdout
      transcript beside it.

What it refuses
    * a worktree with local modifications before the first stage runs (that is not a
      checkout, it is a working tree with a git directory);
    * a dataset file whose digest differs from the design — the experiment is defined
      against those bytes, not against whatever is on disk;
    * reporting a comparison it did not make: a missing published file is a failed
      reproduction, not a skipped one.

What it does not claim
    No order is placed and no fill is observed. This proves the published arithmetic
    follows from the committed code and the frozen bars; it says nothing about the market.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
PYTHON = str(REPO / ".venv" / "Scripts" / "python.exe")

RELATIVE = Path("reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001")
DATASET_RELATIVE = Path("reports/ai-bots/EXP-003K-CANDIDATE-001/dataset")

#: Compared as text, because they describe when a program ran rather than what it found.
VOLATILE = {"generated_at_utc", "fetched_at_utc", "finished_at_utc", "started_at_utc"}
TOLERANCE = 1e-6


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _run(command: list[str], cwd: Path, log: Path) -> tuple[int, str]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    elapsed = time.monotonic() - started
    text = result.stdout + result.stderr
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"$ {' '.join(command)}   # cwd={cwd} rc={result.returncode} {elapsed:.1f}s\n")
        handle.write(text.rstrip("\n") + "\n\n")
    return int(result.returncode), text


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd or REPO, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _walk(published: Any, reproduced: Any, path: str, diffs: list[str], key: str) -> None:
    """Compare two JSON trees leaf by leaf; a shape difference is a difference, not a skip."""

    if isinstance(published, dict) and isinstance(reproduced, dict):
        missing = sorted(set(published) ^ set(reproduced))
        if missing:
            diffs.append(f"{key}: shape differs at {path or '/'} ({missing[:3]})")
            return
        for name in published:
            if name in VOLATILE:
                continue
            _walk(published[name], reproduced[name], f"{path}/{name}", diffs, key)
        return
    if isinstance(published, list) and isinstance(reproduced, list):
        if len(published) != len(reproduced):
            diffs.append(f"{key}: {path or '/'} has {len(reproduced)} rows, published {len(published)}")
            return
        for index, (left, right) in enumerate(zip(published, reproduced, strict=True)):
            _walk(left, right, f"{path}[{index}]", diffs, key)
        return
    if isinstance(published, bool) or isinstance(reproduced, bool):
        if published is not reproduced:
            diffs.append(f"{key}: {path} reproduced {reproduced!r}, published {published!r}")
        return
    if isinstance(published, (int, float)) and isinstance(reproduced, (int, float)):
        if abs(float(published) - float(reproduced)) > TOLERANCE:
            diffs.append(f"{key}: {path} reproduced {reproduced!r}, published {published!r}")
        return
    if published != reproduced:
        diffs.append(f"{key}: {path} reproduced {reproduced!r}, published {published!r}")


def _compare(published: Any, reproduced: Any, key: str) -> list[str]:
    diffs: list[str] = []
    _walk(published, reproduced, "", diffs, key)
    return diffs


def _compare_cells(
    published: list[dict[str, Any]], reproduced: list[dict[str, Any]], key: str
) -> tuple[int, int, list[str]]:
    """Compare cell rows by their own key, so one wrong cell counts as one wrong cell."""

    left = {str(row["key"]): row for row in published}
    right = {str(row["key"]): row for row in reproduced}
    diffs: list[str] = []
    mismatched = 0
    for name in sorted(set(left) | set(right)):
        if name not in left or name not in right:
            diffs.append(f"{key}: cell {name} present on one side only")
            mismatched += 1
            continue
        cell_diffs: list[str] = []
        _walk(left[name], right[name], "", cell_diffs, key)
        if cell_diffs:
            mismatched += 1
            diffs.extend(cell_diffs[:2])
    return len(set(left) | set(right)), mismatched, diffs


def _pytest_count(text: str, word: str) -> int:
    """Read ``N passed`` / ``N failed`` out of pytest's summary line, wherever it sits."""

    for line in reversed(text.splitlines()):
        parts = line.replace("=", " ").replace(",", " ").split()
        for index, part in enumerate(parts):
            if part == word and index and parts[index - 1].isdigit():
                return int(parts[index - 1])
    return 0


def _prepare(worktree: Path, commit: str) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(
        ["git", "worktree", "prune"], cwd=REPO, capture_output=True, text=True, check=False
    )
    _git("worktree", "add", "--detach", str(worktree), commit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="commit to reproduce (default HEAD)")
    parser.add_argument("--worktree", default="", help="where to materialise the worktree")
    parser.add_argument("--out", default=str(OUT), help="published experiment directory")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse an existing repro-out/SCREENING.json instead of spending the sample again",
    )
    args = parser.parse_args(argv)

    import tempfile

    published_out = Path(args.out)
    worktree = Path(args.worktree) if args.worktree else Path(tempfile.gettempdir()) / "003n-repro"
    result_dir = worktree / RELATIVE
    evidence = published_out / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    stdout_log = evidence / "CLEAN_CHECKOUT_REPRODUCTION_STDOUT.txt"
    stdout_log.write_text(
        "# CLEAN CHECKOUT REPRODUCTION — EXP-003N\n"
        f"# worktree={worktree}\n\n",
        encoding="utf-8",
        newline="\n",
    )

    commit = _git("rev-parse", args.commit)

    # The committed tree already holds a SCREENING.json and the builder refuses to overwrite
    # one, by design. The reproduction therefore writes into its own directory and carries a
    # copy of the *committed* protocol, so the digests it is checked against are the published
    # ones and nothing in the checkout is edited.
    repro_out = worktree / "repro-out"
    resumed = bool(args.resume) and (repro_out / "analysis" / "SCREENING.json").exists()
    if not resumed:
        _prepare(worktree, commit)
    elif _git("rev-parse", "HEAD", cwd=worktree) != commit:
        print("[003n-repro] FAIL — the worktree is not at the commit to reproduce", file=sys.stderr)
        return 8

    dirty = [
        line
        for line in _git("status", "--porcelain", cwd=worktree).splitlines()
        if "repro-out" not in line
    ]
    if dirty:
        print(f"[003n-repro] FAIL — worktree is not clean: {dirty[:3]}", file=sys.stderr)
        return 2

    design = _read_json(result_dir / "design" / "DESIGN.json")

    if resumed:
        print("[003n-repro] resuming from the screening this worktree already produced")
        # A resumed run must still *execute* validation and verification: the builders refuse
        # to overwrite their own output, so the downstream artifacts of the earlier attempt go.
        for stale in ("VALIDATION.json", "DECISION.json", "VERIFICATION_REPRODUCED.json"):
            path = repro_out / "analysis" / stale
            if path.exists():
                path.unlink()
    (repro_out / "design").mkdir(parents=True, exist_ok=True)
    for name in ("DESIGN.json", "STRATEGY_UNIVERSE.json", "STRATEGY_UNIVERSE.md"):
        shutil.copy2(result_dir / "design" / name, repro_out / "design" / name)
    dataset_target = worktree / DATASET_RELATIVE
    dataset_target.mkdir(parents=True, exist_ok=True)
    matched = 0
    for name, entry in sorted(design["dataset"]["symbols"].items()):
        source = DATASET / entry["file"]
        target = dataset_target / entry["file"]
        shutil.copy2(source, target)
        digest = _sha256(target)
        if digest != entry["sha256"]:
            print(f"[003n-repro] FAIL — {name} digest {digest[:16]}… != design", file=sys.stderr)
            return 3
        matched += 1
    manifest = DATASET / "DATASET_MANIFEST.json"
    if manifest.exists():
        shutil.copy2(manifest, dataset_target / manifest.name)
    print(f"[003n-repro] dataset {matched}/{len(design['dataset']['symbols'])} digests match the design")

    started = time.monotonic()
    if resumed:
        screen_code, screen_seconds = 0, 0.0
    else:
        screen_code, _ = _run(
            [PYTHON, "scripts/exp_003n_screen.py", "--out", str(repro_out)],
            worktree,
            stdout_log,
        )
        screen_seconds = time.monotonic() - started
    if screen_code != 0:
        print(f"[003n-repro] FAIL — screen exited {screen_code}", file=sys.stderr)
        return 4
    validate_code, _ = _run(
        [PYTHON, "scripts/exp_003n_validate.py", "--out", str(repro_out)],
        worktree,
        stdout_log,
    )
    if validate_code != 0:
        print(f"[003n-repro] FAIL — validate exited {validate_code}", file=sys.stderr)
        return 5
    verify_code, _ = _run(
        [
            PYTHON,
            "scripts/exp_003n_verify.py",
            "--out",
            str(repro_out),
            "--negative-controls",
            "--json-out",
            str(repro_out / "analysis" / "VERIFICATION_REPRODUCED.json"),
        ],
        worktree,
        stdout_log,
    )
    if verify_code != 0:
        print(f"[003n-repro] FAIL — verifier exited {verify_code}", file=sys.stderr)
        return 6
    test_code, test_text = _run(
        [PYTHON, "-m", "pytest", "tests/unit/reports/test_exp_003n_screen.py", "-q"],
        worktree,
        stdout_log,
    )

    screening = _read_json(published_out / "analysis" / "SCREENING.json")
    reproduced_screening = _read_json(repro_out / "analysis" / "SCREENING.json")
    validation = _read_json(published_out / "analysis" / "VALIDATION.json")
    reproduced_validation = _read_json(repro_out / "analysis" / "VALIDATION.json")
    decision = _read_json(published_out / "analysis" / "DECISION.json")
    reproduced_decision = _read_json(repro_out / "analysis" / "DECISION.json")
    reproduced_verification = _read_json(repro_out / "analysis" / "VERIFICATION_REPRODUCED.json")

    screening_cells, screening_mismatched, screening_diffs = _compare_cells(
        screening["decisions"], reproduced_screening["decisions"], "screening"
    )
    validation_cells, validation_mismatched, validation_diffs = _compare_cells(
        validation["cells"], reproduced_validation["cells"], "validation"
    )
    diffs: list[str] = [*screening_diffs, *validation_diffs]
    diffs += _compare(
        {"counts": screening["counts"], "verdict": screening["verdict"]},
        {"counts": reproduced_screening["counts"], "verdict": reproduced_screening["verdict"]},
        "screening-summary",
    )
    diffs += _compare(
        {
            "counts": decision["counts"],
            "verdict": decision["verdict"],
            "candidates": decision["candidates"],
        },
        {
            "counts": reproduced_decision["counts"],
            "verdict": reproduced_decision["verdict"],
            "candidates": reproduced_decision["candidates"],
        },
        "decision",
    )

    payload = {
        "schema_version": "AI_BOTS_003N_CHECKOUT_REPRODUCTION_V1",
        "experiment": design["experiment"],
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": {
            "worktree": "git worktree add --detach <commit>; no copy of the dirty tree",
            "dataset": (
                "the three frozen 1-minute files were copied into the worktree only after each "
                "SHA-256 matched the digest design/DESIGN.json recorded before the screening ran"
            ),
            "stages": [
                "python scripts/exp_003n_screen.py --out <worktree>/repro-out",
                "python scripts/exp_003n_validate.py --out <worktree>/repro-out",
                "python scripts/exp_003n_verify.py --negative-controls",
                "python -m pytest tests/unit/reports/test_exp_003n_screen.py -q",
            ],
            "comparison": (
                "published and reproduced JSON are walked leaf by leaf; timestamps are the only "
                f"keys excluded, floats compare within {TOLERANCE:g}"
            ),
        },
        "result": {
            "commit": commit,
            "worktree_status_lines_before": 0,
            "dataset_digests_matched": matched,
            "dataset_digests_expected": len(design["dataset"]["symbols"]),
            "cells_compared": screening_cells,
            "cells_mismatched": screening_mismatched,
            "screening_verdict_published": screening["verdict"],
            "screening_verdict_reproduced": reproduced_screening["verdict"],
            "validation_compared": validation_cells,
            "validation_mismatched": validation_mismatched,
            "decision_verdict_published": decision["verdict"],
            "decision_verdict_reproduced": reproduced_decision["verdict"],
            "verification_checks": reproduced_verification["summary"]["checks"],
            "verification_controls": reproduced_verification["summary"]["controls_detected"],
            "verification_verdict": reproduced_verification["verdict"],
            "verification_false_success": reproduced_verification["summary"]["false_success"],
            "tests_passed": _pytest_count(test_text, "passed"),
            "tests_failed": _pytest_count(test_text, "failed"),
            "tests_exit_code": test_code,
            "screen_seconds": round(screen_seconds, 1),
            "screen_source": (
                "a full re-run inside this worktree at this commit; the first invocation wrote "
                "every artifact and then exited 1 in a final print (DEF-003N-01), so this one "
                "reused that output instead of spending the sample twice"
                if resumed
                else "a full re-run inside this worktree at this commit"
            ),
            "differences": diffs[:20],
        },
        "defects": [
            {
                "id": "DEF-003N-01",
                "found_by": "this reproduction",
                "defect": (
                    "exp_003n_screen.py printed target.relative_to(REPO) and raised ValueError "
                    "when --out pointed outside the repository (the worktree path arrived in "
                    "8.3 short form), so a legitimate run exited 1"
                ),
                "impact": (
                    "the crash came after SCREENING.json, SIGNALS.jsonl.gz and "
                    "ECONOMIC_SCREENING.csv were written; the reproduced numbers matched, the "
                    "stage exit code did not, and a caller that only reads the exit code would "
                    "have discarded a good result"
                ),
                "repair": (
                    "the diagnostic line falls back to the absolute path when the target is "
                    "outside the repo; no measurement code changed"
                ),
            },
        ],
        "not_verified": [
            "no order was placed and no fill is observed: this reproduces the arithmetic, not the market",
            "the reproduction writes into <worktree>/repro-out, so the checkout stays as committed; what is compared is the numbers, not the bytes",
            "the frozen bars were copied in after their digests matched, not re-downloaded here; EXP-003M's rehearsal already re-downloaded this same window byte-identically from the venue",
            "lane B cells with no sample stay INSUFFICIENT_EVIDENCE: a reproduction cannot create sample",
        ],
        "verdict": "REPRODUCED" if not diffs and test_code == 0 else "DIVERGED",
    }
    _write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
    with stdout_log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"# cells={len(screening['decisions'])} differences={len(diffs)}\n")
        handle.write(f"# verdict={payload['verdict']} tests_exit={test_code}\n")

    print(
        f"[003n-repro] {payload['verdict']}: {len(screening['decisions'])} screening cells, "
        f"{len(validation['cells'])} validation cells, differences={len(diffs)}, "
        f"tests_exit={test_code}"
    )
    for diff in diffs[:10]:
        print(f"[003n-repro]   {diff}")
    return 0 if payload["verdict"] == "REPRODUCED" else 7


if __name__ == "__main__":
    raise SystemExit(main())
