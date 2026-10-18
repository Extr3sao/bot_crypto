"""record_test_receipts — measure RED on the base commit and GREEN on this one.

RED is measured by running the new tests against the *base* source (``git archive`` of
``b7e100a``), where ``trading_bot.intelligence.ai_critic`` does not exist. GREEN is
measured in this worktree. Both receipts keep the command, exit code, stdout, stderr and
the path of the runtime module the tests actually imported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

BASE_COMMIT = "b7e100a"
TEST = "tests/unit/intelligence/ai_critic/test_bot_cri_01.py"
RELATED = "tests/unit/intelligence/ai_bots"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], cwd: Path, env: dict[str, str]) -> dict:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env,
                          check=False)
    return {
        "command": " ".join(command),
        "cwd": str(cwd),
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # --- RED: the tests against the base commit, where the module is absent ----------
    red_dir = Path(tempfile.mkdtemp(prefix="tap004-red-base-"))
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", BASE_COMMIT, "src"],
        capture_output=True, check=False,
    )
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(red_dir)
    test_copy = red_dir / TEST
    test_copy.parent.mkdir(parents=True, exist_ok=True)
    test_copy.write_text((repo / TEST).read_text(encoding="utf-8"), encoding="utf-8")
    red_env = {**os.environ, "PYTHONPATH": str(red_dir / "src")}
    red = run([args.python, "-m", "pytest", TEST, "-q"], red_dir, red_env)

    # --- GREEN: this worktree --------------------------------------------------------
    green_env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    green = run([args.python, "-m", "pytest", TEST, "-q"], repo, green_env)
    related = run([args.python, "-m", "pytest", RELATED, "-q"], repo, green_env)
    import_probe = run(
        [args.python, "-c",
         "import trading_bot.intelligence.ai_critic as m; print(m.__file__)"],
        repo, green_env,
    )

    receipt = {
        "schema_version": "TAP004_TEST_RECEIPT_V1",
        "test_target": "trading_bot.intelligence.ai_critic",
        "runtime_target": "trading_bot.intelligence.ai_critic",
        "test_target_equals_runtime_target": import_probe["stdout"].strip().replace("\\", "/")
        .endswith("bot_crypto_004/src/trading_bot/intelligence/ai_critic/__init__.py"),
        "imported_module_path": import_probe["stdout"].strip(),
        "red": {
            "base_commit": BASE_COMMIT,
            "expected": "collection error: the module does not exist at the base commit",
            "result": red,
            "module_present": False,
        },
        "green": {
            "commit": subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                     capture_output=True, text=True, check=False).stdout.strip(),
            "result": green,
            "related_suite": related,
        },
        "test_file_sha256": sha256(repo / TEST),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    target = out / "TEST_RED_GREEN.json"
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "red_exit": red["exit_code"],
        "green_exit": green["exit_code"],
        "related_exit": related["exit_code"],
        "same_target": receipt["test_target_equals_runtime_target"],
        "sha256": sha256(target),
    }, indent=2))
    return 0 if red["exit_code"] != 0 and green["exit_code"] == 0 and related["exit_code"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
