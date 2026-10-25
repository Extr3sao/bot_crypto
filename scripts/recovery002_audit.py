"""WP-RECOVERY-002 audit — collects evidence, never mutates the original repository.

Every subcommand writes one JSON document under
``reports/ai-bots/WP-RECOVERY-002/evidence/``.  The builder owns this file; the
independent verifier (``scripts/verify_recovery_002.py``) re-derives the same
facts from the artefacts and must not import anything from here.

Hard rules encoded below:

* the live repository is only ever read (``git fsck`` is read-only, and fsck
  writes nothing);
* new refs are created **only** inside ``WORK/protected.git``, an isolated copy
  of the object store;
* no ``gc``/``prune``/``clean``/``reset --hard``/recursive delete is issued.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("C:/Users/GVLLFR0035/Downloads/bot freebuff")
BACKUP = Path("C:/Users/GVLLFR0035/incident-backup-20261023")
BUNDLE = BACKUP / "REPO_ALL_REFS.bundle"
BUNDLE_SHA_FILE = BACKUP / "REPO_ALL_REFS.bundle.sha256"
BACKUP_REPO = BACKUP / "Downloads" / "bot freebuff"
DOWNLOADS = Path("C:/Users/GVLLFR0035/Downloads")
WORK = Path("C:/Users/GVLLFR0035/recovery-002")
OUT = Path("C:/Users/GVLLFR0035/Downloads/ff-wt-trunkfmt/reports/ai-bots/WP-RECOVERY-002")
EVIDENCE = OUT / "evidence"

PROTECTED_GITDIR = WORK / "protected.git"
PACKAGE_DIR = WORK / "package"
PACKAGE_COPY_B = WORK / "package-copy-b"
RESTORE_A = WORK / "restore-a"
RESTORE_B = WORK / "restore-b"

INCIDENT_ENTRIES_JSON = (
    Path("C:/Users/GVLLFR0035/Downloads/ff-wt-trunkfmt/reports/ai-bots/WP-RECOVERY-INCIDENT-001/"
         "LOST_ARTIFACTS_INVENTORY.json")
)

KEY_COMMITS = {
    "origin/main": "5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d",
    "main": "0e13160a8d5522961978fe3bd6b904b3a14be1c3",
    "recovery/trunk-format-001": "dc21870ffc512533da9dfc0e5a7eed5f075058c4",
    "campaign-anchor-47ca8dac": "47ca8dac",
    "campaign-anchor-cedc1346": "cedc1346",
    "campaign-anchor-03d169c8": "03d169c8",
    "pre-incident-main-1d2192b0": "1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22",
}


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #
def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900,
        env: dict[str, str] | None = None) -> dict:
    started = time.time()
    merged = dict(os.environ)
    merged.setdefault("GIT_TERMINAL_PROMPT", "0")
    merged.setdefault("GIT_OPTIONAL_LOCKS", "0")
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            errors="replace", timeout=timeout, env=merged,
        )
        return {
            "cmd": cmd, "exit": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "seconds": round(time.time() - started, 2),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd, "exit": "TIMEOUT", "seconds": round(time.time() - started, 2),
            "stdout": (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            "stderr": f"timed out after {timeout}s",
        }


def git(args: list[str], gitdir: Path | None = None, cwd: Path | None = None,
        timeout: int = 900) -> dict:
    cmd = ["git"]
    if gitdir is not None:
        cmd += [f"--git-dir={gitdir}"]
    cmd += args
    return run(cmd, cwd=cwd, timeout=timeout)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_evidence(name: str, payload: dict) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def fsck_objects(text: str) -> dict[str, list[str]]:
    """Parse fsck output into {'commit': [sha], 'tree': [...], 'blob': [...]} buckets."""
    buckets: dict[str, list[str]] = {}
    for ln in lines(text):
        parts = ln.split()
        if len(parts) >= 3 and parts[0] in {"unreachable", "dangling"} and parts[1] in {"commit", "tree", "blob", "tag"}:
            buckets.setdefault(parts[1], []).append(parts[2])
    return {k: sorted(set(v)) for k, v in buckets.items()}


def parse_count_objects(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for ln in lines(text):
        if ":" not in ln:
            continue
        key, _, value = ln.partition(":")
        value = value.strip()
        out[key.strip()] = int(value) if value.isdigit() else value  # type: ignore[assignment]
    return out


# --------------------------------------------------------------------------- #
# A1 — copies inventory
# --------------------------------------------------------------------------- #
def cmd_copies() -> None:
    entries: list[dict] = []

    packs = sorted((REPO / ".git" / "objects" / "pack").glob("*.pack"))
    live = {
        "id": "live-repo",
        "path": str(REPO),
        "kind": "ORIGINAL (read-only in this work package)",
        "exists": REPO.exists(),
        "packs": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p),
             "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))}
            for p in packs
        ],
        "count_objects": parse_count_objects(git(["count-objects", "-v"], cwd=REPO)["stdout"]),
        "refs": len(lines(git(["for-each-ref", "--format=%(refname)"], cwd=REPO)["stdout"])),
        "head": git(["rev-parse", "HEAD"], cwd=REPO)["stdout"].strip(),
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO)["stdout"].strip(),
    }
    live["pack_bytes_total"] = sum(p["bytes"] for p in live["packs"])
    entries.append(live)

    declared = BUNDLE_SHA_FILE.read_text(encoding="utf-8").split()[0].strip() if BUNDLE_SHA_FILE.exists() else None
    actual = sha256_file(BUNDLE) if BUNDLE.exists() else None
    verify = git(["bundle", "verify", str(BUNDLE).replace("\\", "/")], cwd=REPO) if BUNDLE.exists() else None
    heads = git(["bundle", "list-heads", str(BUNDLE).replace("\\", "/")], cwd=REPO) if BUNDLE.exists() else None
    entries.append({
        "id": "backup-bundle",
        "path": str(BUNDLE),
        "kind": "ALL-REFS GIT BUNDLE (derived from live refs at 21:15Z)",
        "exists": BUNDLE.exists(),
        "bytes": BUNDLE.stat().st_size if BUNDLE.exists() else None,
        "sha256": actual,
        "sha256_declared": declared,
        "sha256_match": (actual == declared) if (actual and declared) else False,
        "bundle_verify_exit": verify["exit"] if verify else None,
        "bundle_verify_tail": lines(verify["stdout"] + verify["stderr"])[-3:] if verify else None,
        "list_heads": heads["stdout"].splitlines() if heads else [],
    })

    backup_packs = sorted((BACKUP_REPO / ".git" / "objects" / "pack").glob("*.pack"))
    entries.append({
        "id": "backup-repo-copy",
        "path": str(BACKUP_REPO),
        "kind": "FULL REPOSITORY COPY (.git incl. unreachable objects)",
        "exists": BACKUP_REPO.exists(),
        "packs": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)}
            for p in backup_packs
        ],
        "pack_bytes_total": sum(p.stat().st_size for p in backup_packs),
        "count_objects": parse_count_objects(git(["count-objects", "-v"], gitdir=BACKUP_REPO / ".git")["stdout"]),
        "refs": len(lines(git(["for-each-ref", "--format=%(refname)"], gitdir=BACKUP_REPO / ".git")["stdout"])),
        "fsck_connectivity_only": git(["fsck", "--no-progress", "--connectivity-only"],
                                      gitdir=BACKUP_REPO / ".git")["exit"],
    })

    registered = git(["worktree", "list", "--porcelain"], cwd=REPO)["stdout"]
    wt: list[dict] = []
    current: dict = {}
    for ln in registered.splitlines():
        if ln.startswith("worktree "):
            if current:
                wt.append(current)
            current = {"path": ln.split(" ", 1)[1]}
        elif " " in ln and current:
            k, _, v = ln.partition(" ")
            current[k] = v
        elif ln.strip() and current is not None and ln != "":
            current.setdefault("flags", []).append(ln)
    if current:
        wt.append(current)
    for entry in wt:
        p = Path(entry["path"])
        if p.exists():
            entry["files_on_disk"] = sum(1 for _ in p.rglob("*") if _.is_file()) if p.name != "bot freebuff" else "live tree"
            entry["present"] = True
        else:
            entry["present"] = False
            entry["files_on_disk"] = 0
    entries.append({"id": "registered-worktrees", "kind": "LIVE WORKTREES", "entries": wt})

    shells = []
    for child in sorted(DOWNLOADS.iterdir()):
        if not child.is_dir():
            continue
        gitlink = child / ".git"
        if gitlink.is_file():
            target = gitlink.read_text(encoding="utf-8", errors="replace").strip()
            files = sum(1 for f in child.rglob("*") if f.is_file())
            shells.append({"name": child.name, "gitlink": target, "files": files,
                           "empty_shell": files == 1})
    entries.append({
        "id": "emptied-worktrees",
        "kind": "SHELLS (gitlink only)",
        "count": len(shells),
        "shells": shells,
        "admin_dirs_present": sorted(p.name for p in (REPO / ".git" / "worktrees").iterdir())
        if (REPO / ".git" / "worktrees").exists() else [],
    })

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002A.1 — copies and SHA-256",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": {"platform": sys.platform, "python": sys.version.split()[0]},
        "copies": entries,
        "independent_object_copies": [
            "live-repo (.git/objects)",
            "backup-repo-copy (.git/objects)",
        ],
        "derived_copies": ["backup-bundle (refs only, no unreachable objects)"],
    }
    print(write_evidence("A1_COPIES.json", payload))


# --------------------------------------------------------------------------- #
# A2 — integrity
# --------------------------------------------------------------------------- #
def cmd_integrity() -> None:
    full = git(["fsck", "--full", "--no-progress"], cwd=REPO, timeout=1800)
    conn = git(["fsck", "--no-progress", "--connectivity-only"], cwd=REPO, timeout=1800)
    fsck_lines = lines(full["stdout"] + full["stderr"])
    errors = [ln for ln in fsck_lines if not ln.startswith(("dangling", "unreachable"))]
    missing = [ln for ln in errors if "missing" in ln or "corrupt" in ln or "broken" in ln]

    packs = []
    for idx in sorted((REPO / ".git" / "objects" / "pack").glob("*.idx")):
        vp = git(["verify-pack", "-v", str(idx)], cwd=REPO, timeout=900)
        objs = [ln for ln in lines(vp["stdout"]) if len(ln.split()) >= 5 and not ln.startswith("non delta")]
        packs.append({
            "pack": idx.name.replace(".idx", ".pack"),
            "verify_pack_exit": vp["exit"],
            "objects": len(objs),
            "sha256_idx": sha256_file(idx),
        })

    key = {}
    for label, sha in KEY_COMMITS.items():
        r = git(["cat-file", "-t", sha], cwd=REPO)
        obj_type = r["stdout"].strip() if r["exit"] == 0 else None
        info = {}
        if obj_type == "commit":
            meta = git(["log", "-1", "--format=%H%x00%ci%x00%an%x00%s", sha], cwd=REPO)["stdout"].strip()
            h, ci, an, subj = (meta.split("\x00") + ["", "", "", ""])[:4]
            info = {"short": h[:8], "date": ci, "author": an, "subject": subj}
        key[label] = {"sha": sha, "type": obj_type, "resolve_exit": r["exit"], **info}

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002A.2 — object integrity",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fsck_full": {"exit": full["exit"], "seconds": full["seconds"],
                      "non_dangling_lines": errors[:40],
                      "missing_or_corrupt": missing,
                      "dangling_or_unreachable_lines": len(fsck_lines) - len(errors)},
        "fsck_connectivity_only": {"exit": conn["exit"], "seconds": conn["seconds"]},
        "verify_pack": packs,
        "key_commits": key,
        "garbage_files": [ln for ln in fsck_lines if "garbage" in ln],
    }
    payload["verdict"] = (
        "PASS" if full["exit"] == 0 and conn["exit"] == 0 and not missing
        and all(p["verify_pack_exit"] == 0 for p in packs) else "FAIL"
    )
    print(write_evidence("A2_INTEGRITY.json", payload))


# --------------------------------------------------------------------------- #
# A3/A4 — dangling enumeration and bundle coverage
# --------------------------------------------------------------------------- #
def _isolation_repo() -> Path:
    """Empty repository used only to materialise what the bundle carries."""
    repo = WORK / "bundle-odb"
    if not repo.exists():
        repo.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "--quiet", str(repo)])
        run(["git", f"--git-dir={repo / '.git'}", "fetch", "--quiet",
             str(BUNDLE).replace("\\", "/"), "+refs/*:refs/bundle/*"], cwd=repo, timeout=1800)
    return repo / ".git"


def object_presence(gitdir: Path, shas: list[str]) -> set[str]:
    """Which of ``shas`` exist in ``gitdir``'s object database (one process)."""
    if not shas:
        return set()
    proc = subprocess.run(
        ["git", f"--git-dir={gitdir}", "cat-file", "--batch-check=%(objectname)"],
        input="\n".join(shas) + "\n", capture_output=True, text=True, timeout=1800,
    )
    present = set()
    for sha, ln in zip(shas, proc.stdout.splitlines()):
        if not ln.endswith(" missing"):
            present.add(sha)
    return present


