"""bots — the two discretionary agents, and the trace they leave behind.

``VisualBot``     BOT-VIS-01: a PNG of candles plus numeric context.
``StructuredBot`` BOT-CTX-01: the same context as numbers and multi-timeframe structure,
                  **no image at all**, which is what makes it a scientific control: if the
                  structured bot does as well as the visual one, the chart added nothing.

Both are exposed through the same ``analyze(request)`` shape the visual lane already
uses, so the canonical book — one ``RiskManager``, one ``PaperBroker``, one cost
schedule, one clock — is shared rather than re-instantiated per bot. Neither module
imports ``PaperBroker``: a bot that can reach the broker is not an opinion.

The structured bot is deliberately *not* a translation of any AGPL project: the MTF
summary below is our own contract (returns, ranges, regime label, ATR) built from the
same causal bars the visual lane draws.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from trading_bot.vision.prompt import PromptBundle
from trading_bot.vision.provider import (
    OpenAICompatibleVisionProvider,
    PriceTable,
    ProviderError,
    VisionProvider,
    VisionRequest,
    VisionResponse,
)
from trading_bot.vision.settings import VisionConfig

STRUCTURED_PROMPT_VERSION = "aibot-ctx-prompt/1"


# ---------------------------------------------------------------------------
# multi-timeframe features (numbers, no image)
# ---------------------------------------------------------------------------


def resample_closed(bars: Sequence[Any], factor: int) -> list[dict[str, float]]:
    """Aggregate ``factor`` 1h bars into one higher-timeframe bar.

    Only complete groups are emitted, so an HTF bar is never a partly-formed window: the
    last group is dropped unless it is exactly full.
    """
    if factor < 2:
        raise ValueError("factor must be >= 2")
    out: list[dict[str, float]] = []
    for start in range(0, len(bars) - factor + 1, factor):
        group = bars[start : start + factor]
        out.append(
            {
                "open": float(group[0].open),
                "high": max(float(bar.high) for bar in group),
                "low": min(float(bar.low) for bar in group),
                "close": float(group[-1].close),
                "volume": sum(float(bar.volume) for bar in group),
                "open_ms": int(group[0].ts_ms),
            }
        )
    return out


def _pct_change(values: Sequence[float]) -> float | None:
    if len(values) < 2 or values[0] == 0:
        return None
    return (values[-1] / values[0] - 1.0) * 100.0


def _true_range_pct(bars: Sequence[Any]) -> float | None:
    if len(bars) < 3:
        return None
    ranges = []
    for previous, current in pairwise(bars):
        high, low, prev_close = float(current.high), float(current.low), float(previous.close)
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    last = float(bars[-1].close)
    return None if last <= 0 else sum(ranges) / len(ranges) / last * 100.0


def _regime(closes: Sequence[float], window: int = 20) -> str:
    """A label, not a signal: the model still decides what to do with it."""
    if len(closes) < window + 1:
        return "UNKNOWN"
    recent = closes[-window:]
    span = max(recent) - min(recent)
    if span == 0:
        return "FLAT"
    drift = (recent[-1] - recent[0]) / span
    if drift > 0.5:
        return "TREND_UP"
    if drift < -0.5:
        return "TREND_DOWN"
    return "RANGE"


def mtf_features(bars: Sequence[Any]) -> dict[str, Any]:
    """Everything BOT-CTX-01 sees. Causal: only bars passed in are used."""
    closes = [float(bar.close) for bar in bars]
    features: dict[str, Any] = {
        "bars": len(bars),
        "last_close": closes[-1] if closes else None,
        "return_1h_pct": _pct_change(closes[-2:]) if len(closes) >= 2 else None,
        "return_24h_pct": _pct_change(closes[-24:]) if len(closes) >= 24 else None,
        "return_120h_pct": _pct_change(closes[-120:]) if len(closes) >= 120 else None,
        "atr_pct": _true_range_pct(bars),
        "regime": _regime(closes),
        "range_high": max((float(b.high) for b in bars), default=None),
        "range_low": min((float(b.low) for b in bars), default=None),
    }
    four_hour = resample_closed(bars, 4)
    features["htf_4h"] = {
        "bars": len(four_hour),
        "return_4h_pct": _pct_change([row["close"] for row in four_hour]) if four_hour else None,
        "last_close": four_hour[-1]["close"] if four_hour else None,
        "last_closed_open_ms": four_hour[-1]["open_ms"] if four_hour else None,
    }
    return features


CTX_SYSTEM_PROMPT = """You are a discretionary crypto trader reading a numeric market summary.

You do not receive a chart. You receive multi-timeframe numbers: returns, range, ATR,
regime label and higher-timeframe structure, plus your open position and the account.

Rules:
- Answer with ONE JSON object and no other text.
- action is exactly one of: "LONG", "SHORT", "CLOSE", "NO_TRADE".
- You do not choose size, leverage or risk. Do not mention them; they are refused.
- For LONG or SHORT you must give stop_loss_pct.
- If the numbers do not give you an edge, answer NO_TRADE. Uncertainty is not a reason to
  trade.

