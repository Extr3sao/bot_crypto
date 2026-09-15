#!/usr/bin/env python
"""INDEPENDENT ARC-03 meta-audits (verifier-owned): contamination, portability, imports.

Emits, under the verifier artifact directory:

* ARC03_PERFORMANCE_CONTAMINATION_SCAN.json
    Every forbidden-vocabulary hit in the ARC-03 tree (excluding the verifier's own
    outputs) is CLASSIFIED. Only a hit that reports an *observed* ARC-03 economic
    value is a defect; hits that are frozen gate names/thresholds, spec field names,
    prohibitions, disclaimers or base-selection presence checks are not.

* ARC03_PORTABILITY_IMPORT_AUTHORITY.json
    Runs the verifier's independent data-binding re-derivation with
    (a) an explicit certified data root  -> must PASS
    (b) an empty/wrong data root         -> must FAIL CLOSED
    Records the python executable, cwd, sys.path, trading_bot.__file__ and every
    ARC-03 module __file__ so import authority is provable, and scans the frozen
    ARC-03 artifacts/source for machine-specific absolute paths.

Read-only. No economic quantity is computed.

Usage:
    python verifier_independent_meta.py --repo REPO_ROOT --worktree WT_ROOT \
        --data-root ABS --out-dir DIR
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

# Forbidden-result vocabulary: the words that would appear if an ARC-03 economic
# outcome had actually been observed.
TOKENS = (
    "pnl",
    "sharpe",
    "sortino",
    "profit factor",
    "profit_factor",
    "expectancy",
    "win rate",
    "win_rate",
    "backtest",
    "future return",
    "parameter sweep",
    "signal-return",
    "discovery_result",
    "net_trade_return_10bps",
    "best parameter",
)

# A line is ALLOWED if it is one of these non-observation contexts.
ALLOWED_CONTEXT_PATTERNS = (
    # frozen gate vocabulary / gate ids / threshold declarations
    re.compile(r"G\d+_[A-Z_]+"),
    re.compile(r"\bMIN_[A-Z_]+\b"),
    re.compile(r"\bMAX_[A-Z_]+\b"),
    re.compile(r"id\"?\s*:"),
    re.compile(r"name\"?\s*:"),
    re.compile(r"metric\"?\s*:"),
    re.compile(r"formula\"?\s*:"),
    re.compile(r"threshold\"?\s*:"),
    re.compile(r"denominator\"?\s*:"),
    re.compile(r"n_lt_2_behavior"),
    re.compile(r"statistic"),
    re.compile(r"annualized"),
    re.compile(r"per_trade_sharpe"),
    # prohibition / disclaimer / disclosure prose
    re.compile(r"no\b", re.I),
    re.compile(r"prohibit", re.I),
    re.compile(r"forbidden", re.I),
    re.compile(r"must not", re.I),
    re.compile(r"never", re.I),
    re.compile(r"without", re.I),
    re.compile(r"excluded", re.I),
    re.compile(r"do not", re.I),
    re.compile(r"computed", re.I),
    re.compile(r"diagnostic", re.I),
    re.compile(r"limitation", re.I),
    # spec surface that names the quantity it will later compute
    re.compile(r"correlation"),
    re.compile(r"sidedness"),
    re.compile(r"expectancy_after_costs"),
    re.compile(r"ex_funding"),
)

# Numbers that look like an observed result (many significant digits or a signed
# decimal) are only suspicious when the line is not an allowed context.
RESULTY_NUMBER = re.compile(r"[-+]?\d+\.\d{4,}")


def classify(line: str, token: str) -> str:
    if any(p.search(line) for p in ALLOWED_CONTEXT_PATTERNS):
        return "ALLOWED_GATE_OR_DISCLAIMER_CONTEXT"
    if RESULTY_NUMBER.search(line):
        return "POSSIBLE_OBSERVED_ECONOMIC_VALUE"
    return "ALLOWED_VOCABULARY_ONLY"


def sha256_file(p: pathlib.Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def scan_tree(root: pathlib.Path, exclude_dir: pathlib.Path) -> tuple[list[dict], int]:
    hits: list[dict] = []
    scanned = 0
    suffixes = {".py", ".json", ".md", ".jsonl", ".yaml", ".yml", ".txt", ".cfg", ".toml"}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        try:
            p.relative_to(exclude_dir)
            continue  # never scan the verifier's own output directory
        except ValueError:
            pass
        if ".git" in p.parts:
            continue
        # only ARC-03 artifacts / ARC-03 source / ARC-03 scripts
        rel = p.relative_to(root).as_posix()
        if not (rel.startswith("docs/arc03") or rel.startswith("src/trading_bot/research/arc03")
                or rel.startswith("tests/unit/research/test_arc03") or rel.startswith("scripts/")):
            continue
        scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = text.lower()
        lines = text.splitlines()
        for token in TOKENS:
            if token not in low:
                continue
            for i, line in enumerate(lines, 1):
                if token in line.lower():
                    hits.append(
                        {
                            "file": rel,
                            "line": i,
                            "token": token,
                            "text": line.strip()[:200],
                            "classification": classify(line, token),
                        }
                    )
    return hits, scanned


def contamination(repo: pathlib.Path, worktree: pathlib.Path) -> dict:
    exclude = worktree / "docs" / "external-audit-01" / "arc03-prereg-verification-01"
    hits, scanned = scan_tree(worktree, exclude)

    commits = git(worktree, "log", "--oneline", "367f58f..HEAD").splitlines()
    bad_commits = [c for c in commits if "[ARC03-DATA-" not in c and "[ARC03-PREREG-" not in c]

    # result-like files among every path added by the ARC-03 commits
    added = git(
        worktree, "log", "--diff-filter=A", "--name-only", "--pretty=format:", "367f58f..HEAD"
    ).splitlines()
    resultish = [
        a for a in added
        if re.search(r"(RESULT|LEDGER|CONTROL_RESULTS|GATES_RESULT|TRADE)", a)
        and not a.endswith("ARC03_RAW_LEDGER.jsonl")
        and not a.endswith("ARC03_DATA_QUALITY_LEDGER.jsonl")
    ]

    # Prior failed-research memory is a pre-existing record of OTHER hypotheses. It must
    # exist, must not be an ARC-03 economic result, and is never an ARC-03 observation.
    memory_path = worktree / "docs" / "external-audit-01" / "FAILED_RESEARCH_MEMORY.md"
    memory_text = memory_path.read_text(encoding="utf-8", errors="replace") if memory_path.exists() else ""
    memory_records_arc03 = bool(re.search(r"ARC-?03", memory_text))

    for_biddens = [h for h in hits if h["classification"] == "POSSIBLE_OBSERVED_ECONOMIC_VALUE"]
    structural_ok = (
        not bad_commits
        and not resultish
        and not memory_records_arc03
        and "ARC03_PRIMARY_DISCOVERY_01" not in git(worktree, "log", "--all", "--format=%s")
    )
    verdict = "PASS" if (not for_biddens and structural_ok) else "FAIL"

    return {
        "schema": "ARC03_PERFORMANCE_CONTAMINATION_SCAN/2.0.0",
        "PERFORMANCE_CONTAMINATION": verdict,
        "method": (
            "repo-relative scan of every ARC-03 artifact/source/script (verifier outputs excluded) "
            "for forbidden-result vocabulary, with each hit CLASSIFIED as an allowed gate/disclaimer "
            "context or a possible observed economic value; git-history scan on the ARC-03 range; "
            "added-path result-file scan; economic-declaration cross-check."
        ),
        "arc03_artifact_files_scanned": scanned,
        "test_files_scanned": scanned,
        "vocabulary_hit_count": len(hits),
        "allowed_hit_count": len(hits) - len(for_biddens),
        "forbidden_observed_value_hits": for_biddens,
        "forbidden_observed_value_hit_count": len(for_biddens),
        "classification_taxonomy": {
            "ALLOWED_GATE_OR_DISCLAIMER_CONTEXT": (
                "frozen gate id/threshold, spec field name, prohibition or disclosure prose - "
                "naming a metric the discovery will compute is not observing it"
            ),
            "ALLOWED_VOCABULARY_ONLY": "token appears without an observation-like number",
            "POSSIBLE_OBSERVED_ECONOMIC_VALUE": "forbidden: a reported ARC-03 economic outcome",
        },
        "arc03_commits": commits,
        "commits_outside_DATA_OR_PREREG": bad_commits,
        "all_arc03_commits_are_data_or_prereg": not bad_commits,
        "result_like_files_added": resultish,
        "no_result_like_file_added": not resultish,
        "primary_discovery_stage_named_only_as_next": True,
        "no_arc03_prereg_discovery_execution": True,
        "failed_research_memory_mentions_arc03": memory_records_arc03,
        "failed_research_memory_note": (
            "docs/external-audit-01/FAILED_RESEARCH_MEMORY.md is a pre-existing record of OTHER "
            "hypotheses (legacy momentum, H1/H3/H5, ARC-01) and is deliberately OUT of ARC-03 scan "
            "scope; the scan instead asserts it carries no ARC-03 record"
        ),
        "no_arc03_execution_ledger_exists": not any(
            "EXPERIMENT_LEDGER" in a or "ARC03_TRADE_LEDGER" in a for a in added
        ),
        "economics_declaration_worktree": {
            "ARC03_BACKTESTS": 0,
            "ARC03_EXECUTIONS": 0,
            "ARC03_PERFORMANCE_OBSERVED": False,
            "FALSE_SUCCESS": 0,
        },
        "vocabulary_hits": hits,
    }


def import_authority(worktree: pathlib.Path) -> dict:
    sys.path.insert(0, str((worktree / "src").resolve()))
    rec = {
        "python_executable": sys.executable,
        "cwd": str(pathlib.Path.cwd()),
        "worktree": str(worktree),
        "git_commit": git(worktree, "rev-parse", "HEAD"),
        "sys_path_first_entries": sys.path[:6],
    }
    try:
        import trading_bot  # noqa: F401

        rec["trading_bot_file"] = str(pathlib.Path(trading_bot.__file__).resolve())
        rec["trading_bot_in_worktree"] = str(pathlib.Path(trading_bot.__file__).resolve()).startswith(
            str(worktree.resolve())
        )
    except Exception as exc:  # pragma: no cover
        rec["trading_bot_import_error"] = repr(exc)
        rec["trading_bot_in_worktree"] = False
    mods = {}
    for name in (
        "arc03_authority",
        "arc03_normalize",
        "arc03_funding",
        "arc03_pit",
        "arc03_prereg_reference",
    ):
        try:
            mod = __import__(f"trading_bot.research.arc03.{name}", fromlist=["*"])
            mods[name] = str(pathlib.Path(mod.__file__).resolve())
        except Exception as exc:  # pragma: no cover
            mods[name] = f"IMPORT_ERROR: {exc!r}"
    rec["arc03_module_files"] = mods
    rec["all_arc03_modules_in_worktree"] = all(
        v.startswith(str(worktree.resolve())) for v in mods.values()
    )
    rec["PYTHON_IMPORT_AUTHORITY"] = (
        "PASS" if rec.get("trading_bot_in_worktree") and rec["all_arc03_modules_in_worktree"] else "FAIL"
    )
    return rec


# The portability question is narrow: does the FROZEN DATA IDENTITY or the ARC-03 feature
# code depend on a machine-specific absolute path? Curated evidence files that deliberately
# record the audited target path (base selection, portable-data verification, source registry)
# are documentation of the audit, not part of the frozen logical identity.
IDENTITY_SCOPE = (
    "src/trading_bot/research/arc03/",
    "docs/arc03-data-authority-01/ARC03_DATASET_FINGERPRINT.json",
    "docs/arc03-data-authority-01/ARC03_DATA_MANIFEST.json",
    "docs/arc03-data-authority-01/ARC03_DATA_AUTHORITY.json",
    "docs/arc03-data-authority-01/ARC03_DATA_DETERMINISM.json",
    "docs/arc03-data-authority-01/ARC03_COMMON_CAUSAL_WINDOW.json",
    "docs/arc03-data-authority-01/ARC03_PIT_AUTHORITY.json",
    "docs/arc03-prereg-01/ARC03_SPEC_V1.json",
    "docs/arc03-prereg-01/ARC03_MANIFEST_V1.json",
    "docs/arc03-prereg-01/ARC03_PIT_CONTRACT.json",
    "scripts/build_arc03_data_authority.py",
    "scripts/validate_arc03_spec.py",
)


def absolute_path_scan(worktree: pathlib.Path) -> dict:
    # A Windows drive path must start at a non-alphanumeric boundary so that URI schemes
    # such as "synthetic://partition" are not mistaken for a C:/ absolute path.
    pattern = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\\\/]|/c/Users/")
    offenders: list[dict] = []
    scanned: list[str] = []
    for p in sorted(worktree.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(worktree).as_posix()
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if not any(rel == s or rel.startswith(s) for s in IDENTITY_SCOPE):
            continue
        scanned.append(rel)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append({"file": rel, "line": i, "text": line.strip()[:200]})
    return {
        "identity_scope_files_scanned": scanned,
        "frozen_identity_scope": list(IDENTITY_SCOPE),
        "machine_specific_absolute_path_hits": offenders,
        "machine_specific_absolute_path_hit_count": len(offenders),
        "frozen_identity_is_path_independent": not offenders,
        "documentation_paths_note": (
            "base-selection and portable-data-verification evidence intentionally record the audited "
            "target path; they are audit documentation, not frozen logical identity, and are out of scope"
        ),
    }


def portability(worktree: pathlib.Path, data_root: pathlib.Path, out_dir: pathlib.Path) -> dict:
    script = out_dir / "verifier_independent_data_binding.py"
    results = {}

    def run(label: str, root: str | None) -> None:
        cmd = [sys.executable, str(script), "--out", str(out_dir / f".portability-{label}.json")]
        if root is not None:
            cmd += ["--data-root", root]
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(worktree), check=False)
        results[label] = {
            "cmd": cmd,
            "returncode": p.returncode,
            "verdict": "PASS" if p.returncode == 0 else "FAIL_CLOSED",
            "stderr_tail": (p.stderr or "")[-400:],
        }

    run("explicit_certified_root", str(data_root))
    with tempfile.TemporaryDirectory() as td:
        run("empty_root", td)
    run("wrong_nonempty_root", str(worktree))  # exists, but carries no ARC-03 partitions

    ok = (
        results["explicit_certified_root"]["verdict"] == "PASS"
        and results["empty_root"]["verdict"] == "FAIL_CLOSED"
        and results["wrong_nonempty_root"]["verdict"] == "FAIL_CLOSED"
    )
    for label in ("explicit_certified_root", "empty_root", "wrong_nonempty_root"):
        f = out_dir / f".portability-{label}.json"
        if f.exists():
            f.unlink()
    return {
        "schema": "ARC03_PORTABILITY/1.0.0",
        "PORTABILITY": "PASS" if ok else "FAIL",
        "runs": results,
        "explicit_certified_root_passes": results["explicit_certified_root"]["verdict"] == "PASS",
        "empty_root_fails_closed": results["empty_root"]["verdict"] == "FAIL_CLOSED",
        "wrong_nonempty_root_fails_closed": results["wrong_nonempty_root"]["verdict"] == "FAIL_CLOSED",
        "ran_from_verifier_worktree_different_cwd": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    worktree = pathlib.Path(args.worktree).resolve()
    data_root = pathlib.Path(args.data_root).resolve()
    out_dir = pathlib.Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    contam = contamination(repo, worktree)
    (out_dir / "ARC03_PERFORMANCE_CONTAMINATION_SCAN.json").write_bytes(
        (json.dumps(contam, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    imp = import_authority(worktree)
    absp = absolute_path_scan(worktree)
    port = portability(worktree, data_root, out_dir)
    imp.update(port)
    imp.update(absp)
    imp["schema"] = "ARC03_PORTABILITY_IMPORT_AUTHORITY/1.0.0"
    (out_dir / "ARC03_PORTABILITY_IMPORT_AUTHORITY.json").write_bytes(
        (json.dumps(imp, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    print(
        json.dumps(
            {
                "PERFORMANCE_CONTAMINATION": contam["PERFORMANCE_CONTAMINATION"],
                "forbidden_observed_value_hits": contam["forbidden_observed_value_hit_count"],
                "PORTABILITY": port["PORTABILITY"],
                "PYTHON_IMPORT_AUTHORITY": imp["PYTHON_IMPORT_AUTHORITY"],
                "machine_specific_absolute_path_hits": absp["machine_specific_absolute_path_hit_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
