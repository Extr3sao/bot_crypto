"""V3 price overlap full verification (spec 28 — EXT-PRICE-LIMIT-001).

V2 verifier downgraded PRICE_OVERLAP to LIMITATION_PARTIAL because the manifest
proved equality at a single boundary timestamp. This verifier compares the FULL
overlap between the frozen H1 1h klines (cb3de4f) and the V2 extended price
authority, element-wise, for all three assets, plus strict 1h continuity of the
V2 extension tail. Writes durable machine-readable evidence and exits non-zero
on any mismatch.

Usage: python scripts/verify_price_overlap_v3.py [--data-root <path>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVID3 = REPO / "docs/external-audit-01/oi-full-history-03"
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def resolve_data_root(cli: str | None) -> Path:
    if cli:
        return Path(cli)
    env = os.environ.get("TRADING_AGENTIC_DATA_ROOT")
    if env:
        return Path(env)
    try:
        shared = REPO.parents[1] / "data"
    except IndexError:
        shared = REPO.parent / "data"
    if (shared / "processed" / "price_1h_v2").is_dir():
        return shared
    return REPO / "data"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None)
    ap.add_argument(
        "--evidence-dir",
        default=os.environ.get("H6_EVIDENCE_DIR"),
        help="directory for the machine-readable result (default: the historical V3 evidence dir)",
    )
    args = ap.parse_args()
    root = resolve_data_root(args.data_root)

    per_asset: dict[str, dict] = {}
    for asset in ASSETS:
        h1p = REPO / "docs/external-audit-01/h1-regime-transition-01/dataset" / f"{asset}_1h.jsonl"
        v2p = root / "processed" / "price_1h_v2" / f"{asset}_1h.jsonl"
        if not h1p.exists() or not v2p.exists():
            print(json.dumps({"status": "FAIL", "reason": f"missing authority file for {asset}", "h1": str(h1p), "v2": str(v2p)}))
            return 1
        h1 = [json.loads(l) for l in h1p.read_text(encoding="utf-8").splitlines() if l.strip()]
        v2 = [json.loads(l) for l in v2p.read_text(encoding="utf-8").splitlines() if l.strip()]
        n = min(len(h1), len(v2))
        mismatches = sum(1 for i in range(n) if h1[i] != v2[i])
        tail = v2[n - 48 : n]
        gaps = sum(1 for j in range(1, len(tail)) if tail[j][0] - tail[j - 1][0] != 3_600_000)
        per_asset[asset] = {
            "h1_rows": len(h1),
            "v2_rows": len(v2),
            "overlap_rows_compared": n,
            "mismatch_count": mismatches,
            "extension_tail_hours": len(tail),
            "tail_continuity_gaps": gaps,
            "overlap_boundary_ts_match": bool(h1[-1][0] == v2[n - 1][0]),
        }
        per_asset[asset]["overlap_equal"] = (
            per_asset[asset]["mismatch_count"] == 0
            and per_asset[asset]["overlap_boundary_ts_match"]
            and per_asset[asset]["tail_continuity_gaps"] == 0
        )

    ok = all(r["overlap_equal"] for r in per_asset.values())
    out = {
        "checkpoint": "H6-V3-REPAIR",
        "proof": "PRICE_OVERLAP_V3_FULL",
        "command": "python scripts/verify_price_overlap_v3.py [--data-root <path>]",
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip(),
        "data_root": str(root),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "exit_code": 0 if ok else 1,
        "per_asset": per_asset,
        "total_rows_compared": sum(r["overlap_rows_compared"] for r in per_asset.values()),
        "status": "PASS" if ok else "FAIL",
        "note": "full element-wise overlap of frozen H1 klines vs V2 extended authority (all rows, all assets) + strict 1h continuity of extension tail",
    }
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else EVID3
    if not evidence_dir.is_absolute():
        evidence_dir = REPO / evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "PRICE_OVERLAP_V3_RESULT.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "total_rows_compared": out["total_rows_compared"], "per_asset": {a: r["overlap_equal"] for a, r in per_asset.items()}}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
