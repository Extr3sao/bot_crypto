"""The formatter exemption list must stay identical to the certified pin set.

`pyproject.toml` excludes 24 files from `ruff format` because committed
certification records pin their exact bytes (WP-003-07). That exclusion is the
only hole in the format gate, so it is guarded by `scripts/verify_format_exemptions.py`
and this test runs that guard inside the ordinary suite: an exemption added for
convenience, a path widened to a glob, or a lint exclusion quietly matching the same
files all fail here instead of being discovered months later.

The guard itself is mutation-tested with `--self-test`; the second test below keeps a
cheap in-process control so the suite notices even if the script's self-test is skipped.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "verify_format_exemptions.py"


def _guard() -> Any:
    """Load the guard script as a module without adding `scripts/` to sys.path."""
    spec = importlib.util.spec_from_file_location("verify_format_exemptions", GUARD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules, so the module has
    # to be registered before its body executes.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def test_formatter_exemptions_equal_the_certified_pin_set() -> None:
    """Every guard check passes on the committed configuration."""
    guard = _guard()
    checks = guard.measure(REPO, guard.DEFAULT_BASE)
    failed = [f"{check.name}: {check.detail}" for check in checks if not check.ok]
    assert not failed, "formatter exemptions drifted from the certified pins:\n  " + "\n  ".join(
        failed
    )


def test_guard_rejects_a_configuration_that_hides_more_files() -> None:
    """A single-path exemption widened to a glob must not be accepted."""
    guard = _guard()
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    configured = guard.formatter_exclude(guard.parse_toml(text))
    assert configured, "the configuration declares no exemptions; this control is meaningless"
    declared = guard.declared_exemptions(REPO / guard.DEFAULT_DECLARATION)
    globbed = guard.parse_toml(text.replace(f'"{configured[0]}"', '"scripts/*.py"', 1))
    assert not guard.check_entries_are_exact_files(globbed, REPO, declared).ok
    assert guard.check_entries_are_exact_files(guard.parse_toml(text), REPO, declared).ok
