"""Build EXCLUDED_FROM_SYNC_MANIFEST.json.

Every local file that the local -> GitHub synchronisation did NOT publish, with
its SHA-256, local path, size and the policy reason for the exclusion, so an
unpublished file is never mistaken for a synchronised one.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path.cwd()
OUT = REPO / "EXCLUDED_FROM_SYNC_MANIFEST.json"

REASONS: dict[str, str] = {
    ".venv_recovery005/": "ENTORNO_VIRTUAL: venv local del carril recovery-005; .gitignore prohíbe versionar venvs (.venv_*/).",
    ".venv/": "ENTORNO_VIRTUAL: entorno uv del proyecto; .gitignore prohíbe versionarlo (.venv/).",
    "wt-sup001/": "WORKTREE_ANIDADO: carpeta física de `git worktree`; su contenido ya está publicado en la rama codepaper/supervisor-001.",
    "tdm14a-base/": "WORKTREE_ANIDADO: carpeta física de `git worktree` creada durante la auditoría; su contenido ya está publicado en la rama fix/tdm14a.",
    ".tmp/": "SCRATCH_LOCAL: clon temporal de trabajo (.tmp/tdm-head) excluido por .git/info/exclude; no es artefacto del proyecto.",
    ".worktrees/": "WORKTREE_FISICO: excluido por .gitignore (.worktrees/); las ramas se publican, las carpetas no.",
    "reports/": "POLITICA_REPO: .gitignore declara `reports/*` (solo se versiona .gitkeep). Informes generados; el 93% de su contenido ya existe en otras ramas (reports/ai-bots tiene 100 commits históricos publicados).",
    "logs/": "POLITICA_REPO: .gitignore declara `logs/*`; logs de ejecución, no evidencia versionada.",
    "data/raw/": "POLITICA_REPO: .gitignore declara `data/raw/*`; datasets OHLCV crudos fuera del árbol versionado.",
    "__pycache__/": "GENERADO: caché de bytecode de Python.",
    ".pytest_cache/": "GENERADO: caché de pytest.",
    ".mypy_cache/": "GENERADO: caché de mypy.",
    ".ruff_cache/": "GENERADO: caché de ruff.",
    ".hypothesis/": "GENERADO: base de datos de property-testing de hypothesis.",
    ".coverage": "GENERADO: informe de cobertura local.",
    "htmlcov/": "GENERADO: informe HTML de cobertura.",
    "egg-info/": "GENERADO: metadatos de distribución de setuptools.",
}

DEFAULT_REASON = "EXCLUIDO: fichero ignorado por la política del repositorio (.gitignore/.git/info/exclude); no forma parte del árbol versionado."


def reason_for(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    for i in range(len(parts)):
        prefix = "/".join(parts[: i + 1]) + "/"
        if prefix in REASONS:
            return REASONS[prefix]
        if parts[i] in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}:
            return REASONS.get(parts[i] + "/", DEFAULT_REASON)
        if parts[i].endswith(".egg-info"):
            return REASONS["egg-info/"]
    return DEFAULT_REASON


def collect() -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain=v1", "--ignored=matching", "-uall"],
        capture_output=True, text=True, check=True,
    ).stdout
    paths: list[str] = []
    for line in out.splitlines():
        if line.startswith("!!"):
            p = line[3:].strip().strip('"')
        elif line.startswith("??"):
            p = line[3:].strip().strip('"')
        else:
            continue
        paths.append(p)
    return sorted(set(paths))


def walk(top: str) -> list[str]:
    base = REPO / top
    if base.is_file():
        return [top]
    if not base.exists():
        return []
    files = []
    for p in base.rglob("*"):
        if p.is_file() and not p.is_symlink():
            files.append(str(p.relative_to(REPO)).replace("\\", "/"))
    return files


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Ficheros con evidencia propia: se listan uno a uno con su SHA-256.
PER_FILE_PREFIXES = ("reports/", "logs/", "data/raw/")


def tree_digest(files: list[str]) -> str:
    """Merkle-style digest over `sha256<space>relative-path` lines, sorted."""
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(f"{sha256(REPO / rel)}  {rel}\n".encode("utf-8"))
    return h.hexdigest()


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True,
    ).stdout
    return {line.replace("\\", "/") for line in out.splitlines() if line}


def main() -> None:
    per_file: list[dict[str, object]] = []
    per_tree: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    tracked = tracked_files()
    skip = {OUT.name}

    for top in collect():
        for rel in walk(top):
            if rel in seen or rel in skip:
                continue
            seen.add(rel)
            path = REPO / rel
            if not path.is_file() or path.is_symlink():
                continue
            if rel in tracked:
                # Published already: only the untracked siblings of an ignored
                # directory belong in the exclusion manifest.
                continue
            reason = reason_for(rel)
            if rel.startswith(PER_FILE_PREFIXES):
                per_file.append({
                    "path": rel,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "reason": reason,
                })
                continue
            key = rel.split("/")[0] + "/"
            bucket = per_tree.setdefault(key, {
                "path": key,
                "reason": reason,
                "files": [],
                "bytes": 0,
            })
            bucket["files"].append(rel)
            bucket["bytes"] = int(bucket["bytes"]) + path.stat().st_size

    trees = []
    for key in sorted(per_tree):
        b = per_tree[key]
        files = sorted(b.pop("files"))
        entry = {
            "path": key,
            "scope": "TREE_DIGEST (sha256 de cada fichero + ruta, ordenado)",
            "files": len(files),
            "size_bytes": b["bytes"],
            "sha256_of_file_list_and_hashes": tree_digest(files),
            "first_paths": files[:5],
            "reason": b["reason"],
        }
        if key.rstrip("/") in {"wt-sup001", "tdm14a-base"}:
            entry["published_via"] = (
                "worktree anidado: su contenido ya está en el repositorio en la rama "
                "codepaper/supervisor-001 (3b758e22)"
                if key.startswith("wt-") else
                "worktree anidado: su contenido ya está en el repositorio en la rama fix/tdm14a"
            )
            entry.pop("sha256_of_file_list_and_hashes")
            entry["note"] = "Sin digest: es un checkout de git, no un artefacto local."
        trees.append(entry)

    trees = [t for t in trees if int(t["files"]) > 0]
    total_files = len(per_file) + sum(int(t["files"]) for t in trees)
    total_bytes = sum(int(e["size_bytes"]) for e in per_file) + sum(int(t["size_bytes"]) for t in trees)

    doc = {
        "schema": "TAP_SYNC_EXCLUSIONS_V1",
        "generated": "2026-10-25",
        "repository": "https://github.com/Extr3sao/bot_crypto",
        "backup_of_record": "C:/Users/GVLLFR0035/Downloads/sync-backup-20261025 (SHA256SUMS.txt, 554 ficheros)",
        "statement": (
            "Ninguno de estos ficheros se declara sincronizado. Viven solo en local; "
            "se listan con digest SHA-256 para poder verificarlos o recuperarlos. "
            "Por política del repositorio no se publican venvs, worktrees anidados, "
            "cachés, logs ni `reports/*`."
        ),
        "counts": {"files": total_files, "bytes": total_bytes, "trees": len(trees), "individual_files": len(per_file)},
        "individual_files": per_file,
        "trees": trees,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{total_files} files in {len(trees)} trees + {len(per_file)} individual -> {OUT}")


if __name__ == "__main__":
    main()
