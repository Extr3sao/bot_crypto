"""Labelled SYNTHETIC controls for the multi-family entrypoint. No real data, no economic claim.

Every dataset here is a seeded random walk generated in a temp directory; the
repository is never written. The controls exist to turn three read claims into
observations:

  C1  an exception inside a family is indistinguishable from "no signal"
  C2  the field named `gross` already contains slippage
  C3  the DEV/VAL/OOS split is inferred from the filename prefix, and a dataset
      outside W1..W7 contributes to `totals` only, silently
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
tmp = Path(tempfile.mkdtemp(prefix="wp005_synth_"))
data = tmp / "data"
data.mkdir()
outdir = tmp / "out"
outdir.mkdir()


def make_bars(n: int = 400, seed: int = 7, start: int = 1_600_000_000_000) -> list[dict]:
    rnd = random.Random(seed)
    price, bars = 30_000.0, []
    for i in range(n):
        drift = rnd.gauss(0.0, 0.0015)
        op = price
        price = price * (1 + drift)
        hi = max(op, price) * (1 + abs(rnd.gauss(0, 0.0006)))
        lo = min(op, price) * (1 - abs(rnd.gauss(0, 0.0006)))
        bars.append({"ts": start + i * 300_000, "open": round(op, 2), "high": round(hi, 2),
                     "low": round(lo, 2), "close": round(price, 2), "volume": round(rnd.uniform(1, 50), 3)})
    return bars


def load():
    spec = importlib.util.spec_from_file_location("multi_family_backtest",
                                                 root / "scripts" / "multi_family_backtest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DATA = str(data)
    module.OUTDIR = str(outdir)
    return module


def run(label: str) -> dict:
    for f in outdir.glob("*.json"):
        f.unlink()
    module = load()
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        module.main()
    payload = json.loads((outdir / "MULTI_FAMILY_RESULTS.json").read_text(encoding="utf-8"))
    print(f"--- {label} | stderr/traceback emitted for a failing family: "
          f"{'YES' if 'Traceback' in buf.getvalue() else 'NO'}")
    return payload


def summarise(payload: dict, families=("ema_crossover", "momentum")) -> None:
    for fam in families:
        base = payload[fam]["BASE"]
        zero = payload[fam]["ZERO_COST"]
        print(f"  {fam:15s} BASE trades={base['totals']['trades']:3d} gross={base['totals']['gross']:10.2f} "
              f"fees={base['totals']['fees']:8.2f} net={base['totals']['net']:10.2f} | "
              f"ZERO_COST gross={zero['totals']['gross']:10.2f} fees={zero['totals']['fees']:6.2f} "
              f"net={zero['totals']['net']:10.2f}")
        print(f"  {'':15s} split trades dev={base['DEV_W1_W4']['trades']} val={base['VAL_W5_W6']['trades']} "
              f"oos={base['OOS_W7']['trades']} per_window={sorted(base['per_window'])}")


# C2/C3 baseline: a correctly named dataset
(data / "BTCUSDT_W1.json").write_text(json.dumps(make_bars()), encoding="utf-8")
print("== CONTROL 1: one W1 dataset ==")
p = run("W1 dataset present")
summarise(p)
trades_base = {fam: p[fam]["BASE"]["totals"]["trades"] for fam in p}
gross_shift = {fam: round(p[fam]["ZERO_COST"]["totals"]["gross"] - p[fam]["BASE"]["totals"]["gross"], 4)
               for fam in p}
print("  C2 gross(BASE) - gross(ZERO_COST) != 0 => 'gross' carries slippage:",
      {k: v for k, v in gross_shift.items() if abs(v) > 1e-9} or "no trades to compare")

# C3: the same bars, named outside W1..W7
(data / "BTCUSDT_W1.json").unlink()
(data / "BTCUSDT_AUGSEP.json").write_text(json.dumps(make_bars()), encoding="utf-8")
print("\n== CONTROL 2: same bars, filename outside W1..W7 ==")
p2 = run("AUGSEP dataset present")
summarise(p2)
print("  C3 totals unchanged:", {f: (trades_base[f], p2[f]['BASE']['totals']['trades']) for f in trades_base})
print("  C3 split emptied for ema_crossover:",
      {k: p2["ema_crossover"]["BASE"][k]["trades"] for k in ("DEV_W1_W4", "VAL_W5_W6", "OOS_W7")})

# C1: a family whose indicator computation raises
(data / "BTCUSDT_AUGSEP.json").unlink()
(data / "BTCUSDT_W1.json").write_text(json.dumps(make_bars()), encoding="utf-8")
print("\n== CONTROL 3: one family raises inside _compute_indicators ==")
module = load()


class ExplodingFamily:
    def _compute_indicators(self, bars):
        raise RuntimeError("SYNTHETIC_CONTROL: indicator failure")

    def generate(self, bars, indicators, ctx):  # never reached
        raise AssertionError("must not be reached")


module.FAMILIES["momentum"] = ExplodingFamily()
import contextlib, io
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    module.main()
payload = json.loads((outdir / "MULTI_FAMILY_RESULTS.json").read_text(encoding="utf-8"))
print("  traceback in process output:", "YES" if "Traceback" in buf.getvalue() else "NO")
print("  momentum BASE trades:", payload["momentum"]["BASE"]["trades"], "net:", payload["momentum"]["BASE"]["net"])
print("  ema_crossover BASE trades (control, unaffected):", payload["ema_crossover"]["BASE"]["trades"])
print("  C1 the failing family is reported exactly like a family with no signals:",
      payload["momentum"]["BASE"]["trades"] == 0 and "error" not in json.dumps(payload["momentum"]).lower())