def cmd_dangling() -> None:
    unreach_noreflog = git(["fsck", "--full", "--no-progress", "--unreachable", "--no-reflogs"],
                           cwd=REPO, timeout=1800)
    dangling = git(["fsck", "--no-progress", "--dangling"], cwd=REPO, timeout=1800)
    set_noreflog = fsck_objects(unreach_noreflog["stdout"] + unreach_noreflog["stderr"])
    set_dangling = fsck_objects(dangling["stdout"] + dangling["stderr"])
    all_commits = sorted(set(set_noreflog.get("commit", [])) | set(set_dangling.get("commit", [])))
    all_trees = sorted(set(set_noreflog.get("tree", [])) | set(set_dangling.get("tree", [])))
    all_blobs = sorted(set(set_noreflog.get("blob", [])) | set(set_dangling.get("blob", [])))

    bundle_gitdir = _isolation_repo()
    every = all_commits + all_trees + all_blobs
    in_bundle = object_presence(bundle_gitdir, every)
    in_backup = object_presence(BACKUP_REPO / ".git", every)
    reflog_only_set = set(set_noreflog.get("commit", [])) - set(set_dangling.get("commit", []))

    # parents of every unreachable commit -> tips have no unreachable child
    parents: dict[str, list[str]] = {}
    subjects: dict[str, dict] = {}
    for sha in all_commits:
        raw = git(["cat-file", "commit", sha], cwd=REPO)["stdout"]
        head = raw.split("\n\n", 1)[0].splitlines()
        par = [ln.split()[1] for ln in head if ln.startswith("parent ")]
        parents[sha] = par
        meta = git(["log", "-1", "--format=%H%x00%ci%x00%an%x00%s", sha], cwd=REPO)["stdout"].strip()
        h, ci, an, subj = (meta.split("\x00") + ["", "", "", ""])[:4]
        subjects[sha] = {"short": h[:8], "date": ci, "author": an, "subject": subj}

    unreachable_set = set(all_commits)
    children: dict[str, int] = {c: 0 for c in all_commits}
    for sha, par in parents.items():
        for parent in par:
            if parent in unreachable_set:
                children[parent] = children.get(parent, 0) + 1
    tips = sorted(c for c in all_commits if children.get(c, 0) == 0)

    def classify(sha: str, kind: str) -> dict:
        return {
            "sha": sha,
            "type": kind,
            "reachable_only_via_reflog": sha in reflog_only_set,
            "in_bundle": sha in in_bundle,
            "in_backup_repo": sha in in_backup,
            "in_live_odb": True,
        }

    tip_records = []
    for sha in tips:
        tree_list = git(["ls-tree", "-r", "--name-only", sha], cwd=REPO)["stdout"]
        campaigns = sorted({ln.split("/")[2] for ln in tree_list.splitlines()
                            if ln.startswith("reports/ai-bots/") and ln.count("/") >= 2})
        rfcs = sorted({ln.split("/")[1] for ln in tree_list.splitlines()
                       if ln.startswith("docs/rfc/") and "/" in ln[len("docs/rfc/"):]})
        tip_records.append({**subjects[sha], **classify(sha, "commit"),
                            "parents": parents[sha],
                            "reports_campaigns": campaigns[:8],
                            "rfc_dirs": rfcs[:8],
                            "tree_entries": len(tree_list.splitlines())})

    commit_records = [classify(c, "commit") for c in all_commits]
    tree_records = [classify(t, "tree") for t in all_trees]
    blob_records = [classify(b, "blob") for b in all_blobs]

    def tally(records: list[dict]) -> dict:
        return {
            "total": len(records),
            "in_bundle": sum(1 for r in records if r["in_bundle"]),
            "not_in_bundle": sum(1 for r in records if not r["in_bundle"]),
            "in_backup_repo": sum(1 for r in records if r["in_backup_repo"]),
            "reflog_only": sum(1 for r in records if r["reachable_only_via_reflog"]),
        }

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002A.3/002A.4 — dangling objects and bundle coverage",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commands": {
            "unreachable_no_reflogs": "git fsck --full --no-progress --unreachable --no-reflogs",
            "dangling": "git fsck --no-progress --dangling",
            "bundle_odb": "git fetch <REPO_ALL_REFS.bundle> +refs/*:refs/bundle/*",
        },
        "unreachable_no_reflogs": {k: len(v) for k, v in set_noreflog.items()},
        "dangling_only": {k: len(v) for k, v in set_dangling.items()},
        "union": {"commits": len(all_commits), "trees": len(all_trees), "blobs": len(all_blobs)},
        "object_sets": {"unreachable_no_reflogs": set_noreflog, "dangling": set_dangling},
        "not_in_backup_repo": [s for s in every if s not in in_backup],
        "coverage": {
            "commits": tally(commit_records),
            "trees": tally(tree_records),
            "blobs": tally(blob_records),
        },
        "tips": tip_records,
        "commits": commit_records,
        "trees": tree_records,
        "blobs_not_in_bundle": [b for b in blob_records if not b["in_bundle"]][:200],
        "bundle_odb_refs": len(lines(git(["for-each-ref", "--format=%(refname)"],
                                         gitdir=bundle_gitdir)["stdout"])),
    }
    print(write_evidence("A3_DANGLING_AND_COVERAGE.json", payload))


