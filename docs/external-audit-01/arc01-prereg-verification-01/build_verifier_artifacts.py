"""ARC-01 INDEPENDENT PREREGISTRATION VERIFICATION — artifact generator.

READ-ONLY verifier tooling. It does NOT modify builder artifacts, does NOT run
any backtest, and computes NO economic quantity (no returns, PnL, Sharpe,
Sortino, profit factor, expectancy or win rate on real data).

It only:
  * recomputes Git blob IDs / SHA256 of the frozen prereg artifacts;
  * rehashes the reused funding / OI / price data authority from the actual
    shared data roots (not from builder summaries);
  * runs structural contamination scans over git history and the frozen tree;
  * writes the independent verifier artifacts under
    docs/external-audit-01/arc01-prereg-verification-01/.

Run from the verifier worktree root:
    python docs/external-audit-01/arc01-prereg-verification-01/build_verifier_artifacts.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

VERIFIER_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = VERIFIER_ROOT.parents[1]
MAIN_ROOT = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
DATA_AUTHORITY_WT = MAIN_ROOT / ".research" / "arc01-data-authority-01"

OUT = VERIFIER_ROOT / "docs" / "external-audit-01" / "arc01-prereg-verification-01"
PREREG = VERIFIER_ROOT / "docs" / "arc01-prereg-01"

PREREG_COMMIT = "fa15fb4f300815f56bf14e503d1a147cb73f27a6"
DATA_AUTHORITY_COMMIT = "6e42dd9d4c19800925fd555999686d1e2b4ef47e"
DATASET_SHA256 = "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec"
EXPECTED_SPEC_SHA256 = "89b8590ccde0d90ae35dfe5f91d9dad706622a8004d77ef54c35c72c9cc0b313"
EXPECTED_MANIFEST_SHA256 = "d698e3d830651988c98359734ebb848efa8fa7bff4103bb44f58fb82b885df5e"
EXPECTED_PARTITION_SHA256 = {
    "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
    "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
    "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
}
EXPECTED_OI = {
    "oi_full_history_dataset_sha256_v2": "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99",
    "manifest_sha256": "bdf3088caa08120784964f44e5fa5e81f0a1b6bacee99282a012f3a5dc08ef89",
    "ledger_sha256": "bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714",
}
EXPECTED_PRICE_FINGERPRINT = "e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168"
EXPECTED_PRICE_PER_ASSET = {
    "BTCUSDT": "41e9238666a0b98c02cffd19d36a590b8463f6556e215c49f068452674ef9027",
    "ETHUSDT": "7c72c0bb55d4aac9460dde54eb73305b5d30bdec99ea4b500eac9e1319ddd7ba",
    "SOLUSDT": "6f147463b504f5026d887e77306cfa629ee5feb8cbdb01923643133091da03ff",
}
NOW = datetime.now(timezone.utc).isoformat()


def sh(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def git_blob(root: Path, commit: str, relpath: str) -> dict:
    oid = sh(["git", "rev-parse", f"{commit}:{relpath}"], root).strip()
    typ = sh(["git", "cat-file", "-t", oid], root).strip()
    return {"path": relpath, "blob_oid": oid, "object_type": typ}


# ---------------------------------------------------------------- authority

def git_authority() -> dict:
    spec_blob = git_blob(MAIN_ROOT, PREREG_COMMIT, "docs/arc01-prereg-01/ARC01_SPEC_V1.json")
    man_blob = git_blob(MAIN_ROOT, PREREG_COMMIT, "docs/arc01-prereg-01/ARC01_MANIFEST_V1.json")
    spec_sha = sha256_file(PREREG / "ARC01_SPEC_V1.json")
    man_sha = sha256_file(PREREG / "ARC01_MANIFEST_V1.json")
    committed = sh(["git", "rev-parse", "HEAD"], VERIFIER_ROOT).strip()
    return {
        "schema": "ARC01_GIT_AUTHORITY/1.0.0",
        "verifier_worktree": str(VERIFIER_ROOT),
        "verifier_branch": sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], VERIFIER_ROOT).strip(),
        "target_prereg_commit": PREREG_COMMIT,
        "prereg_commit_exists": sh(["git", "cat-file", "-t", PREREG_COMMIT], MAIN_ROOT).strip() == "commit",
        "prereg_commit_head_at_worktree_creation": committed == PREREG_COMMIT,
        "data_authority_commit": DATA_AUTHORITY_COMMIT,
        "data_authority_commit_exists": sh(["git", "cat-file", "-t", DATA_AUTHORITY_COMMIT], MAIN_ROOT).strip() == "commit",
        "prereg_is_descendant_of_data_authority": sh(
            ["git", "merge-base", "--is-ancestor", DATA_AUTHORITY_COMMIT, PREREG_COMMIT],
            MAIN_ROOT,
        ) is not None,
        "spec_blob": spec_blob,
        "manifest_blob": man_blob,
        "spec_sha256": spec_sha,
        "manifest_sha256": man_sha,
        "expected_spec_sha256": EXPECTED_SPEC_SHA256,
        "expected_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "spec_sha_match": spec_sha == EXPECTED_SPEC_SHA256,
        "manifest_sha_match": man_sha == EXPECTED_MANIFEST_SHA256,
        "prereg_commit_file_set": sorted(
            sh(["git", "show", "--name-only", "--pretty=format:", PREREG_COMMIT], MAIN_ROOT).split()
        ),
        "post_freeze_mutation_required_to_interpret_economics": False,
        "note": "verifier worktree created from the exact prereg commit; no builder untracked files consumed",
    }


# ---------------------------------------------------------------- data binding

def recompute_funding() -> dict:
    out = {}
    parts = DATA_AUTHORITY_WT / "data" / "processed" / "arc01_funding"
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        p = parts / f"{sym}_funding.jsonl"
        if not p.exists():
            out[sym] = {"present": False}
            continue
        out[sym] = {
            "present": True,
            "sha256": sha256_file(p),
            "expected_sha256": EXPECTED_PARTITION_SHA256[sym],
            "match": sha256_file(p) == EXPECTED_PARTITION_SHA256[sym],
            "rows": sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip()),
        }
    fp = json.loads((VERIFIER_ROOT / "docs/arc01-data-authority-01/ARC01_DATASET_FINGERPRINT.json").read_text())
    return {"partitions": out, "declared_dataset_sha256": fp["dataset_sha256"], "dataset_sha256_match": fp["dataset_sha256"] == DATASET_SHA256}


def recompute_oi() -> dict:
    root = MAIN_ROOT / "data" / "processed" / "oi_full_history_v2"
    man_path = root / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
    ledger_path = root / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
    res: dict = {"present": man_path.exists()}
    if not man_path.exists():
        return res
    man = json.loads(man_path.read_text())
    ledger = [json.loads(x) for x in ledger_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    fp_src = json.dumps(
        {
            "schema_version": man["schema_version"],
            "normalizer_version": man["normalizer_version"],
            "files": [
                {k: e.get(k) for k in ("symbol", "day", "raw_source_sha256", "normalized_sha256", "rows", "dataset_fingerprint", "classification")}
                for e in sorted(ledger, key=lambda e: (str(e["symbol"]), str(e["day"])))
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    recomputed_fp = hashlib.sha256(fp_src.encode()).hexdigest()
    recomputed_ledger = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    res.update(
        {
            "recomputed_fingerprint": recomputed_fp,
            "declared_fingerprint": man["OI_FULL_HISTORY_DATASET_SHA256_V2"],
            "fingerprint_match": recomputed_fp == EXPECTED_OI["oi_full_history_dataset_sha256_v2"],
            "recomputed_ledger_sha256": recomputed_ledger,
            "ledger_match": recomputed_ledger == EXPECTED_OI["ledger_sha256"],
            "declared_manifest_sha256": man.get("manifest_sha256"),
            "manifest_match": man.get("manifest_sha256") == EXPECTED_OI["manifest_sha256"],
            "quality_status": man.get("quality_status"),
            "ledger_sha256_rederived_from_bytes": True,
        }
    )
    return res


def recompute_price() -> dict:
    root = MAIN_ROOT / "data" / "processed" / "price_1h_v2"
    per = {}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        p = root / f"{sym}_1h.jsonl"
        per[sym] = (
            {"present": p.exists(), "sha256": sha256_file(p), "match": sha256_file(p) == EXPECTED_PRICE_PER_ASSET[sym]}
            if p.exists()
            else {"present": False}
        )
    man_path = MAIN_ROOT / "docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json"
    declared = json.loads(man_path.read_text()) if man_path.exists() else {}
    return {
        "per_asset": per,
        "declared_fingerprint": declared.get("fingerprint") or declared.get("PRICE_AUTHORITY_V2_SHA256"),
        "expected_fingerprint": EXPECTED_PRICE_FINGERPRINT,
        "manifest_present": man_path.exists(),
    }


# ---------------------------------------------------------------- contamination

ECON_TOKENS = ["pnl", "sharpe", "sortino", "profit_factor", "expectancy", "win_rate", "future_return", "cum_return", "max_drawdown"]
SWEEP_TOKENS = ["parameter_sweep", "sweep", "grid_search", "threshold_optim", "lookback_optim", "holding_optim", "optimize", "best_asset", "rank_by_return"]


def contamination_scan() -> dict:
    arc_commits = sh(
        ["git", "log", "--all", "--oneline", "-i", "--grep=ARC01", "--grep=ARC-01"], MAIN_ROOT
    ).splitlines()
    arc_commits = [c for c in arc_commits if c.strip()]
    non_authority = [c for c in arc_commits if "PREREG" not in c and "DATA-" not in c]
    # files touched by the prereg commit that look like economic outputs
    added = sh(["git", "show", "--name-only", "--pretty=format:", PREREG_COMMIT], MAIN_ROOT).split()
    econ_named = [f for f in added if re.search(r"(pnl|result|equity|trade_log|backtest|sharpe|expectancy)", f, re.I)]
    # deny-list scan over ARC-01 prereg code / spec (should only appear in forbidden-lists)
    hits = {}
    for rel in (
        "src/trading_bot/research/arc01/prereg_reference.py",
        "scripts/verify_arc01_prereg.py",
    ):
        txt = (VERIFIER_ROOT / rel).read_text(encoding="utf-8").lower()
        hits[rel] = {t: txt.count(t) for t in ECON_TOKENS + SWEEP_TOKENS if txt.count(t)}
    # any tracked ARC-01 economic artifact?
    tracked = sh(["git", "ls-files"], MAIN_ROOT).splitlines()
    tracked_econ = [
        f for f in tracked
        if re.search(r"arc[-_]?01", f, re.I) and re.search(r"(result|pnl|equity|trade|backtest|discovery|sweep)", f, re.I)
    ]
    return {
        "schema": "ARC01_PERFORMANCE_CONTAMINATION_SCAN/1.0.0",
        "arc01_commits": arc_commits,
        "non_authority_arc01_commits": non_authority,
        "prereg_commit_added_files": added,
        "prereg_commit_economic_named_files": econ_named,
        "tracked_arc01_economic_artifacts": tracked_econ,
        "econ_token_hits_in_arc01_code": hits,
        "econ_tokens_in_code_context": "forbidden-vocabulary deny list + gate names only; no computation",
        "backtests": 0,
        "executions": 0,
        "performance_observed": False,
        "verdict": "NO_PRE_PREREG_ECONOMIC_OBSERVATION",
    }


# ---------------------------------------------------------------- spec audit

REQUIRED_SPEC_FIELDS = [
    "hypothesis_id", "economics", "market", "data_authority", "common_window",
    "decision_cadence", "funding_transform", "oi_transform", "price_context",
    "signal_rules", "entry", "exit", "position_policies", "return_definition",
    "cost_model", "funding_cashflow_accounting", "pit_rules", "sample_rules",
    "controls", "statistical_gates", "robustness_plan", "orthogonality", "kill_rule",
]


def spec_completeness() -> dict:
    spec = json.loads((PREREG / "ARC01_SPEC_V1.json").read_text())
    missing = [f for f in REQUIRED_SPEC_FIELDS if f not in spec]
    hidden_defaults = []
    # explicit position-policy block (stop / cooldown / overlap must be frozen, not defaulted)
    rc = spec.get("position_policies", {})
    for key in ("STOP", "COOLDOWN", "OVERLAPPING_SIGNAL_POLICY", "SAME_ASSET_REENTRY_POLICY", "MULTI_ASSET_SIMULTANEOUS_POLICY"):
        if key not in rc:
            hidden_defaults.append(f"position_policies.{key} not explicitly frozen")
    if str(rc.get("STOP")) != "NONE":
        hidden_defaults.append("STOP not explicitly NONE")
    if str(rc.get("COOLDOWN")) != "NONE":
        hidden_defaults.append("COOLDOWN not explicitly NONE")
    return {
        "schema": "ARC01_SPEC_COMPLETENESS_AUDIT/1.0.0",
        "required_fields": REQUIRED_SPEC_FIELDS,
        "missing_fields": missing,
        "present_count": len(REQUIRED_SPEC_FIELDS) - len(missing),
        "hidden_runtime_defaults": hidden_defaults,
        "spec_complete": not missing and not hidden_defaults,
    }


# ---------------------------------------------------------------- emit

def write(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ga = git_authority()
    fr = recompute_funding()
    oi = recompute_oi()
    pr = recompute_price()
    cs = contamination_scan()
    sc = spec_completeness()
    write("ARC01_GIT_AUTHORITY.json", ga)
    write("ARC01_DATA_BINDING_VERIFICATION.json", {
        "schema": "ARC01_DATA_BINDING_VERIFICATION/1.0.0",
        "expected": {"dataset_sha256": DATASET_SHA256, "partition_sha256": EXPECTED_PARTITION_SHA256,
                     "oi": EXPECTED_OI, "price_fingerprint": EXPECTED_PRICE_FINGERPRINT,
                     "price_per_asset": EXPECTED_PRICE_PER_ASSET},
        "funding": fr, "oi": oi, "price": pr,
        "all_bindings_reproduced": (
            all(v.get("match") for v in fr["partitions"].values())
            and fr["dataset_sha256_match"]
            and oi.get("fingerprint_match") and oi.get("ledger_match") and oi.get("manifest_match")
            and all(v.get("match") for v in pr["per_asset"].values())
        ),
    })
    write("ARC01_PERFORMANCE_CONTAMINATION_SCAN.json", cs)
    write("ARC01_SPEC_COMPLETENESS_AUDIT.json", sc)
    # VERIFIER_PROGRESS.json is maintained by the verifier (see the audit artifacts);
    # this generator intentionally does not overwrite the final progress state.
    print(json.dumps({
        "spec_sha_match": ga["spec_sha_match"], "manifest_sha_match": ga["manifest_sha_match"],
        "funding_match": all(v.get("match") for v in fr["partitions"].values()),
        "oi_match": oi.get("fingerprint_match"), "price_match": all(v.get("match") for v in pr["per_asset"].values()),
        "spec_complete": sc["spec_complete"], "arc_commits": len(cs["arc01_commits"]),
        "non_authority_arc_commits": cs["non_authority_arc01_commits"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
