"""Tests for src/trading_bot/scanner/exceptions.py.

Estrategia: re-pin el SIGINT-safety contract que TSK-013.1 round-3
drop'd (via removed test_exceptions_inherit_scanner_error forzado
por la regla 8/8 DoD F1 pin). TSK-013.2 restaura el sentinel via
runtime _freeze_hierarchy() + 5 tests explicitos: 1 cheap parent-
class re-pin + 2 MRO SIGINT-safety fence + 2 runtime
_freeze_hierarchy idempotence + violation path.

Cobertura esperada: 5 tests verde en este archivo.
"""

from __future__ import annotations

import pytest

from trading_bot.scanner.exceptions import (
    ScannerError,
    ScannerHierarchyInvariantError,
    _freeze_hierarchy,
)


def test_scanner_error_is_subclass_of_exception() -> None:
    """Pinea que ScannerError extiende Exception (no BaseException
    directo), preservando la filosofia del modulo."""
    assert issubclass(ScannerError, Exception)


def test_scanner_error_mro_excludes_keyboard_interrupt() -> None:
    """SIGINT-safety fence: MRO of ScannerError must NOT include
    KeyboardInterrupt as an ancestor. issubclass catches transitive
    inheritance; this confirms nobody in ScannerError's class chain
    reaches KeyboardInterrupt.

    Rationale: Python's exception hierarchy is a flow-control
    channel. KeyboardInterrupt extends BaseException directly; its
    only interceptor should be the user (Ctrl-C). Any other class
    inheriting from it silently swallows SIGINT across all except
    cascades in the bot loop, defeating manual killswitches and
    graceful shutdowns (asyncio.CancelledError-adjacent).
    """
    assert not issubclass(ScannerError, KeyboardInterrupt)


def test_scanner_error_mro_excludes_system_exit() -> None:
    """SIGINT-safety fence: MRO of ScannerError must NOT include
    SystemExit as an ancestor. issubclass catches transitive
    inheritance; this confirms nobody in ScannerError's class chain
    reaches SystemExit.

    Rationale: SystemExit extends BaseException directly; it's the
    interpreter-shutdown signal. Any other class inheriting from it
    swallows sys.exit() calls and garbage-collection finalization
    attempts, breaking clean run exits.
    """
    assert not issubclass(ScannerError, SystemExit)


def test_freeze_hierarchy_idempotent_on_clean_state() -> None:
    """Re-llamar _freeze_hierarchy con la cadena canonica limpia NO
    debe raise (idempotente; el modulo ya la llamo al import-time).

    English rationale: The module-level call at the bottom of
    exceptions.py already proved the invariant holds on the real
    ScannerError (else the import would have failed). This test
    confirms that re-calling with the SAME args is a no-op.
    """
    _freeze_hierarchy(ScannerError, (KeyboardInterrupt, SystemExit))
    # No raise expected; passes if invariant is satisfied.


def test_freeze_hierarchy_raises_on_violation() -> None:
    """Una regresion que meta una clase bajo KeyboardInterrupt debe
    fallar via ScannerHierarchyInvariantError -- NO AssertionError
    (los asserts pelados se eliminan bajo python -O; las excepciones
    custom sobreviven, conforme house-style de TSK-101).

    Strategy: synthetic subclass of KeyboardInterrupt (NOT
    ScannerError!) to verify the detection logic. The real
    ScannerError chain is untouched. Synthetic class declared without
    leading underscore per Python convention (underscore-prefixed
    names are reserved for module privacy, not test-local classes).
    """

    class FakeBadSubclass(KeyboardInterrupt):
        """Synthetic class used ONLY here to verify violation
        detection. Real ScannerError's MRO does NOT include
        KeyboardInterrupt (sentinel pineado por
        test_scanner_error_mro_excludes_keyboard_interrupt).
        """

    with pytest.raises(ScannerHierarchyInvariantError) as exc_info:
        _freeze_hierarchy(FakeBadSubclass, (KeyboardInterrupt,))
    # Mensaje debe identificar ambas clases para diagnosticar la
    # regresion sin necesidad de trazar el codigo.
    assert "FakeBadSubclass" in str(exc_info.value)
    assert "KeyboardInterrupt" in str(exc_info.value)
