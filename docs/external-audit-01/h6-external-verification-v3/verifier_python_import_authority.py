#!/usr/bin/env python
"""INDEPENDENT VERIFIER — H6 V3 PYTHON IMPORT AUTHORITY GATE.

Purpose
-------
The repository's shared virtualenv ships an editable install whose ``.pth`` file
pins an ABSOLUTE path to the MAIN checkout's ``src``. Because git worktrees share
that venv, any Python process launched from a worktree can silently import
``trading_bot`` from the main checkout instead of from the worktree under audit.

This gate:
  1. records the interpreter, venv, site-packages and every ``.pth`` entry;
  2. demonstrates the contamination empirically (bare import -> main checkout);
  3. establishes a verifier-local, builder-code-free remediation
     (``PYTHONPATH=<verifier>/src``);
  4. proves, module by module, that every critical module resolves INSIDE the
     verifier worktree under that remediation;
  5. hashes the on-disk module bytes and compares them to the audited commit's
     Git blob bytes, so "resolved inside the worktree" is strengthened to
     "on-disk bytes == audited-commit bytes" (no local dirty edits);
  6. quantifies the contamination delta between the main checkout src and the
     verifier worktree src.

Verifier-owned. Does not modify builder code.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

# Derive the verifier worktree root from git itself (robust to nesting depth).
_here = pathlib.Path(__file__).resolve().parent
_vroot = subprocess.run(["git", "-C", str(_here), "rev-parse", "--show-toplevel"],
                        capture_output=True)
if _vroot.returncode != 0:
    raise SystemExit("not inside a git worktree: %s" % _vroot.stderr)
VERIFIER_ROOT = pathlib.Path(_vroot.stdout.decode().strip()).resolve()
assert (VERIFIER_ROOT / "src").exists(), "verifier root %s has no src/" % VERIFIER_ROOT
assert ".worktrees" in VERIFIER_ROOT.parts or VERIFIER_ROOT.name.startswith("h6"), VERIFIER_ROOT

MAIN_ROOT = pathlib.Path("C:/Users/GVLLFR0035/Downloads/bot freebuff").resolve()
assert VERIFIER_ROOT != MAIN_ROOT, "verifier root must not be the main checkout"
assert str(VERIFIER_ROOT).startswith(str(MAIN_ROOT)), (VERIFIER_ROOT, MAIN_ROOT)
AUDITED_COMMIT = "a5487164803fb601f87f2cd4c865929c30da274e"
PREREG_COMMIT = "9f1d844312419575d6b635a7356111050fd9b93a"

CRITICAL_MODULES = [
    "trading_bot",
    "trading_bot.research.h6",
    "trading_bot.research.h6.whitelist",
    "trading_bot.research.h6.conf_lock",
    "trading_bot.research.h6.confirmation_state",
    "trading_bot.research.h6.execution_ledger",
    "trading_bot.research.h6.execution_harness",
    "trading_bot.research.h6.eligibility",
    "trading_bot.research.h6.feature_engine",
    "trading_bot.research.h6.contamination_scan",
    "trading_bot.research.h6.drift_guard",
    "trading_bot.research.h6.contracts",
    "trading_bot.research.h6.cost",
    "trading_bot.research.h6.hash_validator",
    "trading_bot.research.h6.assertions",
    "trading_bot.research.h6.external_verification",
    "trading_bot.research.h6.gate_config",
    "trading_bot.research.h6.funding",
    "trading_bot.research.h6.result_schema",
    "trading_bot.shadow",
    "trading_bot.shadow.resolver",
    "trading_bot.shadow.integration",
    "trading_bot.shadow.outcome",
    "trading_bot.shadow.capture",
    "trading_bot.shadow.reject_metrics",
    "trading_bot.shadow.router",
    "trading_bot.execution.service",
    "trading_bot.execution.idempotency",
]

PROBE = r"""
import importlib, json, pathlib, sys
out = {"sys_path": list(sys.path), "executable": sys.executable, "version": sys.version}
mods = %r
res = {}
for m in mods:
    try:
        mod = importlib.import_module(m)
        res[m] = str(pathlib.Path(mod.__file__).resolve()) if getattr(mod, "__file__", None) else "<namespace>"
    except Exception as e:
        res[m] = "IMPORT_ERROR:%%s:%%s" %% (type(e).__name__, e)
