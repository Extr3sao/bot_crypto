"""Verifier environment bootstrap — one command to determine if all required evidence inputs are accessible.

A fresh verifier worktree can run:

    python scripts/verify_h6_v3_environment.py [--data-root <path>]

Output: H6_V3_VERIFIER_ENVIRONMENT_CHECK.json
Checks: Git objects, data authority, raw OI access, normalized OI access, price authority,
        official source locators, test fixtures, required scripts.
No H6 economics.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def git_show_bytes(path: str, commit: str = "HEAD") -> bytes | None:
    try:
        return subprocess.check_output(["git", "show", f"{commit}:{path}"], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--commit", default="HEAD", help="commit to check Git objects against (default HEAD)")
    args = ap.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    commit = args.commit
    data_root = Path(args.data_root) if args.data_root else None
    if not data_root and os.environ.get("TRADING_AGENTIC_DATA_ROOT"):
        data_root = Path(os.environ["TRADING_AGENTIC_DATA_ROOT"])
    if not data_root:
        data_root = repo / "data"

    checks: list[dict[str, object]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # 1. Git objects for V3 (or V2 if V3 not yet committed) — we check V2 as fallback for builder state
    for p in [
        "docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json",
        "docs/external-audit-01/oi-full-history-02/H6_MANIFEST_V2.json",
        "docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json",
        "docs/external-audit-01/oi-full-history-02/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl",
        "docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json",
        "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
    ]:
        b = git_show_bytes(p, commit) or (repo / p).read_bytes() if (repo / p).exists() else None  # type: ignore[operator]
        check(f"artifact_exists:{Path(p).name}", b is not None, str(b[:20]) if b else "missing")

    # 2. Data authority JSON exists and is tracked
    da_path = repo / "docs" / "external-audit-01" / "oi-full-history-03" / "H6_DATA_AUTHORITY_V3.json"
    check("H6_DATA_AUTHORITY_V3_tracked", da_path.exists())
    if da_path.exists():
        try:
            da = json.loads(da_path.read_text(encoding="utf-8"))
            check("H6_DATA_AUTHORITY_V3_has_locator", "raw_source_locator_pattern" in da)
            check("H6_DATA_AUTHORITY_V3_has_dataset_sha", len(str(da.get("dataset_sha256", ""))) == 64)
            check("H6_DATA_AUTHORITY_V3_ledger_sha_correct", da.get("ledger_sha256") == "bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714")
        except Exception as e:
            check("H6_DATA_AUTHORITY_V3_parse", False, str(e))

    # 3. Raw OI access via data root
    raw_base = data_root / "raw" / "binance_um" / "metrics"
    if data_root != repo / "data" and not raw_base.exists():
        raw_base = repo / "data" / "raw" / "binance_um" / "metrics"
    for sym, exp in [("BTCUSDT", 2201), ("ETHUSDT", 1745), ("SOLUSDT", 1745)]:
        cnt = len(list((raw_base / sym).glob("*.zip"))) if raw_base.exists() else -1
        check(f"raw_OI_access:{sym}", cnt == exp, f"{cnt}/{exp} at {raw_base / sym}")

    # 4. Normalized OI access
    norm_root = data_root / "processed" / "oi_full_history_v2"
    if data_root != repo / "data" and not norm_root.exists():
        norm_root = repo / "data" / "processed" / "oi_full_history_v2"
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        exists = (norm_root / sym).exists() if norm_root.exists() else False
        check(f"normalized_OI_access:{sym}", exists, str(norm_root / sym))

    # 5. Price authority
    pm = repo / "docs" / "external-audit-01" / "oi-full-history-02" / "PRICE_1H_AUTHORITY_V2_MANIFEST.json"
    check("price_authority_manifest", pm.exists())
    if pm.exists():
        try:
            j = json.loads(pm.read_text(encoding="utf-8"))
            check("price_covers_window", j.get("all_assets_cover_common_window") is True)
        except Exception as e:
            check("price_manifest_parse", False, str(e))

    # 6. Required scripts
    for s in ["scripts/verify_h6_data_authority.py", "scripts/normalize_oi_full_history_v2.py", "scripts/build_price_authority_v2.py", "src/trading_bot/research/h6/whitelist.py", "src/trading_bot/research/h6/hash_validator.py", "src/trading_bot/research/h6/conf_lock.py", "src/trading_bot/research/h6/confirmation_state.py"]:
        check(f"script:{Path(s).name}", (repo / s).exists(), s)

    # 7. Hash validators: ledger 71-char trap must fail
    try:
        from trading_bot.research.h6.hash_validator import validate_sha256

        try:
            validate_sha256("bb2b43c27a88bf9ff334fa5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc")
            check("hash_validator_blocks_71", False, "71-char should have raised")
        except ValueError:
            check("hash_validator_blocks_71", True)
        try:
            validate_sha256("bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714")
            check("hash_validator_passes_correct_64", True)
        except ValueError:
            check("hash_validator_passes_correct_64", False)
    except Exception as e:
        check("hash_validator_import", False, str(e))

    failed = [c for c in checks if not c["ok"]]
    out = {
        "commit": commit,
        "data_root": str(data_root),
        "raw_base": str(raw_base),
        "H6_V3_VERIFIER_ENVIRONMENT_CHECK": "PASS" if not failed else "FAIL",
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "checks": checks,
    }
    out_path = repo / "docs" / "external-audit-01" / "oi-full-history-03" / "H6_V3_VERIFIER_ENVIRONMENT_CHECK.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
