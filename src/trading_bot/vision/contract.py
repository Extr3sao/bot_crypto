"""contract — the decision the model is allowed to make, and nothing more.

The failure mode this module exists to prevent is a language model that answers with
prose, or with JSON that *looks* like a decision. A parser that is generous with
"probably meant LONG" turns a bad generation into a real position, and the loss then
looks like a strategy result instead of a parsing accident.

So the rules are:

* one JSON object, one schema, ``extra="forbid"`` — an invented field is an error,
  not something to ignore;
* ``NaN``/``Infinity`` are rejected at the JSON level, because ``float('nan')``
  compares false against every risk limit and would slip through ``<=`` checks;
* a directional action without a stop is refused: "LONG but I did not say where I am
  wrong" is not a tradeable instruction;
* the symbol must be the symbol in the image; a mismatch means the model answered a
  different question than the one asked.

The parser never invents a default. Every rejection carries a machine-readable code so
the ledger can be counted by cause instead of by anecdote.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION: Final[Literal["ai-vision-decision/1"]] = "ai-vision-decision/1"

Action = Literal["LONG", "SHORT", "CLOSE", "NO_TRADE"]
DIRECTIONAL: tuple[str, ...] = ("LONG", "SHORT")

#: Hard ceiling on the prose, so a rambling answer cannot become a 100 kB ledger line.
MAX_RATIONALE = 600


class DecisionParseError(ValueError):
    """A model answer that cannot be turned into a decision.

    ``code`` is stable and countable (``NO_JSON``, ``INVALID_JSON``,
    ``SCHEMA_VIOLATION``, ``SYMBOL_MISMATCH``); ``detail`` is for humans.
    """

    def __init__(self, code: str, detail: str, *, raw: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.raw = raw


class VisionDecision(BaseModel):
    """One discretionary decision about one symbol.

    The model may only pick an action, a conviction, a horizon, a stop level and say
    why. It cannot choose size, leverage or which symbol: size comes from the runtime
    ``RiskManager``, which is what keeps the comparison against the deterministic lane
    honest and keeps the LLM from editing the risk policy through the prompt.
    """

    model_config = ConfigDict(extra="forbid", strict=False, frozen=True)

    schema_version: Literal["ai-vision-decision/1"] = SCHEMA_VERSION
    symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    horizon_bars: int = Field(ge=1, le=168)
    stop_loss_pct: float | None = Field(default=None, gt=0.0, le=25.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    invalidation: str | None = Field(default=None, max_length=240)
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE)

    @field_validator("symbol", mode="before")
    @classmethod
    def _symbol_shape(cls, value: Any) -> Any:
        text = str(value or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{1,15}/[A-Z0-9]{1,15}", text):
            raise ValueError(f"symbol must look like BTC/USDT, got {value!r}")
        return text

    @field_validator("action", mode="before")
    @classmethod
    def _action_shape(cls, value: Any) -> Any:
        # Before, not after: the Literal check would otherwise reject "long" before any
        # normalisation could run, and a lowercase answer is a formatting choice, not a
        # different instruction.
        return str(value or "").strip().upper()

    def model_post_init(self, __context: Any) -> None:
        if self.action in DIRECTIONAL and self.stop_loss_pct is None:
            raise ValueError(f"{self.action} requires stop_loss_pct")

    @property
    def directional(self) -> bool:
        return self.action in DIRECTIONAL


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _reject_constants(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant {value!r} is not allowed")


def _candidate_objects(text: str) -> list[str]:
    """Every JSON object the answer could plausibly be, best first.

    The model is told to answer with a bare object. Models wrap it anyway: in a fence,
    behind a sentence, or inside an array of one. Each candidate is tried in order, and
    the *first* that parses as an object wins — but an answer with no object at all is
    an error, never an empty decision.
    """
    stripped = text.strip()
    out: list[str] = []
    if stripped.startswith("{"):
        out.append(stripped)
    out.extend(match.group(1) for match in _FENCE.finditer(text))

    # last resort: the first balanced brace block, so a leading "Here is my read:"
    # does not hide a perfectly valid object
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : index + 1])
                    break
        start = text.find("{", start + 1)
    # de-duplicate while keeping order
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def parse_decision(raw: str, *, symbol: str) -> VisionDecision:
    """Turn a model answer into a validated decision, or raise ``DecisionParseError``.

    ``symbol`` is the symbol the chart was rendered for; a decision about another
    symbol is a rejection, not a reinterpretation.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise DecisionParseError("EMPTY_RESPONSE", "the provider returned no text", raw=raw or "")

    candidates = _candidate_objects(raw)
    if not candidates:
        raise DecisionParseError("NO_JSON", "no JSON object in the answer", raw=raw)

    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            loaded = json.loads(candidate, parse_constant=_reject_constants)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            continue
        if isinstance(loaded, dict):
            payload = loaded
            break
        last_error = ValueError(f"candidate is {type(loaded).__name__}, not an object")
    if payload is None:
        raise DecisionParseError(
            "INVALID_JSON", f"no candidate parsed as an object: {last_error}", raw=raw
        )

    try:
        decision = VisionDecision.model_validate(payload)
    except ValidationError as exc:
        fields = ", ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise DecisionParseError("SCHEMA_VIOLATION", fields, raw=raw) from exc
    except ValueError as exc:  # model_post_init (missing stop on a directional call)
        raise DecisionParseError("SCHEMA_VIOLATION", str(exc), raw=raw) from exc

    expected = symbol.strip().upper()
    if decision.symbol != expected:
        raise DecisionParseError(
            "SYMBOL_MISMATCH",
            f"decision is about {decision.symbol} but the chart is {expected}",
            raw=raw,
        )
    return decision


