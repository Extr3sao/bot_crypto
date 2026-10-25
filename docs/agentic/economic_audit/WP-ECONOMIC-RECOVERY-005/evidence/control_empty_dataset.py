"""Negative control: drive the real entrypoint over an EMPTY dataset directory.

Nothing in the repository is written: DATA/OUTDIR are repointed at a temp root
before main() runs. The point is to observe what the entrypoint emits when its
dataset glob matches nothing.
"""
import importlib.util, json, os, sys, tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
tmp = Path(tempfile.mkdtemp(prefix="wp005_empty_"))
data = tmp / "reports" / "strategy-baseline" / "data"
data.mkdir(parents=True)
spec = importlib.util.spec_from_file_location("multi_family_backtest", root / "scripts" / "multi_family_backtest.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.DATA = str(data)
m.OUTDIR = str(tmp / "reports" / "strategy-baseline")
m.main()
out = Path(m.OUTDIR) / "MULTI_FAMILY_RESULTS.json"
payload = json.loads(out.read_text(encoding="utf-8"))
print("ARTIFACT_WRITTEN:", out.relative_to(tmp).as_posix())
print("BYTES:", out.stat().st_size)
print("FAMILIES:", sorted(payload))
trades = {fam: sum(payload[fam][sc]["totals"]["trades"] for sc in payload[fam]) for fam in payload}
print("TRADES_BY_FAMILY:", trades)
print("DATASETS_IN_INPUT_DIR:", len(list(data.glob('*.json'))))
