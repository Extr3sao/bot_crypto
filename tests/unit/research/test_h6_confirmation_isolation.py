"""H6 must not import confirmation outcomes."""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]


def test_h6_does_not_import_confirmation_outcome() -> None:
    h6_dir = REPO / "src" / "trading_bot" / "research" / "h6"
    for p in h6_dir.glob("*.py"):
        t = p.read_text(encoding="utf-8")
        # H6 files must not consume confirmation performance state
        if "confirmation" in t.lower():
            # conf_lock itself is the guard — allowed to mention confirmation
            if p.name in ("conf_lock.py", "confirmation_state.py"):
                continue
            # feature_engine, whitelist, hash_validator, etc. must not import confirmation data
            assert "ConfirmationState" not in t, f"{p.name} must not import ConfirmationState"
            # No direct ledger read for H6 signal
            assert "CONFIRMATION_LEDGER" not in t, f"{p.name} must not read confirmation ledger for H6 signal"
            # execution_harness must not consume confirmation outcomes either — only governance guard
            if p.name == "execution_harness.py":
                assert "consumed" not in t.lower() or "confirmation" not in t.lower(), "harness must not check consumed for H6 logic"


def test_h6_feature_engine_imports_are_isolated() -> None:
    fe = (REPO / "src" / "trading_bot" / "research" / "h6" / "feature_engine.py").read_text(encoding="utf-8")
    assert "CONFIRMATION" not in fe
    assert "confirmation" not in fe.lower()
    assert "Shadow" not in fe
