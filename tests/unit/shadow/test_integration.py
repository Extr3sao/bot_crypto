"""Track D tests — ShadowCaptureHook (Shadow Campaign V2 preparation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.shadow.integration import ShadowCaptureHook
from trading_bot.shadow.outcome import ShadowBar, ShadowTradeOutcome


def _ctx(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "decision_id": "decision:rej-1",
        "trace_id": "trace-1",
        "run_id": "run-1",
        "asset": "SOL",
        "direction": "LONG",
        "strategy_id": "momentum",
        "strategy_version": "legacy-1",
        "timeframe": "5m",
        "proposal_ref": "prop-1",
        "decision_ref": "dec-1",
        "verifier_ref": "ver-1",
        "decision_time": "2026-09-09T08:00:00+00:00",
        "decision_price": 100.0,
        "entry_reference": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "invalidation": "structural stop",
        "regime_signature": "RANGING|LOW_VOL",
        "strategy_health_state": "LEGACY_PAPER_BASELINE",
        "portfolio_context_ref": "portfolio-snap-1",
        "correlation_state": "NORMAL",
        "risk_verdict": "REJECT",
        "risk_rejection_reason": "MAX_POSITIONS",
        "market_data_fingerprint": "md-1",
        "cost_model_sha256": "cm-1",
    }
    base.update(overrides)
    return base


class TestCaptureArm:
    def test_reject_capture_is_persisted_and_deterministic(self, tmp_path: Path) -> None:
        hook = ShadowCaptureHook(
            captures_path=tmp_path / "captures.jsonl",
            outcomes_path=tmp_path / "outcomes.jsonl",
        )
        cid1 = hook.on_risk_reject(_ctx())
        hook2 = ShadowCaptureHook(
            captures_path=tmp_path / "captures.jsonl",
            outcomes_path=tmp_path / "outcomes.jsonl",
        )
        # Same economic context -> duplicate id rejected on reload (immutability).
        with pytest.raises(ValueError, match="duplicate"):
            hook2.on_risk_reject(_ctx())
        # Different decision -> distinct id.
        cid2 = hook2.on_risk_reject(_ctx(decision_id="decision:rej-2"))
        assert cid1 != cid2
        assert len(hook2.captures) == 2
        assert hook2.captures.captures[0].shadow_candidate_id == cid1

    def test_accept_decisions_never_captured(self, tmp_path: Path) -> None:
        hook = ShadowCaptureHook(captures_path=tmp_path / "c.jsonl")
        with pytest.raises(ValueError, match="REJECT"):
            hook.on_risk_reject(_ctx(risk_verdict="ACCEPT"))
        assert len(hook.captures) == 0


class TestResolutionArm:
    def test_pit_resolution_excludes_pre_decision_bars(self, tmp_path: Path) -> None:
        hook = ShadowCaptureHook(
            captures_path=tmp_path / "c.jsonl", outcomes_path=tmp_path / "o.jsonl"
        )
        hook.on_risk_reject(_ctx())
        bars = [
            ShadowBar("2026-09-09T07:00:00+00:00", 500.0, 10.0, 100.0),  # pre-decision noise
            ShadowBar("2026-09-09T08:05:00+00:00", 104.5, 100.5, 104.0),  # TP
        ]
        trades = hook.resolve_pending({"decision:rej-1": bars})
        assert len(trades) == 1
        assert trades[0].outcome is ShadowTradeOutcome.TAKE_PROFIT_HIT
        assert trades[0].exit_time == "2026-09-09T08:05:00+00:00"
        # outcome ledger persisted separately
        reloaded = ShadowCaptureHook(
            captures_path=tmp_path / "c.jsonl", outcomes_path=tmp_path / "o.jsonl"
        )
        assert len(reloaded.outcomes) == 1

    def test_duplicate_resolution_rejected(self, tmp_path: Path) -> None:
        hook = ShadowCaptureHook(
            captures_path=tmp_path / "c.jsonl", outcomes_path=tmp_path / "o.jsonl"
        )
        hook.on_risk_reject(_ctx())
        bars = [ShadowBar("2026-09-09T08:05:00+00:00", 104.5, 100.5, 104.0)]
        hook.resolve_pending({"decision:rej-1": bars})
        with pytest.raises(ValueError, match="duplicate"):
            hook.resolve_pending({"decision:rej-1": bars})


class TestIsolation:
    def test_hook_module_never_imports_paper_runtime(self) -> None:
        """Isolation by IMPORT GRAPH (AST): no paper/portfolio/campaign/risk
        modules may be imported by the shadow integration hook."""
        import ast

        source = Path("src/trading_bot/shadow/integration.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        forbidden_prefixes = (
            "trading_bot.paper",
            "trading_bot.demo",
            "trading_bot.risk",
            "trading_bot.portfolio",
        )
        for module in imported_modules:
            assert not module.startswith(forbidden_prefixes), module
        # Execution imports are limited to the canonical cost model.
        exec_imports = {m for m in imported_modules if m.startswith("trading_bot.execution")}
        assert exec_imports == {"trading_bot.execution.cost_model"}

    def test_capture_labels_exclude_from_paper_accounting(self, tmp_path: Path) -> None:
        hook = ShadowCaptureHook(captures_path=tmp_path / "c.jsonl")
        hook.on_risk_reject(_ctx())
        raw = (tmp_path / "c.jsonl").read_text(encoding="utf-8")
        payload = json.loads(raw.splitlines()[0])
        labels = payload["labels"]
        assert "EXCLUDED_FROM_PAPER_PNL" in labels
        assert "EXCLUDED_FROM_PAPER_FREQUENCY" in labels
        assert "SHADOW_ONLY" in labels and "COUNTERFACTUAL" in labels
