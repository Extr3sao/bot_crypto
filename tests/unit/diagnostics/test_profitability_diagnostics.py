from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "scripts/profitability_diagnostics/run.py"
spec = importlib.util.spec_from_file_location("profitability_diagnostics", MODULE)
assert spec and spec.loader
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def test_normalize_reason_uses_closed_taxonomy() -> None:
    assert diag.normalize_reason("Max open positions reached (1)") == "MAX_POSITIONS"
    assert diag.normalize_reason("unknown reason") == "OTHER"


def test_funnel_preserves_unknowns_and_counts() -> None:
    report = diag.funnel(
        {
            "telemetry": [
                {
                    "state": {
                        "market_scans": 3,
                        "trade_proposals": 6,
                        "debates": 3,
                        "decisions_selected": 3,
                        "no_trade": 0,
                        "risk_accepts": 2,
                        "risk_rejects": 1,
                        "paper_trades": 1,
                        "closed_trades": 0,
                    }
                }
            ],
            "intents": [{}, {}],
        }
    )
    assert report["counts"]["RAW_STRATEGY_SIGNAL"] == "UNKNOWN"
    assert report["counts"]["TRADE_PROPOSAL"] == 6
    assert report["counts"]["RISK"] == 3
    assert report["counts"]["PAPER_ORDER"] == 1


def test_generation_is_non_interfering_and_deterministic(tmp_path, monkeypatch) -> None:
    campaign = tmp_path / "campaign"
    cycles = campaign / "cycles"
    shadow = campaign / "shadow"
    cycles.mkdir(parents=True)
    shadow.mkdir()
    (campaign / "R2_CAMPAIGN_STATE.json").write_text("{}")
    (campaign / "R2_LAUNCH_RECORD.json").write_text("{}")
    (cycles / "R2_INTENT_LEDGER.jsonl").write_text("")
    (shadow / "shadow_captures.jsonl").write_text("")
    (campaign / "R2_CYCLE_LEDGER.jsonl").write_text(
        '{"state":{"market_scans":1,"trade_proposals":0}}\n'
    )
    monkeypatch.setattr(diag, "CAMPAIGN", campaign)
    monkeypatch.setattr(diag, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(diag, "REPORTS", tmp_path / "reports")
    protected = [
        campaign / "R2_CAMPAIGN_STATE.json",
        cycles / "R2_INTENT_LEDGER.jsonl",
        shadow / "shadow_captures.jsonl",
    ]
    before = [p.read_bytes() for p in protected]
    first = diag.generate()
    second = diag.generate()
    assert first["state_before_equals_after"] is True
    assert second["state_before_equals_after"] is True
    assert [p.read_bytes() for p in protected] == before