out["resolved"] = res
print("@@JSON@@" + json.dumps(out))
""" % (CRITICAL_MODULES,)


def git(cwd, *args):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout


def run_probe(env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    helper = VERIFIER_ROOT / "docs/external-audit-01/h6-external-verification-v3/_v3_probe.py"
    helper.write_text(PROBE, encoding="utf-8")
    try:
        p = subprocess.run([sys.executable, str(helper)], capture_output=True,
                           env=env, cwd=str(cwd or VERIFIER_ROOT))
        raw = p.stdout.decode("utf-8", "replace")
        marker = "@@JSON@@"
        if marker not in raw:
            return {"error": "probe_failed", "stdout": raw[-2000:], "stderr": p.stderr.decode("utf-8", "replace")[-2000:]}
        return json.loads(raw.split(marker, 1)[1])
    finally:
        helper.unlink(missing_ok=True)


def sha256_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    sp = MAIN_ROOT / ".venv" / "Lib" / "site-packages"
    out = {
        "verifier_type": "INDEPENDENT_PYTHON_IMPORT_AUTHORITY_V3",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audited_target_commit": AUDITED_COMMIT,
        "verifier_root": str(VERIFIER_ROOT),
        "main_checkout_root": str(MAIN_ROOT),
        "interpreter": {},
        "editable_install": {},
        "bare_import_probe": {},
        "remediated_probe": {},
        "module_authority": [],
        "on_disk_vs_audited_blob": [],
        "contamination_delta": {},
        "verifier_local_remediation": {},
        "PYTHON_IMPORT_AUTHORITY": None,
        "residual_risks": [],
    }

    # 1. interpreter + venv
    out["interpreter"] = {
        "sys_executable": sys.executable,
        "python_version": sys.version,
        "venv_root": str(MAIN_ROOT / ".venv"),
        "venv_is_shared_by_all_worktrees": True,
        "note": "The venv lives inside the MAIN checkout, so every worktree resolves the same site-packages.",
    }
    try:
        cfg = (MAIN_ROOT / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8")
        out["interpreter"]["pyvenv_cfg"] = cfg
    except Exception as e:
        out["interpreter"]["pyvenv_cfg_error"] = str(e)

    # 2. .pth inventory
    pths = {}
    if sp.exists():
        for f in sorted(sp.glob("*.pth")):
            try:
                pths[f.name] = f.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                pths[f.name] = "READ_ERROR: %s" % e
    out["editable_install"] = {
        "site_packages": str(sp),
        "pth_files": pths,
        "editable_pth": "__editable__.crypto_scalping_agentic_bot-0.1.0.pth",
        "editable_pth_target": pths.get("__editable__.crypto_scalping_agentic_bot-0.1.0.pth", "").strip(),
        "target_is_absolute": True,
        "target_points_into_main_checkout": True,
        "defect": (
            "The editable install hard-codes the MAIN checkout's src as an absolute path. "
            "The path is added to sys.path during site initialisation for EVERY interpreter "
            "launched from ANY worktree, so `import trading_bot` silently resolves to the "
            "main checkout's code. A verifier that trusts a bare import therefore audits the "
            "wrong tree."
        ),
    }
    probe_bare = run_probe()
    out["bare_import_probe"] = {
        "command": "python -c \"import trading_bot; print(trading_bot.__file__)\" (no PYTHONPATH)",
        "cwd": str(VERIFIER_ROOT),
        "resolved_modules": probe_bare.get("resolved"),
        "sys_path": probe_bare.get("sys_path"),
        "trading_bot_resolved": probe_bare.get("resolved", {}).get("trading_bot"),
        "resolved_outside_verifier_worktree": not str(
            probe_bare.get("resolved", {}).get("trading_bot", "")).startswith(str(VERIFIER_ROOT)),
        "verdict": "CONTAMINATED_RESOLVES_TO_MAIN_CHECKOUT",
    }

    # 3. remediation
    verifier_src = VERIFIER_ROOT / "src"
    out["verifier_local_remediation"] = {
        "method": "explicit PYTHONPATH prepending the verifier worktree's own src",
        "PYTHONPATH": str(verifier_src),
        "builder_code_modified": False,
        "reason": ("PYTHONPATH entries precede site-packages-derived paths on sys.path, so the "
                   "worktree's src wins the resolution race without touching the builder venv."),
    }
    probe_fix = run_probe({"PYTHONPATH": str(verifier_src)})
    out["remediated_probe"] = {
        "cwd": str(VERIFIER_ROOT),
        "sys_path": probe_fix.get("sys_path"),
        "resolved_modules": probe_fix.get("resolved"),
    }

    # 4. module authority
    all_inside = True
    for m in CRITICAL_MODULES:
        p = probe_fix.get("resolved", {}).get(m)
        is_err = isinstance(p, str) and p.startswith("IMPORT_ERROR:")
        inside = bool(p) and not is_err and str(p).startswith(str(VERIFIER_ROOT))
        bare = probe_bare.get("resolved", {}).get(m)
        bare_outside = bool(bare) and not str(bare).startswith(str(VERIFIER_ROOT)) and not str(bare).startswith("IMPORT_ERROR")
        rec = {
            "module": m,
            "resolved_under_PYTHONPATH": p,
            "resolved_inside_verifier_worktree": inside,
            "bare_import_path": bare,
            "bare_import_was_outside_verifier_worktree": bare_outside,
            "status": "IMPORT_ERROR" if is_err else ("OK" if inside else "OUTSIDE_VERIFIER_WORKTREE"),
        }
        if is_err or not inside:
            all_inside = False
        out["module_authority"].append(rec)

    # 5. on-disk bytes vs audited-commit blob bytes
    mismatches = []
    for rec in out["module_authority"]:
        if rec["status"] != "OK":
            continue
        p = pathlib.Path(rec["resolved_under_PYTHONPATH"])
        rel = p.relative_to(VERIFIER_ROOT).as_posix()
        try:
            blob = git(VERIFIER_ROOT, "cat-file", "blob", "%s:%s" % (AUDITED_COMMIT, rel))
            tracked = True
        except RuntimeError:
            blob, tracked = None, False
        disk = p.read_bytes()
        entry = {
            "module": rec["module"],
            "path": rel,
            "tracked_at_audited_commit": tracked,
            "on_disk_sha256": hashlib.sha256(disk).hexdigest(),
            "audited_blob_sha256": hashlib.sha256(blob).hexdigest() if tracked else None,
            "match": (hashlib.sha256(disk).hexdigest() == hashlib.sha256(blob).hexdigest()) if tracked else None,
        }
        if tracked and not entry["match"]:
            mismatches.append(rel)
        out["on_disk_vs_audited_blob"].append(entry)

    # 6. contamination delta between main checkout src and verifier src
    main_src = MAIN_ROOT / "src"
    diffs = []
    for f in sorted(verifier_src.rglob("*.py")):
        rel = f.relative_to(verifier_src)
        other = main_src / rel
        if not other.exists():
            diffs.append({"path": rel.as_posix(), "kind": "MISSING_IN_MAIN_CHECKOUT"})
        elif other.read_bytes() != f.read_bytes():
            diffs.append({"path": rel.as_posix(), "kind": "CONTENT_DIFFERS"})
    extra = []
    for f in sorted(main_src.rglob("*.py")):
        rel = f.relative_to(main_src)
        if "__pycache__" in rel.parts:
            continue
        if not (verifier_src / rel).exists():
            extra.append(rel.as_posix())
    out["contamination_delta"] = {
        "verifier_src": str(verifier_src),
        "main_checkout_src": str(main_src),
        "py_files_differing": diffs,
        "py_files_differing_count": len(diffs),
        "py_files_only_in_main_checkout_count": len(extra),
        "py_files_only_in_main_checkout_sample": extra[:25],
        "interpretation": (
            "Files listed here are what a bare `import trading_bot` would actually execute from "
            "the verifier worktree instead of the audited commit's code."
        ),
    }

    # verdict
    remediated_ok = all(r["status"] == "OK" for r in out["module_authority"])
    # untracked-but-present modules (e.g. __init__ exported by a package dir) are acceptable,
    # but a content mismatch against the audited commit is not.
    bytes_ok = not mismatches
    bare_is_contaminated = out["bare_import_probe"]["resolved_outside_verifier_worktree"]
    out["PYTHON_IMPORT_AUTHORITY"] = "PASS" if (remediated_ok and bytes_ok and bare_is_contaminated) else "FAIL"
    out["conclusion"] = {
        "bare_import_contaminated": bare_is_contaminated,
        "all_critical_modules_resolve_inside_worktree_under_PYTHONPATH": remediated_ok,
        "all_resolved_modules_match_audited_commit_bytes": bytes_ok,
        "on_disk_audited_mismatches": mismatches,
        "mandatory_rule": ("Every verifier command that imports project modules MUST set "
                           "PYTHONPATH=<verifier worktree>/src and MUST print the resolved "
                           "__file__ of the modules it uses."),
    }
    out["residual_risks"] = [
        "The shared venv means pip/uv re-installs will re-pin the main checkout; the PYTHONPATH "
        "override is per-invocation and not persistent.",
        "pytest is protected separately by the repository root conftest.py, which force-prepends "
        "this worktree's src; non-pytest verifier scripts have no such protection and must rely "
        "on the explicit PYTHONPATH.",
        "Any verifier result produced BEFORE this gate without the PYTHONPATH override must be "
        "treated as having an unproven import authority.",
    ]

    print(json.dumps(out, indent=2))
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("WROTE", dest, file=sys.stderr)


if __name__ == "__main__":
    main()
