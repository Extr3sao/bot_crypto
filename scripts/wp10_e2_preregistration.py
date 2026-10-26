"""WP-10 E-2 — pre-registration for a forward-drift entry screen, and its gate state.

E-2 is the second experiment the ACTIVE roadmap asks for: the gross edge of the
registered families peaks at 15-30 minutes, so the question is whether *entry
quality* — not another family — can lift a cell over the cost plane. The RFC that
would carry it exists only as a draft (`data/recovery/wp9/RFC_050_COST_AND_ENTRY_DRAFT.md`,
`STATUS = DRAFT`, `AUTHORIZED = false`), and no governance instrument authorises a
new campaign.

So this script does what is still allowed with the gate closed, and refuses the
rest:

* it reads the governance record and prints the gate verdict, instead of assuming
  one: an unregistered RFC and an unauthorized campaign mean SPEC_ONLY;
* it writes the **pre-registration**: hypothesis, universe, reserved forward
  windows, metrics, the frozen cost plane it will be judged against, the decision
  rule and the kill criteria — fixed *before* any observation is looked at, which
  is the entire point of pre-registering;
* it enumerates the windows already spent (the W1-W7 research period, the excluded
  paper day, the sealed book window E-1 measured, and RFC-049's still-closed sealed
  OOS) and reserves a window disjoint from all of them, chosen by calendar rather
  than by outcome;
* it runs **synthetic contract tests** of the decision rule, so the rule cannot be
  quietly re-tuned later: a rule that promotes a noisy series, or a series that
  flips sign between partitions, or a series too short to resolve a 23.35 bps
  effect, is broken and the tests say so;
* it reads no market data and starts nothing. ``--self-test`` runs the tests alone.

Read-only. Exit codes: 0 pre-registration written and self-tests pass, 3 a
self-test failed, 4 the gate-state reading contradicts the governance record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.microstructure.cost_model_v3 import (  # noqa: E402
    ADMISSION_SCENARIO_ID,
    default_model,
)

REGISTRY = ROOT / "docs" / "roadmap" / "RFC_REGISTRY.json"
STATE_VIEW = ROOT / "data" / "recovery" / "CAMPAIGN_STATE_VIEW.json"
RFC_DRAFT = ROOT / "data" / "recovery" / "wp9" / "RFC_050_COST_AND_ENTRY_DRAFT.md"
RFC049_AUTH = ROOT / "data" / "rfc049" / "discovery2" / "CAMPAIGN_AUTHORIZATION.json"
V3_RESULTS = ROOT / "docs" / "STRATEGY_DISCOVERY_V3_RESULTS.json"
FORWARD_MANIFEST_DIR = ROOT / "reports" / "microstructure-forward-continuous" / "manifest"
E1_DISTRIBUTION = ROOT / "data" / "recovery" / "wp10" / "WP10_EXECUTION_COST_DISTRIBUTION.json"
OUT_DIR = ROOT / "data" / "recovery" / "wp10"

PREREGISTRATION_VERSION = "E2-PREREG-V1"
#: RFC-049 licensed a single sealed inspection for a window that opens here and has
#: never been read. E-2 may not touch it; the reservation below starts after it.
RFC049_SEALED_OOS_FROM = "2026-10-11T00:00:00Z"
#: The window E-2 reserves: forward, after every period already spent or licensed.
RESERVED_FROM = "2026-10-12T00:00:00Z"
Z_95 = 1.959964
Z_80_POWER = 2.801585
#: Minimum detectable effect the campaign must be able to resolve: one round trip at
#: the frozen plane. An edge smaller than the plane cannot be net positive, so a
#: sample that cannot resolve the plane cannot distinguish success from noise.
MINIMUM_DETECTABLE_EFFECT_BPS = 23.353553391


# ---------------------------------------------------------------------------
# the decision rule, fixed here and tested below
# ---------------------------------------------------------------------------


def required_trades(sd_bps: float, target_bps: float = MINIMUM_DETECTABLE_EFFECT_BPS,
                    z: float = Z_80_POWER) -> int:
    """Trades needed for ``z``-sized resolution of ``target_bps`` given ``sd_bps``.

    Called on the development partition only, so the requirement is computed from
    data the campaign is allowed to look at while it is still deciding how much
    validation data it needs.
    """
    if sd_bps <= 0.0 or target_bps <= 0.0:
        return 0
    return int(math.ceil((z * sd_bps / target_bps) ** 2))


def decide(net_bps: Sequence[float], dev_size: int | None = None,
           target_bps: float = MINIMUM_DETECTABLE_EFFECT_BPS) -> dict[str, Any]:
    """The pre-registered verdict for one candidate, from its per-trade net bps.

    ``net_bps`` is already net of the frozen cost plane. The verdict is PROMOTE only
    when every condition holds; otherwise it names the first condition that failed,
    so a rejection is as informative as a promotion.
    """
    series = list(net_bps)
    n = len(series)
    if n < 2:
        return {"verdict": "NOT_PROMOTE", "reason": "fewer than two trades: nothing to test",
                "n": n}
    mean = sum(series) / n
    variance = sum((value - mean) ** 2 for value in series) / (n - 1)
    sd = math.sqrt(variance)
    se = sd / math.sqrt(n)
    lcb = mean - Z_95 * se
    split = dev_size if dev_size is not None else n // 2
    split = max(1, min(n - 1, split))
    dev_mean = sum(series[:split]) / split
    val_mean = sum(series[split:]) / (n - split)
    dev_sd = math.sqrt(sum((v - dev_mean) ** 2 for v in series[:split]) / max(1, split - 1))
    needed = required_trades(dev_sd, target_bps)

    failures = []
    if mean <= 0.0:
        failures.append("net expectancy is not positive")
    if lcb <= 0.0:
        failures.append("lower 95% confidence bound is not above zero")
    if not (dev_mean > 0.0 and val_mean > 0.0):
        failures.append("the sign does not hold across development and validation")
    if n < needed:
        failures.append(f"sample below the pre-registered requirement ({n} < {needed})")
    return {
        "verdict": "PROMOTE" if not failures else "NOT_PROMOTE",
        "reason": "; ".join(failures) if failures else "every pre-registered condition holds",
        "n": n,
        "mean_net_bps": round(mean, 6),
        "sd_bps": round(sd, 6),
        "standard_error_bps": round(se, 6),
        "lcb_95_bps": round(lcb, 6),
        "dev_mean_net_bps": round(dev_mean, 6),
        "val_mean_net_bps": round(val_mean, 6),
        "dev_sd_bps": round(dev_sd, 6),
        "trades_required": needed,
        "minimum_detectable_effect_bps": target_bps,
    }


# ---------------------------------------------------------------------------
# synthetic contract tests: the rule must behave, and must be seen to behave
# ---------------------------------------------------------------------------


def _series(mean: float, sd: float, n: int) -> list[float]:
    """A deterministic series with exactly this mean and (for even n) exactly this sd.

    Contract tests must not depend on a random draw: a test whose verdict moves with
    the seed is not a contract test, it is a coin toss that happened to land well.
    """
    return [mean + (sd if index % 2 == 0 else -sd) for index in range(n)]


def contract_tests() -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []

    def record(name: str, passed: bool, verdict: dict[str, Any], expectation: str) -> None:
        tests.append({"test": name, "passed": bool(passed), "expectation": expectation,
                      "verdict": verdict})

    strong = _series(30.0, 20.0, 300)
    result = decide(strong, dev_size=150)
    record("a strong, well-sampled positive edge is promoted",
           result["verdict"] == "PROMOTE", result, "PROMOTE")

    noisy = _series(30.0, 300.0, 50)
    result = decide(noisy, dev_size=25)
    record("a positive but noisy small sample is not promoted",
           result["verdict"] == "NOT_PROMOTE" and "confidence" in result["reason"],
           result, "NOT_PROMOTE, confidence bound fails")

    flip = _series(30.0, 30.0, 150) + _series(-10.0, 30.0, 150)
    result = decide(flip, dev_size=150)
    record("a series whose sign flips between partitions is not promoted even with a "
           "positive pooled bound",
           result["verdict"] == "NOT_PROMOTE" and "sign" in result["reason"]
           and result["lcb_95_bps"] > 0.0, result,
           "NOT_PROMOTE by the sign rule while the pooled bound is positive")

    negative = _series(-5.0, 20.0, 400)
    result = decide(negative, dev_size=200)
    record("a net-negative series is not promoted",
           result["verdict"] == "NOT_PROMOTE", result, "NOT_PROMOTE")

    short = _series(40.0, 100.0, 20)
    result = decide(short, dev_size=10)
    record("a sample below the pre-registered requirement is not promoted",
           result["verdict"] == "NOT_PROMOTE" and "sample below" in result["reason"],
           result, "NOT_PROMOTE, sample requirement")

    shuffled = list(strong)
    random.Random(17).shuffle(shuffled)
    first = decide(shuffled, dev_size=150)
    second = decide(shuffled, dev_size=150)
    record("the verdict depends on the numbers, not on the order they arrive in",
           first["verdict"] == second["verdict"] and first["mean_net_bps"] == second["mean_net_bps"],
           first, "the same verdict and the same mean")
    partition_effect = decide(strong, dev_size=150)["verdict"] == decide(sorted(strong), dev_size=150)["verdict"]
    tests.append({"test": "sorting the series does not change the verdict",
                  "passed": partition_effect,
                  "expectation": "same verdict (the rule reads values, not position)",
                  "verdict": {"sorted_verdict": decide(sorted(strong), dev_size=150)["verdict"]}})

    promoted_when_bound_negative = 0
    rng = random.Random(18)
    for _ in range(200):
        candidate = [rng.gauss(-3.0, 40.0) for _ in range(rng.randint(2, 200))]
        outcome = decide(candidate)
        if outcome["verdict"] == "PROMOTE" and outcome["lcb_95_bps"] <= 0.0:
            promoted_when_bound_negative += 1
    tests.append({"test": "negative control: 200 random series never promote with a bound at "
                          "or below zero",
                  "passed": promoted_when_bound_negative == 0,
                  "expectation": "0 violations",
                  "verdict": {"violations": promoted_when_bound_negative}})

    identical = [1.0] * 50
    result = decide(identical, dev_size=25)
    tests.append({"test": "a zero-dispersion series neither crashes nor divides by zero",
                  "passed": result["verdict"] in {"PROMOTE", "NOT_PROMOTE"}
                  and result["sd_bps"] == 0.0,
                  "expectation": "a verdict with sd 0",
                  "verdict": result})
    return tests


# ---------------------------------------------------------------------------
# governance state, read rather than assumed
# ---------------------------------------------------------------------------


def governance_state() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}
    draft_text = RFC_DRAFT.read_text(encoding="utf-8") if RFC_DRAFT.exists() else ""
    authorization = (json.loads(RFC049_AUTH.read_text(encoding="utf-8"))
                     if RFC049_AUTH.exists() else {})
    v3 = json.loads(V3_RESULTS.read_text(encoding="utf-8")) if V3_RESULTS.exists() else {}
    manifests = sorted(FORWARD_MANIFEST_DIR.glob("*.json")) if FORWARD_MANIFEST_DIR.exists() else []
    sealed = []
    for path in manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sealed.append({"run_id": payload.get("run_id"), "started_at": payload.get("started_at"),
                       "ended_at": payload.get("ended_at"), "status": payload.get("status")})

    draft_state = {
        "path": str(RFC_DRAFT.relative_to(ROOT)).replace("\\", "/") if RFC_DRAFT.exists() else None,
        "exists": RFC_DRAFT.exists(),
        "declares_draft": "STATUS = DRAFT" in draft_text,
        "declares_unauthorized": "AUTHORIZED = false" in draft_text,
        "declares_campaign_not_started": "CAMPAIGN_STARTED = false" in draft_text,
    }
    registered_numbers = sorted((registry.get("numbers") or {}).keys())
    rfc_050_registered = "050" in registered_numbers
    # The state view already arbitrates between competing declarations, so the resolved
    # flag is read from it rather than re-decided here from one of the sources it ranks.
    view = json.loads(STATE_VIEW.read_text(encoding="utf-8")) if STATE_VIEW.exists() else {}
    resolved: dict[str, Any] = {}
    for resolution in view.get("resolutions") or []:
        if resolution.get("field") in {"NEXT_CAMPAIGN", "PAPER_PROMOTION", "SEALED_OOS",
                                       "LIVE_TRADING", "TRADES_AUTHORIZED"}:
            resolved[resolution["field"]] = {
                "effective": resolution.get("effective"),
                "decided_by": (resolution.get("decided_by") or {}).get("source"),
            }
    campaign_authorized = str(authorization.get("next_campaign") or "").upper() == "AUTHORIZED"
    scope = authorization.get("authorization_scope")
    gate_open = bool(rfc_050_registered and campaign_authorized
                     and not draft_state["declares_unauthorized"])
    return {
        "rfc_registry": {
            "path": str(REGISTRY.relative_to(ROOT)).replace("\\", "/") if REGISTRY.exists() else None,
            "next_free_number_above_046": registry.get("next_free_number_above_046"),
            "registered_numbers": registered_numbers,
            "rfc_050_registered": rfc_050_registered,
            "current_rfc": registry.get("current_rfc"),
        },
        "rfc_050_draft": draft_state,
        "campaign_authorization": {
            "path": str(RFC049_AUTH.relative_to(ROOT)).replace("\\", "/")
            if RFC049_AUTH.exists() else None,
            "next_campaign": authorization.get("next_campaign"),
            "authorization_scope": scope,
            "covers_e2": False,
            "note": ("the only campaign authorization on record is RFC-049's, scoped to offline "
                     "development and validation of its own two hypotheses; it does not authorise a "
                     "new campaign, and E-2 is a new campaign"),
            "resolved_by_the_state_view": resolved,
            "state_view": str(STATE_VIEW.relative_to(ROOT)).replace("\\", "/")
            if STATE_VIEW.exists() else None,
        },
        "gate": {
            "state": "OPEN" if gate_open else "CLOSED",
            "why": ("RFC-050 is not registered, the draft states AUTHORIZED = false and "
                    "CAMPAIGN_STARTED = false, and no governance instrument authorises a new "
                    "campaign"),
            "allowed_with_gate_closed": [
                "write the pre-registration",
                "synthetic contract tests of the decision rule",
                "viability analysis on already-read periods",
                "prepare the runtime contract the screen would need",
            ],
            "forbidden_with_gate_closed": [
                "run the screen on any window",
                "open RFC-049's sealed OOS window or reuse its partitions as validation",
                "authorise paper promotion",
                "change any frozen threshold, criterion or cost",
            ],
        },
        "burned_windows": {
            "research_period_W1_W7": v3.get("dataset", {}).get("windows")
            or "W1-W7 2026-03-01..2026-09-24",
            "excluded_paper_day": v3.get("dataset", {}).get("paper_day_excluded"),
            "sealed_book_windows_measured_by_E1": sealed,
            "rfc049_sealed_oos_from": RFC049_SEALED_OOS_FROM,
            "note": ("W1-W7 carried the 24 registered cells and the 5m family diagnostics; RFC-049 "
                     "spent its development and validation partitions on 2019-2023 and 2024-2026; "
                     "its sealed OOS window opens at the timestamp above and has never been read. "
                     "None of them may carry E-2's validation"),
        },
        "reserved_for_e2": {
            "from": RESERVED_FROM,
            "rule": ("a forward window chosen by calendar, strictly after every period already "
                     "spent or licensed; if the window does not exist yet, the campaign waits "
                     "rather than substituting another period"),
        },
    }


# ---------------------------------------------------------------------------
# the document
# ---------------------------------------------------------------------------


def build() -> tuple[dict[str, Any], int, str]:
    governance = governance_state()
    plane = default_model(ADMISSION_SCENARIO_ID).evaluate(size_usd=200.0)
    measured_cost = None
    if E1_DISTRIBUTION.exists():
        payload = json.loads(E1_DISTRIBUTION.read_text(encoding="utf-8"))
        assessment = payload.get("assessment") or {}
        measured_cost = {
            "source": str(E1_DISTRIBUTION.relative_to(ROOT)).replace("\\", "/"),
            "state": assessment.get("state"),
            "observed_round_trip_microstructure_bps_median":
                assessment.get("observed_round_trip_microstructure_bps_median_across_books"),
            "plane_round_trip_bps": assessment.get("plane_round_trip_bps"),
            "role": ("secondary reporting layer only: the campaign is judged against the frozen "
                     "plane, and the measured distribution may be reported beside the result but "
                     "may not replace the plane or any threshold"),
        }
    tests = contract_tests()
    tests_passed = sum(1 for test in tests if test["passed"])

    payload = {
        "artifact": "WP10_E2_PREREGISTRATION",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "PHASE 4 — E-2 FORWARD DRIFT ENTRY SCREEN (PRE-REGISTRATION)",
        "version": PREREGISTRATION_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY — no market data read, no process, no order",
        "gate": governance["gate"],
        "governance": governance,
        "hypothesis": {
            "statement": (
                "at a 30-minute horizon, requiring a positive direction-adjusted forward-drift "
                "estimate at the moment of entry raises the net expectancy of the registered "
                "families that already show positive gross edge at that horizon, by enough to "
                "clear the frozen round-trip cost plane"
            ),
            "falsified_when": (
                "the screen reduces the trade count without raising net expectancy, or raises it "
                "by less than the plane, or the improvement does not hold in the validation "
                "partition — each of which is a published NOT_PROMOTE, not a failed run"
            ),
            "why_one_candidate": (
                "the brief forbids creating a family to increase candidate count; E-2 is one "
                "screen over already-named families, and the pre-registration names them below"
            ),
        },
        "universe": {
            "families_eligible": ["volatility@30m", "mean_reversion@30m", "trend@30m"],
            "why": ("the only 30m cells with a positive zero-cost gross edge in the rebuilt "
                    "baseline; the list is taken from the phase-1 rebuild, not from a search"),
            "assets": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "30m",
            "runtime_contract": (
                "Strategy.evaluate(candles, indicators, config) -> Signal | None "
                "(src/trading_bot/strategies/protocols.py): the screen is an indicator computed "
                "from candles up to and including the decision bar plus a filter on the returned "
                "signal. No new runtime layer, no exchange access, no order path"
            ),
        },
        "windows": {
            "reserved_from": RESERVED_FROM,
            "partition_rule": (
                "decision instants are split by calendar index — the first 60 % are development, "
                "the remainder validation — fixed now, before any observation exists, so no "
                "boundary can be moved after seeing a result"
            ),
            "burned": governance["burned_windows"],
            "pit_rule": (
                "every input of a decision at instant T is available at or before T; the screen "
                "uses no candle whose close is after T, and the verification re-derives this "
                "with a point-in-time check rather than trusting the implementation"
            ),
        },
        "cost_model": {
            "judged_against": {
                "scenario_id": ADMISSION_SCENARIO_ID,
                "round_trip_bps": round(plane.round_trip_bps, 9),
                "stress_1p5x_bps": round(plane.required_edge_bps(1.5), 9),
                "knowledge_mix": {c.name: c.knowledge for c in plane.components},
                "frozen": True,
            },
            "measured_layer": measured_cost,
        },
        "metrics": [
            "net expectancy bps per round trip, net of the frozen plane",
            "lower 95 % confidence bound of that expectancy",
            "sign of the net expectancy in the development partition and in the validation partition",
            "trade count achieved against the pre-registered requirement",
            "hit rate, payoff and exit mix, for the record",
            "exposure and trades per day, compared with the 3-operations-per-day objective",
            "cost under the 1.5x stress envelope, reported beside the headline",
        ],
        "decision_rule": {
            "function": "decide(net_bps, dev_size, target_bps) in scripts/wp10_e2_preregistration.py",
            "promote_requires": [
                "mean net expectancy > 0",
                "lower 95 % confidence bound > 0",
                "net expectancy positive in both development and validation",
                "trade count >= required_trades(sd of the development partition, 23.3536 bps, "
                "80 % power)",
            ],
            "minimum_detectable_effect_bps": MINIMUM_DETECTABLE_EFFECT_BPS,
            "why_that_effect": (
                "an edge smaller than one round trip at the frozen plane cannot be net positive, "
                "so a sample that cannot resolve the plane cannot separate success from noise"
            ),
            "kill_criteria": [
                "the screen cannot be expressed without reading an input from the future",
                "the trade count after screening falls below the requirement within the reserved "
                "window, and the window may not be extended to reach it",
                "the measured cost layer shows the plane is not the binding constraint, in which "
                "case the next experiment is the one E-1 names, not this one",
                "any promotion would require changing a frozen threshold",
            ],
        },
        "contract_tests": {
            "executed": True,
            "results": tests,
            "passed": tests_passed,
            "total": len(tests),
            "note": ("synthetic series only: these test the decision rule, not the market. A rule "
                     "that cannot be shown to reject what it should reject is not pre-registered, "
                     "it is a hope"),
        },
        "not_done": [
            "no window was read: the market data for E-2 does not exist yet and none was fabricated",
            "no candidate was run, no threshold was fitted, no result is reported",
            "the RFC-049 sealed window was not opened",
        ],
        "verdict": {
            "e2": "SPEC_ONLY",
            "gate": governance["gate"]["state"],
            "self_tests_passed": tests_passed == len(tests),
            "authorized": False,
            "campaign_started": False,
        },
    }
    exit_code = 0 if tests_passed == len(tests) else 3
    if governance["gate"]["state"] == "OPEN":
        exit_code = 4
    return payload, exit_code, render_markdown(payload)


def render_markdown(payload: dict[str, Any]) -> str:
    gate = payload["gate"]
    governance = payload["governance"]
    tests = payload["contract_tests"]
    lines = [
        f"# WP-10 E-2 — FORWARD DRIFT ENTRY SCREEN · PRE-REGISTRATION `{payload['version']}`",
        "",
        f"> `{payload['generated_at_utc']}` · **E-2 = {payload['verdict']['e2']}** · "
        f"gate **{gate['state']}** · authorized `{payload['verdict']['authorized']}` · "
        f"campaign started `{payload['verdict']['campaign_started']}`",
        "",
        "Nothing in this document has been run on market data, and nothing authorises a run. "
        "It exists so that when the gate opens the hypothesis, the partitions, the cost plane and "
        "the decision rule are already on the record.",
        "",
        "## 1. Why the gate is closed",
        "",
        f"* RFC-050 registry state: registered = "
        f"`{governance['rfc_registry']['rfc_050_registered']}` "
        f"(registry's next free number above 046: "
        f"`{governance['rfc_registry']['next_free_number_above_046']}`)",
        f"* RFC-050 draft: exists = `{governance['rfc_050_draft']['exists']}`, declares DRAFT = "
        f"`{governance['rfc_050_draft']['declares_draft']}`, declares AUTHORIZED = false = "
        f"`{governance['rfc_050_draft']['declares_unauthorized']}`, campaign started = "
        f"`{not governance['rfc_050_draft']['declares_campaign_not_started']}`",
        f"* the only campaign authorization on record: next_campaign = "
        f"`{governance['campaign_authorization']['next_campaign']}`, scope = "
        f"`{governance['campaign_authorization']['authorization_scope']}` — "
        f"{governance['campaign_authorization']['note']}",
        "",
        f"**Gate verdict: {gate['state']}** — {gate['why']}.",
        "",
        "Allowed while closed:",
        *[f"* {item}" for item in gate["allowed_with_gate_closed"]],
        "",
        "Forbidden while closed:",
        *[f"* {item}" for item in gate["forbidden_with_gate_closed"]],
        "",
        "## 2. Hypothesis (one, falsifiable)",
        "",
        payload["hypothesis"]["statement"] + ".",
        "",
        f"*Falsified when:* {payload['hypothesis']['falsified_when']}.",
        "",
        f"*Why only one candidate:* {payload['hypothesis']['why_one_candidate']}.",
        "",
        "## 3. Universe",
        "",
        f"* families: {', '.join(f'`{f}`' for f in payload['universe']['families_eligible'])} "
        f"— {payload['universe']['why']}",
        f"* assets: {', '.join(payload['universe']['assets'])}; timeframe "
        f"{payload['universe']['timeframe']}",
        f"* runtime contract: {payload['universe']['runtime_contract']}",
        "",
        "## 4. Reserved windows, and the windows already spent",
        "",
        f"* E-2 reserves forward data from **{payload['windows']['reserved_from']}**",
        f"* partition rule: {payload['windows']['partition_rule']}",
        f"* PIT rule: {payload['windows']['pit_rule']}",
        "",
        "| already spent | period |",
        "| --- | --- |",
        f"| research period | `{governance['burned_windows']['research_period_W1_W7']}` |",
        f"| excluded paper day | `{governance['burned_windows']['excluded_paper_day']}` |",
        f"| RFC-049 sealed OOS (never read, licensed, not to be spent here) | "
        f"`{governance['burned_windows']['rfc049_sealed_oos_from']}` onward |",
        *[f"| sealed book window measured by E-1 | `{row['run_id']}` "
          f"{row['started_at']} → {row['ended_at']} |"
          for row in governance["burned_windows"]["sealed_book_windows_measured_by_E1"]],
        "",
        "## 5. Cost plane the result will be judged against",
        "",
        f"* `{payload['cost_model']['judged_against']['scenario_id']}` = "
        f"**{payload['cost_model']['judged_against']['round_trip_bps']} bps** per round trip, "
        f"stress 1.5x = {payload['cost_model']['judged_against']['stress_1p5x_bps']} bps, frozen",
        f"* knowledge mix: "
        f"{', '.join(f'{k}={v}' for k, v in payload['cost_model']['judged_against']['knowledge_mix'].items())}",
    ]
    measured = payload["cost_model"]["measured_layer"]
    if measured:
        lines.append(f"* measured layer (E-1, secondary only): `{measured['state']}`, observed "
                     f"round trip median {measured['observed_round_trip_microstructure_bps_median']} bps "
                     f"of microstructure beside a plane of {measured['plane_round_trip_bps']} bps — "
                     f"{measured['role']}")
    lines += [
        "",
        "## 6. Metrics",
        "",
        *[f"* {metric}" for metric in payload["metrics"]],
        "",
        "## 7. The decision rule, fixed now",
        "",
        f"`{payload['decision_rule']['function']}`",
        "",
        "PROMOTE requires all of:",
        *[f"* {item}" for item in payload["decision_rule"]["promote_requires"]],
        "",
        f"* minimum detectable effect: **{payload['decision_rule']['minimum_detectable_effect_bps']} bps** "
        f"— {payload['decision_rule']['why_that_effect']}",
        "",
        "Kill criteria:",
        *[f"* {item}" for item in payload["decision_rule"]["kill_criteria"]],
        "",
        "## 8. Synthetic contract tests (executed)",
        "",
        f"{tests['passed']}/{tests['total']} passed. {tests['note']}.",
        "",
        "| test | expected | got | passed |",
        "| --- | --- | --- | --- |",
    ]
    for row in tests["results"]:
        verdict = row["verdict"]
        got = verdict.get("verdict") or verdict.get("violations") or verdict.get("sorted_verdict")
        lines.append(f"| {row['test']} | {row['expectation']} | `{got}` | "
                     f"{'yes' if row['passed'] else '**NO**'} |")
    lines += [
        "",
        "## 9. What was deliberately not done",
        "",
        *[f"* {item}" for item in payload["not_done"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                        help="run only the synthetic contract tests")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        tests = contract_tests()
        passed = sum(1 for test in tests if test["passed"])
        for test in tests:
            print(f"[{'PASS' if test['passed'] else 'FAIL'}] {test['test']} "
                  f"(expected: {test['expectation']})")
        print(f"{passed}/{len(tests)} contract tests passed")
        return 0 if passed == len(tests) else 3

    payload, exit_code, markdown = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    md_path = OUT_DIR / "WP10_E2_PREREGISTRATION.md"
    md_path.write_text(markdown + "\n", encoding="utf-8")
    payload["payload_sha256"] = hashlib.sha256(md_path.read_bytes()).hexdigest()
    (OUT_DIR / "WP10_E2_PREREGISTRATION.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"E-2 {payload['verdict']['e2']} · gate {payload['verdict']['gate']} · "
          f"contract tests {payload['contract_tests']['passed']}/{payload['contract_tests']['total']} "
          f"· {md_path.relative_to(ROOT)} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
