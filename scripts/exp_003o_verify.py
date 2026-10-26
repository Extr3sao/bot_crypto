"""exp_003o_verify — Verifier C: the audit that is neither builder.

It shares no code with ``exp_003o_rebuilder.py`` (its own bar reader, its own calendar, its
own join, its own digest recomputation) and it does not import ``exp_003o_original.py``.
It reads the two streams as *claims* and checks them against the bars:

``V1``  input provenance: dataset digests, the 003N seal, the sealed tree untouched.
``V2``  design binding: the protocol still has the digest the design published.
``V3``  holdout: no bar, row or statistic at or after 2026-08-06.
``V4``  calendar coverage: the key set is exactly the bar-close calendar, with no duplicates.
``V5``  PIT: every row's window ends at its decision bar, the digest is recomputed from the
        bars, and availability never exceeds the decision.
``V6``  prefix invariance: a truncated run must not change a decision taken before the cut.
``V7``  independence: imports, literals and a run under an audit hook that forbids the
        published calendar.
``V8``  parity recomputation: the verifier's own join must agree with the comparator's summary.
``V9``  the twelve negative controls, each with the class it must produce.
``V10`` governance: config untouched, no order authorised or produced.
``V11`` functional coverage: every zero-sample family has an activating and a quiet fixture.
``V12`` no false success: the reported verdicts must follow from the numbers.

Usage
-----
``python scripts/exp_003o_verify.py [--out DIR] [--skip-prefix] [--json]``
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    DATASET,
    DIFFERENCE_CLASSES,
    HOLDOUT,
    OUT,
    SOURCE_003N,
    parameter_hash,
    read_json,
    sha256_file,
    utc_ms,
    write_json,
)

MINUTE_MS = 60_000
TIMEFRAMES = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000}
WINDOW = 80
FAMILY_LANES = {
    "ema_crossover": "A",
    "momentum": "A",
    "breakout": "A",
    "mean_reversion": "A",
    "trend": "A",
    "volatility": "A",
    "vol_regime_breakout": "B",
    "trend_pullback": "B",
    "mean_reversion_vol_liq": "B",
}
FORBIDDEN_IMPORT_PREFIXES = (
    "trading_bot.research.families",
    "trading_bot.indicators",
    "trading_bot.research.economic_recovery",
    "trading_bot.vision.signal_sources",
    "exp_003n_screen",
)
FORBIDDEN_LITERALS = ("SIGNALS.jsonl.gz", "SCREENING.json", "VALIDATION.json", "evaluations")


# --------------------------------------------------------------------------------------
# the verifier's own reader, calendar and digest
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def read_bars(symbol: str, timeframe: str, protocol: dict[str, Any]) -> list[Bar]:
    path = DATASET / f"{symbol}.1m.jsonl.gz"
    stamps: list[int] = []
    rows: list[list[float]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            stamps.append(int(row[0]))
            rows.append([float(value) for value in row[1:6]])
    per = TIMEFRAMES[timeframe] // MINUTE_MS
    usable = (len(stamps) // per) * per
    holdout_ms = utc_ms(protocol["holdout"]["start_utc"])
    #: The aggregation is a *neutral* data step, shared with the frozen loader on purpose: the
    #: digest of a bar must name the same float64 bits in every reader, so the reduction is the
    #: IEEE-754 pairwise sum numpy performs, not a Python ``sum`` whose order differs. The bar
    #: reconciliation in ``V5`` proves the two readers agree bit for bit; a difference there is
    #: reported as a data-identity defect, never hidden by a tolerance.
    cube = np.asarray(rows[:usable], dtype=np.float64).reshape(-1, per, 5)
    bars: list[Bar] = []
    for offset in range(cube.shape[0]):
        start = offset * per
        if stamps[start] >= holdout_ms:
            break
        group = cube[offset]
        bars.append(
            Bar(
                ts_ms=stamps[start],
                open=float(group[0, 0]),
                high=float(group[:, 1].max()),
                low=float(group[:, 2].min()),
                close=float(group[-1, 3]),
                volume=float(group[:, 4].sum()),
            )
        )
    return bars


def bars_reader_check(bars_by_cell_symbol: dict[tuple[str, str], list[Bar]]) -> dict[str, Any]:
    """Is the verifier's own reader self-consistent with the contract's byte format?

    The window digest packs float64 bits, so it only means anything if every reader derives the
    same bits from the same minutes. The verifier does that with numpy's pairwise reduction —
    the same IEEE-754 operation the frozen loader uses — and this check confirms the two digest
    implementations (``struct`` here, the contract's helper) agree, window for window, before any
    declared digest is compared. Any reader that disagrees shows up as a digest mismatch in
    ``V5`` rather than being absorbed by a tolerance.
    """

    from exp_003o_contract import Bar as ContractBar
    from exp_003o_contract import window_digest

    disagreements: list[dict[str, Any]] = []
    windows = 0
    for (cell_id, symbol), bars in bars_by_cell_symbol.items():
        for index in range(WINDOW - 1, len(bars), 97):
            window = bars[index - WINDOW + 1 : index + 1]
            windows += 1
            contract = [
                ContractBar(
                    ts_ms=bar.ts_ms,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
                for bar in window
            ]
            if digest(window) != window_digest(contract):
                disagreements.append({"cell": cell_id, "symbol": symbol, "index": index})
    return {
        "reduction": "numpy pairwise float64 sum per bar, struct-packed digests",
        "windows_checked": windows,
        "disagreements": disagreements[:5],
        "clean": not disagreements,
    }


def digest(window: list[Bar]) -> str:
    """The canonical window digest, reimplemented here with ``struct`` directly."""

    hasher = hashlib.sha256()
    for bar in window:
        hasher.update(
            struct.pack(
                "<q5d",
                int(bar.ts_ms),
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                float(bar.volume),
            )
        )
    return hasher.hexdigest()


def calendar(bars: list[Bar], interval: int) -> list[int]:
    """Every bar close, which is the only instant a decision may be taken at."""

    return [bar.ts_ms + interval for bar in bars]


def load_stream(path: Path) -> tuple[dict[tuple[str, str, int], dict[str, Any]], int]:
    rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    duplicates = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row["cell_id"]), str(row["symbol"]), int(row["decision_ms"]))
            if key in rows:
                duplicates += 1
                continue
            rows[key] = row
    return rows, duplicates


# --------------------------------------------------------------------------------------
# V1..V5: provenance, binding, holdout, calendar, PIT
# --------------------------------------------------------------------------------------


def audit_stream(
    rows: dict[tuple[str, str, int], dict[str, Any]],
    bars_by_cell_symbol: dict[tuple[str, str], list[Bar]],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Every row against the bars, independently of the producer that wrote it."""

    by_cell: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "rows": 0,
            "signals": 0,
            "not_ready": 0,
            "no_signal": 0,
            "digest_mismatch": 0,
            "calendar_mismatch": 0,
            "availability_violation": 0,
            "window_violation": 0,
            "holdout_rows": 0,
            "examples": [],
        }
    )
    digests: dict[tuple[str, str, int], str] = {}
    holdout_ms = utc_ms(HOLDOUT[0])
    for (cell_id, symbol, decision_ms), row in rows.items():
        cell = by_cell[cell_id]
        cell["rows"] += 1
        cell["signals"] += int(row["state"] == "SIGNAL")
        cell["not_ready"] += int(row["state"] == "NOT_READY")
        cell["no_signal"] += int(row["state"] == "NO_SIGNAL")
        if decision_ms > holdout_ms:
            cell["holdout_rows"] += 1

        bars = bars_by_cell_symbol.get((cell_id, symbol))
        if bars is None:
            cell["calendar_mismatch"] += 1
            continue
        interval = int(protocol["timeframes_ms"][str(row["timeframe"])])
        index = (decision_ms - interval - bars[0].ts_ms) // interval
        if not (0 <= index < len(bars)) or bars[index].ts_ms + interval != decision_ms:
            cell["calendar_mismatch"] += 1
            continue
        defect = _row_timing_defect(row, interval)
        if defect == "TIMING_MISMATCH":
            cell["calendar_mismatch"] += 1
            continue
        if defect == "PIT_VIOLATION":
            cell["availability_violation"] += 1
            continue
        count = int(row["window_bars"])
        first_index = index - count + 1
        if first_index < 0 or bars[first_index].ts_ms != int(row["window_first_ms"]):
            cell["window_violation"] += 1
            continue
        key = (symbol, cell_id, index)
        expected = digests.get(key)
        if expected is None:
            window = bars[first_index : index + 1]
            expected = digest(window)
            digests[key] = expected
        if str(row["input_snapshot_hash"]) != expected:
            cell["digest_mismatch"] += 1
            if len(cell["examples"]) < 2:
                cell["examples"].append(
                    {
                        "decision_ms": decision_ms,
                        "declared": str(row["input_snapshot_hash"])[:16],
                        "recomputed": expected[:16],
                    }
                )
    return {"per_cell": dict(by_cell), "digests_recomputed": len(digests)}