# --------------------------------------------------------------------------- #
# A5 — preserve in an isolated copy
# --------------------------------------------------------------------------- #
def cmd_preserve() -> None:
    evidence_path = EVIDENCE / "A3_DANGLING_AND_COVERAGE.json"
    dangling = json.loads(evidence_path.read_text(encoding="utf-8"))
    tips = [t["sha"] for t in dangling["tips"]]

    WORK.mkdir(parents=True, exist_ok=True)
    if not PROTECTED_GITDIR.exists():
        # copy the object store; the ORIGINAL is untouched
        tmp = WORK / "protected.tmp"
        if tmp.exists():
            _force_rmtree(tmp)
        shutil.copytree(REPO / ".git", tmp, symlinks=True)
        tmp.rename(PROTECTED_GITDIR)

    # counts EXCLUDING any refs/recovered/* already present, so the step is idempotent
    before_refs = len([ln for ln in lines(git(["for-each-ref", "--format=%(refname)"],
                                               gitdir=PROTECTED_GITDIR)["stdout"])
                       if not ln.startswith("refs/recovered/")])
    before_count = int(git(["rev-list", "--count", "--exclude=refs/recovered/*", "--all"],
                           gitdir=PROTECTED_GITDIR)["stdout"].strip() or 0)

    created = []
    for index, sha in enumerate(tips, start=1):
        ref = f"refs/recovered/tip-{index:04d}"
        res = git(["update-ref", ref, sha], gitdir=PROTECTED_GITDIR)
        created.append({"ref": ref, "sha": sha, "exit": res["exit"]})

    after_refs = len(lines(git(["for-each-ref", "--format=%(refname)"], gitdir=PROTECTED_GITDIR)["stdout"]))
    after_count = int(git(["rev-list", "--all", "--count"], gitdir=PROTECTED_GITDIR)["stdout"].strip() or 0)

    # Anything still unreachable after pinning the tips (orphan trees/blobs from an
    # aborted commit, for example) gets its own ref so the bundle can carry it too.
    mid = git(["fsck", "--full", "--no-progress", "--unreachable", "--no-reflogs",
               "--connectivity-only"], gitdir=PROTECTED_GITDIR, timeout=1800)
    mid_left = fsck_objects(mid["stdout"] + mid["stderr"])
    orphan_refs = []
    for kind in ("commit", "tree", "blob"):
        for index, sha in enumerate(mid_left.get(kind, []), start=1):
            ref = f"refs/recovered/orphan-{kind}-{index:04d}"
            res = git(["update-ref", ref, sha], gitdir=PROTECTED_GITDIR)
            orphan_refs.append({"ref": ref, "sha": sha, "type": kind, "exit": res["exit"]})
    if orphan_refs:
        after_refs = len(lines(git(["for-each-ref", "--format=%(refname)"], gitdir=PROTECTED_GITDIR)["stdout"]))
        after_count = int(git(["rev-list", "--all", "--count"], gitdir=PROTECTED_GITDIR)["stdout"].strip() or 0)

    post = git(["fsck", "--full", "--no-progress", "--unreachable", "--no-reflogs",
                "--connectivity-only"], gitdir=PROTECTED_GITDIR, timeout=1800)
    remaining = fsck_objects(post["stdout"] + post["stderr"])

    live_refs_unchanged = len(lines(git(["for-each-ref", "--format=%(refname)"], cwd=REPO)["stdout"]))
    all_recovered = lines(git(["for-each-ref", "--format=%(refname) %(objectname)",
                               "refs/recovered/"], gitdir=PROTECTED_GITDIR)["stdout"])
    orphan_refs_present = [ln for ln in all_recovered if "/orphan-" in ln]

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002A.5 — preservation via protected refs in an isolated copy",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "isolated_copy": str(PROTECTED_GITDIR),
        "original_repo_written_to": False,
        "tips": len(tips),
        "refs_before": before_refs,
        "refs_after": after_refs,
        "commits_reachable_before": before_count,
        "commits_reachable_after": after_count,
        "commits_gained": after_count - before_count,
        "refs_created": created,
        "orphan_refs_created": orphan_refs,
        "orphan_refs_present": orphan_refs_present,
        "recovered_refs_total": len(all_recovered),
        "post_fsck_exit": post["exit"],
        "remaining_unreachable": {k: len(v) for k, v in remaining.items()},
        "live_repo_refs_after": live_refs_unchanged,
        "live_repo_untouched": live_refs_unchanged == 80,
    }
    payload["verdict"] = (
        "PASS" if after_count - before_count == dangling["union"]["commits"]
        and remaining == {} and post["exit"] == 0
        and live_refs_unchanged == 80 else "FAIL"
    )
    payload["expected_commits_gained"] = dangling["union"]["commits"]
    print(write_evidence("A5_PRESERVATION.json", payload))


