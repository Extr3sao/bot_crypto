"""Filtros pre-batch y per-par (RF-2, RF-3).

Pure functions: sin I/O, sin state, solo leen ``Settings``. Cubren
dos guards pineados en 03-specify §5:

- ``check_kill_switch`` (RF-3): pre-batch guard. Si el kill_switch
  esta activo retornamos ``"skip_kill_switch"`` ANTES de cualquier
  I/O.

- ``check_active_hours`` (RF-2): per-par guard. Wrap-around
  soportado: ventana que cruza medianoche (e.g. ``22:00..06:00``)
  incluye ``minute >= start OR minute < end``.

Sobre la diferencia entre spec y cod: 03-specify §5 asume un
``Scheduler`` con campos ``active_hours_start: int`` y
``active_hours_end: int`` planos; el modelo real
``SchedulerActiveHours`` (TSK-099) usa strings ``HH:MM``. Esta
implementacion parsea ``"HH:MM"`` a ``minute_of_day`` (0..1439) para
mantener la firma del spec a nivel de minuto. La resolution
completa (modelo plano int vs HH:MM nested) queda pinned como
drift deferido a F4 wiring + ADR-0014 (aqui pineamos parseo en el
boundary; el resto del scheduler consume ``evaluate_cache_hit`` con
ms ints puros sin tocar el Settings).

Sobre ``PreBatchDecision``: la Literal documentada en 03-specify §5
era 3-valores (``continue``, ``skip_kill_switch``,
``skip_empty_universe``) pero ``check_active_hours`` realmente
retorna ``"skip_active_hours"`` (per-par skip). Ampliamos a 4
valores en F2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trading_bot.config.settings import Settings

# Cuatro valores: dos pre-batch (skip_kill_switch, skip_empty_universe)
# + uno per-par (skip_active_hours) + continue default.
PreBatchDecision = Literal[
    "continue",
    "skip_kill_switch",
    "skip_empty_universe",
    "skip_active_hours",
]


@dataclass(frozen=True, slots=True)
class ActiveHoursWindow:
    """Ventana activa en ``minute_of_day`` (0..1439).

    Pine contract:
    - ``start_minute`` y ``end_minute`` en ``[0..1439]``.
    - ``start_minute == end_minute`` ventana vacia (cortocircuito):
      siempre ``skip_active_hours``.
    - ``start_minute < end_minute`` ventana normal: minutos que
      cumplen ``start <= minute < end``.
    - ``start_minute > end_minute`` ventana wrap-around: minutos que
      cumplen ``minute >= start OR minute < end``.
    """

    start_minute: int  # 0..1439 inclusive
    end_minute: int  # 0..1439


def parse_hhmm_to_minute(s: str) -> int:
    """Parse ``"HH:MM"`` -> minute of day ``0..1439``.

    Pine contract: el input ya viene validado por el pattern
    ``^([01]\\d|2[0-3]):[0-5]\\d$`` en ``SchedulerActiveHours``;
    aqui solo queremos unmarshalling determinista + un error
    legible si algo se cuela (defensivo, no deberia dispararse en
    flujo normal).

    Args:
        s: cadena ``"HH:MM"`` (formato 24h).

    Returns:
        ``h * 60 + m`` en ``[0..1439]``.

    Raises:
        ValueError: si el formato no es valido (defensivo).
    """
    if not isinstance(s, str):
        raise ValueError(
            f"HH:MM must be a string (got {type(s).__name__}: {s!r}). "
            f"The pattern validator on SchedulerActiveHours ensures this "
            f"never fires from load_settings(); tests that bypass load "
            f"may trigger it."
        )
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"HH:MM must have exactly 2 colon-separated parts: {s!r}")
    # Strict 2-digit components per YAML pattern
    # ``^([01]\\d|2[0-3]):[0-5]\\d$`` (SchedulerActiveHours Field constraint).
    # Pine contract: ``"8:00"`` o ``"08:0"`` -> ValueError (no lenient parsing).
    if len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError(
            f"HH:MM components must be exactly 2 digits each (got {s!r}). "
            f"The YAML pattern enforced by SchedulerActiveHours is "
            f"``^([01]\\d|2[0-3]):[0-5]\\d$`` (HH:MM). "
            f"Zero-pad single digit hours/minutes before passing here."
        )
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError as e:
        raise ValueError(f"HH:MM non-numeric components: {s!r}: {e}") from e
    if not (0 <= h <= 23):
        raise ValueError(f"HH out of [0..23]: {s!r}")
    if not (0 <= m <= 59):
        raise ValueError(f"MM out of [0..59]: {s!r}")
    return h * 60 + m


def active_hours_window_from_settings(settings: Settings) -> ActiveHoursWindow:
    """Construye ``ActiveHoursWindow`` parseando HH:MM desde Settings.

    Pine contract:
    - Lee ``settings.runtime.scheduler.active_hours.start`` y ``.end``
      (nested ``SchedulerActiveHours`` model en TSK-099 layout,
      ADR-0010 contract).
    - Whitespace u otras inconsistencias se pinean via el pattern
      validator en el model: si llega aqui, ya es valido.
    """
    window_raw = settings.runtime.scheduler.active_hours
    return ActiveHoursWindow(
        start_minute=parse_hhmm_to_minute(window_raw.start),
        end_minute=parse_hhmm_to_minute(window_raw.end),
    )


def check_kill_switch(settings: Settings) -> PreBatchDecision:
    """Pre-batch guard (RF-3).

    Pine contract:
    - Lee ``settings.risk.kill_switch_enabled`` (ADR-0010 layout).
    - Retorna ``"skip_kill_switch"`` si el flag esta activo,
      ANTES de cualquier I/O.
    - El orchestrator (``OHLCVScheduler._execute_iteration``) captura
      este return y emite log estructurado
      ``scheduler.paused.kill_switch`` una vez por iteracion
      abortada, luego retorna ``SchedulerResult(pulls_attempted=0)``
      con ``early_exit="kill_switch"``.
    """
    if settings.risk.kill_switch_enabled:
        return "skip_kill_switch"
    return "continue"


def check_active_hours(settings: Settings, now: datetime) -> PreBatchDecision:
    """Per-par guard (RF-2).

    Pine contract:
    - Parsea HH:MM con ``parse_hhmm_to_minute``.
    - Compara ``now`` como ``minute_of_day`` entero en
      ``[0..1439]``.
    - Ventana vacia ``start == end``: siempre ``skip_active_hours``.
    - Ventana normal ``start < end``: ``start <= minute < end``
      (inclusive start, exclusive end).
    - Ventana wrap-around ``start > end``: ``minute >= start OR
      minute < end``.
    - Por par, NO pre-batch global: el orchestrator llama a esta
      funcion dentro del loop ``for pair in enabled_pairs``.
    """
    window = active_hours_window_from_settings(settings)
    now_minute = now.hour * 60 + now.minute
    if window.start_minute == window.end_minute:
        # Window vacia: cortocircuito determinista.
        return "skip_active_hours"
    if window.start_minute < window.end_minute:
        in_window = window.start_minute <= now_minute < window.end_minute
    else:
        in_window = now_minute >= window.start_minute or now_minute < window.end_minute
    return "continue" if in_window else "skip_active_hours"


__all__ = [
    "ActiveHoursWindow",
    "PreBatchDecision",
    "active_hours_window_from_settings",
    "check_active_hours",
    "check_kill_switch",
    "parse_hhmm_to_minute",
]
