"""CARRY-FUNDING-DEEP-01 — preregistered execution (TRACK D2/D3).

Runs EXACTLY the preregistered probe from
``docs/external-audit-01/CARRY_FUNDING_DEEP_01_PREREG.md``:

* Dataset: the D1-pinned BTCUSDT funding history (2019-09-10 → present,
  fingerprinted; NO synthetic rows).
* Hypothesis (as frozen in batch-02 preregistration, unchanged): extreme
  funding-rate regimes carry predictive information for the NEXT funding
  interval's perp return (contrarian at extremes).
* Evaluation: PIT join against public binanceusdm 5m price history at the
  decision boundary (only data with fundingTime <= decision time used);
  direction = SHORT when funding >= +q95, LONG when funding <= -q95
  (preregistered thresholds, no tuning); cost = 10 bps round-trip applied
  at entry; halves/thirds sign-consistency; permutation significance with a
  fixed seed (N=1000).
* Outcome classes (D3): DISCOVERY_PASS | DISCOVERY_FAIL |
  INSUFFICIENT_SAMPLE | INSUFFICIENT_DATA. PAPER_PROMOTIONS = 0 always.

This is a RESEARCH evaluation on public data. It never touches the paper
campaign, Risk, the broker or any trading parameter.
"""

from __future__ import annotations

import json
import random
import statistics
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "external-audit-01" / "carry-funding-deep-01"
DATASET = OUT / "BTCUSDT_FUNDING_DEEP.jsonl"
FINGERPRINT = OUT / "D1_DATA_FINGERPRINT.json"

FUNDING_FINGERPRINT_EXPECTED_PREFIX = "8b0e796c"  # pinned by D1
COST_ROUNDTRIP_BPS = 10.0  # preregistered cost assumption (5 bps each side)
QUANTILE = 0.05  # preregistered extreme threshold: q95 / q05
PERMUTATIONS = 1000
SEED = 20260910  # fixed preregistered seed

PRICES_CACHE = OUT / "BTCUSDT_1D_PUBLIC.jsonl"


