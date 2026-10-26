"""CAP-004 — the frozen campaign identity, cadence and drift sentinel.

CAP-003 built the instrument.  CAP-004 makes it run without supervision, which
is only meaningful if the thing running cannot quietly stop being the same
experiment.  This module freezes *what the campaign is* and answers the three
questions a long-running run must be able to answer at any moment:

* **Which slot is due?**  ``due_decision_slot`` is derived from CAP-003, not
  invented: CAP-003 sealed its four real decisions at the 2026-10-06 16:00 UTC
  boundary, so the authoritative cadence is one decision per asset per UTC day at
  the **16:00 UTC** slot.  That also puts the 24H horizon on the same grid as the
  next decision, so decisions and settlements land together.
* **Has this slot already been used?**  ``decision_key`` is a deterministic
  identity over ``(campaign, asset, decision_time, horizon, analyst_version)``,
  which is what makes sealing exactly-once across restarts, retries and
  overlapping runners.  The identity is recomputed for the pre-existing CAP-003
  decisions, so the slot they occupy can never be sealed twice.
* **Is this still the same experiment?**  ``detect_drift`` re-derives every
  frozen knob from the live code and compares it with the manifest.  A moved
  prompt digest, feature version, schema version, cost model or rule version
  blocks new decisions instead of silently mixing variants.

The CAP-003 pilot cohort is *adopted, not retro-fitted*: those four decisions
predate ``campaign_id`` / ``code_commit`` in provenance, so they are labelled
``LEGACY_CAP003_PILOT`` rather than rewritten.  Every decision CAP-004 seals must
carry the extended provenance or it is refused.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import agentic_baselines as ab
from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import analyst_provenance as ap
from trading_bot.research import decision_outcomes as do
from trading_bot.research import market_analyst_v1 as mav
from trading_bot.research import real_market_context as rmc

__all__ = [
    "CAMPAIGN_ASSETS",
    "CAMPAIGN_ID",
    "CAMPAIGN_MANIFEST_FILENAME",
    "CAMPAIGN_PROVENANCE_FIELDS",
    "CAMPAIGN_VERSION",
    "COHORT_CAP004",
    "COHORT_LEGACY_CAP003_PILOT",
    "DECISION_SLOT_UTC_HOUR",
    "HORIZON",
    "MANIFEST_VERSION",
    "MODEL_DRIFT",
    "SEAL_WINDOW_SECONDS",
    "build_campaign_provenance",
    "build_manifest",
    "campaign_provenance_missing",
    "cohort_of",
    "decision_key",
    "decision_slot_unix",
    "detect_drift",
    "due_decision_slot",
    "load_manifest",
    "manifest_digest",
    "next_decision_slot",
    "occupied_decision_keys",
    "write_manifest",
]

MANIFEST_VERSION = "CAMPAIGN_MANIFEST_V1"
CAMPAIGN_ID = "CAP004-REAL-DECISIONS-V1"
CAMPAIGN_VERSION = "1.0"
CAMPAIGN_MANIFEST_FILENAME = "CAMPAIGN_MANIFEST.json"

#: The cohort of decisions CAP-004 itself seals.
COHORT_CAP004 = CAMPAIGN_ID
#: The four CAP-003 pilot decisions: adopted by the campaign, never rewritten.
COHORT_LEGACY_CAP003_PILOT = "LEGACY_CAP003_PILOT"

MODEL_DRIFT = "MODEL_DRIFT"

#: Authoritative cadence, taken from the CAP-003 pilot run.
DECISION_SLOT_UTC_HOUR = 16
#: The horizon CAP-003 froze for the campaign.
HORIZON = "24H"
#: A slot's answer may still be sealed inside this window; the delay is recorded.
#: Past it the slot is ``MISSED_DECISION_SLOT`` and is never filled retroactively,
#: because a late seal is a seal made with information the slot never had.
SEAL_WINDOW_SECONDS = 14_400
CAMPAIGN_ASSETS: tuple[str, ...] = rmc.CAMPAIGN_ASSETS

#: Provenance CAP-004 adds on top of the CAP-003 contract.
CAMPAIGN_PROVENANCE_FIELDS: tuple[str, ...] = (
    *ap.PROVENANCE_FIELDS,
    "campaign_id",
    "code_commit",
)

MODEL_POLICY: dict[str, str] = {
    "model": "freebuff-agent-in-context",
    "provider": "freebuff",
    "temperature": ap.NOT_EXPOSED,
    "note": (
        "the analyst is the LLM client; the repository never synthesises its answer, and a "
        "provider that exposes no sampling parameter must record NOT_EXPOSED"
    ),
}

PRIMARY_METRIC: dict[str, Any] = {
    "name": "G_AGENTIC_EDGE",
    "definition": (
        "the CAP-003 alpha scorecard conclusion, i.e. all incremental edges of A versus "
        "B (frozen deterministic rule), C (buy-and-hold) and D (random matched distribution) "
        "strictly positive"
    ),
    "source": "trading_bot.research.alpha_scorecard.alpha_scorecard",
    "positive_conclusion": asc.CONCLUSION_EDGE_POSITIVE_PRELIMINARY,
    "min_evaluable_decisions": asc.MIN_EVALUABLE_DECISIONS,
    "frozen": True,
    "note": "frozen by CAP-003 and never redefined by CAP-004",
}


# --------------------------------------------------------------------------- #
# §1 — the decision slot
# --------------------------------------------------------------------------- #


def decision_slot_unix(day: dt.date) -> int:
    """Unix seconds of 16:00 UTC on ``day`` — the authoritative CAP-003 slot."""
    moment = dt.datetime(day.year, day.month, day.day, DECISION_SLOT_UTC_HOUR, 0, 0, tzinfo=dt.UTC)
    return int(moment.timestamp())


def due_decision_slot(now_seconds: int) -> int:
    """The most recent slot whose 16:00 UTC boundary has already closed."""
    today = dt.datetime.fromtimestamp(now_seconds, dt.UTC).date()
    slot = decision_slot_unix(today)
    if now_seconds >= slot:
        return slot
    return decision_slot_unix(today - dt.timedelta(days=1))


def next_decision_slot(now_seconds: int) -> int:
    """The next slot boundary, whether or not it has been consumed."""
    slot = due_decision_slot(now_seconds)
    return slot + 86_400 if now_seconds >= slot else slot


def decision_key(*, asset: str, decision_time: int, horizon: str, analyst_version: str) -> str:
    """Deterministic slot identity: the same slot can never be sealed twice."""
    return f"{CAMPAIGN_ID}|{asset}|{int(decision_time)}|{horizon}|{analyst_version}"


def occupied_decision_keys(decisions: Sequence[Mapping[str, Any]]) -> set[str]:
    """Slot keys already used, recomputed for the adopted CAP-003 decisions too."""
    return {
        decision_key(
            asset=str(entry["asset"]),
            decision_time=int(entry["decision_time"]),
            horizon=str(entry["horizon"]),
            analyst_version=str(entry.get("prompt_version", "")),
        )
        for entry in decisions
    }


# --------------------------------------------------------------------------- #
# §2 — campaign provenance
# --------------------------------------------------------------------------- #


def campaign_provenance_missing(payload: Mapping[str, Any]) -> list[str]:
    """Fields missing from the *extended* CAP-004 provenance contract."""
    return [
        field
        for field in CAMPAIGN_PROVENANCE_FIELDS
        if payload.get(field) is None or not str(payload.get(field)).strip()
    ]


def build_campaign_provenance(
    *,
    code_commit: str,
    model: str = MODEL_POLICY["model"],
    provider: str = MODEL_POLICY["provider"],
    temperature: str = MODEL_POLICY["temperature"],
    dataset: str = rmc.PROVIDER,
) -> dict[str, str]:
    """The complete CAP-004 provenance record for one sealed decision."""
    return ap.AnalystProvenance(
        analyst_id=mav.PROMPT_VERSION,
        prompt_version=mav.PROMPT_VERSION,
        prompt_digest=mav.prompt_digest(),
        model=model,
        provider=provider,
        temperature=temperature,
        schema_version=ap.SCHEMA_VERSION,
        feature_version=ap.FEATURE_VERSION,
        dataset=dataset,
    ).to_dict() | {"campaign_id": CAMPAIGN_ID, "code_commit": code_commit}


def cohort_of(entry: Mapping[str, Any], *, expected_model: str | None = None) -> str:
    """Which cohort a decision belongs to; a model change splits the cohort."""
    provenance = entry.get("provenance") or {}
    campaign = str(provenance.get("campaign_id", "")).strip()
    base = campaign if campaign else COHORT_LEGACY_CAP003_PILOT
    if campaign and expected_model is not None:
        model = str(provenance.get("model", "")).strip()
        if model and model != expected_model:
            return f"{base}|{MODEL_DRIFT}:{model}"
    return base


# --------------------------------------------------------------------------- #
# §3 — the manifest
# --------------------------------------------------------------------------- #


def baseline_definitions() -> dict[str, Any]:
    """The frozen comparators, copied into the manifest verbatim."""
    return {
        "A": {"id": do.AGENT_ID, "definition": "MARKET_ANALYST_V1.0 decisions"},
        "B": {
            "id": do.BASELINE_ID_DETERMINISTIC,
            "version": do.DETERMINISTIC_RULE_VERSION,
            "definition": "close > SMA(200) and MACD(12,26,9) and 30 <= RSI(14) <= 70",
            "input_bars_4h": do.RULE_INPUT_BARS_4H,
            "input_bars_1d": do.RULE_INPUT_BARS_1D,
            "frozen": True,
        },
        "C": {"id": do.BASELINE_ID_BUY_AND_HOLD, "definition": "always long, same window"},
        "D": {
            "id": do.BASELINE_ID_RANDOM_MATCHED,
            "definition": "exact permutation of the analyst's own direction multiset",
            "seed": asc.RANDOM_BASELINE_SEED,
            "assignment_scope": "DATASET_LEVEL_AT_SCORING_TIME",
        },
    }


def build_manifest(*, created_at: int, code_commit: str) -> dict[str, Any]:
    """The frozen identity CAP-004 must never silently change."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "campaign_id": CAMPAIGN_ID,
        "campaign_version": CAMPAIGN_VERSION,
        "campaign_start": int(created_at),
        "campaign_start_utc": dt.datetime.fromtimestamp(created_at, dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "cadence": {
            "rule": "one decision per asset per UTC day at the decision slot",
            "decision_slot_utc_hour": DECISION_SLOT_UTC_HOUR,
            "slot_grid_seconds": 14_400,
            "seal_window_seconds": SEAL_WINDOW_SECONDS,
            "late_seal_policy": "MISSED_DECISION_SLOT: never filled retroactively",
            "authority": (
                "CAP-003 sealed its four real decisions at the 2026-10-06 16:00 UTC boundary; "
                "that slot is reused rather than replaced"
            ),
            "backfill": "FORBIDDEN",
        },
        "horizon": HORIZON,
        "assets": list(CAMPAIGN_ASSETS),
        "analyst_id": mav.PROMPT_VERSION,
        "analyst_version": mav.PROMPT_VERSION,
        "prompt_version": mav.PROMPT_VERSION,
        "prompt_digest": mav.prompt_digest(),
        "schema_version": ap.SCHEMA_VERSION,
        "feature_version": ap.FEATURE_VERSION,
        "provider": rmc.PROVIDER,
        "source_type": rmc.REAL_SOURCE_TYPE,
        "model_policy": dict(MODEL_POLICY),
        "cost_model": ab.DEFAULT_COST_MODEL.to_dict(),
        "baselines": baseline_definitions(),
        "evaluator": {"id": do.EVALUATOR_ID, "version": do.EVALUATOR_VERSION},
        "score_version": do.EVALUATOR_VERSION,
        "checkpoints": list(asc.CHECKPOINTS),
        "min_evaluable_decisions": asc.MIN_EVALUABLE_DECISIONS,
        "checkpoint_policy": (
            "IDEMPOTENT_APPEND_ONLY: a checkpoint is written once for its population and is "
            "never silently rewritten with a different decision set"
        ),
        "primary_metric": dict(PRIMARY_METRIC),
        "campaign_provenance_fields": list(CAMPAIGN_PROVENANCE_FIELDS),
        "cohorts": {
            COHORT_CAP004: "decisions sealed by CAP-004 with full campaign provenance",
            COHORT_LEGACY_CAP003_PILOT: (
                "the four CAP-003 pilot decisions, adopted as-is because rewriting their "
                "provenance would break ledger immutability"
            ),
        },
        "runtime_promotion": "FORBIDDEN",
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "alpha_claimed": ac.ALPHA_CLAIMED,
        "alpha_research_freeze": ac.ALPHA_RESEARCH_FREEZE,
        "next_alpha_rfc_allowed": ac.NEXT_ALPHA_RFC_ALLOWED,
        "code_commit": code_commit,
        "frozen_at": int(created_at),
    }


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return ac.payload_digest(dict(manifest))


