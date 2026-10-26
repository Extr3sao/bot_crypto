"""Does the preflight's own rule catch the false-success artifact the entrypoint just wrote?"""
import importlib.util, json, sys, tempfile, glob, os
from pathlib import Path

root = Path(sys.argv[1]).resolve()
candidates = [Path(p) for p in glob.glob(os.path.join(tempfile.gettempdir(), "wp005_empty_*", "reports", "strategy-baseline", "MULTI_FAMILY_RESULTS.json"))]
assert candidates, "no control artifact found"
artifact = candidates[-1]
spec = importlib.util.spec_from_file_location("wp005_preflight", root / "scripts" / "wp005_preflight.py")
pf = importlib.util.module_from_spec(spec); spec.loader.exec_module(pf)
detail = pf.read_result(artifact, artifact.parents[2])
print("ARTIFACT:", artifact)
print("JSON:", detail["json"], "| empty:", detail["empty"], "| families:", len(detail["families"]))
print("ZERO_TRADE_FAMILIES:", detail["zero_trade_families"])
print("WOULD_BLOCK:", bool(detail["zero_trade_families"]))
