"""Build LOCAL_GITHUB_SYNC_AUDIT.json.

Combines live git state (branches, remotes, worktrees, ahead/behind, dirty files)
with the qualitative audit fields collected during the 2026-10-25 local -> GitHub
synchronisation: runtime reachability, test state, evidence and target PR.

Run from anywhere inside the repository:  .venv/Scripts/python.exe scripts/sync_audit_report.py
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
OUT = REPO / "LOCAL_GITHUB_SYNC_AUDIT.json"

# Qualitative fields gathered during the audit (not derivable from git alone).
QUAL: dict[str, dict[str, str]] = {
    "main": {"runtime": "RUNTIME_REACHABLE", "tests": "FAIL 90F/3263P/14E (baseline pre-existente)",
             "evidence": "corpus TDM/CI/RFC publicado", "pr": "#18 (admission/integration-002)",
             "note": "Contenido de main publicado vorigin/admission/integration-002; no se hizo push a origin/main."},
    "admission/integration-002": {"runtime": "NOT_VERIFIED", "tests": "CI en GitHub", "evidence": "reports/",
                                  "pr": "#18 (ready)", "note": "gate de admision recalculado"},
    "audit/economic-blocker-001": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "-", "pr": "-",
                                   "note": "ancla del bloqueo economico"},
    "audit/g7-real-paper": {"runtime": "NOT_VERIFIED", "tests": "CI FAIL", "evidence": "reports G-7", "pr": "#35 (draft)",
                            "note": "auditoria G-7"},
    "audit/mt0004-negative-controls": {"runtime": "NOT_VERIFIED", "tests": "CI FAIL", "evidence": "reports/",
                                       "pr": "#34 (draft)", "note": "controles negativos MT-0004"},
    "audit/supervisor-integration-001": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "reports/ (24)",
                                         "pr": "#22 (draft)", "note": "auditoria del carril supervisor"},
    "codepaper/supervisor-001": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "reports/",
                                 "pr": "#23 (draft)", "note": "WIP carril supervisor"},
    "evidence/tdm11": {"runtime": "TEST_ONLY", "tests": "CI FAIL", "evidence": "evidence/ (11)", "pr": "#30 (draft)",
                       "note": "short-in-downtrend refutado"},
    "evidence/tdm12": {"runtime": "TEST_ONLY", "tests": "CI FAIL", "evidence": "evidence/ (25)", "pr": "#31 (draft)",
                       "note": "TDM-11 cerrado como rechazado"},
    "evidence/tdm13": {"runtime": "TEST_ONLY", "tests": "CI FAIL", "evidence": "evidence/ (62)", "pr": "#32 (draft)",
                       "note": "inputs sellados byte-identicos"},
    "fix/tdm14a": {"runtime": "TEST_ONLY", "tests": "CI FAIL (recovery-determinism PASS)", "evidence": "evidence/ (64)",
                   "pr": "#29 (draft)", "note": "TDM-13/14a"},
    "gate/integration-001": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "reports/ (436)",
                             "pr": "#20 (draft)", "note": "verificacion post-entrega"},
    "integ/supervisor-002": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "reports/ (168)",
                             "pr": "#21 (draft)", "note": "entrega independiente supervisor"},
    "paper/reald-data-001": {"runtime": "RUNTIME_REACHABLE", "tests": "CI FAIL", "evidence": "docs/ (43)",
                             "pr": "#33 (draft)", "note": "campana PAPER con datos reales"},
    "recovery/exp004a-02k-9983b050": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "docs/",
                                      "pr": "#26 (draft)", "note": "recuentos de la matriz exp004a"},
    "recovery/mt0003-kill-switch-60455b46": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "reports/",
                                             "pr": "#24 (draft)",
                                             "note": "CRITICO DE RIESGO: no fusionar sin autorizacion de risk-manager"},
    "recovery/trunk-format-001": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "reports/ (17)",
                                  "pr": "#25 (draft)", "note": "formato del tronco"},
    "repro/economic-recovery-002": {"runtime": "NOT_VERIFIED", "tests": "NOT_RUN", "evidence": "docs/", "pr": "#27 (draft)",
                                    "note": "recuento de defectos economicos"},
    "repro/paper-admission-001": {"runtime": "NOT_VERIFIED", "tests": "CI FAIL", "evidence": "reports/ (1327)",
                                  "pr": "#28 (draft)", "note": "reproduccion del clone de admision"},
    "project/roadmap-trading-agentic": {"runtime": "NOT_VERIFIED", "tests": "CI FAIL", "evidence": "roadmap xlsx/json/csv",
                                        "pr": "#15 (ready)", "note": "roadmap v1.6"},
}

PRESERVATION_NOTE = "Rama de preservacion creada por la auditoria para publicar el trabajo sin commit de un worktree."

# Draft PR opened for each preservation branch (head branch -> PR number).
PRESERVATION_PRS = {
    "sync/uncommitted-main-20261025": 19,
    "sync/uncommitted-ff-wt-tdm06-20261025": None,
    "sync/uncommitted-ff-wt-tdm11-20261025": None,
    "sync/uncommitted-ff-wt-tdm09-repro-20261025": None,
    "sync/uncommitted-ff-wt-tdm12-20261025": None,
    "sync/uncommitted-exp004a-recovery-02k-20261025": None,
    "sync/uncommitted-ff-wt-tdm08-20261025": None,
    "sync/uncommitted-ff-wt-tdm13-20261025": None,
    "sync/uncommitted-ff-wt-tdm14a-20261025": None,
    "sync/uncommitted-ff-wt-trunkfmt-20261025": None,
    "sync/uncommitted-recovery-rehearsal-9vicsg7h-20261025": None,
    "sync/uncommitted-ff-wt-base-20261025": None,
    "sync/uncommitted-ff-wt-adm002-20261025": None,
    "sync/uncommitted-ff-wt-eco001-20261025": None,
    "sync/uncommitted-ff-wt-g7-20261025": None,
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, cwd=REPO, errors="replace")


def git_lines(*args: str) -> list[str]:
    out = git(*args)
    return [line for line in out.splitlines() if line.strip()]


def worktrees() -> dict[str, dict[str, object]]:
    """branch -> {path, head, dirty, untracked, staged}"""
    res: dict[str, dict[str, object]] = {}
    path = ""
    branch = ""
    for line in git_lines("worktree", "list", "--porcelain"):
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch "):
            branch = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "bare":
            path, branch = "", ""
        if path and branch:
            try:
                st = subprocess.check_output(
                    ["git", "-C", path, "status", "--porcelain=v1", "-uall"],
                    text=True, errors="replace", timeout=300,
                ).splitlines()
            except Exception as exc:  # pragma: no cover - defensive
                st = [f"! status failed: {exc}"]
            res[branch] = {
                "path": path,
                "head": git("-C", path, "rev-parse", "HEAD").strip(),
                "dirty": len(st),
                "modified": sum(1 for s in st if s[:2].strip() and s[0] in " M"),
                "untracked": sum(1 for s in st if s.startswith("??")),
                "entries": st if len(st) <= 40 else [f"({len(st)} entradas; ver respaldo local)"],
            }
            path, branch = "", ""
    return res


def main() -> None:
    remotes = git_lines("remote", "-v")
    branches = git_lines("for-each-ref", "--format=%(refname:short)", "refs/heads")
    wts = worktrees()

    remote_branches = {
        line.split()[-1].removeprefix("origin/")
        for line in git_lines("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
        if line.split()[-1] != "origin/HEAD"
    }

    # Commits that exist locally but are reachable from no origin ref at all.
    unreachable = int(git("rev-list", "--branches", "--not", "--remotes=origin", "--count").strip())

    rows = []
    for b in branches:
        local = git("rev-parse", b).strip()
        remote = None
        ahead = behind = None
        if b in remote_branches:
            remote = git("rev-parse", f"origin/{b}").strip()
            ahead = int(git("rev-list", "--count", f"origin/{b}..{b}"))
            behind = int(git("rev-list", "--count", f"{b}..origin/{b}"))
        else:
            ahead = int(git("rev-list", "--count", b))
            behind = 0

        wt = wts.get(b, {})
        q = QUAL.get(b, {})
        if b.startswith("sync/uncommitted-"):
            pr_no = PRESERVATION_PRS.get(b)
            q = {
                "runtime": "BLOCKED" if b == "sync/uncommitted-main-20261025" else "NOT_VERIFIED",
                "tests": "FAIL (coleccion rota)" if b == "sync/uncommitted-main-20261025" else "NOT_RUN",
                "evidence": "contenido del worktree original",
                "pr": f"#{pr_no} (draft)" if pr_no else "sin PR (rama publicada)",
                "note": PRESERVATION_NOTE,
            }
            status = "PUBLISHED_WIP"
        elif ahead == 0 and behind == 0:
            status = "ALREADY_PUBLISHED"
        elif behind and behind > 0:
            status = "REMOTE_DIVERGED"
        else:
            status = "UNPUBLISHED"

        if b in QUAL and QUAL[b].get("pr", "-").endswith("(draft)"):
            status = "PUBLISHED_BLOCKED_INTEGRATION"
        if b == "recovery/mt0003-kill-switch-60455b46":
            status = "BLOCKED"

        rows.append({
            "branch": b,
            "local_head": local,
            "remote_head": remote,
            "ahead_of_origin_main": int(git("rev-list", "--count", f"origin/main..{b}")),
            "ahead": ahead,
            "behind": behind,
            "worktree": wt.get("path"),
            "dirty": wt.get("dirty"),
            "untracked": wt.get("untracked"),
            "runtime_reachable": q.get("runtime", "NOT_VERIFIED"),
            "tests": q.get("tests", "NOT_RUN"),
            "evidence": q.get("evidence", "-"),
            "sync_status": status,
            "target_pr": q.get("pr", "-"),
            "note": q.get("note", ""),
        })

    payload = {
        "report": "LOCAL_GITHUB_SYNC_AUDIT",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": "Extr3sao/bot_crypto",
        "local_checkout": str(REPO),
        "origin": [r for r in remotes if r.startswith("origin")],
        "status": "PARTIAL_SYNC",
        "invariants": [
            "SYNC_COMPLETE != MAIN_INTEGRATED != RUNTIME_CERTIFIED != PROFITABLE",
            "Publicar codigo no certifica el runtime ni demuestra rentabilidad.",
        ],
        "initial_inventory": {
            "worktrees": 26,
            "worktrees_at_close": 46,
            "worktrees_removed": 0,
            "local_branches": 19,
            "remote_branches": 73,
            "stashes": 0,
            "unpublished_local_commits": 226,
            "dirty_entries_main_worktree": 1338,
            "untracked_files_other_worktrees": 246,
            "backup": "C:/Users/GVLLFR0035/Downloads/sync-backup-20261025",
        },
        "final_inventory": {
            "local_branches": len(branches),
            "commits_not_reachable_from_any_origin_ref": unreachable,
            "stashes": len(git_lines("stash", "list")),
            "backup_sha256_manifest": "sync-backup-20261025/SHA256SUMS.txt",
        },
        "orphan_reflog_preservation": {
            "definition": "commits alcanzables solo desde el reflog (versiones sustituidas por amend/rebase)",
            "discovered": 40,
            "preserved_as_tags": len(git_lines("tag", "-l", "sync/orphan-*")),
            "tag_pattern": "sync/orphan-<sha12>",
            "published_to_origin": int(
                git("ls-remote", "--tags", "origin", "sync/orphan-*", "--refs")
                .count("refs/tags/sync/orphan-")
            ),
            "policy": "ningun commit local se deja solo en el reflog (expira a los 90 dias)",
        },
        "branches": rows,
        "preservation_branches": sorted(
            b for b in branches if b.startswith("sync/uncommitted-")
        ),
        "exclusions": {
            "manifest": "EXCLUDED_FROM_SYNC_MANIFEST.json",
            "generated_by": "scripts/sync_exclusion_manifest.py",
            "policy": "nada excluido se da por sincronizado",
        },
        "validation": {
            "commands": [
                ".venv/Scripts/python.exe -m ruff check .",
                ".venv/Scripts/python.exe -m ruff format --check .",
                ".venv/Scripts/python.exe -m mypy .",
                ".venv/Scripts/python.exe -m pytest -q",
            ],
            "pytest_local_baseline": "90 failed, 3263 passed, 14 errors (2026-10-25, exit 1)",
            "pytest_local_baseline_prior_run": "90 failed, 3206 passed, 14 errors (2026-10-23, exit 1)",
            "pytest_origin_main": "582 passed (2026-10-25, exit 0)",
            "ci_baseline_on_origin_main": "failure (2026-09-22 y anteriores) -> rojo pre-existente",
            "independent_clean_clone_2026-10-26": {
                "checkout": "git clone local de e67194e7 en gate-check-main-20261026 (0 entradas sucias)",
                "uv_sync": "exit 0",
                "ruff_format_check": "444 ficheros a reformatear / 374 OK (exit 1)",
                "ruff_check": "130 errores, 81 auto-fixables (exit 1)",
                "mypy": "297 errores en 38 ficheros, 812 comprobados (exit 1)",
                "pytest": "78 failed, 3275 passed, 31 skipped, 3 deselected, 14 errors (786 s, exit 1)",
                "coverage": "76.01% < 90% requerido (exit 1)",
                "verifier": "ejecucion independiente del worktree gate-main-20261026 (BUILDER != VERIFIER)",
            },
            "false_success": 0,
        },
    }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes), branches={len(rows)}, unreachable_commits={unreachable}")


if __name__ == "__main__":
    main()
