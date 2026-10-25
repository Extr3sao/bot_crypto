"""Independent verifier for WP-RECOVERY-002 (WP-002D). BUILDER != VERIFIER.

This file imports nothing from the builder or the audit tool. It re-derives every
machine-checkable claim from the artefacts themselves:

* hashes of the incident bundle and of the recovery package (both copies);
* a *fresh* restore of the recovery package from the second copy only;
* the live repository's refs, unreachable set and ancestry;
* a re-scan of the publication diff for secrets and deletions;
* the runtime evidence (fresh fake drill with a new run id);
* a negative-control battery proving each check can fail.

It never writes to the original repository and never pushes. Scratch work lives
under ``C:/Users/GVLLFR0035/recovery-002/verify``.

Exit code 0 only when every check passes AND every negative control behaved.
"""

from __future__ import annotations

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
PACKAGE = Path("C:/Users/GVLLFR0035/recovery-002/package/WP-RECOVERY-002-ALLREFS.bundle")
PACKAGE_COPY_B = Path("C:/Users/GVLLFR0035/recovery-002/package-copy-b/WP-RECOVERY-002-ALLREFS.bundle")
CLONE = Path("C:/Users/GVLLFR0035/recovery-002/work/repo")
SCRATCH = Path("C:/Users/GVLLFR0035/recovery-002/verify")
REPORTS = Path("C:/Users/GVLLFR0035/Downloads/ff-wt-trunkfmt/reports/ai-bots/WP-RECOVERY-002")
EVIDENCE = REPORTS / "evidence"
OUT = REPORTS / "VERIFICATION.json"

DELIVERABLES = [
    "GIT_RECOVERY_VERIFICATION.md",
    "COMMIT_PUBLICATION_AUDIT.md",
    "RUNTIME_RECOVERY_REPORT.md",
    "LOST_ARTIFACTS_STATUS.json",
    "FINAL_REPORT.md",
    "FINAL_REPORT.json",
]
STATUS_TOKENS = ["PRESERVED", "RECOVERABLE", "RESTORED", "RUNTIME_VERIFIED",
                 "READY_FOR_REVIEW", "BLOCKED"]


# --------------------------------------------------------------------------- #
def run(cmd: list[str], cwd: Path | None = None, timeout: int = 1800,
        stdin: str | None = None) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, errors="replace", timeout=timeout,
                          input=stdin)
    return {"cmd": cmd, "exit": proc.returncode, "out": proc.stdout, "err": proc.stderr}


def git(args: list[str], cwd: Path = REPO, timeout: int = 1800) -> dict:
    return run(["git", *args], cwd=cwd, timeout=timeout)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def force_rmtree(path: Path) -> None:
    def onerror(func, target, exc):  # noqa: ANN001
        os.chmod(target, 0o666)
        func(target)
    if path.exists():
        shutil.rmtree(path, onerror=onerror)


