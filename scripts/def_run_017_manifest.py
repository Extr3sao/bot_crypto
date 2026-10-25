"""DEF-RUN-017 — manifiesto de la capa de informes.

El manifiesto que el verificador usa como ancla es el del paquete versionado
(`data/def-run-017/ARTIFACT_MANIFEST.json`), porque un checkout limpio no ve `reports/`.
Este script publica además un manifiesto de la capa legible, con rutas relativas al repo y
sha256 de cada artefacto, para que quien lea el informe pueda comprobar sus bytes.

Orden de generación (importante para no pedir un hash imposible):

1. se generan todos los artefactos del informe;
2. se ejecuta este script, que **no incluye** el propio manifiesto en su lista;
3. el manifiesto se copia al paquete con `def_run_017_package.py --only 17`.

Uso::

    python scripts/def_run_017_manifest.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017"
SELF = ROOT / "evidence" / "ARTIFACT_MANIFEST.json"
#: Los ledgers del OOS pesan ~2,5 MB por día-run y son regenerables: se publica su sha256
#: por run en `OOS_RUNS_*.json`, no 120 MB de JSONL en el manifiesto de informes.
EXCLUDE_DIRS = ("evidence/oos/runs", "evidence/oos/runs-superseded")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(SELF))
    args = parser.parse_args(argv)
    artefacts: dict[str, dict[str, object]] = {}
    excluded: dict[str, str] = {}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path == Path(args.out):
            continue
        relative = path.relative_to(REPO).as_posix()
        if any(part in relative for part in EXCLUDE_DIRS):
            excluded[relative] = "regenerable y pesado; su sha256 vive en OOS_RUNS_*.json"
            continue
        artefacts[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    payload = {
        "schema_version": "DEF_RUN_017_REPORT_MANIFEST_V1",
        "rfc": "RFC-DEF-RUN-017",
        "scope": "reports (capa legible; el ancla del verificador es data/def-run-017)",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": artefacts,
        "excluded": excluded,
        "count": len(artefacts),
        "bytes": sum(int(meta["bytes"]) for meta in artefacts.values()),
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"artifacts={len(artefacts)} bytes={payload['bytes']} excluded={len(excluded)}")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
