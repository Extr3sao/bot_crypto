"""exp_003o_preregister — WP-003O-01: freeze the protocol before any comparison runs.

The protocol is written **once** and committed. ``--check`` only re-verifies the digest it
published; it never regenerates the file, so a later edit cannot masquerade as the frozen
design. That is the difference between a preregistration and a summary written afterwards.

Outputs
-------
``SIGNAL_SPECIFICATIONS.md``  the observable semantics of all 24 cells, read from code.
``design/PROTOCOL.json``      keys, calendar, tolerances, controls, acceptance, fixtures.
``design/PREREGISTRATION.md`` the same decisions in prose, with their limits.
``design/DESIGN.sha256``      the digest the reports must quote.

Usage
-----
``python scripts/exp_003o_preregister.py [--out DIR] [--check]``
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003o_contract import (  # noqa: E402
    DAY_MS,
    HOLDOUT,
    LANE_A_FAMILIES,
    LANE_A_WINDOW,
    LANE_B_FAMILIES,
    LANE_B_WARMUP,
    OUT,
    PARTITIONS,
    REPO as ROOT,
    SOURCE_003N,
    SYMBOLS,
    TIMEFRAME_MS,
    cell_inventory,
    parameter_hash,
    sha256_bytes,
    sha256_file,
    write_json,
)

PROTOCOL_SCHEMA = "AI_BOTS_003O_PROTOCOL_V1"

SPECIFICATIONS_MD = """# SIGNAL SPECIFICATIONS — EXP-003O

Semantics read from the frozen code at `scripts/exp_003n_screen.py`,
`src/trading_bot/research/families/*.py`, `src/trading_bot/indicators/builtin.py` and
`src/trading_bot/research/economic_recovery/pit15.py`. Every statement below is a property of
that code, including the parts a reader would not guess.

## 1. Data and calendar

- Minutes are the archived 1m klines of EXP-003K (`reports/ai-bots/EXP-003K-CANDIDATE-001/dataset`),
  one row per minute, `ts_ms` = the bar's **open** time.
- A bar of timeframe `T` aggregates `T / 1m` consecutive minutes **by position**, starting at
  the series' first minute; a trailing partial group is dropped, never padded. The series is
  86 400 minutes (2026-06-21 00:00 → 2026-08-19 23:59 UTC), evenly divisible by 5, 60 and 240,
  and has no gaps (verified: 86 399 deltas of exactly 60 000 ms in every symbol).
- The research series is cut at `bar_open_time < 2026-08-06T00:00:00Z`. No bar, signal or
  statistic at or after that instant is produced.
- **Availability convention** (declared, not observed): a bar whose open is `T` and whose
  interval is `I` holds the trades of `[T, T+I)` and is treated as available at `T+I`.
  `bar_close_time = data_available_at = T+I`, and `decision_time = data_available_at`.
  An entry that the decision triggers fills at the **open of the next bar**, whose own
  timestamp is also `T+I`; the contract therefore allows `decision_time == fill_time` and
  records it as a known optimism (no latency, no queue, no partial fill) rather than pretending
  the fill is observed.

## 2. Lane A — the six AlphaFamilies

Common to all six:

