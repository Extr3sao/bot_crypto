"""exp_003k_inventory — what strategies already exist, and which one may be tested.

    ./.venv/Scripts/python.exe scripts/exp_003k_inventory.py

WP-3 of 003K asks for a second strategy "de familia distinta, sin duplicar código". That is
impossible to honour without first knowing what is already there, so this script walks the
two places strategies actually live and reads them with ``ast`` instead of trusting a list
somebody typed:

``src/trading_bot/strategies/``
    The canonical ``Strategy`` implementations behind ``StrategyRouter``. Most are state
    ``research`` or ``TEST_ONLY`` and are *not* reachable from the PAPER lane.

``src/trading_bot/research/families/``
    The ``AlphaFamily`` objects the lane's experimental signal source can question. This is
    the only place a 003K candidate can come from without inventing a new agent, a new
    router or a second execution path.

For each class it records the docstring's opening claim, the module's declared parameters
(``UPPER_CASE`` constants and their values), the module's ``MIN_CANDLES`` when it has one,
and whether the id is admitted to the experimental source in ``signal_sources``. Nothing is
executed and no strategy is imported: the inventory has to work even if a module is broken.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

STRATEGY_DIRS = (
    REPO / "src" / "trading_bot" / "strategies",
    REPO / "src" / "trading_bot" / "research" / "families",
)


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return ast.unparse(node)


def _module_facts(tree: ast.Module) -> dict[str, Any]:
    constants: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                constants[target.id] = _literal(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper() and node.value is not None:
                constants[node.target.id] = _literal(node.value)
    return {"constants": constants, "docstring": (ast.get_docstring(tree) or "").strip()}


def _guard_min_candles(node: ast.AST) -> int | None:
    """``if len(candles) < N: return []`` — the family's own refusal threshold."""

    found: list[int] = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1:
            continue
        if not isinstance(item.ops[0], ast.Lt) or len(item.comparators) != 1:
            continue
        left = item.left
        if not (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "len"
            and left.args
            and isinstance(left.args[0], ast.Name)
            and left.args[0].id in {"candles", "bars", "window"}
        ):
            continue
        right = item.comparators[0]
        if isinstance(right, ast.Constant) and isinstance(right.value, int):
            found.append(int(right.value))
    return max(found) if found else None


def _classes(tree: ast.Module) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [item.name for item in node.body if isinstance(item, ast.FunctionDef)]
        found.append(
            {
                "name": node.name,
                "bases": [ast.unparse(base) for base in node.bases],
                "methods": methods,
                "docstring_first_line": (ast.get_docstring(node) or "").strip().splitlines()[0]
                if ast.get_docstring(node)
                else "",
                "has_generate": "generate" in methods,
                "has_evaluate": "evaluate" in methods,
                "guard_min_candles": _guard_min_candles(node),
            }
        )
    return found


def _admitted() -> dict[str, str]:
    """The ids the experimental source accepts, read from the registry itself."""

    try:
        from trading_bot.vision.signal_sources import STRATEGY_SPECS

        return {key: spec.classification for key, spec in STRATEGY_SPECS.items()}
    except Exception as exc:  # pragma: no cover - the inventory must still print without it
        return {"__unavailable__": f"{type(exc).__name__}: {exc}"}


