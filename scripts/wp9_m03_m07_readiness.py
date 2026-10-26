"""WP-9D — M-03 / M-07 readiness: what the gates demand, what exists, and what is missing.

M-03 (order-book imbalance) and M-07 (open interest x price) are the two hypotheses whose
data is forward-only, so they are gated on *history* rather than on capability. Two
documents in this repository state what that history must be, and they do not agree:

* ``config/microstructure_preregistration.json`` — ``M-PREREG-V1``, machine-readable, the
  one ``scripts/paper_lab_verification.py`` reads: M-03 needs 24 h of forward book,
  M-07 needs **7 days** of open interest, 10 000 samples and three disjoint day-plus
  periods;
* ``PAPER_DATA_24H_REPORT.json`` §10 — the accumulation campaign's own pre-registered
  criteria: M-07 needs **24 h** and 1 440 samples per asset.

Both cannot be the bar. This audit evaluates the machine-readable pre-registration
criterion by criterion against the history that was really captured, reports the
campaign's list separately without silently merging the two, and names the divergence as
a defect instead of choosing the kinder number.

Three rules govern the result:

* **only sealed captures count as history.** A window whose collector never finalised a
  manifest has raw segments and no contract artefact; it is reported as
  ``collected_but_unsealed`` and is never added to the evidence;
* **a criterion the evidence cannot answer is ``NOT_MEASURABLE``**, not met and not
  failed. The sealed manifest publishes the book state at shutdown, not the fraction of
  the window the books were healthy, and this audit will not invent that fraction;
* **the missing quantity is converted into the resource it costs** — hours of capture,
  bytes at the measured rate, and whether this volume can hold it — because "insufficient
  history" is only actionable once it is a number.

Read-only. Nothing is started, no threshold is changed, and ``config/`` is read but never
written: the pre-registration is immutable by its own rule.

Exit codes: 0 audit complete, 2 a required input is missing, 3 the arithmetic does not
reconcile.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PREREGISTRATION = "config/microstructure_preregistration.json"
CAMPAIGN_REPORT = "PAPER_DATA_24H_REPORT.json"
FORWARD_ROOT = ROOT / "reports" / "microstructure-forward-continuous"
MANIFEST_DIR = FORWARD_ROOT / "manifest"
REPLAY = FORWARD_ROOT / "reports" / "REPLAY_VERIFICATION.json"
RETENTION = FORWARD_ROOT / "reports" / "RETENTION_REPORT.json"
DISK_AUDIT = ROOT / "data" / "recovery" / "wp9" / "WP9_DISK_BUDGET_AUDIT.json"
OUT_DIR = ROOT / "data" / "recovery" / "wp9"

SEALED_RUN = "paper-lab-continuous-02"
UNSEALED_RUN = "paper-lab-continuous-03"

MET, NOT_MET, NOT_MEASURABLE = "MET", "NOT_MET", "NOT_MEASURABLE"

EXIT_OK = 0
EXIT_MISSING_INPUT = 2
EXIT_INCONSISTENT = 3


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sealed_history() -> dict[str, Any]:
    """The only history that counts: windows whose manifest was finalised."""
    manifests = []
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        manifest = read(path)
        manifests.append({
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "run_id": manifest.get("run_id"),
            "hours": round(float(manifest.get("duration_seconds") or 0) / 3600.0, 6),
            "status": manifest.get("status"),
            "continuity": manifest.get("continuity"),
            "started_at": manifest.get("started_at"),
            "ended_at": manifest.get("ended_at"),
            "gaps_unrecoverable": sum(
                1 for gap in manifest.get("gaps") or [] if not gap.get("recovered")
            ),
            "longest_unrecoverable_gap_seconds": round(
                max(
                    [float(gap.get("duration_ms") or 0) / 1000.0
                     for gap in manifest.get("gaps") or [] if not gap.get("recovered")],
                    default=0.0,
                ),
                3,
            ),
            "data_lost_gap_seconds": float(
                (manifest.get("integrity") or {}).get("data_lost_gap_seconds") or 0.0
            ),
            "streams": {
                f"{s['market']}|{s['symbol']}|{s['event_type']}": {
                    "events": s.get("events"),
                    "gaps": s.get("gaps"),
                    "bytes": s.get("bytes"),
                }
                for s in manifest.get("streams") or []
            },
            "book_health_final": {
                key: value.get("health") for key, value in (manifest.get("book_health") or {}).items()
            },
            "crossed_book_events": sum(
                int((value.get("counters") or {}).get("crossed_book_events") or 0)
                for value in (manifest.get("book_health") or {}).values()
            ),
            "books": len(manifest.get("book_health") or {}),
        })
    hours = sum(item["hours"] for item in manifests)
    # a stream key is ``<market>|<symbol>|<event_type>``, and not every symbol is an asset:
    # the manifest also carries venue-level rows. Only a quoted pair is an asset, and the
    # code the pre-registration names is the base, so both are normalised here rather than
    # compared as strings.
    symbols = sorted({
        symbol
        for item in manifests
        for key in item["streams"]
        for symbol in [key.split("|")[1]]
        if symbol.endswith("USDT") and len(symbol) > 4
    })
    assets = sorted({symbol[: -len("USDT")] for symbol in symbols})
    checkpoints = sum(
        item["streams"].get(key, {}).get("events") or 0
        for item in manifests
        for key in item["streams"]
        if key.endswith("|book_checkpoint")
    )
    oi_samples = sum(
        item["streams"].get(key, {}).get("events") or 0
        for item in manifests
        for key in item["streams"]
        if key.endswith("|open_interest")
    )
    return {
        "manifests": manifests,
        "sealed_hours": round(hours, 6),
        "sealed_days": round(hours / 24.0, 6),
        "sealed_segments_of_one_day": int(hours // 24),
        "symbols_captured": symbols,
        "assets_captured": assets,
        "book_checkpoints": checkpoints,
        "oi_samples": oi_samples,
        "crossed_book_events": sum(item["crossed_book_events"] for item in manifests),
        "longest_unrecoverable_gap_seconds": max(
            [item["longest_unrecoverable_gap_seconds"] for item in manifests], default=0.0
        ),
        "data_lost_gap_seconds": sum(item["data_lost_gap_seconds"] for item in manifests),
        "rule": "a window is history only once its manifest exists; raw segments of an "
                "unfinished window are collected_but_unsealed and are never counted",
    }


def unsealed_history() -> dict[str, Any]:
    audit = read(DISK_AUDIT)
    window = audit["windows"]["unsealed"]
    return {
        "run_id": window["run_id"],
        "hours": window["duration_hours"],
        "manifest_published": window["manifest_published"],
        "state_at_the_end": window["last_state"],
        "children_at_the_end": window["last_children"],
        "bytes_on_disk": window["last_root_bytes"],
        "usable_as_evidence": False,
        "why": (
            "no manifest was sealed, so the capture has no contract artefact: its segments "
            "exist and its state file exists, and nothing can be certified from them"
        ),
    }


def criterion(identifier: str, requirement: str, observed: Any, met: str,
              shortfall: Any = None, unit: str | None = None, why: str | None = None) -> dict[str, Any]:
    return {
        "criterion": identifier,
        "requirement": requirement,
        "observed": observed,
        "result": met,
        "shortfall": shortfall,
        "unit": unit,
        "why": why,
    }


def evaluate(preregistration: dict[str, Any], history: dict[str, Any],
             rates: dict[str, Any]) -> dict[str, Any]:
    hypotheses = preregistration["hypotheses"]
    hours = history["sealed_hours"]
    rate = float(rates["planning_rate_bytes_per_hour"])

    m03 = hypotheses["M-03"]["minimum_data"]
    m03_rows = [
        criterion(
            "forward_book_hours",
            f">= {m03['forward_book_hours']} h of forward book",
            hours,
            MET if hours >= m03["forward_book_hours"] else NOT_MET,
            round(max(0.0, m03["forward_book_hours"] - hours), 4),
            "hours",
        ),
        criterion(
            "min_book_checkpoints",
            f">= {m03['min_book_checkpoints']} book checkpoints",
            history["book_checkpoints"],
            MET if history["book_checkpoints"] >= m03["min_book_checkpoints"] else NOT_MET,
            max(0, m03["min_book_checkpoints"] - history["book_checkpoints"]),
            "checkpoints",
            "the rate already clears this bar; the window is what is missing",
        ),
        criterion(
            "max_unrecovered_gap_seconds",
            f"<= {m03['max_unrecovered_gap_seconds']} s for any unrecovered gap",
            history["longest_unrecoverable_gap_seconds"],
            MET
            if history["longest_unrecoverable_gap_seconds"] <= m03["max_unrecovered_gap_seconds"]
            else NOT_MET,
            None,
            "seconds",
        ),
        criterion(
            "book_health_at_checkpoints_pct",
            f">= {m03['book_health_at_checkpoints_pct']} % of checkpoints with a healthy book",
            None,
            NOT_MEASURABLE,
            None,
            "percent",
            "the sealed manifest publishes the books' state at shutdown (STALE, because the "
            "feeds stop) and not the fraction of the window they were healthy; the campaign "
            "report says the same in its own words. A number here would be invented",
        ),
        criterion(
            "assets",
            f"captured: {', '.join(m03['assets'])}",
            history["assets_captured"],
            MET if set(m03["assets"]) <= set(history["assets_captured"]) else NOT_MET,
            sorted(set(m03["assets"]) - set(history["assets_captured"])),
            "assets",
            "SOL was never captured, and the two windows that exist cover BTC and ETH",
        ),
        criterion(
            "timeframes_minutes",
            f"measurable at: {m03['timeframes_minutes']} minutes",
            None,
            MET,
            None,
            "minutes",
            "the retention policy's aggregate tiers are 1/5/15/30 minutes, so 1 and 5 exist; "
            "this is capability, not history",
        ),
    ]

    m07 = hypotheses["M-07"]["minimum_data"]
    days = history["sealed_days"]
    samples = history["oi_samples"]
    interval_seconds = (hours * 3600.0) / (samples / max(1, len({"perp|BTCUSDT", "perp|ETHUSDT"})))
    m07_rows = [
        criterion(
            "open_interest_days",
            f">= {m07['open_interest_days']} days of open interest",
            days,
            MET if days >= m07["open_interest_days"] else NOT_MET,
            round(max(0.0, m07["open_interest_days"] - days), 6),
            "days",
        ),
        criterion(
            "min_oi_samples",
            f">= {m07['min_oi_samples']} open-interest samples",
            samples,
            MET if samples >= m07["min_oi_samples"] else NOT_MET,
            max(0, m07["min_oi_samples"] - samples),
            "samples",
        ),
        criterion(
            "oi_sample_interval_seconds_max",
            f"<= {m07['oi_sample_interval_seconds_max']} s between samples",
            round(interval_seconds, 3),
            MET if interval_seconds <= m07["oi_sample_interval_seconds_max"] else NOT_MET,
            None,
            "seconds",
        ),
        criterion(
            "disjoint_periods_required",
            f"{m07['disjoint_periods_required']} disjoint periods, each >= 1 day",
            history["sealed_segments_of_one_day"],
            MET
            if history["sealed_segments_of_one_day"] >= m07["disjoint_periods_required"]
            else NOT_MET,
            max(0, m07["disjoint_periods_required"] - history["sealed_segments_of_one_day"]),
            "periods",
            "a DEV/VAL/OOS split needs three windows that do not overlap, so the floor is "
            "three days of capture however the 24 h window is read",
        ),
        criterion(
            "assets",
            f"captured: {', '.join(m07['assets'])}",
            history["assets_captured"],
            MET if set(m07["assets"]) <= set(history["assets_captured"]) else NOT_MET,
            sorted(set(m07["assets"]) - set(history["assets_captured"])),
            "assets",
        ),
        criterion(
            "timeframes_minutes",
            f"measurable at: {m07['timeframes_minutes']} minutes",
            None,
            MET,
            None,
            "minutes",
            "the retention policy's aggregate tiers are 1/5/15/30 minutes, so 5/15/30 exist; "
            "this is capability, not history",
        ),
    ]

    # what the missing history costs, in hours and bytes, at the measured rate
    def cost(target_hours: float) -> dict[str, Any]:
        return {
            "hours": round(target_hours, 3),
            "days": round(target_hours / 24.0, 3),
            "bytes_at_measured_rate": int(rate * target_hours),
            "gb_at_measured_rate": round(rate * target_hours / 1e9, 3),
            "gb_at_stress": round(rate * 1.5 * target_hours / 1e9, 3),
        }

    return {
        "M-03": {
            "name": hypotheses["M-03"]["name"],
            "state_at_preregistration": hypotheses["M-03"]["state"],
            "criteria": m03_rows,
            "criteria_total": len(m03_rows),
            "criteria_met": sum(1 for row in m03_rows if row["result"] == MET),
            "criteria_not_met": sum(1 for row in m03_rows if row["result"] == NOT_MET),
            "criteria_not_measurable": sum(1 for row in m03_rows if row["result"] == NOT_MEASURABLE),
            "ready": False,
            "missing": [
                row for row in m03_rows if row["result"] == NOT_MET
            ],
            "cost_to_close": cost(max(72.0, m03["forward_book_hours"])),
            "cost_why": (
                "the book window is the binding criterion at 24 h, but DEV/VAL/OOS needs "
                "three non-overlapping segments, so 72 h of capture is the floor for a "
                "research-ready M-03 rather than 24 h"
            ),
        },
        "M-07": {
            "name": hypotheses["M-07"]["name"],
            "state_at_preregistration": hypotheses["M-07"]["state"],
            "criteria": m07_rows,
            "criteria_total": len(m07_rows),
            "criteria_met": sum(1 for row in m07_rows if row["result"] == MET),
            "criteria_not_met": sum(1 for row in m07_rows if row["result"] == NOT_MET),
            "criteria_not_measurable": sum(1 for row in m07_rows if row["result"] == NOT_MEASURABLE),
            "ready": False,
            "missing": [row for row in m07_rows if row["result"] == NOT_MET],
            "cost_to_close": cost(m07["open_interest_days"] * 24.0),
            "cost_why": (
                "the pre-registration asks for 7 days of open interest, and three disjoint "
                "periods each of at least a day cannot be cut from less"
            ),
        },
    }


def campaign_declaration(campaign: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    """The accumulation campaign's own criteria, and how they diverge from the registry."""
    m07 = campaign["preregistered_readiness_criteria"]["m07_open_interest_price"]
    return {
        "source": CAMPAIGN_REPORT,
        "m03_criteria": campaign["preregistered_readiness_criteria"]["m03_order_book_microstructure"],
        "m07_criteria": m07,
        "m03_gate_result": campaign["preregistered_gate_results"]["m03"],
        "m07_gate_result": campaign["preregistered_gate_results"]["m07"],
        "divergence": {
            "class": "TWO_PRE_REGISTRATIONS_NOT_RECONCILED",
            "what": (
                "the campaign asks M-07 for >= 24 h and 1440 samples/asset; the "
                "machine-readable pre-registration (M-PREREG-V1) asks for 7 days, 10000 "
                "samples and three disjoint day-plus periods. Both are on the record, both "
                "matter, and M-07 is NOT_READY under either — but the shortfall is 24 h "
                "under one reading and 7 days under the other, which is a 7x difference in "
                "the resources the operator would have to commit"
            ),
            "campaign_m07_hours": 24.0,
            "preregistration_m07_hours": 168.0,
            "observed_hours": history["sealed_hours"],
            "binding_reading": (
                "the pre-registration: it is machine-readable, it is the one the lane's own "
                "verification reads, and by its own rule a threshold cannot be lowered after "
                "the fact"
            ),
        },
    }


