"""Freeze a corpus, mirror it, and restore it for real — the operations, not the theory.

    python scripts/wp_edge04_freeze.py freeze --root reports/alpha-expansion-v1/data --interval 1h
    python scripts/wp_edge04_freeze.py verify --root reports/alpha-expansion-v1/data
    python scripts/wp_edge04_freeze.py mirror --root <root> --dest <independent path>
    python scripts/wp_edge04_freeze.py drill  --root <root> --backup <dest>

Every subcommand prints one JSON receipt and exits non-zero when the receipt is bad, so a
caller can chain them without parsing prose.  ``drill`` is the one that matters: it deletes a
copy of the corpus and puts it back from the mirror, in a scratch root, and then has a real
loader read the restored bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.prospective import freeze  # noqa: E402

#: The 1h corpus EDGE-03/04 read once the 15m shards were gone; the source is the public spot
#: endpoint, per-year shards, fetched by ``scripts/fetch_alpha_expansion_history.py``.
DEFAULT_ROOT = REPO / "reports" / "alpha-expansion-v1" / "data"
NORMALIZATION = (
    "list of [{ts,open,high,low,close,volume}], ts = bar OPEN time (ms, UTC), as fetched by "
    "scripts/fetch_alpha_expansion_history.py; no interpolation, no synthesis"
)
SOURCE = "BINANCE_PUBLIC_REST:/api/v3/klines"


def reader_for(root: Path):
    """A real consumer of the corpus, so the drill proves readability and not just equality."""
    from trading_bot.research.edge01.data import load_1h

    def read(path: Path) -> dict:
        loaded = load_1h("BTC", corpus=path)
        return {
            "bars": loaded.n,
            "first_ts": loaded.first_ts,
            "last_ts": loaded.last_ts,
            "sha256": loaded.sha256,
        }

    return read


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["freeze", "verify", "mirror", "drill"])
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--dest", default=None, help="mirror destination (independent of the tree)")
    ap.add_argument("--scratch", default=str(REPO / ".tmp15m" / "drill"))
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root)
    receipt: dict = {"command": args.command, "root": str(root)}

    if args.command == "freeze":
        manifest = freeze.freeze(
            root, interval=args.interval, source=SOURCE, normalization=NORMALIZATION
        )
        receipt.update(
            {
                "ok": True,
                "corpus_digest": manifest["corpus_digest"],
                "shards": manifest["totals"]["shards"],
                "bars": manifest["totals"]["bars"],
                "bytes": manifest["totals"]["bytes"],
                "last_close_utc": max(s["last_close_ts"] for s in manifest["shards"].values()),
                "manifest": str(root / freeze.DEFAULT_MANIFEST_NAME),
            }
        )

    elif args.command == "verify":
        checked = freeze.verify(root)
        receipt.update(checked)
        receipt["ok"] = checked["ok"]

    elif args.command == "mirror":
        if not args.dest:
            raise SystemExit("mirror needs --dest")
        receipt.update(
            freeze.mirror(root, Path(args.dest), overwrite=args.overwrite) | {"ok": True}
        )

    else:  # drill
        if not args.dest:
            raise SystemExit("drill needs --dest (the mirror written by `mirror`)")
        drill = freeze.restore_drill(
            root, Path(args.dest), scratch=Path(args.scratch), reader=reader_for(root)
        )
        receipt.update(drill)
        receipt["ok"] = bool(drill["restored"] and drill["reader_agrees"])

    print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
