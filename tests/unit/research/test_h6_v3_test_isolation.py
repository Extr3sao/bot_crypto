"""H6 V3 — TEST ISOLATION (spec 14).

From the test context, deliberately attempt writes into the canonical dataset
roots (V1 and V2/V3) through the sanctioned dataset APIs.

Required behavior: FAIL CLOSED with an explicit authority error, and the
dataset fingerprint evidence must be unchanged (BEFORE == AFTER).

If the shared data authority is not reachable, tests SKIP with an explicit
reason (never fake a pass).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _resolve_canonical_roots() -> tuple[Path, Path] | None:
    """Resolve (v1_root, v2_root) via the portable authority chain, else None."""
    env = os.environ.get("TRADING_AGENTIC_DATA_ROOT")
    candidates: list[Path] = []
    if env:
        r = Path(env)
        candidates += [r / "data" / "processed", r / "processed"]
    # worktree-local first, then shared main repo (nested .worktrees layout)
    candidates += [
        REPO / "data" / "processed",
        REPO.parents[1] / "data" / "processed",
    ]
    for base in candidates:
        v2 = base / "oi_full_history_v2"
        if (v2 / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").exists():
            return base / "oi_full_history", v2
    return None


def _fingerprint_bytes(v2_root: Path) -> str:
    ledger = v2_root / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
    manifest = v2_root / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
    h = hashlib.sha256()
    h.update(ledger.read_bytes())
    if manifest.exists():
        h.update(manifest.read_bytes())
    # include the BTC forensic-day canonical file bytes
    probe = v2_root / "BTCUSDT" / "BTCUSDT-oi-5m-2024-06-05.jsonl"
    if probe.exists():
        h.update(probe.read_bytes())
    return h.hexdigest()


def _attempt_canonical_writes(v1_root: Path, v2_root: Path) -> list[str]:
    """Deliberate write attacks through sanctioned dataset APIs; return caught errors."""
    caught: list[str] = []
    os.environ["PYTEST_CURRENT_TEST"] = "test_isolation_attack (call)"
    try:
        from scripts.normalize_oi_full_history_v2 import process_file_v2

        for root in (v1_root, v2_root):
            try:
                process_file_v2("BTCUSDT", "2099-01-01", raw_dir=Path(os.devnull).parent, out_dir=root)
                caught.append(f"UNCAUGHT_WRITE {root}")
            except RuntimeError as e:
                if "TEST_DATASET_WRITE_FORBIDDEN" in str(e):
                    caught.append(f"BLOCKED {root.name}")
                else:
                    caught.append(f"OTHER_RUNTIME_ERROR {root.name}: {e}")
            except Exception as e:  # noqa: BLE001
                caught.append(f"OTHER_ERROR {root.name}: {type(e).__name__}")
    finally:
        os.environ.pop("PYTEST_CURRENT_TEST", None)
    return caught


def test_test_isolation_attacks_fail_closed_and_fingerprint_unchanged() -> None:
    roots = _resolve_canonical_roots()
    if roots is None:
        pytest.skip("AUTHORITY_UNREACHABLE: canonical V2 data root not found (portable resolution failed)")
    v1_root, v2_root = roots
    before = _fingerprint_bytes(v2_root)

    caught = _attempt_canonical_writes(v1_root, v2_root)
    assert "UNCAUGHT_WRITE" not in " ".join(caught), f"write attack succeeded: {caught}"
    assert sum(1 for c in caught if c.startswith("BLOCKED")) == 2, f"both roots must fail closed: {caught}"

    after = _fingerprint_bytes(v2_root)
    assert before == after, "dataset fingerprint changed during isolation attacks (BEFORE != AFTER)"


def test_test_isolation_reader_side_never_writes(tmp_path: Path) -> None:
    """Causal reader APIs must be read-only against the canonical authority."""
    roots = _resolve_canonical_roots()
    if roots is None:
        pytest.skip("AUTHORITY_UNREACHABLE: canonical V2 data root not found (portable resolution failed)")
    _v1_root, v2_root = roots
    before = _fingerprint_bytes(v2_root)

    from trading_bot.research.oi_dataset_v2 import (
        decision_eligibility_at_v2,
        oi_hourly_decision_state_v2,
        oi_state_at_ms,
        validate_ledger_v2_semantics,
    )

    T = 1717545600000  # 2024-06-05T00:00Z (historic, read-only)
    oi_state_at_ms(T, "BTCUSDT", v2_root)
    oi_hourly_decision_state_v2(T, "BTCUSDT", v2_root)
    decision_eligibility_at_v2(T, "BTCUSDT", v2_root)
    validate_ledger_v2_semantics(v2_root / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl")

    after = _fingerprint_bytes(v2_root)
    assert before == after, "read-side APIs modified the canonical authority"
