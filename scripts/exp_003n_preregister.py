"""exp_003n_preregister — freeze the gross-first screening before any result exists.

    ./.venv/Scripts/python.exe scripts/exp_003n_preregister.py
    ./.venv/Scripts/python.exe scripts/exp_003n_preregister.py --check

EXP-003M closed the door on the only candidate that survived EXP-003L: on a realistic
maker fill model the per-trade gross ceiling is 0.2669 USDT against a 0.75 USDT fee floor,
a coverage of 0.356x. That verdict does not say "the executor was wrong"; it says the
*gross* income of `5m/mean_reversion` cannot pay for a round trip. The question this
experiment inherits is therefore not how to fill better, but whether any mechanism already
present in this repository produces gross income that covers its own costs.

Two things must be true before a result may be looked at, and this script writes both:

* the **candidate surface** is fixed — which families exist, where they are wired, and how
  each one is classified (`RUNTIME_AUTHORITATIVE`, `RUNTIME_REACHABLE`, `TEST_ONLY`,
  `RESEARCH_ONLY`, `EXPERIMENTAL`). The classification is computed from the tree and its
  references, not typed from memory, and every entry carries the module digest it was read
  from.
* the **screening protocol** is fixed — partitions, horizons, cost model, gates, bootstrap,
  multiple-testing correction and decision rule. The holdout 2026-08-06 → 2026-08-20 is
  closed here and enforced by the runner and the verifier.

Nothing in this script reads a price. It hashes inputs (dataset, family modules, configs)
and refuses to overwrite an existing design, so the protocol cannot be edited after the
numbers are known.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"

EXPERIMENT = "EXP-003N-GROSS-FIRST-DISCOVERY-001"
SCHEMA = "AI_BOTS_003N_DESIGN_V1"
UNIVERSE_SCHEMA = "AI_BOTS_003N_STRATEGY_UNIVERSE_V1"

#: Computed from the datetimes, never typed, so the guard is right on the day it fires.
HOLDOUT_START = "2026-08-06T00:00:00Z"
HOLDOUT_END = "2026-08-20T00:00:00Z"

PARTITIONS: dict[str, tuple[str, str]] = {
    "IS": ("2026-06-21T00:00:00Z", "2026-07-11T00:00:00Z"),
    "VAL": ("2026-07-11T00:00:00Z", "2026-07-26T00:00:00Z"),
    "TEST": ("2026-07-26T00:00:00Z", "2026-08-06T00:00:00Z"),
}

TIMEFRAMES: dict[str, int] = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000}

#: The six AlphaFamilies the PAPER adapter already admits (003K). The list is literal and
#: checked against the adapter below: a seventh family appearing in code is a design change,
#: not a silent addition to the grid.
RUNTIME_FAMILIES: tuple[str, ...] = (
    "ema_crossover",
    "momentum",
    "breakout",
    "mean_reversion",
    "trend",
    "volatility",
)

#: WP-EDGE-015 families that are testable (the maker hypothesis is excluded: no fill model).
#: They are re-run here on a different venue, asset set and period; the earlier verdicts are
#: carried in the universe as prior evidence, never overwritten.
ALPHA15_FAMILIES: tuple[str, ...] = (
    "vol_regime_breakout",
    "trend_pullback",
    "mean_reversion_vol_liq",
)
ALPHA15_TIMEFRAMES: tuple[str, ...] = ("1h", "4h")

#: Forward horizons in bars after the entry bar. One rule, not a search per cell.
HORIZONS: tuple[int, ...] = (1, 3, 6, 12, 24, 48)

#: Stage 2 turns a signal into a closed trade with one frozen policy: an ATR(14) stop at
#: 2.0x, a horizon exit after 12 bars and nothing else. No target: a target would make the
#: gross a function of where the target sits rather than of the signal.
EXIT_POLICY: dict[str, Any] = {
    "atr_period": 14,
    "stop_atr_multiple": 2.0,
    "horizon_bars": 12,
    "target": "NONE",
    "intrabar": "stop_first: when a bar holds both the stop and the horizon price, the stop is taken",
    "entry": "open of the bar after the decision bar, plus the adverse price terms of the cost model",
    "exit": "open of the bar 12 bars later, or the stop level if the stop is touched first",
}

STAKE_USDT = 500.0
#: Published spot VIP0 taker fee, one side. The *comparable minimum* is the round trip.
FEE_BPS_PER_SIDE = 10.0
BNB_DISCOUNT = 0.75
FEE_FLOOR_BPS_NO_BNB = 2.0 * FEE_BPS_PER_SIDE
FEE_FLOOR_BPS_BNB = 2.0 * FEE_BPS_PER_SIDE * BNB_DISCOUNT

BOOTSTRAP = {
    "method": "moving block bootstrap over signals ordered in time",
    "block_days": 5,
    "resamples": 10_000,
    "seed": 20261020,
    "alpha": 0.05,
    "unit": "signed forward return in bps per signal",
}
MULTIPLE_TESTING = {
    "method": "Benjamini-Hochberg",
    "q": 0.10,
    "family": "every (candidate, horizon) cell tested in stage 1, then every surviving cell in stage 2",
}

GATES: dict[str, str] = {
    "S0_sample": "a cell needs >= 50 signals in RESEARCH, >= 20 in IS and >= 15 in VAL; below that the verdict is INSUFFICIENT_EVIDENCE, never a pass",
    "S1_existence": "in IS, the mean signed forward return at some horizon > 0 and its bootstrap 95% lower bound > 0",
    "S2_replication": "the same horizon has a positive mean in VAL, a block the horizon was not chosen on",
    "S3_economic": "VAL mean gross - full round-trip cost (fee + half spread + slippage + impact at 500 USDT) > 0, and the VAL mean gross at least covers the fee floor (20 bps, or 15 bps with the BNB discount)",
    "S4_multiple_testing": "the cell survives Benjamini-Hochberg at q = 0.10 inside its stage's test family",
    "S5_holdout_integrity": "no input row, signal or statistic covers 2026-08-06 -> 2026-08-20; the holdout is never read",
    "S6_governance": "config/runtime.yaml still declares paper with live_trading_enabled false, no live order exists, and this experiment changes no risk limit",
    "S7_null_baseline": "a coin-flip signal with the same cadence and the same exit policy must fail S1-S4; if it does not, the gates are measuring costs and not edge",
}

DECISION_RULES: dict[str, str] = {
    "ADVANCE_TO_VALIDATION": "S1, S2, S3 and S4 hold and the closed-trade view in VAL is net positive after full cost",
    "EXPERIMENT": "S1 holds and S2/S3 do not: the signal carries information this sample cannot turn into money",
    "REJECT": "S1 fails, or S1 holds but S3 shows the gross cannot cover even the fee floor",
    "INSUFFICIENT_EVIDENCE": "S0 fails, or the measurement depends on an input the experiment cannot verify",
    "NO_VIABLE_CANDIDATES": "no candidate reaches ADVANCE_TO_VALIDATION; the refuted hypotheses are listed with the measured deficit",
}

#: Prior verdicts this experiment inherits. Carried verbatim so a reader cannot mistake a
#: re-measurement for a fresh hypothesis.
PRIOR_EVIDENCE: dict[str, str] = {
    "EXP-003L": "the taker round trip is ~25.4 bps at 500 USDT; the best configuration's gross was 8.5 bps per trade and every other cell was negative",
    "EXP-003M": "5m/mean_reversion REJECT: the maker fill ceiling is 0.2669 USDT per closed trade against a 0.75 USDT fee floor (0.356x coverage)",
    "WP-EDGE-015": "NO_ECONOMIC_EDGE_FOUND on the 1h alt corpora: trend_pullback REJECT, vol_regime_breakout REJECT_OUTLIER_DRIVEN, mean_reversion_vol_liq EXPERIMENT_COST_FRAGILE, cross_sectional_rotation REJECT, maker hypothesis DEFER_NO_FILL_MODEL",
    "SOURCE-TO-RUNTIME": "all five cand001-cand003 arms REJECTED_INITIAL_EXPERIMENT with negative gross expectancy per trade",
    "STRATEGY_ADMISSION": "the authoritative ledger records NO_GROSS_EDGE or COST_KILLED for all 24 (family, timeframe) cells; the largest zero-cost gross is volatility@30m at 8.91 bps",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _parse_utc(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


#: Where a class may be wired. The order is the classification order.
LAYERS: dict[str, tuple[str, ...]] = {
    "runtime": ("src/trading_bot/autonomous",),
    "adapter": ("src/trading_bot/vision",),
    "research": ("src/trading_bot/research",),
    "scripts": ("scripts",),
    "tests": ("tests",),
}

#: The only config files that authorise execution; the admission ledger is evidence about
#: verdicts, not a wiring, so it is not one of them.
RUNTIME_CONFIGS: tuple[str, ...] = ("config/runtime.yaml", "config/strategies.yaml")


def _layer_of(path: Path) -> str | None:
    relative = str(path.relative_to(REPO)).replace("\\", "/")
    for layer, prefixes in LAYERS.items():
        if any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in prefixes):
            return layer
    return None


def _reference_index() -> dict[str, dict[str, list[str]]]:
    """symbol -> layer -> files that import it or call it, parsed from the AST.

    A name in a docstring is not a wiring. The AST sees `from x import Foo` and
    `Foo(...)`; it does not see prose, which is exactly the defect that would otherwise
    classify a class the adapter's own comment labels TEST_ONLY as reachable.
    """

    index: dict[str, dict[str, list[str]]] = {}
    roots = [REPO / prefix for layer in LAYERS.values() for prefix in layer]
    for root in dict.fromkeys(roots):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            layer = _layer_of(path)
            if layer is None or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:  # pragma: no cover - not our file to repair
                continue
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        names.add(alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.name.rsplit(".", 1)[-1])
                elif isinstance(node, ast.Call):
                    target = node.func
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        names.add(target.attr)
            relative = str(path.relative_to(REPO)).replace("\\", "/")
            for name in names:
                bucket = index.setdefault(name, {}).setdefault(layer, [])
                bucket.append(relative)
    return index


def _module_index() -> dict[str, dict[str, list[str]]]:
    """module stem -> layer -> files that import it (``from ... import`` included).

    A class used only by its own module — the machines behind ``run_family``, for instance —
    is still reachable if that module is imported somewhere else. Without this fallback the
    inventory would label a live research engine ``UNREFERENCED``.
    """

    index: dict[str, dict[str, list[str]]] = {}
    roots = [REPO / prefix for prefixes in LAYERS.values() for prefix in prefixes]
    for root in dict.fromkeys(roots):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            layer = _layer_of(path)
            if layer is None or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:  # pragma: no cover
                continue
            stems: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    stems.add(node.module.rsplit(".", 1)[-1])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        stems.add(alias.name.rsplit(".", 1)[-1])
            relative = str(path.relative_to(REPO)).replace("\\", "/")
            for stem in stems:
                index.setdefault(stem, {}).setdefault(layer, []).append(relative)
    return index


def _classify(
    module_path: str,
    class_name: str,
    index: dict[str, dict[str, list[str]]],
    modules: dict[str, dict[str, list[str]]],
    *,
    runtime_mentions: bool,
) -> tuple[str, dict[str, list[str]]]:
    """Classify from evidence; the rule that fired is the verdict's reason."""

    own = module_path.replace("\\", "/")
    hits = {
        layer: sorted({item for item in paths if item != own})
        for layer, paths in index.get(class_name, {}).items()
    }
    stem = own.rsplit("/", 1)[-1].removesuffix(".py")
    for layer, paths in modules.get(stem, {}).items():
        hits.setdefault(layer, [])
        hits[layer] = sorted(set(hits[layer]) | {item for item in paths if item != own})
    for layer in LAYERS:
        hits.setdefault(layer, [])
    if "research/experimental/" in own:
        return "EXPERIMENTAL", hits
    if hits["runtime"] or runtime_mentions:
        return "RUNTIME_AUTHORITATIVE", hits
    if hits["adapter"]:
        return "RUNTIME_REACHABLE", hits
    if hits["research"] or hits["scripts"]:
        return "RESEARCH_ONLY", hits
    if hits["tests"]:
        return "TEST_ONLY", hits
    return "UNREFERENCED", hits