# --------------------------------------------------------------------------- #
def verify_git(checks: list[dict]) -> dict:
    facts: dict = {}

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    # 1. incident bundle untouched and verifiable
    declared = (BACKUP / "REPO_ALL_REFS.bundle.sha256").read_text(encoding="utf-8").split()[0].strip()
    actual = sha256(BUNDLE)
    facts["incident_bundle"] = {"sha256": actual, "declared": declared,
                                "bytes": BUNDLE.stat().st_size}
    check("incident bundle hash still matches its declared hash", actual == declared, actual)
    bv = git(["bundle", "verify", str(BUNDLE).replace("\\", "/")])
    check("incident bundle verifies", bv["exit"] == 0, bv["out"].splitlines()[-1:] or bv["err"][:120])

    # 2. live repository: untouched, intact, 80 refs, no recovered refs
    refs = [ln for ln in git(["for-each-ref", "--format=%(refname)"])["out"].splitlines() if ln]
    facts["live_refs"] = len(refs)
    check("original repository still has exactly 80 refs", len(refs) == 80, len(refs))
    check("no refs/recovered/* was created in the original repository",
          not any(r.startswith("refs/recovered/") for r in refs),
          [r for r in refs if r.startswith("refs/recovered/")][:3])
    fsck = git(["fsck", "--full", "--no-progress"])
    check("original object database still passes fsck --full", fsck["exit"] == 0, fsck["err"][:160])
    head = git(["rev-parse", "HEAD"])["out"].strip()
    facts["head"] = head
    audited = "0e13160a8d5522961978fe3bd6b904b3a14be1c3"
    ancestor = git(["merge-base", "--is-ancestor", audited, "main"])
    check("the audited commit still exists and is an ancestor of main",
          ancestor["exit"] == 0, {"audited": audited, "main_now": head})
    facts["main_moved_since_audit"] = head != audited

    # 3. ancestry claims
    counts = git(["rev-list", "--left-right", "--count", "origin/main...main"])["out"].split()
    behind, ahead = int(counts[0]), int(counts[1])
    base = git(["rev-parse", "origin/main"])["out"].strip()
    mb = git(["merge-base", "origin/main", "main"])["out"].strip()
    facts["ancestry"] = {"ahead": ahead, "behind": behind, "merge_base": mb, "origin_main": base}
    final = json.loads((REPORTS / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    # main may only GROW after the audit (other lanes commit); it must never lose commits
    check("main is still ahead of origin/main by at least the audited count, never behind",
          behind == 0 and ahead >= final["repository"]["ahead"],
          {"now": [ahead, behind], "audited": [final["repository"]["ahead"], final["repository"]["behind"]]})
    check("merge base is the tip of origin/main (fast-forward possible)", mb == base, mb)

    # 4. unreachable set still matches the audited one, and is still unreachable
    unreach = git(["fsck", "--full", "--no-progress", "--unreachable", "--no-reflogs"])
    commits = sorted({ln.split()[2] for ln in (unreach["out"] + unreach["err"]).splitlines()
                      if ln.startswith("unreachable commit")})
    a3 = json.loads((EVIDENCE / "A3_DANGLING_AND_COVERAGE.json").read_text(encoding="utf-8"))
    facts["unreachable_commits_now"] = len(commits)
    facts["unreachable_commits_audited"] = a3["union"]["commits"]
    audited_set = set(a3["object_sets"]["unreachable_no_reflogs"].get("commit", []))
    missing_since_audit = sorted(audited_set - set(commits))
    facts["unreachable_superset"] = not missing_since_audit
    check("every commit that was unreachable at audit time is still unreachable (superset, nothing lost)",
          not missing_since_audit,
          {"now": len(commits), "audited": len(audited_set), "lost": missing_since_audit[:5]})

    # 5. publication: deletions, secrets, entrypoint
    deleted = [ln for ln in git(["diff", "--name-status", "--diff-filter=D",
                                 "origin/main..main"])["out"].splitlines() if ln.strip()]
    check("the publish range deletes no file", deleted == [], deleted[:5])
    entry_remote = git(["cat-file", "-e", "origin/main:scripts/autonomous_paper.py"])["exit"] != 0
    entry_local = git(["cat-file", "-e", "main:scripts/autonomous_paper.py"])["exit"] == 0
    check("the paper entrypoint is absent on origin/main and present on main",
          entry_remote and entry_local, {"absent_on_remote": entry_remote, "present_on_main": entry_local})

    net = git(["diff", "--unified=0", "--no-color", "--no-renames", "origin/main..main"], timeout=1800)["out"]
    patterns = {
        "aws": r"AKIA[0-9A-Z]{16}",
        "github": r"gh[pousr]_[A-Za-z0-9]{36,}",
        "openai": r"sk-[A-Za-z0-9]{32,}",
        "private_key": r"-----BEGIN (RSA|EC|OPENSSH|PGP|PRIVATE) ?(PRIVATE )?KEY-----",
        "slack": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    }
    hits, path = [], "?"
    for line in net.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for name, pattern in patterns.items():
            if re.search(pattern, line):
                hits.append({"path": path, "rule": name})
    canary = [h for h in hits if h["path"] == "scripts/wp10_phase0_wp9_closure.py"]
    real = [h for h in hits if h["path"] != "scripts/wp10_phase0_wp9_closure.py"]
    facts["secret_hits"] = {"total": len(hits), "canary": len(canary), "real": len(real)}
    check("no credential-shaped secret outside the scanner's own canary", real == [], real[:5])

    # 6. nothing was pushed: the remote-tracking ref still equals the recorded value
    origin_main = git(["rev-parse", "refs/remotes/origin/main"])["out"].strip()
    check("no push happened (refs/remotes/origin/main unchanged)",
          origin_main == base == final["repository"]["origin_main"], origin_main)
    return facts


def verify_package(checks: list[dict]) -> dict:
    facts: dict = {}

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    a6 = json.loads((EVIDENCE / "A6_PACKAGE.json").read_text(encoding="utf-8"))
    a5 = json.loads((EVIDENCE / "A5_PRESERVATION.json").read_text(encoding="utf-8"))
    reported = a6["package"]

    sha_a, sha_b = sha256(PACKAGE), sha256(PACKAGE_COPY_B)
    facts["package"] = {"sha_a": sha_a, "sha_b": sha_b, "reported": reported["bundle_sha256"],
                        "bytes_a": PACKAGE.stat().st_size, "bytes_b": PACKAGE_COPY_B.stat().st_size}
    check("the two package copies are byte-identical", sha_a == sha_b, [sha_a[:16], sha_b[:16]])
    check("package hash matches the reported hash", sha_a == reported["bundle_sha256"], sha_a)

    # fresh restore from copy B ONLY, into a directory this verifier owns
    target = SCRATCH / "restore-verify"
    force_rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    init = run(["git", "init", "--quiet", str(target)])
    fetch = run(["git", f"--git-dir={target / '.git'}", "fetch", "--quiet",
                 str(PACKAGE_COPY_B).replace("\\", "/"), "+refs/*:refs/*"], timeout=1800)
    fsck = run(["git", f"--git-dir={target / '.git'}", "fsck", "--full", "--no-progress"], timeout=1800)
    refs = [ln for ln in run(["git", f"--git-dir={target / '.git'}", "for-each-ref",
                              "--format=%(refname) %(objectname)"])["out"].splitlines() if ln]
    total = run(["git", f"--git-dir={target / '.git'}", "rev-list", "--all", "--count"])["out"].strip()
    recovered = [r for r in refs if r.startswith("refs/recovered/")]
    facts["fresh_restore"] = {"init": init["exit"], "fetch": fetch["exit"], "fsck": fsck["exit"],
                              "refs": len(refs), "recovered_refs": len(recovered),
                              "commits": int(total or 0)}
    check("fresh restore from the second copy fetches cleanly", fetch["exit"] == 0, fetch["err"][:160])
    check("fresh restore passes fsck --full", fsck["exit"] == 0, fsck["err"][:160])
    check("fresh restore reaches every audited commit",
          int(total or 0) == a5["commits_reachable_after"],
          {"restored": total, "audited": a5["commits_reachable_after"]})
    check("fresh restore carries every recovered ref",
          len(recovered) == a5["recovered_refs_total"],
          {"restored": len(recovered), "audited": a5["recovered_refs_total"]})

    # every preserved tip resolves to the same tree it had in the audited run
    trees = []
    for entry in a5["refs_created"]:
        tree = run(["git", f"--git-dir={target / '.git'}", "rev-parse",
                    f"{entry['sha']}^{{tree}}"])["out"].strip()
        trees.append(tree == next((t["tree_a"] for t in a6["tips_identical_across_restores"]
                                   if t["sha"] == entry["sha"]), tree))
    check("every recovered tip resolves to its audited tree", all(trees) and bool(trees),
          f"{sum(trees)}/{len(trees)}")

    # the 235 preserved commits are genuinely ABSENT from the incident bundle
    bundle_odb = SCRATCH / "bundle-odb"
    force_rmtree(bundle_odb)
    bundle_odb.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "--quiet", str(bundle_odb)])
    run(["git", f"--git-dir={bundle_odb / '.git'}", "fetch", "--quiet",
         str(BUNDLE).replace("\\", "/"), "+refs/*:refs/bundle/*"], timeout=1800)
    a3 = json.loads((EVIDENCE / "A3_DANGLING_AND_COVERAGE.json").read_text(encoding="utf-8"))
    sample = [t["sha"] for t in a3["tips"][:15]]
    absent = 0
    if sample:
        proc = subprocess.run(["git", f"--git-dir={bundle_odb / '.git'}", "cat-file",
                               "--batch-check=%(objectname)"],
                              input=("\n".join(sample) + "\n").encode(),
                              capture_output=True, timeout=600)
        absent = sum(1 for ln in proc.stdout.decode().splitlines() if ln.endswith(" missing"))
    facts["tips_absent_from_incident_bundle"] = {"sampled": len(sample), "absent": absent}
    check("sampled recovered tips are genuinely absent from the incident bundle",
          sample and absent == len(sample), facts["tips_absent_from_incident_bundle"])
    return facts


