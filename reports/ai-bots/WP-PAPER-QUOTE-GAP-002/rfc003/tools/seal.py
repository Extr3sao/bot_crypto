"""Seal the evidence directory: sha256 over the bytes, no self-reference.

The manifest cannot hash itself, so the anchor is external: the commit that carries it
(``EVIDENCE_SHA``).  That is why ``check_evidence_manifest`` rejects any entry that points at
the manifest, and why ``git`` — not this file — is what makes the seal verifiable.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[5]
WP = REPO / "reports" / "ai-bots" / "WP-PAPER-QUOTE-GAP-002"
RFC = WP / "rfc003"
OUT = RFC / "EVIDENCE_MANIFEST.json"
SELF = OUT.resolve()

RUNTIME_INVENTORY = [
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/vision/quotes.py",
    "src/trading_bot/vision/durable.py",
    "src/trading_bot/vision/gap_recovery.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/risk/manager.py",
    "pyproject.toml",
]


def role_for(rel: str) -> str:
    name = Path(rel).name
    if "/evidence/" in rel:
        if name.endswith(".log"):
            return "primary-log"
        if name == "collect.txt":
            return "collection"
        if name.startswith("requirements"):
            return "environment"
        return "evidence"
    if "/tools/" in rel:
        return "tooling"
    if "/archive/" in rel:
        return "input-dataset"
    if "/lab/" in rel or "/drill/" in rel:
        return "artifact"
    if name.endswith(".json"):
        return "artifact"
    return "report"


def producer_for(rel: str) -> str:
    if "/evidence/" in rel:
        return "scripts in rfc003/tools driven from the clean checkout"
    if "/archive/" in rel:
        return "minute collector (binance_spot_rest_1m), archived"
    return "builder"


def main() -> int:
    entries: list[dict[str, Any]] = []
    for path in sorted(WP.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() == SELF:
            continue
        #: The verifier's own output cannot be sealed by the manifest it reads: every run would
        #: make the entry stale by existing. Its integrity is anchored by EVIDENCE_SHA instead,
        #: and the verifier re-hashes every *other* entry on each run.
        if path.name == "PHASE_A_VERIFICATION.json":
            continue
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if "rfc003/evidence/__pycache__" in rel or rel.endswith(".pyc"):
            continue
        raw = path.read_bytes()
        entries.append({
            "path": rel,
            "role": role_for(rel),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "producer": producer_for(rel),
            "created_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            .isoformat(timespec="seconds"),
        })

    lab = json.loads((WP / "lab" / "GAP_LAB.json").read_text(encoding="utf-8"))
    data = json.loads((RFC / "DATA_PROVENANCE.json").read_text(encoding="utf-8"))
    suite = json.loads((RFC / "SUITE_IDENTITY.json").read_text(encoding="utf-8"))

    payload = {
        "schema": "EVIDENCE_MANIFEST_V2",
        "wp": "WP-PAPER-QUOTE-GAP-002",
        "rfc": "RFC-PAPER-QUOTE-GAP-003",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_sha": suite.get("code_sha"),
        "runtime_inventory": RUNTIME_INVENTORY,
        "hash_kinds": {
            "file_sha256": "sha256 of the bytes in `entries`",
            "event_chain_head_sha256": (
                "head of the collector's hash chain; it names 3034 rows, not the file"),
            "minutes_sha256": "sha256 of the per-symbol 1-minute file (same as file_sha256)",
            "bars_sha256": "sha256 of the derived 5m series",
        },
        "chain_heads": {
            "events": data.get("collector", {}).get("chain_head"),
            "lab_locked": {
                "final_state_digest": (lab.get("kill_while_resuming") or {})
                .get("final_state_digest"),
                "reference_state_digest": (lab.get("kill_while_resuming") or {})
                .get("reference_state_digest"),
            },
        },
        "entries": entries,
        "self_excluded": str(OUT.relative_to(REPO)).replace("\\", "/"),
        "anchor": (
            "this manifest is not hashed inside itself; the commit that publishes it "
            "(EVIDENCE_SHA) is the external anchor, and tests re-hash every entry from disk"),
        "totals": {
            "entries": len(entries),
            "bytes": sum(entry["byte_count"] for entry in entries),
            "by_role": {},
        },
    }
    for entry in entries:
        payload["totals"]["by_role"][entry["role"]] = \
            payload["totals"]["by_role"].get(entry["role"], 0) + 1

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                          text=True).stdout.strip()
    print(f"wrote {OUT.relative_to(REPO)}: {len(entries)} entries, "
          f"{payload['totals']['bytes']} bytes, code_sha={payload['code_sha']}, head={head[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
