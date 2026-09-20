"""Fail-closed pytest authority guard for this checkout."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

_helper = SRC / "trading_bot" / "research" / "import_authority.py"
_spec = importlib.util.spec_from_file_location("_pytest_checkout_import_authority", _helper)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"missing import authority contract: {_helper}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
_expected = os.environ.get("ARC02_EXPECTED_COMMIT") or subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
).strip()
_module.CheckoutImportAuthority(
    target_root=ROOT,
    expected_commit=_expected,
    package_name="trading_bot",
    critical_modules=(
        "trading_bot.research.arc02.arc02_authority",
        "trading_bot.research.arc02.arc02_normalize",
        "trading_bot.research.arc02.arc02_pit",
    ),
).assert_authority()
