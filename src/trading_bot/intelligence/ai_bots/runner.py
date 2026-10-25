"""runner — one canonical book, one bot at a time, traces for every call.

The runner owns the pieces a bot may not have: the ``RiskManager``, the ``PaperBroker``,
the venue cost schedule and the clock. A bot arrives as a ``VisionProvider``-shaped
adapter plus its prompt, which means the two discretionary agents trade the same book
under identical limits and the only variable is what they were shown.

Two local decisions worth stating:

* **Provider budget is real even in mock runs.** The wrapper counts calls and refuses to
  exceed the bot's declared ``max_calls_per_day``, so a mock cannot quietly become a
  1 000-call rehearsal.
* **Every call is traced before it is used.** ``MODEL_INVOCATIONS.jsonl`` is appended as
  the call returns, so a crash mid-run still leaves the receipt of what was paid for.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.config.risk import Risk
from trading_bot.intelligence.ai_bots.bots import TraceWriter, invocation_row
from trading_bot.intelligence.ai_bots.registry import BotCapabilityRegistry
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.prompt import PromptBundle, build_prompt
from trading_bot.vision.provider import (
    ProviderError,
    ReplayProvider,
    VisionProvider,
    VisionRequest,
    VisionResponse,
)
from trading_bot.vision.settings import VisionConfig


class BudgetExceeded(ProviderError):
    def __init__(self, bot_id: str, limit: int) -> None:
        super().__init__(
            "CALL_BUDGET_EXCEEDED",
            f"{bot_id} reached its declared budget of {limit} calls for this run",
            attempts=0,
        )


@dataclass
class TracedProvider:
    """Wraps a provider so every call leaves a receipt and cannot exceed a budget."""

    inner: VisionProvider
    bot_id: str
    run_id: str
    traces: TraceWriter
    max_calls: int
    calls: int = 0
    successful_calls: int = 0
    exceeded: bool = False
    #: A settable attribute, not a property: the provider protocol expects one.
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = str(getattr(self.inner, "name", "unknown"))

    def analyze(self, request: VisionRequest) -> VisionResponse:
        if self.calls >= self.max_calls:
            if not self.exceeded:
                self.exceeded = True
                self.traces.invocation(
                    {
                        "invocation_id": f"{self.bot_id}-{self.run_id}-budget",
                        "run_id": self.run_id,
                        "bot_id": self.bot_id,
                        "provider": self.name,
                        "model_id": getattr(self.inner, "_model", "unknown"),
                        "prompt_id": request.prompt.version,
                        "prompt_sha256": request.prompt.sha256,
                        "input_image_sha256": request.chart.sha256,
                        "image_attached": False,
                        "decision_time_ms": request.decision_ts_ms,
                        "model_status": "CALL_BUDGET_EXCEEDED",
                        "error_class": "BudgetExceeded",
                        "provider_cost_usd": 0.0,
                    }
                )
            raise BudgetExceeded(self.bot_id, self.max_calls)
        self.calls += 1
        invocation_id = f"{self.bot_id}-{self.run_id}-{self.calls:05d}"
        try:
            response = self.inner.analyze(request)
        except ProviderError as exc:
            self.traces.invocation(
                {
                    "invocation_id": invocation_id,
                    "run_id": self.run_id,
                    "bot_id": self.bot_id,
                    "provider": self.name,
                    "model_id": getattr(self.inner, "_model", "unknown"),
                    "prompt_id": request.prompt.version,
                    "prompt_sha256": request.prompt.sha256,
                    "input_image_sha256": request.chart.sha256,
                    "image_attached": False,
                    "decision_time_ms": request.decision_ts_ms,
                    "model_status": exc.code,
                    "error_class": type(exc).__name__,
                    "provider_cost_usd": 0.0,
                }
            )
            raise
        self.traces.invocation(
            invocation_row(
                invocation_id=invocation_id,
                run_id=self.run_id,
                bot_id=self.bot_id,
                request=request,
                response=response,
                model_status="OK",
            )
        )
        self.successful_calls += 1
        return response


MOCK_PROVIDER_NAMES = frozenset({"replay", "mock-script"})


def _model_status(provider: VisionProvider, traced: TracedProvider) -> str:
    # A wrapper hides the real provider one level down; the name is part of the trace.
    inner = getattr(provider, "inner", provider)
    name = str(getattr(inner, "name", ""))
    if isinstance(inner, ReplayProvider) or name in MOCK_PROVIDER_NAMES:
        return "MOCK_TEST"
    if traced.successful_calls:
        return "REAL_MODEL_CALL"
    return "REAL_MODEL_ATTEMPTED_FAILED"


def run_bot(
    *,
    registry: BotCapabilityRegistry,
    bot_id: str,
    series: Mapping[str, Sequence[Any]],
    provider: VisionProvider,
    risk_policy: Risk,
    out_dir: Path | str,
    config: VisionConfig,
    run_id: str | None = None,
    prompt_builder: Callable[[dict[str, Any], Sequence[Any]], PromptBundle] | None = None,
    equity: float = 10_000.0,
    decision_every_bars: int | None = None,
    max_calls: int | None = None,
    max_spend_usd: float | None = None,
    prompt_version: str | None = None,
    allow_disabled: bool = False,
) -> dict[str, Any]:
    """Run one bot over one dataset, with the canonical book and a trace trail.

    ``allow_disabled`` exists for tests that must exercise a disabled bot; the flag is
    never passed by the benchmark, which is where a bot would be mistaken for active.
    """
    spec = registry.get(bot_id)
    if not allow_disabled and spec not in registry.active():
        raise PermissionError(
            f"{bot_id} is not enabled (AI_BOTS_ENABLED={registry.enabled}, "
            f"bot enabled={spec.enabled}); a disabled bot must not run"
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    traces = TraceWriter(out)
    resolved_run_id = run_id or uuid.uuid4().hex[:12]
    budget = int(max_calls if max_calls is not None else spec.max_calls_per_day)
    traced = TracedProvider(
        inner=provider,
        bot_id=bot_id,
        run_id=resolved_run_id,
        traces=traces,
        max_calls=budget,
    )

    lane = VisionLane(
        series={symbol: list(bars) for symbol, bars in series.items()},
        provider=traced,
        config=config,
        risk_policy=risk_policy,
        ledger_path=out / f"{bot_id}_DECISIONS.jsonl",
        equity=equity,
        book_id=f"paper-{bot_id.lower()}",
        decision_every_bars=decision_every_bars,
        # The lane stops itself at the same number the wrapper enforces, so the run ends
        # cleanly instead of paying for one attempt that the trace must then refuse.
        max_calls=budget,
        max_spend_usd=max_spend_usd,
        prompt_builder=prompt_builder or (lambda context, _bars: build_prompt(context)),
    )
    summary = lane.run()
    if traced.exceeded and not summary.get("stop_reason"):
        summary["stop_reason"] = "MAX_CALLS_REACHED"
    summary.update(
        {
            "bot_id": bot_id,
            "bot_version": spec.bot_version,
            "family": spec.family,
            "run_id": resolved_run_id,
            "provider_calls_traced": traced.calls,
            "call_budget": budget,
            "paper_namespace": spec.paper_namespace,
            "prompt_version": prompt_version or "ai-vision-prompt/2",
            # A real call is only named as such when a successful receipt exists.
            "model_status": _model_status(provider, traced),
        }
    )
    traces.decision(
        {
            "run_id": resolved_run_id,
            "bot_id": bot_id,
            "bot_version": spec.bot_version,
            "summary": summary,
        }
    )
    return summary
