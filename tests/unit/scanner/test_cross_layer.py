"""Cross-layer enforcement for the scanner package (TSK-103.4.9).

Parsea el AST de cada modulo dentro de ``src/trading_bot/scanner/`` y
falla el test si el scanner importa directa o indirectamente de las
capas prohibidas: ``exchange.*``, ``execution.*``, ``strategies.*``,
``risk.*``, ``portfolio.*``, ``indicators.*``, ``paper.*``,
``observability.*``.

Regla arquitectonica pineada en ``docs/architecture.md`` §11 + §14.
Sin librerias externas (no ``astroid``); usa ``ast`` directo de la
stdlib para mantener la base de tests ligera.

Excepciones intencionales (no son violaciones):
- ``scanner/protocols.py`` importa ``OHLCV`` de ``market_data`` (permitido).
- ``scanner/scanner.py`` importa ``Settings`` y ``TradingMode`` de
  ``config`` (permitido).
- ``scanner/filters.py`` importa ``OHLCV`` de ``market_data`` (permitido).
- Todo ``import`` dentro de un TYPE_CHECKING block se ignora (mypy
  only) per ADR-0008 style.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCANNER_PKG = Path("src/trading_bot/scanner")

# Capas prohibidas (cross-layer enforcement per ``docs/architecture.md``).
FORBIDDEN_LAYERS: frozenset[str] = frozenset(
    {
        "trading_bot.exchange",
        "trading_bot.execution",
        "trading_bot.strategies",
        "trading_bot.risk",
        "trading_bot.portfolio",
        "trading_bot.indicators",
        "trading_bot.paper",
        "trading_bot.observability",
    }
)

ALLOWED_LAYERS: frozenset[str] = frozenset(
    {
        "trading_bot.scanner",  # intra-package (self-referential).
        "trading_bot.market_data",  # types only (OHLCV).
        "trading_bot.config",  # Settings universe runtime typing.
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
                # `hasattr` is not a mypy --strict type-guard on
                # `AST.lineno`; use getattr + isinstance instead.
                child_lineno = getattr(child, "lineno", None)
                if isinstance(child_lineno, int):
                    type_checking_lines.add(child_lineno)

    imports: list[str] = []
    for node in ast.walk(tree):
        # Outer: 0 (root Module.lineno); inner: None+isinstance. Same fix in tests/bdd/conftest.py::_when_inspect_imports.
        if getattr(node, "lineno", 0) in type_checking_lines:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # ``from X import ...``  ->  X es el modulo.
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


def _all_scanner_sources() -> list[Path]:
    """Devuelve todos los ``*.py`` del paquete scanner (incl. __init__.py)."""
    if not SCANNER_PKG.exists():
        pytest.fail(f"Scanner pkg not found at {SCANNER_PKG.resolve()}")
    return sorted(SCANNER_PKG.glob("*.py"))


@pytest.mark.parametrize("path", _all_scanner_sources(), ids=lambda p: p.name)
def test_scanner_module_does_not_import_forbidden_layers(path: Path) -> None:
    """TSK-103.4.9: cada modulo scanner NO importa de capas prohibidas."""
    imports = _extract_imports(path)
    violations = _violations(imports)
    assert not violations, (
        f"{path.name} importa capas prohibidas: {violations}. "
        f"Capas prohibidas per spec 12 anti-patrones: {sorted(FORBIDDEN_LAYERS)}"
    )


def test_scanner_only_imports_allowed_layers() -> None:
    """Cobertura: la union de todos los imports del paquete cae dentro
    de allowed_layers (modulos externos a trading_bot son stdlib/
    third-party como ``structlog``; permitidos)."""
    all_imports: set[str] = set()
    for path in _all_scanner_sources():
        all_imports.update(_extract_imports(path))

    cross_layer_violations = _violations(list(all_imports))
    assert not cross_layer_violations, (
        f"Cross-layer violations en scanner package: {cross_layer_violations}"
    )


def test_scanner_does_not_import_root_exchange_module() -> None:
    """Spot-check explicito: scanner nunca toca ``trading_bot.exchange``
    (la cap CCXT connector TSK-101 funciona via ``MarketDataSourceProtocol``
    abstracto en ``protocols.py``)."""
    for path in _all_scanner_sources():
        imports = _extract_imports(path)
        assert not any(
            mod == "trading_bot.exchange" or mod.startswith("trading_bot.exchange.")
            for mod in imports
        ), f"{path.name} importa exchange directo: debe ser solo via Protocol"
