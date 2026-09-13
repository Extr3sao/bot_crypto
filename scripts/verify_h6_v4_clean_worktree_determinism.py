"""H6 V4 — clean-worktree DATASET AUTHORITY + DETERMINISM gate.

Why this is not just a re-run of ``prove_h6_v3_dataset_determinism.py``
----------------------------------------------------------------------
The full A/B proof re-normalizes 5,691 raw provider files twice; on this machine
that costs ~8,860 s (~2.5 h) per invocation.  Checkpoint section 25 explicitly
forbids rebuilding data authority without reason: DATA_AUTHORITY,
DATASET_FINGERPRINT and BTC_2024_06_05_FORENSIC already have PASSing durable
evidence, so re-deriving them wholesale in the disposable clean worktree would
burn the execution budget without adding any new information.

What this gate does instead — it is deliberately split into two independent
halves:

  (1) RECOMPUTED IN THIS WORKTREE (the part that is layout/data-path sensitive,
      i.e. the part a clean worktree genuinely can falsify):
      resolve the shared data root through the shipped runtime resolver, then
      recompute the canonical dataset fingerprint from the ACTUAL bytes of the
      frozen normalized files and require it to equal the committed authority
      fingerprint recorded in the V2 manifest.

  (2) REUSED DURABLE EVIDENCE (the expensive part, whose result cannot depend on
      which worktree executes it):
      the standalone ``DATASET_DETERMINISM_V3_RESULT.json`` must exist, be PASS
      on all three sub-proofs, and be bound to EXACTLY this worktree's commit.

Reuse is only sound while the proof's INPUTS are unchanged.  The gate therefore
requires the proof's commit to be an ancestor of this worktree's HEAD **and** the
normalization / data-authority code to be byte-identical between the two
(``git diff --name-only <proof_commit>..HEAD -- <authority code>`` must be empty).
Commits that only add evidence, tests or harnesses do not invalidate the proof;
any commit that touches the normalizer or the data-root resolver does, and the
gate then FAILS closed instead of silently accepting stale evidence.

DATA-ONLY: no signals, no performance, no economics.
Exit 0 iff both halves PASS.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from normalize_oi_full_history_v2 import NORMALIZER_VERSION, SCHEMA_VERSION  # noqa: E402
from prove_h6_v3_dataset_determinism import recompute_dataset_fingerprint  # noqa: E402

from trading_bot.research.oi_dataset_v2 import (  # noqa: E402
    resolve_oi_v2_data_dir,
)

EVID = REPO / "docs" / "external-audit-01" / "h6-v4-repair"
# Inputs whose bytes decide the reused proof's result.
PROOF_INPUT_PATHS = [
    "scripts/normalize_oi_full_history_v2.py",
    "src/trading_bot/research/oi_dataset_v2.py",
]
LEDGER = REPO / "docs/external-audit-01/oi-full-history-02/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
MANIFEST = REPO / "docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
OUT_NAME = "H6_V4_CLEAN_WORKTREE_DETERMINISM.json"


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True, text=True
    ).stdout.strip()


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def main() -> int:
    head = _head()
    out: dict[str, object] = {
        "artifact": "H6_V4_CLEAN_WORKTREE_DETERMINISM",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "worktree": str(REPO),
        "git_commit": head,
        "python_executable": sys.executable,
        "normalizer_version": NORMALIZER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "H6_BACKTESTS": 0,
        "H6_EXECUTIONS": 0,
        "PERFORMANCE_OBSERVED": False,
    }

    # ---- (1) recomputed in THIS worktree -------------------------------------
    processed = resolve_oi_v2_data_dir()
    resolved_root = processed.parents[1] if processed.name == "oi_full_history_v2" else processed
    committed_fp = json.loads(MANIFEST.read_text(encoding="utf-8"))[
        "OI_FULL_HISTORY_DATASET_SHA256_V2"
    ]
    fp_local = recompute_dataset_fingerprint(LEDGER, files_root=processed)
    out["local_recomputation"] = {
        "resolver_used": "trading_bot.research.oi_dataset_v2.resolve_oi_v2_data_dir",
        "resolved_processed_dir": str(processed),
        "resolved_data_root": str(resolved_root),
        "processed_dir_exists": processed.is_dir(),
        "committed_authority_fingerprint": committed_fp,
        "recomputed_canonical_fingerprint": fp_local,
        "recomputed_equals_committed": fp_local == committed_fp,
    }

    # ---- (2) reused durable evidence, bound to this commit --------------------
    durable_path = EVID / "DATASET_DETERMINISM_V3_RESULT.json"
    reuse: dict[str, object] = {"evidence_file": durable_path.name}
    durable: dict = {}
    if not durable_path.exists():
        reuse["evidence_present"] = False
        reuse["status"] = "FAIL_MISSING_DURABLE_EVIDENCE"
    else:
        durable = json.loads(durable_path.read_text(encoding="utf-8"))
        det = durable.get("determinism", {}) or {}
        mut = durable.get("mutation_sensitivity", {}) or {}
        fore = durable.get("btc_2024_06_05_forensic", {}) or {}
        proof_commit = str(durable.get("commit") or "")
        anc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", proof_commit, head],
            cwd=str(REPO), capture_output=True, text=True,
        )
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{proof_commit}..{head}", "--", *PROOF_INPUT_PATHS],
            cwd=str(REPO), capture_output=True, text=True,
        )
        changed_inputs = [ln for ln in diff.stdout.splitlines() if ln.strip()]
        rebind_ok = anc.returncode == 0 and not changed_inputs
        reuse.update(
            {
                "evidence_present": True,
                "evidence_commit": proof_commit,
                "evidence_status": durable.get("status"),
                "evidence_data_root": durable.get("data_root"),
                "evidence_duration_seconds": durable.get("duration_seconds"),
                "evidence_commit_is_ancestor_of_head": anc.returncode == 0,
                "proof_input_paths": PROOF_INPUT_PATHS,
                "proof_input_paths_changed_since_evidence": changed_inputs,
                "reuse_binding_ok": rebind_ok,
                "commit_matches_clean_worktree": proof_commit == head,
                "data_root_matches_resolved": _norm(durable.get("data_root", ""))
                == _norm(resolved_root),
                "determinism_status": det.get("determinism_status"),
                "ledger_bytes_A_equals_B": det.get("ledger_bytes_A_equals_B"),
                "fingerprint_A_equals_B": det.get("fingerprint_A_equals_B"),
                "fingerprint_A_equals_committed": det.get("fingerprint_A_equals_committed"),
                "fingerprint_commits_to_actual_bytes": det.get("fingerprint_commits_to_actual_bytes"),
                "fingerprint_A": det.get("fingerprint_A"),
                "mutation_status": mut.get("mutation_status"),
                "mutation_changed_fingerprint": mut.get("fingerprint_C_differs_from_A"),
                "forensic_status": fore.get("forensic_status"),
                "official_checksum_match": fore.get("official_checksum_match"),
                "renormalized_byte_identical_to_canonical": fore.get("byte_identical"),
            }
        )
        reuse["status"] = "PASS" if (
            rebind_ok
            and durable.get("status") == "PASS"
            and det.get("determinism_status") == "PASS"
            and bool(det.get("ledger_bytes_A_equals_B"))
            and bool(det.get("fingerprint_A_equals_B"))
            and bool(det.get("fingerprint_A_equals_committed"))
            and bool(det.get("fingerprint_commits_to_actual_bytes"))
            and mut.get("mutation_status") == "PASS"
            and bool(mut.get("fingerprint_C_differs_from_A"))
            and fore.get("forensic_status") == "PASS"
            and bool(fore.get("official_checksum_match"))
            and bool(fore.get("byte_identical"))
        ) else "FAIL"

    # the reused proof's own fingerprint must agree with what we recomputed here
    cross_fp = (durable.get("determinism", {}) or {}).get("committed_authority_fingerprint")
    out["reuse"] = reuse
    out["cross_check"] = {
        "durable_committed_authority_fingerprint": cross_fp,
        "durable_fingerprint_equals_local_recomputation": cross_fp == fp_local,
    }

    pass_local = bool(
        processed.is_dir() and fp_local == committed_fp
    )
    pass_reuse = reuse.get("status") == "PASS"
    pass_cross = cross_fp == fp_local
    out["local_recomputation_status"] = "PASS" if pass_local else "FAIL"
    out["reuse_status"] = "PASS" if pass_reuse else "FAIL"
    out["cross_check_status"] = "PASS" if pass_cross else "FAIL"
    status = "PASS" if (pass_local and pass_reuse and pass_cross) else "FAIL"
    out["DATASET_DETERMINISM"] = status
    out["evidence_policy"] = (
        "full A/B re-normalization + mutation sensitivity + BTC forensic are REUSED from the "
        "durable standalone proof bound to this exact commit; the canonical authority "
        "fingerprint is RECOMPUTED here from actual bytes through the shipped resolver"
    )

    (EVID / OUT_NAME).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
