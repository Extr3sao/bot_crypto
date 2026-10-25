"""DEF-RUN-018 / WP-018-00 — inventario de lo que existe antes de tocar nada.

El RFC-018 arranca con una pregunta incómoda: ¿qué parte de lo que el informe de
RFC-DEF-RUN-017 afirma está respaldada por bytes que un checkout limpio puede ver?
Este script no opina: recorre el árbol, etiqueta cada módulo según si el entrypoint
del replay lo alcanza de verdad (grafo de imports estático, no una tabla copiada) y
hashea cada insumo crítico.

Dos distinciones que el informe necesita y que un `ls` no da:

* **versionado** — `git ls-files --error-unmatch`; una evidencia que solo existe en
  este disco no la puede verificar un checkout limpio, y se declara como gap.
* **referenciado** — un módulo que existe pero que ningún entrypoint importa no es
  autoridad de runtime por el hecho de estar en `src/`.

Uso::

    python scripts/def_run_018_baseline.py
    python scripts/def_run_018_baseline.py --json out/BASELINE_017.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RFC = "RFC-DEF-RUN-018"
SUBJECT = "RFC-DEF-RUN-017"
OUT = REPO / "reports" / "ai-bots" / RFC
SCHEMA = "DEF_RUN_018_BASELINE_V1"

#: Entrypoints que de verdad ejecutan el carril. Si un módulo no es alcanzable desde
#: ninguno de estos, no puede ser RUNTIME_AUTHORITATIVE por mucho que viva en src/.
RUNTIME_ENTRYPOINTS = (
    "scripts/def_run_017_oos.py",
    "scripts/def_run_016_audit.py",
    "scripts/def_run_017_reproduce.py",
)
TEST_ENTRYPOINTS = (
    "scripts/def_run_017_verify.py",
    "scripts/def_run_018_verify_b.py",
)

CRITICAL_GLOBS = (
    "data/def-run-016/**/*",
    "data/def-run-017/**/*",
    "data/quote-feed-1m/*",
    "reports/ai-bots/RFC-DEF-RUN-017/evidence/*.json",
    "reports/ai-bots/RFC-DEF-RUN-017/evidence/*.csv",
    "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/*.json",
    "reports/ai-bots/RFC-DEF-RUN-017/*.json",
    "reports/ai-bots/RFC-DEF-RUN-017/*.md",
)

CODE_GLOBS = (
    "scripts/def_run_014_*.py",
    "scripts/def_run_016_*.py",
    "scripts/def_run_017_*.py",
    "scripts/def_run_018_*.py",
    "src/trading_bot/vision/*.py",
    "src/trading_bot/paper/*.py",
)

CLAIMS = (
    ("verifier_a_status", "PASS"),
    ("verifier_a_checks", 158),
    ("verifier_tests", "29 passed"),
    ("parity_bundle", "111 passed"),
    ("report_artifacts", 21),
    ("packaged_artifacts", 9),
    ("oos_decision", "NOT_EVIDENCED"),
    ("stress_status", "NEGATIVE"),
    ("stress_used_for_decision", False),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def tracked(relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def module_name(path: Path) -> str:
    relative = path.relative_to(REPO / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def local_imports(path: Path) -> set[str]:
    """Nombres `trading_bot.*` que el fichero importa, sin ejecutarlo."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("trading_bot"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            base = node.module
            if base.startswith("trading_bot"):
                found.add(base)
                found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def script_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("trading_bot"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("trading_bot"):
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def build_graph() -> tuple[dict[str, Path], dict[str, set[str]]]:
    modules = {module_name(path): path for path in (REPO / "src" / "trading_bot").rglob("*.py")}
    graph = {name: local_imports(path) for name, path in modules.items()}
    return modules, graph


def reachable(graph: dict[str, set[str]], roots: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for child in graph.get(name, ()):
            if child in graph:
                stack.append(child)
    return seen


def resolve_roots(graph: dict[str, set[str]], scripts: Iterable[str]) -> set[str]:
    roots: set[str] = set()
    for script in scripts:
        path = REPO / script
        if not path.is_file():
            continue
        for name in script_imports(path):
            if name in graph:
                roots.add(name)
    return reachable(graph, roots)


def authority_map() -> list[dict[str, Any]]:
    modules, graph = build_graph()
    runtime = resolve_roots(graph, RUNTIME_ENTRYPOINTS)
    testing = resolve_roots(graph, TEST_ENTRYPOINTS)
    rows: list[dict[str, Any]] = []
    for name, path in sorted(modules.items()):
        if name in runtime:
            tag = "RUNTIME_AUTHORITATIVE"
        elif name in testing:
            tag = "TEST_ONLY"
        elif not path.read_text(encoding="utf-8").strip():
            tag = "EMPTY"
        else:
            tag = "UNREACHABLE_FROM_ENTRYPOINTS"
        rows.append(
            {
                "module": name,
                "path": str(path.relative_to(REPO)).replace("\\", "/"),
                "tag": tag,
                "tracked": tracked(str(path.relative_to(REPO))),
            }
        )
    return rows


def hashed(patterns: Iterable[str]) -> list[dict[str, Any]]:
    seen: set[Path] = set()
    entries: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in REPO.glob(pattern):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            relative = str(path.relative_to(REPO)).replace("\\", "/")
            entries.append(
                {
                    "path": relative,
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                    "tracked": tracked(relative),
                }
            )
    return sorted(entries, key=lambda entry: entry["path"])


def declared_claims() -> dict[str, Any]:
    """Lo que el informe afirma, separado de lo que este script ha observado."""
    facts_path = REPO / "reports" / "ai-bots" / SUBJECT / "facts.json"
    facts: dict[str, Any] = {}
    if facts_path.is_file():
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    return {
        "source": "reports/ai-bots/RFC-DEF-RUN-017/facts.json",
        "source_present": facts_path.is_file(),
        "claims": {
            "verifier_a_status": (facts.get("verification") or {}).get("status"),
            "verifier_a_checks": (facts.get("verification") or {}).get("checks_total"),
            "report_artifacts": (facts.get("package") or {}).get("report_artifacts"),
            "packaged_artifacts": (facts.get("package") or {}).get("packaged_artifacts"),
            "oos_decision": (facts.get("oos") or {}).get("economic_status"),
            "stress_status": (facts.get("stress") or {}).get("stress_status"),
            "stress_used_for_decision": (facts.get("stress") or {}).get("used_for_decision"),
        },
    }


def gaps(evidence: list[dict[str, Any]], code: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    untracked_evidence = [entry for entry in evidence if not entry["tracked"]]
    if untracked_evidence:
        out.append(
            {
                "code": "EVIDENCE_NOT_VERSIONED",
                "severity": "P0",
                "count": len(untracked_evidence),
                "paths": [entry["path"] for entry in untracked_evidence][:12],
                "detail": "un checkout limpio no puede ver estos bytes hasta que se commiteen",
            }
        )
    untracked_code = [entry for entry in code if not entry["tracked"]]
    if untracked_code:
        out.append(
            {
                "code": "CODE_NOT_VERSIONED",
                "severity": "P0",
                "count": len(untracked_code),
                "paths": [entry["path"] for entry in untracked_code][:12],
                "detail": "el replay no es reproducible desde un commit si el carril no está commiteado",
            }
        )
    original = REPO / "reports" / "ai-bots" / SUBJECT / "evidence" / "oos" / "OOS_RESULTS.json"
    if original.is_file():
        cells = json.loads(original.read_text(encoding="utf-8")).get("cells") or {}
        defer = {k: v for k, v in cells.items() if k.endswith("|DEFER|1.0")}
        if defer and all(value.get("deferred_slots") == 0 for value in defer.values()):
            out.append(
                {
                    "code": "DEFERRED_COUNTERS_ZERO",
                    "severity": "P0",
                    "detail": "las celdas DEFER publican 0 aplazamientos; el ledger dice otra cosa",
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=str(OUT / "BASELINE_017.json"))
    parser.add_argument("--md", default=str(OUT / "BASELINE_017.md"))
    parser.add_argument(
        "--authority-md", default=str(OUT / "RUNTIME_AUTHORITY_MAP.md")
    )
    args = parser.parse_args(argv)

    status = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    evidence = hashed(CRITICAL_GLOBS)
    code = hashed(CODE_GLOBS)
    authority = authority_map()
    payload = {
        "schema_version": SCHEMA,
        "rfc": RFC,
        "subject": SUBJECT,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": {
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": git("rev-parse", "HEAD"),
            "head_subject": git("log", "-1", "--format=%s"),
            "dirty_paths": len(status),
            "status": status,
        },
        "entrypoints": {
            "runtime": list(RUNTIME_ENTRYPOINTS),
            "test_only": list(TEST_ENTRYPOINTS),
        },
        "authority": authority,
        "counts": {
            "modules": len(authority),
            "runtime_authoritative": sum(
                1 for row in authority if row["tag"] == "RUNTIME_AUTHORITATIVE"
            ),
            "evidence_files": len(evidence),
            "evidence_tracked": sum(1 for row in evidence if row["tracked"]),
            "code_files": len(code),
            "code_tracked": sum(1 for row in code if row["tracked"]),
        },
        "evidence": evidence,
        "code": code,
        "declared": declared_claims(),
        "gaps": gaps(evidence, code),
        "false_success": 0,
    }
    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    runtime_rows = [row for row in authority if row["tag"] == "RUNTIME_AUTHORITATIVE"]
    lines = [
        f"# BASELINE_017 — {RFC}",
        "",
        f"Generado: `{payload['generated_at_utc']}` · rama `{payload['git']['branch']}` · "
        f"HEAD `{payload['git']['head']}` · {payload['git']['dirty_paths']} rutas sucias.",
        "",
        "## Lo que existe, y si un checkout limpio lo puede ver",
        "",
        "| Conjunto | Ficheros | Versionados |",
        "| --- | --- | --- |",
        f"| Evidencia de 016/017 | {payload['counts']['evidence_files']} | "
        f"{payload['counts']['evidence_tracked']} |",
        f"| Código del carril | {payload['counts']['code_files']} | "
        f"{payload['counts']['code_tracked']} |",
        f"| Módulos de `trading_bot` | {payload['counts']['modules']} | "
        f"{payload['counts']['runtime_authoritative']} alcanzables desde el entrypoint |",
        "",
        "## Gaps detectados (no corregidos aquí)",
        "",
    ]
    if payload["gaps"]:
        for gap in payload["gaps"]:
            lines.append(f"- **{gap['code']}** ({gap['severity']}): {gap['detail']}")
            for path in gap.get("paths", [])[:6]:
                lines.append(f"  - `{path}`")
    else:
        lines.append("- ninguno")
    lines += [
        "",
        "## Afirmaciones del informe 017 (declaradas, aún no reejecutadas)",
        "",
        "```json",
        json.dumps(payload["declared"], indent=2, sort_keys=True),
        "```",
        "",
        "Este baseline no valida esas cifras: solo deja constancia de dónde salen. La",
        "reejecución corresponde a WP-018-02 (checkout limpio) y WP-018-03 (verificador B).",
        "",
    ]
    md_path = Path(args.md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    authority_lines = [
        f"# RUNTIME_AUTHORITY_MAP — {RFC}",
        "",
        f"HEAD `{payload['git']['head']}` · {len(authority)} módulos · "
        f"{len(runtime_rows)} alcanzables desde `{'`, `'.join(RUNTIME_ENTRYPOINTS)}`.",
        "",
        "Etiqueta derivada del grafo de imports estático, no de una tabla escrita a mano:",
        "un módulo que ningún entrypoint importa no es autoridad de runtime.",
        "",
        "| Módulo | Etiqueta | Versionado |",
        "| --- | --- | --- |",
    ]
    for row in authority:
        authority_lines.append(f"| `{row['module']}` | {row['tag']} | {row['tracked']} |")
    authority_lines.append("")
    Path(args.authority_md).write_text(
        "\n".join(authority_lines), encoding="utf-8", newline="\n"
    )

    print(
        f"evidence={payload['counts']['evidence_files']} "
        f"tracked={payload['counts']['evidence_tracked']} "
        f"code={payload['counts']['code_files']} "
        f"tracked={payload['counts']['code_tracked']} "
        f"gaps={len(payload['gaps'])} -> {json_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
