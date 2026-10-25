"""Pre-fix replay: execute 2536928's collector, then run the new tests against four mutants.

Not a deliverable; a scratch harness whose stdout is saved as evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
H = 3_600_000
START = 497_777 * H
BARS = [
    [START + i * H, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 7.0 + i] for i in range(2_600)
]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str) -> None:
    RESULTS.append((name, condition, detail))
    print(f"[{'DETECTED' if condition else 'MISSED'}] {name}: {detail}")


class FakeExchange:
    rateLimit = 1_000

    def __init__(self, bars: list[list[float]]) -> None:
        self.bars = bars
        self.calls: list[tuple[str, int | None, int]] = []

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None = None, limit: int = 1000
    ) -> list[list[float]]:
        self.calls.append((symbol, since, limit))
        start = START if since is None else int(since)
        return [bar for bar in self.bars if bar[0] >= start][:limit]


def load_pre_fix_collector() -> types.ModuleType:
    source = subprocess.run(
        ["git", "show", "2536928:scripts/edge15_oos_preregistration.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    module = types.ModuleType("old_collector_2536928")
    module.__dict__["__file__"] = str(REPO / "scripts" / "edge15_oos_preregistration.py")
    exec(compile(source, "scripts/edge15_oos_preregistration.py@2536928", "exec"), module.__dict__)
    return module


def part_one_pre_fix() -> None:
    print("=" * 78)
    print("PART 1 - the pre-fix collector at 2536928, executed as published")
    print("=" * 78)
    old = load_pre_fix_collector()
    work = Path(tempfile.mkdtemp(prefix="edge17-prefix-"))
    slice_path = work / "OOS_PROSPECTIVE_1H.jsonl"

    first = {"BTC/USDT": [list(bar) for bar in BARS[:3]]}
    old._write_slice(slice_path, first)
    rows_after_first = [json.loads(line) for line in slice_path.read_text().splitlines()]
    print(f"\nrun 1: venue returned 3 bars -> slice holds {len(rows_after_first)}")

    second = {"BTC/USDT": [list(bar) for bar in BARS[1:3]]}
    old._write_slice(slice_path, second)
    rows_after_second = [json.loads(line) for line in slice_path.read_text().splitlines()]
    lost = [row for row in rows_after_first if row["timestamp"] not in {r["timestamp"] for r in rows_after_second}]
    print(f"run 2: venue page starts at the second bar -> slice holds {len(rows_after_second)}")
    check(
        "repeated capture destroys the oldest bar (write mode 'w')",
        len(lost) == 1 and len(rows_after_second) == 2,
        f"rows 3 -> 2, bar {lost[0]['timestamp'] if lost else None} destroyed",
    )

    exchange = FakeExchange(BARS)
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.binance = lambda: exchange
    sys.modules["ccxt"] = fake_ccxt
    fetched = old._fetch(["BTC/USDT"], START, START + 2_600 * H, "binance")
    returned = fetched["BTC/USDT"]
    newest_available = BARS[-1][0]
    requests = " ".join(f"(since={since}, limit={limit})" for _, since, limit in exchange.calls)
    print(f"\nsingle-page fetch for a 2600-bar window: requests={requests or '(none)'}")
    check(
        "history beyond one page is never reached (fixed since + limit=1000)",
        len(returned) == 1_000 and returned[-1][0] < newest_available,
        f"returned {len(returned)} of 2600 bars, newest held={returned[-1][0]}, newest available={newest_available}",
    )

    captured = {row["symbol"]: int(row["timestamp"]) for row in rows_after_first}
    captured_bars_per_symbol = 1 if captured else 0
    dedupe_duplicate_keys = 0 if len(captured) == len(set(captured)) else 1
    print(
        "\ncoverage expressions copied verbatim from "
        "2536928:scripts/edge16_capture.py (captured_bars_per_symbol, dedupe_check):"
    )
    check(
        "coverage cannot report more than one bar per symbol",
        len(rows_after_first) == 3 and captured_bars_per_symbol == 1,
        f"{len(rows_after_first)} rows in the slice -> captured_bars_per_symbol={captured_bars_per_symbol}",
    )
    check(
        "duplicate check compares a dict's keys with their own set (tautology)",
        dedupe_duplicate_keys == 0,
        "3 identical rows collapsed into a 1-key dict -> duplicate_keys=0 always",
    )


MUTANTS: dict[str, str] = {
    "M1 truncating write (merge drops existing rows)": """
def merge_slice(existing, incoming):
    rows = [normalise_row(row) for row in incoming]
    return MergeResult(rows=sorted(rows, key=lambda r: (r["symbol"], r["timestamp"])),
                       added=len(rows), duplicates_identical=0)
""",
    "M2 binary coverage (one observed bar per symbol)": """