# ---------------------------------------------------------------------------
# coherence against the book
# ---------------------------------------------------------------------------

Intent = Literal["OPEN_LONG", "OPEN_SHORT", "CLOSE", "NONE"]


@dataclass(frozen=True, slots=True)
class ResolvedIntent:
    """What the book will actually attempt, and why anything was dropped."""

    intent: Intent
    reason: str
    decision: VisionDecision

    @property
    def actionable(self) -> bool:
        return self.intent != "NONE"


def resolve_intent(
    decision: VisionDecision, *, position_side: str | None = None
) -> ResolvedIntent:
    """Map a decision onto the book without inventing behaviour.

    Policy, applied identically to every decision (and asserted by tests):

    * ``NO_TRADE`` does nothing, with or without a position;
    * a directional call with the symbol flat opens that side;
    * a directional call *with* an open position is not pyramided and not reversed —
      it is dropped as ``ALREADY_<SIDE>`` / ``OPPOSITE_<SIDE>``. Reversing through the
      model in one step would mean the book pays two spreads for one opinion, and the
      model never sees the fill it caused;
    * ``CLOSE`` closes, and with nothing open is a no-op rather than an error.
    """
    side = (position_side or "").lower() or None
    if decision.action == "NO_TRADE":
        return ResolvedIntent("NONE", "MODEL_NO_TRADE", decision)
    if decision.action == "CLOSE":
        if side is None:
            return ResolvedIntent("NONE", "NO_POSITION_TO_CLOSE", decision)
        return ResolvedIntent("CLOSE", "MODEL_CLOSE", decision)
    if decision.action == "LONG":
        if side == "buy":
            return ResolvedIntent("NONE", "ALREADY_LONG", decision)
        if side == "sell":
            return ResolvedIntent("NONE", "OPPOSITE_SHORT_OPEN", decision)
        return ResolvedIntent("OPEN_LONG", "MODEL_LONG", decision)
    if decision.action == "SHORT":
        if side == "sell":
            return ResolvedIntent("NONE", "ALREADY_SHORT", decision)
        if side == "buy":
            return ResolvedIntent("NONE", "OPPOSITE_LONG_OPEN", decision)
        return ResolvedIntent("OPEN_SHORT", "MODEL_SHORT", decision)
    raise DecisionParseError("UNKNOWN_ACTION", f"unhandled action {decision.action!r}")
