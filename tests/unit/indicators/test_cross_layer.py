"""Cross-layer enforcement for the indicators package (TSK-200.4.8 / RF-11).

Parsea el AST de cada modulo dentro de ``src/trading_bot/indicators/``
y falla el test si el motor de indicators importa directa o
indirectamente de las capas prohibidas: ``strategies.*``,
``execution.*``, ``risk.*``, ``portfolio.*``, ``exchange.*``,
``scanner.*``, ``paper.*``, ``observability.*``.

Regla arquitectonica pineada en ``docs/architecture.md`` + ADR-0013-Fase2
+ spec 02-bdd.md RF-11. Sin librerias externas (no ``astroid``); usa
``ast`` directo de la stdlib para mantener la base de tests ligera,
siguiendo la convencion pineada por ``tests/unit/scanner/test_cross_layer.py``.

Excepciones intencionales (NO son violaciones):
- ``ema.py`` importa ``OHLCV`` de ``trading_bot.market_data.types`` (permitido).
- ``cache.py``, ``protocols.py``, ``registry.py``, ``types.py``,
  ``exceptions.py`` importan de ``trading_bot.indicators.*`` (intra-package).
- ``ema.py`` puede importar de ``trading_bot.indicators.{types,
  exceptions}`` (intra-package) y ``trading_bot.market_data.types``.
- Todo ``import`` dentro de un ``TYPE_CHECKING`` block se ignora
  (mypy only) per ADR-0008 style y la convencion pineada en
  ``tests/unit/scanner/test_cross_layer.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

INDICATORS_PKG = Path("src/trading_bot/indicators")

# Capas prohibidas (cross-layer enforcement per ``docs/architecture.md``
# + ADR-0013-Fase2 + 02-bdd.md RF-11).
FORBIDDEN_LAYERS: frozenset[str] = frozenset(
    {
        "trading_bot.strategies",
        "trading_bot.execution",
        "trading_bot.risk",
        "trading_bot.portfolio",
        "trading_bot.exchange",
        "trading_bot.scanner",
        "trading_bot.paper",
        "trading_bot.observability",
    }
)

ALLOWED_LAYERS: frozenset[str] = frozenset(
    {
        "trading_bot.indicators",  # intra-package (self-referential).
        "trading_bot.market_data",  # types only (OHLCV) per spec section 3.
        "trading_bot.config",  # Settings / IndicatorsConfig (F4.4 wiring).
        "trading_bot",  # top of pkg (e.g. ``from trading_bot import ...``).
    }
)


def _extract_imports(path: Path) -> list[str]:
    """Devuelve la lista de modulos importados por ``path`` (no-TYPE_CHECKING)."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))

    # Detecta TYPE_CHECKING block (mypy only) para excluir sus imports.
    type_checking_lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            for child in ast.walk(node):
                # ast.AST doesn't statically declare ``lineno`` (the
                # attribute is added by ``ast.parse`` per-node).
                # ``getattr(child, "lineno", 0)`` keeps mypy strict
                # happy without a per-node type ignore.
                type_checking_lines.add(getattr(child, "lineno", 0))

    imports: list[str] = []
    for node in ast.walk(tree):
        # ``getattr(node, 'lineno', 0)`` default 0 covers the root
        # ``Module`` node (Python 3.11 ast.parse deja ``lineno=0``
        # para el module root).
        if getattr(node, "lineno", 0) in type_checking_lines:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                # ``from . import X`` (relative); allow trivial intra-package.
                continue
            imports.append(node.module)
    return imports


def _violations(imports: list[str]) -> list[str]:
    """Filtra los imports que pegan contra un forbidden layer."""
    out: list[str] = []
    for mod in imports:
        # package-level match (X == forbidden, or X.start with forbidden.___)
        for forbidden in FORBIDDEN_LAYERS:
            if mod == forbidden or mod.startswith(forbidden + "."):
                out.append(f"{mod} <- {forbidden}")
                break
    return out


