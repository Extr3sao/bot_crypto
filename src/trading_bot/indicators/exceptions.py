"""Custom exception hierarchy for the indicators engine (TSK-200, Fase 2).

Per docs/specs/TSK-200-indicators-interface/03-specify.md section 7 and
05-tasks.md F1 step 1.4.

Four classes, all rooted at ``IndicatorError``:

- ``IndicatorError``: base for every engine-specific error.
- ``RegistryFrozenError``: raised when ``register()`` is called after
  ``freeze()`` on the ``IndicatorRegistry``.
- ``InsufficientHistoryError``: raised when ``len(ohlcv) < required``
  for an indicator.  Exposes ``.required`` and ``.got`` attributes.
- ``ParamsHashError``: raised when ``params`` is not
  JSON-serializable; wraps the ``json.dumps`` ``TypeError`` defensively
  (CL-4).

``IndicatorError`` extends :class:`Exception` (NOT :class:`BaseException`)
so the contract ``except IndicatorError:`` does NOT silently absorb
``KeyboardInterrupt`` / ``SystemExit``.  Mirrors the ``ScannerError``
convention of the scanner package.
ADR-0013-Fase2 is the architecture-record anchor for this hierarchy.
"""

from __future__ import annotations


class IndicatorError(Exception):
    """Base for every engine-specific error in the indicators package.

    Extends :class:`Exception` (NOT :class:`BaseException`) so that
    ``KeyboardInterrupt`` / ``SystemExit`` are not silently absorbed
    by ``except IndicatorError:`` blocks.  Mirrors the
    ``ScannerError`` convention of the scanner package.
    """


class RegistryFrozenError(IndicatorError):
    """Raised when ``register()`` is called after ``freeze()`` on the
    ``IndicatorRegistry``.

    The catalog of indicators is treated as immutable after app boot
    (per ADR-0013-Fase2 / F3 contract in
    ``docs/specs/TSK-200-indicators-interface/03-specify.md`` section 4).
    Any runtime modification requires a process restart; this error
    surfaces that policy so a misconfigured caller fails loudly
    rather than mutating registry state behind the orchestrator's
    back.  The caller formats the message (e.g. with the offending
    indicator name) before raising.
    """


class InsufficientHistoryError(IndicatorError):
    """Raised when ``len(ohlcv) < required`` for an indicator.

    Attributes:
        required: minimum number of candles the indicator needs to
            produce a value (e.g. ``period`` for an EMA, or the
            ``require_min_candles`` global threshold for live mode).
        got: number of candles actually provided.

    The orchestrator (Fase 4) maps this exception to the structured
    log line ``indicator.insufficient_history { name, required, got }``
    (see ``03-specify.md`` seccion 9), so these two attributes are
    part of the public contract and must remain stable across
    refactors.
    """

    def __init__(self, required: int, got: int) -> None:
        self.required = required
        self.got = got
        super().__init__(f"insufficient_history: required {required} velas, got {got}")


class ParamsHashError(IndicatorError):
    """Raised when ``params`` is not JSON-serializable.

    Wraps the :class:`TypeError` raised by ``json.dumps`` inside
    ``compute_params_hash`` so the indicator engine surfaces its own
    domain error rather than leaking stdlib type names.  Triggered
    by values such as ``lambda: x``, ``set([...])``,
    ``Decimal('1.5')``, etc. that pass the ``Mapping`` structural
    contract but fail JSON serialization.  See CL-4 in
    ``02-bdd.md`` for the upstream scenario.
    """


__all__ = [
    "IndicatorError",
    "InsufficientHistoryError",
    "ParamsHashError",
    "RegistryFrozenError",
]
