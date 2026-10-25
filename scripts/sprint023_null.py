"""RFC-023 — resumable chunked runner for the best-of-N null distribution.

Each invocation appends up to ``CHUNK`` fresh draws (new RNG seed per chunk) to
``reports/generalization/_null_draws.json`` until ``N_TARGET`` draws exist.
Resumable so the 200-draw plan can be satisfied across several short processes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint023_lib as G  # noqa: E402

CACHE = G.OUT / "_null_draws.json"
CHUNK = 50
N_TARGET = G.N_PERM


def load() -> list[dict[str, Any]]:
    if CACHE.exists():
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    return []


def main() -> int:
    G.OUT.mkdir(parents=True, exist_ok=True)
    draws = load()
    remaining = N_TARGET - len(draws)
    if remaining <= 0:
        print(f"null complete: {len(draws)} draws")
        print(json.dumps(G.summarise_null(draws), indent=2))
        return 0
    take = min(CHUNK, remaining)
    seed = G.SEED + len(draws) * 1009
    print(f"running {take} draws (seed={seed}), have {len(draws)}/{N_TARGET}", flush=True)
    new = G.null_draws(take, seed)
    draws.extend(new)
    CACHE.write_text(json.dumps(draws), encoding="utf-8")
    print(f"now {len(draws)}/{N_TARGET}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