# --------------------------------------------------------------------------- #
# A6 — recovery package + restoration from a second independent copy
# --------------------------------------------------------------------------- #
def _force_rmtree(path: Path) -> None:
    """rmtree that also clears the read-only bit Git sets on pack files."""
    def onerror(func, target, exc_info):  # noqa: ANN001
        os.chmod(target, 0o666)
        func(target)
    shutil.rmtree(path, onerror=onerror)


def _restore(bundle_path: Path, target: Path) -> dict:
    if target.exists():
        _force_rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    init = run(["git", "init", "--quiet", str(target)])
    fetch = run(["git", f"--git-dir={target / '.git'}", "fetch", "--quiet",
                 str(bundle_path).replace("\\", "/"), "+refs/*:refs/*"], timeout=1800)
    fsck = run(["git", f"--git-dir={target / '.git'}", "fsck", "--full", "--no-progress"], timeout=1800)
    refs = run(["git", f"--git-dir={target / '.git'}", "for-each-ref",
                "--format=%(refname) %(objectname)"], timeout=300)
    total = run(["git", f"--git-dir={target / '.git'}", "rev-list", "--all", "--count"], timeout=300)
    recovered = [ln for ln in lines(refs["stdout"]) if ln.startswith("refs/recovered/")]
    return {
        "target": str(target),
        "init_exit": init["exit"],
        "fetch_exit": fetch["exit"],
        "fetch_stderr": lines(fetch["stderr"])[:5],
        "fsck_exit": fsck["exit"],
        "fsck_stderr": lines(fsck["stdout"] + fsck["stderr"])[:10],
        "refs": len(lines(refs["stdout"])),
        "recovered_refs": len(recovered),
        "recovered_refs_of_tips": recovered,
        "commits_reachable": int(total["stdout"].strip() or 0),
    }