def _docstring_params(text: str) -> list[str]:
    """Lines of the module docstring that declare parameters, kept verbatim."""

    return [
        line.strip("- ").strip()
        for line in text.splitlines()
        if line.strip().startswith(("-", "*")) and len(line.strip()) > 3
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    admitted = _admitted()
    entries: list[dict[str, Any]] = []
    for directory in STRATEGY_DIRS:
        if not directory.exists():
            entries.append({"error": f"missing directory {directory}"})
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            facts = _module_facts(tree)
            for klass in _classes(tree):
                is_strategy_like = (
                    bool(klass["bases"])
                    or klass["has_generate"]
                    or klass["has_evaluate"]
                    or klass["name"].endswith(("Strategy", "Family", "Bot"))
                )
                if is_strategy_like:
                    entries.append(
                        {
                            "file": path.relative_to(REPO).as_posix(),
                            "group": directory.name,
                            "class": klass["name"],
                            "bases": klass["bases"],
                            "methods": klass["methods"],
                            "purpose": klass["docstring_first_line"],
                            "min_candles": facts["constants"].get("MIN_CANDLES")
                            or klass["guard_min_candles"],
                            "min_candles_source": (
                                "module constant MIN_CANDLES"
                                if facts["constants"].get("MIN_CANDLES")
                                else "literal guard inside the class"
                                if klass["guard_min_candles"]
                                else None
                            ),
                            "declared_parameters": _docstring_params(facts["docstring"]),
                            "admitted_to_experimental_source": (
                                klass["name"] in {"__none__"}
                            ),
                            "classification": None,
                        }
                    )

    # Attach the runtime admission flag to the family that the registry actually names.
    by_family = {}
    for entry in entries:
        if entry.get("group") != "families":
            continue
        stem = Path(entry["file"]).stem.replace("_family", "")
        by_family[stem] = entry
    for strategy_id, classification in admitted.items():
        entry = by_family.get(strategy_id)
        if entry is None:
            continue
        entry["classification"] = classification
        entry["admitted_to_experimental_source"] = True
        entry["strategy_id"] = strategy_id

    families = [entry for entry in entries if entry.get("group") == "families"]
    strategies = [entry for entry in entries if entry.get("group") == "strategies"]
    payload = {
        "schema_version": "AI_BOTS_003K_STRATEGY_INVENTORY_V1",
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "commit": _git_head(),
        "scope": [path.relative_to(REPO).as_posix() for path in STRATEGY_DIRS],
        "method": "ast walk of every non-underscore module in scope; nothing imported or run",
        "families": families,
        "strategies": strategies,
        "admitted_registry": admitted,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "STRATEGY_INVENTORY.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "STRATEGY_INVENTORY.md").write_text(_markdown(payload), encoding="utf-8", newline="\n")
    print(
        f"[003k-inventory] {len(families)} AlphaFamily classes, {len(strategies)} "
        f"Strategy classes, {len(admitted)} admitted to the experimental source",
        flush=True,
    )
    return 0


def _git_head() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        return "UNKNOWN"


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 003K — Inventario de estrategias ya implementadas",
        "",
        f"Generado por `scripts/exp_003k_inventory.py` sobre `{payload['commit'][:7]}`.",
        f"Método: {payload['method']}.",
        "",
        "## AlphaFamilies — las únicas alcanzables por la lane experimental",
        "",
        "| id | clase | fichero | MIN_CANDLES | clasificación | propósito |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for entry in payload["families"]:
        lines.append(
            f"| `{entry.get('strategy_id', '—')}` | {entry['class']} | "
            f"`{entry['file']}` | {entry.get('min_candles')} | "
            f"{entry.get('classification') or 'no admitida'} | {entry['purpose']} |"
        )
    lines += [
        "",
        "## Estrategias canónicas (`strategies/`) — no alcanzables desde PAPER",
        "",
        "| clase | fichero | métodos | propósito |",
        "| --- | --- | --- | --- |",
    ]
    for entry in payload["strategies"]:
        lines.append(
            f"| {entry['class']} | `{entry['file']}` | "
            f"{', '.join(entry['methods'][:6])} | {entry['purpose']} |"
        )
    lines += [
        "",
        "## Regla de selección aplicada",
        "",
        "Una candidata válida tiene que (a) ser una `AlphaFamily` ya escrita, (b) estar admitida",
        "por `signal_sources.STRATEGY_SPECS` sin tocar el router ni el broker, (c) declarar sus",
        "parámetros como pre-registrados en su propio docstring, y (d) tener `MIN_CANDLES`",
        "cubierto por la ventana de 60 barras. Duplicar una familia o crear un agente nuevo",
        "queda fuera de alcance por diseño.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
