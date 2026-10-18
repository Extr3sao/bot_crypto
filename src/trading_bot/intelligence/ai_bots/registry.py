"""registry — who exists, what they may do, and what they may never do.

Every bot is off until someone turns it on, and the switch is a file, not a prompt. The
registry is the only place where a bot's *capabilities* are declared, so an audit can
answer "could this bot have touched the exchange?" by reading one artefact instead of
grepping every module.

Design choices worth naming:

* **Disabled by default.** ``AI_BOTS_ENABLED=false`` and per-bot ``enabled=false``; the
  RFC's rollback is a flag flip, and a flag that defaults to on is not a rollback.
* **Forbidden capabilities are structural.** A registration that asks for
  ``place_order``, ``modify_risk`` or ``read_secrets`` is refused at construction, so the
  mistake surfaces in a test run rather than in production.
* **Duplicate ids are refused.** Two bots sharing an id would share traces, budgets and
  blame.
* **The registry never grants execution.** ``allowed_tools`` only ever names analysis
  tools; the order path is not a capability a bot can hold.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Capabilities no bot may ever hold. Refused at registration time.
FORBIDDEN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "place_order",
        "cancel_order",
        "modify_order",
        "modify_risk",
        "set_leverage",
        "read_secrets",
        "write_filesystem",
        "execute_shell",
        "call_exchange",
        "withdraw",
    }
)

ALLOWED_CAPABILITIES: frozenset[str] = frozenset(
    {"read_ohlcv", "read_positions", "render_chart", "invoke_llm", "read_calendar"}
)

#: State vocabulary, taken from the roadmap. A lower state never implies a higher one.
BOT_STATES = (
    "NOT_STARTED",
    "DESIGN_ONLY",
    "IMPLEMENTED",
    "UNIT_TESTED",
    "REAL_MODEL_CALLED",
    "PAPER_RUNTIME_EXECUTED",
    "INDEPENDENT_VERIFIED",
    "BLOCKED",
)


@dataclass(frozen=True, slots=True)
class BotSpec:
    bot_id: str
    bot_version: str
    family: str
    enabled: bool
    model_provider: str
    model_id: str
    input_contract: str
    output_contract: str
    allowed_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    max_calls_per_day: int
    max_latency_ms: int
    cost_budget_usd: float
    paper_namespace: str
    reliability_status: str = "IMPLEMENTED"
    notes: str = ""

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["allowed_tools"] = list(self.allowed_tools)
        row["forbidden_actions"] = list(self.forbidden_actions)
        return row


class RegistryError(ValueError):
    """A registration that would grant a bot more than an opinion."""


@dataclass
class BotCapabilityRegistry:
    """In-memory registry with an explicit switch and a JSON projection."""

    enabled: bool = False
    specs: dict[str, BotSpec] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BotCapabilityRegistry:
        source = os.environ if env is None else env
        flag = str(source.get("AI_BOTS_ENABLED", "false")).strip().lower()
        return cls(enabled=flag in {"1", "true", "yes", "on"})

    def register(self, spec: BotSpec) -> BotSpec:
        if spec.bot_id in self.specs:
            raise RegistryError(f"duplicate bot_id {spec.bot_id!r}")
        granted = set(spec.allowed_tools)
        illegal = sorted(granted & FORBIDDEN_CAPABILITIES)
        if illegal:
            raise RegistryError(
                f"{spec.bot_id} asks for capabilities a bot may never hold: {', '.join(illegal)}"
            )
        unknown = sorted(granted - ALLOWED_CAPABILITIES)
        if unknown:
            raise RegistryError(
                f"{spec.bot_id} asks for unknown capabilities: {', '.join(unknown)}; "
                "add them to ALLOWED_CAPABILITIES deliberately if they are analysis-only"
            )
        if set(spec.forbidden_actions) & granted:
            raise RegistryError(
                f"{spec.bot_id} forbids and grants the same action: "
                f"{sorted(set(spec.forbidden_actions) & granted)}"
            )
        if spec.reliability_status not in BOT_STATES:
            raise RegistryError(
                f"{spec.bot_id} has unknown reliability_status {spec.reliability_status!r}"
            )
        self.specs[spec.bot_id] = spec
        return spec

    def active(self) -> list[BotSpec]:
        """Bots that may actually run: the global flag *and* the bot's own flag."""
        if not self.enabled:
            return []
        return [spec for spec in self.specs.values() if spec.enabled]

    def get(self, bot_id: str) -> BotSpec:
        if bot_id not in self.specs:
            raise KeyError(f"unknown bot {bot_id!r}")
        return self.specs[bot_id]

    def set_state(self, bot_id: str, state: str) -> BotSpec:
        if state not in BOT_STATES:
            raise RegistryError(f"unknown state {state!r}")
        spec = self.get(bot_id)
        updated = BotSpec(**{**spec.as_row(), "reliability_status": state,
                             "allowed_tools": tuple(spec.allowed_tools),
                             "forbidden_actions": tuple(spec.forbidden_actions)})
        self.specs[bot_id] = updated
        return updated

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": "AIBOT_CAPABILITY_REGISTRY_V1",
            "enabled_globally": self.enabled,
            "bot_count": len(self.specs),
            "bots": [spec.as_row() for spec in self.specs.values()],
            "states_vocabulary": list(BOT_STATES),
            "note": (
                "AI_BOTS_ENABLED must be true AND the bot's own enabled flag must be true; "
                "no bot holds an execution capability by construction"
            ),
        }

    def write(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return target


def default_registry(env: Mapping[str, str] | None = None) -> BotCapabilityRegistry:
    """The two discretionary bots of this package, both disabled by default."""
    registry = BotCapabilityRegistry.from_env(env)
    source = os.environ if env is None else env
    # Enabling a bot is always an explicit, per-bot act: the global switch alone is not
    # enough, because a forgotten bot must not start spending tokens after a restart.
    allowed = {
        item.strip()
        for item in str(source.get("AI_BOTS_ALLOW", "")).split(",")
        if item.strip()
    }
    provider_model = source.get("VISION_MODEL", "gpt-4o-mini")
    registry.register(
        BotSpec(
            bot_id="BOT-VIS-01",
            bot_version="1.2.0",
            family="VISUAL_DISCRETIONARY",
            enabled="BOT-VIS-01" in allowed,
            model_provider="openai-compatible",
            model_id=provider_model,
            input_contract="ChartSnapshotBundle(png, sha256) + MarketContext",
            output_contract="AITradeOpinion(AIBOT_OPINION_V1)",
            allowed_tools=("read_ohlcv", "render_chart", "invoke_llm", "read_positions"),
            forbidden_actions=tuple(sorted(FORBIDDEN_CAPABILITIES)),
            max_calls_per_day=96,
            max_latency_ms=60_000,
            cost_budget_usd=2.0,
            paper_namespace="AI_BOTS_EXPERIMENTAL",
            reliability_status="UNIT_TESTED",
            notes="vision lane in src/trading_bot/vision; paper only",
        )
    )
    registry.register(
        BotSpec(
            bot_id="BOT-CTX-01",
            bot_version="1.0.0",
            family="STRUCTURED_DISCRETIONARY",
            enabled="BOT-CTX-01" in allowed,
            model_provider="openai-compatible",
            model_id=provider_model,
            input_contract="FeatureSnapshot(MTF numeric) — no image",
            output_contract="AITradeOpinion(AIBOT_OPINION_V1)",
            allowed_tools=("read_ohlcv", "invoke_llm", "read_positions"),
            forbidden_actions=tuple(sorted(FORBIDDEN_CAPABILITIES)),
            max_calls_per_day=96,
            max_latency_ms=60_000,
            cost_budget_usd=2.0,
            paper_namespace="AI_BOTS_EXPERIMENTAL",
            reliability_status="UNIT_TESTED",
            notes="scientific control for BOT-VIS-01: same book, no pixels",
        )
    )
    # BOT-CRI-01 reviews a frozen proposal; it holds no book and no execution tool.
    # SHADOW_ONLY is the only mode it may enter without the AI-BOTS-003C gate.
    registry.register(
        BotSpec(
            bot_id="BOT-CRI-01",
            bot_version="1.0.0",
            family="EPISTEMIC_CRITIC",
            enabled="BOT-CRI-01" in allowed,
            model_provider="openai-compatible",
            model_id=provider_model,
            input_contract="FrozenTradeProposal + EvidenceLedger (authenticated refs)",
            output_contract="CriticReview(TAP_CRITIC_REVIEW_V1) ACCEPT|CHALLENGE|ABSTAIN",
            allowed_tools=("read_ohlcv", "invoke_llm"),
            forbidden_actions=tuple(sorted(FORBIDDEN_CAPABILITIES)),
            max_calls_per_day=48,
            max_latency_ms=8_000,
            cost_budget_usd=0.5,
            paper_namespace="AI_CRITIC_SHADOW",
            reliability_status="IMPLEMENTED",
            notes=(
                "default OFF; SHADOW_ONLY observes and cannot alter fills/PNL/risk; "
                "GATED_PAPER blocked until AI-BOTS-003C validation"
            ),
        )
    )
    return registry


def specs_by_id(specs: Sequence[BotSpec]) -> dict[str, BotSpec]:
    return {spec.bot_id: spec for spec in specs}