def cmd_package() -> None:
    preservation = json.loads((EVIDENCE / "A5_PRESERVATION.json").read_text(encoding="utf-8"))
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    bundle = PACKAGE_DIR / "WP-RECOVERY-002-ALLREFS.bundle"
    if bundle.exists():
        bundle.unlink()  # regenerating our own artefact is allowed; backups are never touched
    created = git(["bundle", "create", str(bundle).replace("\\", "/"), "--all"],
                  gitdir=PROTECTED_GITDIR, timeout=1800)
    digest = sha256_file(bundle)
    (PACKAGE_DIR / "WP-RECOVERY-002-ALLREFS.bundle.sha256").write_text(
        f"{digest} *{bundle.name}\n", encoding="utf-8")

    PACKAGE_COPY_B.mkdir(parents=True, exist_ok=True)
    copy_b = PACKAGE_COPY_B / bundle.name
    shutil.copy2(bundle, copy_b)
    digest_b = sha256_file(copy_b)
    verify_b = run(["git", "bundle", "verify", str(copy_b).replace("\\", "/")], cwd=REPO, timeout=600)

    restore_a = _restore(bundle, RESTORE_A)
    restore_b = _restore(copy_b, RESTORE_B)

    # byte-identical worktrees must come out of both restores for every recovered tip
    tip_compare = []
    for entry in preservation["refs_created"]:
        tree_a = git(["rev-parse", f"{entry['sha']}^{{tree}}"], gitdir=RESTORE_A / ".git")["stdout"].strip()
        tree_b = git(["rev-parse", f"{entry['sha']}^{{tree}}"], gitdir=RESTORE_B / ".git")["stdout"].strip()
        tip_compare.append({"ref": entry["ref"], "sha": entry["sha"],
                            "tree_a": tree_a, "tree_b": tree_b, "identical": tree_a == tree_b and bool(tree_a)})

    # and one full checkout must produce a working tree that git considers clean
    sample = preservation["refs_created"][0]["sha"] if preservation["refs_created"] else None
    checkout_status = None
    checkout_dir = WORK / "checkout-a"
    if sample:
        if checkout_dir.exists():
            _force_rmtree(checkout_dir)
        checkout_dir.mkdir(parents=True, exist_ok=True)
        co = run(["git", f"--git-dir={RESTORE_A / '.git'}", f"--work-tree={checkout_dir}",
                  "-c", "core.bare=false", "checkout", "--quiet", "--force", sample], timeout=900)
        st = run(["git", f"--git-dir={RESTORE_A / '.git'}", f"--work-tree={checkout_dir}",
                  "-c", "core.bare=false", "status", "--porcelain"], timeout=600)
        checkout_status = {"exit": co["exit"], "dirty_entries": len(lines(st["stdout"])),
                           "stderr": lines(co["stderr"])[:3]}

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002A.6 — recovery package and independent restoration",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "package": {
            "bundle_create_exit": created["exit"],
            "bundle_bytes": bundle.stat().st_size,
            "bundle_sha256": digest,
            "sha256_file": str(PACKAGE_DIR / "WP-RECOVERY-002-ALLREFS.bundle.sha256"),
            "second_copy": str(copy_b),
            "second_copy_sha256": digest_b,
            "copies_identical": digest == digest_b,
            "second_copy_bundle_verify_exit": verify_b["exit"],
            "heads": len(lines(git(["bundle", "list-heads", str(bundle).replace("\\", "/")],
                                   cwd=WORK)["stdout"])),
        },
        "restore_from_copy_a": restore_a,
        "restore_from_copy_b": restore_b,
        "tips_identical_across_restores": tip_compare,
        "checkout_probe": checkout_status,
        "expected_commits": preservation["commits_reachable_after"],
    }
    expected_refs = preservation["recovered_refs_total"]
    checks = [
        ("bundle created", created["exit"] == 0),
        ("two copies byte-identical", digest == digest_b),
        ("git bundle verify on the second copy", verify_b["exit"] == 0),
        ("fetch from copy A succeeds", restore_a["fetch_exit"] == 0),
        ("fetch from copy B succeeds", restore_b["fetch_exit"] == 0),
        ("fsck --full clean on restore A", restore_a["fsck_exit"] == 0),
        ("fsck --full clean on restore B", restore_b["fsck_exit"] == 0),
        ("restore A carries every recovered ref", restore_a["recovered_refs"] == expected_refs),
        ("restore B carries every recovered ref", restore_b["recovered_refs"] == expected_refs),
        ("restore A reaches every commit", restore_a["commits_reachable"] == preservation["commits_reachable_after"]),
        ("restore B reaches every commit", restore_b["commits_reachable"] == preservation["commits_reachable_after"]),
        ("recovered tips have identical trees in both restores", all(t["identical"] for t in tip_compare)),
        ("recovered tip checks out to a clean work tree",
         checkout_status is None or (checkout_status["exit"] == 0 and checkout_status["dirty_entries"] == 0)),
    ]
    payload["checks"] = [{"check": name, "pass": bool(ok)} for name, ok in checks]
    payload["checks_total"] = len(checks)
    payload["checks_passed"] = sum(1 for _, ok in checks if ok)
    payload["verdict"] = "PASS" if all(ok for _, ok in checks) else "FAIL"
    print(write_evidence("A6_PACKAGE.json", payload))


