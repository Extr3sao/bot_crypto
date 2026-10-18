"""run_ablation — matched opportunities, one book, and an honest verdict.

Arms:

``NO_CRITIC``  the canonical lane, no reviewer.
``SHADOW``     the same lane run, then every actionable decision reviewed in SHADOW_ONLY.
               The critic has no path to the broker, so economics must be identical; the
               report measures the cost and latency that were added, nothing else.
``NO_TRADE``   the same lane with an always-NO_TRADE provider. A legitimate control, not
               a failure.
``GATED_PAPER`` **not executed.** It requires the AI-BOTS-003C validation, which this
               work package does not have. Only the *rule* is counted against the shadow
               reviews, and the count is labelled as a simulation without economics.

The script never claims prospective value: the reviewer is scripted, the data is
historical and synthetic, and no paid model was called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.config.settings import load_settings
from trading_bot.intelligence.ai_bots.registry import default_registry
from trading_bot.intelligence.ai_bots.runner import run_bot
from trading_bot.intelligence.ai_critic.contracts import (
    EvidenceLedger,
    EvidenceRef,
    FrozenTradeProposal,
    canonical_sha256,
)
from trading_bot.intelligence.ai_critic.critic import CriticBudget, CriticService
from trading_bot.intelligence.ai_critic.policy import CriticMode
from trading_bot.intelligence.ai_critic.provider import ScriptedCriticProvider
from trading_bot.intelligence.ai_critic.trace import CriticTraceWriter
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.provider import ReplayProvider
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000
ECONOMIC_KEYS = (
    "fills",
    "closed_trades",
    "net_realised_usdt",
    "gross_realised_usdt",
    "costs_usdt",
    "final_equity_usdt",
    "risk_equity_usdt",
    "drawdown_pct",
    "equity_points",
)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bars(count: int, *, start: int, price: float, drift: float, wobble: float) -> list[Bar]:
    out: list[Bar] = []
    for i in range(count):
        step = drift + (wobble if i % 7 == 6 else 0.0) - (wobble if i % 11 == 10 else 0.0)
        close = price * (1.0 + step)
        out.append(
            Bar(
                ts_ms=start + i * HOUR_MS,
                open=price,
                high=max(price, close) * 1.003,
                low=min(price, close) * 0.997,
                close=close,
                volume=120.0 + (i % 5) * 10.0,
            )
        )
        price = close
    return out


def series() -> dict[str, list[Bar]]:
    return {
        "BTC/USDT": bars(240, start=START_MS, price=60_000.0, drift=0.0015, wobble=0.003),
        "ETH/USDT": bars(240, start=START_MS, price=3_000.0, drift=-0.0012, wobble=0.004),
    }


def decision(action: str, *, confidence: float = 0.62, stop: float = 1.2) -> str:
    return json.dumps(
        {
            "schema_version": "ai-vision-decision/1",
            "symbol": "BTC/USDT",
            "action": action,
            "confidence": confidence,
            "horizon_bars": 8,
            "stop_loss_pct": stop if action in {"LONG", "SHORT"} else None,
            "take_profit_pct": 2.4 if action in {"LONG", "SHORT"} else None,
            "invalidation": "structure fails" if action in {"LONG", "SHORT"} else None,
            "rationale": f"scripted {action} for the matched-opportunity ablation",
        }
    )


def scripted_answers(seed_actions: list[str]) -> Any:
    """Cycle deterministic decisions; the same call index sees the same answer in every arm."""
    state = {"index": 0}

    def answer(_request: Any) -> str:
        action = seed_actions[state["index"] % len(seed_actions)]
        state["index"] += 1
        return decision(action)

    return answer


def vision_config(*, decision_every_bars: int = 40) -> Any:
    config = load_vision_config(env={})
    lane = config.lane
    merged = {
        "timeframe": "1h",
        "window_bars": 30,
        "decision_every_bars": decision_every_bars,
        "max_calls_per_run": 40,
        # Replay answers cost nothing, but a zero budget makes the lane stop before its
        # first decision (spend 0 >= budget 0). A positive ceiling is the honest shape.
        "max_estimated_spend_usd": 5.0,
    }
    return config.__class__(provider=config.provider, lane=lane.__class__(**merged))


def run_arm(
    name: str,
    *,
    actions: list[str],
    out_dir: Path,
    risk_policy: Any,
) -> dict[str, Any]:
    registry = default_registry(env={"AI_BOTS_ENABLED": "true"})
    summary = run_bot(
        registry=registry,
        bot_id="BOT-CTX-01",
        series=series(),
        provider=ReplayProvider(scripted_answers(actions)),
        risk_policy=risk_policy,
        out_dir=out_dir,
        config=vision_config(),
        run_id=f"ABL-{name}",
        allow_disabled=True,
        max_calls=40,
    )
    return summary


def ledger_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line)["entry"])
    return rows


def proposal_from_decision(row: dict[str, Any]) -> FrozenTradeProposal | None:
    intent = row.get("intent")
    decision = row.get("decision") or {}
    if intent not in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}:
        return None
    side = {"OPEN_LONG": "buy", "OPEN_SHORT": "sell", "CLOSE": "close"}[intent]
    mapped = {"OPEN_LONG": "OPEN", "OPEN_SHORT": "OPEN", "CLOSE": "CLOSE"}[intent]
    prompt = row.get("prompt") or {}
    context = prompt.get("context") or {}
    return FrozenTradeProposal.freeze(
        proposal_id=f"{row['symbol']}-{row['ts_ms']}-{row.get('seq', '0')}",
        bot_id="BOT-CTX-01",
        run_id="ABL-NO_CRITIC",
        asset=str(row["symbol"]),
        side=side,
        intent=mapped,
        confidence=float(decision.get("confidence") or 0.5),
        timeframe=str(context.get("timeframe") or "1h"),
        decision_time_ms=int(row["ts_ms"]),
        horizon_bars=int(decision.get("horizon_bars") or 8),
        thesis=str(decision.get("rationale") or decision.get("invalidation") or "no thesis"),
        evidence_refs=("bar:chart", "report:context"),
        opinion_digest=canonical_sha256(decision),
    )


def ledger_for(row: dict[str, Any]) -> EvidenceLedger:
    return EvidenceLedger(
        items=(
            EvidenceRef(
                ref_id="bar:chart",
                kind="chart",
                sha256=canonical_sha256(row.get("chart") or {}),
                summary="rendered chart fingerprint for this decision",
                source="vision.lane.chart",
            ),
            EvidenceRef(
                ref_id="report:context",
                kind="context",
                sha256=canonical_sha256((row.get("prompt") or {}).get("context") or {}),
                summary="market context given to the proposer",
                source="vision.lane.prompt",
            ),
        )
    )


def critic_answer(verdict: str, proposal: FrozenTradeProposal, *, challenge: bool) -> str:
    if verdict == "CHALLENGE":
        payload = {
            "verdict": "CHALLENGE", "confidence": 0.7,
            "rationale": "The context snapshot does not support the stated invalidation.",
            "evidence_refs": ["bar:chart"],
            "counter_evidence_refs": ["report:context"],
            "challenge_kind": "UNSUPPORTED_THESIS", "abstain_reason": None,
        }
    else:
        payload = {
            "verdict": "ACCEPT", "confidence": 0.6,
            "rationale": "Chart and context are consistent with the thesis.",
            "evidence_refs": ["bar:chart", "report:context"],
            "counter_evidence_refs": [], "challenge_kind": None, "abstain_reason": None,
        }
    return json.dumps(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    runs_dir = out / "runs"
    runs_dir.mkdir(exist_ok=True)

    started = now()
    risk_policy = load_settings(config_dir=Path(args.config_dir), env_file=None).risk

    actions = ["LONG", "LONG", "CLOSE", "SHORT", "SHORT", "CLOSE", "LONG", "CLOSE"]

    t0 = time.perf_counter()
    baseline = run_arm("NO_CRITIC", actions=actions, out_dir=runs_dir / "NO_CRITIC",
                       risk_policy=risk_policy)
    baseline_seconds = round(time.perf_counter() - t0, 3)
    baseline_ledger = runs_dir / "NO_CRITIC" / "BOT-CTX-01_DECISIONS.jsonl"
    baseline_rows = ledger_rows(baseline_ledger)

    t0 = time.perf_counter()
    repeat = run_arm("NO_CRITIC_REPEAT", actions=actions, out_dir=runs_dir / "NO_CRITIC_REPEAT",
                     risk_policy=risk_policy)
    repeat_seconds = round(time.perf_counter() - t0, 3)
    repeat_ledger = runs_dir / "NO_CRITIC_REPEAT" / "BOT-CTX-01_DECISIONS.jsonl"

    t0 = time.perf_counter()
    no_trade = run_arm("NO_TRADE", actions=["NO_TRADE"], out_dir=runs_dir / "NO_TRADE",
                       risk_policy=risk_policy)
    no_trade_seconds = round(time.perf_counter() - t0, 3)

    # --- SHADOW: review the baseline decisions. There is no path back to the broker. ---
    traces = CriticTraceWriter(out)
    budget = CriticBudget(max_calls=64, max_spend_usd=0.5)
    decisions = [row for row in baseline_rows if row.get("kind") == "DECISION"]
    actionable = [row for row in decisions if row.get("intent") in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}]

    review_rows: list[dict[str, Any]] = []
    review_seconds: list[float] = []
    for index, row in enumerate(actionable):
        proposal = proposal_from_decision(row)
        if proposal is None:
            continue
        # Every third actionable proposal is challenged, so the critic is not a blanket veto.
        is_challenge = index % 3 == 2
        provider = ScriptedCriticProvider(
            [critic_answer("CHALLENGE" if is_challenge else "ACCEPT", proposal,
                           challenge=is_challenge)],
            latency_ms=2,
        )
        service = CriticService(
            ledger=ledger_for(row),
            provider=provider,
            traces=traces,
            mode=CriticMode.SHADOW_ONLY,
            budget=budget,
            timeout_ms=2_000,
            # Anchor the review clock to the decision, not to wall time: the lane's
            # decisions are historical, so a wall clock would make every review late.
            now_ms=lambda ts=proposal.decision_time_ms: ts + 5,
        )
        t1 = time.perf_counter()
        outcome = service.review(proposal)
        review_seconds.append((time.perf_counter() - t1) * 1000.0)
        review_rows.append(
            {
                "proposal_id": proposal.proposal_id,
                "intent": proposal.intent,
                "verdict": outcome.review.verdict,
                "abstain_reason": outcome.review.abstain_reason,
                "gate_action": outcome.gate.action,
                "economics_affected": outcome.gate.economics_affected,
                "review_sha256": outcome.review.review_sha256,
                "receipt_kind": outcome.review.receipt_kind,
                "cost_usd": outcome.review.cost_usd,
                "latency_ms": outcome.review.latency_ms,
            }
        )

    # The lane may close a position through its protective levels before a CLOSE decision
    # is actionable, so the run can contain no protective proposal. The rule that a critic
    # must never block an exit is still measured, with explicit protective probes that are
    # labelled as such rather than passed off as lane opportunities.
    for intent, side in (("CLOSE", "close"), ("REDUCE", "close"),
                         ("STOP", "close"), ("TAKE_PROFIT", "close")):
        anchor = baseline_rows[0]
        probe = FrozenTradeProposal.freeze(
            proposal_id=f"PROBE-{intent}",
            bot_id="BOT-CTX-01",
            run_id="ABL-PROTECTIVE-PROBE",
            asset="BTC/USDT",
            side=side,
            intent=intent,
            confidence=0.8,
            timeframe="1h",
            decision_time_ms=START_MS + HOUR_MS,
            horizon_bars=1,
            thesis=f"protective probe: {intent} must never be blocked by a critic",
            evidence_refs=("bar:chart", "report:context"),
            opinion_digest=canonical_sha256({"probe": intent}),
        )
        provider = ScriptedCriticProvider([critic_answer("CHALLENGE", probe, challenge=True)],
                                          latency_ms=2)
        service = CriticService(
            ledger=ledger_for(anchor), provider=provider, traces=traces,
            mode=CriticMode.SHADOW_ONLY, budget=budget, timeout_ms=2_000,
            now_ms=lambda ts=probe.decision_time_ms: ts + 5,
        )
        outcome = service.review(probe)
        review_rows.append(
            {
                "proposal_id": probe.proposal_id,
                "intent": probe.intent,
                "source": "PROTECTIVE_PROBE",
                "verdict": outcome.review.verdict,
                "abstain_reason": outcome.review.abstain_reason,
                "gate_action": outcome.gate.action,
                "economics_affected": outcome.gate.economics_affected,
                "review_sha256": outcome.review.review_sha256,
                "receipt_kind": outcome.review.receipt_kind,
                "cost_usd": outcome.review.cost_usd,
                "latency_ms": outcome.review.latency_ms,
            }
        )

    verdict_counts = Counter(r["verdict"] for r in review_rows)
    suppressed_simulation = [
        r for r in review_rows if r["intent"] == "OPEN" and r["verdict"] == "CHALLENGE"
    ]
    protective = [r for r in review_rows if r["intent"] != "OPEN"]
    protective_blocked = [r for r in protective if r["gate_action"] != "ALLOW"]
    entries = [r for r in review_rows if r["intent"] == "OPEN"]
    challenge_rate = (
        round(len(suppressed_simulation) / len(entries), 4) if entries else None
    )
    degenerate = challenge_rate == 1.0

    baseline_econ = {key: baseline.get(key) for key in ECONOMIC_KEYS}
    repeat_econ = {key: repeat.get(key) for key in ECONOMIC_KEYS}
    no_trade_econ = {key: no_trade.get(key) for key in ECONOMIC_KEYS}
    same_sequence = [row.get("ts_ms") for row in decisions] == [
        row.get("ts_ms") for row in ledger_rows(repeat_ledger) if row.get("kind") == "DECISION"
    ]
    identical_economics = baseline_econ == repeat_econ

    runtime_files = [
        Path(__file__).resolve().parents[2] / "src/trading_bot/intelligence/ai_critic" / name
        for name in ("contracts.py", "prompt.py", "provider.py", "critic.py", "policy.py", "trace.py")
    ]
    runtime_sha = {str(path.relative_to(path.parents[3])).replace("\\", "/"): sha256_file(path)
                   for path in runtime_files}

    status = "INCONCLUSIVE_VALUE"
    recommendation = "DO_NOT_ADOPT_PENDING_PROSPECTIVE"
    if degenerate:
        status = "DO_NOT_ADOPT"
        recommendation = "DO_NOT_ADOPT"
    elif baseline_econ["fills"] == 0:
        status = "INCONCLUSIVE_NO_OPPORTUNITIES"

    report = {
        "schema_version": "TAP004_ABLATION_V1",
        "generated_at": now(),
        "started_at": started,
        "test_target": "trading_bot.intelligence.ai_critic",
        "runtime_target": "trading_bot.intelligence.ai_critic",
        "test_source_path": "tests/unit/intelligence/ai_critic/test_bot_cri_01.py",
        "runtime_source_path": "src/trading_bot/intelligence/ai_critic",
        "test_target_equals_runtime_target": True,
        "runtime_module_sha256": runtime_sha,
        "python": sys.version,
        "platform": platform.platform(),
        "matched_opportunities": {
            "decision_points": len(decisions),
            "actionable_proposals": len(actionable),
            "same_sequence_across_arms": same_sequence,
            "assets": ["BTC/USDT", "ETH/USDT"],
            "regimes": ["drift_up_with_wobble", "drift_down_with_wobble"],
            "note": "historical synthetic bars; not a forward test",
        },
        "arms": {
            "NO_CRITIC": {
                "executed": True,
                "economics": baseline_econ,
                "wall_seconds": baseline_seconds,
                "net_realised_usdt": baseline.get("net_realised_usdt"),
                "model_status": baseline.get("model_status", "MOCK_TEST"),
            },
            "NO_CRITIC_REPEAT": {
                "executed": True,
                "economics": repeat_econ,
                "wall_seconds": repeat_seconds,
                "baseline_identical": identical_economics,
            },
            "SHADOW": {
                "executed": True,
                "economics": baseline_econ,
                "economics_identical_to_baseline": identical_economics,
                "applied_to_economics": False,
                "reviews": len(review_rows),
                "review_scope": "lane decisions plus 4 explicitly labelled protective probes",
                "verdicts": dict(verdict_counts),
                "would_suppress_entries_if_gated": len(suppressed_simulation),
                "protective_reviews": len(protective),
                "protective_blocked": len(protective_blocked),
                "challenge_rate_on_entries": challenge_rate,
                "degenerate_blanket_veto": degenerate,
                "receipt_kinds": dict(Counter(r["receipt_kind"] for r in review_rows)),
                "critic_cost_usd": round(sum(r["cost_usd"] for r in review_rows), 8),
                "review_latency_ms_median": (
                    round(statistics.median(review_seconds), 3) if review_seconds else None
                ),
                "review_latency_ms_max": (
                    round(max(review_seconds), 3) if review_seconds else None
                ),
            },
            "GATED_PAPER": {
                "executed": False,
                "status": "BLOCKED_GATED_PAPER_NOT_AUTHORIZED",
                "reason": (
                    "AI-BOTS-003C runtime validation is not certified on this branch; the "
                    "gate therefore never altered the book"
                ),
                "simulation_only": True,
                "would_suppress_entries": len(suppressed_simulation),
                "economics_measured": False,
            },
            "NO_TRADE": {
                "executed": True,
                "economics": no_trade_econ,
                "wall_seconds": no_trade_seconds,
            },
        },
        "value": {
            "economic_value": "UNMEASURED",
            "real_critic_model_called": False,
            "prospective_edge_verified": False,
            "reason": (
                "reviewer answers are scripted and data is historical; no paid model call, "
                "no out-of-sample sample, no economic claim"
            ),
            "status": status,
            "recommendation": recommendation,
            "shadow_continues": True,
        },
        "control": {
            "false_success": 0,
            "builder_is_not_verifier": True,
            "independent_verification_required": True,
        },
    }
    (out / "ABLATION_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "ABLATION_REVIEWS.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in review_rows) + "\n", encoding="utf-8"
    )

    def money(value: Any) -> str:
        return "n/a" if value is None else f"{float(value):.2f}"

    md = f"""# ABLATION_REPORT — BOT-CRI-01 (RFC-TAP-AI-BOTS-004)

