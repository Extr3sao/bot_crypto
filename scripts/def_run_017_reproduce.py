"""DEF-RUN-017 / WP-017-04 — ¿se puede volver a producir la captura con este código?

Reejecuta los cinco escenarios de RFC-016 **con el carril del commit**, sobre los minutos
empaquetados, y compara contra los ledgers publicados: fills, operaciones cerradas, llamadas,
aplazamientos, sustituciones y neto. No compara bytes (cada línea lleva una hora de pared);
compara la economía y la contabilidad, que es lo que el informe afirma.

El escenario se invoca con la misma especificación que usó RFC-016 (su módulo se importa,
no se copia), así que una diferencia no puede venir de una config distinta.

Uso::

    python scripts/def_run_017_reproduce.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from trading_bot.vision.economic_audit import money, reconstruct  # noqa: E402

PUBLISHED = REPO / "data" / "def-run-016" / "ledgers"
OUT = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017" / "evidence"
TOL = Decimal("0.000001")


def load_audit():
    spec = importlib.util.spec_from_file_location(
        "def_run_016_audit", REPO / "scripts" / "def_run_016_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT / "REPRODUCTION.json"))
    args = parser.parse_args(argv)
    audit = load_audit()
    minutes, minutes_sha = audit.load_minutes()
    work_root = Path(tempfile.mkdtemp(prefix="def017-repro-"))
    rows: list[dict[str, Any]] = []
    for lifecycle, label in (("SUPERSEDE", "CURRENT"), ("DEFER", "PROPOSED")):
        for name, spec in audit.SCENARIOS.items():
            work = work_root / label / name
            work.mkdir(parents=True, exist_ok=True)
            result = audit.run_scenario(name, spec, minutes, work, lifecycle)
            published_path = PUBLISHED / label / f"{name}.jsonl"
            fresh_path = work / "ledger.jsonl"
            published = reconstruct(published_path, source_commit="d05f8de")
            fresh = reconstruct(fresh_path, source_commit="worktree")
            delta = fresh.net_exact() - published.net_exact()
            rows.append(
                {
                    "label": label,
                    "lifecycle": lifecycle,
                    "scenario": name,
                    "published_fills": int(published.totals["fills"]),
                    "fresh_fills": int(fresh.totals["fills"]),
                    "published_closed": int(published.totals["closed_trades"]),
                    "fresh_closed": int(fresh.totals["closed_trades"]),
                    "published_net_usdt": money(published.net_exact()),
                    "fresh_net_usdt": money(fresh.net_exact()),
                    "delta_usdt": money(delta),
                    "published_calls": result["summary_view"]["calls"],
                    "fresh_calls": int(result["metrics"]["calls"]),
                    "published_deferred": int(result["metrics"]["deferred_slots"]),
                    "published_superseded": int(result["metrics"]["superseded"]),
                    "matches": (
                        int(published.totals["fills"]) == int(fresh.totals["fills"])
                        and int(published.totals["closed_trades"])
                        == int(fresh.totals["closed_trades"])
                        and delta.copy_abs() <= TOL
                    ),
                    "fresh_status": fresh.status,
                }
            )
            print(
                f"{label:8s} {name:14s} published {published.totals['net_realised_usdt']:>13s} "
                f"fresh {money(fresh.net_exact()):>13s} delta {money(delta):>10s} "
                f"fills {published.totals['fills']}/{fresh.totals['fills']}",
                flush=True,
            )
    payload = {
        "schema_version": "DEF_RUN_017_REPRODUCTION_V1",
        "generated_at_utc": utc_now(),
        "builder": "scripts/def_run_017_reproduce.py",
        "minutes_sha256": minutes_sha,
        "minutes_source": "data/def-run-016/market-1m/BTCUSDT.jsonl",
        "lane_source": "src/trading_bot/vision/lane.py del commit actual (== d05f8de para ese fichero)",
        "tolerance_usdt": "0.000001",
        "rows": rows,
        "all_match": all(row["matches"] for row in rows),
        "note": "las marcas de tiempo de pared difieren por construcción; lo que se compara es "
        "la contabilidad y la economía",
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"all_match={payload['all_match']} wrote {target}")
    return 0 if payload["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
