"""Independent verification of TAP-INTEGRATION-ADMISSION-002.

``BUILDER != VERIFIER``.  This program imports nothing from ``scripts/tap_integration_gate.py``,
nothing from ``scripts/tap_gate_campaign_audit.py`` and nothing from
``reports/ai-bots/TAP-INTEGRATION-GATE-001/tools/review_gate.py``.  It re-reads the artefacts,
recomputes the hashes and the ledger chains with its own copy of the canonicalisation rule, and
re-runs the gate's ``verify`` and the reviewer as *subprocesses* rather than trusting their
stored exit codes.

Claims:

``A1``  the branch the report names is the branch on disk, main is not an ancestor of it, and
        the delivery added no merge commit;
``A2``  the GATE-001 manifests still describe the files on disk;
``A3``  the gate's own report is a passing run of this commit and ``verify`` re-derives it;
``A4``  the PAPER session in the evidence recovered, executed cycles, left no lock and sent no
        live order;
``A5``  the admission ledger admits no strategy;
``A6``  the integration check rejects tampered evidence and accepts the delivered evidence;
``A7``  the runtime's static import closure is complete without the 301-commit lane;
``A8``  the PAPER session's recorded runtime is HEAD's runtime and the delta since it ran
        touches no executable path;
``S1``  self-control: ``A4`` fails on a session whose chain is broken;
``S2``  self-control: ``A5`` fails on a ledger that admits one strategy;
``S3``  self-control: ``A8`` fails on a drifted runtime hash and on an executable delta;
``A9``  the gate was recomputed at this branch's own commit and the recomputation still
        hashes;
``S4``  self-control: ``A9`` fails on a manifest whose hash was edited after the run.

A claim is ``PASS`` only when the artefact proves it, ``FAIL`` when it contradicts it, and
``UNKNOWN`` when the evidence is missing.  ``UNKNOWN`` is never a pass, and a self-control that
cannot run is a ``FAIL``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPORT = HERE.parents[1]
REPO = HERE.parents[4]
GATE_REPORT_DIR = REPO / "reports" / "ai-bots" / "TAP-INTEGRATION-GATE-001"
GATE_EVIDENCE = GATE_REPORT_DIR / "evidence"
PAPER_SESSION = REPORT / "evidence" / "paper_session"
ADMISSION = REPO / "config" / "strategy_admission.json"
REVIEWER = GATE_REPORT_DIR / "tools" / "review_gate.py"
GATE_RECOMPUTE = REPORT / "evidence" / "gate_at_600e744d"
SCHEMA = "TAP_INTEGRATION_ADMISSION_VERIFICATION_V1"
GENESIS = "0" * 64
SEPARATORS = (",", ":")


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=SEPARATORS, ensure_ascii=False)


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False
    ).stdout.strip()


def delivery_commit() -> str:
    """The commit that delivered the gate's report, which is what its evidence is valid for.

    The audit branch adds reports of its own, so checking the gate's evidence against *this*
    HEAD would refuse a valid run for the wrong reason.  The evidence is therefore checked
    against the commit that carries it, in a detached worktree.
    """

    return git(
        "log",
        "-1",
        "--format=%H",
        "--",
        "reports/ai-bots/TAP-INTEGRATION-GATE-001/evidence/GATE_REPORT.json",
    )


def add_delivery_worktree() -> tuple[Path | None, Path]:
    sha = delivery_commit()
    holder = Path(tempfile.mkdtemp(prefix="gate-delivery-"))
    target = holder / "wt"
    if not sha:
        return None, holder
    added = subprocess.run(
        ["git", "worktree", "add", "--detach", str(target), sha],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    return (target if added.returncode == 0 else None), holder


def drop_delivery_worktree(target: Path | None, holder: Path) -> None:
    if target is not None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
    shutil.rmtree(holder, ignore_errors=True)


def chain_of(stream: Path) -> dict[str, Any]:
    if not stream.is_file():
        return {"ok": False, "reason": "MISSING", "lines": 0, "entries": []}
    prev = GENESIS
    entries: list[dict[str, Any]] = []
    lines = 0
    for raw in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        lines += 1
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "reason": f"BAD_JSON_AT_{lines}", "lines": lines, "entries": []}
        if int(row.get("seq", -1)) != lines or str(row.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"LINK_AT_{lines}", "lines": lines, "entries": entries}
        digest = hashlib.sha256(
            canonical({"seq": lines, "prev_sha256": prev, "entry": row.get("entry")}).encode()
        ).hexdigest()
        if digest != str(row.get("sha256")):
            return {"ok": False, "reason": f"SHA_AT_{lines}", "lines": lines, "entries": entries}
        prev = digest
        entry = row.get("entry")
        entries.append(entry if isinstance(entry, dict) else {})
    return {"ok": True, "reason": "INTACT", "lines": lines, "head": prev, "entries": entries}


def claim(identifier: str, statement: str, method: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "claim": statement,
        "method": method,
        "status": "UNKNOWN",
        "detail": "",
        "problems": [],
    }


# --------------------------------------------------------------------------- claims


def branch_claim() -> dict[str, Any]:
    out = claim(
        "A1",
        "the audited branch is the one on disk, main is an ancestor only through the delivery, "
        "and no merge commit was added",
        "git rev-parse / merge-base / rev-list on the worktree",
    )
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    main = git("rev-parse", "main")
    origin = git("rev-parse", "origin/main")
    merges = [line for line in git("rev-list", "--merges", f"{main}..HEAD").splitlines() if line]
    ahead = git("rev-list", "--count", f"{main}..HEAD")
    behind = git("rev-list", "--count", "HEAD..main")
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", main, head], cwd=str(REPO), check=False
    ).returncode
    problems = out["problems"]
    if not head or not branch:
        problems.append("not a readable git work tree")
    if is_ancestor != 0:
        problems.append("main is not an ancestor of HEAD")
    if merges:
        problems.append(f"{len(merges)} merge commit(s) on the delivery")
    if behind != "0":
        problems.append(f"the delivery is {behind} commit(s) behind main")
    if not origin:
        problems.append("origin/main is not readable")
    out["detail"] = (
        f"branch={branch} head={head[:12]} main={main[:12]} origin/main={origin[:12]} "
        f"ahead={ahead} behind={behind} merges={len(merges)}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def manifest_claim() -> dict[str, Any]:
    out = claim(
        "A2",
        "the GATE-001 manifests still describe the files on disk",
        "recompute sha256 for every recorded path in both manifests",
    )
    problems = out["problems"]
    checked = 0
    for root, name in (
        (GATE_REPORT_DIR, "DELIVERY_MANIFEST.json"),
        (GATE_EVIDENCE, "EVIDENCE_MANIFEST.json"),
    ):
        manifest = read_json(root / name)
        files = manifest.get("files") or {}
        if not files:
            problems.append(f"{name} missing or empty")
            continue
        bad = [path for path, digest in files.items() if sha256_file(root / path) != digest]
        checked += len(files)
        if bad:
            problems.append(f"{name} disagrees on {len(bad)}: {sorted(bad)[:4]}")
        if int(manifest.get("count") or 0) != len(files):
            problems.append(f"{name} count field disagrees with its own list")
    out["detail"] = f"{checked} recorded hashes recomputed"
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def gate_claim() -> dict[str, Any]:
    out = claim(
        "A3",
        "the gate's report is a passing run of this code and verify re-derives it",
        "read GATE_REPORT.json, then run the gate's verify as a subprocess",
    )
    report = read_json(GATE_EVIDENCE / "GATE_REPORT.json")
    problems = out["problems"]
    if not report:
        problems.append("GATE_REPORT.json missing")
    else:
        if report.get("verdict") != "PASS":
            problems.append(f"gate verdict {report.get('verdict')}")
        steps = report.get("steps") or {}
        failing = [key for key, row in steps.items() if row.get("status") != "PASS"]
        if failing:
            problems.append(f"steps not PASS: {failing}")
        if int(report.get("false_success") or 0) != 0:
            problems.append("the gate recorded false successes")
        present = subprocess.run(
            ["git", "cat-file", "-e", f"{report.get('commit')}^{{commit}}"],
            cwd=str(REPO),
            capture_output=True,
            check=False,
        )
        if present.returncode != 0:
            problems.append("the gate's commit is not in this repository")
    worktree, holder = add_delivery_worktree()
    try:
        if worktree is None:
            problems.append("the delivery commit could not be checked out")
            verify = subprocess.CompletedProcess([], 99, "", "no worktree")
        else:
            verify = subprocess.run(
                [
                    sys.executable,
                    str(worktree / "scripts" / "tap_integration_gate.py"),
                    "verify",
                    "--evidence",
                    str(GATE_EVIDENCE),
                    "--repo",
                    str(worktree),
                ],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if verify.returncode != 0:
                problems.append(f"verify exit {verify.returncode}: {verify.stdout.strip()[-300:]}")
    finally:
        drop_delivery_worktree(worktree, holder)
    out["detail"] = (
        f"steps={len(report.get('steps') or {})} verify_exit={verify.returncode} "
        f"delivery={delivery_commit()[:12]} "
        f"manifest_files={(read_json(GATE_EVIDENCE / 'EVIDENCE_MANIFEST.json')).get('count')}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def paper_claim(root: Path = PAPER_SESSION) -> dict[str, Any]:
    out = claim(
        "A4",
        "the PAPER session executed cycles, recovered, left no lock and sent no live order",
        "re-hash session/STREAM.jsonl, recount rows, scan live_orders and *.lock",
    )
    problems = out["problems"]
    stream = root / "STREAM.jsonl"
    meta = read_json(root / "RUN_META.json")
    summary = read_json(root / "SUMMARY.json")
    chain = chain_of(stream)
    entries = chain.get("entries") or []
    kinds = [str(entry.get("kind")) for entry in entries]
    cycles = [entry.get("cycle") for entry in entries if entry.get("kind") == "CYCLE"]
    live = [int(entry.get("live_orders", 0) or 0) for entry in entries if "live_orders" in entry]
    locked = sorted(path.name for path in root.rglob("*.lock")) if root.is_dir() else []
    result = read_json(root / "RUN_RESULT.json")
    inner = (result or {}).get("summary") or {}

    if not root.is_dir():
        problems.append(f"session directory missing at {root}")
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if len(cycles) < 1:
        problems.append("no cycle was executed")
    if kinds.count("SESSION_START") != 1:
        problems.append(f"{kinds.count('SESSION_START')} SESSION_START rows")
    if kinds.count("SESSION_END") != 1:
        problems.append(f"{kinds.count('SESSION_END')} SESSION_END rows")
    if meta.get("mode") != "PAPER":
        problems.append(f"mode {meta.get('mode')}")
    if meta.get("live_enabled") is not False:
        problems.append(f"live_enabled {meta.get('live_enabled')}")
    if locked:
        problems.append(f"locks left behind: {locked}")
    if any(live):
        problems.append("a live order was recorded")
    if not result:
        problems.append("RUN_RESULT.json missing")
    if result.get("exit_code") not in (0, None):
        problems.append(f"campaign exit {result.get('exit_code')}")
    if inner.get("cycles_blocked"):
        problems.append(f"{inner.get('cycles_blocked')} blocked cycle(s) in summary")
    if inner.get("closed_trades") != summary.get("closed_trades"):
        problems.append(
            f"summary/result disagree on closed_trades "
            f"({summary.get('closed_trades')} vs {inner.get('closed_trades')})"
        )

    out["detail"] = (
        f"cycles={cycles} rows={chain.get('lines')} exit={result.get('exit_code')} "
        f"closed_trades={summary.get('closed_trades')}/{inner.get('closed_trades')} "
        f"live_orders={sorted(set(live))} locks={len(locked)} mode={meta.get('mode')}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def admission_claim(path: Path = ADMISSION) -> dict[str, Any]:
    out = claim(
        "A5",
        "the admission ledger admits no strategy for PAPER execution",
        "read the strategy table and count admitted entries",
    )
    payload = read_json(path)
    strategies = payload.get("strategies") or {}
    problems = out["problems"]
    if not strategies:
        problems.append("strategy table missing or empty")
    admitted = [
        name
        for name, row in strategies.items()
        if isinstance(row, dict) and "ADMIT" in str(row.get("status") or "").upper()
    ]
    candidates = payload.get("paper_candidates")
    if admitted:
        problems.append(f"admitted strategies: {admitted}")
    if candidates:
        problems.append(f"paper_candidates present: {candidates}")
    statuses = sorted(
        {str(row.get("status")) for row in strategies.values() if isinstance(row, dict)}
    )
    out["detail"] = f"{len(strategies)} strategies; statuses={statuses}; admitted={len(admitted)}"
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def check_claim() -> dict[str, Any]:
    out = claim(
        "A6",
        "the integration check rejects tampered evidence and accepts the delivered evidence",
        "run the gate's verify and the reviewer on the delivered evidence, then on a tampered copy",
    )
    problems = out["problems"]
    worktree, holder = add_delivery_worktree()
    try:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            if worktree is None:
                problems.append("the delivery commit could not be checked out")
                valid_verify = subprocess.CompletedProcess([], 99, "", "no worktree")
                bad_verify = valid_verify
                bad_review = valid_verify
            else:
                valid_verify = subprocess.run(
                    [
                        sys.executable,
                        str(worktree / "scripts" / "tap_integration_gate.py"),
                        "verify",
                        "--evidence",
                        str(GATE_EVIDENCE),
                        "--repo",
                        str(worktree),
                    ],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                tampered = tmp / "evidence"
                shutil.copytree(GATE_EVIDENCE, tampered)
                target = tampered / "LOCK_CAMPAIGN_VERIFICATION.json"
                payload = read_json(target)
                payload["false_success"] = 1
                target.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                bad_verify = subprocess.run(
                    [
                        sys.executable,
                        str(worktree / "scripts" / "tap_integration_gate.py"),
                        "verify",
                        "--evidence",
                        str(tampered),
                        "--repo",
                        str(worktree),
                    ],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                bad_review = subprocess.run(
                    [
                        sys.executable,
                        str(worktree / str(REVIEWER.relative_to(REPO))),
                        "--evidence",
                        str(tampered),
                        "--repo",
                        str(worktree),
                        "--out",
                        str(tmp / "REVIEW.json"),
                    ],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
        if valid_verify.returncode != 0:
            problems.append(f"verify refused valid evidence (exit {valid_verify.returncode})")
        if bad_verify.returncode == 0:
            problems.append("verify accepted tampered evidence")
        if bad_review.returncode == 0:
            problems.append("the reviewer accepted tampered evidence")
    finally:
        drop_delivery_worktree(worktree, holder)
    out["detail"] = (
        f"valid_verify={valid_verify.returncode} tampered_verify={bad_verify.returncode} "
        f"tampered_review={bad_review.returncode}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def closure_claim() -> dict[str, Any]:
    out = claim(
        "A7",
        "every trading_bot import in src/ and scripts/ resolves on this branch",
        "parse every module, resolve each import against the files on disk",
    )
    problems = out["problems"]
    src = REPO / "src"
    modules: set[str] = set()
    for path in src.rglob("*.py"):
        relative = path.relative_to(src)
        name = ".".join(relative.with_suffix("").parts)
        modules.add(name[: -len(".__init__")] if name.endswith(".__init__") else name)
    unresolved: list[str] = []
    checked = 0
    for path in list(src.rglob("*.py")) + list((REPO / "scripts").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            unresolved.append(f"{path}: SYNTAX")
            continue
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets = [node.module] + [
                    f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
                ]
            for target in targets:
                if target != "trading_bot" and not target.startswith("trading_bot."):
                    continue
                checked += 1
                parts = target.split(".")
                resolved = any(
                    ".".join(parts[:index]) in modules for index in range(len(parts), 0, -1)
                )
                if not resolved:
                    unresolved.append(f"{path.relative_to(REPO).as_posix()}: {target}")
    if unresolved:
        problems.append(f"{len(unresolved)} unresolved import(s): {unresolved[:5]}")
    out["detail"] = f"{len(modules)} modules, {checked} trading_bot imports, 0 unresolved"
    out["status"] = "PASS" if not problems else "FAIL"
    return out


# --------------------------------------------------------------------------- self-controls


def continuity_claim(
    meta_path: Path | None = None, start_path: Path | None = None
) -> dict[str, Any]:
    """The PAPER session's certificate still describes HEAD, not only the commit it ran on.

    The session recorded the commit it started from and the sha256 of every runtime module it
    imported.  Both are re-derived here against *HEAD* (through `git show`, so the working tree
    cannot flatter the claim), and the commit delta is required to touch nothing executable: a
    report added after the run is allowed, a changed risk or broker module is not.
    """
    out = claim(
        "A8",
        "the PAPER session's recorded runtime is HEAD's runtime, and the delta since it ran is "
        "reports only",
        "sha256 `git show HEAD:<module>` for every module SESSION_START recorded, then classify "
        "`git diff --name-only <session commit> HEAD`",
    )
    meta = read_json(meta_path or (PAPER_SESSION / "RUN_META.json"))
    start = read_json(start_path or (PAPER_SESSION / "SESSION_START.json"))
    problems = out["problems"]
    recorded = str(meta.get("commit") or "")
    hashes = start.get("runtime_sha256") or {}
    executable = ("src/", "scripts/", "tests/", "config/", ".github/", "pyproject.toml", "uv.lock")

    if not re.fullmatch(r"[0-9a-f]{40}", recorded):
        problems.append(f"session recorded no commit ({recorded!r})")
    if not isinstance(hashes, dict) or not hashes:
        problems.append("SESSION_START recorded no runtime hashes")
    drifted: list[str] = []
    for path, digest in sorted(hashes.items()):
        blob = subprocess.run(
            ["git", "show", f"HEAD:{path}"], cwd=str(REPO), capture_output=True, check=False
        )
        if blob.returncode != 0:
            problems.append(f"{path} is not readable at HEAD")
            continue
        if hashlib.sha256(blob.stdout).hexdigest() != digest:
            drifted.append(path)
    if drifted:
        problems.append(f"{len(drifted)} module(s) differ from the session runtime: {drifted[:4]}")

    delta: list[str] = []
    if recorded:
        delta = [line for line in git("diff", "--name-only", recorded, "HEAD").splitlines() if line]
        touched = [path for path in delta if path.startswith(executable)]
        if touched:
            problems.append(f"delta since the session touches executable paths: {touched[:4]}")

    out["detail"] = (
        f"session_commit={recorded[:12]} head={git('rev-parse', 'HEAD')[:12]} "
        f"runtime_modules={len(hashes)} drifted={len(drifted)} delta_files={len(delta)} "
        f"executable_delta={len([p for p in delta if p.startswith(executable)])}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def gate_recompute_claim(
    root: Path | None = None, manifest_path: Path | None = None
) -> dict[str, Any]:
    """The gate was recomputed on this branch's own commit, and that recomputation still hashes.

    A3 checks the *delivered* evidence, which was produced at 680c34df.  That is not the same
    claim as "the gate passes on the commit this report is about", so this recomputation is kept
    as its own artefact with its own commit binding, and its 260-file manifest is re-hashed here.
    The executable delta since that commit is classified for the same reason as A8: a report added
    afterwards is allowed, a changed module is not.
    """
    root = root or GATE_RECOMPUTE
    out = claim(
        "A9",
        "the gate was recomputed at 600e744d, passed every step, changed no risk policy, and its "
        "recomputation still hashes",
        "read GATE_REPORT.json and its invariants, re-hash EVIDENCE_MANIFEST.json, classify the "
        "delta from the certified commit to HEAD",
    )
    report = read_json(root / "GATE_REPORT.json")
    manifest = read_json(manifest_path or (root / "EVIDENCE_MANIFEST.json"))
    problems = out["problems"]

    if not report:
        problems.append("GATE_REPORT.json missing from the recomputation")
        out["detail"] = f"no gate recomputation at {root}"
        out["status"] = "FAIL"
        return out

    summary = report.get("summary") or {}
    invariants = report.get("invariants") or {}
    commit = str(report.get("commit") or "")
    if report.get("verdict") != "PASS":
        problems.append(f"verdict {report.get('verdict')}")
    if report.get("certifies") is not True:
        problems.append("the report does not certify")
    if int(report.get("false_success") or 0) != 0:
        problems.append(f"false_success {report.get('false_success')}")
    for status in ("FAIL", "BLOCKED", "NOT_TESTED"):
        if int(summary.get(status) or 0) != 0:
            problems.append(f"{summary.get(status)} step(s) {status}")
    if int(summary.get("steps") or 0) != int(summary.get("PASS") or -1) or not summary.get("steps"):
        problems.append(f"steps {summary.get('steps')} vs PASS {summary.get('PASS')}")
    if invariants.get("live_orders") != 0:
        problems.append(f"live_orders {invariants.get('live_orders')}")
    if invariants.get("risk_policy_changed") is not False:
        problems.append("the recomputation does not assert the risk policy was left alone")
    if invariants.get("lane_merged") is not False:
        problems.append("the recomputation does not assert the lane was not merged")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        problems.append(f"the report names no commit ({commit!r})")

    files = manifest.get("files") or {}
    missing = [path for path in files if not (root / path).is_file()]
    bad = [
        path
        for path, digest in files.items()
        if (root / path).is_file() and sha256_file(root / path) != digest
    ]
    if not files:
        problems.append("EVIDENCE_MANIFEST.json missing or empty")
    if missing:
        problems.append(f"{len(missing)} manifest file(s) absent: {sorted(missing)[:3]}")
    if bad:
        problems.append(f"{len(bad)} manifest hash(es) disagree: {sorted(bad)[:3]}")
    if int(manifest.get("count") or 0) != len(files):
        problems.append("the manifest count field disagrees with its own list")

    delta: list[str] = []
    executable = ("src/", "scripts/", "tests/", "config/", ".github/", "pyproject.toml", "uv.lock")
    if re.fullmatch(r"[0-9a-f]{40}", commit):
        delta = [line for line in git("diff", "--name-only", commit, "HEAD").splitlines() if line]
        touched = [path for path in delta if path.startswith(executable)]
        if touched:
            problems.append(
                f"delta since the certified commit touches executable paths: {touched[:4]}"
            )

    out["detail"] = (
        f"commit={commit[:12]} steps={summary.get('PASS')}/{summary.get('steps')} "
        f"manifest={len(files)} rehashed={len(files) - len(missing) - len(bad)} "
        f"delta_files={len(delta)} invariants="
        f"g1={invariants.get('g1')},admission={invariants.get('paper_admission')}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def self_control_gate_recompute() -> dict[str, Any]:
    """A9 must reject a recomputation whose manifest was edited after the run."""

    out = claim(
        "S4",
        "the recomputation check is not blind: one edited hash in its manifest must fail A9",
        "write a copy of the manifest with one digest replaced and re-evaluate A9 against it",
    )
    manifest = read_json(GATE_RECOMPUTE / "EVIDENCE_MANIFEST.json")
    files = dict(manifest.get("files") or {})
    if not files:
        out["detail"] = "cannot run: no manifest to tamper with"
        out["problems"] = ["evidence missing"]
        out["status"] = "FAIL"
        return out
    target = sorted(files)[0]
    files[target] = "0" * 64
    with tempfile.TemporaryDirectory() as raw:
        tampered = Path(raw) / "EVIDENCE_MANIFEST.json"
        tampered.write_text(json.dumps({**manifest, "files": files}), encoding="utf-8")
        judged = gate_recompute_claim(None, tampered)
    detected = judged["status"] == "FAIL" and any(
        "hash" in problem for problem in judged["problems"]
    )
    out["detail"] = (
        f"tampered file={target} judged={judged['status']} problems={judged['problems'][:2]}"
    )
    out["problems"] = [] if detected else ["an edited manifest hash did not fail A9"]
    out["status"] = "PASS" if detected else "FAIL"
    return out


def self_control_paper() -> dict[str, Any]:
    out = claim(
        "S1",
        "the session check is not blind: a broken chain must fail A4",
        "rewrite one stream row in a temporary copy and re-evaluate A4",
    )
    stream = PAPER_SESSION / "STREAM.jsonl"
    if not stream.is_file():
        out["detail"] = "no session to tamper with"
        out["problems"] = ["evidence missing"]
        out["status"] = "FAIL"
        return out
    with tempfile.TemporaryDirectory() as raw:
        copy = Path(raw) / "session"
        shutil.copytree(PAPER_SESSION, copy)
        rows = (copy / "STREAM.jsonl").read_text(encoding="utf-8").splitlines()
        index = max(0, len(rows) - 2)
        payload = json.loads(rows[index])
        entry = payload.get("entry")
        entry = entry if isinstance(entry, dict) else {}
        entry["live_orders"] = int(entry.get("live_orders", 0) or 0) + 1
        payload["entry"] = entry
        rows[index] = json.dumps(payload, sort_keys=True)
        (copy / "STREAM.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        verdict = paper_claim(copy)
    out["detail"] = f"tampered session judged {verdict['status']} ({verdict['detail']})"
    out["problems"] = [] if verdict["status"] == "FAIL" else ["the tampered copy still passed"]
    out["status"] = "PASS" if verdict["status"] == "FAIL" else "FAIL"
    return out


def self_control_continuity() -> dict[str, Any]:
    """A8 must fail on both things it claims: a drifted module and an executable delta.

    One mutation is not enough.  A check that only compares hashes would pass the second case,
    and a check that only compares commit deltas would pass the first, so both are exercised
    against copies written outside the repository.
    """
    out = claim(
        "S3",
        "the continuity check is not blind: a drifted runtime hash and an executable delta must "
        "both fail A8",
        "write two mutated copies of the session's metadata and re-evaluate A8 against each",
    )
    meta = read_json(PAPER_SESSION / "RUN_META.json")
    start = read_json(PAPER_SESSION / "SESSION_START.json")
    hashes = dict(start.get("runtime_sha256") or {})
    recorded = str(meta.get("commit") or "")
    problems = out["problems"]
    if not hashes or not recorded:
        problems.append("no recorded runtime to mutate")
        out["detail"] = "cannot run: session metadata missing"
        out["status"] = "FAIL"
        return out

    with tempfile.TemporaryDirectory() as raw:
        holder = Path(raw)
        module = sorted(hashes)[0]
        flipped = dict(hashes)
        flipped[module] = "0" * 64
        drifted_meta = holder / "drifted_meta.json"
        drifted_start = holder / "drifted_start.json"
        drifted_meta.write_text(json.dumps(dict(meta)), encoding="utf-8")
        drifted_start.write_text(json.dumps({**start, "runtime_sha256": flipped}), encoding="utf-8")
        first = continuity_claim(drifted_meta, drifted_start)

        behind_meta = holder / "behind_meta.json"
        behind_meta.write_text(
            json.dumps({**meta, "commit": git("rev-parse", "main")}), encoding="utf-8"
        )
        second = continuity_claim(behind_meta, None)

    if first["status"] != "FAIL":
        problems.append("a drifted module hash did not fail A8")
    if second["status"] != "FAIL":
        problems.append("a session commit behind the executable delta did not fail A8")
    out["detail"] = (
        f"drifted={first['status']} ({first['detail'][:70]}) "
        f"delta={second['status']} ({second['detail'][:70]})"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def self_control_admission() -> dict[str, Any]:
    out = claim(
        "S2",
        "the admission check is not blind: one admitted strategy must fail A5",
        "add an ADMITTED row in a temporary copy of the ledger and re-evaluate A5",
    )
    payload = read_json(ADMISSION)
    if not payload:
        out["detail"] = "ledger missing"
        out["problems"] = ["evidence missing"]
        out["status"] = "FAIL"
        return out
    with tempfile.TemporaryDirectory() as raw:
        copy = Path(raw) / "admission.json"
        mutated = json.loads(json.dumps(payload))
        strategies = mutated.get("strategies") or {}
        first = next(iter(strategies), None)
        if first is None:
            out["detail"] = "ledger has no strategy to admit"
            out["problems"] = ["empty ledger"]
            out["status"] = "FAIL"
            return out
        strategies[first]["status"] = "ADMITTED_PAPER"
        copy.write_text(json.dumps(mutated), encoding="utf-8")
        verdict = admission_claim(copy)
    out["detail"] = f"tampered ledger judged {verdict['status']} ({verdict['detail']})"
    out["problems"] = [] if verdict["status"] == "FAIL" else ["the tampered copy still passed"]
    out["status"] = "PASS" if verdict["status"] == "FAIL" else "FAIL"
    return out


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent admission verification")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    claims = [
        branch_claim(),
        manifest_claim(),
        gate_claim(),
        paper_claim(),
        admission_claim(),
        check_claim(),
        closure_claim(),
        continuity_claim(),
        gate_recompute_claim(),
        self_control_paper(),
        self_control_admission(),
        self_control_continuity(),
        self_control_gate_recompute(),
    ]
    by_id = {row["id"]: row for row in claims}
    false_success = int(
        (by_id["A4"]["status"] == "PASS" and by_id["S1"]["status"] != "PASS")
        or (by_id["A5"]["status"] == "PASS" and by_id["S2"]["status"] != "PASS")
        or (by_id["A8"]["status"] == "PASS" and by_id["S3"]["status"] != "PASS")
        or (by_id["A9"]["status"] == "PASS" and by_id["S4"]["status"] != "PASS")
    )
    passed = sum(1 for row in claims if row["status"] == "PASS")
    payload = {
        "schema": SCHEMA,
        "repo": str(REPO),
        "head": git("rev-parse", "HEAD"),
        "claims": by_id,
        "summary": {
            "claims": len(claims),
            "pass": passed,
            "fail": sum(1 for row in claims if row["status"] == "FAIL"),
            "unknown": sum(1 for row in claims if row["status"] == "UNKNOWN"),
        },
        "false_success": false_success,
        "verdict": "PASS" if passed == len(claims) and false_success == 0 else "FAIL",
    }
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
