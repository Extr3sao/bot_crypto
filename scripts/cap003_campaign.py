"""CAP-003 campaign cycle — seal real decisions, settle matured outcomes, score.

One cycle, four phases, all on real free market data (public Binance OHLCV via
the repository's existing ``CCXTExchangeConnector``):

* **SEAL** — build a causal real snapshot per campaign asset, evaluate
  ``G_REAL_MARKET_CONTEXT``, write the prompt package, and seal whatever analyst
  answer exists (with full provenance) into the real decision ledger.  The
  analyst is the LLM client; the repository never invents its answer.
* **SETTLE** — for every ledger decision whose horizon has closed, run the
  deterministic :class:`DecisionOutcomeEvaluator` and append the outcome and the
  evaluation.  Nothing is ever re-scored in place.
* **SCORE** — aggregate the evaluated campaign into ``ALPHA_SCORECARD``.
* **SELFTEST** — exercise the whole seal->outcome->evaluation chain on real data
  with a *deterministic* decision, so the pipeline is proven without consuming a
  campaign observation and without hindsight.

The analyst prompt is frozen; nothing here tunes it.  Running the cycle twice is
safe: duplicate seals and duplicate outcomes are refused by the ledger.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cap001_run as c1  # noqa: E402

from trading_bot.research import agentic_contracts as ac  # noqa: E402
from trading_bot.research import alpha_scorecard as asc  # noqa: E402
from trading_bot.research import analyst_provenance as ap  # noqa: E402
from trading_bot.research import decision_ledger as dl  # noqa: E402
from trading_bot.research import decision_outcomes as do  # noqa: E402
from trading_bot.research import market_analyst_v1 as mav  # noqa: E402
from trading_bot.research import real_market_context as rmc  # noqa: E402

OUT = REPO / "reports" / "agentic-campaign-cap003"
REPORTS = REPO / "reports"
LEDGER_ROOT = REPO / "evidence" / "real_decisions"
RAW_DIRNAME = dl.RAW_EVIDENCE_DIRNAME

ANALYST_MODEL = "freebuff-agent-in-context"
ANALYST_PROVIDER = "freebuff"
CRITIC_NOTE = "single-analyst campaign; no separate critic model in V1"

BAR_MS = 4 * 3_600 * 1_000
SELFTEST_BACKOFF_BARS = 6
SELFTEST_HORIZON = "4H"


def asset_key(asset: str) -> str:
    return asset.split(":")[-1]


def last_completed_boundary_ms(*, now_ms: int | None = None, bar_ms: int = BAR_MS) -> int:
    moment = int(time.time() * 1_000) if now_ms is None else int(now_ms)
    return (moment // bar_ms) * bar_ms


def provenance_record() -> dict[str, str]:
    """The complete, frozen reproducibility record CAP-003 demands."""
    return ap.AnalystProvenance(
        analyst_id=mav.PROMPT_VERSION,
        prompt_version=mav.PROMPT_VERSION,
        prompt_digest=mav.prompt_digest(),
        model=ANALYST_MODEL,
        provider=ANALYST_PROVIDER,
        temperature=ap.NOT_EXPOSED,
        schema_version=ap.SCHEMA_VERSION,
        feature_version=ap.FEATURE_VERSION,
        dataset=rmc.PROVIDER,
    ).to_dict()


def fetch_all(connector: Any) -> dict[str, dict[str, list[Any]]]:
    return {
        asset: {key: rmc.fetch_provider_ohlcv(connector, asset, key) for key in rmc.CONTRACT_INTERVALS}
        for asset in rmc.CAMPAIGN_ASSETS
    }


def build_contexts(
    raw_by_asset: dict[str, dict[str, list[Any]]], *, decision_ms: int, decision_time: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Real snapshot artefact + real-context gate, per campaign asset."""
    btc_rows_4h = rmc.completed_rows(
        raw_by_asset["BINANCE:BTCUSDT"]["4h"], decision_ms=decision_ms, interval_key="4h"
    )
    artifacts: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    for asset in rmc.CAMPAIGN_ASSETS:
        rows = {
            key: rmc.completed_rows(raw_by_asset[asset][key], decision_ms=decision_ms, interval_key=key)
            for key in rmc.CONTRACT_INTERVALS
        }
        artifact = rmc.build_real_snapshot_artifact(
            asset=asset,
            decision_time=decision_time,
            rows_by_interval=rows,
            reference_rows_4h=btc_rows_4h,
        )
        artifacts[asset] = artifact
        gates[asset] = rmc.evaluate_g_real_market_context(artifact, snapshot_at=decision_time)
    return artifacts, gates


