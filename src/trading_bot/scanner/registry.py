"""FilterRegistry - composicion ordenable de filtros (TSK-103.2/F2).

Reglas de diseno:
- ``OrderedDict`` para preservar el orden de insercion (RF-9). El
  primer falla corto-circuita el resto (Decision de performance
  documentada en ``docs/specs/TSK-103-universe-scanner/04-plan.md``).
- Freeze opt-in via ``.freeze()``: una vez congelado, cualquier
  intento de ``.register()`` levanta ``RuntimeError`` (pineado en
  test). El orquestador (``UniverseScanner``, TSK-103.4) llama
  ``freeze()`` en su ``__init__`` antes de exponer el registry al
  scheduler para que cambios runtime NO alteren la composicion
  bajo los pies del loop.
- ``register(name, f)`` rechaza duplicados con ``ValueError`` (no
  ``TypeError`` para distinguir semantica: typo vs freeze).
- Sin imports cross-layer (solo ``trading_bot.scanner.protocols``).

ADR lock (TSK-103.2.1, ``docs/specs/TSK-103-universe-scanner/05-tasks.md``):
cambios en la forma del registry (incluida la election de freeze
opt-in vs implicito) requieren ADR firmada en ``tasks/decisions.md``.
La decision actual esta pineada por los tests
``tests/unit/scanner/test_registry.py::test_freeze_*``.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator

from trading_bot.scanner.protocols import Filter


class FilterRegistry:
    """Registro ordenable de filtros extensibles (Decision D4 del spec)."""

    def __init__(self) -> None:
        self._filters: OrderedDict[str, Filter] = OrderedDict()
        self._frozen: bool = False

    def register(self, name: str, f: Filter) -> None:
        """Registra un filtro bajo ``name``. Rechaza duplicados y freeze."""
        if self._frozen:
            raise RuntimeError(
                "FilterRegistry esta congelado; no acepta mas registros "
                "tras freeze(). Si necesitas modificar la composicion, "
                "construye un registry nuevo y congelalo de nuevo."
            )
        if name in self._filters:
            raise ValueError(
                f"Filter {name!r} ya registrado (existente: "
                f"{self._filters[name].__class__.__name__})"
            )
        self._filters[name] = f

    def freeze(self) -> None:
        """Bloquea cualquier registro adicional. Idempotente."""
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        """Estado de congelacion del registry."""
        return self._frozen

    def all(self) -> list[Filter]:
        """Devuelve la lista de filtros en orden de insercion."""
        return list(self._filters.values())

    def get(self, name: str) -> Filter | None:
        """Acceso por nombre; ``None`` si no existe (lookup no-pinea)."""
        return self._filters.get(name)

    def names(self) -> list[str]:
        """Lista de nombres registrados en orden de insercion."""
        return list(self._filters.keys())

    def __contains__(self, name: object) -> bool:
        # Acepta cualquier ``name`` (incluso no-str) para no levantar
        # en operaciones ``__contains__`` defensivas; ``__contains__``
        # es read-only y no debe propagar excepciones de tipo.
        return name in self._filters

    def __len__(self) -> int:
        return len(self._filters)

    def __iter__(self) -> Iterator[Filter]:
        """Itera sobre los filtros en orden de insercion."""
        return iter(self._filters.values())


__all__ = ["FilterRegistry"]