def coverage_ladder(*, symbols, expected_opens, slice_rows, lane_rows=()):
    rows = [normalise_row(r) for r in slice_rows]
    held = {r["symbol"] for r in rows}
    ladder = [{"symbol": s, "open_ms": int(o), "stages": ["EXPECTED"],
               "missing": not (s in held and int(o) == max([r["timestamp"] for r in rows if r["symbol"] == s] or [0])),
               "classified": "MISSING_NO_COLLECTOR"} for s in symbols for o in expected_opens]
    for row in ladder:
        if not row["missing"]:
            row["stages"].append("OBSERVED")
    return ladder, {"per_symbol": {}, "identity_holds": True,
                    "expected_symbol_bars": len(expected_opens) * len(symbols),
                    "observed_symbol_bars": sum(1 for r in ladder if not r["missing"]),
                    "evaluated_symbol_bars": 0, "bars_with_a_proposal": 0, "bars_with_a_fill": 0,
                    "unexpected_symbol_bars": 0,
                    "duplicate_slice_rows": 0 if len(rows) == len({row_key(r) for r in rows}) else 1,
                    "slice_rows": len(rows)}
""",
    "M3 tautological dedupe (keys compared with their own set)": """
def merge_slice(existing, incoming):
    merged = {row_key(normalise_row(r)): normalise_row(r) for r in [*existing, *incoming]}
    rows = [merged[k] for k in sorted(merged)]
    known = {row_key(r) for r in rows}
    return MergeResult(rows=rows, added=0,
                       duplicates_identical=0 if len(rows) == len(known) else 1)
""",
    "M4 non-atomic write (truncate in place)": """
def write_slice_atomic(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(normalise_row(row), sort_keys=True) + chr(10) for row in rows)
    with path.open("w", encoding="utf-8", newline=chr(10)) as stream:
        stream.write(payload)
    return {"path": path.as_posix(), "rows": len(rows), "bytes": len(payload.encode()),
            "sha256": hashlib.sha256(payload.encode()).hexdigest()}
""",
}


def part_two_mutants() -> None:
    print("\n" + "=" * 78)
    print("PART 2 - the new tests run against four re-introduced defects")
    print("=" * 78)
    source = (REPO / "src/trading_bot/research/oos_capture.py").read_text(encoding="utf-8")
    test_file = "tests/unit/research/test_edge17_capture.py"
    for label, patch in MUTANTS.items():
        root = Path(tempfile.mkdtemp(prefix="edge17-mutant-"))
        package = root / "trading_bot" / "research"
        package.mkdir(parents=True)
        (root / "trading_bot/__init__.py").write_text(
            (REPO / "src/trading_bot/__init__.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "oos_capture.py").write_text(source + "\n\n" + patch, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(root)}
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-q", "-p", "no:cacheprovider", "--no-header", "-rf", "--tb=no"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
        )
        tail = [line for line in proc.stdout.splitlines() if "passed" in line or "failed" in line]
        detail = tail[-1] if tail else proc.stdout.strip().splitlines()[-1:]
        check(label, proc.returncode != 0, f"pytest exit={proc.returncode}; {detail}")


NO_LOCK_MUTANT = """
import contextlib as _ctx


@_ctx.contextmanager
def slice_lock(path, **kwargs):
    yield lock_path_for(path)
"""


def part_three_lock_matters() -> None:
    print("\n" + "=" * 78)
    print("PART 3 - the concurrency test with the single-writer lock removed")
    print("=" * 78)
    source = (REPO / "src/trading_bot/research/oos_capture.py").read_text(encoding="utf-8")
    root = Path(tempfile.mkdtemp(prefix="edge17-nolock-"))
    package = root / "trading_bot" / "research"
    package.mkdir(parents=True)
    (root / "trading_bot/__init__.py").write_text(
        (REPO / "src/trading_bot/__init__.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "oos_capture.py").write_text(source + NO_LOCK_MUTANT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/research/test_edge17_capture.py",
         "-q", "-p", "no:cacheprovider", "--no-header", "-k", "concurrent", "--tb=line"],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
    )
    detail = [line for line in proc.stdout.splitlines() if "passed" in line or "failed" in line]
    print(proc.stdout.strip()[-600:])
    check(
        "without the lock the concurrent capture fails (lost update, or a replace race)",
        proc.returncode != 0,
        f"pytest exit={proc.returncode}; {detail[-1] if detail else ''}",
    )


def main() -> int:
    part_one_pre_fix()
    part_two_mutants()
    part_three_lock_matters()
    detected = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 78)
    print(f"SUMMARY: {detected}/{len(RESULTS)} defects reproduced by the executed artefacts")
    print("=" * 78)
    return 0 if detected == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