def write_manifest(root: Path, manifest: Mapping[str, Any]) -> Path:
    path = Path(root) / CAMPAIGN_MANIFEST_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(manifest), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_manifest(root: Path) -> dict[str, Any] | None:
    path = Path(root) / CAMPAIGN_MANIFEST_FILENAME
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


# --------------------------------------------------------------------------- #
# §4 — drift detection
# --------------------------------------------------------------------------- #


def _expected_live() -> dict[str, Any]:
    """Every frozen knob, re-derived from the live code (never from the file)."""
    return {
        "campaign_id": CAMPAIGN_ID,
        "campaign_version": CAMPAIGN_VERSION,
        "horizon": HORIZON,
        "assets": list(CAMPAIGN_ASSETS),
        "analyst_version": mav.PROMPT_VERSION,
        "prompt_version": mav.PROMPT_VERSION,
        "prompt_digest": mav.prompt_digest(),
        "schema_version": ap.SCHEMA_VERSION,
        "feature_version": ap.FEATURE_VERSION,
        "provider": rmc.PROVIDER,
        "cost_round_trip_fraction": ab.DEFAULT_COST_MODEL.round_trip_fraction,
        "evaluator_version": do.EVALUATOR_VERSION,
        "rule_version": do.DETERMINISTIC_RULE_VERSION,
        "rule_input_bars_4h": do.RULE_INPUT_BARS_4H,
        "rule_input_bars_1d": do.RULE_INPUT_BARS_1D,
        "random_seed": asc.RANDOM_BASELINE_SEED,
        "checkpoints": list(asc.CHECKPOINTS),
        "min_evaluable_decisions": asc.MIN_EVALUABLE_DECISIONS,
        "decision_slot_utc_hour": DECISION_SLOT_UTC_HOUR,
        "seal_window_seconds": SEAL_WINDOW_SECONDS,
    }


