"""Jerarquia de errores del scanner.

Tres clases, jerarquizadas sobre ``ScannerError``:

- ``KillSwitchActiveError``: kill_switch activo produjo una iteracion
  abortada. NO se propaga al caller en ``run()``: el orquestador
  convierte a ``[]`` y emite log estructurado. Solo se usa en tests
  que pinean explicitamente el comportamiento de abort.

- ``ConfigurationError``: la configuracion invalida (e.g.
  ``settings=None`` en constructor, ``universe.pairs`` vacio en modo
  ``live``). El orquestador ``UniverseScanner`` la propaga al caller
  porque indica un error de setup que NO debe ser silenciado.

``ScannerError`` extiende ``Exception`` (no ``BaseException``) para
NO atrapar accidentalmente ``KeyboardInterrupt`` / ``SystemExit``.

Regla de extension: cualquier nueva excepcion aqui requiere
extender ``bdd/features/market_scanner.feature`` con un escenario
de error precedente (regla metodologica SDD/BDD: 100% cobertura RF ->
BDD -> tests).

IMPORT-TIME FAIL-LOUD ENFORCEMENT (TSK-013.2, SIGINT-safety):
este modulo enforces contractualmente que el MRO de ScannerError
NO contiene (KeyboardInterrupt, SystemExit) como ancestors --
la regresion seria un kill-switch hazard. Enforcement via
_freeze_hierarchy(ScannerError, (KeyboardInterrupt, SystemExit))
al final del modulo; raises ScannerHierarchyInvariantError
(RuntimeError subclass, NO bare assert para sobrevivir
python -O) en violation. Equivalente runtime del static
class X(Exception) declaration, pero fail-loud ante
monkeypatch o shadowing.
"""

from __future__ import annotations


class ScannerError(Exception):
    """Base para todos los errores especificos del scanner.

    Hereda de ``Exception`` (no ``BaseException``) para NO atrapar
    ``KeyboardInterrupt`` / ``SystemExit`` accidentalmente.
    """


class KillSwitchActiveError(ScannerError):
    """El kill_switch esta activo; iteracion abortada.

    Behavior contract (TSK-103.4 RF-4): ``UniverseScanner.run()``
    detecta el kill_switch ANTES del loop y NO propaga esta excepcion
    al scheduler; convierte a ``list[MarketSnapshot] = []`` y emite
    log estructurado ``scanner.paused.kill_switch``. Solo tests
    pinean explicitamente este error via ``pytest.raises`` o
    construccion directa.
    """


class ConfigurationError(ScannerError):
    """La configuracion del scanner es invalida.

    Casos tipicos (TSK-103.4):
    - ``settings=None`` en constructor.
    - ``universe.pairs`` vacio en modo ``live`` (paper acepta vacio).
    - Filtros con valores contradictorios en config YAML (e.g.
      ``min_atr_percent > max_atr_percent``).
    - ``runtime.mode`` desconocido (no en {research, backtest, paper,
      live}).

    Esta excepcion SI se propaga al caller: indica un error de
    setup que deberia aparecer en logs y bloquear el arranque,
    no quedar silenciado por el loop defensivo del orquestador.
    """


# ---------------------------------------------------------------------------
# Hierarchy freeze (SIGINT-safety). TSK-013.2 follow-up to TSK-013.1 round-3
# (commit d831345 on feature/tsk-013-1-mypy-strict-test-types deferred coverage
# of ScannerError MRO containing (KeyboardInterrupt, SystemExit) to this
# ticket; see commit body of d831345 Coverage deferral section).
# ---------------------------------------------------------------------------


class ScannerHierarchyInvariantError(RuntimeError):
    """Raised by _freeze_hierarchy on hierarchy violation.

    Sentinel explicito: el scanner pin-a contractualmente que el MRO
    de ScannerError NO contiene (KeyboardInterrupt, SystemExit)
    como ancestors. Una regresion seria un kill-switch hazard para
    cualquier loop except ScannerError en el bot loop principal
    o en tareas asincronicas asyncio.CancelledError-adjacent.

    Subclass of RuntimeError (NOT bare assert) per house-style
    established in TSK-101 (UnmappedOrderStatusError(RuntimeError)
    precedent): bare assert se elimina bajo python -O, lo que
    silenciosamente dejaria pasar la regresion en produccion. Custom
    exception sobrevive python -O y surfaces al import-time de
    trading_bot.scanner.exceptions.
    """


def _freeze_hierarchy(
    cls: type[BaseException],
    forbidden_bases: tuple[type[BaseException], ...],
) -> None:
    """Pin the SIGINT-safety invariant: cls MRO must NOT include
    any member of forbidden_bases as ancestor.

    Rationale (English): Python's exception hierarchy is a flow-control
    channel. KeyboardInterrupt and SystemExit extend BaseException
    directly; their only interceptor should be the user (Ctrl-C) and
    the interpreter shutdown. Any class that ALSO inherits from these
    types is unsafe in except cascades because it silently swallows
    SIGINT across the bot loop, defeating manual killswitches and
    graceful shutdowns.

    Called once at module-load with the canonical
    (ScannerError, (KeyboardInterrupt, SystemExit)) to enforce
    SIGINT-safety. Raises ScannerHierarchyInvariantError on
    violation. The function takes cls + forbidden_bases as
    parameters so tests can verify the violation path on synthetic
    subclasses WITHOUT actually breaking the real chain.
    """
    for base in forbidden_bases:
        if issubclass(cls, base):
            raise ScannerHierarchyInvariantError(
                f"{cls.__name__} inherits from {base.__name__}; "
                f"this leaks into the related `except {cls.__name__}` flow "
                f"and would silently swallow SIGINT/{base.__name__}."
            )


# Module-level freeze on import: a regression breaks the import.
_freeze_hierarchy(ScannerError, (KeyboardInterrupt, SystemExit))


__all__ = [
    "ConfigurationError",
    "KillSwitchActiveError",
    "ScannerError",
    "ScannerHierarchyInvariantError",
]