def write_packages(
    artifacts: dict[str, Any], gates: dict[str, Any], *, decision_ms: int, decision_time: int
) -> None:
    for asset in rmc.CAMPAIGN_ASSETS:
        key = asset_key(asset)
        c1.write_json(OUT / f"REAL_EVIDENCE_{key}.json", artifacts[asset]["raw_evidence"])
        snap = dict(artifacts[asset])
        snap.pop("raw_evidence", None)
        c1.write_json(OUT / f"REAL_SNAPSHOT_{key}.json", snap)
        c1.write_json(OUT / f"REAL_GATE_{key}.json", gates[asset])
        c1.write_json(
            OUT / f"ANALYST_PACKAGE_{key}.json",
            {
                "campaign": "CAP-003",
                "prompt_version": mav.PROMPT_VERSION,
                "prompt_digest": mav.prompt_digest(),
                "system_prompt": mav.SYSTEM_PROMPT,
                "output_fields": list(mav.ANALYST_OUTPUT_FIELDS),
                "allowed_decisions": list(mav.ALLOWED_DECISIONS),
                "allowed_horizons": list(mav.HORIZONS),
                "decision_time": decision_time,
                "decision_boundary_ms": decision_ms,
                "snapshot_hash": artifacts[asset]["snapshot_hash"],
                "raw_data_hash": artifacts[asset]["raw_evidence_hash"],
                "snapshot": artifacts[asset]["snapshot"],
                "provenance_required": list(ap.PROVENANCE_FIELDS),
            },
        )


def seal_phase(
    ledger: dl.DecisionLedger,
    artifacts: dict[str, Any],
    *,
    provenance: dict[str, str],
    decision_ms: int,
    decision_time: int,
) -> dict[str, Any]:
    """Seal every analyst answer that exists for *this* boundary."""
    sealed: dict[str, Any] = {}
    for asset in rmc.CAMPAIGN_ASSETS:
        key = asset_key(asset)
        path = OUT / f"ANALYST_DECISION_{key}.json"
        status: dict[str, Any] = {"asset": asset, "status": "NO_ANALYST_ANSWER", "path": str(path)}
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("decision_time", 0)) != decision_time:
                status["status"] = "STALE_ANSWER_FOR_ANOTHER_BOUNDARY"
                status["answer_decision_time"] = payload.get("decision_time")
            else:
                record = mav.seal_analyst_decision(
                    payload,
                    snapshot_hash=artifacts[asset]["snapshot_hash"],
                    raw_data_hash=artifacts[asset]["raw_evidence_hash"],
                    critic_output={"note": CRITIC_NOTE},
                    provenance=provenance,
                )
                raw_rel = f"{RAW_DIRNAME}/{artifacts[asset]['snapshot_hash']}.json"
                entry = dl.decision_entry(
                    record=record,
                    snapshot_artifact=artifacts[asset],
                    provenance=provenance,
                    raw_evidence_path=raw_rel,
                )
                if ledger.has_decision(record.decision_hash):
                    status["status"] = "ALREADY_IN_LEDGER"
                else:
                    (ledger.root / RAW_DIRNAME).mkdir(parents=True, exist_ok=True)
                    c1.write_json(ledger.root / raw_rel, artifacts[asset]["raw_evidence"])
                    ledger.append_decision(entry)
                    status["status"] = "SEALED"
                status["decision_id"] = entry["decision_id"]
                status["decision"] = record.decision
                status["horizon"] = entry["horizon"]
                status["decision_hash"] = record.decision_hash
                status["record_verified"] = record.is_verified()
                status["provenance_digest"] = entry["provenance_digest"]
                sealed[asset] = status
                c1.write_json(OUT / f"SEALED_DECISION_{key}.json", status)
                c1.write_md(
                    OUT / f"SEALED_DECISION_{key}.md",
                    c1.render(f"CAP-003 SEALED REAL DECISION — {asset}", status),
                )
        else:
            c1.write_json(OUT / f"SEALED_DECISION_{key}.json", status)
    return sealed