def _strategy_classes(path: Path) -> list[str]:
    """Classes that implement a strategy, not the dataclasses that configure one."""

    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = {
            item.name
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if not name_is_strategy(node.name) or node.name in {"Machine", "MachineBase"}:
            continue
        if methods & {
            "generate",
            "family_name",
            "analyze",
            "evaluate",
            "propose",
            "decide",
            "on_closed_bar",
        }:
            found.append(node.name)
    return found


def name_is_strategy(name: str) -> bool:
    return name.endswith(("Family", "Strategy", "Machine"))


def build_universe() -> dict[str, Any]:
    """Every strategy-shaped object in the tree, with where it is wired and by what rule."""

    from trading_bot.research.economic_recovery.alpha15 import FAMILY_BY_NAME
    from trading_bot.vision.signal_sources import STRATEGY_SPECS

    adapter_ids = sorted(STRATEGY_SPECS)
    if adapter_ids != sorted(RUNTIME_FAMILIES):
        raise SystemExit(
            "[003n] REFUSED — the PAPER adapter admits "
            f"{adapter_ids} but the frozen design covers {sorted(RUNTIME_FAMILIES)}"
        )

    index = _reference_index()
    modules = _module_index()
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((REPO / "src" / "trading_bot" / "autonomous").glob("*.py"))
    )
    config_text = "\n".join(
        (REPO / name).read_text(encoding="utf-8", errors="replace")
        for name in RUNTIME_CONFIGS
        if (REPO / name).exists()
    )

    sources: list[tuple[str, str]] = []
    for base in ("families", "experimental"):
        for path in sorted((REPO / "src" / "trading_bot" / "research" / base).glob("*.py")):
            if path.name.startswith("_"):
                continue
            for name in _strategy_classes(path):
                sources.append((str(path.relative_to(REPO)).replace("\\", "/"), name))
    sources.extend(
        [
            ("src/trading_bot/strategies/ema_crossover.py", "EmaCrossoverStrategy"),
            ("src/trading_bot/research/managed_futures_v1.py", "ManagedFuturesV1"),
            ("src/trading_bot/research/small_capital_v1.py", "SmallCapitalV1"),
            (
                "src/trading_bot/research/small_capital_dual_momentum_v1.py",
                "SmallCapitalDualMomentumV1",
            ),
        ]
    )
    pit = REPO / "src" / "trading_bot" / "research" / "economic_recovery" / "pit15.py"
    if pit.exists():
        for name in _strategy_classes(pit):
            sources.append((str(pit.relative_to(REPO)).replace("\\", "/"), name))

    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for module_path, class_name in sources:
        if (module_path, class_name) in seen:
            continue
        seen.add((module_path, class_name))
        absolute = REPO / module_path
        if not absolute.exists():
            continue
        # A family/id named in the runtime's own source or execution config is wired even
        # when the class is reached through a registry rather than an import.
        runtime_mentions = class_name in runtime_text or class_name in config_text
        verdict, hits = _classify(
            module_path, class_name, index, modules, runtime_mentions=runtime_mentions
        )
        entries.append(
            {
                "module": module_path,
                "module_sha256": _sha256(absolute),
                "class": class_name,
                "classification": verdict,
                "references": {layer: paths[:6] for layer, paths in hits.items()},
                "screened_here": class_name
                in {
                    "EmaCrossoverFamily",
                    "MomentumFamily",
                    "BreakoutFamily",
                    "MeanReversionFamily",
                    "TrendFamily",
                    "VolatilityFamily",
                },
            }
        )

    alpha15 = [
        {
            "family": name,
            "classification": "RESEARCH_ONLY",
            "status": family.status,
            "parameters": family.parameters,
            "differs_from": list(family.differs_from),
            "untestable_reason": family.untestable_reason,
            "prior_verdict": "WP-EDGE-015 (see PRIOR_EVIDENCE)",
            "screened_here": name in ALPHA15_FAMILIES,
        }
        for name, family in sorted(FAMILY_BY_NAME.items())
    ]

    by_class: dict[str, int] = {}
    for entry in entries:
        by_class[entry["classification"]] = by_class.get(entry["classification"], 0) + 1
    return {
        "schema_version": UNIVERSE_SCHEMA,
        "experiment": EXPERIMENT,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git("rev-parse", "HEAD"),
        "counts": by_class,
        "entries": sorted(entries, key=lambda item: (item["module"], item["class"])),
        "alpha15_families": alpha15,
        "adapter_strategies": adapter_ids,
        "note": (
            "classification is computed from import/instantiation references, not from intent: "
            "RUNTIME_AUTHORITATIVE (src/trading_bot/autonomous or config), RUNTIME_REACHABLE "
            "(the PAPER adapter in src/trading_bot/vision), RESEARCH_ONLY (research or scripts), "
            "TEST_ONLY (tests only), EXPERIMENTAL (research/experimental)"
        ),
    }


