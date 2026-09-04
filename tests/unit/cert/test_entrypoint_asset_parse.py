"""RUN-OP-004 — entrypoint asset parsing (DEF-OP-003-ENTRYPOINT-ASSETS).

Reproducer + permanent regression:

The baseline ``scripts/start_paper_trading.py::build_settings`` iterated
``args.assets`` (a raw CLI string) and built one PairSpec per CHARACTER
("BTC,ETH,SOL" -> B,T,C,',',E,... = 11 pairs). The scanner then found no
active pair, so the canonical decision cycle never executed any strategy.

Invariant enforced here:

    CLI text -> normalized asset list (exactly once, at the boundary)
    -> settings universe

so per-character splitting is impossible.

FAIL BEFORE FIX (baseline): ``parse_assets`` does not exist and the
universe is built from characters.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "scripts" / "start_paper_trading.py").exists():
    _REPO_ROOT = _REPO_ROOT.parent
    if _REPO_ROOT.parent == _REPO_ROOT:
        raise RuntimeError("repo root not found")


def _load_entry():
    spec = importlib.util.spec_from_file_location(
        "start_paper_trading", _REPO_ROOT / "scripts" / "start_paper_trading.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


entry = _load_entry()


def test_parse_assets_canonical_comma_list() -> None:
    assert entry.parse_assets("BTC,ETH,SOL") == ["BTC", "ETH", "SOL"]


def test_parse_assets_single_asset() -> None:
    assert entry.parse_assets("BTC") == ["BTC"]


def test_parse_assets_whitespace_and_case_normalized() -> None:
    assert entry.parse_assets(" btc , eth , SOL ") == ["BTC", "ETH", "SOL"]


def test_parse_assets_dedupes_preserving_order() -> None:
    assert entry.parse_assets("BTC,btc,ETH,BTC") == ["BTC", "ETH"]


def test_parse_assets_drops_empty_tokens() -> None:
    assert entry.parse_assets("BTC,,ETH,") == ["BTC", "ETH"]


def test_parse_assets_rejects_whitespace_only_input() -> None:
    with pytest.raises(ValueError):
        entry.parse_assets(" , , ")


def test_character_split_impossible() -> None:
    """Guard: the CLI string can never leak into per-character symbols."""
    for raw in ("BTC,ETH,SOL", "BTC", "BTC, ETH , SOL", "btc,eth,sol"):
        assets = entry.parse_assets(raw)
        assert assets, f"empty result for {raw!r}"
        assert all(len(a) >= 2 for a in assets), f"character-level token in {assets}"
        assert "/" not in "".join(assets)


def test_build_settings_universe_uses_normalized_assets() -> None:
    """The settings universe must contain exactly the requested canonical pairs."""
    args = argparse.Namespace(config_dir=str(_REPO_ROOT / "config"), timeframe="5m")
    settings = entry.build_settings(args, ["BTC", "ETH", "SOL"])
    symbols = [p.symbol for p in settings.universe.pairs if p.enabled]
    assert symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_parse_assets_then_build_settings_yields_no_duplicate_pairs() -> None:
    """Dedup happens once at the boundary (parse_assets); build_settings maps
    the normalized list 1:1 into the universe, so duplicates can never reach
    the scanner."""
    args = argparse.Namespace(config_dir=str(_REPO_ROOT / "config"), timeframe="5m")
    assets = entry.parse_assets("BTC,btc,BTC")
    assert assets == ["BTC"]
    settings = entry.build_settings(args, assets)
    assert [p.symbol for p in settings.universe.pairs if p.enabled] == ["BTC/USDT"]