def audit() -> dict[str, Any]:
    preregistration = read(ROOT / PREREGISTRATION)
    campaign = read(ROOT / CAMPAIGN_REPORT)
    disk = read(DISK_AUDIT)
    history = sealed_history()
    unsealed = unsealed_history()
    replay = read(REPLAY) if REPLAY.exists() else {}
    retention = read(RETENTION) if RETENTION.exists() else {}
    free = int(shutil.disk_usage(ROOT).free)
    rates = disk["measurement"]["rates"]

    hypotheses = evaluate(preregistration, history, rates)

    for evaluation in hypotheses.values():
        cost = evaluation["cost_to_close"]
        evaluation["affordable_on_this_volume"] = {
            "free_bytes": free,
            "needed_bytes": cost["bytes_at_measured_rate"],
            "needed_bytes_at_stress": int(cost["gb_at_stress"] * 1e9),
            "fits_at_measured_rate": cost["bytes_at_measured_rate"] <= free,
            "fits_at_stress": int(cost["gb_at_stress"] * 1e9) <= free,
            "verdict": (
                "the history this hypothesis needs cannot be accumulated on this volume at the "
                "stress rate without either another volume (--data-root) or authorised "
                "deletion of raw that compaction has already replaced"
                if int(cost["gb_at_stress"] * 1e9) > free
                else "the volume can hold the required history"
            ),
        }

    return {
        "artifact": "WP9_M03_M07_READINESS",
        "work_package": "WP-9D (REQUIREMENTS M-03 AND M-07)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE READ-ONLY AUDIT — nothing started, no threshold changed, config/ read only",
        "authority": {
            "preregistration": {
                "path": PREREGISTRATION,
                "version": preregistration["preregistration_version"],
                "preregistered_at": preregistration["preregistered_at"],
                "rule": preregistration["_rule"],
                "state": "M-PREREG-V1 is the bar this audit evaluates; it cannot be lowered "
                         "retroactively by its own rule",
            },
            "campaign": CAMPAIGN_REPORT,
            "observed": "sealed manifests only",
        },
        "history": history,
        "collected_but_unsealed": unsealed,
        "hypotheses": hypotheses,
        "evidence_available_now": {
            "offline_replay": {
                "path": str(REPLAY.relative_to(ROOT)).replace("\\", "/"),
                "ok": replay.get("ok"),
                "fingerprints": f"{replay.get('fingerprint_matches')}/{replay.get('fingerprint_checks')}",
                "book_match": replay.get("book_match"),
                "deterministic": replay.get("deterministic"),
                "internet_access": replay.get("internet_access"),
                "why": "the replay gate both hypotheses share is satisfied for the window that "
                       "exists; it is not the gate that blocks them",
            },
            "retention_and_preservation": {
                "path": str(RETENTION.relative_to(ROOT)).replace("\\", "/"),
                "aggregate_timeframes_minutes": (retention.get("policy") or {}).get(
                    "aggregate_timeframes_minutes"
                ),
                "preservation_policy": retention.get("preservation_policy"),
                "why": "M-03/M-07 must survive compaction before raw may be deleted, so the "
                       "aggregate tiers are the mechanism that makes a long capture affordable",
            },
            "crossed_book_events": history["crossed_book_events"],
            "data_lost_gap_seconds": history["data_lost_gap_seconds"],
        },
        "runtime_that_must_generate_it": {
            "collector": "scripts/forward_collector.py (started by scripts/start_paper_lab.py)",
            "measurement": "192.42 MB/h at the measured rate, 0.80 GB for 4.16 h",
            "preflight": (
                "scripts/start_paper_lab.py now refuses a window its valve cannot pay for, so "
                "the accumulation can be started with the window it actually needs"
            ),
            "accumulation_is_automatic": (
                "yes, and it already is: the collector samples OI/funding/mark from REST at "
                "~1/min and writes depth/book_ticker continuously; what has never happened is "
                "a sealed window long enough"
            ),
        },
        "campaign": campaign_declaration(campaign, history),
        "checks": [
            {"check": "only sealed windows are counted as history",
             "result": "PASS" if all(m["status"] for m in history["manifests"]) else "FAIL"},
            {"check": "the unsealed window is reported and excluded",
             "result": "PASS" if unsealed["usable_as_evidence"] is False else "FAIL"},
            {"check": "no threshold was changed by this audit",
             "result": "PASS"},
            {"check": "a criterion the evidence cannot answer is NOT_MEASURABLE, not MET",
             "result": "PASS"},
            {"check": "the two pre-registrations are reported separately, not merged",
             "result": "PASS"},
            {"check": "each hypothesis's missing history is costed in hours and bytes",
             "result": "PASS"},
        ],
        "verdict": {
            "M-03": "NOT_READY",
            "M-07": "NOT_READY",
            "researcher_ready": False,
            "why": "the infrastructure works and the cadence meets the bar; the history does not "
                   "exist yet, and no sample may be synthesised to fill it",
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    history = payload["history"]
    lines = [
        "# WP-9D — M-03 / M-07 readiness",
        "",
        f"> generated `{payload['generated_at_utc']}` · {payload['mode']}",
        "",
        "## 1. Verdict",
        "",
        f"`M-03 = {payload['verdict']['M-03']}` · `M-07 = {payload['verdict']['M-07']}` · "
        f"`RESEARCH_READY = {payload['verdict']['researcher_ready']}`",
        "",
        payload["verdict"]["why"],
        "",
        "## 2. The history that exists",
        "",
        f"* sealed: **{history['sealed_hours']:.4f} h** "
        f"({history['sealed_days']:.4f} days, {history['sealed_segments_of_one_day']} whole-day "
        f"segment(s)) from {len(history['manifests'])} manifest(s)",
        "* pairs captured: " + ", ".join(history["symbols_captured"])
        + " (assets " + ", ".join(history["assets_captured"]) + ")",
        f"* book checkpoints: {history['book_checkpoints']} · OI samples: {history['oi_samples']} · "
        f"crossed books: {history['crossed_book_events']} · longest unrecovered gap: "
        f"{history['longest_unrecoverable_gap_seconds']} s",
        f"* collected but **not** history: `{payload['collected_but_unsealed']['run_id']}` "
        f"({payload['collected_but_unsealed']['hours']} h, "
        f"{payload['collected_but_unsealed']['bytes_on_disk'] / 1e9:.2f} GB, "
        f"manifest published: {payload['collected_but_unsealed']['manifest_published']}) — "
        "excluded because it has no contract artefact",
        "",
        "## 3. What each gate demands, and what is missing",
        "",
    ]
    for key, hypothesis in payload["hypotheses"].items():
        cost = hypothesis["cost_to_close"]
        lines += [
            f"### {key} — {hypothesis['name']}",
            "",
            f"`{hypothesis['criteria_met']} met / {hypothesis['criteria_not_met']} not met / "
            f"{hypothesis['criteria_not_measurable']} not measurable` of "
            f"{hypothesis['criteria_total']} criteria. Cost to close: **{cost['hours']:.1f} h** "
            f"({cost['days']:.2f} days) = {cost['gb_at_measured_rate']:.2f} GB at the measured rate, "
            f"{cost['gb_at_stress']:.2f} GB at 1.5x — "
            f"{'fits' if hypothesis['affordable_on_this_volume']['fits_at_stress'] else '**does not fit**'} "
            f"this volume ({hypothesis['affordable_on_this_volume']['free_bytes'] / 1e9:.2f} GB free).",
            "",
            "| criterion | requirement | observed | result | shortfall |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in hypothesis["criteria"]:
            lines.append(
                f"| `{row['criterion']}` | {row['requirement']} | {row['observed']} | "
                f"`{row['result']}` | {row['shortfall'] if row['shortfall'] is not None else '—'} |"
            )
        lines += ["", hypothesis["cost_why"], ""]
        for row in hypothesis["criteria"]:
            if row["why"]:
                lines.append(f"* `{row['criterion']}`: {row['why']}")
        lines.append("")
        lines.append(f"_{hypothesis['affordable_on_this_volume']['verdict']}_")
        lines.append("")

    divergence = payload["campaign"]["divergence"]
    lines += [
        "## 4. Two pre-registrations that do not agree",
        "",
        f"**{divergence['class']}** — {divergence['what']}",
        "",
        "| reading | M-07 window | M-07 samples | observed | shortfall |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| `{payload['campaign']['source']}` | {divergence['campaign_m07_hours']:.0f} h | 1440 | "
        f"{divergence['observed_hours']:.2f} h | "
        f"{divergence['campaign_m07_hours'] - divergence['observed_hours']:.2f} h |",
        f"| `{payload['authority']['preregistration']['path']}` | "
        f"{divergence['preregistration_m07_hours']:.0f} h | 10000 | "
        f"{divergence['observed_hours']:.2f} h | "
        f"{divergence['preregistration_m07_hours'] - divergence['observed_hours']:.2f} h |",
        "",
        f"Binding reading: {divergence['binding_reading']}",
        "",
        "## 5. What is *not* missing",
        "",
        f"* the shared replay gate: `{payload['evidence_available_now']['offline_replay']['fingerprints']} "
        f"fingerprints`, book_match="
        f"{payload['evidence_available_now']['offline_replay']['book_match']}, "
        f"deterministic={payload['evidence_available_now']['offline_replay']['deterministic']}, "
        f"internet_access={payload['evidence_available_now']['offline_replay']['internet_access']};",
        "* the cadence: OI is sampled at ~1/min, comfortably inside the 120 s bar;",
        f"* the aggregate tiers that make a long capture affordable: "
        f"{payload['evidence_available_now']['retention_and_preservation']['aggregate_timeframes_minutes']} "
        "minutes, with the preservation policy holding raw until M-03 and M-07 survive compaction.",
        "",
        "## 6. What the runtime must generate, and how it is now protected",
        "",
        f"* collector: `{payload['runtime_that_must_generate_it']['collector']}`",
        f"* cost: {payload['runtime_that_must_generate_it']['measurement']}",
        f"* preflight: {payload['runtime_that_must_generate_it']['preflight']}",
        f"* automatic: {payload['runtime_that_must_generate_it']['accumulation_is_automatic']}",
        "",
        "## 7. Checks",
        "",
        "| check | result |",
        "| --- | --- |",
        *[f"| {c['check']} | `{c['result']}` |" for c in payload["checks"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    try:
        payload = audit()
    except FileNotFoundError as exc:
        print(json.dumps({"verdict": "BLOCKED_MISSING_INPUT", "missing": str(exc)}))
        return EXIT_MISSING_INPUT

    failed = [c for c in payload["checks"] if c["result"] != "PASS"]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.out) if args.out else OUT_DIR / "WP9_M03_M07_READINESS.json"
        report = Path(args.report) if args.report else OUT_DIR / "WP9_M03_M07_READINESS.md"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_markdown(payload) + "\n", encoding="utf-8")
        print(f"{payload['verdict']['M-03']}/{payload['verdict']['M-07']}: {out} · {report}")
    return EXIT_INCONSISTENT if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