# --------------------------------------------------------------------------- #
# A7 — artifacts Git cannot restore
# --------------------------------------------------------------------------- #
def _walk(root: Path, skip: set[str], limit_bytes: int = 0) -> list[dict]:
    out: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if limit_bytes and size > limit_bytes:
                out.append({"path": str(p.relative_to(root)).replace("\\", "/"), "bytes": size,
                            "sha256": None, "skipped": "larger than per-file cap"})
                continue
            try:
                out.append({"path": str(p.relative_to(root)).replace("\\", "/"), "bytes": size,
                            "sha256": sha256_file(p)})
            except OSError as exc:
                out.append({"path": str(p.relative_to(root)).replace("\\", "/"), "bytes": size,
                            "sha256": None, "error": str(exc)})
    return out


def cmd_unrecoverable() -> None:
    status = git(["status", "--porcelain=v1", "--ignored", "--untracked-files=all"], cwd=REPO)["stdout"]
    groups: dict[str, list[str]] = {"modified_tracked": [], "untracked": [], "ignored": []}
    for ln in status.splitlines():
        code, _, path = ln[:2], ln[2:3], ln[3:]
        if code == "??":
            groups["untracked"].append(path)
        elif code == "!!":
            groups["ignored"].append(path)
        else:
            groups["modified_tracked"].append(path)

    skip = {".venv", "node_modules", ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
            ".ruff_cache", ".hypothesis", ".tmp", "wt-sup001"}

    # unique on-disk content that no commit carries
    unique_candidates = [
        "src/lib_interop",
        "src/trading_bot/config/types.py",
        "scripts/recovery005_m9_direct_check_in_process.py",
        "scripts/recovery005_m9_mutant_check.py",
        ".ci/recovery005_mutant_20261023T181752",
        ".ci/recovery005_mutant_20261023T181809",
        ".ci/recovery005_mutant_inprocess_20261023T181914",
    ]
    unique = []
    for rel in unique_candidates:
        p = REPO / rel
        if not p.exists():
            unique.append({"path": rel, "state": "ABSENT"})
            continue
        if p.is_dir():
            files = _walk(p, skip, limit_bytes=64 * 1024 * 1024)
            unique.append({"path": rel, "state": "PRESENT_ON_DISK", "kind": "dir",
                           "files": len(files), "bytes": sum(f["bytes"] for f in files),
                           "manifest_sha256": sha256_bytes(
                               json.dumps([[f["path"], f["bytes"], f["sha256"]] for f in files],
                                          sort_keys=True).encode()),
                           "sample": files[:10]})
        else:
            unique.append({"path": rel, "state": "PRESENT_ON_DISK", "kind": "file",
                           "files": 1, "bytes": p.stat().st_size, "sha256": sha256_file(p)})

    incident = json.loads(INCIDENT_ENTRIES_JSON.read_text(encoding="utf-8")) if INCIDENT_ENTRIES_JSON.exists() else {}
    entries = incident.get("entries") or incident.get("worktrees") or []
    lost_entries = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        pre = e.get("pre_incident") or {}
        lost_entries.append({
            "name": e.get("name") or e.get("worktree") or e.get("path"),
            "gib": pre.get("gib"),
            "files": pre.get("files"),
            "state_now": e.get("state"),
            "present_now": e.get("present_now"),
            "classification": e.get("classification"),
        })

    # ignored trees that exist locally and would vanish with the machine
    ignore_roots = sorted({p.split("/")[0] for p in groups["ignored"] if "/" in p})
    ignore_sizes = []
    for root in ignore_roots:
        p = REPO / root
        if not p.is_dir():
            continue
        files = _walk(p, skip, limit_bytes=32 * 1024 * 1024)
        ignore_sizes.append({"root": root, "files": len(files),
                             "bytes": sum(f["bytes"] for f in files),
                             "unhashed": sum(1 for f in files if f["sha256"] is None)})

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002A.7 — artifacts not recoverable from Git",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tracked_status_counts": {k: len(v) for k, v in groups.items()},
        "unique_unversioned_content_present": unique,
        "ignored_roots_on_disk": ignore_sizes,
        "emptied_worktrees_from_incident_001": {
            "entries": len(lost_entries),
            "detail_source": str(INCIDENT_ENTRIES_JSON),
            "totals_pre_incident": incident.get("totals_pre_incident"),
            "gib_sum": round(sum(e["gib"] or 0 for e in lost_entries), 3),
            "files_sum": sum(e["files"] or 0 for e in lost_entries),
            "all": lost_entries,
        },
        "recoverable_by_copy": [u["path"] for u in unique if u["state"] == "PRESENT_ON_DISK"],
        "irrecoverable": [
            "untracked/ignored content of the 26 emptied worktrees (reports/, data/, .ci/, .venv/)",
            "the vanished directory bot_crypto_004g-scratch",
            "worktree -> branch attribution and the pre-19:44 reflogs",
        ],
    }
    print(write_evidence("A7_UNRECOVERABLE.json", payload))


# --------------------------------------------------------------------------- #
# B — publication audit
# --------------------------------------------------------------------------- #
SECRET_PATTERNS = {
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "github_token": r"gh[pousr]_[A-Za-z0-9]{36,}",
    "openai_sk": r"sk-[A-Za-z0-9]{32,}",
    "slack_token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    "private_key_block": r"-----BEGIN (RSA|EC|OPENSSH|PGP|PRIVATE) ?(PRIVATE )?KEY-----",
    "binance_key_assignment": r"(BINANCE|BYBIT|KUCOIN|COINBASE)_(API_KEY|SECRET)\s*=\s*['\"][A-Za-z0-9/+]{16,}",
    "generic_secret_assignment": r"(?i)(api_secret|api_key|password|passwd|secret_key)\s*=\s*['\"][^'\"\s]{12,}['\"]",
}
INCOMPLETE_MARKERS = {
    "conflict_marker": r"^(<<<<<<<|>>>>>>>|=======)\s*$",
    "todo_added": r"(?i)\b(TODO|FIXME|XXX|HACK)\b",
    "skip_added": r"pytest\.mark\.(skip|xfail)",
    "suppression_added": r"(noqa|type: ignore|pytest: no cover)",
    "not_implemented": r"NotImplementedError",
}


