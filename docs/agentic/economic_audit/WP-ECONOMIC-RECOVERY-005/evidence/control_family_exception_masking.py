"""SYNTHETIC control: does a failing family look like a family with no signals?

No real data and no repository writes: the dataset is a seeded random walk in a
temp directory and DATA/OUTDIR are repointed before main() runs. The only claim
under test is the observability of a failure, not the performance of anything.

Run from the repository root:  ./.venv/Scripts/python.exe <this file>
Prints the healthy totals, the totals of the same family made to raise inside
``_compute_indicators``, and whether any traceback or ``error`` key survived.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import random
import tempfile
from pathlib import Path

root = Path(".").resolve()
tmp = Path(tempfile.mkdtemp(prefix="wp005_mask_"))
data = tmp / "data"
data.mkdir()
outdir = tmp / "out"
outdir.mkdir()

rnd = random.Random(7)
price, bars = 30_000.0, []
for i in range(400):
    op, price = price, price * (1 + rnd.gauss(0.0, 0.0015))
    hi = max(op, price) * (1 + abs(rnd.gauss(0, 0.0006)))
    lo = min(op, price) * (1 - abs(rnd.gauss(0, 0.0006)))
    bars.append({"ts": 1_600_000_000_000 + i * 300_000, "open": round(op, 2), "high": round(hi, 2),
                 "low": round(lo, 2), "close": round(price, 2), "volume": round(rnd.uniform(1, 50), 3)})
(data / "BTCUSDT_W1.json").write_text(json.dumps(bars), encoding="utf-8")


def load():
    spec = importlib.util.spec_from_file_location("multi_family_backtest",
                                                 root / "scripts" / "multi_family_backtest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DATA, module.OUTDIR = str(data), str(outdir)
    return module


class ExplodingFamily:
    def _compute_indicators(self, bars):
        raise RuntimeError("SYNTHETIC_CONTROL: indicator failure")

    def generate(self, bars, indicators, ctx):
        raise AssertionError("must not be reached")


def run(module) -> tuple[dict, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        module.main()
    payload = json.loads((outdir / "MULTI_FAMILY_RESULTS.json").read_text(encoding="utf-8"))
    return payload, buf.getvalue()


healthy, _ = run(load())
print("healthy momentum BASE totals:", healthy["momentum"]["BASE"]["totals"])

for f in outdir.glob("*.json"):
    f.unlink()
broken_module = load()
broken_module.FAMILIES["momentum"] = ExplodingFamily()
broken, output = run(broken_module)
b = broken["momentum"]["BASE"]["totals"]
print("failing  momentum BASE totals:", b)
print("exit status of the process: 0 (no exception propagated)")
print("traceback / exception text in output:",
      "YES" if "Traceback" in output or "SYNTHETIC_CONTROL" in output else "NO")
print("error key anywhere in momentum block:", "error" in json.dumps(broken["momentum"]).lower())
print("C1 identical shape to a no-signal family (trades=0, net=0):",
      b["trades"] == 0 and b["net"] == 0.0)
print("control family unaffected:",
      broken["ema_crossover"]["BASE"]["totals"]["trades"] == healthy["ema_crossover"]["BASE"]["totals"]["trades"])
