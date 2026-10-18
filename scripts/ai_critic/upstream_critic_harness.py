"""upstream_critic_harness — run the *pinned* TradingAgents research debate offline.

This is an audit instrument, not runtime code. It imports the original node factories
from a pinned checkout (``TauricResearch/TradingAgents`` @
``e8f5503e9b86d5c2710b0c76b1f686703968c9df``), drives them with a scripted LLM and no
network, and records what the upstream code actually did:

* the Bull Researcher's opening turn (opponent has not spoken yet),
* the Bear Researcher replying to that real argument,
* the router's transition to the Research Manager at the round budget,
* the Research Manager consuming the debate history through the original
  structured-output path (and its free-text fallback when the schema call fails),
* ``tradingagents.reporting.write_report_tree`` rendering ``complete_report.html``.

No model is called: every ``llm.invoke`` is a local fixture. The resulting evidence is
labelled ``UPSTREAM_PYTHON_INSTRUMENTED_NOT_REA`` — REA observes the rendered page, it
does not observe this reasoning.

Run with the pinned checkout's interpreter, e.g.::

    ta_lab/.venv/Scripts/python.exe scripts/ai_critic/upstream_critic_harness.py \
        --upstream-root ../ta_lab --out reports/ai-bots/RFC-AI-BOTS-004/upstream

Exit codes: 0 the harness completed and every assertion held; 2 a check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import socket
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_ID = "T-TA-CRITIC"
SOURCE_COMMIT = "e8f5503e9b86d5c2710b0c76b1f686703968c9df"
SOURCE_URL = "https://github.com/TauricResearch/TradingAgents.git"
EXPECTED_LICENSE = "Apache License"

#: The upstream files this harness exercises or renders with. Hashes are the audit pin.
SOURCE_FILES = {
    "tradingagents/agents/researchers/bull_researcher.py",
    "tradingagents/agents/researchers/bear_researcher.py",
    "tradingagents/agents/managers/research_manager.py",
    "tradingagents/agents/context.py",
    "tradingagents/agents/schemas.py",
    "tradingagents/agents/structured.py",
    "tradingagents/agents/state.py",
    "tradingagents/graph/conditional_logic.py",
    "tradingagents/reporting.py",
    "tradingagents/report_html.py",
    "tradingagents/agents/rating.py",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(payload.encode("utf-8"))


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Deterministic scripted provider (no model, no network)
# ---------------------------------------------------------------------------


@dataclass
class ScriptedResponse:
    content: str


@dataclass
class ScriptedLLM:
    """A provider-shaped stub: scripted prose plus a scripted structured path."""

    name: str = "scripted-upstream-fixture"
    _model: str = "STUB-UPSTREAM-CRITIC-004"
    prompts: list[str] = field(default_factory=list)
    structured_prompts: list[str] = field(default_factory=list)
    structured_mode: str = "valid"  # valid | raise | wrong_type
    _structured_calls: int = 0

    def with_structured_output(self, schema: Any) -> ScriptedStructured:
        return ScriptedStructured(llm=self, schema=schema)

    def invoke(self, prompt: str) -> ScriptedResponse:
        self.prompts.append(prompt)
        return ScriptedResponse(content=free_text_answer(len(self.prompts)))


@dataclass
class ScriptedStructured:
    llm: ScriptedLLM
    schema: Any

    def invoke(self, prompt: str) -> Any:
        self.llm.structured_prompts.append(prompt)
        self.llm._structured_calls += 1
        if self.llm.structured_mode == "raise":
            # A provider that cannot parse its own JSON is the documented case the
            # upstream code falls back from.
            raise ValueError("scripted malformed JSON: provider returned no parsed result")
        if self.llm.structured_mode == "wrong_type":
            return {"recommendation": "Maybe", "rationale": "x", "strategic_actions": "y"}
        return self.schema(
            recommendation="Overweight",
            rationale=(
                "The bull case carried the growth argument while the bear case failed to "
                "price the demand trend; the debate history is the deciding evidence."
            ),
            strategic_actions="Gradually increase exposure against a standard allocation.",
        )


def free_text_answer(turn: int) -> str:
    return (
        f"Scripted upstream fixture turn {turn}: the case is argued from the supplied "
        "research reports, names the opposing argument it answers, and states no order, "
        "size, leverage or risk change. MODEL_STATUS=STUB."
    )


# ---------------------------------------------------------------------------
# Trace plumbing
# ---------------------------------------------------------------------------


class TraceWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: list[dict[str, Any]] = []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def network_guard() -> dict[str, int]:
    """Refuse every outbound socket and count attempts, so ``network_calls=0`` is measured."""
    counter = {"attempts": 0}
    original_connect = socket.socket.connect

    def blocked_connect(self: socket.socket, address: Any) -> Any:
        counter["attempts"] += 1
        raise RuntimeError(f"network disabled by harness: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket._harness_original_connect = original_connect  # type: ignore[attr-defined]
    return counter


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    upstream = Path(args.upstream_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(upstream))
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # -- provenance before importing anything from the checkout -----------------
    license_text = (upstream / "LICENSE").read_text(encoding="utf-8", errors="replace")
    check("license_is_apache_2_0", license_text.lstrip().startswith(EXPECTED_LICENSE),
          license_text.splitlines()[0].strip())
    import subprocess

    head = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    check("upstream_head_matches_pin", head == SOURCE_COMMIT, head)
    file_hashes = {}
    for rel in sorted(SOURCE_FILES):
        path = upstream / rel
        file_hashes[rel] = sha256_file(path) if path.exists() else None
    check("every_exercised_file_present", all(file_hashes.values()))

    # -- import the original code ---------------------------------------------
    from unittest.mock import MagicMock

    from tradingagents.agents.managers.research_manager import create_research_manager
    from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
    from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
    from tradingagents.agents.schemas import ResearchPlan
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.reporting import write_report_tree

    counter = network_guard()
    traces = TraceWriter(out / "UPSTREAM_PYTHON_TRACE.jsonl")

    def trace(agent: str, sequence: int, **extra: Any) -> None:
        row = {
            "trace_id": f"TAP004-UPSTREAM-{sequence:03d}",
            "source_id": SOURCE_ID,
            "source_commit": SOURCE_COMMIT,
            "source_stage": "UPSTREAM_PYTHON_INSTRUMENTED_NOT_REA",
            "agent": agent,
            "sequence": sequence,
            "model_status": "STUB",
            "network_calls": counter["attempts"],
            "orders": 0,
            "captured_at": utc_now(),
        }
        row.update(extra)
        traces.append(row)

    reports = {
        "company_of_interest": "BTC/USDT",
        "asset_type": "crypto",
        "trade_date": "2026-10-17",
        "instrument_context": "Instrument: BTC/USDT (crypto pair), resolved for this fixture.",
        "market_report": "Momentum above the 20/50 EMA with rising volume; resistance at 71 400.",
        "sentiment_report": "Positioning is neutral-to-long; funding is not stretched.",
        "news_report": "No scheduled macro event inside the decision window.",
        "fundamentals_report": "(crypto: fundamentals are not supplied in this fixture)",
        "portfolio_context": "",
        "memory_note": "",
    }

    llm = ScriptedLLM()
    bull = create_bull_researcher(llm)
    bear = create_bear_researcher(llm)
    manager_llm = ScriptedLLM(structured_mode="valid")
    manager = create_research_manager(manager_llm)
    router = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)

    state: dict[str, Any] = {
        **reports,
        "investment_debate_state": {
            "history": "", "bull_history": "", "bear_history": "",
            "current_response": "", "count": 0,
        },
        "investment_plan": "",
    }

    sequence = 1
    # (a) Bull opens: the opponent has not spoken.
    input_sha = canonical_sha256(state)
    bull_out = bull(state)
    bull_prompt = llm.prompts[-1]
    bull_argument = bull_out["investment_debate_state"]["current_response"]
    trace(
        "Bull Researcher", sequence,
        prompt_sha256=sha256_bytes(bull_prompt.encode("utf-8")),
        prompt_chars=len(bull_prompt),
        input_state_sha256=input_sha,
        output_state_sha256=canonical_sha256({**state, **bull_out}),
        response_sha256=sha256_bytes(bull_argument.encode("utf-8")),
        response_type="free_text",
        opening_marker="has not spoken yet" in bull_prompt,
        opponent_argument_present=False,
        debate_count=bull_out["investment_debate_state"]["count"],
        router_decision=None,
        source_file="tradingagents/agents/researchers/bull_researcher.py",
        source_file_sha256=file_hashes["tradingagents/agents/researchers/bull_researcher.py"],
    )
    check("bull_prompt_states_the_opponent_has_not_spoken",
          "has not spoken yet" in bull_prompt)
    check("bull_does_not_receive_an_invented_bear_argument",
          "Last bear argument: (The bear analyst has not spoken yet" in bull_prompt)

    state = {**state, **bull_out}
    decision = router.should_continue_debate(state)
    trace("ConditionalLogic.should_continue_debate", sequence + 1,
          router_decision=decision, debate_count=state["investment_debate_state"]["count"],
          input_state_sha256=canonical_sha256(state),
          source_file="tradingagents/graph/conditional_logic.py",
          source_file_sha256=file_hashes["tradingagents/graph/conditional_logic.py"])
    check("router_sends_bull_opening_to_bear", decision == "Bear Researcher", decision)
    sequence += 2

    # (b) Bear answers the real bull argument.
    input_sha = canonical_sha256(state)
    bear_out = bear(state)
    bear_prompt = llm.prompts[-1]
    bear_argument = bear_out["investment_debate_state"]["current_response"]
    trace("Bear Researcher", sequence,
          prompt_sha256=sha256_bytes(bear_prompt.encode("utf-8")),
          prompt_chars=len(bear_prompt),
          input_state_sha256=input_sha,
          output_state_sha256=canonical_sha256({**state, **bear_out}),
          response_sha256=sha256_bytes(bear_argument.encode("utf-8")),
          response_type="free_text",
          opening_marker="has not spoken yet" in bear_prompt,
          opponent_argument_present=bull_argument in bear_prompt,
          debate_count=bear_out["investment_debate_state"]["count"],
          router_decision=None,
          source_file="tradingagents/agents/researchers/bear_researcher.py",
          source_file_sha256=file_hashes["tradingagents/agents/researchers/bear_researcher.py"],
    )
    check("bear_receives_the_real_bull_argument", bull_argument in bear_prompt)
    check("bear_does_not_treat_the_bull_as_silent",
          "has not spoken yet" not in bear_prompt)

    state = {**state, **bear_out}
    decision = router.should_continue_debate(state)
    trace("ConditionalLogic.should_continue_debate", sequence + 1,
          router_decision=decision, debate_count=state["investment_debate_state"]["count"],
          input_state_sha256=canonical_sha256(state),
          source_file="tradingagents/graph/conditional_logic.py",
          source_file_sha256=file_hashes["tradingagents/graph/conditional_logic.py"])
    check("router_terminates_at_round_budget", decision == "Research Manager", decision)
    sequence += 2

    # Extra router case: one more hypothetical turn must still terminate.
    over_budget = {
        **state,
        "investment_debate_state": {**state["investment_debate_state"], "count": 2},
    }
    trace("ConditionalLogic.should_continue_debate", sequence,
          router_decision=router.should_continue_debate(over_budget),
          debate_count=2, case="over_budget_recheck",
          input_state_sha256=canonical_sha256(over_budget),
          source_file="tradingagents/graph/conditional_logic.py",
          source_file_sha256=file_hashes["tradingagents/graph/conditional_logic.py"])
    check("router_terminates_when_count_exceeds_budget",
          router.should_continue_debate(over_budget) == "Research Manager")
    sequence += 1

    # (c) Research Manager consumes the history through the structured path.
    input_sha = canonical_sha256(state)
    manager_out = manager(state)
    rm_prompt = manager_llm.structured_prompts[-1]
    plan_text = manager_out["investment_plan"]
    trace("Research Manager", sequence,
          prompt_sha256=sha256_bytes(rm_prompt.encode("utf-8")),
          prompt_chars=len(rm_prompt),
          input_state_sha256=input_sha,
          output_state_sha256=canonical_sha256({**state, **manager_out}),
          response_sha256=sha256_bytes(plan_text.encode("utf-8")),
          response_type="structured_valid",
          opening_marker=False,
          opponent_argument_present=bull_argument in rm_prompt,
          debate_count=state["investment_debate_state"]["count"],
          router_decision=None,
          source_file="tradingagents/agents/managers/research_manager.py",
          source_file_sha256=file_hashes["tradingagents/agents/managers/research_manager.py"],
    )
    check("manager_prompt_contains_the_debate_history",
          bull_argument in rm_prompt and bear_argument in rm_prompt)
    check("structured_plan_renders_recommendation", "Overweight" in plan_text, plan_text[:80])
    state = {**state, **manager_out}
    sequence += 1

    # (c2) The schema itself rejects an out-of-vocabulary recommendation.
    schema_rejected = False
    try:
        ResearchPlan(recommendation="Maybe", rationale="x", strategic_actions="y")
    except Exception as exc:  # pydantic ValidationError
        schema_rejected = True
        schema_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    trace("ResearchPlan.schema", sequence,
          response_type="schema_rejected", schema_rejected=schema_rejected,
          detail=schema_error if schema_rejected else "accepted an invalid rating",
          source_file="tradingagents/agents/schemas.py",
          source_file_sha256=file_hashes["tradingagents/agents/schemas.py"])
    check("schema_rejects_unknown_rating", schema_rejected)
    sequence += 1

    # (c3) Structured call fails -> upstream falls back to free text.
    fallback_llm = ScriptedLLM(structured_mode="raise")
    fallback_manager = create_research_manager(fallback_llm)
    fallback_out = fallback_manager(state)
    trace("Research Manager", sequence,
          response_type="freetext_fallback",
          structured_attempts=fallback_llm._structured_calls,
          freetext_attempts=len(fallback_llm.prompts),
          input_state_sha256=input_sha,
          output_sha256=sha256_bytes(
              fallback_out["investment_plan"].encode("utf-8")),
          response_sha256=sha256_bytes(
              fallback_out["investment_plan"].encode("utf-8")),
          opening_marker=False,
          debate_count=state["investment_debate_state"]["count"],
          source_file="tradingagents/agents/managers/research_manager.py",
          source_file_sha256=file_hashes["tradingagents/agents/managers/research_manager.py"],
    )
    check("failed_structured_call_falls_back_once_to_free_text",
          fallback_llm._structured_calls == 1 and len(fallback_llm.prompts) == 1,
          f"structured={fallback_llm._structured_calls} free_text={len(fallback_llm.prompts)}")
    sequence += 1

    # (c4) A provider without with_structured_output is also handled.
    plain_only = MagicMock(spec=["invoke"])
    plain_only.invoke.return_value = ScriptedResponse(content="free-text-only plan")
    plain_manager = create_research_manager(plain_only)
    plain_out = plain_manager(state)
    trace("Research Manager", sequence,
          response_type="no_structured_support",
          freetext_attempts=plain_only.invoke.call_count,
          output_sha256=sha256_bytes(plain_out["investment_plan"].encode("utf-8")),
          source_file="tradingagents/agents/managers/research_manager.py",
          source_file_sha256=file_hashes["tradingagents/agents/managers/research_manager.py"])
    check("provider_without_structured_support_uses_free_text",
          plain_out["investment_plan"] == "free-text-only plan", plain_out["investment_plan"])
    sequence += 1

    # -- write the final state and render the original HTML --------------------
    final_state = {
        **state,
        "investment_plan": manager_out["investment_plan"],
    }
    (out / "final_state.json").write_text(
        json.dumps(final_state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    final_state_sha = canonical_sha256(final_state)

    settings = {
        "version": "TAP-004-upstream-fixture",
        "llm_provider": "scripted-stub",
        "deep_think_llm": "STUB-UPSTREAM-CRITIC-004",
        "quick_think_llm": "STUB-UPSTREAM-CRITIC-004",
        "analysts": ["market", "sentiment", "news", "fundamentals"],
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "data_vendors": {},
    }
    report_tree = out / "report_tree"
    write_report_tree(final_state, "BTC/USDT", report_tree, settings=settings, html=True)
    html_path = report_tree / "complete_report.html"
    md_path = report_tree / "complete_report.md"
    check("complete_report_html_written", html_path.exists())
    check("complete_report_md_written", md_path.exists())
    html_text = html_path.read_text(encoding="utf-8")
    check("html_has_no_script", "<script" not in html_text.lower())
    check("html_has_no_remote_asset",
          not any(f"<{tag}" in html_text.lower() for tag in ("img", "link", "iframe", "embed")))
    check("html_shows_bull_bear_and_manager_sections",
          all(token in html_text for token in ("Bull Researcher", "Bear Researcher",
                                               "Research Manager")))
    check("html_carries_the_debate_text", "Scripted upstream fixture turn 1" in html_text)

    html_sha = sha256_file(html_path)
    html_meta = {
        "schema_version": "TAP004_HTML_REPORT_V1",
        "source_id": SOURCE_ID,
        "source_commit": SOURCE_COMMIT,
        "renderer": "tradingagents.reporting.write_report_tree(html=True)",
        "renderer_source_sha256": file_hashes["tradingagents/reporting.py"],
        "render_html_source_sha256": file_hashes["tradingagents/report_html.py"],
        "final_state_sha256": final_state_sha,
        "html_path": "report_tree/complete_report.html",
        "html_sha256": html_sha,
        "html_bytes": html_path.stat().st_size,
        "markdown_sha256": sha256_file(md_path),
        "javascript_present": "<script" in html_text.lower(),
        "remote_assets_present": False,
        "state_provenance": "nodes executed in this harness from the pinned source",
        "analyst_reports_provenance": "declared fixture inputs, not produced by this harness",
        "generated_at": utc_now(),
    }
    (out / "HTML_REPORT_SHA256.json").write_text(
        json.dumps(html_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    meta = {
        "schema_version": "TAP004_UPSTREAM_HARNESS_V1",
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "license": "Apache-2.0",
        "license_sha256": sha256_file(upstream / "LICENSE"),
        "file_sha256": file_hashes,
        "python": sys.version,
        "platform": platform.platform(),
        "network_calls": counter["attempts"],
        "orders": 0,
        "model_status": "STUB",
        "reconstruction_stage": "UPSTREAM_PYTHON_INSTRUMENTED_NOT_REA",
        "final_state_sha256": final_state_sha,
        "html_sha256": html_sha,
        "trace_rows": len(traces.rows),
        "checks": checks,
        "checks_passed": sum(1 for c in checks if c["ok"]),
        "checks_total": len(checks),
        "generated_at": utc_now(),
    }
    (out / "UPSTREAM_HARNESS_META.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    failed = [c for c in checks if not c["ok"]]
    print(json.dumps({"checks_passed": meta["checks_passed"],
                      "checks_total": meta["checks_total"],
                      "failed": failed,
                      "network_calls": counter["attempts"],
                      "html_sha256": html_sha}, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(3) from None
