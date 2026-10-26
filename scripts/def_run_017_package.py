"""DEF-RUN-017 / WP-017-04 — empaquetar la evidencia para que sobreviva al checkout.

`reports/` está excluido por `.gitignore` (política del repositorio). Eso significa que un
árbol limpio **no** puede verificar lo que el informe afirma. Este script copia los bytes
necesarios —ledgers, minutos, reconstrucción, resultados OOS— a `data/def-run-016` y
`data/def-run-017`, que sí se versionan, y publica un manifiesto con el sha256 de cada byte.

Regla de oro: **copia, no regenera**. Si un artefacto falta en el origen, el script falla;
no rellena el hueco con una reconstrucción silenciosa.

Uso::

    python scripts/def_run_017_package.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RFC16 = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-016" / "evidence"
RFC17 = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017"
PACKAGE16 = REPO / "data" / "def-run-016"
PACKAGE17 = REPO / "data" / "def-run-017"
SCENARIOS = ("m1_cadence1", "m1_cadence5", "m1_hole", "m1_zero_delay", "m3_cadence1")
LABELS = ("CURRENT", "PROPOSED")
RFC17_FILES = (
    "ECONOMIC_ATTRIBUTION.json",
    "TRADE_LEDGER.csv",
    "PAIRED_DELTA.csv",
)


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source: Path, destination: Path, *, origin: str, purpose: str) -> dict[str, Any]:
    if not source.is_file():
        raise SystemExit(f"missing source artifact: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "origin": origin,
        "purpose": purpose,
        "bytes": destination.stat().st_size,
        "sha256": sha256(destination),
        "source_sha256": sha256(source),
    }


def write_manifest(root: Path, entries: dict[str, dict[str, Any]], *, rfc: str) -> Path:
    manifest = {
        "schema_version": "DEF_RUN_017_PACKAGE_V1",
        "rfc": rfc,
        "generated_at_utc": utc_now(),
        "root": str(root.relative_to(REPO)),
        "note": "las claves son relativas a este directorio; el verificador las resuelve "
        "contra el árbol limpio",
        "artifacts": {
            name: {"bytes": meta["bytes"], "sha256": meta["sha256"]}
            for name, meta in sorted(entries.items())
        },
        "evidence": {
            name: {"bytes": meta["bytes"], "sha256": meta["sha256"]}
            for name, meta in sorted(entries.items())
            if name.startswith("ledgers/")
        },
        "provenance": {name: {"origin": meta["origin"], "purpose": meta["purpose"]}
                       for name, meta in sorted(entries.items())},
    }
    path = root / "ARTIFACT_MANIFEST.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def build16() -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for label in LABELS:
        for scenario in SCENARIOS:
            relative = f"ledgers/{label}/{scenario}.jsonl"
            entries[relative] = copy(
                RFC16 / "ledgers" / label / f"{scenario}.jsonl",
                PACKAGE16 / relative,
                origin=f"reports/ai-bots/RFC-DEF-RUN-016/evidence/{relative}",
                purpose="ledger hash-chained del run: fuente primaria de la reconstrucción",
            )
    minutes = "reports/ai-bots/DEF-RUN-PAPER/model-20261020T170635Z/market-1m/BTCUSDT.jsonl"
    entries["market-1m/BTCUSDT.jsonl"] = copy(
        REPO / minutes,
        PACKAGE16 / "market-1m/BTCUSDT.jsonl",
        origin=minutes,
        purpose="minutos de la sesión: permiten reejecutar el replay y comprobar el corte",
    )
    for name in ("AUDIT_CURRENT.json", "AUDIT_PROPOSED.json", "AUDIT_COMPARISON.json",
                 "ECONOMICS.json"):
        entries[name] = copy(
            RFC16 / name,
            PACKAGE16 / name,
            origin=f"reports/ai-bots/RFC-DEF-RUN-016/evidence/{name}",
            purpose="captura publicada por RFC-016 contra la que se reconcilia",
        )
    entries["RFC16_ARTIFACT_MANIFEST.json"] = copy(
        RFC16 / "ARTIFACT_MANIFEST.json",
        PACKAGE16 / "RFC16_ARTIFACT_MANIFEST.json",
        origin="reports/ai-bots/RFC-DEF-RUN-016/evidence/ARTIFACT_MANIFEST.json",
        purpose="ancla original: sus sha256 son los que publicó RFC-016",
    )
    manifest = write_manifest(PACKAGE16, entries, rfc="RFC-DEF-RUN-016")
    (PACKAGE16 / "SOURCE_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": "DEF_RUN_017_SOURCE_V1",
                "generated_at_utc": utc_now(),
                "why": "reports/ está gitignored; estos bytes permiten verificar RFC-016 y "
                "RFC-017 desde un checkout limpio sin regenerar evidencia",
                "source_commit": "d05f8de498c175f7a9b8ccdd38e6e1067832d5e6",
                "entries": entries,
                "manifest": str(manifest.relative_to(REPO)),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"artifacts": len(entries), "bytes": sum(m["bytes"] for m in entries.values())}


def build17() -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for name in RFC17_FILES:
        entries[name] = copy(
            RFC17 / "evidence" / name,
            PACKAGE17 / name,
            origin=f"reports/ai-bots/RFC-DEF-RUN-017/evidence/{name}",
            purpose="artefacto de la reconstrucción económica que el verificador contrasta",
        )
    #: El estrés x2 viaja con la rejilla primaria: el verificador comprueba que está
    #: separado de la decisión (`used_for_decision: false`), y eso solo se puede mirar si
    #: sus bytes están en el paquete.
    for name in (
        "OOS_PLAN.json",
        "OOS_RESULTS.json",
        "OOS_RUNS_untouched_test.json",
        "OOS_RUNS_untouched_test_cost2.json",
        "OOS_STRESS_COST2.json",
    ):
        source = RFC17 / "evidence" / "oos" / name
        if source.is_file():
            entries[f"oos/{name}"] = copy(
                source,
                PACKAGE17 / "oos" / name,
                origin=f"reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/{name}",
                purpose="protocolo congelado y resultados fuera de muestra",
            )
    verification = RFC17 / "evidence" / "INDEPENDENT_VERIFICATION.json"
    if verification.is_file():
        entries["INDEPENDENT_VERIFICATION.json"] = copy(
            verification,
            PACKAGE17 / "INDEPENDENT_VERIFICATION.json",
            origin="reports/ai-bots/RFC-DEF-RUN-017/evidence/INDEPENDENT_VERIFICATION.json",
            purpose="dictamen del verificador independiente sobre este mismo paquete",
        )
    manifest = write_manifest(PACKAGE17, entries, rfc="RFC-DEF-RUN-017")
    (PACKAGE17 / "SOURCE_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": "DEF_RUN_017_SOURCE_V1",
                "generated_at_utc": utc_now(),
                "why": "los resultados y la atribución se publican versionados para que un "
                "checkout limpio pueda replicar la verificación sin reports/",
                "entries": entries,
                "manifest": str(manifest.relative_to(REPO)),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"artifacts": len(entries), "bytes": sum(m["bytes"] for m in entries.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("16", "17"), default=None)
    args = parser.parse_args(argv)
    summary: dict[str, Any] = {}
    if args.only != "17":
        summary["def-run-016"] = build16()
    if args.only != "16":
        summary["def-run-017"] = build17()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
