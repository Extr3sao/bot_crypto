"""MA-0 architectural boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path

MA_ROOT = Path("src/trading_bot/multi_agent")
FORBIDDEN_PREFIXES = (
    "trading_bot.paper",
    "trading_bot.risk",
    "trading_bot.execution",
    "trading_bot.market_data",
    "trading_bot.config",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.append(node.module)
    return result


def test_contract_and_registry_modules_do_not_import_trading_runtime() -> None:
    source_files = sorted(MA_ROOT.glob("contracts/*.py")) + sorted(MA_ROOT.glob("registry/*.py"))
    assert source_files
    violations = [
        f"{path}: {module}"
        for path in source_files
        for module in _imports(path)
        if module.startswith(FORBIDDEN_PREFIXES)
    ]
    assert violations == []
