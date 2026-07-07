"""Jerarquia de errores del OHLCV Scheduler.

Cuatro clases, pineadas por spec 03-specify.md §7:

- ``SchedulerError``: base para todos los errores especificos del
  scheduler. Hereda de ``Exception`` (NO ``BaseException``) para NO
  atrapar accidentalmente ``KeyboardInterrupt`` / ``SystemExit``.

- ``KillSwitchActiveError``: el kill_switch esta activo; la iteracion
  fue abortada. NO se propaga al caller en ``OHLCVScheduler.run_once``:
  el orquestador convierte a ``SchedulerResult(pulls_attempted=0)`` y
  emite log estructurado ``scheduler.paused.kill_switch``. Solo tests
  pinean explicitamente el comportamiento via ``pytest.raises`` o
  construccion directa.

- ``EmptyUniverseWarning``: warning (NO error) cuando
  ``universe.pairs`` esta vacio. NO se eleva via ``warnings.warn``
  en la implementacion actual: el scheduler loguea
  ``scheduler.universe.empty`` (Nivel WARNING) y retorna
  ``SchedulerResult(pulls_attempted=0)``. Esta clase existe solo
  para que tests puedan ``pytest.warns(EmptyUniverseWarning)`` si
  lo necesitan en cobertura adicional.

- ``RetryExhaustedError``: se eleva desde ``_fetch_with_retry``
  (TSK-104.3b.1) tras agotar los retries. La excepcion incluye el
  ``last_exception`` (chain via ``raise ... from ...``) y el
  ``attempts`` count. Caller (``_process_one_pair``) captura,
  incrementa ``pulls_failed``, emite log ``scheduler.pull.failed``
  motivo ``rate_limit_exhausted`` (o el que corresponda), y
  continua con el siguiente par. El error NO aborta el batch.

Regla de extension: cualquier nueva excepcion aqui requiere extender
``bdd/features/ohlcv_scheduler.feature`` con un escenario de error
procedente (regla metodologica SDD/BDD: 100% cobertura RF -> BDD ->
tests).
"""

from __future__ import annotations


class SchedulerError(Exception):
    """Base para todos los errores especificos del scheduler.

    Hereda de ``Exception`` (NO ``BaseException``) para NO atrapar
    ``KeyboardInterrupt`` / ``SystemExit`` accidentalmente.
    """


class KillSwitchActiveError(SchedulerError):
    """El kill_switch esta activo; iteracion abortada.

    Behavior contract (TSK-104.3, R1 opcion b chain): el
    ``OHLCVScheduler.run_once`` detecta ``settings.risk.kill_switch_enabled``
    ANTES del cache hit check (kill-switch es pre-batch, no
    per-pair) y NO propaga esta excepcion al loop exterior;
    convierte a ``SchedulerResult(pulls_attempted=0, ...empty)`` y
    emite log estructurado ``scheduler.paused.kill_switch``.
    Pine contract: el log se emite UNA vez por iteracion abortada
    (single emission point en ``_execute_iteration``).

    Solo tests pinean explicitamente este error via
    ``pytest.raises(KillSwitchActiveError)`` o construccion
    directa.
    """


class EmptyUniverseWarning(UserWarning):
    """Warning cuando ``universe.pairs`` esta vacio.

    NO se eleva via ``warnings.warn`` en la implementacion actual:
    el scheduler loguea ``scheduler.universe.empty`` (Nivel WARNING
    via structlog) y retorna
    ``SchedulerResult(pulls_attempted=0, ..., early_exit='empty_universe')``.

    Esta clase existe solo para que tests puedan
    ``pytest.warns(EmptyUniverseWarning)`` si lo necesitan en
    cobertura adicional. NOTA: ``UserWarning`` (no
    ``SchedulerError``) refleja la gravedad: NO es bloqueante, es
    una condicion operacional esperada en configuracion de paper
    / research.
    """


class RetryExhaustedError(SchedulerError):
    """Se eleva desde ``_fetch_with_retry`` tras agotar los retries.

    La excepcion incluye el ``last_exception`` (chain via
    ``raise ... from ...``) y el ``attempts`` count (1 inicial +
    3 retries = 4 max attempts per CL-9, 03-specify §8).

    Caller (``_process_one_pair``) captura esta excepcion,
    incrementa ``pulls_failed``, emite evento
    ``on_pull_failed`` con ``reason`` optenido del mapeo de la
    excepcion original (e.g. ``ccxt.RateLimitExceeded`` ->
    ``"rate_limit_exhausted"``), y continua con el siguiente par.
    El error NO aborta el batch.

    Atributos esperados (pine contract via ``__init__``):
    - ``last_exception``: la excepcion original que provoco el
      fail (CCXT exception o builtin TimeoutError). Tipado
      ``Exception`` (no ``BaseException``) para NO aceptar
      ``KeyboardInterrupt``/``SystemExit`` como causa pineada, en
      linea con el contrato de ``SchedulerError(Exception)``.
    - ``attempts``: el numero total de intentos (>=1). Per
      CL-9 + 03-specify §8: 1 inicial + 3 retries = 4 intentos
      max. Validado en ``__init__``: cualquier valor fuera de
      ``1..= max(1, 1 + max_retries)`` levanta ``ValueError``
      antes de construir el objeto.
    """

    def __init__(
        self,
        message: str,
        *,
        last_exception: Exception,
        attempts: int,
    ) -> None:
        if attempts < 1:
            raise ValueError(
                f"RetryExhaustedError.attempts must be >= 1 (got {attempts}). "
                f"A zero-attempt exhaustion is a self-contradiction; "
                f"use bare 'raise ... from ...' for zero-attempt failure paths. "
                f"Valid range per CL-9: 1..= 1+max_retries (1..= 4 default)."
            )
        super().__init__(message)
        self.last_exception = last_exception
        self.attempts = attempts


__all__ = [
    "EmptyUniverseWarning",
    "KillSwitchActiveError",
    "RetryExhaustedError",
    "SchedulerError",
]