- **Decision window.** Each decision at bar index `i` is taken on the **80 bars ending at `i`**
  (`LANE_A_WINDOW = 80`, which is the frozen producer's `max(min_candles + 1, 80)`). Re-seeding
  an EMA on an 80-bar window is not the same number as running it over the whole series, so the
  window is part of the rule, not an implementation detail.
- **Decision instants.** Every bar from index 79 to the last bar of the research window.
  Indices 0..78 are `NOT_READY`.
- **Direction.** A signal is emitted at the close of bar `i`; the producer's forward-return
  code enters at the open of bar `i+1`. The signal is long or short only; nothing is emitted
  while a position is open, because lane A has no position state at all.
- **Indicators**, all computed on closes/volumes of that 80-bar window:
  - `EMA(p)`: seed = arithmetic mean of the first `p` closes of the window, then
    `ema = close*k + ema*(1-k)`, `k = 2/(p+1)`.
  - `RSI(14)`: Wilder. Seed = mean of the first 14 gains and of the first 14 losses of the
    window's 79 deltas; then `avg = (avg*(p-1) + value)/p`. `avg_loss == 0` returns `100.0`.
  - `ATR(14)`: true range per bar with the previous close (the window's first bar uses
    `high - low`); seed = mean of the first 14 TRs; Wilder smoothing. The family refuses to
    emit when `ATR <= 0`.
  - `MACD(12,26,9)`: EMA12 and EMA26 seeded on the window's closes; the fast series is aligned
    by dropping its first `26-12 = 14` values; the signal line is `EMA(9)` of the MACD series,
    seeded on its first 9 values; `histogram = macd - signal`.
  - `Bollinger(20, 2.0)`: mean and **population** standard deviation over the last 20 closes
    of the window (the current bar included).
  - `Momentum(10)`: `close[-1]/close[-11] - 1`.
  - `VolumeRelative(20)`: `volume[-1] / mean(volume[-21:-1])` — the current bar is excluded
    from its own baseline.

Per family:

| family | rule (long) | rule (short) | guard |
| --- | --- | --- | --- |
| `ema_crossover` | `EMA9 > EMA21` and `RSI14 > 50` | `EMA9 < EMA21` and `RSI14 < 50` | `ATR14 > 0` |
| `momentum` | `histogram > 0` and `Momentum10 > 0.005` | `histogram < 0` and `Momentum10 < -0.005` | `ATR14 > 0` |
| `breakout` | `close > max(high[-21:-1])` and `VolumeRelative20 >= 1.5` | `close < min(low[-21:-1])` and `VolumeRelative20 >= 1.5` | `ATR14 > 0` |
| `mean_reversion` | `close[-2] < lower` and `close[-1] > lower` | `close[-2] > upper` and `close[-1] < upper` | `ATR14 > 0` |
| `trend` | `EMA8 > EMA21 > EMA55` and `slope > 0.0005` | `EMA8 < EMA21 < EMA55` and `slope < -0.0005` | `ATR14 > 0`, `EMA55 > 0` |
| `volatility` | 6 consecutive squeeze bars, then `close > upper` | 6 consecutive squeeze bars, then `close < lower` | `ATR14 > 0` |

Three of those rules contain a detail that a paraphrase loses:

1. `trend` computes `slope` as `(EMA55(window) - EMA55(window[:-1])) / EMA55(window[:-1])`.
   The second value is a **55-EMA re-seeded on a 79-bar series**, not the previous value of the
   first series. Reproducing `slope` as a difference of consecutive EMA values of one series
   gives a different number.
2. `volatility` tests the squeeze on `window[:-i]` for `i = 6..1` while the released close is
   compared against the Bollinger bands of the **whole** window. The two band sets come from
   different prefixes by construction.
3. `mean_reversion` re-enters when the previous close was outside the band and the current close
   is back inside it. The band itself includes the current bar, so a violent bar can move the
   band it is being compared to.

## 3. Lane B — the three WP-EDGE-015 machines

- Stateful, streaming, one decision per closed bar, from bar 0. Warm-up is not a guard but a
  consequence: a rule whose input is `NaN` is false.
- `NOT_READY` is declared mechanically from the frozen inputs, not from the absence of signals:
  `vol_regime_breakout` and `mean_reversion_vol_liq` need 720 ATR values, and the ATR needs 24
  bars, so bar 743 is the first whose percentile exists; `trend_pullback` needs a 200-bar EMA and
  its value 24 bars back, so bar 223 is its first.
- **Parameter names lie about timeframes.** `channel_hours`, `percentile_window_hours`,
  `*_ema_hours` are consumed as **bar counts**. On 1h bars this coincides with the name; on 4h
  bars it does not (168 "hours" = 672 hours of wall clock). This is a defect of the inherited
  universe, reproduced as frozen (`DEF-003O-02`) and never silently repaired.
- `PercentileRank` fixes its bucket bounds from the first 720 known values, uses 50 buckets,
  clamps every later value into the outermost bucket, and returns
  `(count_below + 0.5*count_in_bucket) / 720`.
- Fill policy of the driver: a decision taken at the close of bar `t` fills at the open of `t+1`;
  an entry that would fill at the same instant as the previous exit is dropped; a position still
  open at the last bar is marked at that close with `is_mark=true` and is **not** a decision.
- **Direction** is long-only for all three machines. An exit decision is reported as
  `SIGNAL/FLAT` so that exits are compared too, not only entries.

## 4. What is compared

Only **decisions**: state, direction and decision instant, keyed by
`(cell_id, symbol, decision_time)`. Indicator values are not compared, and no numeric tolerance
is used for a decision: a float difference that changes a decision is a decision difference, and
a float difference that changes nothing is outside this experiment by design. That choice is
declared here, before any number exists, so it cannot be chosen after seeing a difference.

## 5. Known ambiguities that are reproduced, not repaired

| id | ambiguity | treatment |
| --- | --- | --- |
| `AMB-01` | `trend`'s slope is a difference of two differently-seeded EMAs | reproduced exactly; documented above |
| `AMB-02` | lane-B `*_hours` are bar counts | reproduced; flagged as `DEF-003O-02` |
| `AMB-03` | lane A has no position state, so a signal can fire on every bar of a trend | reproduced; it is a property of the screening, not of the verification |
| `AMB-04` | availability is `open + interval` by convention, never observed | declared; every row carries `data_available_at` |
| `AMB-05` | lane B 4h cells have 0 evaluable bars (276 bars, 744-bar warm-up) | `INSUFFICIENT_EVIDENCE_REAL_WINDOW`, never `PASS` |
"""

PREREGISTRATION_MD = """# PREREGISTRATION — EXP-003O — Independent Signal Regeneration

**Written and committed before any comparison ran.** The digest of `design/PROTOCOL.json`
travels inside every artefact this experiment produces, and `RUN_REPORT.json` states whether the
commit order actually makes this prospective (`prospective` is computed from Git, not typed by
hand).

## Question

Does the frozen signal producer of EXP-003N emit, at every evaluable instant of its own
calendar, the same decision that a separately written implementation derives from the same
bars — and if it does not, where exactly do they diverge?

This is a question about **causal correctness**, not about money. `ECONOMIC_EDGE` is
`NOT_EVALUATED` here and no cell can be promoted by passing.

## Unit of comparison

`EvaluationKey = (cell_id, symbol, decision_time)`, with

- `cell_id` = `family@timeframe` over the 24 cells 003N screened (6 lane-A families × 5m/1h/4h
  and 3 lane-B families × 1h/4h), three symbols each;
- `decision_time` = the bar close at which the decision was taken.

Every key carries one state: `SIGNAL` (with `LONG`, `SHORT` or `FLAT`), `NO_SIGNAL`,
`NOT_READY` or `NOT_EVALUABLE`. `NOT_READY` and `NOT_EVALUABLE` carry a reason code and are
**never** merged into `NO_SIGNAL`: a zero produced by a warm-up and a zero produced by a quiet
market are different facts.

## Frozen inputs

- The three 1m files of EXP-003K, by the digests `DESIGN.json` of 003N froze
  (`7fbdfefa…`, `cf04dc37…`, `33342aac…`), re-hashed at run time.
- The 003N seal (`SHA256SUMS.txt`, 29 files) verified before and after, and never written to.
- The 24 cells, their families and their parameters, copied into `design/PROTOCOL.json` with a
  `parameter_hash` per cell.
- The calendar rule per lane, the availability convention and the reason vocabulary.

## Independence

The rebuilder is `scripts/exp_003o_rebuilder.py`. It may import the standard library, `numpy`
and `scripts/exp_003o_contract.py` (cell ids, states, writers, a bar dataclass, a digest
helper). It may **not** import `trading_bot.research.families`, `trading_bot.indicators`,
`trading_bot.research.economic_recovery.pit15`, `trading_bot.vision.signal_sources`, nor read
`SIGNALS.jsonl.gz`, `SCREENING.json`, `VALIDATION.json` or any `*evaluations*` file.

That rule is not a promise. `scripts/exp_003o_verify.py` enforces it three ways: an AST scan of
the rebuilder's import graph, a static scan for the forbidden paths as string literals, and a
causal run of the rebuilder under an audit hook that raises on any `open` of a forbidden path.
`NEG-12` proves the third mechanism can fail.

## Order of work

1. `WP-00` baseline: seals, digests, cells, dependency map. **Done before this file.**
2. `WP-01` this protocol, **committed**. The commit hash is recorded in every report.
3. `WP-02` both producers run without reading each other: the independent rebuilder first, then
   the replay of the frozen producer.
4. `WP-03` parity join, PIT audit, prefix invariance, 12 negative controls, independence audit.
5. `WP-04` clean-checkout reproduction, reports, seal.

## Acceptance, decided in advance

| id | condition | if it fails |
| --- | --- | --- |
| `ACC-003O-01` | baseline inputs intact, 003N read-only | `BLOCKED` |
| `ACC-003O-02` | protocol committed before evaluation; `prospective` truthful | `INCOMPLETE` if not prospective |
| `ACC-003O-03` | all 24 cells have a traceable count and state | `INCOMPLETE` |
| `ACC-003O-04` | rebuilder isolated from the producer's signal and indicator code | `FAIL` |
| `ACC-003O-05` | exact coverage; 0 unexplained differences | `FAIL` |
| `ACC-003O-06` | `data_available_at <= decision_time` at every instant used | `FAIL` |
| `ACC-003O-07` | 12/12 negative controls effective and detected | `FAIL` / `INCOMPLETE` |
| `ACC-003O-08` | zero-sample families have an activating fixture and a quiet control | `INCOMPLETE_FUNCTIONAL_COVERAGE` |
| `ACC-003O-09` | verifier is not a builder; clean-checkout reproduction | `INCOMPLETE` |
| `ACC-003O-10` | holdout closed, 0 orders, `config/` untouched | `FAIL` |
| `ACC-003O-11` | reports and hashes complete; `FALSE_SUCCESS=0` | `INCOMPLETE` |
| `ACC-003O-12` | the verdict promotes nothing and re-prices nothing | `FAIL` |

## Two verdicts, never merged

- `TECHNICAL_SIGNAL_PARITY` — coverage, PIT, parity and controls. It can pass on a window too
  short to be economically meaningful; it says nothing about edge.
- `FULL_INDEPENDENT_CERTIFICATION` — the above **plus** functional coverage of every family
  (real sample or activating fixture) and a verifier that is not a builder. Lane B's 4h cells
  cannot have a real sample in a 46-day window, so this one is expected to be
  `INCOMPLETE_REAL_DATA_COVERAGE` unless the fixtures carry the functional weight — and the
  fixtures prove implementation behaviour, not regime coverage.

`ECONOMIC_EDGE = NOT_EVALUATED` in all cases. `STRATEGY_PROMOTION = DENIED`. `LIVE = DISABLED`.
`HOLDOUT = CLOSED`.

## What would make this file dishonest

Editing it after seeing a difference, adding a tolerance after a mismatch, dropping a cell that
fails, or reporting `PASS` because two empty lists matched. None of those is available here: the
digest is quoted by every downstream artefact, and the comparator's difference classes are a
closed list frozen in `PROTOCOL.json`.
"""


def _negative_controls() -> list[dict[str, Any]]:
    return [
        {
            "id": "NEG-01",
            "mutation": "a window that reaches one bar past the decision instant (shift(-1))",
            "expected": "PIT_VIOLATION",
        },
        {
            "id": "NEG-02",
            "mutation": "decide on a bar before it closes (decision_time = bar open)",
            "expected": "TIMING_MISMATCH",
        },
        {
            "id": "NEG-03",
            "mutation": "declare availability as the bar open instead of its close",
            "expected": "PIT_VIOLATION",
        },
        {
            "id": "NEG-04",
            "mutation": "centre the rolling window on future bars",
            "expected": "PIT_VIOLATION",
        },
        {
            "id": "NEG-05",
            "mutation": "change one frozen parameter",
            "expected": "PARAMETER_HASH_MISMATCH",
        },
        {
            "id": "NEG-06",
            "mutation": "delete a known signal from the independent stream",
            "expected": "MISSING_SIGNAL",
        },
        {
            "id": "NEG-07",
            "mutation": "add a spurious signal and a duplicate key",
            "expected": "EXTRA_SIGNAL",
        },
        {
            "id": "NEG-08",
            "mutation": "invert a direction and shift a signal one bar",
            "expected": "DIRECTION_MISMATCH",
        },
        {
            "id": "NEG-09",
            "mutation": "alter one byte of a bar file and duplicate a bar",
            "expected": "DATA_INTEGRITY_FAIL",
        },
        {
            "id": "NEG-10",
            "mutation": "relabel a NOT_READY instant as NO_SIGNAL",
            "expected": "STATE_MISMATCH",
        },
        {
            "id": "NEG-11",
            "mutation": "append future bars until a past decision changes",
            "expected": "PREFIX_INVARIANCE_FAIL",
        },
        {
            "id": "NEG-12",
            "mutation": "make the rebuilder read the published signal calendar",
            "expected": "INDEPENDENCE_VIOLATION",
        },
    ]


def _fixtures() -> list[dict[str, Any]]:
    """Frozen fixture specifications: deterministic synthetic series, no real data."""

    return [
        {
            "fixture_id": "vol_regime_breakout_active",
            "family": "vol_regime_breakout",
            "timeframe": "1h",
            "bars": 1400,
            "expected": "at least one ENTRY after bar 743",
            "generator": "synthetic_lcg_v1",
            "generator_seed": 11,
            "regime": "rising trend, sinusoidal volatility, breakout bar",
        },
        {
            "fixture_id": "vol_regime_breakout_quiet",
            "family": "vol_regime_breakout",
            "timeframe": "1h",
            "bars": 1400,
            "expected": "no ENTRY",
            "generator": "synthetic_lcg_v1",
            "generator_seed": 11,
            "regime": "flat drift, constant volatility: no breakout",
        },
        {
            "fixture_id": "trend_pullback_active",
            "family": "trend_pullback",
            "timeframe": "1h",
            "bars": 1400,
            "expected": "at least one ENTRY after bar 223",
            "generator": "synthetic_lcg_v1",
            "generator_seed": 7,
            "regime": "up trend with a pullback and a reclaim",
        },
        {
            "fixture_id": "trend_pullback_quiet",
            "family": "trend_pullback",
            "timeframe": "1h",
            "bars": 1400,
            "expected": "no ENTRY",
            "generator": "synthetic_lcg_v1",
            "generator_seed": 7,
            "regime": "monotone decline: the trend filter never allows a long",
        },
        {
            "fixture_id": "mean_reversion_vol_liq_active",
            "family": "mean_reversion_vol_liq",
            "timeframe": "1h",
            "bars": 1400,
            "expected": "at least one ENTRY after bar 743",
            "generator": "synthetic_lcg_v1",
            "generator_seed": 3,
            "regime": "range with a two-sigma flush on a volume spike",
        },
        {
            "fixture_id": "mean_reversion_vol_liq_quiet",
            "family": "mean_reversion_vol_liq",
            "timeframe": "1h",
            "bars": 1400,
            "expected": "no ENTRY",
            "generator": "synthetic_lcg_v1",
            "generator_seed": 3,
            "regime": "narrow range, no stretch and no volume spike",
        },
    ]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    ).stdout.strip()


def build(out: Path) -> dict[str, Any]:
    baseline = json.loads((out / "BASELINE_MANIFEST.json").read_text(encoding="utf-8"))
    cells: list[dict[str, Any]] = []
    for cell in cell_inventory():
        params = dict(cell["parameters"])
        cells.append({**cell, "parameter_hash": parameter_hash(params)})

    protocol: dict[str, Any] = {
        "schema_version": PROTOCOL_SCHEMA,
        "run_id": "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001",
        "frozen_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "experiment": "EXP-003N-GROSS-FIRST-DISCOVERY-001",
            "baseline_sha256": sha256_file(out / "BASELINE_MANIFEST.json"),
            "design_sha256": baseline["source_003n"]["design_sha256"],
            "screening_sha256": baseline["source_003n"]["screening_sha256"],
            "signals_sha256": baseline["source_003n"]["signals_sha256"],
            "dataset": baseline["dataset"],
        },
        "holdout": {"start_utc": HOLDOUT[0], "end_utc": HOLDOUT[1], "opened": False},
        "partitions": {name: list(window) for name, window in PARTITIONS.items()},
        "timeframes_ms": dict(TIMEFRAME_MS),
        "symbols": list(SYMBOLS),
        "cells": cells,
        "evaluation_contract": {
            "key": ["cell_id", "symbol", "decision_time"],
            "states": ["SIGNAL", "NO_SIGNAL", "NOT_READY", "NOT_EVALUABLE"],
            "directions": ["LONG", "SHORT", "FLAT"],
            "reason_codes": ["WARMUP", "IN_POSITION", "RULE_FALSE", "ENTRY_RULE", "EXIT_RULE"],
            "lane_a_window_bars": LANE_A_WINDOW,
            "lane_a_warmup_bars": LANE_A_WINDOW - 1,
            "lane_b_warmup_bars": dict(LANE_B_WARMUP),
            "states_never_merged": ["NOT_READY", "NOT_EVALUABLE"],
            "row_fields": [
                "cell_id",
                "symbol",
                "timeframe",
                "decision_ms",
                "bar_open_ms",
                "bar_close_ms",
                "data_available_ms",
                "state",
                "direction",
                "reason",
                "parameter_hash",
                "input_snapshot_hash",
                "window_first_ms",
                "window_last_ms",
                "window_bars",
                "producer",
            ],
        },
        "temporal_contract": {
            "bar_timestamp_is": "open",
            "availability_convention": "bar available at open + interval; never observed at finer granularity",
            "decision_time_equals": "bar close of the decision bar",
            "requirement": "data_available_ms <= decision_ms and window_last_ms + interval == decision_ms",
            "no_partial_bars": True,
            "aggregation": "positional complete groups from the first minute; trailing partial group dropped",
        },
        "comparator": {
            "join": "full outer join on the evaluation key",
            "exact_fields": ["state", "direction", "decision_ms"],
            "difference_classes": [
                "MISSING_EVALUATION",
                "EXTRA_EVALUATION",
                "EXTRA_SIGNAL",
                "MISSING_SIGNAL",
                "DIRECTION_MISMATCH",
                "STATE_MISMATCH",
                "TIMING_MISMATCH",
                "PIT_VIOLATION",
                "INPUT_MISMATCH",
                "PARAMETER_HASH_MISMATCH",
                "DUPLICATE_KEY",
                "CONTRACT_AMBIGUITY",
                "DATA_INTEGRITY_FAIL",
                "INDEPENDENCE_VIOLATION",
                "PREFIX_INVARIANCE_FAIL",
            ],
            "tolerances": {
                "timestamps": "exact (milliseconds)",
                "state": "exact",
                "direction": "exact",
                "indicator_floats": "not compared; a float difference that changes a decision is a decision difference",
            },
            "duplicate_keys": "a duplicate key in either stream is a failure, not a last-write-wins",
        },
        "negative_controls": _negative_controls(),
        "fixtures": _fixtures(),
        "acceptance": [
            "ACC-003O-01 baseline intact",
            "ACC-003O-02 protocol committed before evaluation",
            "ACC-003O-03 all 24 cells traceable",
            "ACC-003O-04 rebuilder isolated",
            "ACC-003O-05 exact coverage, 0 unexplained differences",
            "ACC-003O-06 data_available_ms <= decision_ms",
            "ACC-003O-07 12/12 negative controls",
            "ACC-003O-08 zero-sample families have fixtures",
            "ACC-003O-09 verifier independent and clean-checkout reproduced",
            "ACC-003O-10 holdout closed, 0 orders, config untouched",
            "ACC-003O-11 reports complete, FALSE_SUCCESS=0",
            "ACC-003O-12 no promotion, no re-pricing",
        ],
        "independence": {
            "rebuilder_module": "scripts/exp_003o_rebuilder.py",
            "forbidden_import_prefixes": [
                "trading_bot.research.families",
                "trading_bot.indicators",
                "trading_bot.research.economic_recovery",
                "trading_bot.vision.signal_sources",
                "exp_003n_screen",
            ],
            "forbidden_path_fragments": [
                "SIGNALS.jsonl.gz",
                "SCREENING.json",
                "VALIDATION.json",
                "evaluations",
            ],
            "allowed_shared": ["scripts/exp_003o_contract.py", "numpy", "standard library"],
        },
        "governance": {
            "builder_is_not_verifier": True,
            "false_success_target": 0,
            "live_trading": "DISABLED",
            "orders_authorised": 0,
            "paper_promotion": "NOT_AUTHORIZED",
            "economic_edge": "NOT_EVALUATED",
            "holdout": "CLOSED",
        },
        "defects_known_before_running": [
            {
                "id": "DEF-003O-02",
                "summary": "lane-B parameter names say hours but the machines consume bars",
                "effect": "4h cells run a ~4x longer rule than their names claim",
                "treatment": "reproduced, not repaired",
            },
            {
                "id": "DEF-003O-03",
                "summary": "lane A has no position state, so overlapping signals are emitted bar by bar",
                "effect": "signal counts are not trade counts",
                "treatment": "reproduced; the comparator counts decisions, not trades",
            },
        ],
    }
    return protocol


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O WP-01 preregistration")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    protocol_path = out / "design" / "PROTOCOL.json"
    digest_path = out / "design" / "DESIGN.sha256"

    if args.check:
        if not protocol_path.exists() or not digest_path.exists():
            print("[003o-prereg] FAIL — the protocol has not been written", file=sys.stderr)
            return 2
        digest = sha256_file(protocol_path)
        published = digest_path.read_text(encoding="utf-8").split()[0]
        if digest != published:
            print(
                f"[003o-prereg] FAIL — PROTOCOL.json digest {digest[:12]}… != published {published[:12]}…",
                file=sys.stderr,
            )
            return 3
        proto = json.loads(protocol_path.read_text(encoding="utf-8"))
        mismatched = [
            cell["cell_id"]
            for cell in proto["cells"]
            if parameter_hash(cell["parameters"]) != cell["parameter_hash"]
        ]
        if mismatched:
            print(f"[003o-prereg] FAIL — parameter hash drift: {mismatched[:3]}", file=sys.stderr)
            return 4
        print(f"[003o-prereg] OK — protocol {digest[:16]}… cells={len(proto['cells'])}")
        return 0

    if (out / "signals" / "independent_evaluations.jsonl.gz").exists():
        print(
            "[003o-prereg] REFUSED — evaluations already exist; a protocol is not frozen after them",
            file=sys.stderr,
        )
        return 5
    if protocol_path.exists():
        print(
            "[003o-prereg] REFUSED — PROTOCOL.json exists; a frozen protocol is never rewritten",
            file=sys.stderr,
        )
        return 6

    protocol = build(out)
    write_json(protocol_path, protocol)
    (out / "SIGNAL_SPECIFICATIONS.md").write_text(SPECIFICATIONS_MD, encoding="utf-8", newline="\n")
    (out / "design" / "PREREGISTRATION.md").write_text(
        PREREGISTRATION_MD, encoding="utf-8", newline="\n"
    )
    digest = sha256_file(protocol_path)
    digest_path.write_text(f"{digest}  PROTOCOL.json\n", encoding="utf-8", newline="\n")
    print(
        f"[003o-prereg] written  digest={digest[:16]}…  cells={len(protocol['cells'])}  "
        f"controls={len(protocol['negative_controls'])}  fixtures={len(protocol['fixtures'])}"
    )
    print(f"[003o-prereg] HEAD={_git('rev-parse', '--short', 'HEAD')} — commit design/ before running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