def settle_phase(
    ledger: dl.DecisionLedger, raw_by_asset: dict[str, dict[str, list[Any]]]
) -> dict[str, Any]:
    """Close the outcome of every decision whose horizon has matured."""
    settled: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    for entry in ledger.pending_decisions():
        decision_id = str(entry["decision_id"])
        horizon = str(entry["horizon"])
        key = f"{decision_id}:{horizon}"
        asset = str(entry["asset"])
        rows = raw_by_asset[asset]["4h"]
        daily = raw_by_asset[asset]["1D"]
        record = dl.record_from_entry(entry)
        try:
            outcome = do.evaluate_decision(
                record=record, asset=asset, horizon=horizon, rows=rows
            )
        except do.HorizonNotMaturedError as exc:
            results[key] = {"status": "NOT_MATURED", "detail": str(exc)}
            continue
        performance = do.build_performance(
            record=record, outcome=outcome, rows_4h=rows, daily_rows=daily
        )
        ledger.append_outcome(outcome)
        ledger.append_evaluation(performance)
        settled.append(outcome.to_dict())
        results[key] = {
            "status": "SETTLED",
            "outcome": outcome.outcome,
            "net_return": outcome.net_return,
            "outcome_hash": outcome.outcome_hash,
            "evaluation_hash": performance.evaluation_hash,
        }
        c1.write_json(OUT / f"OUTCOME_{asset_key(asset)}_{decision_id[4:12]}_{horizon}.json", outcome.to_dict())
    return {"settled": settled, "per_decision": results}


def selftest_phase(
    raw_by_asset: dict[str, dict[str, list[Any]]], *, decision_ms: int
) -> dict[str, Any]:
    """Prove the full chain on real data with a deterministic (non-LLM) decision."""
    boundary = decision_ms // 1_000 - SELFTEST_BACKOFF_BARS * do.HORIZON_SECONDS["4H"]
    asset = "BINANCE:BTCUSDT"
    rows = raw_by_asset[asset]["4h"]
    daily = raw_by_asset[asset]["1D"]
    direction, reason = do.deterministic_trend_direction(
        rows_4h=rows, daily_rows=daily, decision_time=boundary
    )
    record = ac.seal_decision_record(
        timestamp=boundary,
        prompt_version="CAP-003-PIPELINE-SELFTEST-DETERMINISTIC-NOT-AN-LLM-RUN",
        evidence_snapshot_hash=ac.payload_digest({"selftest": True, "boundary": boundary}),
        agent_output={"selftest": True, "rule": reason, "direction": direction},
        critic_output=None,
        decision=direction,
    )
    payload: dict[str, Any] = {
        "counts_toward_campaign": False,
        "llm_invoked": False,
        "agent_decision_real": False,
        "asset": asset,
        "decision_time": boundary,
        "horizon": SELFTEST_HORIZON,
        "deterministic_rule": do.DETERMINISTIC_RULE_VERSION,
        "direction": direction,
        "reason": reason,
    }
    try:
        outcome = do.evaluate_decision(
            record=record, asset=asset, horizon=SELFTEST_HORIZON, rows=rows
        )
    except do.HorizonNotMaturedError as exc:
        payload["status"] = "NOT_MATURED"
        payload["detail"] = str(exc)
        return payload
    performance = do.build_performance(
        record=record, outcome=outcome, rows_4h=rows, daily_rows=daily
    )
    payload["status"] = "CHAIN_OK"
    payload["outcome"] = outcome.to_dict()
    payload["evaluation"] = performance.to_dict()
    payload["checks"] = {
        "outcome_verified": outcome.is_verified(),
        "evaluation_verified": performance.is_verified(),
        "outcome_links_to_decision": outcome.decision_hash == record.decision_hash,
        "evaluation_links_to_outcome": performance.outcome_hash == outcome.outcome_hash,
        "net_equals_gross_minus_costs": abs(
            outcome.net_return - (outcome.gross_return - outcome.costs)
        )
        < 1e-12,
    }
    return payload