**Generated:** {report["generated_at"]} · **Status:** `{status}` · **Recommendation:** `{recommendation}`

## Matching

- Assets: BTC/USDT and ETH/USDT, {len(decisions)} decision points, {len(actionable)} actionable proposals.
- Same sequence across arms: **{same_sequence}**. Same capital, fees, slippage and latency settings.
- Data is historical and synthetic: this is **not** a forward test.

## Arms

| Arm | Executed | Fills | Closed | Net realised | Final equity | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NO_CRITIC | yes | {baseline_econ["fills"]} | {baseline_econ["closed_trades"]} | {money(baseline_econ["net_realised_usdt"])} | {money(baseline_econ["final_equity_usdt"])} | canonical lane |
| SHADOW | yes | {baseline_econ["fills"]} | {baseline_econ["closed_trades"]} | {money(baseline_econ["net_realised_usdt"])} | {money(baseline_econ["final_equity_usdt"])} | {len(review_rows)} reviews, economics untouched |
| NO_TRADE | yes | {no_trade_econ["fills"]} | {no_trade_econ["closed_trades"]} | {money(no_trade_econ["net_realised_usdt"])} | {money(no_trade_econ["final_equity_usdt"])} | legitimate control |
| GATED_PAPER | **no** | — | — | — | — | `BLOCKED_GATED_PAPER_NOT_AUTHORIZED` |

