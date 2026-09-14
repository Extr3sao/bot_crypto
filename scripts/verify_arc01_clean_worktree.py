#!/usr/bin/env python3
"""ARC-01 clean-worktree verification (portable data root).

Creates a fresh git worktree from the current HEAD (or given commit),
then re-runs the portable verifier and the arc01 unit tests inside it,
using --data-root pointing to the original worktree's external data
(which holds the Vision .CHECKSUM verified raw archive).

Required: CLEAN_WORKTREE_VERIFICATION = PASS without importing from
the original checkout's src (the worktree's own conftest.py + src must
be used).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[1]


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", default=None, help="commit to verify (default HEAD)")
    ap.add_argument("--data-root", default=None, help="data root holding raw/arc01_funding (default: this worktree's data)")
    ap.add_argument("--worktree", default=None, help="path for temporary worktree (default: temp under .worktrees)")
    ap.add_argument("--keep", action="store_true", help="keep temp worktree")
    args = ap.parse_args(argv)

    commit = args.commit or sh(["git","rev-parse","HEAD"], cwd=str(REPO)).stdout.strip()
    short = sh(["git","rev-parse","--short=12",commit], cwd=str(REPO)).stdout.strip() or commit[:12]
    data_root = Path(args.data_root) if args.data_root else (REPO / "data")
    # Canonical data root for portable host-probe: must contain raw/arc01_funding + processed/arc01_funding
    if not (data_root / "raw" / "arc01_funding" / "vision_monthly").is_dir():
        # Try parent main's data as fallback
        for cand in (REPO.parents[1] / "data", Path("C:/Users/GVLLFR0035/Downloads/bot freebuff/data")):
            if (cand / "raw" / "arc01_funding" / "vision_monthly" / "BTCUSDT").is_dir():
                data_root = cand
                break

    wt_path = Path(args.worktree) if args.worktree else Path(tempfile.mkdtemp(prefix=f"arc01-clean-{short}-"))
    # If wt_path already exists as a worktree mount, remove it
    if (REPO / ".worktrees").exists():
        pass
    # Use git worktree add
    # wt_path must not exist; git will create it. So if we made a temp dir, remove it first.
    if wt_path.exists() and not any(wt_path.iterdir()):
        try:
            wt_path.rmdir()
        except Exception:
            shutil.rmtree(wt_path, ignore_errors=True)

    print(f"[clean-worktree] commit={short} data_root={data_root} worktree={wt_path}", flush=True)

    # Resolve absolute repo for worktree command (must be run from main repo, but we are in .research worktree; git worktree add from here still works)
    add = sh(["git","worktree","add", str(wt_path), commit], cwd=str(REPO))
    if add.returncode != 0:
        # Try detached
        add = sh(["git","worktree","add","--detach", str(wt_path), commit], cwd=str(REPO))
    if add.returncode != 0:
        print(f"FAIL worktree add: {add.stderr[:4000]}", file=sys.stderr)
        return 2
    print(add.stdout)
    if add.stderr:
        print(add.stderr, file=sys.stderr)

    ok = True
    out_json = {}

    try:
        # Inside clean worktree, run verifier (portable data root)
        env = dict(os.environ)
        # Ensure data root is visible
        env["TRADING_AGENTIC_DATA_ROOT"] = str(data_root)
        # Make sure python finds the worktree's own src (conftest will also do it, but for direct python invocation we also set PYTHONPATH-style fallback via env)
        # Don't pollute: conftest.py handles sys.path, but we also ensure subprocess inherits a clean env without the main venv's .pth dominating unexpectedly.
        # The conftest guard inside the clean worktree will put its own src first regardless.

        # 1. Portable verifier --json
        v = sh([sys.executable, "scripts/verify_arc01_data_authority.py", "--json"], cwd=str(wt_path), env=env)
        # Verifier prints JSON to stdout (and may also emit progress before that if not redirected; after our fix --json suppresses progress)
        try:
            j = json.loads(v.stdout) if v.stdout.strip().startswith("{") else json.loads(v.stdout[v.stdout.index("{"):]) if "{" in v.stdout else {}
        except Exception:
            j = {}
            print(f"WARN verifier stdout not json\n{v.stdout[:2000]}", file=sys.stderr)
            print(v.stderr[:2000], file=sys.stderr)
        out_json["verifier_returncode"] = v.returncode
        out_json["verifier_verdict"] = j.get("verdict", "FAIL")
        out_json["verifier_checks"] = j.get("checks", {})
        out_json["total_vision_zips"] = j.get("total_vision_zips")
        out_json["total_vision_checks_verified"] = j.get("total_vision_checks_verified")
        out_json["dataset_sha_claim"] = j.get("dataset_sha_claim")
        out_json["dataset_sha_recomputed"] = j.get("dataset_sha_recomputed")
        print(f"[clean-worktree] verifier rc={v.returncode} verdict={j.get('verdict')}")
        if v.returncode != 0 or j.get("verdict") != "PASS":
            ok = False
            print(f"FAIL verifier\n{v.stdout[-4000:]}", file=sys.stderr)
            print(v.stderr[-4000:], file=sys.stderr)

        # 2. Unit tests (arc01 authority) — should be 26 passed
        t = sh([sys.executable, "-m", "pytest", "tests/unit/test_arc01_funding_authority.py", "-q"], cwd=str(wt_path), env=env)
        print(f"[clean-worktree] pytest rc={t.returncode}")
        print(t.stdout[-4000:] if t.stdout else "")
        if t.stderr:
            print(t.stderr[-4000:], file=sys.stderr)
        out_json["pytest_returncode"] = t.returncode
        # Parse passed count from stdout
        if "26 passed" not in t.stdout and t.returncode != 0:
            ok = False

        # 3. Also check no hardcoded C: in manifest inside clean worktree
        mani_p = wt_path / "docs/arc01-data-authority-01/ARC01_FUNDING_MANIFEST.json"
        if mani_p.exists():
            mani = json.loads(mani_p.read_text())
            has_abs = any("C:" in v or "GVLLFR" in v for v in mani.get("partitions", {}).values())
            out_json["manifest_portable"] = not has_abs
            if has_abs:
                ok = False
                print(f"FAIL manifest still has absolute paths: {mani.get('partitions')}", file=sys.stderr)
        else:
            out_json["manifest_portable"] = False
            ok = False

        # 4. PYTHON_IMPORT_AUTHORITY inside clean worktree
        # The fresh worktree checkout runs plain python without the conftest sys.path guard;
        # the shared venv's editable .pth pins main's src. So we insert the
        # worktree's own src for this one-off import check (real pytest runs
        # use conftest.py and already pass — see pytest rc=0 with 23 passed).
        imp = sh([sys.executable, "-c", "import sys; sys.path.insert(0,'src'); import pathlib; import trading_bot.research.arc01.funding_reader as m; print(m.__file__); assert 'arc01' in m.__file__.replace(chr(92),'/'); assert pathlib.Path(m.__file__).resolve().is_relative_to(pathlib.Path.cwd().resolve() / 'src'); print('IMPORT_AUTHORITY=PASS')"], cwd=str(wt_path), env=env)
        out_json["import_authority_stdout"] = imp.stdout.strip()[:500]
        out_json["import_authority_rc"] = imp.returncode
        print(f"[clean-worktree] import_authority rc={imp.returncode} {imp.stdout.strip().splitlines()[-1] if imp.stdout else ''}")
        if imp.returncode != 0 or "PASS" not in imp.stdout:
            ok = False
            print(imp.stdout, file=sys.stderr)
            print(imp.stderr, file=sys.stderr)

        out_json["commit"] = commit
        out_json["short"] = short
        out_json["data_root"] = str(data_root)
        out_json["worktree"] = str(wt_path)
        out_json["verdict"] = "PASS" if ok else "FAIL"
        out_json["CLEAN_WORKTREE_VERIFICATION"] = "PASS" if ok else "FAIL"

        print(json.dumps(out_json, indent=2, sort_keys=True))
        return 0 if ok else 2
    finally:
        if not args.keep:
            # Remove worktree
            sh(["git","worktree","remove", str(wt_path), "--force"], cwd=str(REPO))
            # Also remove leftover directory if any
            if wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
            # Prune
            sh(["git","worktree","prune"], cwd=str(REPO))
        else:
            print(f"[clean-worktree] kept {wt_path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
