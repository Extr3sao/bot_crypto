"""Standalone bootstrap used by ARC-02 scripts before first-party imports."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def bootstrap_arc02(target_root: Path | None = None, expected_commit: str | None = None):
    root = (target_root or Path(__file__).resolve().parents[1]).resolve()
    source = root / "src"
    helper_path = source / "trading_bot" / "research" / "import_authority.py"
    spec = importlib.util.spec_from_file_location("_arc02_import_authority", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import authority contract: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = expected_commit or os.environ.get("ARC02_EXPECTED_COMMIT")
    if expected is None:
        import subprocess
        expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    authority = module.CheckoutImportAuthority(
        target_root=root,
        expected_commit=expected,
        package_name="trading_bot",
        critical_modules=(
            "trading_bot.research.arc02.arc02_authority",
            "trading_bot.research.arc02.arc02_normalize",
            "trading_bot.research.arc02.arc02_pit",
        ),
    )
    evidence = authority.assert_authority()
    os.environ["ARC02_TARGET_ROOT"] = str(root)
    os.environ["ARC02_EXPECTED_COMMIT"] = expected
    return evidence


__all__ = ["bootstrap_arc02"]
