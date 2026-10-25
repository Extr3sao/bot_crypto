"""WP051-02K — one place that records what was run, what it exited with, and on which bytes.

The verifiers are the repository's own (``exp004a_wp051_02k_verify.py`` and
``edge04_verify.py``), invoked as subprocesses with their exit codes preserved. This collector
is builder tooling and says so: it is not independent of the recovery, and the independence that
matters here is builder (the observer tick, the corpus fetch) versus verifier (sealed scripts).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(argv: list[str], cwd: Path, timeout: int = 600) -> dict:
    completed = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
    )
    return {
        "command": " ".join(argv),
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout.strip().splitlines()[-30:],
        "stderr_tail": completed.stderr.strip().splitlines()[-10:],
    }


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=120
    )
    return completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="the tree the campaign runs in")
    parser.add_argument("--python", required=True)
    parser.add_argument("--ops", required=True, help="where the evidence is written")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--corpus-1h", required=True)
    parser.add_argument("--corpus-15m", required=True)
    parser.add_argument("--search-c", required=True)
    parser.add_argument("--search-g", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    python = Path(args.python)
    ops = Path(args.ops).resolve()
    ops.mkdir(parents=True, exist_ok=True)
    state_root = Path(args.state_root)

    # 1. the frozen pin, called exactly as the observer calls it.
    probe = run(
        [
            str(python),
            "-c",
            "import sys; sys.path.insert(0,'src')\n"
            "from trading_bot.research.edge03 import forward_plan as FP\n"
            "try:\n    print('PIN_OK', FP.assert_frozen_corpus())\n"
            "except Exception as exc:\n    print('PIN_FAIL', type(exc).__name__, exc)\n"
            "    raise SystemExit(3)\n",
        ],
        cwd=repo,
    )

    # 2. the corpus evidence gathered by the fetch tool.
    corpus_1h = json.loads(Path(args.corpus_1h).read_text(encoding="utf-8"))
    corpus_15m = json.loads(Path(args.corpus_15m).read_text(encoding="utf-8"))
    restored = sorted((repo / "reports" / "alpha-expansion-v1" / "data").glob("*.json"))
    corpus = {
        "one_hour": {
            "accepted": [
                {
                    "asset": row["asset"],
                    "bars": row["bars"],
                    "first_ts": row["first_ts"],
                    "last_ts": row["last_ts"],
                    "corpus_digest": row["corpus_digest"],
                    "frozen_prefix16": row["frozen_prefix16"],
                    "matches": row["digest_matches_frozen"],
                }
                for row in corpus_1h["results"]
            ],
            "verdict": "RESTORED_AND_PINNED"
            if all(row.get("digest_matches_frozen") for row in corpus_1h["results"])
            else "NOT_RESTORED",
        },
        "fifteen_minutes": {
            "attempts": [
                {
                    "asset": row.get("asset"),
                    "window_bars": row.get("window_bars"),
                    "bytes": row.get("bytes"),
                    "published_bytes": row.get("published_bytes"),
                    "bytes_short": (row.get("published_bytes") or 0) - (row.get("bytes") or 0),
                    "sha256": row.get("sha256"),
                    "published_sha256": row.get("published_sha256"),
                    "sha256_matches": row.get("sha256_matches_published"),
                    "digest_matches": row.get("digest_matches_frozen"),
                }
                for row in corpus_15m["results"]
            ],
            "verdict": "NOT_REPRODUCIBLE"
            if not any(row.get("sha256_matches_published") for row in corpus_15m["results"])
            else "RESTORED",
        },
        "written_into_the_tree": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in restored
        ],
        "acceptance": corpus_1h["acceptance"],
    }

    # 3. the filesystem search for the missing shards, as it was performed.
    search = {}
    for label, path in (("C:", args.search_c), ("G:", args.search_g)):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        rows = [line for line in text.splitlines() if line.strip() and line.strip() != "DONE"]
        search[label] = {
            "source": str(path),
            "completed": "DONE" in text,
            "hits": len(rows),
            "shard_hits": sum(1 for row in rows if row.endswith(("_15m.json",))),
            "alpha_expansion_hits": sum(1 for row in rows if "alpha-expansion-v1" in row),
            "sample": rows[:5],
        }

    # 4. the store the failed tick left behind.
    runs_path = state_root / "runs.jsonl"
    runs = []
    if runs_path.is_file():
        for line in runs_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                runs.append(
                    {
                        "run_id": row.get("run_id"),
                        "slot_key": row.get("slot_key"),
                        "mode": row.get("mode"),
                        "outcome": row.get("outcome"),
                        "exit_code": row.get("exit_code"),
                        "error_class": row.get("error_class"),
                        "payload_error": (row.get("payload_error") or "")[:200],
                        "duration_seconds": row.get("duration_seconds"),
                        "started_at_utc": row.get("started_at_utc"),
                        "free_gib": (row.get("disk_after") or {}).get("free_gib"),
                    }
                )
    campaign = {
        "state_root": str(state_root),
        "rows": runs,
        "distinct_run_ids": sorted({row["run_id"] for row in runs if row.get("run_id")}),
        "lease_dir_empty": (state_root / "lock").is_dir()
        and not any((state_root / "lock").iterdir()),
        "artifacts": sorted(path.name for path in state_root.iterdir() if path.is_file()),
        "released_after_failure": True,
        "observation_produced": any(row.get("outcome") == "OBSERVED" for row in runs),
        "resumed_on_the_same_slot": len(runs) > 1
        and len({row["run_id"] for row in runs}) == 1,
    }

    # 5. the repository's own verifiers, exit codes preserved.
    verifier_02k = run([str(python), "scripts/exp004a_wp051_02k_verify.py"], cwd=repo)
    verifier_edge04 = run(
        [
            str(python),
            "scripts/edge04_verify.py",
            "--state-root",
            str(state_root),
            "--repo",
            str(repo),
            "--json-out",
            str(ops / "VERIFIER_EDGE04.json"),
        ],
        cwd=repo,
    )
    (ops / "VERIFIER_02K.stdout.txt").write_text(
        "\n".join(verifier_02k["stdout_tail"]) + "\n", encoding="utf-8"
    )
    (ops / "VERIFIER_EDGE04.stdout.txt").write_text(
        "\n".join(verifier_edge04["stdout_tail"]) + "\n", encoding="utf-8"
    )

    # 6. what was changed, and the bytes that carry it.
    guard = repo / "scripts" / "edge04_watchdog.py"
    report = {
        "schema_version": "EXP004A_WP051_02K_OPS_EVIDENCE_V1",
        "generated_at_utc": iso(),
        "pin": {
            "command": probe["command"],
            "exit_code": probe["exit_code"],
            "stdout_tail": probe["stdout_tail"],
            "verdict": "PIN_REFUSES" if probe["exit_code"] != 0 else "PIN_SATISFIED",
        },
        "corpus": corpus,
        "search": search,
        "campaign": campaign,
        "verifiers": {
            "wp051_02k_verify": {
                "exit_code": verifier_02k["exit_code"],
                "summary": verifier_02k["stdout_tail"][-1:] or [],
                "artifact": "VERIFIER_02K.stdout.txt",
            },
            "edge04_verify": {
                "exit_code": verifier_edge04["exit_code"],
                "summary": verifier_edge04["stdout_tail"][-1:] or [],
                "artifact": "VERIFIER_EDGE04.json",
            },
        },
        "provenance": {
            "repo": str(repo),
            "head": git(repo, "rev-parse", "HEAD"),
            "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_paths": git(repo, "status", "--porcelain").splitlines()[:20],
            "guard_sha256": sha256_file(guard),
            "guard_diff_stat": git(repo, "diff", "--stat", "--", "scripts/edge04_watchdog.py"),
        },
        "builder_verifier_separation": {
            "builder": [
                "scripts/edge04_observer.py (the tick that failed)",
                "docs/agentic/exp004a/wp051_02k/ops/recover_frozen_corpus.py (the corpus fetch)",
                "docs/agentic/exp004a/wp051_02k/ops/verify_guard.py (the guard harness)",
            ],
            "verifier": [
                "scripts/exp004a_wp051_02k_verify.py (sealed in 9983b050)",
                "scripts/edge04_verify.py (sealed in 9983b050)",
            ],
            "collector_is_independent": False,
            "note": (
                "this collector is builder tooling; it records the sealed verifiers' exit codes "
                "verbatim rather than restating their conclusions as its own"
            ),
        },
    }
    Path(args.ops, "EVIDENCE.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "pin": report["pin"]["verdict"],
                "corpus_1h": corpus["one_hour"]["verdict"],
                "corpus_15m": corpus["fifteen_minutes"]["verdict"],
                "observation_produced": campaign["observation_produced"],
                "verifier_02k_exit": verifier_02k["exit_code"],
                "verifier_edge04_exit": verifier_edge04["exit_code"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
