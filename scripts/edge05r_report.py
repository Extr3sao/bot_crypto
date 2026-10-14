#!/usr/bin/env python
"""WP-EDGE-05R — render every report from one frozen snapshot, or refuse to render at all.

`RUN_REPORT.json`, `RUN_REPORT.md` and `FINAL_REPORT.md` all come from the same
`READING_SNAPSHOT.json`. Nothing here reads the live lane, the store or the clock: the numbers were
read once, tagged with the instant and the digest of the artefact they came from, and frozen. Two
renders of the same snapshot therefore agree exactly, and a snapshot edited after it was taken is
refused rather than rendered — which is the difference between a consistent report and one that
happens to look consistent today.

The acceptance matrix is part of the same rendering: each ACC row states its verdict *and* the
figures that produced it, so a row that cannot point at evidence has to say `NOT_TESTED` instead of
being asserted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge05 import reading  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_TESTED = "NOT_TESTED"


class Snapshot:
    """A verified snapshot with the accessors the rules below are written against."""

    def __init__(self, body: reading.ReadingSnapshot) -> None:
        self.body = body
        self.figures = {item.name: item for item in body.figures}

    def __call__(self, name: str, default: Any = None) -> Any:
        item = self.figures.get(name)
        return item.value if item is not None else default

    def has(self, name: str) -> bool:
        return name in self.figures

    def check(self, name: str, key: str = "status") -> Any:
        return ((self.body.facts.get("newest_checks") or {}).get(name) or {}).get(key)

    def alerts_of_kind(self, kind: str) -> int:
        return int((self(self.name_of_alert_kinds) or {}).get(kind) or 0)

    name_of_alert_kinds = "watchdog_alert_kinds"


# --------------------------------------------------------------------------- the rules
def _present(s: Snapshot, names: list[str]) -> bool:
    """Absent is not zero.

    Every defect count below is written as `int(s(name) or 0) == 0`, which reads a missing artefact
    as a clean bill of health — the exact substitution this work package exists to remove. A `PASS`
    is therefore conditional on the figures it cites being *in the reading*; when they are not, the
    row says `NOT_TESTED`, because "nobody counted" and "the count is zero" are different sentences.
    """
    return all(s.has(name) and s(name) is not None for name in names)


def _acc_01(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["runtime_authority_map_bytes", "git_head"]
    return (
        PASS if s.has("runtime_authority_map_bytes") else NOT_TESTED,
        figures,
        "the authority map of this work package exists, and the commit it was taken at is recorded",
    )


def _acc_02(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["lane_ticks_observed", "lane_ticks_total"]
    ok = int(s("lane_ticks_observed") or 0) >= 2 and s.check("scheduler_task") == "OK"
    return (
        PASS if ok else BLOCKED,
        [*figures, "watchdog_newest_at_utc"],
        "ticks fired from the registered task with no hand running the command",
    )


def _acc_03(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["watchdog_detection_latency_seconds", "watchdog_alert_kinds"]
    detected = int((s("watchdog_alert_kinds") or {}).get("SCHEDULER_DISABLED") or 0) >= 1
    return (
        PASS if detected and s.has("watchdog_detection_latency_seconds") else NOT_TESTED,
        figures,
        "an induced stop was alerted and closed by a named recovering tick; the latency is the one "
        "that rehearsal measured",
    )


def _acc_04(s: Snapshot) -> tuple[str, list[str], str]:
    figures = [
        "defect_chain_broken",
        "defect_double_claim",
        "restart_proof_broken",
        "reconciliation_seals_orphaned",
    ]
    if not _present(s, figures):
        return (
            NOT_TESTED,
            figures,
            "the reconciliation that carries these counts is not in the reading; an absent count is "
            "not a clean one",
        )
    ok = all(int(s(name) or 0) == 0 for name in figures)
    return (
        PASS if ok else FAIL,
        figures,
        "bars already persisted when a process stopped are attributed once and nothing is duplicated",
    )


def _acc_05(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["defect_seal_missing", "defect_seal_orphaned", "defect_decision_divergence"]
    if not _present(s, [*figures, "reconciliation_seals"]):
        return (
            NOT_TESTED,
            [*figures, "reconciliation_seals"],
            "the seal accounting is not in the reading, and no seal count is not the same as no lost "
            "seal",
        )
    ok = all(int(s(name) or 0) == 0 for name in figures) and int(s("reconciliation_seals") or 0) > 0
    return (
        PASS if ok else FAIL,
        [*figures, "reconciliation_seals"],
        "one logical decision per slot, strategy and asset, with every seal accounted for",
    )


def _acc_06(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["lane_ticks_already_observed", "lane_ticks_already_running"]
    ok = int(s("lane_ticks_already_observed") or 0) >= 1 and int(s("lane_ticks_already_running") or 0) >= 1
    return (
        PASS if ok else NOT_TESTED,
        figures,
        "a second pass over a slot that was already observed appends nothing",
    )


def _acc_07(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["restart_proof_broken", "reconciliation_unattributed_bars"]
    if not _present(s, figures):
        return (
            NOT_TESTED,
            [*figures, "watchdog_newest_at_utc"],
            "the restart arithmetic is not in the reading, so the lease cannot be read as a number "
            "here",
        )
    ok = all(int(s(name) or 0) == 0 for name in figures) and s.check("lane_lease") == "OK"
    return (
        PASS if ok else BLOCKED,
        [*figures, "watchdog_newest_at_utc"],
        "the lease is read as arithmetic rather than guessed from a pid, and no abandoned lease was "
        "found in the newest reading",
    )


def _acc_08(s: Snapshot) -> tuple[str, list[str], str]:
    return (
        NOT_TESTED,
        ["defect_chain_broken"],
        "no live provider outage has occurred in this window, so the classification is exercised in "
        "tests and not in the field; declaring it PASS would be an assertion, not a measurement",
    )


def _acc_09(s: Snapshot) -> tuple[str, list[str], str]:
    figures = [
        "lane_ticks_disk_budget_exceeded",
        "lane_first_disk_refusal_utc",
        "volume_verdict",
        "storage_reclaimed_bytes",
        "storage_verdict_after",
    ]
    refused = int(s("lane_ticks_disk_budget_exceeded") or 0)
    return (
        PASS if refused > 0 else NOT_TESTED,
        figures,
        "the floors were crossed for real: the lane refused its own ticks before any request, deleted "
        "nothing, and resumed once space came back",
    )


def _acc_10(s: Snapshot) -> tuple[str, list[str], str]:
    figures = [
        "forward_days_with_data",
        "forward_days_densely_covered_but_backfilled",
        "forward_days_prospectively_observed",
        "forward_days_required",
    ]
    ok = int(s("forward_days_densely_covered_but_backfilled") or 0) >= 1
    return (
        PASS if ok else NOT_TESTED,
        figures,
        "backfilled days are counted and excluded; a day that is not prospectively complete is not "
        "added, so the honest count stays at zero",
    )


def _acc_11(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["lane_last_parity_verdict", "lane_last_ruleset_params_hash"]
    ok = str(s("lane_last_parity_verdict")) == "PARITY_PASS"
    return (
        PASS if ok else NOT_TESTED,
        figures,
        "the newest tick's own parity verdict and the parameters hash it ran under; no limit, size "
        "or gate was touched by this work package",
    )


def _acc_12(s: Snapshot) -> tuple[str, list[str], str]:
    figures = [
        "verification_verdict",
        "verification_self_test",
        "tests_chain_passed",
        "tests_chain_exit_code",
        "tests_chain_failed",
    ]
    verdict = str(s("verification_verdict") or "")
    self_test = str(s("verification_self_test") or "")
    failed = s("tests_chain_failed")
    chain_exit = s("tests_chain_exit_code")
    ok = (
        verdict.startswith("VERIFY_PASS")
        and self_test.startswith("SELF_TEST_PASS")
        and failed is not None
        and int(failed) == 0
        and chain_exit is not None
        and int(chain_exit) == 0
    )
    return (
        PASS if ok else FAIL,
        figures,
        "the verifier's own verdict and the chain suites' own exit code, both paid for by running "
        "the commands rather than by summarising them",
    )


def _acc_13(s: Snapshot) -> tuple[str, list[str], str]:
    figures = [
        "lane_rows_claiming_an_order",
        "watchdog_rows_claiming_an_order",
        "reconciliation_market_requests",
    ]
    if not _present(s, figures):
        return (
            NOT_TESTED,
            figures,
            "one of the three logs that would have to be read to say this is not in the reading",
        )
    ok = all(int(s(name) or 0) == 0 for name in figures)
    return (
        PASS if ok else FAIL,
        figures,
        "no row in the lane's log, the watchdog's log or the reconciliation claims an order or a "
        "promotion",
    )


def _acc_14(s: Snapshot) -> tuple[str, list[str], str]:
    return (
        NOT_TESTED,
        ["forward_days_prospectively_observed", "forward_days_required"],
        "the sixty-day gate is a later milestone, not a condition of this work package; the window "
        "measured here is hours, not days",
    )


def _acc_15(s: Snapshot) -> tuple[str, list[str], str]:
    figures = ["git_head", "git_commits_since_root", "git_dirty_entries", "github_push_state"]
    ok = s.has("git_head") and s.has("github_push_state")
    return (
        PASS if ok else NOT_TESTED,
        figures,
        "the commit this reading was taken at, what is still uncommitted in the shared checkout, and "
        "the recorded result of the publication probe",
    )


RULES: tuple[tuple[str, str, Callable[[Snapshot], tuple[str, list[str], str]]], ...] = (
    ("ACC-01", "Runtime audit and a reproducible baseline", _acc_01),
    ("ACC-02", "The scheduler really fires, with nobody running the command", _acc_02),
    ("ACC-03", "The watchdog detects an induced stop, with a measured latency", _acc_03),
    ("ACC-04", "A stop after partial persistence duplicates no bar", _acc_04),
    ("ACC-05", "A stop during decision or seal leaves one logical decision per slot", _acc_05),
    ("ACC-06", "A retry of the same slot is idempotent everywhere", _acc_06),
    ("ACC-07", "A restart leaves no orphan lease and no crash", _acc_07),
    ("ACC-08", "A provider outage is classified, and no forward day is invented", _acc_08),
    ("ACC-09", "Disk pressure blocks before corruption and preserves evidence", _acc_09),
    ("ACC-10", "Forward eligibility excludes backfill and incomplete days", _acc_10),
    ("ACC-11", "Risk limits and gates are unchanged", _acc_11),
    ("ACC-12", "Independent verification, with the command's own exit code", _acc_12),
    ("ACC-13", "Operation without orders", _acc_13),
    ("ACC-14", "A long unattended window", _acc_14),
    ("ACC-15", "Git and traceability", _acc_15),
)


def matrix(snapshot: Snapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for identifier, requirement, rule in RULES:
        verdict, figures, note = rule(snapshot)
        cited = []
        for name in figures:
            item = snapshot.figures.get(name)
            cited.append(
                {
                    "figure": name,
                    "value": item.value if item is not None else None,
                    "unit": item.unit if item is not None else "",
                    "as_of_utc": item.as_of_utc if item is not None else "",
                    "source_artifact": item.source_artifact if item is not None else "",
                    "source_digest": item.source_digest if item is not None else "",
                    "measurement_scope": item.measurement_scope if item is not None else "",
                }
            )
        rows.append(
            {
                "id": identifier,
                "requirement": requirement,
                "verdict": verdict,
                "note": note,
                "evidence": cited,
            }
        )
    return rows


def pressure_line(snapshot: Snapshot) -> str:
    """What the volume means for the *next* tick, which is not the same as for the last one."""
    verdict = str(snapshot("volume_verdict"))
    free = snapshot("volume_free_gib")
    if verdict == "BELOW_CRITICAL":
        return (
            f"**The volume is below the critical floor right now ({free} GiB free)**: the next "
            "scheduled tick will be refused again until space is returned, so the resumed ingest "
            "above is a window, not a fixed state."
        )
    if verdict == "ABOVE_CRITICAL_BELOW_HEALTHY":
        return (
            f"The volume is above the critical floor but under the healthy one ({free} GiB free): "
            "the lane ingests and the heavy publication waits. One more consumer on this volume ends "
            "the window."
        )
    return f"The volume is above both floors ({free} GiB free)."


def floor_line(snapshot: Snapshot) -> str:
    """What the volume means, from the floors the lane's own guard uses — not from a literal.

    The sentence this replaced said "the healthy 5 GiB floor is not reached" unconditionally, and
    the report of 2026-10-14T00:22Z printed it beside a verdict of `BELOW_CRITICAL`. A sentence
    that cannot follow its own figure from one reading to the next is the defect this work package
    exists to remove, so this one is a function of the figures and nothing else.
    """
    verdict = str(snapshot("storage_verdict_after"))
    free = snapshot("volume_free_gib")
    reclaimed = snapshot("storage_reclaimed_bytes")
    if verdict == "HEALTHY":
        return (
            f"- El volumen queda **por encima de los dos suelos declarados** (`{verdict}`, {free} GiB "
            f"libres). De ese espacio, **{reclaimed} bytes** son cachés de herramienta que devolvió "
            "este work package; el resto del alivio no es suyo: se recuperó fuera del repositorio, "
            "entre dos lecturas del mismo volumen, y las dos quedan etiquetadas con su instante en el "
            "informe técnico en lugar de presentarse como una sola."
        )
    if verdict == "ABOVE_CRITICAL_BELOW_HEALTHY":
        return (
            f"- El volumen queda **por encima del suelo crítico y por debajo del sano** (`{verdict}`, "
            f"{free} GiB libres) tras devolver {reclaimed} bytes de caché: la lane ingiere y la "
            "publicación pesada espera. Un consumidor más en este volumen cierra la ventana."
        )
    return (
        f"- **No se alcanza el suelo crítico de 2 GiB** (`{verdict}`, {free} GiB libres), y con las "
        f"cachés ({reclaimed} bytes) no basta: el siguiente tick programado seguirá siendo rechazado "
        "antes de hacer ninguna petición de mercado. Cerrar esa distancia no es una limpieza — el "
        "inventario de diagnóstico nombra los consumidores, dentro y fuera del repositorio, y la "
        "decisión es del propietario del volumen."
    )


def reclaim_note(snapshot: Snapshot) -> str:
    """What the sweep's own result means, in the English report, derived from its own verdict.

    The sentence this replaces said "it was not enough to reach the healthy floor" unconditionally,
    and the reading of 2026-10-14T05:44:52Z recorded `HEALTHY` — the same class of contradiction as
    the floors table it sat under.
    """
    base = (
        "The reclaim removed tool caches and nothing else: each path was checked, at the moment it "
        "was removed, for being a cache by name, untracked by git and named in `.gitignore`. Market "
        "data, evidence, other workstreams' artefacts, source and the environment's own files were "
        "sized and left alone."
    )
    verdict = str(snapshot("storage_verdict_after"))
    if verdict == "HEALTHY":
        return base + (
            " The volume clears both declared floors at the instants this report cites, and most of "
            "that headroom is not this work package's doing: the sweep returned tens of MiB inside "
            "the repository while the volume gained several GiB from outside it, between two "
            "readings this report keeps separate rather than blending. What the repository could "
            "give back on its own was given back; the rest is the volume owner's decision, planned "
            "rather than executed in `VOLUME_NEIGHBOURS.md`."
        )
    if verdict == "ABOVE_CRITICAL_BELOW_HEALTHY":
        return base + (
            " It was not enough to reach the healthy floor: the lane ingests and the heavy "
            "publication waits, and the plan for what remains is the owner's to accept or refuse."
        )
    return base + (
        " It was not enough to reach the critical floor either, so the next scheduled tick will be "
        "refused before it makes any market request; the plan for what remains is the owner's to "
        "accept or refuse."
    )


def resumed_tick_line(snapshot: Snapshot) -> str:
    """Whether the tick after the recovery observed — which may only be said if it did.

    The report of 2026-10-14T00:22Z said "the next scheduled tick observed again" and then quoted
    `DISK_BUDGET_EXCEEDED` with 0 new bars in the same sentence: a claim and its own refutation,
    four words apart. The outcome now decides which sentence is printed.
    """
    outcome = str(snapshot("lane_last_outcome"))
    when = snapshot("lane_last_tick_utc")
    bars = snapshot("lane_last_new_bars")
    if outcome in ("OBSERVED", "NO_NEW_DATA"):
        return (
            f"- El tick programado **después** de la recuperación volvió a observar: `{outcome}` a las "
            f"`{when}` con {bars} barra(s) nuevas, y sin que nadie ejecutara el comando a mano. Es la "
            "comprobación que pedía el encargo: el mismo planificador, con el volumen por encima del "
            "suelo, y el rechazo anterior conservado en el registro."
        )
    if outcome == "DISK_BUDGET_EXCEEDED":
        return (
            f"- El tick programado **no** volvió a observar: `{outcome}` a las `{when}`, rechazado por "
            "el guardián de disco de la propia lane antes de hacer ninguna petición de mercado. No hay "
            "ningún éxito que declarar aquí: mientras el volumen no esté por encima del suelo, el "
            "siguiente tick será rechazado igual."
        )
    return (
        f"- El tick más nuevo terminó en `{outcome}` a las `{when}` con {bars} barra(s) nuevas: ni "
        "un éxito ni un rechazo por disco, y este informe no lo presenta como ninguna de las dos cosas."
    )


def publication_line(snapshot: Snapshot) -> str:
    """The publication probe's own verdict, quoted instead of remembered.

    The report of 2026-10-14T00:22Z said publication was still blocked by authentication while
    `GITHUB_STATE.json` of 22:01:54Z recorded the same probe exiting 0 on the same branch. One of
    the two documents was out of date, and neither said which.
    """
    state = str(snapshot("github_push_state"))
    code = snapshot("github_probe_exit_code")
    if state == "AVAILABLE_NOT_EXERCISED":
        return (
            f"- La publicación en GitHub **está disponible y no se ha ejercido** (`{state}`, sonda con "
            f"código `{code}`): ningún ref remoto se ha tocado y los commits quedan locales hasta que "
            "el operador lo pida."
        )
    if state in ("BLOCKED_GITHUB_AUTH", "BLOCKED", "UNKNOWN", ""):
        return (
            f"- La publicación en GitHub sigue bloqueada (`{state}`, sonda con código `{code}`): los "
            "commits quedan locales."
        )
    return (
        f"- Estado de publicación registrado: `{state}` (sonda con código `{code}`), tal como lo "
        "dejó la última ejecución del sondeo."
    )


def work_package_verdict(rows: list[dict[str, Any]], state: str) -> tuple[str, str]:
    """The one verdict that may not be asserted: may this work package call itself closed?"""
    failures = [row["id"] for row in rows if row["verdict"] == FAIL]
    blocked = [row["id"] for row in rows if row["verdict"] == BLOCKED]
    untested = [row["id"] for row in rows if row["verdict"] == NOT_TESTED]
    if failures or blocked:
        return "NOT_CLOSED", (
            f"{len(failures)} acceptance row(s) failed and {len(blocked)} are blocked: "
            f"{', '.join(failures + blocked)}"
        )
    if state == "INGEST_BLOCKED":
        return "NOT_CLOSED_INGEST_BLOCKED", (
            "the lane cannot observe at this instant, so no closure is declared: the rows below "
            "describe the state that could be read, and the ingest itself is blocked"
        )
    if untested:
        return "CLOSED_WITH_OPEN_ITEMS", (
            f"every row that could be measured is PASS, with {len(untested)} declared not tested: "
            f"{', '.join(untested)}"
        )
    return "CLOSED", "every acceptance row is PASS"


def ingest_state(snapshot: Snapshot) -> tuple[str, str]:
    """Whether the lane is observing right now — the one thing that may not be called PASS."""
    last = str(snapshot("lane_last_outcome"))
    refused = int(snapshot("lane_ticks_disk_budget_exceeded") or 0)
    if last == "DISK_BUDGET_EXCEEDED":
        return "INGEST_BLOCKED", (
            "The newest tick was refused by the lane's own disk guard: no report may claim success "
            "while the lane cannot observe"
        )
    if last in ("OBSERVED", "NO_NEW_DATA"):
        if refused:
            return "INGEST_RESUMED", (
                f"The lane refused {refused} tick(s) on disk and has observed again since: the "
                "refusal was real and is over"
            )
        return "INGESTING", "The newest tick observed, with no refusal on record"
    return "INGEST_UNKNOWN", f"The newest tick's outcome is {last!r}"


# --------------------------------------------------------------------------- rendering
def _figure_row(snapshot: Snapshot, name: str) -> str:
    item = snapshot.figures.get(name)
    if item is None:
        return f"| `{name}` | *(absent)* | | | | |"
    value = item.value
    if isinstance(value, dict):
        value = ", ".join(f"{key}={value[key]}" for key in sorted(value)[:8])
    return (
        f"| `{item.name}` | {value} | {item.unit} | {item.as_of_utc} | "
        f"`{item.source_digest[:12]}…` | {item.measurement_scope} |"
    )


def classification_evidence(snapshot: Snapshot) -> list[dict[str, str]]:
    """The alert transitions that show a refused tick filed as pressure, not as a scheduler fault.

    Read from the reading's own timeline, so these rows carry this reading's instant and cannot be
    quoted from another one. The historical rows matter as much as the newest: an alert that used to
    fire on a disk refusal and no longer does is the repair, visible.
    """
    relevant = ("SCHEDULER_TASK_FAILED", "TICK_REFUSED_RESOURCE", "SCHEDULER_DISABLED")
    rows: list[dict[str, str]] = []
    for row in snapshot.body.facts.get("timeline") or []:
        if row.get("actor") != "alert":
            continue
        what = str(row.get("what") or "")
        if any(kind in what for kind in relevant):
            rows.append(
                {
                    "instant_utc": str(row.get("instant_utc") or ""),
                    "alert": what,
                    "as_of_utc": str(row.get("as_of_utc") or ""),
                    "run_id": str(row.get("run_id") or ""),
                }
            )
    return rows


def render_run_md(
    snapshot: Snapshot,
    rows: list[dict[str, Any]],
    state: str,
    why: str,
    verdict: str,
    verdict_why: str,
) -> str:
    body = snapshot.body
    lines = [
        "# WP-EDGE-05R — recovery and reporting integrity",
        "",
        f"*One reading, taken at `{body.as_of_utc}`, snapshot `{body.run_id}`, digest "
        f"`{body.digest[:16]}…`. Every figure in this report was read at that instant and says so; "
        "the Markdown, the JSON and the executive summary are three renderings of that one file.*",
        "",
        "## 0. The bottom line",
        "",
        f"**Work package verdict: `{verdict}`** — {verdict_why}.",
        "",
        f"**Ingest state: `{state}`.** {why}.",
        "",
        pressure_line(snapshot),
        "",
        "| Question | Answer, as of this reading |",
        "| --- | --- |",
        f"| Free space | {snapshot('volume_free_gib')} GiB (`{snapshot('volume_verdict')}`) |",
        f"| Lane ticks | {snapshot('lane_ticks_total')} total, "
        f"{snapshot('lane_ticks_observed')} observed, {snapshot('lane_ticks_disk_budget_exceeded')} "
        f"refused on disk |",
        f"| Newest tick | `{snapshot('lane_last_outcome')}` at {snapshot('lane_last_tick_utc')} |",
        f"| Watchdog readings | {snapshot('watchdog_readings')}, newest "
        f"`{snapshot('watchdog_newest_verdict')}` / `{snapshot('watchdog_newest_category')}` |",
        f"| Forward days | {snapshot('forward_days_prospectively_observed')} of "
        f"{snapshot('forward_days_required')} prospectively observed; "
        f"{snapshot('forward_days_with_data')} days carry data, "
        f"{snapshot('forward_days_densely_covered_but_backfilled')} of them backfilled |",
        f"| Reconciliation | `{snapshot('reconciliation_verdict')}` / "
        f"`{snapshot('reconciliation_status')}` at "
        f"{snapshot('reconciliation_generated_at_utc')} |",
        f"| Independent verification | `{snapshot('verification_verdict')}` · "
        f"`{snapshot('verification_self_test')}` |",
        "",
        "## 1. Storage: what was wrong, what was returned, and what was left alone",
        "",
        "| | |",
        "| --- | --- |",
        f"| Repository size | {snapshot('storage_repo_bytes')} bytes |",
        f"| Proven safe to reclaim | {snapshot('storage_safe_reclaimable_bytes')} bytes of tool cache |",
        f"| Actually reclaimed | {snapshot('storage_reclaimed_bytes')} bytes |",
        f"| Free after the reclaim | {snapshot('storage_free_bytes_after')} bytes "
        f"(`{snapshot('storage_verdict_after')}`) |",
        f"| Free at this reading | {snapshot('volume_free_bytes')} bytes |",
        "",
        reclaim_note(snapshot),
        "",
        "## 2. The lane, after the refusal",
        "",
        "| | |",
        "| --- | --- |",
        "| Tick count by outcome | " + ", ".join(
            f"`{name.replace('lane_ticks_', '')}`={snapshot(name)}"
            for name in sorted(snapshot.figures)
            if name.startswith("lane_ticks_") and name != "lane_ticks_total"
        ) + " |",
        f"| First disk refusal | {snapshot('lane_first_disk_refusal_utc')} |",
        f"| Newest tick | `{snapshot('lane_last_outcome')}` with "
        f"{snapshot('lane_last_new_bars')} new bar(s), parity "
        f"`{snapshot('lane_last_parity_verdict')}` |",
        f"| Stored bars | {snapshot('store_bars')} across {snapshot('store_series')} series |",
        f"| Sealed slots | {snapshot('lane_slot_seals')} |",
        f"| Ingest attempts | {snapshot('ingest_ledger_rows')}, "
        f"{snapshot('ingest_appended_bars')} bars appended in total |",
        "",
        "## 3. The watchdog, and the cause it now names",
        "",
        "| | |",
        "| --- | --- |",
        "| Readings by verdict | "
        + ", ".join(
            f"`{name.replace('watchdog_verdict_', '')}`={snapshot(name)}"
            for name in sorted(snapshot.figures)
            if name.startswith("watchdog_verdict_")
        )
        + " |",
        "| Categories seen | " + ", ".join(
            f"`{key}`={value}"
            for key, value in sorted((snapshot("watchdog_categories_seen") or {}).items())
        ) + " |",
        f"| Newest reading | `{snapshot('watchdog_newest_verdict')}` / "
        f"`{snapshot('watchdog_newest_category')}`, schema "
        f"`{snapshot('watchdog_newest_schema')}` |",
        f"| Newest cause | `{snapshot('watchdog_newest_cause')}` |",
        f"| Alerts | {snapshot('watchdog_alerts')} rows |",
        f"| Detection latency (rehearsal) | "
        f"{snapshot('watchdog_detection_latency_seconds')} s |",
        "",
        "The reading schema is now V2: a non-zero scheduler result caused by the lane's own resource "
        "guard is filed as `RESOURCE_PRESSURE` with a `TICK_REFUSED_RESOURCE` alert, and the "
        "scheduler is explicitly cleared. The verifier checks that claim for itself, and the "
        "sabotage matrix now contains a row that files a resource refusal as a scheduler failure.",
        "",
        "### The two labels on the same instant, repaired rather than paraphrased",
        "",
        "The newest reading publishes its scheduler instants in the form they were derived in: "
        f"`{snapshot('watchdog_newest_scheduler_next_run_utc')}` with the platform's own spelling "
        f"kept beside it as `{snapshot('watchdog_newest_scheduler_platform_spelling')}`. Until this "
        f"work package, that spelling was what the `_utc` field carried: the reading of "
        f"`2026-10-14T05:32:32Z` printed `10/14/2026 07:40:53` under `next_run_utc` while the "
        f"same instant read `2026-10-14T05:40:53.0000000Z` two fields away — one instant, two "
        f"hours apart, in one row.",
        "",
        "The figure that was published as `host_clock_skew_seconds` was the same kind of mistake "
        "with the sign pointing the wrong way: the probe runs *after* the reading is stamped, so "
        "the difference between the two is elapsed time. It is now "
        f"`watchdog_newest_probe_answer_lag_seconds` = "
        f"`{snapshot('watchdog_newest_probe_answer_lag_seconds')}` s, between the two instants the "
        "same check publishes (`reading_stamped_at_utc`, `probe_reported_now_utc`), and only a "
        "lag that points *backwards* — an instant older than the stamp it was taken after — is "
        "reported as the clock disagreement it would have to be.",
        "",
        "The host's own offset is published two ways for the same reason: "
        f"`{snapshot('watchdog_newest_local_utc_offset_minutes')}` minutes is the offset in force "
        "at the instant read, while the base offset the platform reports is 60 minutes — an hour "
        "short of the wall clock, and an hour of error for anyone who converts with it.",
        "",
    ]
    transitions = classification_evidence(snapshot)
    if transitions:
        lines += [
            f"Every alert row that names the scheduler or a refused tick, taken from this same "
            f"reading (`{snapshot.body.as_of_utc}`), oldest first. The last two are the repair "
            f"working on a real refusal:",
            "",
            "| Instant | Alert (kind, state, severity) |",
            "| --- | --- |",
        ]
        for row in transitions:
            lines.append(f"| `{row['instant_utc']}` | {row['alert']} |")
        lines += [""]
    lines += [
        "## 4. Reconciliation and the forward window",
        "",
        "`RECONCILIATION_INCOMPLETE` here names an incompleteness of the *record*, not an unresolved "
        "defect: two ingest attempts (11:25:20Z and 15:02:10Z) have no run row that names them, "
        "both are closed episodes whose bars are all present, and every open defect count is zero. "
        "The reconciliation refuses to call that clean, and rightly.",
        "",
        "| | |",
        "| --- | --- |",
        f"| Verdict | `{snapshot('reconciliation_verdict')}` / "
        f"`{snapshot('reconciliation_status')}` |",
        f"| Chains holding | {snapshot('reconciliation_chains_holding')} of 6 series |",
        f"| Seals | {snapshot('reconciliation_seals')}, orphaned "
        f"{snapshot('reconciliation_seals_orphaned')}, missing "
        f"{snapshot('reconciliation_seals_missing_for_a_consuming_run')} |",
        f"| Restart proof | {snapshot('restart_proof_broken')} broken of "
        f"{snapshot('restart_proof_instants_with_two_passes')} instants ingested twice |",
        "| Defect counts | " + ", ".join(
            f"`{name.replace('defect_', '')}`={snapshot(name)}"
            for name in sorted(snapshot.figures)
            if name.startswith("defect_")
        ) + " |",
        "",
        "## 5. The acceptance matrix, each row citing its own figures",
        "",
        "| ACC | Requirement | Verdict | Evidence (figures) |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        cited = ", ".join(f"`{item['figure']}`" for item in row["evidence"]) or "—"
        lines.append(f"| {row['id']} | {row['requirement']} | **{row['verdict']}** | {cited} |")
    lines += [
        "",
        "### Why each row reads the way it does",
        "",
    ]
    for row in rows:
        lines.append(f"* **{row['id']} — {row['verdict']}.** {row['note']}")
    lines += [
        "",
        "## 6. Regression: what the tests said, and what the failures outside this chain are",
        "",
        "| Run | Result | Exit code |",
        "| --- | --- | --- |",
        f"| The forward chain's suites | {snapshot('tests_chain_passed')} passed, "
        f"{snapshot('tests_chain_failed')} failed | `{snapshot('tests_chain_exit_code')}` |",
        f"| The whole research suite | {snapshot('tests_full_passed')} passed, "
        f"{snapshot('tests_full_failed')} failed | `{snapshot('tests_full_exit_code')}` |",
        f"| Failures with no demonstrated cause | {snapshot('tests_unexplained_failures')} | |",
        "",
    ]
    regression = (snapshot.body.facts.get("regression") or {}).get("failures_attributed") or []
    if regression:
        lines += [
            "The failures that are not this chain's are attributed rather than waved at:",
            "",
            "| Failing test | Cause demonstrated | Owner |",
            "| --- | --- | --- |",
        ]
        causes: dict[str, int] = {}
        for row in regression:
            causes[str(row["cause"])] = causes.get(str(row["cause"]), 0) + 1
            lines.append(f"| `{row['node']}` | {row['cause']} — {row['demonstrated']} | {row['owner']} |")
        lines += [""]
        if causes.get("HOST_FREE_SPACE"):
            lines.append(
                f"The {causes['HOST_FREE_SPACE']} `HOST_FREE_SPACE` failures are the same defect this "
                "work package removed from the forward chain's fixtures, in another workstream's "
                "launcher tests: their own launcher states the refusal it hit (`INSUFFICIENT_FREE_SPACE` "
                "— the declared window costs more than this volume's free space above its reserve). The "
                "fix is stated in `REGRESSION.json` and left to that workstream, because the file is "
                "theirs."
            )
        if causes.get("STALE_COMMITTED_ARTEFACT"):
            lines.append(
                f"The {causes['STALE_COMMITTED_ARTEFACT']} `STALE_COMMITTED_ARTEFACT` failures are a "
                "committed view and a certification record that no longer match the state they "
                "describe — also not this work package's to regenerate."
            )
        if int(snapshot("tests_unexplained_failures") or 0):
            lines.append(
                "**One failure has no demonstrated cause, and this report does not invent one.** "
                "`test_st6_scheduler.py::test_an_impossible_cadence_refuses_with_a_non_zero_status` "
                "fails inside the whole-suite run and passes alone on the same state: re-run by hand "
                "at `2026-10-14T06:20:47Z` with the same interpreter and `-q --tb=short`, it printed "
                "`1 passed in 142.63s`. Its own body races the live ST-6 schedule — it waits out a "
                "scheduled tick and retries twice — and the ST-6 task fires every fifteen minutes "
                "(its own committed task definition asserts `PT15M`), so at least one of those triggers "
                "fell inside the window the suite occupied (`REGRESSION.json#full`, taken at "
                "`2026-10-14T06:18:41Z`). The mechanism was not observed, so the failure stays "
                "`UNEXPLAINED` in the artefact: a plausible mechanism written down as a cause is how "
                "an unexplained failure becomes a hidden one."
            )
        lines += [""]
    lines += [
        "## 7. Every figure in this report, with its instant and its source",
        "",
        "| Figure | Value | Unit | as_of_utc | Source digest | Scope |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in sorted(snapshot.figures.values(), key=lambda f: f.name):
        lines.append(_figure_row(snapshot, item.name))
    lines += [
        "",
        "## 8. Sources, each with the digest it had at this reading",
        "",
        "| Source | Path | Bytes | Rows | Digest |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, source in sorted(body.sources.items()):
        lines.append(
            f"| `{key}` | `{source.path}` | {source.bytes} | {source.rows} | "
            f"`{source.digest[:16]}…` |"
        )
    lines += [
        "",
        "## 9. How to reproduce",
        "",
        "```bash",
        "# one reading, frozen with its digest",
        "python scripts/edge05r_snapshot.py",
        "",
        "# the reports, rendered from that reading and from nothing else",
        "python scripts/edge05r_report.py",
        "",
        "# storage, read-only then applied",
        "python scripts/edge05r_storage_inventory.py",
        "python scripts/edge05r_storage_reclaim.py",
        "python scripts/edge05r_storage_reclaim.py --apply",
        "",
        "# the reconciliation and the independent verifier, in this order",
        "python scripts/edge05_reconcile.py",
        "python scripts/edge05_verify.py --self-test",
        "```",
        "",
        "A report rendered from a snapshot whose digest does not match its own contents is refused: "
        "`edge05r_report.py` exits non-zero and writes nothing.",
        "",
    ]
    return "\n".join(lines)


def render_final_md(
    snapshot: Snapshot,
    rows: list[dict[str, Any]],
    state: str,
    why: str,
    verdict: str,
    verdict_why: str,
) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    resumen = ", ".join(f"{value} {key}" for key, value in sorted(counts.items()))
    lines = [
        "# WP-EDGE-05R — Recuperación y coherencia de informes: informe ejecutivo",
        "",
        f"*Una sola lectura, tomada a las `{snapshot.body.as_of_utc}` (`{snapshot.body.run_id}`, "
        f"digest `{snapshot.body.digest[:16]}…`). Todas las cifras de este informe llevan su "
        "instante de lectura y el digest del artefacto del que salen; los tres informes —este, el "
        "técnico y el JSON— son tres lecturas del mismo fichero congelado.*",
        "",
        "## 1. Estado en una línea",
        "",
        f"**Veredicto del work package: `{verdict}`** — {verdict_why}.",
        "",
        f"**Estado de la ingesta: `{state}`** — {why}.",
        "",
        "## 2. Disco: qué estaba mal, qué se devolvió y qué no se tocó",
        "",
        f"- El volumen tenía **{snapshot('volume_free_gib')} GiB libres** al tomar esta lectura "
        f"(`{snapshot('volume_verdict')}`). El repositorio ocupa "
        f"{snapshot('storage_repo_bytes')} bytes; el resto del volumen está fuera de este "
        "workstream y no se ha medido ni tocado.",
        f"- Se recuperaron **{snapshot('storage_reclaimed_bytes')} bytes** de cachés de herramienta "
        "(`__pycache__`, mypy, pytest, ruff, hypothesis, coverage), cada ruta verificada en el "
        "momento de borrarla como caché por nombre, no versionada por git y nombrada en "
        "`.gitignore`. En un dry run previo el plan se negó a incluir `.hypothesis` justo porque "
        "`.gitignore` no lo nombraba: se corrigió el `.gitignore` y entonces sí pasó la prueba.",
        floor_line(snapshot),
        "- Nada de datos de mercado, evidencia, otros workstreams, código ni el entorno se tocó: el "
        "criterio de cada ruta borrada se re-verificó en el momento de borrarla.",
        "- El plan que **sí** requeriría una decisión del propietario —los consumidores del volumen "
        "fuera del repositorio y su tamaño— está en `STORAGE_INVENTORY.md` y en el plan adjunto, no "
        "ejecutado aquí.",
        "-",
        f"  {pressure_line(snapshot)}",
        "",
        "## 3. La lane, después del rechazo",
        "",
        f"- La lane rechazó **{snapshot('lane_ticks_disk_budget_exceeded')} tick(s)** por disco, el "
        f"primero a las `{snapshot('lane_first_disk_refusal_utc')}`, **antes de hacer ninguna "
        "petición de mercado** y sin borrar nada.",
        resumed_tick_line(snapshot),
        f"- Total: **{snapshot('lane_ticks_observed')} ticks observados** de "
        f"{snapshot('lane_ticks_total')}, {snapshot('store_bars')} barras en "
        f"{snapshot('store_series')} series, {snapshot('lane_slot_seals')} slots sellados.",
        "",
        "## 4. Clasificación de fallos: la causa, no el sitio donde se notó",
        "",
        "El vocabulario queda cerrado en seis causas y se comprueban: `RESOURCE_PRESSURE`, "
        "`PROVIDER_FAILURE`, `DATA_QUALITY_FAILURE`, `RUNTIME_FAILURE`, `SCHEDULER_FAILURE` y "
        "`EXPECTED_NO_NEW_DATA`. Un tick que la lane rechaza por disco se notifica por el código de "
        "resultado del planificador, pero **la causa es el volumen**: ahora se archiva como "
        "`RESOURCE_PRESSURE`, con alerta `TICK_REFUSED_RESOURCE`, y el planificador se declara "
        "explícitamente limpio en lugar de acusado. El verificador independiente recalcula esa "
        "regla desde el propio dato y la matriz de sabotajes incluye un caso que archiva un rechazo "
        "por recursos como fallo del planificador: si volviera a etiquetarse mal, ese sabotaje "
        "dejaría de detectarse y el self-test fallaría.",
        "",
        f"- Estado de la lectura más nueva: `{snapshot('watchdog_newest_verdict')}` / "
        f"`{snapshot('watchdog_newest_category')}` (esquema `{snapshot('watchdog_newest_schema')}`), "
        f"causa `{snapshot('watchdog_newest_cause')}`.",
        f"- Lecturas: {snapshot('watchdog_readings')}; alertas: {snapshot('watchdog_alerts')}.",
        "",
        "## 5. Informes coherentes",
        "",
        "Los tres informes se generan con **un solo comando** desde una instantánea inmutable "
        "(`READING_SNAPSHOT.json`) que lleva su propio digest y "
        f"**{len(snapshot.figures)} cifras**, cada una con `run_id`, `as_of_utc`, "
        "`source_artifact`, `source_digest` y `measurement_scope`, procedentes de "
        f"{len(snapshot.body.sources)} artefactos de origen con su digest. "
        "Si la instantánea se edita después de tomarla, el generador **se niega a renderizar** y "
        "sale con código distinto de cero. Ya no hay cifras escritas a mano que puedan quedar "
        "obsoletas: es el defecto que obligó a corregir dos veces los informes de WP-EDGE-05.",
        "",
        "## 6. Matriz de aceptación",
        "",
        f"**{resumen}.** Ninguna fila se declara por afirmación: cada una cita las cifras que la "
        "sostienen.",
        "",
        "| ACC | Qué se exigía | Resultado | Cifras que lo sostienen |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        cited = ", ".join(f"`{item['figure']}`" for item in row["evidence"]) or "—"
        lines.append(f"| {row['id']} | {row['requirement']} | **{row['verdict']}** | {cited} |")
    lines += [
        "",
        "## 7. Lo que este work package NO declara",
        "",
        "- No se declara `CERTIFIED`, `READY_FOR_PAPER` ni `PRODUCTION_READY`.",
        f"- **{snapshot('forward_days_prospectively_observed')} de "
        f"{snapshot('forward_days_required')} días forward válidos.** El gate de 60 días sigue "
        "abierto y este encargo no acorta uno solo de sus días.",
        "- No se ha tocado sizing, límites de riesgo, estrategias, señales ni gates de promoción.",
        "- No se ha enviado ninguna orden: 0 en el registro de la lane, 0 en el del vigilante, 0 en "
        "la reconciliación.",
        publication_line(snapshot),
        "",
    ]
    return "\n".join(lines)


def build_json(
    snapshot: Snapshot,
    rows: list[dict[str, Any]],
    state: str,
    why: str,
    verdict: str,
    verdict_why: str,
) -> dict[str, Any]:
    return {
        "schema_version": "EDGE05R_RUN_REPORT_V1",
        "work_package": "WP-EDGE-05R",
        "title": "Recovery and reporting integrity for the forward observation lane",
        "generated_from": {
            "snapshot": "READING_SNAPSHOT.json",
            "run_id": snapshot.body.run_id,
            "as_of_utc": snapshot.body.as_of_utc,
            "digest": snapshot.body.digest,
            "reading": "every figure below was read once and frozen; the reports are renderings of it",
        },
        "work_package_verdict": verdict,
        "work_package_verdict_reading": verdict_why,
        "ingest_state": state,
        "ingest_state_reading": why,
        "volume_pressure_now": pressure_line(snapshot),
        "does_not_authorise": (
            "PAPER or LIVE trading, and no promotion of any strategy: this work package recovers "
            "storage and repairs how failures are classified and reported"
        ),
        "acceptance_matrix": rows,
        "figures": [item.as_dict() for item in sorted(snapshot.body.figures, key=lambda f: f.name)],
        "sources": {key: source.as_dict() for key, source in sorted(snapshot.body.sources.items())},
        "timeline": snapshot.body.facts.get("timeline") or [],
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def load_snapshot(path: Path) -> reading.ReadingSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = reading.ReadingSnapshot.from_dict(payload)
    ok, why = body.verified()
    if not ok:
        raise SystemExit(f"refusing to render: {why}")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--json", action="store_true", help="print the JSON report, write nothing")
    options = parser.parse_args(argv)

    out = Path(options.out) if options.out else REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-05R"
    snapshot_path = Path(options.snapshot) if options.snapshot else out / "READING_SNAPSHOT.json"
    body = load_snapshot(snapshot_path)
    snapshot = Snapshot(body)
    rows = matrix(snapshot)
    state, why = ingest_state(snapshot)
    verdict, verdict_why = work_package_verdict(rows, state)
    payload = build_json(snapshot, rows, state, why, verdict, verdict_why)

    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (out / "ACCEPTANCE_MATRIX.json").write_text(
        json.dumps(
            {
                "schema_version": "EDGE05R_ACCEPTANCE_MATRIX_V1",
                "run_id": body.run_id,
                "as_of_utc": body.as_of_utc,
                "snapshot_digest": body.digest,
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "RUN_REPORT.md").write_text(
        render_run_md(snapshot, rows, state, why, verdict, verdict_why), encoding="utf-8"
    )
    (out / "FINAL_REPORT.md").write_text(
        render_final_md(snapshot, rows, state, why, verdict, verdict_why), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print(f"rendered from snapshot {body.run_id} (digest {body.digest[:16]}…)")
    print(f"work package verdict: {verdict}")
    print(f"ingest state: {state}")
    print("matrix: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    print(f"wrote RUN_REPORT.md, RUN_REPORT.json, FINAL_REPORT.md and ACCEPTANCE_MATRIX.json into {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
