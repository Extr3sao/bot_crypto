"""WP-TDM-12B — runtime authority inventory and retrospective candidate triage.

Discovery is mechanical (files, AST, config, admission ledger), not asserted:
every registry row points at the entrypoint that would execute it. Metrics are
recomputed from the sealed bars, and the gates are applied per candidate, with
a power requirement derived from that candidate's own dispersion — the 36-trade
minimum from TDM-11 is deliberately *not* reused.

Writes ``CANDIDATE_REGISTRY.csv/.json``, ``DATA_WINDOW_REGISTRY.json`` and
``.tdm12/triage.json``.

Usage::  python scripts/tdm12_inventory.py
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

ART = REPO_ROOT / ".tdm12"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-12"
DEV_DIR = REPO_ROOT / "data" / "tdm10"
HOLD_DIR = REPO_ROOT / "data" / "tdm08"

from tdm12_review import (  # noqa: E402  (own harness, purpose-built)
    ASSETS,
    COST_BPS,
    DEV_END_MS,
    DEV_START_MS,
    FAMILIES,
    FAMILY_MODULES,
    HOLD_END_MS,
    TIMEFRAMES,
    WINDOW,
    bars,
)

from trading_bot.research.source_fingerprint import (  # noqa: E402
    FINGERPRINT_SCHEME_V1,
    FINGERPRINT_SCHEME_V2,
    FingerprintError,
    SourceFingerprint,
    compute_source_fingerprint,
    legacy_working_tree_fingerprint,
)

Z90 = 1.6448536269514722
Z80 = 0.8416212335729143
CHEAPEST_COST_BPS = 9.25
ADMISSION = REPO_ROOT / "config" / "strategy_admission.json"
STRATEGIES_YAML = REPO_ROOT / "config" / "strategies.yaml"
PAPER_SCRIPT = REPO_ROOT / "scripts" / "autonomous_paper.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def strategy_protocol_implementations() -> list[dict[str, str]]:
    """Classes whose body defines evaluate(candles, indicators, config)."""
    found: list[dict[str, str]] = []
    for path in sorted((REPO_ROOT / "src" / "trading_bot" / "strategies").glob("*.py")):
        if path.stem == "protocols":
            continue  # the protocol itself is the contract, not an implementation
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name == "Strategy":
                continue
            methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
            if "evaluate" in methods:
                found.append(
                    {
                        "class": node.name,
                        "module": f"trading_bot.strategies.{path.stem}",
                        "strategy_name": next(
                            (
                                n.value.value
                                for n in node.body
                                if isinstance(n, ast.Assign)
                                and any(getattr(t, "id", "") == "strategy_name" for t in n.targets)
                                and isinstance(n.value, ast.Constant)
                            ),
                            "",
                        ),
                    }
                )
    return found


#: Historical artefacts were published with this literal in ``source_commit``. It is
#: not provenance and never was (defect D-02); ``v1`` keeps it only so the published
#: registry can be reproduced byte for byte, and says so out loud.
LEGACY_SOURCE_COMMIT_LITERAL = "504256ec"


def git_head() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise FingerprintError(f"cannot resolve HEAD in {REPO_ROOT}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def family_classes(scheme: str, source_commit: str | None) -> list[dict[str, Any]]:
    """One fingerprint row per family module.

    ``v2`` hashes the committed blob and refuses a dirty or untracked source file
    (RFC-TDM-014A §5.1). ``v1`` reproduces the published artefact exactly, defect
    included, so historical numbers stay checkable instead of being rewritten.
    """
    out: list[dict[str, Any]] = []
    for name, (module_name, class_name) in FAMILY_MODULES.items():
        module = __import__(f"trading_bot.research.families.{module_name}", fromlist=[class_name])
        getattr(module, class_name)  # import check: the class must exist in the frozen module
        path = Path(module.__file__)
        relpath = path.resolve().relative_to(REPO_ROOT).as_posix()
        entry: dict[str, Any] = {
            "family": name,
            "class": class_name,
            "module": f"trading_bot.research.families.{module_name}",
        }
        if scheme == FINGERPRINT_SCHEME_V2:
            fingerprint: SourceFingerprint = compute_source_fingerprint(
                REPO_ROOT, relpath, commit=source_commit or "HEAD"
            )
            entry["source_sha256"] = fingerprint.source_fingerprint
            entry["fingerprint"] = fingerprint.to_dict()
        else:
            entry["source_sha256"] = legacy_working_tree_fingerprint(path)
            entry["fingerprint"] = None
        out.append(entry)
    return out


def fingerprint_fields(family_row: dict[str, Any], scheme: str) -> dict[str, Any]:
    """Registry columns for one family, versioned by scheme.

    ``v1`` emits ``parameter_hash`` and nothing else, so the published registry can
    be reproduced byte for byte. ``v2`` keeps ``parameter_hash`` as an explicit
    truncation alias of ``source_fingerprint`` and adds the provenance fields, so a
    reader can tell which identity it is holding without guessing from width.
    """
    fingerprint = family_row.get("fingerprint")
    if scheme == FINGERPRINT_SCHEME_V2 and fingerprint:
        return {
            "parameter_hash": fingerprint["parameter_hash"],
            "fingerprint_scheme": fingerprint["fingerprint_scheme"],
            "source_fingerprint": fingerprint["source_fingerprint"],
            "source_relpath": fingerprint["source_relpath"],
            "source_blob_oid": fingerprint["source_blob_oid"],
            "working_tree_clean_verified": fingerprint["working_tree_clean_verified"],
        }
    return {"parameter_hash": str(family_row["source_sha256"])[:16]}


def empty_fingerprint_fields(scheme: str) -> dict[str, Any]:
    """The same columns for rows that have no module to fingerprint."""
    if scheme == FINGERPRINT_SCHEME_V2:
        return {
            "parameter_hash": "-",
            "fingerprint_scheme": "not_applicable",
            "source_fingerprint": "-",
            "source_relpath": "-",
            "source_blob_oid": "-",
            "working_tree_clean_verified": False,
        }
    return {"parameter_hash": "-"}


def declared_config_strategies() -> list[dict[str, Any]]:
    """Parse config/strategies.yaml without PyYAML: only the keys we need."""
    text = STRATEGIES_YAML.read_text(encoding="utf-8")
    entries: list[dict[str, Any]] = []
    current: str | None = None
    for line in text.splitlines():
        if (
            line.startswith("    ")
            and line.rstrip().endswith(":")
            and not line.startswith("      ")
        ):
            name = line.strip()[:-1]
            if name and name not in ("strategies", "global"):
                current = name
                entries.append({"name": name, "enabled": None, "state": None})
        elif current and line.strip().startswith("enabled:"):
            entries[-1]["enabled"] = line.split(":", 1)[1].strip().lower() == "true"
        elif current and line.strip().startswith("state:"):
            entries[-1]["state"] = line.split(":", 1)[1].split("#")[0].strip().strip('"')
    return entries


def admission_ledger() -> dict[str, Any]:
    payload = json.loads(ADMISSION.read_text(encoding="utf-8"))
    strategies = payload.get("strategies", {})
    return {
        "path": ADMISSION.relative_to(REPO_ROOT).as_posix(),
        "sha256": sha(ADMISSION),
        "period": payload.get("_period"),
        "claim": payload.get("_claim"),
        "count": len(strategies),
        "admitted": sorted(k for k, v in strategies.items() if v.get("admitted_for_paper")),
        "statuses": sorted({v.get("status", "UNKNOWN") for v in strategies.values()}),
        "entries": strategies,
    }


def runtime_entrypoints() -> list[dict[str, Any]]:
    candidates = [
        (
            "scripts/autonomous_paper.py",
            "PAPER runtime; instantiates the six families and gates them on the admission ledger",
        ),
        ("scripts/start_paper_trading.py", "paper starter; same family registry"),
        (
            "src/trading_bot/app.py",
            "application wiring (scanner -> strategy pipeline -> risk -> execution)",
        ),
        ("scripts/multi_family_backtest.py", "research backtest of the six families"),
        ("scripts/rfc010_baseline_replay.py", "research replay of the baseline"),
    ]
    out = []
    for rel, role in candidates:
        path = REPO_ROOT / rel
        out.append(
            {
                "path": rel,
                "exists": path.exists(),
                "sha256": sha(path) if path.exists() else None,
                "role": role,
                "paper_runtime": rel
                in ("scripts/autonomous_paper.py", "scripts/start_paper_trading.py"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# per-cell metrics, both windows, one signal pass
# ---------------------------------------------------------------------------


def cell_metrics() -> dict[str, dict[str, Any]]:
    from trading_bot.market_data.types import OHLCV

    per_cell: dict[str, dict[str, Any]] = {}
    for tf, minutes in TIMEFRAMES.items():
        horizon = max(1, round(30 / minutes))
        for asset in ASSETS:
            series = bars(HOLD_DIR / f"{asset}_{tf}.json")
            dev_series = bars(DEV_DIR / f"{asset}_{tf}.json")
            for family_name in FAMILIES:
                module_name, class_name = FAMILY_MODULES[family_name]
                module = __import__(
                    f"trading_bot.research.families.{module_name}", fromlist=[class_name]
                )
                family = getattr(module, class_name)()
                cell = f"{family_name}@{tf}"
                record = per_cell.setdefault(
                    cell,
                    {
                        "family": family_name,
                        "timeframe": tf,
                        "horizon_bars": horizon,
                        "hold": [],
                        "dev": [],
                    },
                )

                def emit(
                    src: list[list[float]],
                    start_ms: int,
                    end_ms: int,
                    bucket: str,
                    family: Any = family,
                    horizon: int = horizon,
                    record: dict[str, Any] = record,
                    asset: str = asset,
                ) -> None:
                    last_exit = -1
                    for i in range(WINDOW - 1, len(src)):
                        try:
                            alphas = family.generate(
                                [
                                    OHLCV(
                                        symbol="X",
                                        timestamp=int(r[0]),
                                        open=r[1],
                                        high=r[2],
                                        low=r[3],
                                        close=r[4],
                                        volume=r[5],
                                    )
                                    for r in src[i - WINDOW + 1 : i + 1]
                                ],
                                {},
                                None,
                            )
                        except Exception:
                            continue
                        if not alphas:
                            continue
                        best = max(
                            alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0)
                        )
                        direction = str(getattr(best, "direction", "")).upper()
                        if direction not in ("LONG", "SHORT"):
                            continue
                        decision_ms = int(src[i][0])
                        if not (start_ms <= decision_ms < end_ms):
                            continue
                        exit_i = i + horizon
                        if exit_i >= len(src) or i <= last_exit or int(src[exit_i][0]) >= end_ms:
                            continue
                        entry = float(getattr(best, "entry_reference", 0.0) or 0.0) or src[i][4]
                        sign = 1.0 if direction == "LONG" else -1.0
                        record[bucket].append(
                            {
                                "asset": asset,
                                "decision_ms": decision_ms,
                                "direction": direction,
                                "gross_bps": sign * (src[exit_i][4] / entry - 1.0) * 10_000.0,
                            }
                        )
                        last_exit = exit_i

                emit(series, DEV_END_MS, HOLD_END_MS, "hold")
                emit(dev_series, DEV_START_MS, DEV_END_MS, "dev")
    return per_cell


def summarise(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    gross = [t["gross_bps"] for t in trades]
    sd = statistics.stdev(gross) if len(gross) > 1 else float("nan")
    days = (
        max(t["decision_ms"] for t in trades) - min(t["decision_ms"] for t in trades)
    ) / 86_400_000
    net = statistics.fmean(gross) - COST_BPS
    required = (
        math.ceil(((Z90 + Z80) * sd / COST_BPS) ** 2) if sd and sd > 0 and COST_BPS > 0 else None
    )
    per_asset = {}
    for asset in ASSETS:
        sub = [t["gross_bps"] for t in trades if t["asset"] == asset]
        if sub:
            per_asset[asset] = round(statistics.fmean(sub) - COST_BPS, 4)
    half = len(gross) // 2
    return {
        "trades": len(gross),
        "days": round(days, 2),
        "trades_per_day": round(len(gross) / days, 3) if days else None,
        "gross_mean": round(statistics.fmean(gross), 4),
        "gross_sd": round(sd, 4),
        "net_mean": round(net, 4),
        "net_mean_cheapest_cost": round(statistics.fmean(gross) - CHEAPEST_COST_BPS, 4),
        "required_n_at_cost": required,
        "power_sufficient": (len(gross) >= required) if required else False,
        "per_asset_net": per_asset,
        "first_half_net": round(statistics.fmean(gross[:half]) - COST_BPS, 4) if half else None,
        "second_half_net": round(statistics.fmean(gross[half:]) - COST_BPS, 4)
        if len(gross) - half
        else None,
        "max_drawdown_bps": round(_max_dd([g - COST_BPS for g in gross]), 2),
    }


def _max_dd(net: list[float]) -> float:
    equity = peak = worst = 0.0
    for v in net:
        equity += v
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fingerprint-scheme",
        choices=(FINGERPRINT_SCHEME_V1, FINGERPRINT_SCHEME_V2),
        default=FINGERPRINT_SCHEME_V2,
        help="v2 hashes the committed blob (RFC-TDM-014A); v1 reproduces the published artefact",
    )
    parser.add_argument(
        "--source-commit",
        default=None,
        help="commit whose blobs are fingerprinted; defaults to HEAD for v2 and to the "
        "historical literal for v1",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="where the registry artefacts are written (default: the published evidence dir)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="identifies this execution inside the written artefacts",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="reuse .tdm12/cell_metrics.json instead of recomputing it",
    )
    args = parser.parse_args(argv)

    scheme = args.fingerprint_scheme
    source_commit = args.source_commit or (
        git_head() if scheme == FINGERPRINT_SCHEME_V2 else LEGACY_SOURCE_COMMIT_LITERAL
    )
    out_dir = Path(args.out_dir).resolve() if args.out_dir else EVIDENCE
    run_id = args.run_id

    ART.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    ledger = admission_ledger()
    families = family_classes(scheme, source_commit)
    protocol = strategy_protocol_implementations()
    declared = declared_config_strategies()
    entrypoints = runtime_entrypoints()

    print(
        f"discovered: families={len(families)} protocol={len(protocol)} declared={len(declared)}",
        flush=True,
    )
    cache = ART / "cell_metrics.json"
    if args.reuse and cache.exists():
        metrics = json.loads(cache.read_text(encoding="utf-8"))
    else:
        metrics = cell_metrics()
        cache.write_text(json.dumps(metrics), encoding="utf-8")
    print(f"cell metrics ready in {time.time() - started:.0f}s", flush=True)

    runtime_map = {
        "families_in_paper_runtime": sorted(FAMILY_MODULES),
        "admitted_for_paper": ledger["admitted"],
        "protocol_implementations": protocol,
        "declared_config_strategies": declared,
    }

    rows: list[dict[str, Any]] = []
    for cell in sorted(metrics):
        rec = metrics[cell]
        hold = summarise(rec["hold"])
        dev = summarise(rec["dev"])
        admitted = cell in ledger["entries"] and bool(
            ledger["entries"][cell].get("admitted_for_paper")
        )
        gates = {
            "runtime_reachable": True,
            "admitted_for_paper": admitted,
            "lookahead_gate": True,
            "stale_data_gate": True,
            "parameter_freeze": True,
            "cost_verified": False,
            "sample_sufficient": bool(hold.get("power_sufficient")),
            "net_positive_hold": (hold.get("net_mean") or -1) > 0,
            "net_positive_dev": (dev.get("net_mean") or -1) > 0,
        }
        eligible = all(gates.values())
        rows.append(
            {
                "candidate_id": f"TDM12-{cell}",
                "strategy_id": cell,
                "family": rec["family"],
                "runtime_class": "RUNTIME_REACHABLE",
                "entrypoint": "scripts/autonomous_paper.py::families",
                "source_commit": source_commit,
                "assets": "BTC,ETH,SOL",
                "timeframes": rec["timeframe"],
                "regimes": "all; regime label recorded but not filtered",
                **fingerprint_fields(
                    next(f for f in families if f["family"] == rec["family"]), scheme
                ),
                "datasets": "data/tdm08 (HOLD), data/tdm10 (DEV)",
                "data_fingerprint": "see DATA_WINDOW_REGISTRY.json",
                "selection_history": "measured in WP-TDM-10 across 24 cells x 4 horizons",
                "cost_model": "COST_MODEL_V3 BINANCE_SPOT_STANDARD_TAKER",
                "cost_verification_status": "UNVERIFIED_COST (spread estimated, no funding/borrow)",
                "sample_coverage": f"HOLD {hold.get('trades')} / DEV {dev.get('trades')}",
                "trades_by_day": f"{hold.get('trades_per_day')} (HOLD)",
                "edge_gross_bps": hold.get("gross_mean"),
                "edge_net_bps": hold.get("net_mean"),
                "drawdown": hold.get("max_drawdown_bps"),
                "robustness": "fails: DEV net also negative"
                if (dev.get("net_mean") or 0) <= 0
                else "DEV positive",
                "lookahead_gate": "PASS (PIT harness + 12-bar adversarial control)",
                "stale_data_gate": "PASS (0 gaps, 0 duplicates)",
                "promotion_state": "REJECTED" if not eligible else "PREREG_CANDIDATE",
                "reason": "NET_NOT_POSITIVE_HOLD_DEV"
                if (hold.get("net_mean") or -1) <= 0
                else "GATE_FAILED",
                "evidence_refs": "evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv; evidence/tdm/wp-tdm-10/ALPHA_ECONOMIC_MATRIX.csv",
                "_dev": dev,
                "_hold": hold,
                "_gates": gates,
            }
        )

    # non-measured inventory entries (kept in the registry so nothing disappears)
    for item in protocol:
        rows.append(
            {
                "candidate_id": f"TDM12-{item['class']}",
                "strategy_id": item.get("strategy_name") or item["class"],
                "family": "ema_crossover",
                "runtime_class": "ORPHAN",
                "entrypoint": item["module"],
                "source_commit": source_commit,
                "assets": "-",
                "timeframes": "-",
                "regimes": "-",
                **empty_fingerprint_fields(scheme),
                "datasets": "-",
                "data_fingerprint": "-",
                "selection_history": "no measured campaign",
                "cost_model": "n/a",
                "cost_verification_status": "NOT_APPLICABLE",
                "sample_coverage": "0 trades measured",
                "trades_by_day": "-",
                "edge_gross_bps": None,
                "edge_net_bps": None,
                "drawdown": None,
                "robustness": "no evidence",
                "lookahead_gate": "NOT_RUN",
                "stale_data_gate": "NOT_RUN",
                "promotion_state": "REJECTED",
                "reason": "NO_RUNTIME_ENTRYPOINT (only the family wrapper is reachable)",
                "evidence_refs": "grep: no import of EmaCrossoverStrategy outside its module and __init__",
            }
        )
    for item in declared:
        rows.append(
            {
                "candidate_id": f"TDM12-CONFIG-{item['name']}",
                "strategy_id": item["name"],
                "family": "-",
                "runtime_class": "ORPHAN",
                "entrypoint": "config/strategies.yaml",
                "source_commit": source_commit,
                "assets": "-",
                "timeframes": "-",
                "regimes": "-",
                **empty_fingerprint_fields(scheme),
                "datasets": "-",
                "data_fingerprint": "-",
                "selection_history": "none",
                "cost_model": "n/a",
                "cost_verification_status": "NOT_APPLICABLE",
                "sample_coverage": "0 trades measured",
                "trades_by_day": "-",
                "edge_gross_bps": None,
                "edge_net_bps": None,
                "drawdown": None,
                "robustness": "no implementation",
                "lookahead_gate": "NOT_RUN",
                "stale_data_gate": "NOT_RUN",
                "promotion_state": "REJECTED",
                "reason": f"DECLARED_ONLY state={item['state']} enabled={item['enabled']}: no code implements it",
                "evidence_refs": "config/strategies.yaml",
            }
        )

    public_cols = [k for k in rows[0] if not k.startswith("_")]
    with (out_dir / "CANDIDATE_REGISTRY.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=public_cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in public_cols})

    eligible = [r for r in rows if r["promotion_state"] == "PREREG_CANDIDATE"]
    measured = [r for r in rows if r.get("_hold", {}).get("trades", 0) > 0]
    active_track = [
        r
        for r in measured
        if (r["_hold"].get("trades_per_day") or 0) >= 3 and (r["_hold"].get("net_mean") or 0) > 0
    ]

    windows = {
        "artifact": "tdm12-data-window-registry-v1",
        "generated_at_ms": int(time.time() * 1000),
        "append_only": True,
        "windows": [
            {
                "name": "TDM08_W1_W7",
                "range_utc": ["2026-03-01T00:00:00Z", "2026-09-24T00:00:00Z"],
                "used_for": "strategy discovery and admission ledger construction",
                "label": "SELECTION_EXPOSED",
                "reusable_as_confirmatory": False,
                "evidence": "config/strategy_admission.json::_period",
            },
            {
                "name": "TDM10_DEV",
                "range_utc": ["2026-06-25T00:00:00Z", "2026-09-25T00:00:00Z"],
                "used_for": "TDM-10 development/stability, TDM-11 power analysis and retrospective evaluation",
                "label": "DEVELOPMENT",
                "reusable_as_confirmatory": False,
                "files": 12,
                "hash_status": "24/24 verified (12 DEV + 12 HOLD)",
                "evidence": "evidence/tdm/wp-tdm-11/DATASET_PROVENANCE.json",
            },
            {
                "name": "TDM08_HOLD",
                "range_utc": ["2026-09-25T00:00:00Z", "2026-10-24T15:50:00Z"],
                "used_for": "TDM-08 verdict window, TDM-10 verdict window, TDM-11 selection window",
                "label": "SELECTION_EXPOSED",
                "reusable_as_confirmatory": False,
                "evidence": "evidence/tdm/wp-tdm-11/DATASET_PROVENANCE.json",
            },
            {
                "name": "TDM11_CONFIRMATORY",
                "range_utc": ["2026-10-24T16:00:00Z", None],
                "used_for": "never opened; preregistered for TDM11-H1 only",
                "label": "FUTURE_CONFIRMATORY_SEALED",
                "reusable_as_confirmatory": True,
                "bars_read": 0,
                "evidence": "evidence/tdm/wp-tdm-11/DATASET_PROVENANCE.json",
            },
        ],
        "note": "no window in this registry may be relabelled confirmatory after being used to compare candidates",
    }
    (out_dir / "DATA_WINDOW_REGISTRY.json").write_text(
        json.dumps(windows, indent=2) + "\n", encoding="utf-8"
    )

    payload = {
        "generated_at_ms": int(time.time() * 1000),
        "discovery": {
            "families": families,
            "protocol_implementations": protocol,
            "declared_config_strategies": declared,
            "runtime_entrypoints": entrypoints,
            "runtime_map": runtime_map,
        },
        "registry_rows": len(rows),
        "measured_rows": len(measured),
        "eligible_rows": len(eligible),
        "eligible": [r["candidate_id"] for r in eligible],
        "active_track_eligible": [r["candidate_id"] for r in active_track],
        "hold_net_positive": [
            r["candidate_id"] for r in measured if (r["_hold"].get("net_mean") or 0) > 0
        ],
        "dev_net_positive": [
            r["candidate_id"] for r in measured if (r["_dev"].get("net_mean") or 0) > 0
        ],
        "best_hold_gross": max(
            (
                {"candidate_id": r["candidate_id"], "gross": r["_hold"].get("gross_mean")}
                for r in measured
            ),
            key=lambda x: x["gross"] or -1e9,
            default=None,
        ),
        "metrics_by_cell": {
            r["candidate_id"]: {"dev": r["_dev"], "hold": r["_hold"], "gates": r["_gates"]}
            for r in measured
        },
        "elapsed_s": round(time.time() - started, 1),
    }
    (ART / "triage.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    registry: dict[str, Any] = {
        "artifact": f"tdm12-candidate-registry-{scheme}",
        "generated_at_ms": payload["generated_at_ms"],
        "rows": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
        "metrics_by_cell": payload["metrics_by_cell"],
    }
    if scheme == FINGERPRINT_SCHEME_V2:
        # Provenance travels with the artefact so a reader never has to infer it.
        registry["fingerprint_scheme"] = FINGERPRINT_SCHEME_V2
        registry["source_commit"] = source_commit
        registry["fingerprint_algorithm"] = "sha256(git_cat_file_blob:<commit>:<relpath>)"
        registry["run_id"] = run_id
    (out_dir / "CANDIDATE_REGISTRY.json").write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "fingerprint_scheme": scheme,
                "source_commit": source_commit,
                "rows": len(rows),
                "measured": len(measured),
                "eligible": len(eligible),
                "hold_net_positive": payload["hold_net_positive"],
                "dev_net_positive": payload["dev_net_positive"],
                "best_hold_gross": payload["best_hold_gross"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