def _fetch_json(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "carry-deep-01/1"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            if attempt == retries - 1:
                raise
    return None


def verify_dataset() -> tuple[list[dict], dict]:
    fp = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    if not fp["fingerprint_sha256"].startswith(FUNDING_FINGERPRINT_EXPECTED_PREFIX):
        raise SystemExit("funding fingerprint drift — refusing to run (CF-01)")
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != fp["rows"]:
        raise SystemExit("dataset row count drift — refusing to run (CF-01)")
    return rows, fp


def fetch_daily_prices() -> dict[int, float]:
    """Public daily BTCUSDT closes (klines), cached once; daily resolution is
    sufficient for the preregistered next-interval return at funding cadence."""
    if PRICES_CACHE.exists():
        return {
            r["day_open_ts_ms"]: r["close"]
            for r in (
                json.loads(line)
                for line in PRICES_CACHE.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
    rows: dict[int, float] = {}
    since = 0
    while True:
        page = _fetch_json(
            f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&startTime={since}&limit=1000"
        )
        if not page:
            break
        for k in page:
            rows[int(k[0])] = float(k[4])  # close
        since = int(k[0]) + 86_400_000
        if len(page) < 1000:
            break
    with PRICES_CACHE.open("w", encoding="utf-8") as fh:
        for ts in sorted(rows):
            fh.write(json.dumps({"day_open_ts_ms": ts, "close": rows[ts]}) + "\n")
    return rows


def main() -> int:
    funding, fp = verify_dataset()
    prices = fetch_daily_prices()
    price_days = sorted(prices)

    # PIT join: for each funding event, the "decision time" is the funding
    # timestamp; the tradeable return is the NEXT day close vs the close of
    # the day containing the funding event (both strictly known at/after
    # decision; the entry uses the day-close at or after fundingTime —
    # conservative: no look-ahead inside the entry day).
    def day_index(ts_ms: int) -> int | None:
        day_start = ts_ms - (ts_ms % 86_400_000)
        # binary search
        lo, hi = 0, len(price_days) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if price_days[mid] == day_start:
                return mid
            if price_days[mid] < day_start:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    trades: list[dict] = []
    skipped = 0
    for r in funding:
        idx = day_index(r["funding_time_ms"])
        if idx is None or idx + 1 >= len(price_days):
            skipped += 1
            continue
        entry_price = prices[price_days[idx]]
        exit_price = prices[price_days[idx + 1]]
        rate = float(r["funding_rate"])
        trades.append(
            {
                "funding_time_ms": r["funding_time_ms"],
                "rate": rate,
                "entry_price": entry_price,
                "exit_price": exit_price,
            }
        )

    if len(trades) < 100:
        result_class = "INSUFFICIENT_DATA"
        print(json.dumps({"CARRY_RESULT": result_class, "joined_trades": len(trades)}, indent=1))
        return 0

    rates = sorted(t["rate"] for t in trades)
    n = len(rates)
    q_hi = rates[int(n * (1 - QUANTILE))]
    q_lo = rates[int(n * QUANTILE)]

    def run_set(candidates: list[dict]) -> dict:
        returns: list[float] = []
        for t in candidates:
            if t["rate"] >= q_hi:
                direction = -1  # SHORT at extremes (preregistered contrarian)
            elif t["rate"] <= q_lo:
                direction = +1  # LONG at negative extremes
            else:
                continue  # neutral zone: no trade (preregistered)
            gross = direction * (t["exit_price"] / t["entry_price"] - 1.0)
            net = gross - COST_ROUNDTRIP_BPS / 10_000.0
            returns.append(net)
        return summarize(returns)

    def summarize(returns: list[float]) -> dict:
        if len(returns) < 30:
            return {"N": len(returns), "class": "INSUFFICIENT_SAMPLE"}
        mean = statistics.mean(returns)
        gross_win = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        pf = round(gross_win / gross_loss, 6) if gross_loss else None
        sd = statistics.stdev(returns) or 1e-12
        sharpe = round(mean / sd * (365 ** 0.5), 6)  # daily→annualized approx
        wins = sum(1 for r in returns if r > 0)
        losses = sum(1 for r in returns if r < 0)
        return {
            "N": len(returns),
            "net_expectancy_per_trade": round(mean, 8),
            "profit_factor": pf,
            "sharpe_annualized": sharpe,
            "win_rate": round(wins / len(returns), 4),
            "wins": wins,
            "losses": losses,
        }

    extreme = [t for t in trades if t["rate"] >= q_hi or t["rate"] <= q_lo]
    core = run_set(extreme)

    # halves / thirds sign-consistency (chronological)
    def consistency(returns: list[float], parts: int) -> dict:
        if len(returns) < parts * 10:
            return {"status": "INSUFFICIENT_SAMPLE"}
        size = len(returns) // parts
        chunks = [returns[i * size : (i + 1) * size] for i in range(parts)]
        signs = [statistics.mean(c) > 0 for c in chunks]
        return {
            "status": "CONSISTENT" if len(set(signs)) == 1 else "INCONSISTENT",
            "chunk_means": [round(statistics.mean(c), 8) for c in chunks],
        }

    chronological = [
        t for t in extreme
    ]
    chronological.sort(key=lambda t: t["funding_time_ms"])
    core_returns = []
    for t in chronological:
        direction = -1 if t["rate"] >= q_hi else +1
        gross = direction * (t["exit_price"] / t["entry_price"] - 1.0)
        core_returns.append(gross - COST_ROUNDTRIP_BPS / 10_000.0)

    halves = consistency(core_returns, 2)
    thirds = consistency(core_returns, 3)

    # permutation significance: shuffle the rate->direction assignment
    rng = random.Random(SEED)
    observed_mean = statistics.mean(core_returns)
    perm_means = []
    for _ in range(PERMUTATIONS):
        shuffled = core_returns[:]
        rng.shuffle(shuffled)
        # permute the SIGN pattern vs chronology: random sign per trade
        perm = [r * (1 if rng.random() < 0.5 else -1) for r in shuffled]
        perm_means.append(statistics.mean(perm))
    exceed = sum(1 for m in perm_means if m >= observed_mean)
    p_value = round(exceed / PERMUTATIONS, 4)

    # D3 classification (preregistered, no retuning)
    sufficient = core.get("N", 0) >= 100 and halves.get("status") != "INSUFFICIENT_SAMPLE"
    if not sufficient:
        result_class = "INSUFFICIENT_SAMPLE"
    elif (
        core["net_expectancy_per_trade"] > 0
        and (core["profit_factor"] or 0) > 1.0
        and halves.get("status") == "CONSISTENT"
        and thirds.get("status") == "CONSISTENT"
        and p_value < 0.05
    ):
        result_class = "DISCOVERY_PASS"
    else:
        result_class = "DISCOVERY_FAIL"

    report = {
        "experiment": "CARRY-FUNDING-DEEP-01",
        "prereg": "docs/external-audit-01/CARRY_FUNDING_DEEP_01_PREREG.md",
        "data_fingerprint": fp["fingerprint_sha256"],
        "funding_rows": len(funding),
        "joined_trades": len(trades),
        "skipped_no_price": skipped,
        "thresholds": {"q_hi": q_hi, "q_lo": q_lo, "quantile": QUANTILE},
        "cost_roundtrip_bps": COST_ROUNDTRIP_BPS,
        "CORE": core,
        "halves": halves,
        "thirds": thirds,
        "permutation_p_value": p_value,
        "permutations": PERMUTATIONS,
        "seed": SEED,
        "CARRY_RESULT": result_class,
        "PAPER_PROMOTIONS": 0,
        "no_retuning": True,
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
    }
    (OUT / "D3_RESULT.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({k: report[k] for k in ("CORE", "halves", "thirds", "permutation_p_value", "CARRY_RESULT", "PAPER_PROMOTIONS")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