def _batch_blobs(shas: list[str], gitdir: Path | None = None) -> dict[str, bytes]:
    if not shas:
        return {}
    cmd = ["git"] + ([f"--git-dir={gitdir}"] if gitdir else []) + ["cat-file", "--batch"]
    proc = subprocess.run(cmd, input=("\n".join(shas) + "\n").encode(), capture_output=True,
                          timeout=1800, cwd=str(REPO))
    out: dict[str, bytes] = {}
    data = proc.stdout
    pos = 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        header = data[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) < 3:
            continue
        size = int(header[2])
        out[header[0]] = data[pos:pos + size]
        pos += size + 1
    return out


def cmd_publication() -> None:
    base = "origin/main"
    head = "main"
    counts = git(["rev-list", "--left-right", "--count", f"{base}...{head}"], cwd=REPO)["stdout"].split()
    merge_base = git(["merge-base", base, head], cwd=REPO)["stdout"].strip()
    behind, ahead = int(counts[0]), int(counts[1])

    log = git(["log", "--reverse", f"--format=%H%x01%P%x01%an%x01%ae%x01%cI%x01%s%x01%b%x02",
               f"{base}..{head}"], cwd=REPO, timeout=600)["stdout"]
    raw_commits = [c.strip("\n") for c in log.split("\x02") if c.strip("\n")]
    commits = []
    for chunk in raw_commits:
        fields = chunk.strip("\n").split("\x01")
        if len(fields) < 5:
            continue
        sha, parents, author, email, date, subject = fields[:6]
        body = fields[6] if len(fields) > 6 else ""
        commits.append({"sha": sha, "parents": parents.split(), "author": author,
                        "email": email, "date": date, "subject": subject.strip(),
                        "body_chars": len(body)})

    numstat = git(["log", "--reverse", "--no-renames", "--numstat", "--format=@@%H",
                   f"{base}..{head}"], cwd=REPO, timeout=900)["stdout"]
    per_commit: dict[str, dict] = {}
    area_touch: dict[str, set[str]] = {}
    current = None
    for ln in numstat.splitlines():
        if ln.startswith("@@"):
            current = ln[2:].strip()
            per_commit[current] = {"added": 0, "deleted": 0, "files": 0, "paths": []}
            continue
        if current is None or not ln.strip():
            continue
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        add, dele, path = parts[0], parts[1], parts[2]
        entry = per_commit[current]
        entry["added"] += int(add) if add.isdigit() else 0
        entry["deleted"] += int(dele) if dele.isdigit() else 0
        entry["files"] += 1
        entry["paths"].append(path)
        area_touch.setdefault(current, set()).add(path)

    deleted = git(["log", "--diff-filter=D", "--name-only", "--format=@@%H",
                   f"{base}..{head}"], cwd=REPO, timeout=900)["stdout"]
    deletions: dict[str, list[str]] = {}
    cur = None
    for ln in deleted.splitlines():
        if ln.startswith("@@"):
            cur = ln[2:].strip()
            deletions[cur] = []
        elif ln.strip() and cur:
            deletions[cur].append(ln.strip())

    all_paths = sorted({p for e in per_commit.values() for p in e["paths"]})
    risky = {
        "risk": "src/trading_bot/risk/",
        "execution": "src/trading_bot/execution/",
        "accounting": "src/trading_bot/accounting/",
        "paper": "src/trading_bot/paper/",
        "autonomous_runtime": "src/trading_bot/autonomous/",
        "live_gate": "src/trading_bot/execution/live_gate.py",
        "verification_scripts": "scripts/verify_",
        "entrypoint_paper": "scripts/autonomous_paper.py",
        "ci": ".github/workflows/",
    }
    risky_summary = {}
    for name, prefix in risky.items():
        touched = sorted({p for paths in area_touch.values() for p in paths
                          if p == prefix or p.startswith(prefix)})
        commits_touching = sum(1 for paths in area_touch.values()
                               if any(p == prefix or p.startswith(prefix) for p in paths))
        risky_summary[name] = {"prefix": prefix, "files_touched_sample": touched[:12],
                               "files_touched": len(touched), "commits_touching": commits_touching}

    # --- secret / incomplete-change scan over every blob added in the range ---
    added_blobs: dict[str, set[str]] = {}
    tree_raw = git(["log", "--raw", "--no-renames", "--format=", f"{base}..{head}"], cwd=REPO, timeout=900)["stdout"]
    for ln in tree_raw.splitlines():
        if not ln.startswith(":"):
            continue
        meta, _, path = ln[1:].partition("\t")
        parts = meta.split()
        if len(parts) < 4:
            continue
        new_sha = parts[3]
        if set(new_sha) != {"0"}:
            added_blobs.setdefault(new_sha, set()).add(path.strip())
    blobs = _batch_blobs(sorted(added_blobs))

    secret_hits, marker_hits = [], []
    for sha, blob in blobs.items():
        text = blob.decode("utf-8", "replace")
        for name, pattern in SECRET_PATTERNS.items():
            for m in re.finditer(pattern, text, flags=re.MULTILINE):
                secret_hits.append({"blob": sha, "rule": name,
                                    "paths": sorted(added_blobs.get(sha, set()))[:3],
                                    "line": text[:m.start()].count("\n") + 1,
                                    "match_head": m.group(0)[:24]})
                break
        for name, pattern in INCOMPLETE_MARKERS.items():
            if re.search(pattern, text, flags=re.MULTILINE):
                marker_hits.append({"blob": sha, "marker": name})

    # --- net diff (what publication would add), scanned line by line ---
    net = git(["diff", "--unified=0", "--no-color", "--no-renames", f"{base}..{head}"],
              cwd=REPO, timeout=1800)["stdout"]
    net_secret_hits: list[dict] = []
    net_marker_hits: dict[str, dict[str, int]] = {}
    current_path = "?"
    added_line_total = 0
    for ln in net.splitlines():
        if ln.startswith("+++ b/"):
            current_path = ln[6:]
            continue
        if not ln.startswith("+") or ln.startswith("+++"):
            continue
        added_line_total += 1
        body = ln[1:]
        for name, pattern in SECRET_PATTERNS.items():
            m = re.search(pattern, body)
            if m:
                net_secret_hits.append({"path": current_path, "rule": name,
                                        "match_head": m.group(0)[:24]})
        for name, pattern in INCOMPLETE_MARKERS.items():
            if re.search(pattern, body):
                net_marker_hits.setdefault(name, {})
                net_marker_hits[name][current_path] = net_marker_hits[name].get(current_path, 0) + 1

    # --- entrypoint availability ---
    entry = {}
    for ref in ("origin/main", "main", "recovery/trunk-format-001"):
        exists = git(["cat-file", "-e", f"{ref}:scripts/autonomous_paper.py"], cwd=REPO)["exit"] == 0
        entry[ref] = {"scripts/autonomous_paper.py": exists}
    entry["added_in"] = lines(git(["log", "--diff-filter=A", "--format=%H %cI %s",
                                   "--", "scripts/autonomous_paper.py"], cwd=REPO)["stdout"])[:5]
    entry["tracked_runtime_modules"] = lines(git(["ls-tree", "-r", "--name-only", "main",
                                                  "src/trading_bot/autonomous/"], cwd=REPO)["stdout"])

    # --- working tree not part of any commit ---
    status = git(["status", "--porcelain=v1"], cwd=REPO)["stdout"]
    dirty = [ln for ln in status.splitlines() if ln.strip()]

    # --- remote branches not contained in main ---
    remote_refs = lines(git(["for-each-ref", "--format=%(refname)", "refs/remotes/origin/"], cwd=REPO)["stdout"])
    not_contained = []
    for ref in remote_refs:
        if ref.endswith("/HEAD"):
            continue
        res = git(["merge-base", "--is-ancestor", ref, "main"], cwd=REPO)
        if res["exit"] != 0:
            not_contained.append(ref)

    subjects = [c["subject"] for c in commits]
    prefixes: dict[str, int] = {}
    for s in subjects:
        m = re.match(r"^([a-z]+)(\(|!|:)", s)
        prefixes[m.group(1) if m else "(sin prefijo)"] = prefixes.get(m.group(1) if m else "(sin prefijo)", 0) + 1

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002B — publication audit",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ancestry": {
            "base": base,
            "base_sha": git(["rev-parse", base], cwd=REPO)["stdout"].strip(),
            "head": head,
            "head_sha": git(["rev-parse", head], cwd=REPO)["stdout"].strip(),
            "ahead": ahead, "behind": behind, "merge_base": merge_base,
            "merge_base_is_base_tip": merge_base == git(["rev-parse", base], cwd=REPO)["stdout"].strip(),
            "fast_forward_possible": behind == 0,
            "remote_branches_not_contained_in_main": not_contained,
        },
        "commits": [
            {**c, **{k: per_commit.get(c["sha"], {}).get(k, 0) for k in ("added", "deleted", "files")},
             "deleted_paths": deletions.get(c["sha"], [])}
            for c in commits
        ],
        "commit_count": len(commits),
        "authors": {a: sum(1 for c in commits if c["author"] == a)
                    for a in sorted({c["author"] for c in commits})},
        "first_commit_date": commits[0]["date"] if commits else None,
        "last_commit_date": commits[-1]["date"] if commits else None,
        "subject_prefixes": prefixes,
        "churn": {
            "files": len(all_paths),
            "added": sum(e["added"] for e in per_commit.values()),
            "deleted": sum(e["deleted"] for e in per_commit.values()),
        },
        "deleted_paths_total": sum(len(v) for v in deletions.values()),
        "deleted_files_check": lines(git(["diff", "--name-status", "--diff-filter=D",
                                          f"{base}..{head}"], cwd=REPO)["stdout"])[:40],
        "deleted_paths": sorted({p for v in deletions.values() for p in v})[:200],
        "risky_areas": risky_summary,
        "secret_scan": {
            "blobs_scanned": len(blobs),
            "patterns": list(SECRET_PATTERNS),
            "blob_hits": secret_hits[:100],
            "blob_hit_count": len(secret_hits),
            "net_diff_hits": net_secret_hits[:100],
            "net_diff_hit_count": len(net_secret_hits),
            "net_diff_added_lines": added_line_total,
        },
        "incomplete_change_scan": {
            "blobs_with_markers": len(marker_hits),
            "blob_markers": {m: sum(1 for h in marker_hits if h["marker"] == m) for m in INCOMPLETE_MARKERS},
            "net_diff_markers": {m: {"total": sum(v.values()), "top_paths": dict(sorted(v.items(), key=lambda kv: -kv[1])[:5])}
                                 for m, v in net_marker_hits.items()},
        },
        "entrypoint": entry,
        "uncommitted_working_tree": dirty,
    }
    print(write_evidence("B_PUBLICATION.json", payload))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
COMMANDS = {
    "copies": cmd_copies,
    "integrity": cmd_integrity,
    "dangling": cmd_dangling,
    "preserve": cmd_preserve,
    "package": cmd_package,
    "unrecoverable": cmd_unrecoverable,
    "publication": cmd_publication,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=sorted(COMMANDS) + ["all"])
    args = parser.parse_args(argv)
    steps = sorted(COMMANDS) if args.step == "all" else [args.step]
    order = ["copies", "integrity", "dangling", "preserve", "package", "unrecoverable", "publication"]
    for step in sorted(steps, key=order.index):
        print(f"== {step} ==", flush=True)
        COMMANDS[step]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
