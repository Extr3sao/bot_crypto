"""V3 fail-closed pytest authority guard for this checkout.

Work order §12: before collecting critical ARC-02 tests, prove
``trading_bot.__file__`` is within the target; if wrong, pytest exits nonzero
BEFORE evidence-producing tests execute. The guard also re-verifies loaded
first-party modules during collection (RC-4).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# Establish target precedence, then prove it (never trust ordering alone).
if str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

_helper = SRC / "trading_bot" / "research" / "import_authority.py"
_spec = importlib.util.spec_from_file_location("_pytest_checkout_import_authority", _helper)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"missing import authority contract: {_helper}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def _expected_commit() -> str:
    env = os.environ.get("ARC02_EXPECTED_COMMIT")
    if env:
        return env
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
    ).strip()


_expected = _expected_commit()
CRITICAL_MODULES = (
    "trading_bot.research.arc02.arc02_authority",
    "trading_bot.research.arc02.arc02_normalize",
    "trading_bot.research.arc02.arc02_pit",
)

try:
    _authority = _module.CheckoutImportAuthority(
        target_root=ROOT,
        expected_commit=_expected,
        package_name="trading_bot",
        critical_modules=CRITICAL_MODULES,
    )
    # RC-2: this raises if a wrong trading_bot was already imported.
    _removed = _authority.prepare()
    # §15: commit identity matters — a wrong checkout must never pass.
    _authority.verify_commit_identity()
    import trading_bot  # noqa: E402  (must now resolve inside ROOT/src)

    _pkg_file = getattr(trading_bot, "__file__", None)
    if _pkg_file is None or not _module.within(_pkg_file, SRC):
        raise _module.ImportAuthorityError(
            f"trading_bot resolves outside the audited target src: {_pkg_file}"
        )
except _module.ImportAuthorityError as _exc:
    # Fail closed BEFORE any evidence-producing test executes.
    raise SystemExit(f"PYTEST_AUTHORITY_FAIL_CLOSED: {_exc}") from _exc


def pytest_collection(session):  # noqa: ANN201
    """Re-verify authority before collection proceeds (RC-4)."""
    try:
        _authority.verify_loaded_state()
    except _module.ImportAuthorityError as exc:
        raise SystemExit(f"PYTEST_AUTHORITY_FAIL_CLOSED (collection): {exc}") from exc


def pytest_collection_modifyitems(session, config, items):  # noqa: ANN201
    """Second re-verification after collection, before any test runs."""
    try:
        _authority.verify_loaded_state()
    except _module.ImportAuthorityError as exc:
        raise SystemExit(f"PYTEST_AUTHORITY_FAIL_CLOSED (modifyitems): {exc}") from exc
