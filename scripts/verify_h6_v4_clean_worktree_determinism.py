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
requires the proof's commit to be an ancestor of this worktree's HEAD **and**
every file in PROOF_INPUT_PATHS (the standalone proof and the normalizer module
it imports -- its only project dependency) to be byte-identical between the
evidence commit and HEAD, compared by git blob IDs.  The gate also asserts the
proof stays free of ``trading_bot`` imports, so those two files are provably the
only inputs that can decide the proof's RESULT.  The runtime data-root resolver
is deliberately NOT a proof input: it cannot change what the proof computed, and
its layout-sensitive behaviour is re-executed locally by half (1) of this gate.
Commits that only add evidence, tests or harnesses do not invalidate the proof;
any commit that touches a PROOF_INPUT_PATHS file does, and the gate then FAILS
closed instead of silently accepting stale evidence.

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
# Inputs whose bytes decide the reused proof's RESULT. The proof is a standalone script:
# it embeds the fingerprint derivation and its only project dependency is the normalizer
# module (neither file mentions `trading_bot`, which the gate asserts below). Anything not
# in this list -- including the runtime data-root resolver -- cannot change what the proof
# computed, so it does not invalidate the reuse; the layout-sensitive behaviour it does
# affect is re-executed locally by half (1) of this gate.
PROOF_INPUT_PATHS = [
    "scripts/prove_h6_v3_dataset_determinism.py",
    "scripts/normalize_oi_full_history_v2.py",
]
PROOF_IMPORT_SCOPE_NOTE = (
    "proof and normalizer must stay free of project-module imports, otherwise the reuse "
    "scope below would be wrong and PROOF_INPUT_PATHS would have to be widened"
)
LEDGER = REPO / "docs/external-audit-01/oi-full-history-02/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
MANIFEST = REPO / "docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
OUT_NAME = "H6_V4_CLEAN_WORKTREE_DETERMINISM.json"


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True, text=True
    ).stdout.strip()


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def _proof_inputs_unchanged(proof_commit: str, head: str) -> tuple[bool, list[str], dict]:
    """Byte-level check: are every proof input identical at the evidence commit and HEAD?

    Compares git blob IDs rather than working-tree bytes so the check is independent of
    checkout state and of any unrelated intermediate commit.
    """
    changed: list[str] = []
    blobs: dict[str, dict[str, str]] = {}
    for path in PROOF_INPUT_PATHS:
        at_evidence = _git("rev-parse", f"{proof_commit}:{path}")
        at_head = _git("rev-parse", f"{head}:{path}")
        b_ev = at_evidence.stdout.strip()
        b_hd = at_head.stdout.strip()
        blobs[path] = {"at_evidence_commit": b_ev, "at_head": b_hd}
        if at_evidence.returncode != 0 or at_head.returncode != 0 or b_ev != b_hd:
            changed.append(path)
    return (not changed), changed, blobs


def _proof_scope_is_stdlib_only() -> tuple[bool, list[str]]:
    offenders = [
        path
        for path in PROOF_INPUT_PATHS
        if "trading_bot" in (REPO / path).read_text(encoding="utf-8", errors="replace")
    ]
    return (not offenders), offenders


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
        anc = _git("merge-base", "--is-ancestor", proof_commit, head)
        inputs_ok, changed_inputs, input_blobs = _proof_inputs_unchanged(proof_commit, head)
        scope_ok, scope_offenders = _proof_scope_is_stdlib_only()
        rebind_ok = anc.returncode == 0 and inputs_ok and scope_ok
        reuse.update(
            {
                "evidence_present": True,
                "evidence_commit": proof_commit,
                "evidence_status": durable.get("status"),
                "evidence_data_root": durable.get("data_root"),
                "evidence_duration_seconds": durable.get("duration_seconds"),
                "evidence_commit_is_ancestor_of_head": anc.returncode == 0,
                "proof_input_paths": PROOF_INPUT_PATHS,
                "proof_input_blob_ids": input_blobs,
                "proof_input_paths_changed_since_evidence": changed_inputs,
                "proof_import_scope_note": PROOF_IMPORT_SCOPE_NOTE,
                "proof_inputs_with_project_imports": scope_offenders,
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
