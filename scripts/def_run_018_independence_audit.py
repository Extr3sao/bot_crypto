"""DEF-RUN-018 / WP-DEF-018-01 — auditar la independencia de B leyendo sus imports.

El verificador B declaraba `imports_trading_bot=false` tras buscar cadenas en su propio
texto. La búsqueda se hacía sobre el fuente recortado por el docstring del módulo, así
que cualquier mención en prosa —una nota, un comentario, un mensaje de error— contaba
como dependencia y B se publicaba como no independiente. Un auditor que subestima su
propia separación sigue estando equivocado: la afirmación tiene que coincidir con el
código.

Aquí la pregunta se responde estructuralmente: `ast.parse` recoge `Import` e
`ImportFrom` con sus alias reales, resuelve los imports dinámicos cuando el argumento es
una cadena literal y, cuando no puede resolverlos, **falla en cerrado** declarando la
incertidumbre. Nada de este módulo se apoya en la declaración que hace B de sí mismo:
el gate consume este artefacto, no el campo `independence` del informe de B.

Uso::

    python scripts/def_run_018_independence_audit.py
    python scripts/def_run_018_independence_audit.py --subject scripts/otro.py --json /tmp/a.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "DEF_RUN_018_INDEPENDENCE_AUDIT_V1"
DEFAULT_SUBJECT = Path("scripts") / "def_run_018_verify_b.py"
DEFAULT_JSON = Path("reports") / "ai-bots" / "RFC-DEF-RUN-018" / "INDEPENDENCE_AUDIT.json"

#: Módulos que, importados, convierten a B en un envoltorio de A o del Builder.
FORBIDDEN = ("trading_bot", "def_run_017_verify", "economic_audit")

#: Formas de importar sin `import`: si el destino no es un literal, no es verificable.
DYNAMIC_CALLS = {
    "importlib.import_module",
    "importlib.__import__",
    "import_module",
    "__import__",
    "importlib.util.spec_from_file_location",
    "spec_from_file_location",
    "runpy.run_path",
    "exec",
    "eval",
}


def dotted(node: ast.AST) -> str | None:
    """Nombre punteado de una expresión de llamada, o `None` si no es un nombre."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def is_forbidden(module: str) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in FORBIDDEN)


def _dynamic_call(node: ast.Call, collected: set[str], details: list[dict[str, Any]]) -> None:
    name = dotted(node.func)
    if name not in DYNAMIC_CALLS:
        return
    target = node.args[0] if node.args else None
    literal = target.value if isinstance(target, ast.Constant) and isinstance(target.value, str) else None
    if literal is None:
        details.append({"call": name, "resolved": None, "state": "UNRESOLVED"})
        return
    if name in {"exec", "eval"}:
        try:
            nested = ast.parse(literal)
        except SyntaxError:
            details.append({"call": name, "resolved": None, "state": "UNPARSABLE_LITERAL"})
            return
        for inner in ast.walk(nested):
            if isinstance(inner, ast.Import):
                collected.update(alias.name for alias in inner.names)
            elif isinstance(inner, ast.ImportFrom) and inner.module:
                collected.add(inner.module)
        details.append({"call": name, "resolved": literal, "state": "INSPECTED_LITERAL"})
        return
    collected.add(literal)
    details.append({"call": name, "resolved": literal, "state": "RESOLVED_LITERAL"})


def audit_source(source: str, *, path: str = "<memory>", sha: str | None = None) -> dict[str, Any]:
    """Clasifica la independencia de un fuente sin ejecutarlo ni leer su prosa."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return {
            "schema_version": SCHEMA,
            "audited_path": path,
            "audited_sha256": sha,
            "state": "FAIL",
            "independent": False,
            "reasons": ["SYNTAX_ERROR"],
            "detail": f"{error.msg} (línea {error.lineno})",
            "imports": [],
            "dynamic_imports": [],
            "forbidden": [],
            "non_stdlib": [],
            "relative_imports": [],
            "uncertain": True,
            "self_declaration_used": False,
            "verified_by": "ast.parse del fuente auditado",
        }

    modules: set[str] = set()
    relative: list[str] = []
    dynamic: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative.append("." * node.level + (node.module or ""))
            elif node.module:
                modules.add(node.module)
        elif isinstance(node, ast.Call):
            _dynamic_call(node, modules, dynamic)

    forbidden = sorted(name for name in modules if is_forbidden(name))
    non_stdlib = sorted(
        name
        for name in modules
        if not (
            name.split(".")[0] in sys.stdlib_module_names
            or name.split(".")[0] in sys.builtin_module_names
            or name in {"__future__"}
        )
    )
    unresolved = [item for item in dynamic if item["state"] != "RESOLVED_LITERAL" and item["state"] != "INSPECTED_LITERAL"]

    reasons: list[str] = []
    if forbidden:
        reasons.append("FORBIDDEN_IMPORT")
    if non_stdlib:
        reasons.append("NON_STDLIB_IMPORT")
    if relative:
        reasons.append("RELATIVE_IMPORT")
    if unresolved:
        reasons.append("UNRESOLVED_DYNAMIC_IMPORT")

    independent = not reasons
    return {
        "schema_version": SCHEMA,
        "audited_path": path,
        "audited_sha256": sha,
        "state": "PASS" if independent else "FAIL",
        "independent": independent,
        "reasons": reasons,
        "imports": sorted(modules),
        "dynamic_imports": dynamic,
        "forbidden": forbidden,
        "non_stdlib": non_stdlib,
        "relative_imports": relative,
        "uncertain": bool(unresolved),
        "self_declaration_used": False,
        "verified_by": "ast.parse del fuente auditado; Import/ImportFrom con alias y llamadas dinámicas",
    }


def audit_path(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = audit_source(
        raw.decode("utf-8"), path=str(path), sha=hashlib.sha256(raw).hexdigest()
    )
    payload["generated_at_utc"] = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", default=str(DEFAULT_SUBJECT))
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    args = parser.parse_args(argv)
    subject = Path(args.subject)
    if not subject.is_file():
        print(f"BLOCKED: no existe {subject}", file=sys.stderr)
        return 2
    payload = audit_path(subject)
    target = Path(args.json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"{subject}: independent={payload['independent']} reasons={payload['reasons']} "
        f"imports={len(payload['imports'])} -> {target}"
    )
    return 0 if payload["independent"] else 1


if __name__ == "__main__":
    sys.exit(main())