#: Frozen knob -> (manifest section, key inside that section).
_NESTED_KNOBS: dict[str, tuple[str, str]] = {
    "cost_round_trip_fraction": ("cost_model", "round_trip_fraction"),
    "evaluator_version": ("evaluator", "version"),
    "rule_version": ("baselines", "B.version"),
    "rule_input_bars_4h": ("baselines", "B.input_bars_4h"),
    "rule_input_bars_1d": ("baselines", "B.input_bars_1d"),
    "random_seed": ("baselines", "D.seed"),
    "decision_slot_utc_hour": ("cadence", "decision_slot_utc_hour"),
    "seal_window_seconds": ("cadence", "seal_window_seconds"),
}


def _manifest_knob(manifest: Mapping[str, Any], key: str) -> Any:
    nested = _NESTED_KNOBS.get(key)
    if nested is None:
        return manifest.get(key)
    section, path = nested
    node: Any = manifest.get(section)
    for part in path.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def detect_drift(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Compare every re-derived knob with the frozen manifest.

    ``PROMPT_DRIFT`` / ``FEATURE_DRIFT`` / ``CAMPAIGN_CONFIGURATION_DRIFT`` all
    block new decisions; nothing here updates the manifest automatically.
    """
    live = _expected_live()
    checks: list[dict[str, Any]] = []
    for key, expected in live.items():
        recorded = _manifest_knob(manifest, key)
        matched = recorded == expected
        checks.append({"knob": key, "recorded": recorded, "live": expected, "match": matched})
    drifted = [item["knob"] for item in checks if not item["match"]]

    label = None
    if "prompt_digest" in drifted or "prompt_version" in drifted:
        label = "PROMPT_DRIFT"
    elif "schema_version" in drifted or "feature_version" in drifted:
        label = "FEATURE_DRIFT"
    elif drifted:
        label = "CAMPAIGN_CONFIGURATION_DRIFT"

    return {
        "status": "NO_DRIFT" if not drifted else label,
        "drifted": drifted,
        "checks": checks,
        "live": live,
        "manifest_digest": manifest_digest(manifest),
    }


def detect_model_drift(
    manifest: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Decisions whose recorded model is not the manifest's model policy."""
    policy = manifest.get("model_policy") or {}
    expected_model = str(policy.get("model", ""))
    expected_provider = str(policy.get("provider", ""))
    drifted: list[dict[str, Any]] = []
    for entry in decisions:
        provenance = entry.get("provenance") or {}
        model = str(provenance.get("model", "")).strip()
        provider = str(provenance.get("provider", "")).strip()
        if model and (model != expected_model or provider != expected_provider):
            drifted.append(
                {
                    "decision_id": entry.get("decision_id"),
                    "model": model,
                    "provider": provider,
                    "expected_model": expected_model,
                    "expected_provider": expected_provider,
                }
            )
    return {
        "status": MODEL_DRIFT if drifted else "NO_DRIFT",
        "drifted": drifted,
        "expected_model": expected_model,
        "expected_provider": expected_provider,
    }
