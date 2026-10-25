#!/usr/bin/env python
"""WP-EDGE-09B — data quality, provenance, coverage and point-in-time viability.

    python scripts/edge09_sources.py [--no-probe]

Probes the public endpoints the registered sources name (read-only, bounded),
measures the forward captures this repository already holds, and publishes
``sources/SOURCE_VIABILITY.{json,md}``. With ``--append-registry`` it also
appends the measured entries to ``docs/source_registry.md`` — appended, never
rewritten, because that registry is a record of when claims were fixed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09 import sources  # noqa: E402
from trading_bot.research.edge09.registration import (  # noqa: E402
    SCHEMA_VERSION,
    SOURCE_REGISTRY,
    WP,
)

OUTDIR = WP / "sources"


def render(payload: dict[str, Any]) -> str:
    capture = payload["captured"]
    lines = [
        "# WP-EDGE-09B — source viability, coverage and point-in-time",
        "",
        f"*Measured at `{payload['as_of_utc']}`. Probes: {len(payload['probes'])}. "
        "`promotion: NONE`.*",
        "",
        "## 1. What the providers answer, today",
        "",
        "| Probe | What it establishes | Status | Seconds | Reachable |",
        "| --- | --- | ---: | ---: | :-: |",
    ]
    for row in payload["probes"]:
        status = row.get("status")
        note = f"{status}" if status is not None else f"no answer ({row.get('note', '')[:40]})"
        lines.append(
            f"| {row['id']} | {row['what']} | {note} | {row.get('seconds')} | "
            f"{row.get('reachable')} |"
        )
    lines += [
        "",
        "A probe that does not answer is recorded as such: the package does not replace a "
        "missing series with a different one, and it does not model what it cannot measure.",
        "",
        "## 2. What this repository already holds",
        "",
        "| | |",
        "| --- | --- |",
        f"| Capture roots with a manifest or segments | {capture['roots']} |",
        f"| Total captured span | {capture['total_hours']} h ({capture['total_seconds']} s) |",
        f"| Longest single capture | {capture['longest_seconds']} s |",
        f"| Runs declaring CONTINUOUS_DATA | {capture['runs_continuous']} |",
        f"| Runs declaring INCOMPLETE_DATA | {capture['runs_incomplete']} |",
        f"| Markets covered | {', '.join(capture['markets_covered'])} |",
        f"| Symbols covered | {', '.join(capture['symbols_covered'])} |",
        f"| Streams covered | {', '.join(capture['streams_covered'])} |",
        "",
        f"{capture['continuity_note']}",
        "",
        "### Per run",
        "",
        "| Root | Run | Duration (s) | Continuity | Markets | Segments | Reconnects | Resnapshots |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for row in capture["per_root"]:
        lines.append(
            f"| `{row['root']}` | `{row['run_id']}` | {row['duration_seconds']} | "
            f"{row['continuity']} | {row['markets']} | {row['segments']} | "
            f"{row['reconnects']} | {row['resnapshots']} |"
        )
    lines += [
        "",
        "## 3. Verdict per source",
        "",
        "| Source | Name | Depth | Point-in-time | Classification | Why |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["source_verdicts"]:
        lines.append(
            f"| `{row['source_id']}` | {row['name']} | {row['depth']} | {row['pit']} | "
            f"**{row['classification']}** | {row['why']} |"
        )
    lines.append("")
    return "\n".join(lines)


def append_registry(payload: dict[str, Any]) -> str:
    """Append the measured rows to the project's source registry."""
    block = [
        "",
        "## Fuentes medidas por RFC-EDGE-009 (añadidas, no reescritas)",
        "",
        f"> Medición propia de esta fase el **{payload['as_of_utc'][:10]}**. Las filas anteriores de este",
        "> registro no se tocan: un claim se fija cuando se fija, y se añade lo que se midió después.",
        "",
        "| SOURCE_ID | fuente | profundidad medida | PIT | clasificación | evidencia |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["source_verdicts"]:
        block.append(
            f"| {row['source_id']} | {row['name']} | {row['depth']} | {row['pit']} | "
            f"**{row['classification']}** | `reports/edge-recovery/WP-EDGE-09/sources/SOURCE_VIABILITY.json` |"
        )
    for probe in payload["probes"]:
        status = probe.get("status")
        verdict = "responde" if probe.get("reachable") else "NO responde"
        block.append(
            f"| {probe['id']} | `{probe['url'].split('?')[0]}` | sondeo HTTP {status} ({verdict}) | "
            f"n/a | {'AVAILABLE' if probe.get('reachable') else 'UNAVAILABLE_IN_CURRENT_ENVIRONMENT'} | "
            f"`SOURCE_VIABILITY.json` |"
        )
    block.append("")
    return "\n".join(block)


def main(argv: list[str] | None = None) -> int:
    from datetime import UTC, datetime

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-probe", action="store_true", help="read the corpus only")
    parser.add_argument(
        "--append-registry", action="store_true", help="append the rows to docs/source_registry.md"
    )
    options = parser.parse_args(argv)

    payload = sources.build(probe=not options.no_probe)
    payload["schema_version"] = SCHEMA_VERSION
    payload["work_package"] = "WP-EDGE-09B"
    payload["as_of_utc"] = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "SOURCE_VIABILITY.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (OUTDIR / "SOURCE_VIABILITY.md").write_text(render(payload), encoding="utf-8")

    if options.append_registry:
        with SOURCE_REGISTRY.open("a", encoding="utf-8") as handle:
            handle.write(append_registry(payload))

    print(
        f"probes {len(payload['probes'])} reachable "
        f"{sum(1 for row in payload['probes'] if row.get('reachable'))}"
    )
    for row in payload["probes"]:
        print(f"  {row['id']} status={row.get('status')} {row.get('what', '')[:60]}")
    capture = payload["captured"]
    print(
        f"captures {capture['roots']} roots, {capture['total_hours']} h total, "
        f"longest {capture['longest_seconds']} s"
    )
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)}/SOURCE_VIABILITY.{{json,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
