from __future__ import annotations

import json
import pathlib
import hashlib
import sys
import datetime
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPLORER = ROOT / "data/recovery/COST_BARRIER_EXPLORER.json"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
VERIFIER = str(ROOT / "scripts/cost_barrier_verify.py")

def main() -> int:
    if not EXPLORER.exists():
        print("FAIL: explorer missing"); return 10
    if not PYTHON.exists():
        print("FAIL: python launcher missing at", PYTHON); return 11

    original_bytes = EXPLORER.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    doc = json.loads(original_bytes)
    published_payload_sha = doc.get("payload_sha256")
    print("original sha256:", original_sha)
    print("payload_sha256 in root:", published_payload_sha)
    print("n cells:", len(doc.get("cells", [])))

    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    tmp_dir = ROOT / ".ci" / f"recovery005_mutant_{stamp}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    mutant_path = tmp_dir / "COST_BARRIER_EXPLORER_MUTANT.json"

    mutant = json.loads(original_bytes)
    mutant["payload_sha256"] = "0" * 64
    mutant_bytes = json.dumps(mutant, indent=2, sort_keys=True).encode("utf-8")
    mutant_path.write_bytes(mutant_bytes)

    print("mutant path:", mutant_path)
    print("mutant sha256:", hashlib.sha256(mutant_bytes).hexdigest())
    print("original still byte-identical at write time:", EXPLORER.read_bytes() == original_bytes)

    completed = subprocess.run(
        [str(PYTHON), VERIFIER, "--explorer", str(mutant_path), "--out", str(tmp_dir / "verifier_out.json"), "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    print("verifier exit code:", completed.returncode)
    print("verifier stdout tail:")
    print(completed.stdout[-4000:])
    print("verifier stderr tail:")
    print(completed.stderr[-2000:])

    evidence_path = tmp_dir / "M9_MUTATION_EVIDENCE.json"
    evidence = {
        "run_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": [str(PYTHON), VERIFIER, "--explorer", str(mutant_path), "--out", str(tmp_dir / "verifier_out.json"), "--json"],
        "commit": subprocess.run(["git","rev-parse","HEAD"], cwd=str(ROOT), capture_output=True, text=True).stdout.strip(),
        "original_sha256": original_sha,
        "original_payload_sha256": published_payload_sha,
        "mutant_path": str(mutant_path),
        "mutant_sha256": hashlib.sha256(mutant_bytes).hexdigest(),
        "mutated_key": "payload_sha256",
        "mutated_value": "0" * 64,
        "original_intact_after_experiment": EXPLORER.read_bytes() == original_bytes,
        "verifier_exit_code": completed.returncode,
        "verifier_stdout_tail": completed.stdout[-4000:],
        "verifier_stderr_tail": completed.stderr[-2000:],
    }
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print("evidence written:", evidence_path)

    if completed.returncode == 0:
        print("BLOCKED_M9_VERIFIER_NOT_REJECTING_HASH_ZERO: verifier returned 0 on a hash-mutated copy")
        return 12
    print("M9_HASH_MUTATION_REJECTED: verifier rejected the hash-zero copy with non-zero exit")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
