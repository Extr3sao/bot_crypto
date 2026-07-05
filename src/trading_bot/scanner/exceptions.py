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


__all__ = ["ConfigurationError", "KillSwitchActiveError", "ScannerError"]
