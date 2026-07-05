"""Indicator registry (TSK-200, F3).

Per docs/specs/TSK-200-indicators-interface/03-specify.md section 4
and 05-tasks.md F3 rows TSK-200.3.1..3.3.

``IndicatorRegistry`` is the per-process catalog of indicators
used by the orchestrator (Fase 4) when materializing strategies.
Its contract:

- ``register(name, indicator)`` — adds a new entry.  Raises
  ``ValueError`` if ``name`` is already taken; raises
  ``RegistryFrozenError`` after ``freeze()``.  Hybrid validation
  combines ``isinstance(indicator, Indicator)`` (PEP 544 structural
  contract — verifies the ``compute`` method is callable) plus a
  defensive ``isinstance(getattr(indicator, 'name', None), str)``
  check (PEP 544 does NOT verify data attributes, so this catches
  candidates that would otherwise pass ``isinstance`` but fail at
  registry lookup time with ``AttributeError``).
- ``freeze()`` — locks the registry against further ``register()``
  calls.  Idempotent per CL-7.
- ``all()`` / ``get(name)`` / ``__contains__`` / ``__len__`` —
  read-only operations work normally even after ``freeze()`` (a
  frozen registry is fully readable; only mutators raise).

NOTA: a diferencia de ``FilterRegistry`` de F2 (que NO tiene
``freeze()`` porque F4 evaluara registries per-mode sin re-registro),
el ``IndicatorRegistry`` SI tiene ``freeze()`` para pinear el
contrato de Fase 2: el catalogo de indicators se carga al arranque
de ``trading_bot.app`` desde ``IndicatorsConfig`` y NO se espera
mutacion runtime (RF-12 + ADR-0013-Fase2).  Cualquier extension
requiere un restart del process.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator

from trading_bot.indicators.exceptions import RegistryFrozenError
from trading_bot.indicators.protocols import Indicator

__all__ = ["IndicatorRegistry"]


class IndicatorRegistry:
    """Ordered, freeze-friendly registry of ``Indicator`` instances."""

    def __init__(self) -> None:
        self._indicators: OrderedDict[str, Indicator] = OrderedDict()
        self._frozen: bool = False

    def register(self, name: str, indicator: Indicator) -> None:
        """Add a new indicator under ``name``.

        Args:
            name: unique registry key (also surfaced as the
                indicator's ``.name`` attribute convention; callers
                typically pass ``name == indicator.name`` for
                consistency).
            indicator: any object satisfying the ``Indicator``
                Protocol — i.e. exposing a callable ``compute``
                method AND a ``name: str`` attribute.

        Raises:
            RegistryFrozenError: if called after ``freeze()``.
            ValueError: if ``name`` is already registered.
            TypeError: if ``indicator`` does not satisfy the
                ``Indicator`` Protocol (no callable ``compute``) OR
                is missing the ``name: str`` data attribute.  The
                dual check guards against PEP 544's silent failure
                mode where ``isinstance(obj, Indicator)`` returns
                ``True`` for candidates that lack the ``name``
                attribute but expose a callable ``compute``.

        Hybrid validation rationale (per Q1 think-with-files):
        - ``isinstance(indicator, Indicator)`` matches the
          structural ``compute`` method via PEP 544 ``runtime_checkable``.
        - PEP 544 does NOT verify ``name: str`` data attributes —
          a candidate with ``compute`` but no ``name`` slips
          through ``isinstance`` only to fail at lookup time
          (``self._indicators[bad_indicator.name]`` →
          ``AttributeError``).  We add an explicit
          ``isinstance(getattr(..., 'name', None), str)`` check so
          the registration fails loudly at the right site instead
          of silently corrupting future reads.
        """
        if self._frozen:
            raise RegistryFrozenError(f"IndicatorRegistry is frozen; cannot register {name!r}")
        if name in self._indicators:
            raise ValueError(f"name {name!r} already registered in IndicatorRegistry")
        # PEP 544 structural check: callable ``compute`` recognised.
        if not isinstance(indicator, Indicator):
            raise TypeError(
                f"indicator must satisfy Indicator Protocol; got {type(indicator).__name__}"
            )
        # PEP 544 defensive: explicit data-attribute check; runtime_checkable
        # does NOT verify ``name`` even when the Protocol declares it.
        if not isinstance(getattr(indicator, "name", None), str):
            raise TypeError(
                f"indicator missing 'name' string attribute (got "
                f"{type(getattr(indicator, 'name', None)).__name__}); "
                "Indicator Protocol requires name: str for registry lookup"
            )
        self._indicators[name] = indicator

    def freeze(self) -> None:
        """Lock the registry against further ``register()`` calls.

        Idempotent per CL-7: a second ``freeze()`` call is a no-op.
        After freeze, mutators (``register``) raise
        ``RegistryFrozenError`` while readers (``get``, ``all``,
        ``__contains__``, ``__len__``, ``is_frozen``) keep working.
        """
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        """True iff ``freeze()`` has been called."""
        return self._frozen

    def all(self) -> list[Indicator]:
        """Return all registered indicators in insertion order.

        The order matches the registration order (the underlying
        ``OrderedDict`` preserves insertion order); callers should
        NOT mutate the returned list (it is a defensive copy).
        """
        return list(self._indicators.values())

    def get(self, name: str) -> Indicator:
        """Return the indicator registered under ``name``.

        Raises:
            KeyError: if ``name`` is not in the registry.  (We use
                ``KeyError`` rather than ``IndicatorError`` because
                this is a registry lookup miss, not an indicator
                engine failure.)
        """
        if name not in self._indicators:
            raise KeyError(f"Indicator {name!r} not registered")
        return self._indicators[name]

    def __contains__(self, name: object) -> bool:
        """Return True iff ``name`` is a registered key.

        Read-only operation — works normally post-freeze (matches
        underlying ``OrderedDict`` read semantics; only mutators
        raise).
        """
        return name in self._indicators

    def __len__(self) -> int:
        """Return the number of registered indicators."""
        return len(self._indicators)

    def __iter__(self) -> Iterator[str]:
        """Iterate over registered names in insertion order.

        Mirrors the underlying ``OrderedDict`` iteration so callers
        can do ``for name in registry:`` or ``list(registry)`` and get
        the registered names (not the indicator objects).  This is
        the canonical way to assert on registration order in tests
        (e.g. BDD Scenario 6 "Orden de registro preservado en
        iteracion") without depending on the ``Indicator.name``
        attribute (which is intrinsic to the indicator class and
        independent of the key it was registered under).
        """
        return iter(self._indicators)