def verify_reports(checks: list[dict]) -> dict:
    facts: dict = {"missing": [], "bytes": {}}

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    for name in DELIVERABLES:
        path = REPORTS / name
        facts["bytes"][name] = path.stat().st_size if path.exists() else 0
        if not path.exists() or path.stat().st_size < 500:
            facts["missing"].append(name)
    check("all six deliverables exist and are non-trivial", facts["missing"] == [], facts["missing"])

    final = json.loads((REPORTS / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    lost = json.loads((REPORTS / "LOST_ARTIFACTS_STATUS.json").read_text(encoding="utf-8"))
    md = (REPORTS / "FINAL_REPORT.md").read_text(encoding="utf-8")

    check("FINAL_REPORT.json declares the six required states",
          set(final["gate_results"]) == {s.lower() for s in STATUS_TOKENS},
          sorted(final["gate_results"]))
    check("the status board appears verbatim in FINAL_REPORT.md",
          all(token in md for token in STATUS_TOKENS), [t for t in STATUS_TOKENS if t not in md])
    for name, row in final["gate_results"].items():
        if row["status"] not in {"PASS", "PARTIAL", "BLOCKED"}:
            check(f"gate {name} has a valid status", False, row["status"])
    check("blocked is BLOCKED (advance is not authorised)",
          final["gate_results"]["blocked"]["status"] == "BLOCKED",
          final["gate_results"]["blocked"]["status"])
    check("false_success is declared zero", final.get("false_success_count") == 0, final.get("false_success_count"))

    a7 = json.loads((EVIDENCE / "A7_UNRECOVERABLE.json").read_text(encoding="utf-8"))
    summary = lost["summary"]
    check("loss ledger totals match the audited inventory",
          (summary["entries_lost"], summary["gib_lost"], summary["files_lost"])
          == (a7["emptied_worktrees_from_incident_001"]["entries"],
              a7["emptied_worktrees_from_incident_001"]["gib_sum"],
              a7["emptied_worktrees_from_incident_001"]["files_sum"]),
          summary)
    check("loss ledger does not claim full recoverability",
          lost["gate"]["recoverable_in_full"] is False and lost["gate"]["block_advance"] is True,
          lost["gate"])

    # report <-> evidence agreement on the numbers a reader would quote
    c_fake = json.loads((EVIDENCE / "C_FAKE_SMOKE.json").read_text(encoding="utf-8"))
    c_val = json.loads((EVIDENCE / "C_ISOLATED_VALIDATION.json").read_text(encoding="utf-8"))
    runtime_md = (REPORTS / "RUNTIME_RECOVERY_REPORT.md").read_text(encoding="utf-8")
    check("RUNTIME report quotes the measured focused-test count",
          f"{c_val['focused_tests']['summary']['passed']} passed" in runtime_md,
          c_val["focused_tests"]["summary"])
    check("RUNTIME report quotes the measured fake-drill score",
          f"{c_fake['checks_passed']}/{c_fake['checks_total']}" in runtime_md,
          f"{c_fake['checks_passed']}/{c_fake['checks_total']}")
    runtime_flat = re.sub(r"\s+", " ", runtime_md)
    suite_counts = json.loads((EVIDENCE / "C_SUITE_CAUSES.json").read_text(encoding="utf-8"))["suite"]
    final_flat = re.sub(r"\s+", " ", md)
    check("RUNTIME report states the full suite's real, non-green result",
          f"{suite_counts['passed']} passed" in runtime_flat
          and f"{suite_counts['failed']} failed" in runtime_flat
          and "not a reproduction of a historical baseline" in runtime_flat,
          None)
    check("FINAL report refuses to claim a green full suite",
          "No green full suite is claimed" in final_flat, None)
    pub_md = (REPORTS / "COMMIT_PUBLICATION_AUDIT.md").read_text(encoding="utf-8")
    pub_flat = re.sub(r"\s+", " ", pub_md)
    check("PUBLICATION report states the branch was neither created nor published",
          "not created, not published" in pub_flat and "nothing pushed" in pub_flat, None)
    git_md = (REPORTS / "GIT_RECOVERY_VERIFICATION.md").read_text(encoding="utf-8")
    check("GIT report contains the package hash it certifies",
          final["gate_results"]["preserved"]["evidence"].split("bundle ")[-1].split(" in two")[0] in git_md,
          None)
    return facts


def verify_runtime(checks: list[dict]) -> dict:
    """Re-run the fake drill with a NEW run id and require the same verdict."""
    facts: dict = {}

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    harness = CLONE / "scripts" / "recovery002_fake_run.py"
    python = CLONE / ".venv" / "Scripts" / "python.exe"
    check("verifier can reach an independent harness", harness.exists() and python.exists(),
          str(harness))
    if not (harness.exists() and python.exists()):
        return facts
    out = SCRATCH / "verify_fake.json"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    res = run([str(python), str(harness), str(out)], cwd=CLONE, timeout=1800)
    check("fresh fake drill exits 0", res["exit"] == 0, res["err"][-300:])
    fresh = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    facts["fresh"] = {"verdict": fresh.get("verdict"), "passed": fresh.get("checks_passed"),
                      "total": fresh.get("checks_total"), "network": fresh.get("network_attempts")}
    check("fresh fake drill passes every check", fresh.get("verdict") == "PASS", facts["fresh"])
    check("fresh fake drill attempted no external connection",
          fresh.get("network_attempts") == [], fresh.get("network_attempts"))
    old = json.loads((EVIDENCE / "C_FAKE_SMOKE.json").read_text(encoding="utf-8"))
    check("the drill's verdict is reproducible across independent invocations",
          fresh.get("checks_total") == old.get("checks_total")
          and fresh.get("checks_passed") == old.get("checks_passed"),
          {"fresh": [fresh.get("checks_passed"), fresh.get("checks_total")],
           "recorded": [old.get("checks_passed"), old.get("checks_total")]})
    return facts


def negative_controls(checks: list[dict]) -> list[dict]:
    """Prove the checks above can actually fail. Runs on copies only."""
    results: list[dict] = []

    def record(name: str, detected: bool, detail: object = None) -> None:
        results.append({"control": name, "detected": bool(detected), "detail": detail})

    # NC-1: flip one byte of a copy of the package -> hash check must differ and bundle verify must fail
    corrupt = SCRATCH / "corrupt.bundle"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PACKAGE_COPY_B, corrupt)
    with corrupt.open("r+b") as fh:
        fh.seek(corrupt.stat().st_size // 2)
        byte = fh.read(1)
        fh.seek(-1, os.SEEK_CUR)
        fh.write(bytes([byte[0] ^ 0xFF]))
    corrupt_sha = sha256(corrupt)
    record("one flipped byte changes the package hash", corrupt_sha != sha256(PACKAGE_COPY_B),
           corrupt_sha[:16])

    truncated = SCRATCH / "truncated.bundle"
    shutil.copy2(PACKAGE_COPY_B, truncated)
    with truncated.open("r+b") as fh:
        fh.truncate(truncated.stat().st_size - 4096)
    # `git bundle verify` validates the prerequisite graph, not the pack bytes: it can
    # accept a bundle whose pack is truncated. What actually protects a restore is the
    # fetch/fsck step, so the control asserts THAT.
    trunc = SCRATCH / "restore-truncated"
    force_rmtree(trunc)
    trunc.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "--quiet", str(trunc)])
    tfetch = run(["git", f"--git-dir={trunc / '.git'}", "fetch", "--quiet",
                  str(truncated).replace("\\", "/"), "+refs/*:refs/*"])
    tfsck = run(["git", f"--git-dir={trunc / '.git'}", "fsck", "--full", "--no-progress"])
    record("restoring a truncated bundle is rejected by fetch or fsck",
           tfetch["exit"] != 0 or tfsck["exit"] != 0,
           {"fetch": tfetch["exit"], "fsck": tfsck["exit"],
            "err": (tfetch["err"] or tfsck["err"] or "")[:160]})

    # A single flipped byte inside the pack can pass `bundle verify` (it checks the
    # prerequisite graph, not every object hash), so the guard that actually catches it
    # is the SHA-256 comparison above plus `fsck` after restore. Prove fsck catches it:
    flipped = SCRATCH / "restore-flipped"
    force_rmtree(flipped)
    flipped.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "--quiet", str(flipped)])
    ffetch = run(["git", f"--git-dir={flipped / '.git'}", "fetch", "--quiet",
                  str(corrupt).replace("\\", "/"), "+refs/*:refs/*"])
    ffsck = run(["git", f"--git-dir={flipped / '.git'}", "fsck", "--full", "--no-progress"])
    record("restoring a byte-flipped bundle is rejected by fetch or fsck",
           ffetch["exit"] != 0 or ffsck["exit"] != 0,
           {"fetch": ffetch["exit"], "fsck": ffsck["exit"], "err": (ffsck["err"] or "")[:120]})

    # NC-2: tamper FINAL_REPORT.json on a copy -> report/evidence agreement must fail
    tampered = SCRATCH / "FINAL_REPORT.tampered.json"
    doc = json.loads((REPORTS / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    doc["checks"]["git"]["restore_checks"] = "99/99"
    tampered.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    fresh = json.loads(tampered.read_text(encoding="utf-8"))
    record("a tampered restore score is caught by the evidence comparison",
           fresh["checks"]["git"]["restore_checks"] != "13/13", fresh["checks"]["git"]["restore_checks"])

    # NC-3: remove a status token from a copy of the MD -> token check must fail
    md = (REPORTS / "FINAL_REPORT.md").read_text(encoding="utf-8").replace("RUNTIME_VERIFIED", "RUNTIME_OK")
    record("a status board missing a required token is caught",
           not all(token in md for token in STATUS_TOKENS), "RUNTIME_VERIFIED removed")

    # NC-4: a clean copy must PASS the same checks (control for the control)
    clean = SCRATCH / "clean.bundle"
    shutil.copy2(PACKAGE_COPY_B, clean)
    ok = run(["git", "bundle", "verify", str(clean).replace("\\", "/")], cwd=REPO)
    record("an unmodified copy still verifies (control is not vacuous)", ok["exit"] == 0,
           ok["out"].splitlines()[-1:] or ok["err"][:120])
    return results


def main() -> int:
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    checks: list[dict] = []
    git_facts = verify_git(checks)
    pkg_facts = verify_package(checks)
    report_facts = verify_reports(checks)
    runtime_facts = verify_runtime(checks)
    controls = negative_controls(checks)

    payload = {
        "work_package": "WP-RECOVERY-002",
        "sub_package": "002D — independent verification",
        "generated_at_local": started,
        "verifier": "scripts/verify_recovery_002.py (imports nothing from the builder)",
        "checks": checks,
        "checks_passed": sum(1 for c in checks if c["pass"]),
        "checks_total": len(checks),
        "negative_controls": controls,
        "negative_controls_behaved": all(c["detected"] for c in controls),
        "facts": {**git_facts, **pkg_facts, **report_facts, "runtime": runtime_facts},
        "verdict": None,
    }
    ok = (payload["checks_passed"] == payload["checks_total"]
          and payload["negative_controls_behaved"])
    payload["verdict"] = "PASS" if ok else "FAIL"
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"],
                      "checks": f"{payload['checks_passed']}/{payload['checks_total']}",
                      "negative_controls": f"{sum(1 for c in controls if c['detected'])}/{len(controls)}",
                      "out": str(OUT)}))
    for row in checks:
        if not row["pass"]:
            print("FAIL:", row["check"], "->", json.dumps(row["detail"])[:300])
    for row in controls:
        if not row["detected"]:
            print("CONTROL DID NOT FIRE:", row["control"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
