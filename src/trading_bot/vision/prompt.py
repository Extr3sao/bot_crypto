"""prompt — the versioned text half of the model's input.

The image carries the market. This module carries everything the image cannot show and
that a discretionary trader would know at the moment of the decision: which symbol, how
much capital is behind the decision, whether a position is already open, and what the
risk policy will allow.

Two rules keep the comparison against the deterministic lane defensible:

* **No strategy is described.** Nothing here says "buy the EMA cross". If the prompt
  contained the rules, the model would be a slow implementation of the deterministic
  system and the experiment would measure nothing.
* **No size, no leverage, no limits.** The model may say LONG, SHORT, CLOSE or
  NO_TRADE and where it is wrong. Size and stops are applied afterwards by the same
  ``RiskManager`` the deterministic lane uses, so both lanes trade under one policy.

The hash of this text plus the chart hash is what the ledger stores; a prompt edit is
therefore visible as a new hash rather than as an unexplained change of behaviour.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "ai-vision-prompt/2"


@dataclass(frozen=True, slots=True)
class PromptBundle:
    system: str
    user: str
    version: str = PROMPT_VERSION

    @property
    def sha256(self) -> str:
        payload = json.dumps(
            {"version": self.version, "system": self.system, "user": self.user},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


SYSTEM_PROMPT = """You are a discretionary crypto futures trader looking at a chart.

You receive one candlestick chart image and a short market context. You decide what you
would do now, as a trader, using only what you can see and what you are told.

Rules:
- Answer with ONE JSON object and no other text.
- action is exactly one of: "LONG", "SHORT", "CLOSE", "NO_TRADE".
- You do not choose position size, leverage or how much money to risk. A separate risk
  policy sizes every order and sets the protective stops. Do not mention size.
- For LONG or SHORT you must give stop_loss_pct: where the idea is wrong, as a percent
  of entry price. A directional call without a stop is invalid.
- NO_TRADE is a real answer and it is often the best one. Use it when the chart does
  not give you an edge, when the structure is unclear, or when the reward does not pay
  for the risk. Do not force a trade to be helpful.
- confidence is your honest conviction, 0 to 1, not a marketing number.
- Say what you actually see in the image: the level that matters, the shape of the
  recent bars, where the trend fails. Do not describe indicators you cannot see.

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
  "rationale": "<what you see and why this action, at most 600 characters>"
}"""


def build_prompt(context: dict[str, Any]) -> PromptBundle:
    """Render the user message for one decision point.

    ``context`` is produced by the lane and is also written to the ledger verbatim, so
    the prompt can be rebuilt from evidence instead of being retyped here.
    """
    required = ("symbol", "timeframe", "window_bars", "last_close")
    missing = [key for key in required if key not in context]
    if missing:
        raise ValueError(f"prompt context is missing {missing}")

    lines: list[str] = [
        f"Symbol: {context['symbol']}",
        f"Timeframe: {context['timeframe']}",
        f"Chart covers the last {context['window_bars']} closed bars.",
        f"Last close: {context['last_close']:.2f}",
    ]
    if context.get("atr_pct") is not None:
        lines.append(
            f"Average true range over the window: {context['atr_pct']:.2f}% of price "
            "(mechanical context, not a signal)"
        )
    if context.get("return_20_bars_pct") is not None:
        lines.append(f"Price change over the last 20 bars: {context['return_20_bars_pct']:+.2f}%")

    lines.append("")
    position = context.get("position")
    if position:
        lines.append(
            "Open position: {side} {symbol} entered at {entry:.2f}, currently {upnl:+.2f} USDT "
            "unrealised ({upnl_pct:+.2f}%).".format(
                side=str(position["side"]).upper(),
                symbol=context["symbol"],
                entry=float(position["entry_price"]),
                upnl=float(position.get("unrealised_usdt", 0.0)),
                upnl_pct=float(position.get("unrealised_pct", 0.0)),
            )
        )
        lines.append("If you want to exit it, answer CLOSE. Do not answer the opposite side.")
    else:
        lines.append("Open position: none in this symbol.")

    lines.append("")
    lines.append(
        "Account: equity {equity:.2f} USDT, {open_positions} of {max_positions} position "
        "slots in use, risk policy allows {risk_per_trade:.2f}% of equity per trade "
        "and {max_weekly:.2f}% weekly loss.".format(
            equity=float(context.get("equity", 0.0)),
            open_positions=int(context.get("open_positions", 0)),
            max_positions=int(context.get("max_open_positions", 0)),
            risk_per_trade=float(context.get("risk_per_trade_pct", 0.0)),
            max_weekly=float(context.get("max_weekly_loss_pct", 0.0)),
        )
    )
    if context.get("recent_closed"):
        recent = context["recent_closed"][-3:]
        summary = "; ".join(
            f"{row['symbol']} {str(row['side']).upper()} {float(row['pnl_usdt']):+.2f}"
            for row in recent
        )
        lines.append(f"Your last closed trades: {summary}")

    lines.append("")
    lines.append("Decide now for the bar that just closed. Answer with the JSON object only.")
    return PromptBundle(system=SYSTEM_PROMPT, user="\n".join(lines))