def _all_indicators_sources() -> list[Path]:
    """Devuelve todos los ``*.py`` del paquete indicators (incl. __init__.py)."""
    if not INDICATORS_PKG.exists():
        pytest.fail(f"Indicators pkg not found at {INDICATORS_PKG.resolve()}")
    return sorted(INDICATORS_PKG.glob("*.py"))


@pytest.mark.parametrize(
    "path",
    _all_indicators_sources(),
    ids=lambda p: p.name,
)
def test_indicators_module_does_not_import_forbidden_layers(path: Path) -> None:
    """TSK-200.4.8: cada modulo de indicators NO importa de capas prohibidas.

    Per 02-bdd.md RF-11 verbatim: ``Motor de indicators no importa
    strategies / execution / risk / portfolio / exchange / scanner``.
    El paquete ``indicators/`` solo conoce ``market_data.types`` (para
    ``OHLCV``) y ``config.indicators`` (para ``IndicatorsConfig``).
    """
    imports = _extract_imports(path)
    violations = _violations(imports)
    assert not violations, (
        f"{path.name} importa capas prohibidas: {violations}. "
        f"Capas prohibidas per spec 02-bdd.md RF-11: {sorted(FORBIDDEN_LAYERS)}"
    )


def test_indicators_only_imports_allowed_layers() -> None:
    """Cobertura: la union de todos los imports del paquete cae dentro de
    ``ALLOWED_LAYERS`` (modulos externos a ``trading_bot`` son stdlib /
    third-party como ``structlog``; permitidos por definicion — el
    test solo pinea los imports que SIEMPRE son intra-``trading_bot``).
    """
    all_imports: set[str] = set()
    for path in _all_indicators_sources():
        all_imports.update(_extract_imports(path))

    # Cross-layer violations: imports que pegan contra un forbidden layer.
    cross_layer_violations = _violations(list(all_imports))
    assert not cross_layer_violations, (
        f"Cross-layer violations en indicators package: {cross_layer_violations}"
    )

    # Whitelist check (prefix-match): cada import dentro de
    # ``trading_bot.*`` debe caer bajo un ALLOWED_LAYER como prefijo
    # (matching ``trading_bot.indicators.cache`` against the
    # ``trading_bot.indicators`` layer, etc.).  Sets only do exact
    # match, so THIS check needs explicit prefix logic (the
    # per-module test above uses the same prefix logic via
    # ``_violations``).
    def _is_in_allowed_prefix(mod: str) -> bool:
        return any(mod == layer or mod.startswith(layer + ".") for layer in ALLOWED_LAYERS)

    trading_bot_imports = {
        mod for mod in all_imports if mod == "trading_bot" or mod.startswith("trading_bot.")
    }
    unrecognized = sorted(mod for mod in trading_bot_imports if not _is_in_allowed_prefix(mod))
    assert not unrecognized, (
        f"Imports de trading_bot fuera de ALLOWED_LAYERS (prefix-match): {unrecognized}. "
        f"ALLOWED_LAYERS={sorted(ALLOWED_LAYERS)}"
    )


def test_indicators_does_not_import_strategies_execution_risk_exchange() -> None:
    """Spot-check explicito: ``ForbiddenLayers direct hits`` pinea las 6
    capas prohibidas mas relevantes del spec section RF-11 en un solo
    test para failure mode claro al CI.
    """
    spot_forbidden = (
        "trading_bot.strategies",
        "trading_bot.execution",
        "trading_bot.risk",
        "trading_bot.portfolio",
        "trading_bot.exchange",
        "trading_bot.scanner",
    )
    for path in _all_indicators_sources():
        imports = _extract_imports(path)
        assert not any(
            mod == forbidden or mod.startswith(forbidden + ".")
            for mod in imports
            for forbidden in spot_forbidden
        ), f"{path.name} importa una capa prohibida del spec RF-11: {imports}"