def universe_md(universe: dict[str, Any]) -> str:
    lines = [
        "# STRATEGY UNIVERSE — EXP-003N",
        "",
        f"Computed from `{universe['commit'][:7]}` at {universe['generated_at_utc']}.",
        "A class counts as wired where an import or an instantiation exists, not where a name",
        "appears in prose. `scripts/exp_003n_preregister.py` derives every row.",
        "",
        "## Counts",
        "",
        "| classification | classes |",
        "| --- | ---: |",
    ]
    for label, count in sorted(universe["counts"].items()):
        lines.append(f"| `{label}` | {count} |")
    lines += [
        "",
        "## Classes",
        "",
        "| module | class | classification | screened here | references |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in universe["entries"]:
        refs = ", ".join(
            f"{layer}={len(paths)}" for layer, paths in sorted(entry["references"].items()) if paths
        )
        lines.append(
            f"| `{entry['module']}` | `{entry['class']}` | `{entry['classification']}` | "
            f"{'yes' if entry['screened_here'] else 'no'} | {refs or '—'} |"
        )
    lines += [
        "",
        "## WP-EDGE-015 families (configuration, not classes)",
        "",
        "| family | status | screened here | why it differs |",
        "| --- | --- | --- | --- |",
    ]
    for family in universe["alpha15_families"]:
        lines.append(
            f"| `{family['family']}` | `{family['status']}` | "
            f"{'yes' if family['screened_here'] else 'no'} | "
            f"{', '.join(family['differs_from']) or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _dataset_block() -> dict[str, Any]:
    manifest_path = DATASET / "DATASET_MANIFEST.json"
    block: dict[str, Any] = {
        "path": str(DATASET.relative_to(REPO)).replace("\\", "/"),
        "source": "frozen EXP-003K dataset (Binance spot /api/v3/klines, 1m)",
        "manifest_sha256": _sha256(manifest_path) if manifest_path.exists() else None,
        "symbols": {},
    }
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        path = DATASET / f"{symbol}.1m.jsonl.gz"
        if not path.exists():
            raise SystemExit(f"[003n] BLOCKED — missing {path}; regenerate the 003K dataset first")
        block["symbols"][symbol] = {
            "file": path.name,
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
    return block


def build_design() -> dict[str, Any]:
    from trading_bot.research.economic_recovery.alpha15 import FAMILY_BY_NAME
    from trading_bot.vision.signal_sources import STRATEGY_SPECS

    design: dict[str, Any] = {
        "schema_version": SCHEMA,
        "experiment": EXPERIMENT,
        "frozen_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git("rev-parse", "HEAD"),
        "question": (
            "Does any mechanism that already exists in this repository produce a gross income "
            "per signal that covers its own round-trip cost on valid, point-in-time bars?"
        ),
        "why_not_another_fill_model": (
            "EXP-003M measured that 5m/mean_reversion's most generous fill model still earns "
            "0.2669 USDT per closed trade against a 0.75 USDT fee floor. Modelling fills more "
            "carefully cannot create gross income; only a different gross can."
        ),
        "predecessor": {
            "path": str(PREDECESSOR.relative_to(REPO)).replace("\\", "/"),
            "seal_sha256": _sha256(PREDECESSOR / "SEAL.json")
            if (PREDECESSOR / "SEAL.json").exists()
            else None,
            "decision": _read_json(PREDECESSOR / "analysis" / "DECISION.json").get("verdict")
            if (PREDECESSOR / "analysis" / "DECISION.json").exists()
            else "UNKNOWN",
        },
        "prior_evidence": PRIOR_EVIDENCE,
        "dataset": _dataset_block(),
        "partitions": {name: {"start_utc": bounds[0], "end_utc": bounds[1]} for name, bounds in PARTITIONS.items()},
        "holdout": {
            "start_utc": HOLDOUT_START,
            "end_utc": HOLDOUT_END,
            "status": "CLOSED",
            "rule": (
                "no bar, signal, trade or statistic for this window is produced, stored or "
                "summarised; the runner and the verifier both refuse a row inside it"
            ),
        },
        "timeframes": TIMEFRAMES,
        "candidates": {
            "lane_a_runtime_families": [
                {
                    "id": strategy_id,
                    "family": STRATEGY_SPECS[strategy_id].family_name,
                    "module": str(
                        Path(STRATEGY_SPECS[strategy_id].family_cls.__module__.replace(".", "/"))
                    ),
                    "min_candles": STRATEGY_SPECS[strategy_id].min_candles,
                    "classification": STRATEGY_SPECS[strategy_id].classification,
                }
                for strategy_id in RUNTIME_FAMILIES
            ],
            "lane_b_alpha15_families": [
                {
                    "family": name,
                    "status": FAMILY_BY_NAME[name].status,
                    "parameters": FAMILY_BY_NAME[name].parameters,
                    "differs_from": list(FAMILY_BY_NAME[name].differs_from),
                }
                for name in ALPHA15_FAMILIES
            ],
            "timeframes_lane_a": list(TIMEFRAMES),
            "timeframes_lane_b": list(ALPHA15_TIMEFRAMES),
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "excluded": {
                "cand001-cand003": "already REJECTED_INITIAL_EXPERIMENT with negative gross expectancy per trade; re-running them would spend this experiment's sample on a refuted mechanism",
                "cross_sectional_rotation": "REJECT at WP-EDGE-015 and degenerate on three assets: a top-k rotation over BTC/ETH/SOL is a single-asset trend rule with extra steps",
                "maker_only_spread_capture": "DEFER_NO_FILL_MODEL, and EXP-003M now prices the fill side of it",
            },
        },
        "horizons_bars": list(HORIZONS),
        "exit_policy": EXIT_POLICY,
        "cost_model": {
            "stake_usdt": STAKE_USDT,
            "source": "trading_bot.research.economic_recovery.alpha15.cost_for (the same model EXP-003L and EXP-003M priced)",
            "fee_bps_per_side": FEE_BPS_PER_SIDE,
            "fee_floor_bps_no_bnb": FEE_FLOOR_BPS_NO_BNB,
            "fee_floor_bps_bnb": FEE_FLOOR_BPS_BNB,
            "components": "fee + half spread + slippage + impact per side, on both legs; the fee floor is the comparable minimum, the full round trip is the gate",
        },
        "statistics": {"bootstrap": BOOTSTRAP, "multiple_testing": MULTIPLE_TESTING},
        "gates": GATES,
        "decision_rules": DECISION_RULES,
        "invariants": {
            "config_sha256": {
                name: _sha256(REPO / "config" / name)
                for name in ("risk.yaml", "runtime.yaml", "vision.yaml")
            },
            "live_orders": 0,
            "risk_limits_unchanged": True,
        },
        "governance": {
            "live_trading": "DISABLED",
            "trades_authorized": 0,
            "paper_promotion": "NOT_AUTHORIZED",
            "builder_is_not_verifier": True,
            "false_success_target": 0,
        },
    }
    audit = _read_json(REPO / "config" / "strategy_admission.json")
    design["admission_snapshot"] = {
        "period": audit.get("_period"),
        "strategies": {
            key: {
                "status": value.get("status"),
                "expected_gross_edge_bps": value.get("expected_gross_edge_bps"),
                "admitted_for_paper": value.get("admitted_for_paper"),
            }
            for key, value in sorted(audit.get("strategies", {}).items())
        },
    }
    return design


def check(design: dict[str, Any]) -> int:
    """The design is only frozen if its inputs still hash the same."""

    problems: list[str] = []
    for name, digest in design["invariants"]["config_sha256"].items():
        current = _sha256(REPO / "config" / name)
        if current != digest:
            problems.append(f"config/{name} changed: {digest} -> {current}")
    for symbol, block in design["dataset"]["symbols"].items():
        path = DATASET / block["file"]
        if not path.exists():
            problems.append(f"dataset {symbol} is missing")
            continue
        if _sha256(path) != block["sha256"]:
            problems.append(f"dataset {symbol} changed")
    if design["holdout"]["status"] != "CLOSED":
        problems.append("holdout is not closed")
    for problem in problems:
        print(f"[003n] DRIFT — {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"[003n] design intact: {len(design['invariants']['config_sha256'])} configs, "
          f"{len(design['dataset']['symbols'])} datasets")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--check", action="store_true", help="re-verify the frozen inputs")
    args = parser.parse_args(argv)
    out = Path(args.out)

    if args.check:
        path = out / "design" / "DESIGN.json"
        if not path.exists():
            print(f"[003n] BLOCKED — {path} is missing", file=sys.stderr)
            return 2
        return check(_read_json(path))

    design_path = out / "design" / "DESIGN.json"
    if design_path.exists():
        print(
            f"[003n] REFUSED — {design_path} already exists. A frozen design is not edited "
            "after the first result; a changed protocol is a new experiment.",
            file=sys.stderr,
        )
        return 3

    design = build_design()
    universe = build_universe()
    _write_json(design_path, design)
    _write_json(out / "design" / "STRATEGY_UNIVERSE.json", universe)
    (out / "design" / "STRATEGY_UNIVERSE.md").write_text(
        universe_md(universe), encoding="utf-8", newline="\n"
    )
    print(f"[003n] frozen {design_path.relative_to(REPO)}")
    print(f"[003n]   commit={design['commit'][:7]} datasets={len(design['dataset']['symbols'])}")
    print(f"[003n]   cells: {len(RUNTIME_FAMILIES) * len(TIMEFRAMES)} lane A + "
          f"{len(ALPHA15_FAMILIES) * len(ALPHA15_TIMEFRAMES)} lane B, horizons={list(HORIZONS)}")
    print(f"[003n]   universe: {universe['counts']}")
    return check(design)


if __name__ == "__main__":
    raise SystemExit(main())
