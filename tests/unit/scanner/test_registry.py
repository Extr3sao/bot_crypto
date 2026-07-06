"""Tests unitarios para ``src/trading_bot/scanner/registry.py``.

Estrategia: tests deterministas sin fixtures costosos; pinning
contractual de registro ordenable + freeze() opt-in. La composicion
detallada esta cubierta end-to-end por
``tests/unit/scanner/test_filters.py`` y (cuando se implemente F4) por
``tests/unit/scanner/test_universe_scanner.py``.

Cobertura esperada per DoD F2: 5 sentinels verde.
"""

from __future__ import annotations

from typing import cast

import pytest

from trading_bot.scanner.protocols import MarketDataSourceProtocol
from trading_bot.scanner.registry import FilterRegistry
from trading_bot.scanner.types import FilterOutcome

# ---------------------------------------------------------------------------
# Fakes: stubs que satisfacen el Protocol estructural ``Filter``.
# No necesitan herencia porque el Protocol es structural.
# ---------------------------------------------------------------------------


class _StubFilter:
    """Stub minimo que satisface ``Filter`` Protocol estructuralmente.

    Cambios TSK-013 round-2 (mypy --strict cleanup):

    - ``name`` es atributo de **instancia** (NO ClassVar) con default
      ``"stub"`` para alinearse con ``Filter.name: str`` declarado en
      el Protocol. Sin esto, mypy --strict rechaza el assignability
      ``_StubFilter -> Filter`` porque class-attribute defaults no
      satisfacen instance-attribute shape del Protocol.
    - ``apply(source: MarketDataSourceProtocol)``: la firma stub debe
      conformar exactamente con la del Protocol. La version previa
      usaba ``source: object`` (mas permisivo) pero mypy strict trata
      la firma como invariante para satisfaccion estructural.
    - El access a ``marker`` desde iteraciones del registry se hace
      via ``cast(_StubFilter, f).marker`` (Filter no declara ``marker``).
    """

    name: str = "stub"  # instance attribute default (NO ClassVar).
    marker: str  # valor opaque para identificar instancias en tests.

    def __init__(self, marker: str) -> None:
        self.marker = marker

    async def apply(self, symbol: str, source: MarketDataSourceProtocol) -> FilterOutcome:
        return FilterOutcome(passed=True, reason=None)


# ---------------------------------------------------------------------------
# Registry invariants: composicion ordenable.
# ---------------------------------------------------------------------------


def test_register_success_and_order_preserved() -> None:
    """3 filtros registrados en orden; ``all()`` los devuelve en ese orden."""
    registry = FilterRegistry()
    f1 = _StubFilter(marker="1")
    f2 = _StubFilter(marker="2")
    f3 = _StubFilter(marker="3")
    registry.register("alpha", f1)
    registry.register("beta", f2)
    registry.register("gamma", f3)
    all_filters = registry.all()
    # cast(_StubFilter, f): ``Filter`` Protocol no declara ``marker``;
    # access per-instance identifier via cast desde la iteracion del
    # registry (que devuelve ``list[Filter]``).
    assert [cast(_StubFilter, f).marker for f in all_filters] == ["1", "2", "3"]
    assert registry.names() == ["alpha", "beta", "gamma"]
    assert len(registry) == 3


def test_register_duplicate_raises_value_error() -> None:
    """Registrar el mismo nombre dos veces -> ``ValueError`` (no KeyError)."""
    registry = FilterRegistry()
    stub = _StubFilter(marker="dup-test")
    registry.register("vol", stub)
    dup = _StubFilter(marker="dup-test-2")
    with pytest.raises(ValueError, match=r"vol"):
        registry.register("vol", dup)


# ---------------------------------------------------------------------------
# Registry lookups: ``__contains__`` y ``get``.
# ---------------------------------------------------------------------------


def test_contains_returns_bool_for_registered_and_unknown() -> None:
    """``__contains__`` distingue presente/ausente sin levantar."""
    registry = FilterRegistry()
    registry.register("x", _StubFilter(marker="X"))
    assert "x" in registry
    assert "y" not in registry
    # Lookup tipo-degenerado NO debe levantar (defensivo). Sin
    # ``# type: ignore``: ``__contains__(name: object)`` acepta int;
    # el ignore previo era stale y mypy --strict lo reportaba como
    # [unused-ignore].
    assert (42) not in registry


def test_get_returns_filter_or_none_for_unknown_name() -> None:
    """``get`` devuelve el filter o ``None`` (lookup no-pinea)."""
    registry = FilterRegistry()
    stub = _StubFilter(marker="V")
    registry.register("v", stub)
    # cast: ``registry.get`` devuelve ``Filter | None`` y ``is`` contra
    # ``_StubFilter`` dispara [comparison-overlap] (tipos disjuntos).
    # El cast anota el LHS como ``_StubFilter`` para que la comparacion
    # de identidad sea tipicamente valida.
    assert cast(_StubFilter, registry.get("v")) is stub
    assert registry.get("missing") is None


# ---------------------------------------------------------------------------
# Freeze opt-in: bot TSK-103.4 marca el registry como inmutable.
# ---------------------------------------------------------------------------


def test_freeze_blocks_subsequent_register_raises_runtime_error() -> None:
    """Tras ``freeze()``, ``register`` levanta ``RuntimeError`` (no ValueError).

    Distincion importante: ``ValueError`` = duplicado semantico
    (programacion defensiva); ``RuntimeError`` = uso post-freeze
    (error de orquestador que intenta mutar). Type contract va a
    tests.
    """
    registry = FilterRegistry()
    registry.register("a", _StubFilter(marker="A"))
    registry.freeze()
    assert registry.is_frozen is True
    with pytest.raises(RuntimeError, match=r"freeze"):
        registry.register("b", _StubFilter(marker="B"))


def test_freeze_is_idempotent_and_does_not_corrupt_state() -> None:
    """Multiples ``freeze()`` no alteran la composicion ni el orden."""
    registry = FilterRegistry()
    registry.register("p", _StubFilter(marker="P"))
    registry.freeze()
    registry.freeze()  # idempotente
    registry.freeze()
    assert registry.is_frozen is True
    assert len(registry) == 1
    assert registry.names() == ["p"]