JSON schema:
{
  "schema_version": "ai-vision-decision/1",
  "symbol": "<the symbol you were given>",
  "action": "LONG" | "SHORT" | "CLOSE" | "NO_TRADE",
  "confidence": <0..1>,
  "horizon_bars": <integer 1..168>,
  "stop_loss_pct": <number, required for LONG/SHORT>,
  "take_profit_pct": <number or null>,
  "invalidation": "<short text or null>",
  "rationale": "<what the numbers say and why this action, at most 600 characters>"
}"""


def build_structured_prompt(context: dict[str, Any], bars: Sequence[Any]) -> PromptBundle:
    """The control prompt: same decision contract, no image, explicit features."""
    features = mtf_features(bars)
    lines = [
        f"Symbol: {context.get('symbol')}",
        f"Timeframe: {context.get('timeframe', '1h')}",
        "You have no chart image. These are the numbers.",
        "",
        "Features (causal, closed bars only):",
        json.dumps(features, sort_keys=True, default=str),
        "",
    ]
    position = context.get("position")
    if position:
        lines.append(
            "Open position: {side} entered at {entry:.2f}, {upnl:+.2f} USDT unrealised.".format(
                side=str(position["side"]).upper(),
                entry=float(position["entry_price"]),
                upnl=float(position.get("unrealised_usdt", 0.0)),
            )
        )
        lines.append("Answer CLOSE to exit. Do not answer the opposite side.")
    else:
        lines.append("Open position: none in this symbol.")
    lines.append("")
    lines.append(
        "Account: equity {equity:.2f} USDT, {open_positions}/{max_positions} slots used, "
        "{risk:.2f}% risk per trade, {weekly:.2f}% weekly loss cap.".format(
            equity=float(context.get("equity", 0.0)),
            open_positions=int(context.get("open_positions", 0)),
            max_positions=int(context.get("max_open_positions", 0)),
            risk=float(context.get("risk_per_trade_pct", 0.0)),
            weekly=float(context.get("max_weekly_loss_pct", 0.0)),
        )
    )
    lines.append("")
    lines.append("Decide now for the bar that just closed. Answer with the JSON object only.")
    return PromptBundle(system=CTX_SYSTEM_PROMPT, user="\n".join(lines),
                        version=STRUCTURED_PROMPT_VERSION)


@dataclass(frozen=True, slots=True)
class TextOnlyVisionProvider:
    """BOT-CTX-01's transport: the same endpoint, the payload without an image.

    It reports ``image_sha256_in_request == ""`` so a trace can never claim an image was
    sent, and the lane treats an empty hash as "no image", never as a mismatch.
    """

    delegate: OpenAICompatibleVisionProvider
    name: str = "openai-compatible-text"

    def analyze(self, request: VisionRequest) -> VisionResponse:
        payload = self.delegate.build_payload(request)
        user_content = payload["messages"][1]["content"]
        payload["messages"][1]["content"] = [part for part in user_content if part["type"] == "text"]
        response = self.delegate.analyze_payload(payload, request)
        return VisionResponse(
            text=response.text,
            model=response.model,
            provider=self.name,
            request_id=response.request_id,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            usage=response.usage,
            cost_usd=response.cost_usd,
            raw=response.raw,
            image_sha256_in_request="",
        )


def text_only_provider(
    config: VisionConfig, *, transport: Any = None, sleep: Any = None
) -> TextOnlyVisionProvider | None:
    """Build the CTX transport from configuration, or ``None`` without a credential."""
    delegate = OpenAICompatibleVisionProvider(
        api_key=config.api_key(),
        model=config.provider.model,
        base_url=config.provider.base_url,
        timeout_s=config.provider.timeout_s,
        max_attempts=config.provider.max_attempts,
        supports_json_object=config.provider.supports_json_object,
        prices=PriceTable(
            input_usd_per_mtok=config.provider.prices.input_usd_per_mtok,
            output_usd_per_mtok=config.provider.prices.output_usd_per_mtok,
            image_tokens_estimate=config.provider.prices.image_tokens_estimate,
        ),
        **({"transport": transport} if transport is not None else {}),
        **({"sleep": sleep} if sleep is not None else {}),
    )
    return TextOnlyVisionProvider(delegate=delegate)


# ---------------------------------------------------------------------------
# traces
# ---------------------------------------------------------------------------


class TraceWriter:
    """Append-only JSONL for model invocations and bot decisions (RFC 6.2 / 6.4)."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.invocations = self.directory / "MODEL_INVOCATIONS.jsonl"
        self.decisions = self.directory / "BOT_DECISION_TRACE.jsonl"

    def _append(self, path: Path, row: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    def invocation(self, row: dict[str, Any]) -> None:
        self._append(self.invocations, row)

    def decision(self, row: dict[str, Any]) -> None:
        self._append(self.decisions, row)

    def counts(self) -> dict[str, int]:
        def lines(path: Path) -> int:
            if not path.exists():
                return 0
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

        return {"model_invocations": lines(self.invocations), "bot_decisions": lines(self.decisions)}


def invocation_row(
    *,
    invocation_id: str,
    run_id: str,
    bot_id: str,
    request: VisionRequest,
    response: VisionResponse,
    model_status: str,
) -> dict[str, Any]:
    return {
        "invocation_id": invocation_id,
        "run_id": run_id,
        "bot_id": bot_id,
        "provider": response.provider,
        "model_id": response.model,
        "prompt_id": request.prompt.version,
        "prompt_sha256": request.prompt.sha256,
        "input_image_sha256": request.chart.sha256,
        "image_attached": bool(response.image_sha256_in_request),
        "input_context_sha": request.prompt.sha256,
        "decision_time_ms": request.decision_ts_ms,
        "provider_request_id": response.request_id,
        "token_usage": response.usage,
        "provider_cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
        "attempts": response.attempts,
        "model_status": model_status,
        "response_sha256": _sha(response.text),
    }


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cost_of(response: VisionResponse) -> float:
    return float(response.cost_usd or 0.0)


def finite(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if math.isfinite(float(value)) else None


__all__ = [
    "ProviderError",
    "TextOnlyVisionProvider",
    "TraceWriter",
    "VisionProvider",
    "build_structured_prompt",
    "cost_of",
    "invocation_row",
    "mtf_features",
    "resample_closed",
    "text_only_provider",
]
