"""Independent verification of WP-RECOVERY-INCIDENT-001 deliverables.

Re-derives every claim that can be re-derived from the machine, and refuses to trust the report:

1. the backup bundle still hashes to the value the report publishes and verifies as a bundle;
2. the live object database is connectivity-clean and still holds the key commits;
3. every worktree the inventory calls EMPTIED is still emptied (one file, a dead gitlink);
4. every worktree the inventory calls ABSENT_DIR is still absent;
5. the inventory's totals equal the sum of its entries, and no entry claims surviving content;
6. the paper modules still import on the certified branch tip.

Read-only. Exits 1 if any check fails, printing which one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

MAIN_REPO = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
DOWNLOADS = MAIN_REPO.parent
BACKUP = Path(r"C:\Users\GVLLFR0035\incident-backup-20261023")
DEFAULT_REPORTS = Path(__file__).resolve().parents[1] / "reports/ai-bots/WP-RECOVERY-INCIDENT-001"

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(name)


def git(*args: str, cwd: Path = MAIN_REPO) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    args = parser.parse_args()
    reports = Path(args.reports)

    inventory = json.loads((reports / "LOST_ARTIFACTS_INVENTORY.json").read_text(encoding="utf-8"))
    integrity = json.loads((reports / "GIT_INTEGRITY_REPORT.json").read_text(encoding="utf-8"))

    # 1 — backup
    bundle = Path(integrity["backup"]["bundle"])
    check("backup bundle exists", bundle.is_file(), str(bundle))
    if bundle.is_file():
        digest = sha256(bundle)
        check(
            "backup bundle sha256 matches the report",
            digest == integrity["backup"]["bundle_sha256"],
            digest,
        )
        verify = git("bundle", "verify", str(bundle))
        check("backup bundle verifies", verify.returncode == 0, verify.stderr.strip()[:120])

    # 2 — object database
    fsck = git("fsck", "--connectivity-only")
    check("live object database is connectivity-clean", fsck.returncode == 0, fsck.stderr.strip()[:120])
    for label, entry in integrity["key_commits"].items():
        if not entry["present"]:
            continue
        exists = git("cat-file", "-e", f"{entry['commit']}^{{commit}}")
        check(f"key commit {label} still resolvable", exists.returncode == 0, entry["commit"][:12])

    # 3/4 — worktree state
    emptied = [e for e in inventory["entries"] if e["state"] == "EMPTIED_DIR"]
    absent = [e for e in inventory["entries"] if e["state"] == "ABSENT_DIR"]
    check("inventory lists 26 emptied worktrees", len(emptied) == 26, str(len(emptied)))
    for entry in emptied:
        path = Path(entry["path"])
        files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
        names = {p.name for p in files}
        link = path / ".git"
        target = link.read_text(encoding="utf-8").strip().removeprefix("gitdir: ") if link.is_file() else ""
        check(
            f"{entry['name']}: emptied, gitlink dead",
            names == {".git"} and bool(target) and not Path(target).is_dir(),
            f"files={sorted(names)} target_exists={Path(target).is_dir() if target else None}",
        )
    for entry in absent:
        check(f"{entry['name']}: still absent", not Path(entry["path"]).exists())

    # 5 — totals cover every entry the pre-incident inventory knew, including the vanished one
    totals = inventory["totals_pre_incident"]
    counted = [e for e in inventory["entries"] if e["pre_incident"]]
    check("entry count matches total", totals["entries"] == len(counted), f"{totals['entries']}")
    check("bytes match sum", totals["bytes"] == sum(e["pre_incident"]["bytes"] for e in counted))
    check("files match sum", totals["files"] == sum(e["pre_incident"]["files"] for e in counted))
    check("every entry declares no surviving content", all(e["current"]["files_besides_gitlink"] == 0 for e in emptied))

    # 6 — runtime imports on the certified tree
    repo = Path(__file__).resolve().parents[1]
    probe = subprocess.run(
        [
            str(repo / ".venv/Scripts/python.exe"),
            "-c",
            "import importlib\n"
            "for m in ('trading_bot.paper.broker','trading_bot.autonomous.runtime',"
            "'trading_bot.risk.manager','trading_bot.execution.live_gate'):\n"
            "    importlib.import_module(m)\n"
            "print('ok')",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "", "SYSTEMROOT": "C:\\Windows"},
    )
    check("paper modules import on the certified tree", probe.returncode == 0 and "ok" in probe.stdout,
          (probe.stderr or probe.stdout).strip().splitlines()[-1:] and (probe.stderr or probe.stdout).strip().splitlines()[-1][:120])

    print()
    if FAILURES:
        print(f"VERDICT: FAIL ({len(FAILURES)} check(s))")
        return 1
    print("VERDICT: PASS — deliverables agree with the machine state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