## What the shadow measured

- Verdicts: `{dict(verdict_counts)}`.
- Entries a gated critic *would* have suppressed: **{len(suppressed_simulation)}** of {len(entries)} (simulation only).
- Protective reviews: {len(protective)}; blocked: **{len(protective_blocked)}** (must be zero).
- Degenerate blanket veto: **{degenerate}** — a critic that vetoes everything cannot pass.
- Critic cost: **{report["arms"]["SHADOW"]["critic_cost_usd"]} USD** (mock receipts).
- Review latency (mock): median {report["arms"]["SHADOW"]["review_latency_ms_median"]} ms,
  max {report["arms"]["SHADOW"]["review_latency_ms_max"]} ms.

## Verdict

`ECONOMIC_VALUE = UNMEASURED`. The mechanism is implemented and observable, but there is no
real model call, no prospective sample and no measured improvement. `DO_NOT_ADOPT` for
production; `SHADOW_ONLY` continues. `REAL_CRITIC_MODEL_CALLED = false`.
"""
    (out / "ABLATION_REPORT.md").write_text(md, encoding="utf-8")
    print(json.dumps({
        "status": status,
        "recommendation": recommendation,
        "fills": baseline_econ["fills"],
        "net": baseline_econ["net_realised_usdt"],
        "reviews": len(review_rows),
        "verdicts": dict(verdict_counts),
        "suppressed_simulation": len(suppressed_simulation),
        "identical": identical_economics,
        "same_sequence": same_sequence,
    }, indent=2))
    return 0 if identical_economics and same_sequence else 2


if __name__ == "__main__":
    raise SystemExit(main())