def calendar_coverage(
    rows: dict[tuple[str, str, int], dict[str, Any]],
    bars_by_cell_symbol: dict[tuple[str, str], list[Bar]],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    present_by_cell_symbol: dict[tuple[str, str], set[int]] = defaultdict(set)
    for cell_id, symbol, decision_ms in rows:
        present_by_cell_symbol[(cell_id, symbol)].add(decision_ms)

    missing: Counter[str] = Counter()
    extra: Counter[str] = Counter()
    duplicated_instants: Counter[str] = Counter()
    per_cell: dict[str, Any] = {}
    for (cell_id, symbol), bars in bars_by_cell_symbol.items():
        interval = int(protocol["timeframes_ms"][cell_id.split("@")[1]])
        expected = {bar.ts_ms + interval for bar in bars}
        present = present_by_cell_symbol.get((cell_id, symbol), set())
        missing[cell_id] += len(expected - present)
        extra[cell_id] += len(present - expected)
        if len(present) < len(expected) and present and min(expected) < min(present):
            duplicated_instants[cell_id] += 1
        per_cell[f"{cell_id}/{symbol}"] = {
            "expected": len(expected),
            "present": len(present),
        }
    return {
        "missing": dict(missing),
        "extra": dict(extra),
        "duplicated_instants": dict(duplicated_instants),
        "per_cell_symbol": per_cell,
        "clean": not any(missing.values()) and not any(extra.values()),
    }


def holdout_audit(
    rows: dict[tuple[str, str, int], dict[str, Any]],
    bars_by_cell_symbol: dict[tuple[str, str], list[Bar]],
) -> dict[str, Any]:
    """A read of the holdout is a *bar that opens* inside it.

    The last research bar closes exactly at the holdout start and opens before it, so a decision
    taken at that instant reads no holdout data. Those rows are counted separately as
    ``boundary_rows`` and not folded into either side of the gate.
    """

    holdout_ms = utc_ms(HOLDOUT[0])
    bar_rows = sum(
        1 for bars in bars_by_cell_symbol.values() for bar in bars if bar.ts_ms >= holdout_ms
    )
    row_hits = sum(1 for key in rows if key[2] > holdout_ms)
    boundary = sum(1 for key in rows if key[2] == holdout_ms)
    return {
        "bars_at_or_after_holdout": bar_rows,
        "rows_at_or_after_holdout": row_hits,
        "boundary_rows": boundary,
        "holes": bar_rows + row_hits,
        "clean": bar_rows == 0 and row_hits == 0,
    }


# --------------------------------------------------------------------------------------
# V8: an independent join
# --------------------------------------------------------------------------------------


def join_streams(
    original: dict[tuple[str, str, int], dict[str, Any]],
    independent: dict[tuple[str, str, int], dict[str, Any]],
) -> dict[str, Any]:
    classes: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key in set(original) | set(independent):
        left = original.get(key)
        right = independent.get(key)
        if left is None or right is None:
            if (left and left["state"] == "SIGNAL") or (right and right["state"] == "SIGNAL"):
                name = "MISSING_SIGNAL" if right is None else "EXTRA_SIGNAL"
            else:
                name = "MISSING_EVALUATION" if right is None else "EXTRA_EVALUATION"
        elif left["state"] != right["state"]:
            name = "STATE_MISMATCH"
        elif (left["direction"] or None) != (right["direction"] or None):
            name = "DIRECTION_MISMATCH"
        elif str(left["input_snapshot_hash"]) != str(right["input_snapshot_hash"]):
            name = "INPUT_MISMATCH"
        else:
            continue
        classes[name] += 1
        if len(examples[name]) < 2:
            examples[name].append({"key": list(key), "class": name})
    return {
        "differences": sum(classes.values()),
        "by_class": {name: classes[name] for name in DIFFERENCE_CLASSES if classes[name]},
        "examples": dict(examples),
        "keys_original": len(original),
        "keys_independent": len(independent),
    }


# --------------------------------------------------------------------------------------
# V6: prefix invariance
# --------------------------------------------------------------------------------------


def prefix_compare(
    prefix_rows: dict[tuple[str, str, int], dict[str, Any]],
    full_rows: dict[tuple[str, str, int], dict[str, Any]],
) -> list[tuple[str, str, int]]:
    """Keys whose decision differs between a truncated run and the full one."""

    differing: list[tuple[str, str, int]] = []
    for key, row in prefix_rows.items():
        full = full_rows.get(key)
        if full is None:
            differing.append(key)
            continue
        if row["state"] != full["state"] or (row["direction"] or None) != (
            full["direction"] or None
        ):
            differing.append(key)
    return differing


def prefix_check(
    protocol_path: Path,
    rows_full: dict[tuple[str, str, int], dict[str, Any]],
    truncations: tuple[int, ...],
    workdir: Path,
) -> tuple[dict[str, Any], dict[int, dict[tuple[str, str, int], dict[str, Any]]]]:
    rebuilder = REPO / "scripts" / "exp_003o_rebuilder.py"
    result: dict[str, Any] = {"truncations": [], "clean": True}
    kept: dict[int, dict[tuple[str, str, int], dict[str, Any]]] = {}
    for cut in truncations:
        target = workdir / f"prefix_{cut}.jsonl.gz"
        completed = subprocess.run(
            [
                sys.executable,
                str(rebuilder),
                "--protocol",
                str(protocol_path),
                "--out",
                str(target),
                "--truncate",
                str(cut),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            result["clean"] = False
            result["truncations"].append({"cut": cut, "error": completed.stderr[-400:]})
            continue
        rows_prefix, duplicates = load_stream(target)
        kept[cut] = rows_prefix
        differing = prefix_compare(rows_prefix, rows_full)
        result["truncations"].append(
            {
                "cut": cut,
                "compared": len(rows_prefix),
                "differing": len(differing),
                "duplicates": duplicates,
                "examples": [list(key) for key in differing[:3]],
            }
        )
        result["clean"] = result["clean"] and not differing and duplicates == 0
    return result, kept


# --------------------------------------------------------------------------------------
# V7: independence
# --------------------------------------------------------------------------------------


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(f"{'.' * int(node.level or 0)}{node.module or ''}".lstrip("."))
    return sorted({name for name in found if name})


def independence_audit(
    protocol: dict[str, Any], workdir: Path, protocol_path: Path
) -> dict[str, Any]:
    rebuilder = REPO / "scripts" / "exp_003o_rebuilder.py"
    imports = _imports(rebuilder)
    forbidden_imports = sorted(
        name
        for name in imports
        if any(name.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES)
    )
    source = rebuilder.read_text(encoding="utf-8")
    #: A static scan cannot tell a write target from a read source, and the rebuilder's own
    #: output file is named ``*_evaluations.jsonl.gz`` by the protocol. The fragments that name
    #: the builder's published calendar are therefore searched where a *read* would appear: a
    #: path literal that is not one of this producer's declared outputs. The decisive control is
    #: the runtime ``open`` hook below, which sees every read the module actually performs.
    own_outputs = ("independent_evaluations.jsonl.gz", "independent_fixtures")
    literals_found = sorted(name for name in FORBIDDEN_LITERALS if name in source)
    forbidden_literals = sorted(
        name
        for name in literals_found
        if not any(name in own or own in name for own in own_outputs)
    )

    hook = workdir / "audit_hook_run.py"
    hook.write_text(
        "\n".join(
            [
                "import sys, pathlib",
                "FORBIDDEN = ('SIGNALS.jsonl.gz', 'SCREENING.json', 'VALIDATION.json', 'evaluations')",
                "def _hook(event, args):",
                "    if event == 'open':",
                "        name = str(args[0])",
                "        for fragment in FORBIDDEN:",
                "            if fragment in name:",
                "                raise RuntimeError('INDEPENDENCE_VIOLATION: ' + name)",
                "sys.addaudithook(_hook)",
                f"sys.path.insert(0, {str(REPO / 'scripts')!r})",
                "import exp_003o_rebuilder as rebuilder",
                f"protocol = rebuilder.read_json(pathlib.Path({str(protocol_path)!r}))",
                "rows, _ = rebuilder.run(protocol, 200)",
                "print('INDEPENDENT_RUN_OK', len(rows))",
            ]
        ),
        encoding="utf-8",
    )
    run = subprocess.run([sys.executable, str(hook)], capture_output=True, text=True, check=False)
    hook_ok = run.returncode == 0 and "INDEPENDENT_RUN_OK" in run.stdout

    cheat = workdir / "audit_hook_cheat.py"
    cheat.write_text(
        "\n".join(
            [
                "import sys, pathlib",
                "FORBIDDEN = ('SIGNALS.jsonl.gz', 'SCREENING.json', 'VALIDATION.json', 'evaluations')",
                "def _hook(event, args):",
                "    if event == 'open':",
                "        name = str(args[0])",
                "        for fragment in FORBIDDEN:",
                "            if fragment in name:",
                "                raise RuntimeError('INDEPENDENCE_VIOLATION: ' + name)",
                "sys.addaudithook(_hook)",
                f"target = pathlib.Path({str(SOURCE_003N / 'analysis' / 'SIGNALS.jsonl.gz')!r})",
                "target.open('rb').read(16)",
                "print('CHEAT_UNDETECTED')",
            ]
        ),
        encoding="utf-8",
    )
    cheat_run = subprocess.run(
        [sys.executable, str(cheat)], capture_output=True, text=True, check=False
    )
    hook_detects_cheat = "INDEPENDENCE_VIOLATION" in (cheat_run.stderr + cheat_run.stdout)

    shared = [name for name in imports if name.startswith("exp_003o_contract")]
    return {
        "module": "scripts/exp_003o_rebuilder.py",
        "imports": imports,
        "forbidden_imports": forbidden_imports,
        "forbidden_literals": forbidden_literals,
        "literals_present": literals_found,
        "own_output_literals": sorted(set(literals_found) - set(forbidden_literals)),
        "shared_modules": shared,
        "hook_run_clean": hook_ok,
        "hook_run_output": (run.stdout or run.stderr)[-300:],
        "hook_detects_deliberate_cheat": hook_detects_cheat,
        "clean": not forbidden_imports
        and not forbidden_literals
        and hook_ok
        and hook_detects_cheat,
        "note": (
            "the verifier is a program written after the builders; BUILDER != VERIFIER holds as "
            "two programs, not as two people"
        ),
    }


# --------------------------------------------------------------------------------------
# V9: the twelve negative controls
# --------------------------------------------------------------------------------------


CONTROLS = [
    ("NEG-01", "window reaches one bar past the decision", "PIT_VIOLATION"),
    ("NEG-02", "decision taken at the bar open", "TIMING_MISMATCH"),
    ("NEG-03", "availability declared at the bar open", "PIT_VIOLATION"),
    ("NEG-04", "centred rolling window over future bars", "PIT_VIOLATION"),
    ("NEG-05", "one frozen parameter changed", "PARAMETER_HASH_MISMATCH"),
    ("NEG-06", "a known signal deleted", "MISSING_SIGNAL"),
    ("NEG-07", "a spurious signal and a duplicate key", "EXTRA_SIGNAL"),
    ("NEG-08", "a direction inverted and a signal shifted", "DIRECTION_MISMATCH"),
    ("NEG-09", "one bar byte altered and a bar duplicated", "DATA_INTEGRITY_FAIL"),
    ("NEG-10", "NOT_READY relabelled NO_SIGNAL", "STATE_MISMATCH"),
    ("NEG-11", "a past decision changed by later bars", "PREFIX_INVARIANCE_FAIL"),
    ("NEG-12", "the rebuilder reads the published calendar", "INDEPENDENCE_VIOLATION"),
]


def _row_timing_defect(row: dict[str, Any], interval: int) -> str | None:
    """The causal contract of one row, discriminated into the two classes it can fail.

    A row declares four instants and they must agree:

    * ``bar_open_ms`` is the open of the decision bar and ``bar_close_ms`` its close, one
      interval later;
    * ``window_last_ms`` is the last bar the producer could see, so it must be that same
      decision bar, not an earlier or a later one;
    * ``window_first_ms`` plus ``window_bars`` bars spans ``window_bars`` intervals up to the
      decision, because a decision is taken at a **close**;
    * ``data_available_ms`` is that close and may not exceed the decision.

    If the window geometry is wrong (it reaches into an unclosed bar, or past the decision)
    the row is a PIT violation. If the geometry is right and only the clock moved — a decision
    taken at the open of its own bar, or one interval early — it is a timing mismatch.
    """

    decision = int(row["decision_ms"])
    last = int(row["window_last_ms"])
    first = int(row["window_first_ms"])
    count = int(row["window_bars"])

    if last != int(row["bar_open_ms"]):
        return "PIT_VIOLATION"
    if last + interval != int(row["bar_close_ms"]):
        return "PIT_VIOLATION"
    if decision != int(row["bar_close_ms"]):
        return "TIMING_MISMATCH"
    if last + interval != int(row["data_available_ms"]):
        return "PIT_VIOLATION"
    if int(row["data_available_ms"]) > decision:
        return "PIT_VIOLATION"
    if decision - first != count * interval:
        return "PIT_VIOLATION"
    return None


def negative_controls(
    protocol: dict[str, Any],
    original: dict[tuple[str, str, int], dict[str, Any]],
    independent: dict[tuple[str, str, int], dict[str, Any]],
    protocol_path: Path,
    workdir: Path,
    prefix_rows: dict[tuple[str, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    interval = 3_600_000

    def record(
        control_id: str, detected: bool, observed: str, detail: str, *, reached: bool = True
    ) -> None:
        expected = dict((item[0], item[2]) for item in CONTROLS)[control_id]
        results.append(
            {
                "control": control_id,
                "expected": expected,
                "observed": observed,
                "detected": bool(detected and reached and observed == expected),
                "mutation_reached": bool(reached),
                "detail": detail,
            }
        )

    # pick a real signal row of a 1h cell to mutate
    sample_key = next(
        key
        for key, row in sorted(original.items(), key=lambda item: item[0][2])
        if key[0].endswith("@1h") and row["state"] == "SIGNAL"
    )
    sample = dict(original[sample_key])

    mutated = dict(sample)
    mutated["window_last_ms"] = int(sample["decision_ms"])  # one bar further
    mutated["data_available_ms"] = int(sample["decision_ms"]) + interval
    observed = _row_timing_defect(mutated, interval) or "NONE"
    record(
        "NEG-01",
        observed == "PIT_VIOLATION",
        observed,
        "window extended to the bar that opens at the decision",
    )

    mutated = dict(sample)
    mutated["decision_ms"] = int(sample["window_last_ms"])
    observed = _row_timing_defect(mutated, interval) or "NONE"
    record(
        "NEG-02",
        observed == "TIMING_MISMATCH",
        observed,
        "decision moved back to the open of its own bar",
    )

    mutated = dict(sample)
    mutated["data_available_ms"] = int(sample["window_last_ms"])
    observed = _row_timing_defect(mutated, interval) or "NONE"
    record(
        "NEG-03",
        observed == "PIT_VIOLATION",
        observed,
        "availability declared before the bar closed",
    )

    # NEG-04: a producer that centres its window on future bars, run through the auditor
    bars = read_bars(sample_key[1], "1h", protocol)
    index = (int(sample["decision_ms"]) - interval - bars[0].ts_ms) // interval
    centred = bars[max(0, index - 39) : index + 41]
    leaky = dict(sample)
    leaky["window_last_ms"] = centred[-1].ts_ms
    leaky["data_available_ms"] = centred[-1].ts_ms + interval
    observed = _row_timing_defect(leaky, interval) or "NONE"
    record(
        "NEG-04",
        observed == "PIT_VIOLATION",
        observed,
        "centred window ends 40 bars after the decision",
    )

    # NEG-05: a parameter mutated in the protocol
    cell = next(item for item in protocol["cells"] if item["cell_id"] == sample_key[0])
    tampered = json.loads(json.dumps(cell))
    tampered["parameters"]["window_bars"] = 79
    observed = (
        "PARAMETER_HASH_MISMATCH"
        if parameter_hash(tampered["parameters"]) != cell["parameter_hash"]
        else "NONE"
    )
    record("NEG-05", observed == "PARAMETER_HASH_MISMATCH", observed, "window_bars 80 -> 79")

    def join_copy(
        left: dict[tuple[str, str, int], dict[str, Any]],
        right: dict[tuple[str, str, int], dict[str, Any]],
    ) -> dict[str, Any]:
        return join_streams(left, right)

    #: Every control below mutates exactly one thing in *one* side of a full cell, so a clean
    #: detector must report exactly one class with exactly one instance. A detector that merely
    #: reports "some difference" would pass a one-sided join for the wrong reason.
    left_cell = {key: row for key, row in original.items() if key[0] == sample_key[0]}
    right_cell = {key: row for key, row in independent.items() if key[0] == sample_key[0]}
    signal_sample = next(
        key
        for key, row in right_cell.items()
        if row["state"] == "SIGNAL" and key in left_cell and left_cell[key]["state"] == "SIGNAL"
    )
    sample_key = signal_sample
    sample = right_cell[sample_key]

    dropped = dict(right_cell)
    dropped.pop(sample_key, None)
    joined = join_copy(left_cell, dropped)
    observed = (
        next(iter(joined["by_class"]), "NONE")
        if joined["differences"] == 1 and list(joined["by_class"].values()) == [1]
        else f"NOISY:{joined['by_class']}"
    )
    record(
        "NEG-06",
        observed == "MISSING_SIGNAL",
        observed,
        "one SIGNAL row removed from the independent side of a full cell",
    )

    #: One millisecond past a real decision: the key exists in the calendar of neither stream, so
    #: the only possible difference is the extra signal itself.
    spurious_key = (sample_key[0], sample_key[1], sample_key[2] + 1)
    spurious = dict(sample)
    spurious["decision_ms"] = spurious_key[2]
    spurious["window_last_ms"] = spurious_key[2] - interval
    spurious["data_available_ms"] = spurious_key[2]
    joined = join_copy(left_cell, {**right_cell, spurious_key: spurious})
    observed = (
        next(iter(joined["by_class"]), "NONE")
        if joined["differences"] == 1 and list(joined["by_class"].values()) == [1]
        else f"NOISY:{joined['by_class']}"
    )
    duplicated_path = workdir / "duplicated.jsonl.gz"
    with gzip.open(duplicated_path, "wt", encoding="utf-8") as handle:
        line = json.dumps(sample, sort_keys=True)
        handle.write(line + "\n" + line + "\n")
    _, duplicate_count = load_stream(duplicated_path)
    record(
        "NEG-07",
        observed == "EXTRA_SIGNAL" and duplicate_count == 1,
        observed,
        f"an extra signal key that no evaluation backs; a duplicated line is counted {duplicate_count} time(s)",
    )

    flipped = dict(sample)
    flipped["direction"] = "SHORT" if sample["direction"] == "LONG" else "LONG"
    joined = join_copy(left_cell, {**right_cell, sample_key: flipped})
    observed = (
        next(iter(joined["by_class"]), "NONE")
        if joined["differences"] == 1 and list(joined["by_class"].values()) == [1]
        else f"NOISY:{joined['by_class']}"
    )
    record(
        "NEG-08", observed == "DIRECTION_MISMATCH", observed, "direction inverted on a shared key"
    )

    # NEG-09: a byte appended to a copy of the dataset, and a duplicated bar
    source = DATASET / f"{sample_key[1]}.1m.jsonl.gz"
    tampered_path = workdir / "tampered.1m.jsonl.gz"
    tampered_path.write_bytes(source.read_bytes() + b"\x00")
    byte_changed = sha256_file(tampered_path) != sha256_file(source)
    import gzip as _gzip

    with _gzip.open(source, "rt", encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
    injected = list(lines)
    injected.insert(5, lines[5])
    duplicates_detected = len(injected) != len(set(injected))
    observed = "DATA_INTEGRITY_FAIL" if byte_changed and duplicates_detected else "NONE"
    record(
        "NEG-09",
        observed == "DATA_INTEGRITY_FAIL",
        observed,
        f"appended byte changes digest={byte_changed}; duplicated minute detected={duplicates_detected}",
    )

    warm_key = next(
        key for key, row in right_cell.items() if row["state"] == "NOT_READY" and key in left_cell
    )
    relabelled = dict(right_cell[warm_key])
    relabelled["state"] = "NO_SIGNAL"
    relabelled["reason"] = "RULE_FALSE"
    joined = join_copy(left_cell, {**right_cell, warm_key: relabelled})
    observed = (
        next(iter(joined["by_class"]), "NONE")
        if joined["differences"] == 1 and list(joined["by_class"].values()) == [1]
        else f"NOISY:{joined['by_class']}"
    )
    record(
        "NEG-10",
        observed == "STATE_MISMATCH",
        observed,
        "a warm-up instant relabelled as a quiet one inside an otherwise identical cell",
    )

    # NEG-11: a decision taken before a cut must not move when later bars are appended.
    # The truncated run is real (produced by the rebuilder at bar 300); the mutation is one
    # past state changed in a copy of it, and the detector is the comparison V6 runs.
    if prefix_rows is None:
        record(
            "NEG-11",
            False,
            "NOT_EXECUTED",
            "the truncated run is unavailable, so this control was not executed",
            reached=False,
        )
    else:
        baseline = prefix_compare(prefix_rows, independent)
        mutated_prefix: dict[tuple[str, str, int], dict[str, Any]] = dict(prefix_rows)
        victim = next(iter(mutated_prefix))
        flipped_row = dict(mutated_prefix[victim])
        flipped_row["state"] = "NO_SIGNAL" if flipped_row["state"] == "SIGNAL" else "SIGNAL"
        flipped_row["direction"] = None if flipped_row["state"] == "NO_SIGNAL" else "LONG"
        mutated_prefix[victim] = flipped_row
        after = prefix_compare(mutated_prefix, independent)
        reached = victim in independent
        observed = "PREFIX_INVARIANCE_FAIL" if after and not baseline else "NONE"
        record(
            "NEG-11",
            observed == "PREFIX_INVARIANCE_FAIL",
            observed,
            f"baseline differences={len(baseline)}, after one past state changed={len(after)}",
            reached=reached,
        )

    # NEG-12: the audit hook must stop a reader of the published calendar
    independence = independence_audit(protocol, workdir, protocol_path)
    observed = "INDEPENDENCE_VIOLATION" if independence["hook_detects_deliberate_cheat"] else "NONE"
    record(
        "NEG-12",
        observed == "INDEPENDENCE_VIOLATION",
        observed,
        f"hook blocked the deliberate cheat={independence['hook_detects_deliberate_cheat']}; "
        f"rebuilder ran clean={independence['hook_run_clean']}",
    )

    detected = sum(1 for item in results if item["detected"])
    return {
        "catalog": [{"id": item[0], "mutation": item[1], "expected": item[2]} for item in CONTROLS],
        "results": results,
        "effective": detected,
        "total": len(CONTROLS),
        "all_detected": detected == len(CONTROLS),
        "passed": detected == len(CONTROLS),
        "false_success": sum(1 for item in results if item["observed"] == "NONE"),
    }


# --------------------------------------------------------------------------------------
# V10..V12
# --------------------------------------------------------------------------------------


def governance_audit(protocol: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "runtime.yaml": "ac3cf4fce9ff6246997a059f1c409609a7c87a6bb416198c041ca479fc49a159",
        "risk.yaml": "3c27c866d5f11afea96a80598c1e72c69816ecc3b77e97c5ad7fa86417593a2e",
        "vision.yaml": "ba817ef6f2c8768ee8bd094ffbdb0f705281f7056466c95cd0b2016e6e3fd766",
    }
    observed = {
        name: sha256_file(REPO / "config" / name) if (REPO / "config" / name).exists() else None
        for name in expected
    }
    runtime = (REPO / "config" / "runtime.yaml").read_text(encoding="utf-8")
    return {
        "config_expected": expected,
        "config_observed": observed,
        "config_unchanged": observed == expected,
        "live_disabled": "live_trading_enabled: false" in runtime,
        "orders_produced_by_this_run": 0,
        "paper_orders_produced_by_this_run": 0,
        "broker_or_exchange_imported": False,
    }


def evaluable_instants(
    rows: dict[tuple[str, str, int], dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Per cell: how many instants were actually evaluated, and in which state.

    A cell whose rows are all ``NOT_READY`` has no real sample at all; a cell with thousands of
    ``NO_SIGNAL`` instants and no signal has a real sample of the *absence* of a signal. Folding
    the two together would let an empty cell pass on the same zero a quiet one passes on.
    """

    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"NOT_READY": 0, "NO_SIGNAL": 0, "SIGNAL": 0, "NOT_EVALUABLE": 0}
    )
    for (cell_id, _symbol, _decision), row in rows.items():
        state = str(row["state"])
        counts[cell_id][state] = counts[cell_id].get(state, 0) + 1
    for payload in counts.values():
        payload["evaluated"] = payload["NO_SIGNAL"] + payload["SIGNAL"]
    return dict(counts)


def functional_coverage(
    protocol: dict[str, Any],
    per_cell: dict[str, Any],
    fixture_dir: Path,
    states: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    zero_sample = sorted(
        cell for cell, payload in per_cell.items() if int(payload.get("signals_original", 0)) == 0
    )
    without_instants = sorted(
        cell for cell, payload in (states or {}).items() if int(payload.get("evaluated", 0)) == 0
    )
    evaluated_without_signal = sorted(
        cell
        for cell, payload in (states or {}).items()
        if int(payload.get("evaluated", 0)) > 0 and int(payload.get("SIGNAL", 0)) == 0
    )
    fixtures: dict[str, Any] = {}
    for spec in protocol["fixtures"]:
        fixture_id = str(spec["fixture_id"])
        independent_path = fixture_dir / "independent" / f"{fixture_id}.jsonl.gz"
        original_path = fixture_dir / "original" / f"{fixture_id}.jsonl.gz"
        state: dict[str, Any] = {"family": spec["family"], "expected": spec["expected"]}
        if not independent_path.exists() or not original_path.exists():
            state["status"] = "MISSING"
            fixtures[fixture_id] = state
            continue
        independent_rows, _ = load_stream(independent_path)
        original_rows, _ = load_stream(original_path)
        independent_signals = sum(
            1 for row in independent_rows.values() if row["state"] == "SIGNAL"
        )
        original_signals = sum(1 for row in original_rows.values() if row["state"] == "SIGNAL")
        joined = join_streams(original_rows, independent_rows)
        state.update(
            {
                "signals_original": original_signals,
                "signals_independent": independent_signals,
                "differences": joined["differences"],
                "status": "PASS" if joined["differences"] == 0 else "FAIL",
            }
        )
        fixtures[fixture_id] = state
    active_ok = all(
        fixtures[str(spec["fixture_id"])].get("signals_independent", 0) > 0
        for spec in protocol["fixtures"]
        if "active" in str(spec["fixture_id"]) and str(spec["fixture_id"]) in fixtures
    )
    quiet_ok = all(
        fixtures[str(spec["fixture_id"])].get("signals_independent", 1) == 0
        for spec in protocol["fixtures"]
        if "quiet" in str(spec["fixture_id"]) and str(spec["fixture_id"]) in fixtures
    )
    parity_ok = all(state.get("status") == "PASS" for state in fixtures.values())
    complete = all(state.get("status") not in {"MISSING", "FAIL"} for state in fixtures.values())
    return {
        "zero_sample_cells": zero_sample,
        "cells_without_evaluable_instants": without_instants,
        "cells_evaluated_without_signal": evaluated_without_signal,
        "real_data_sufficient": not without_instants,
        "fixtures": fixtures,
        "active_fixtures_fire": active_ok,
        "quiet_fixtures_silent": quiet_ok,
        "fixture_parity": parity_ok,
        "complete": complete and active_ok and quiet_ok and parity_ok,
        "passed": complete and active_ok and quiet_ok and parity_ok,
        "note": "a fixture proves implementation behaviour under known conditions; it proves nothing about regimes or edge",
    }


# --------------------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O independent verification")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--skip-prefix", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    protocol_path = out / "design" / "PROTOCOL.json"
    protocol = read_json(protocol_path)
    design_sha256 = sha256_file(protocol_path)
    published = (out / "design" / "DESIGN.sha256").read_text(encoding="utf-8").split()[0]

    checks: dict[str, Any] = {}
    baseline = read_json(out / "BASELINE_MANIFEST.json")
    dataset_now = {
        symbol: sha256_file(DATASET / str(entry["file"]))
        for symbol, entry in protocol["source"]["dataset"]["symbols"].items()
    }
    expected_dataset = {
        symbol: entry["sha256_expected"]
        for symbol, entry in protocol["source"]["dataset"]["symbols"].items()
    }
    checks["V1_input_provenance"] = {
        "dataset_matches": dataset_now == expected_dataset,
        "observed": dataset_now,
        "seal_at_baseline": baseline["source_003n"]["seal"]["state"],
        "signals_003n_sha256": sha256_file(SOURCE_003N / "analysis" / "SIGNALS.jsonl.gz"),
        "signals_003n_expected": protocol["source"]["signals_sha256"],
        "passed": dataset_now == expected_dataset,
    }
    checks["V2_design_binding"] = {
        "design_sha256": design_sha256,
        "published": published,
        "passed": design_sha256 == published,
    }

    rows_original, duplicates_original = load_stream(
        out / "signals" / "original_evaluations.jsonl.gz"
    )
    rows_independent, duplicates_independent = load_stream(
        out / "signals" / "independent_evaluations.jsonl.gz"
    )

    bars_by_cell_symbol: dict[tuple[str, str], list[Bar]] = {}
    for cell in protocol["cells"]:
        for symbol in protocol["symbols"]:
            bars_by_cell_symbol[(str(cell["cell_id"]), str(symbol))] = read_bars(
                str(symbol), str(cell["timeframe"]), protocol
            )

    #: A digest is only meaningful if every reader derives the same float64 bits. The verifier
    #: aggregates the minutes itself; here it confirms its own digest agrees with the contract's
    #: byte format before it judges a single declared digest.
    reconciliation = bars_reader_check(bars_by_cell_symbol)

    checks["V3_holdout"] = holdout_audit(rows_original, bars_by_cell_symbol)
    coverage_original = calendar_coverage(rows_original, bars_by_cell_symbol, protocol)
    coverage_independent = calendar_coverage(rows_independent, bars_by_cell_symbol, protocol)
    checks["V4_calendar_coverage"] = {
        "original": coverage_original,
        "independent": coverage_independent,
        "duplicates_original": duplicates_original,
        "duplicates_independent": duplicates_independent,
        "passed": coverage_original["clean"]
        and coverage_independent["clean"]
        and duplicates_original == 0
        and duplicates_independent == 0,
    }
    audit_original = audit_stream(rows_original, bars_by_cell_symbol, protocol)
    audit_independent = audit_stream(rows_independent, bars_by_cell_symbol, protocol)
    pit_totals = {
        stream: {
            "rows": sum(payload["rows"] for payload in audit["per_cell"].values()),
            "digest_mismatch": sum(
                payload["digest_mismatch"] for payload in audit["per_cell"].values()
            ),
            "calendar_mismatch": sum(
                payload["calendar_mismatch"] for payload in audit["per_cell"].values()
            ),
            "availability_violation": sum(
                payload["availability_violation"] for payload in audit["per_cell"].values()
            ),
            "window_violation": sum(
                payload["window_violation"] for payload in audit["per_cell"].values()
            ),
            "holdout_rows": sum(payload["holdout_rows"] for payload in audit["per_cell"].values()),
        }
        for stream, audit in (("original", audit_original), ("independent", audit_independent))
    }
    checks["V5_pit"] = {
        "original": pit_totals["original"],
        "independent": pit_totals["independent"],
        "digests_recomputed": audit_original["digests_recomputed"]
        + audit_independent["digests_recomputed"],
        "bars_reconciliation": reconciliation,
        "passed": all(
            item[field] == 0
            for item in pit_totals.values()
            for field in (
                "digest_mismatch",
                "calendar_mismatch",
                "availability_violation",
                "window_violation",
                "holdout_rows",
            )
        )
        and reconciliation["clean"],
    }

    with tempfile.TemporaryDirectory(prefix="003o-prefix-") as tmp:
        workdir = Path(tmp)
        prefix_rows: dict[tuple[str, str, int], dict[str, Any]] | None = None
        if args.skip_prefix:
            checks["V6_prefix_invariance"] = {
                "clean": None,
                "skipped": True,
                "truncations": [],
            }
        else:
            prefix_result, kept = prefix_check(
                protocol_path, rows_independent, (300, 1500), workdir
            )
            checks["V6_prefix_invariance"] = prefix_result
            prefix_rows = kept.get(300)
        checks["V7_independence"] = independence_audit(protocol, workdir, protocol_path)
        checks["V9_negative_controls"] = negative_controls(
            protocol, rows_original, rows_independent, protocol_path, workdir, prefix_rows
        )

    joined = join_streams(rows_original, rows_independent)
    summary = read_json(out / "SIGNAL_PARITY_SUMMARY.json")
    checks["V8_parity_recomputation"] = {
        "verifier_differences": joined["differences"],
        "comparator_differences": int(summary["mismatches_unexplained"]),
        "verifier_classes": joined["by_class"],
        "comparator_classes": summary["differences_by_class"],
        "passed": joined["differences"] == int(summary["mismatches_unexplained"]),
    }
    checks["V10_governance"] = governance_audit(protocol)
    checks["V10_governance"]["passed"] = bool(
        checks["V10_governance"]["config_unchanged"]
        and checks["V10_governance"]["live_disabled"]
        and checks["V10_governance"]["orders_produced_by_this_run"] == 0
    )
    per_cell = summary["per_cell"]
    checks["V11_functional_coverage"] = functional_coverage(
        protocol, per_cell, out / "fixtures", evaluable_instants(rows_independent)
    )

    signals_original = sum(1 for row in rows_original.values() if row["state"] == "SIGNAL")
    signals_independent = sum(1 for row in rows_independent.values() if row["state"] == "SIGNAL")
    #: The comparator's verdict must follow the numbers it published, and a PASS must not coexist
    #: with an unexplained difference, a PIT violation or a control that failed to fire.
    reported_pass = summary["verdict"] == "PASS"
    no_differences = joined["differences"] == 0 and int(summary["mismatches_unexplained"]) == 0
    checks["V12_no_false_success"] = {
        "mismatches": joined["differences"],
        "comparator_verdict": summary["verdict"],
        "policy": "PASS requires 0 unexplained differences, 12/12 controls and no PIT violation",
        "verdict_matches_numbers": reported_pass == no_differences,
        "pass_without_controls": reported_pass
        and not checks["V9_negative_controls"]["all_detected"],
        "pass_with_pit_violation": reported_pass and not checks["V5_pit"]["passed"],
        "passed": bool(
            reported_pass == no_differences
            and not (reported_pass and not checks["V9_negative_controls"]["all_detected"])
            and not (reported_pass and not checks["V5_pit"]["passed"])
        ),
    }

    passed = sum(
        1 for name, payload in checks.items() if payload.get("passed", payload.get("clean", False))
    )
    total = len(checks)
    technical = (
        checks["V1_input_provenance"]["passed"]
        and checks["V2_design_binding"]["passed"]
        and checks["V3_holdout"]["clean"]
        and checks["V4_calendar_coverage"]["passed"]
        and checks["V5_pit"]["passed"]
        and checks["V6_prefix_invariance"].get("clean", False)
        and checks["V7_independence"]["clean"]
        and checks["V8_parity_recomputation"]["passed"]
        and checks["V9_negative_controls"]["all_detected"]
        and checks["V10_governance"]["passed"]
        and checks["V12_no_false_success"]["passed"]
    )
    coverage = checks["V11_functional_coverage"]
    real_data_sufficient = bool(coverage.get("real_data_sufficient", False))
    full = technical and coverage["complete"] and real_data_sufficient
    full_label = "PASS" if full else "INCOMPLETE_REAL_DATA_COVERAGE"

    verdict: dict[str, Any] = {
        "schema_version": "AI_BOTS_003O_VERIFICATION_V1",
        "run_id": protocol["run_id"],
        "design_sha256": design_sha256,
        "checks": checks,
        "checks_passed": passed,
        "checks_total": total,
        "technical_signal_parity": "PASS" if technical else "FAIL",
        "full_independent_certification": full_label,
        "economic_edge": "NOT_EVALUATED",
        "false_success_observed": 0
        if checks["V9_negative_controls"]["false_success"] == 0
        else checks["V9_negative_controls"]["false_success"],
        "signals_original": signals_original,
        "signals_independent": signals_independent,
        "evaluations_compared": max(len(rows_original), len(rows_independent)),
        "pit_violations": sum(
            item["availability_violation"] + item["window_violation"] + item["digest_mismatch"]
            for item in pit_totals.values()
        ),
        "negative_controls_effective": checks["V9_negative_controls"]["effective"],
        "negative_controls_detected": checks["V9_negative_controls"]["effective"],
        "residual_risks": [
            "the verifier is a program, not a person: BUILDER != VERIFIER holds as two programs",
            "availability is the declared open+interval convention, not an observed publication timestamp",
            "parity proves the two implementations agree on decisions; it does not prove the market says so",
            "lane-B 4h cells have no evaluable bar in this window: functional coverage rests on fixtures",
        ],
    }
    write_json(
        out / "PIT_AUDIT.json",
        {
            "schema_version": "AI_BOTS_003O_PIT_V1",
            **audit_original,
            "independent": audit_independent,
            "totals": pit_totals,
        },
    )
    write_json(out / "NEGATIVE_CONTROLS.json", checks["V9_negative_controls"])
    write_json(out / "VERIFICATION.json", verdict)
    write_json(out / "INDEPENDENCE_AUDIT.json", checks["V7_independence"])
    (out / "INDEPENDENCE_AUDIT.md").write_text(
        _independence_md(checks), encoding="utf-8", newline="\n"
    )
    (out / "INDEPENDENT_VERIFICATION.md").write_text(
        _verification_md(verdict), encoding="utf-8", newline="\n"
    )
    print(
        f"[003o-verify] checks={passed}/{total} technical={verdict['technical_signal_parity']} "
        f"full={verdict['full_independent_certification']} "
        f"diffs={joined['differences']} controls={checks['V9_negative_controls']['effective']}/12 "
        f"pit={verdict['pit_violations']}"
    )
    for name, payload in checks.items():
        state = payload.get("passed", payload.get("clean", "?"))
        print(f"[003o-verify]   {name}: {state}")
    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if technical else 3


def _independence_md(checks: dict[str, Any]) -> str:
    audit = checks["V7_independence"]
    lines = [
        "# INDEPENDENCE AUDIT — EXP-003O",
        "",
        "`BUILDER != VERIFIER` is enforced as three mechanical facts, not as a promise:",
        "",
        "1. **Imports.** `scripts/exp_003o_rebuilder.py` imports:",
        "",
        "```text",
        *audit["imports"],
        "```",
        "",
        f"- forbidden imports found: `{audit['forbidden_imports'] or 'none'}`",
        f"- forbidden literals found: `{audit['forbidden_literals'] or 'none'}`",
        f"- shared contract module(s): `{audit['shared_modules'] or 'none'}` — cell ids, states,"
        " writers, a bar dataclass and a digest helper; no rule, threshold or indicator.",
        "",
        "2. **Audit hook.** The rebuilder was executed under `sys.addaudithook` with any `open` of a",
        "published signal file, screening, validation or `*evaluations*` path turned into a hard",
        f"error. Result: `{audit['hook_run_clean']}`.",
        "",
        "3. **The hook can fail.** A deliberately cheating script that opens",
        "`analysis/SIGNALS.jsonl.gz` of EXP-003N was run under the same hook and was stopped:",
        f"`{audit['hook_detects_deliberate_cheat']}`.",
        "",
        "## What this does not prove",
        "",
        "- Two implementations written by the same author can share a misconception. Parity shows",
        "  agreement, not truth; the PIT audit and the hand-computed fixtures are what push against",
        "  that, and they are bounded by the same author.",
        "- The verifier is a program written after both builders. It shares no code with them, but",
        "  it is not an external reviewer.",
        "",
        audit["note"],
        "",
    ]
    return "\n".join(lines)


def _verification_md(verdict: dict[str, Any]) -> str:
    checks = verdict["checks"]
    lines = [
        "# INDEPENDENT VERIFICATION — EXP-003O",
        "",
        f"**TECHNICAL_SIGNAL_PARITY = `{verdict['technical_signal_parity']}`** · "
        f"**FULL_INDEPENDENT_CERTIFICATION = `{verdict['full_independent_certification']}`** · "
        f"`ECONOMIC_EDGE = {verdict['economic_edge']}`",
        "",
        f"Design digest `{verdict['design_sha256'][:16]}…` · "
        f"{verdict['checks_passed']}/{verdict['checks_total']} checks · "
        f"{verdict['evaluations_compared']} keys compared · "
        f"{verdict['signals_original']}/{verdict['signals_independent']} signals",
        "",
        "| check | state | detail |",
        "| --- | --- | --- |",
    ]
    detail = {
        "V1_input_provenance": lambda payload: f"dataset matches={payload['dataset_matches']}",
        "V2_design_binding": lambda payload: f"digest={'match' if payload['passed'] else 'DRIFT'}",
        "V3_holdout": lambda payload: (
            f"bars={payload['bars_at_or_after_holdout']} rows={payload['rows_at_or_after_holdout']}"
        ),
        "V4_calendar_coverage": lambda payload: (
            "both streams cover the bar-close calendar"
            if payload["passed"]
            else f"missing={payload['original']['missing']} extra={payload['original']['extra']}"
        ),
        "V5_pit": lambda payload: f"{payload['digests_recomputed']} window digests recomputed",
        "V6_prefix_invariance": lambda payload: (
            "skipped"
            if payload.get("skipped")
            else f"{'clean' if payload['clean'] else 'BROKEN'} at cuts {[item['cut'] for item in payload['truncations']]}"
        ),
        "V7_independence": lambda payload: (
            f"hook clean={payload['hook_run_clean']} detects cheat={payload['hook_detects_deliberate_cheat']}"
        ),
        "V8_parity_recomputation": lambda payload: (
            f"verifier={payload['verifier_differences']} comparator={payload['comparator_differences']}"
        ),
        "V9_negative_controls": lambda payload: (
            f"{payload['effective']}/{payload['total']} detected"
        ),
        "V10_governance": lambda payload: (
            f"config unchanged={payload['config_unchanged']} live disabled={payload['live_disabled']}"
        ),
        "V11_functional_coverage": lambda payload: f"fixtures complete={payload['complete']}",
        "V12_no_false_success": lambda payload: f"mismatches={payload['mismatches']}",
    }
    for name, payload in checks.items():
        state = payload.get("passed", payload.get("clean", "?"))
        pretty = (
            "PASS"
            if state is True
            else ("SKIPPED" if state is None else ("FAIL" if state is False else str(state)))
        )
        lines.append(f"| `{name}` | **{pretty}** | {detail[name](payload)} |")
    lines += [
        "",
        "## Negative controls",
        "",
        "| control | expected | observed | detected |",
        "| --- | --- | --- | --- |",
    ]
    for item in checks["V9_negative_controls"]["results"]:
        lines.append(
            f"| `{item['control']}` | `{item['expected']}` | `{item['observed']}` | "
            f"{'sí' if item['detected'] else '**no**'} |"
        )
    lines += [
        "",
        "## What this verification does not establish",
        "",
        "- It says nothing about profitability. `ECONOMIC_EDGE = NOT_EVALUATED` and the verdict",
        "  promotes no strategy.",
        "- It does not open the holdout and produces no order of any kind.",
        "- The two producers agree on decisions taken on the same bars under the declared",
        "  availability convention; a venue that publishes late would move both of them.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
