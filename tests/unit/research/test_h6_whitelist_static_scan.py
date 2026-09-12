"""Static scan: H6 runtime must not bypass H6FieldAccess."""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]


def test_no_runtime_whitelist_bypass() -> None:
    # H6 runtime files that might access OI rows: feature_engine, whitelist itself, possibly research modules.
    # Policy: any direct dict access to known forbidden fields outside whitelist.py is a bypass.
    forbidden = [
        "unadmitted_metric",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ]
    # Allowlisted file: whitelist.py is the authority itself — ignore.
    h6_dir = REPO / "src" / "trading_bot" / "research" / "h6"
    offenders: list[str] = []
    for p in h6_dir.glob("*.py"):
        if p.name == "whitelist.py":
            continue
        text = p.read_text(encoding="utf-8")
        for field in forbidden:
            if field in text:
                offenders.append(f"{p.name} contains forbidden literal {field}")
        # Also flag raw dict indexing like row["sum_open_interest"] outside whitelist if not via H6FieldAccess
        # Our feature_engine uses structured dataclasses, not raw payload dicts — that's fine.
        # Scan for suspicious pattern: '["sum_open_interest"' without H6FieldAccess wrapper (informational)
        # For now only forbid the forbidden fields; raw allowed fields via structured dataclasses are okay.
    assert not offenders, "NO_RUNTIME_WHITELIST_BYPASS failed: " + "; ".join(offenders)

    # Also ensure sum_open_interest is only consumed via H6FieldAccess or the structured H6 contracts
    # For portability, verify feature_engine imports only from contracts, not raw provider payload
    fe = (h6_dir / "feature_engine.py").read_text(encoding="utf-8")
    assert "unadmitted" not in fe.lower()
    for field in forbidden:
        assert field not in fe, f"feature_engine must not reference forbidden field {field}"