def scorecard_md(scorecard: dict[str, Any]) -> str:
    lines = ["# ALPHA_SCORECARD (CAP-003)", ""]
    lines.append(f"- decisions evaluated: {scorecard['n_decisions_evaluated']}")
    lines.append(f"- directional / no-trade: {scorecard['n_directional']} / {scorecard['n_no_trade']}")
    lines.append(f"- checkpoint reached: {scorecard['sample']['checkpoint_reached']}")
    lines.append(f"- next checkpoint: {scorecard['sample']['next_checkpoint']}")
    lines.append(f"- G_AGENTIC_EDGE = {scorecard['gate']['status']}")
    lines.append(f"- conclusion: {scorecard['gate']['conclusion']}")
    lines.append(f"- alpha claimed: {scorecard['alpha_claimed']}")
    lines.append(f"- profitability: {scorecard['profitability_status']}")
    lines.append("")
    agent = scorecard["agent"]
    lines.append("## A — analyst")
    lines.append("")
    lines.extend(
        c1.md_table(
            ["metric", "value"],
            [
                ["mean net return", agent["mean_net_return"]],
                ["hit rate (directional)", agent["hit_rate_directional"]],
                ["profit factor", agent["profit_factor"]],
                ["max drawdown", agent["max_drawdown"]],
                ["brier (directional)", agent["brier_score_directional"]],
            ],
        )
    )
    lines.append("")
    lines.append("## Comparators and incremental edges")
    lines.append("")
    rows: list[list[Any]] = []
    for baseline_id in (
        do.BASELINE_ID_DETERMINISTIC,
        do.BASELINE_ID_BUY_AND_HOLD,
        do.BASELINE_ID_RANDOM_MATCHED,
    ):
        stats = scorecard["comparators"].get(baseline_id) or {}
        rows.append(
            [
                baseline_id,
                stats.get("n", 0),
                stats.get("mean_net_return"),
                scorecard["incremental_edges"].get(baseline_id),
            ]
        )
    lines.extend(c1.md_table(["comparator", "n", "mean net", "edge vs A"], rows))
    lines.append("")
    lines.append(f"next step: {scorecard['next_step']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    gate_state = c1.entry_gate()
    decision_ms = last_completed_boundary_ms()
    decision_time = decision_ms // 1_000
    provenance = provenance_record()

    connector = rmc.make_connector()
    raw_by_asset = fetch_all(connector)
    artifacts, gates = build_contexts(
        raw_by_asset, decision_ms=decision_ms, decision_time=decision_time
    )
    write_packages(artifacts, gates, decision_ms=decision_ms, decision_time=decision_time)

    ledger = dl.DecisionLedger(LEDGER_ROOT)
    sealed = seal_phase(
        ledger,
        artifacts,
        provenance=provenance,
        decision_ms=decision_ms,
        decision_time=decision_time,
    )
    settlement = settle_phase(ledger, raw_by_asset)
    scorecard = asc.alpha_scorecard(ledger.rebuilt_evaluations())
    selftest = selftest_phase(raw_by_asset, decision_ms=decision_ms)
    chain = ledger.verify_chain()

    g_real = "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL"
    report = {
        "campaign": "CAP-003 REAL DECISION OUTCOME & ALPHA EVALUATION",
        "cycle_decision_time": decision_time,
        "provider": rmc.PROVIDER,
        "source_type": rmc.REAL_SOURCE_TYPE,
        "tradingview_used": False,
        "assets": list(rmc.CAMPAIGN_ASSETS),
        "timeframes": list(rmc.CONTRACT_INTERVALS),
        "g_real_market_context": g_real,
        "g_real_market_context_failed": {
            asset: gates[asset]["failed"] for asset in rmc.CAMPAIGN_ASSETS
        },
        "g_tv_context": ac.G_TV_CONTEXT,
        "market_analyst": {
            "version": mav.PROMPT_VERSION,
            "frozen": True,
            "prompt_digest": mav.prompt_digest(),
        },
        "provenance": provenance,
        "provenance_digest": ap.provenance_digest(provenance),
        "seal_phase": sealed,
        "sealed_this_cycle": [
            item["decision_id"] for item in sealed.values() if item["status"] == "SEALED"
        ],
        "settle_phase": settlement["per_decision"],
        "settled_this_cycle": len(settlement["settled"]),
        "ledger": chain,
        "selftest": selftest,
        "alpha_scorecard": scorecard,
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "alpha_claimed": ac.ALPHA_CLAIMED,
        "alpha_research_freeze": ac.ALPHA_RESEARCH_FREEZE,
        "next_alpha_rfc_allowed": ac.NEXT_ALPHA_RFC_ALLOWED,
        "economic_state_digest": c1.file_digest(c1.ECONOMIC_STATE),
        "entry_gate": {
            "branch": gate_state["branch"],
            "head_short": gate_state["head_short"],
            "freeze_seen": gate_state["freeze_seen"],
            "next_alpha_rfc_allowed_seen": gate_state["next_alpha_rfc_allowed_seen"],
        },
    }

    c1.write_json(OUT / "LEDGER_CHAIN.json", chain)
    c1.write_json(OUT / "PIPELINE_SELFTEST.json", selftest)
    c1.write_md(OUT / "PIPELINE_SELFTEST.md", c1.render("CAP-003 pipeline self-test", selftest))
    c1.write_json(REPORTS / "ALPHA_SCORECARD.json", scorecard)
    c1.write_md(REPORTS / "ALPHA_SCORECARD.md", scorecard_md(scorecard))
    c1.write_json(REPORTS / "CAP003_CAMPAIGN_REPORT.json", report)
    c1.write_md(
        REPORTS / "CAP003_CAMPAIGN_REPORT.md",
        c1.render("CAP-003 REAL DECISION OUTCOME & ALPHA EVALUATION", report),
    )

    print("CAP-003 CAMPAIGN CYCLE")
    print(f"provider = {rmc.PROVIDER}  decision_time = {decision_time}")
    print(f"G_REAL_MARKET_CONTEXT = {g_real}   G_TV_CONTEXT = {ac.G_TV_CONTEXT}")
    print(f"analyst = {mav.PROMPT_VERSION} (frozen)  provenance_digest = {report['provenance_digest'][:16]}")
    for asset in rmc.CAMPAIGN_ASSETS:
        item = sealed.get(asset, {"status": "NO_ANALYST_ANSWER"})
        print(f"  {asset}: {item['status']}  {item.get('decision', '')} {item.get('horizon', '')}")
    print(f"sealed this cycle = {len(report['sealed_this_cycle'])}")
    print(f"ledger: {chain['n_decisions']} decisions, {chain['n_outcomes']} outcomes, "
          f"{chain['n_evaluations']} evaluations  CHAIN={chain['status']}")
    print(f"settled this cycle = {report['settled_this_cycle']}")
    print(f"selftest = {selftest['status']}  checks={selftest.get('checks')}")
    print(f"G_AGENTIC_EDGE = {scorecard['gate']['status']}  ({scorecard['gate']['conclusion']})")
    print(f"Trades authorized = {ac.TRADES_AUTHORIZED}   Alpha claimed = {ac.ALPHA_CLAIMED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
