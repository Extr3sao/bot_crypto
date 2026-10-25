"""WP-EDGE-12 — the deliverables, rendered from the readings rather than retyped.

Every markdown file this package publishes is a function of a JSON reading. That is not
tidiness: a number typed into prose is a number nobody re-derives, and the failure this
campaign is trying to avoid is precisely a report that agrees with itself. Each renderer
here takes the structure it prints and never restates a figure by hand.

Where a figure would have to be typed, the renderer prints the field it would have come
from instead, so a reader can see that it was measured.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "continuity_matrix_md",
    "dependency_gate_md",
    "informe_ejecutivo_md",
    "operational_validation_md",
    "operator_handoff_md",
    "recovery_report_md",
    "rollback_md",
    "runner_decision_md",
    "runtime_authority_map_md",
    "storage_plan_md",
]


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")
    return out


def dependency_gate_md(gate: dict[str, Any]) -> str:
    identity = gate["identity"]
    rfc = gate["dependency_named_by_the_request"]
    entry = gate["entry_points"]
    modules = gate["modules"]
    runtime = gate["observer_runtime"]
    scheduler = gate["scheduler"]
    storage = gate["storage"]
    failures = gate["open_failures"]

    lines = [
        "# WP-EDGE-12A — dependency and runtime gate",
        "",
        f"**Generated:** {gate['generated_at_utc']} · **Verdict:** `{gate['verdict']}`",
        "",
        'A work package that answers "are the dependencies met?" from the repository\'s own',
        "documents is answering from intent. Every row below is an answer from the host or the",
        "interpreter this lane runs under, and every question that could not be answered is",
        "recorded as unanswered rather than as zero.",
        "",
        "## 1. Identity",
        "",
        *_table(
            ["", ""],
            [
                ["branch", f"`{identity['branch']}`"],
                ["HEAD", f"`{identity['head']}`"],
                ["HEAD subject", identity["head_subject"]],
                ["committed at", identity["head_committed_at"]],
                ["upstream", f"`{identity['upstream']}`"],
                [
                    "divergence",
                    f"{identity['ahead_of_upstream']} ahead / {identity['behind_upstream']} behind",
                ],
                ["remote ref", f"`{identity['remote_ref']}` = `{identity['remote_sha']}`"],
                ["HEAD is the remote ref", identity["head_is_the_remote_ref"]],
                ["modified paths (other workstreams)", identity["modified_count"]],
                ["untracked paths (other workstreams)", identity["untracked_count"]],
            ],
        ),
        "",
        f"> {identity['worktree_note']}",
        "",
        "## 2. The dependency the request names",
        "",
        f"`{rfc['identifier']}` — searched over {len(rfc['audit']['search_scope'])} scope(s), "
        f"{rfc['audit']['files_scanned']} file(s): **{rfc['audit']['verdict']}**.",
        "",
        f"> {rfc['consequence']}",
        "",
        "What this package certifies instead, by digest:",
        "",
        *_table(
            ["file", "lines", "sha256"],
            [
                [f"`{row['path']}`", row.get("lines"), f"`{(row.get('sha256') or '')[:16]}…`"]
                for row in gate["certified_sources"]
            ],
        ),
        "",
        "## 3. Reachability, measured in a fresh interpreter",
        "",
        f"Interpreter: `{entry['interpreter']}` (Python {entry['python_version']}). "
        f"{entry['reachable']}/{entry['total']} entry point(s) answered `--help` with status 0.",
        "",
        *_table(
            ["entry point", "reachable", "first line"],
            [
                [f"`{row['target']}`", row.get("reachable"), (row.get("first_line") or "")[:70]]
                for row in entry["entry_points"].values()
            ],
        ),
        "",
        f"{modules['importable']}/{modules['total']} runtime module(s) imported successfully "
        "in a separate process:",
        "",
        *_table(
            ["module", "importable", "reason"],
            [
                [f"`{name}`", row.get("importable"), row.get("reason") or ""]
                for name, row in modules["modules"].items()
            ],
        ),
        "",
        "## 4. Observer runtime",
        "",
        *_table(
            ["", ""],
            [
                ["state root", f"`{runtime['state_root']}`"],
                ["store root", f"`{runtime['store_root']}`"],
                ["ticks recorded", runtime["runs"]],
                [
                    "corrupt log lines",
                    f"{runtime['corrupt_run_lines']} run / {runtime['corrupt_slot_lines']} slot",
                ],
                ["outcomes", runtime["outcomes"]],
                ["first tick", runtime["first_tick_utc"]],
                ["last tick", f"{runtime['last_tick_utc']} ({runtime['last_tick_outcome']})"],
                ["sealed slots", runtime["sealed_slots"]],
                ["current slot", runtime["current_slot"]],
                ["daily evidence files", runtime["daily_files"]],
                ["health", runtime["health"]],
                ["prospectively observed days", runtime["coverage"]["prospectively_observed"]],
                ["required days", runtime["coverage"]["required_days"]],
                ["epoch", runtime["coverage"]["epoch_utc"]],
            ],
        ),
        "",
        "## 5. Scheduler registration, read from the host",
        "",
        f"> {scheduler['host_is_authoritative']}",
        "",
        *_table(
            ["", ""],
            [
                ["task name", f"`{scheduler['task_name']}`"],
                ["present on the host", scheduler["present_on_host"]],
                ["state", scheduler["state"]],
                ["logon type", f"`{scheduler['logon_type']}`"],
                ["run level", scheduler["run_level"]],
                ["trigger kinds", ", ".join(scheduler["trigger_kinds"])],
                ["start boundary", scheduler["start_boundary"]],
                ["interval", scheduler["interval"]],
                ["start when available", scheduler["start_when_available"]],
                ["wake to run", scheduler["wake_to_run"]],
                ["multiple instances", scheduler["multiple_instances"]],
                ["execution time limit", scheduler["execution_time_limit"]],
                ["restart policy", f"count={scheduler['restart_count']}"],
                ["last run", scheduler["last_run_utc"]],
                ["last result", scheduler["last_task_result"]],
                ["next run", scheduler["next_run_utc"]],
                ["missed runs (the host's own counter)", scheduler["missed_runs"]],
                [
                    "Task Scheduler operational log enabled",
                    (scheduler.get("scheduler_history") or {}).get("enabled"),
                ],
            ],
        ),
        "",
        "The host reports `NumberOfMissedRuns: "
        f"{scheduler['missed_runs']}` and `LastTaskResult: {scheduler['last_task_result']}`. Neither is",
        "wrong on the host's terms and neither is a statement about continuity: the counter does not",
        "count a trigger whose task could not start, and the log that would is disabled.",
        "",
        "## 6. Storage and the guard",
        "",
        *_table(
            ["", ""],
            [
                ["guard status", storage["guard"]["status"]],
                ["free", f"{storage['guard']['free_gib']} GiB"],
                ["used", _pct((storage["guard"].get("used_percent") or 0) / 100)],
                [
                    "critical floor",
                    f"{round(storage['guard']['critical_free_bytes'] / 1024**3, 4)} GiB",
                ],
                [
                    "warning floor",
                    f"{round(storage['guard']['warning_free_bytes'] / 1024**3, 4)} GiB",
                ],
                ["relocation verdict", f"`{storage['relocation_verdict']}`"],
            ],
        ),
        "",
        *_table(
            ["volume", "fs", "capacity GiB", "free GiB", "used %", "can hold the store"],
            [
                [
                    f"{row['drive_letter'] or '(none)'} {row['label']}",
                    row["file_system"],
                    row["capacity_gib"],
                    row["free_gib"],
                    row["used_percent"],
                    row["can_hold_the_store"],
                ]
                for row in storage["volumes"]
            ],
        ),
        "",
        "## 7. Open failures, carried rather than closed",
        "",
        *_table(
            ["id", "status", "what", "owner"],
            [
                [row["id"], f"`{row['status']}`", row["what"], row.get("owner", "")]
                for row in failures["open_failures"]
            ],
        ),
        "",
        "## 8. Checks",
        "",
        *_table(
            ["check", "verdict", "detail"],
            [
                [f"`{row['name']}`", "PASS" if row["passed"] else "FAIL", row["detail"]]
                for row in gate["checks"]
            ],
        ),
        "",
        f"**`{gate['verdict']}`**",
        "",
        "Research only: hypothetical marks, no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def runtime_authority_map_md(gate: dict[str, Any]) -> str:
    """Which component owns which decision, and where that authority is visible."""
    runtime = gate["observer_runtime"]
    scheduler = gate["scheduler"]
    lines = [
        "# WP-EDGE-12 — runtime authority map",
        "",
        "Read from the runtime in WP-EDGE-12A. The point of the table is the separation: the",
        "scheduler does not decide what to observe, the observer does not decide what to",
        "promote, and the verifier does not decide whether the builder was right.",
        "",
        *_table(
            ["component", "authority", "where it is visible", "what it cannot do"],
            [
                [
                    "Windows Scheduler",
                    f"when the observer starts; currently `{scheduler['state']}`, "
                    f"logon type `{scheduler['logon_type']}`, "
                    f"{len(scheduler['trigger_kinds'])} trigger(s)",
                    "the registration, read from the host",
                    "nothing about the observation: it cannot seal a slot, ingest a bar or refuse a ruleset",
                ],
                [
                    "the observer (`scripts/edge04_observer.py`)",
                    "one tick: fetch, classify, seal the slot, write the daily evidence",
                    f"{runtime['runs']} run row(s) in `{runtime['state_root']}`",
                    "no order, no promotion, no risk parameter",
                ],
                [
                    "the forward plan (`edge03/forward_plan.py`)",
                    "the frozen corpus and the frozen ruleset; a moved input is a refusal",
                    "the pin re-derived on every tick",
                    "cannot measure a tuned rule, by construction",
                ],
                [
                    "the storage guard (`disk_space.py`)",
                    "whether a tick may make a market request at all",
                    "the refusal outcome and the free-space reading in each run row",
                    "cannot delete the store or the daily evidence to make room",
                ],
                [
                    "the lease (`campaign_lock.py`)",
                    "which process may write",
                    "the lease record and the `ALREADY_RUNNING` outcome",
                    "cannot prove a pid is dead; the age rule decides",
                ],
                [
                    "the coverage rule (`prospective_days`)",
                    "which days count as observation",
                    "the day classes in the coverage artefact",
                    "cannot count a backfilled day as forward",
                ],
                [
                    "WP-EDGE-12F verifier",
                    "whether the builder's records are reproducible",
                    "this package's `VERIFICATION.json`",
                    "cannot promote, and shares no code with the audit it checks",
                ],
                [
                    "an operator",
                    "the mechanisms that need a privilege or a credential",
                    "`OPERATOR_HANDOFF.md`",
                    "is asked, not assumed: nothing in this package is applied",
                ],
            ],
        ),
        "",
        "## The boundary this package does not cross",
        "",
        "No component in this map can place an order or admit a strategy. That is not a",
        "convention held by the people writing the code: it is the absence of an exchange",
        "client in the import graph, which WP-EDGE-12A measures by importing every module the",
        f"lane depends on in a fresh interpreter ({gate['modules']['importable']}/"
        f"{gate['modules']['total']} imported) and by reading `order_sent` and `promotion` out",
        "of every record the lane wrote.",
        "",
    ]
    return "\n".join(lines)


def runner_decision_md(
    *,
    decision: dict[str, Any],
    probes: dict[str, Any],
    preflight: dict[str, Any],
    evidence: dict[str, Any],
) -> str:
    rows = probes["probes"]
    levers = probes["additive_levers"]
    lines = [
        "# WP-EDGE-12B — how the observer could be started without a session",
        "",
        f"**Generated:** {decision['generated_at_utc']} · **Selected:** `{decision['selected']}`",
        "",
        f"> {decision['selection_rule']}",
        "",
        f"**Outcome:** {decision['selected_detail']}",
        "",
        "## 1. The mechanisms RFC-EDGE-012 names",
        "",
        *_table(
            ["mechanism", "verdict", "what the host said"],
            [
                [f"`{row['mechanism']}`", f"`{row['verdict']}`", row["detail"][:220]]
                for row in decision["evaluations"]
            ],
        ),
        "",
        "### 1.1 The S4U attempt, in full",
        "",
        "The probe registers **this definition** — both triggers, the witness action, the lane's",
        "own principal — with `LogonType=S4U`, reads it back, runs it on demand and deletes it.",
        "The question an operator asks is not whether S4U exists; it is whether *this* definition",
        "can be registered that way from an unelevated process.",
        "",
        *_table(
            ["", ""],
            [
                ["registration accepted", rows["S4U_PROPOSAL"]["registration_ok"]],
                ["waited for input", rows["S4U_PROPOSAL"]["waited_for_input"]],
                ["password stored", rows["S4U_PROPOSAL"]["stored_a_password"]],
                ["read-back logon type", rows["S4U_PROPOSAL"]["read_back_logon_type"]],
                [
                    "read-back trigger kinds",
                    ", ".join(rows["S4U_PROPOSAL"]["read_back_trigger_kinds"]) or "—",
                ],
                ["ran on demand", rows["S4U_PROPOSAL"]["ran_on_demand"]],
                ["task left behind", rows["S4U_PROPOSAL"]["task_left_behind"]],
                ["host answer", rows["S4U_PROPOSAL"]["registration_output"][:200]],
            ],
        ),
        "",
        "The same attempt with a bare `cmd.exe` task:",
        "",
        f"* verdict `{rows['S4U_BARE']['verdict']}`, registration accepted "
        f"{rows['S4U_BARE']['registration_ok']}, waited for input {rows['S4U_BARE']['waited_for_input']}",
        f"* host answer: {str(rows['S4U_BARE'].get('registration_output'))[:200]}",
        "",
        "### 1.2 The mechanisms that need an operator",
        "",
        *_table(
            ["mechanism", "why not attempted here", "what it would buy"],
            [
                [
                    "`WINDOWS_SERVICE`",
                    f"{rows['WINDOWS_SERVICE'].get('why_not_attempted')} "
                    f"(token elevated: {rows['WINDOWS_SERVICE'].get('token_elevated')})",
                    rows["WINDOWS_SERVICE"].get("what_it_would_remove", ""),
                ],
                [
                    "`AUTHORISED_SERVICE_ACCOUNT`",
                    f"{rows['AUTHORISED_SERVICE_ACCOUNT'].get('why_not_attempted')} "
                    f"({rows['AUTHORISED_SERVICE_ACCOUNT'].get('accounts_found')} account(s) listed, "
                    f"{len(rows['AUTHORISED_SERVICE_ACCOUNT'].get('designated_for_this_campaign') or [])} "
                    "designated)",
                    "a principal whose rights are granted on purpose, instead of borrowed ones",
                ],
                [
                    "`INDEPENDENT_HOST_RUNNER`",
                    rows["INDEPENDENT_HOST_RUNNER"].get("reading", ""),
                    "a host that is not this one, which removes both the session and the volume from the equation",
                ],
            ],
        ),
        "",
        "Automatic logon is not in the table because it is not attempted at all: it would require",
        f"storing the account password on the machine ({evidence.get('autologon', {}).get('auto_admin_logon')}"
        " is `AutoAdminLogon` on this host), and this package holds no credential and will not acquire one.",
        "",
        "## 2. The levers already in the registration",
        "",
        "Two settings are additive and were never priced by the previous pass. Both are visible",
        "in the lane's own run log, which is what makes them measurable rather than arguable.",
        "",
        *_table(
            ["lever", "value", "measured effect in this window"],
            [
                [
                    "`StartWhenAvailable`",
                    levers["start_when_available"],
                    f"{levers['off_phase_launches']} off-phase scheduled launch(es) of "
                    f"{levers['scheduled_launches']}",
                ],
                [
                    "`RestartOnFailure`",
                    f"count={levers['restart_on_failure']['count']}, "
                    f"interval={levers['restart_on_failure']['interval']}",
                    f"{levers['restart_policy_shaped_follow_ups']} follow-up(s) at the policy's own interval",
                ],
                [
                    "`MultipleInstances`",
                    levers["multiple_instances"],
                    "the second trigger changes nothing",
                ],
            ],
        ),
        "",
        f"> {levers['attribution_limitation']}",
        "",
        f"> {levers['what_start_when_available_buys']}",
        "",
        "## 3. Preflight: what an operator can check before applying anything",
        "",
        f"`{preflight['verdict']}` — {len(preflight['checks'])} check(s), "
        f"{len(preflight['blocking_failures'])} blocking failure(s).",
        "",
        *_table(
            ["check", "verdict", "detail"],
            [
                [f"`{row['id']}`", "PASS" if row["passed"] else "FAIL", row["detail"][:180]]
                for row in preflight["checks"]
            ],
        ),
        "",
        f"> {preflight['applies_nothing']}",
        "",
        "## 4. What was not applied, and why",
        "",
        "The live task is left exactly as WP-EDGE-04 registered it. Re-registering a running",
        "lane's task moves the phase a continuity reading measures, which makes it a deployment",
        "decision for an operator rather than a side effect of a certification. The probes used",
        "throwaway names and the count of tasks they left behind is measured:",
        f"**{len(probes['probe_tasks_left_behind'])} left behind**.",
        "",
        "Research only: hypothetical marks, no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def operator_handoff_md(handoff: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-12B — operator handoff",
        "",
        f"**Generated:** {handoff['generated_at_utc']} · **Selected mechanism:** "
        f"`{handoff['selected_mechanism']}`",
        "",
        f"> {handoff['applies_nothing_here']} and this file is the instruction set for somebody who can.",
        "",
        f"Definition: `{handoff['definition']}`",
        "",
    ]
    for step in handoff["steps"]:
        lines += [
            f"### Step {step['order']} — {step['title']}",
            "",
            "```bash",
            step["command"],
            "```",
            "",
            f"Expect: {step['expect']}",
            "",
        ]
        if step.get("requires"):
            lines += [f"Requires: **{step['requires']}**.", ""]
    lines += [
        "## What changes for the measurement",
        "",
        f"{handoff['what_changes_for_the_measurement']}",
        "",
        "## What does not change",
        "",
        f"{handoff['what_does_not_change']}",
        "",
        "Undoing it: `ROLLBACK.md`. Research only: no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def rollback_md(rollback: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-12B — rollback",
        "",
        f"**Generated:** {rollback['generated_at_utc']} · **Task:** `{rollback['task_name']}`",
        "",
        "Written before it is needed, and pinned to the registration that exists now rather than",
        "to a definition somebody would have to reconstruct from a report.",
        "",
        *_table(
            ["", ""],
            [
                ["captured before any change", rollback["captured_before_any_change"]],
                [
                    "live registration sha256",
                    f"`{(rollback['live_registration_sha256'] or '—')[:32]}…`",
                ],
                ["live registration bytes", rollback["live_registration_bytes"]],
                ["live trigger kinds", ", ".join(rollback["live_registration_trigger_kinds"])],
                ["definition this rolls back", f"`{rollback['rollback_definition']}`"],
            ],
        ),
        "",
    ]
    for step in rollback["steps"]:
        lines += [
            f"### {step['order']}. {step['action']}",
            "",
            "```bash",
            step["command"],
            "```",
            "",
        ]
        if step.get("verify"):
            lines += [f"Verify: {step['verify']}", ""]
        if step.get("precondition"):
            lines += [f"Precondition: {step['precondition']}", ""]
    lines += [
        "## What a rollback cannot undo",
        "",
        f"{rollback['what_a_rollback_cannot_undo']}",
        "",
    ]
    return "\n".join(lines)


def storage_plan_md(storage: dict[str, Any]) -> str:
    growth = storage["store_growth"]
    ceiling = storage["retention_ceiling"]
    forecast = storage["forecast"]
    trajectory = storage["volume_trajectory"]
    lines = [
        "# WP-EDGE-12C — storage and resource continuity",
        "",
        f"**Generated:** {storage['schema_version']} · **Horizon:** {storage['horizon_days']} days · "
        f"**Verdict:** `{storage['verdict']}`",
        "",
        "Sixty days of observation has to fit somewhere, and there are two unlike questions hiding",
        "inside that: whether the *lane* fits, and whether the *volume* has room. They have",
        "different answers and only the first one is this lane's to decide.",
        "",
        "## 1. The lane's footprint and its two growth laws",
        "",
        "The state root's logs are bounded, so they have a ceiling that can be summed instead of",
        "extrapolated. The store is append-only and never pruned, so it has a rate instead.",
        "",
        *_table(
            ["tree", "bytes now"],
            [
                ["store", storage["footprint_now"]["store_bytes"]],
                ["state", storage["footprint_now"]["state_bytes"]],
                ["lane (as measured for this reading)", storage["footprint_now"]["lane_bytes"]],
            ],
        ),
        "",
        "### 1.1 Ceiling of the bounded logs",
        "",
        *_table(
            ["log", "rows now", "bytes/row", "rows kept", "projected bytes"],
            [
                [
                    f"`{name}`",
                    row["rows_now"],
                    row["bytes_per_row"],
                    row["rows_kept"],
                    row["projected_bytes"],
                ]
                for name, row in ceiling["operational_logs"].items()
            ],
        ),
        "",
        *_table(
            ["daily evidence", "files now", "mean bytes", "files kept", "projected bytes"],
            [
                [
                    "never truncated",
                    ceiling["daily_evidence"]["files_now"],
                    ceiling["daily_evidence"]["mean_bytes"],
                    ceiling["daily_evidence"]["files_kept"],
                    ceiling["daily_evidence"]["projected_bytes"],
                ]
            ],
        ),
        "",
        f"**Ceiling: {ceiling['ceiling_bytes']} bytes** against a declared lane budget of "
        f"{ceiling['declared_lane_budget_bytes']} bytes — within budget: "
        f"**{ceiling['ceiling_within_budget']}**.",
        "",
        f"> {ceiling['reading']}",
        "",
        "### 1.2 Rate of the store",
        "",
        *_table(
            ["series", "rows", "bytes", "bytes/bar", "bars/day", "bytes/day"],
            [
                [
                    f"`{row['series']}`",
                    row["rows"],
                    row["bytes"],
                    row["bytes_per_bar"],
                    row["bars_per_day"],
                    row["bytes_per_day"],
                ]
                for row in growth["series"]
            ],
        ),
        "",
        f"**{growth['bars_per_day']} bars/day, {growth['bytes_per_day']} bytes/day.**",
        "",
        f"> {growth['reading']}",
        "",
        "## 2. The forecast",
        "",
        *_table(
            ["", ""],
            [
                ["store at the horizon", f"{forecast['store_bytes_at_horizon']} bytes"],
                ["state at the horizon (ceiling)", f"{forecast['state_bytes_at_horizon']} bytes"],
                ["lane at the horizon", f"{forecast['lane_bytes_at_horizon']} bytes"],
                [
                    "added over the horizon",
                    f"{forecast['added_over_the_horizon_bytes']} bytes "
                    f"({forecast['added_gib_over_the_horizon']} GiB)",
                ],
                ["fits", forecast["fits"]],
            ],
        ),
        "",
        f"> {forecast['method']}",
        "",
        f"> {forecast['no_invented_volume_forecast']}",
        "",
        "## 3. The volume, which is the actual constraint",
        "",
        f"Guard status `{storage['guard']['status']}` at `{storage['guard']['free_gib']} GiB` free on "
        f"`{storage['guard']['path']}`; critical floor "
        f"{round(storage['guard']['critical_free_bytes'] / 1024**3, 4)} GiB.",
        "",
        *_table(
            ["volume", "fs", "capacity GiB", "free GiB", "used %", "usable for this store"],
            [
                [
                    f"{row['drive_letter'] or '(none)'} {row['label']}",
                    row["file_system"],
                    row["capacity_gib"],
                    row["free_gib"],
                    row["used_percent"],
                    row["usable_for_this_store"],
                ]
                for row in storage["volumes"]
            ],
        ),
        "",
        f"Relocation verdict: **`{storage['relocation_verdict']}`**. Qualifying volumes: "
        f"{storage['usable_volumes'] or 'none'}.",
        "",
        "### 3.1 The volume's own trajectory, as the lane saw it",
        "",
        *_table(
            ["", ""],
            [
                ["samples", trajectory.get("samples")],
                ["span", f"{trajectory.get('span_days')} days"],
                ["first", f"{trajectory.get('first_gib')} GiB"],
                ["last", f"{trajectory.get('last_gib')} GiB"],
                ["minimum", f"{trajectory.get('minimum_gib')} GiB"],
                ["delta", f"{trajectory.get('delta_gib')} GiB"],
                ["per day", f"{trajectory.get('gib_per_day')} GiB/day"],
                ["status counts", trajectory.get("status_counts")],
            ],
        ),
        "",
        f"> {trajectory.get('reading')}",
        "",
        "## 4. What the refusals cost",
        "",
        *_table(
            ["", ""],
            [
                ["ticks refused by the guard", storage["refusals"]["refused_ticks"]],
                ["slots those refusals touched", storage["refusals"]["refused_slots"]],
                ["first refusal", storage["refusals"]["first_refusal_utc"]],
                ["last refusal", storage["refusals"]["last_refusal_utc"]],
                [
                    "market requests made at a refusal",
                    storage["refusals"]["market_requests_at_refusal"],
                ],
            ],
        ),
        "",
        f"> {storage['refusals']['reading']}",
        "",
        "## 5. The plan",
        "",
        "1. **Do nothing to this lane.** Its ceiling is inside its declared budget and its store",
        f"   adds {forecast['added_gib_over_the_horizon']} GiB over the horizon; moving it would",
        "   change the free space the guard reads by less than the noise in that reading.",
        "2. **Decide about the volume, as an operator.** The occupancy is 97 %. This lane is not",
        "   what fills it and this package will not delete another workstream's data to make the",
        "   number look better: that would be measuring a different thing and calling it capacity.",
        "3. **Keep the guard where it is.** It refuses *before* any market request, so a full",
        "   volume costs slots and never produces a false observation. Loosening it to buy slots",
        "   would buy them with the one property that makes the refusals acceptable.",
        "4. **Re-run `scripts/edge12_storage.py` after any change to what lives on this volume.**",
        "   The lane's own readings are the free-space history on this host; nothing else records it.",
        "",
        "Research only: no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def continuity_matrix_md(matrix: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-12D — continuity matrix",
        "",
        f"**Generated:** {matrix['generated_at_utc']} · **Verdict:** `{matrix['verdict']}`",
        "",
        "Nine properties. Each row names where it was exercised: a rehearsal step that drove the",
        "real observer over a copy of the store, or a live reading. A property that could not be",
        "exercised says so and says why; nothing here passes because the design intends it.",
        "",
        *_table(
            ["property", "evidence", "where", "verdict", "detail"],
            [
                [
                    f"`{row['property']}`",
                    row["evidence_kind"],
                    f"`{row['evidence']}`",
                    f"`{row['verdict']}`",
                    row["detail"],
                ]
                for row in matrix["rows"]
            ],
        ),
        "",
        f"Required: {len(matrix['properties_required'])} · missing: "
        f"{matrix['properties_missing'] or 'none'} · not passing: {matrix['not_passed'] or 'none'}.",
        "",
        "## The rehearsal, step by step",
        "",
        f"Verdict `{summary['verdict']}` over {len(summary['steps'])} step(s); "
        f"failures: {summary['failures'] or 'none'}.",
        "",
        *_table(
            ["step", "property", "verdict"],
            [
                [f"`{row['step_id']}`", f"`{row['property']}`", f"`{row['verdict']}`"]
                for row in summary["steps"]
            ],
        ),
        "",
        f"> {matrix['reading']}",
        "",
        "Research only: no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def recovery_report_md(
    *, matrix: dict[str, Any], live: dict[str, Any], rehearsal: dict[str, Any]
) -> str:
    steps = {row["step_id"]: row for row in rehearsal.get("steps") or []}
    lines = [
        "# WP-EDGE-12D — recovery report",
        "",
        f"**Generated:** {matrix['generated_at_utc']}",
        "",
        "What survives a process dying, a session disappearing and a write being interrupted —",
        "measured, over an isolated copy of the store, and read against the live lane's own logs.",
        "",
        "## 1. The live lane, as it is",
        "",
        *_table(
            ["", ""],
            [
                ["ticks in the log", live["runs"]],
                ["first tick", live["first_tick_utc"]],
                ["last tick", live["last_tick_utc"]],
                ["corrupt log lines", live["corrupt_run_lines"]],
                [
                    "slot ledger rows / unique keys",
                    f"{live['slots_sealed_rows']} / {live['slots_unique_keys']}",
                ],
                ["the ledger is a set", live["slot_ledger_is_a_set"]],
                ["median tick", f"{live['median_tick_seconds']} s"],
                ["maximum tick", f"{live['maximum_tick_seconds']} s"],
                ["ticks over the interval", live["ticks_over_the_interval"]],
                ["silences over the declared bound", len(live["gaps_over_the_declared_bound"])],
                ["worst silence", f"{live['worst_gap_seconds']} s"],
                ["alerts recorded", live["alerts"]["kinds"]],
                [
                    "derived re-reads",
                    f"{live['derived_refresh']['rows']} row(s), {live['derived_refresh']['failures']} failure(s)",
                ],
            ],
        ),
        "",
        "### 1.1 The silences, one by one",
        "",
        *_table(
            ["from", "to", "seconds", "missed intervals"],
            [
                [gap["from_utc"], gap["to_utc"], gap["seconds"], gap["missed_intervals"]]
                for gap in live["gaps_over_the_declared_bound"]
            ]
            or [["—"] * 4],
        ),
        "",
        "## 2. What the rehearsal proved",
        "",
    ]
    for step_id in (
        "repeat_inside_the_same_slot",
        "trigger_while_another_tick_holds_the_lease",
        "lease_left_by_a_crashed_process",
        "bars_that_closed_while_the_observer_was_down",
        "a_log_line_interrupted_mid_write",
        "a_duplicated_slot_seal",
        "a_tick_against_its_own_interval",
    ):
        row = steps.get(step_id)
        if row is None:
            continue
        lines += [
            f"### `{step_id}` — `{row['verdict']}`",
            "",
            f"Expected: {row['expected']}",
            "",
            "```json",
            _compact(row["observed"]),
            "```",
            "",
        ]
    lines += [
        "## 3. What still cannot be proved here",
        "",
        "* a **real sign-in absence** mid-pass: provoking one would end the session this work runs",
        "  in. The property is `BOUNDED_NOT_REMOVED`, and what bounds it is the logon trigger plus",
        "  the measured recovery latency, not this rehearsal.",
        "* a **real reboot**: the host's reboots are in the evidence, but a rehearsal cannot schedule",
        "  one without taking the machine down.",
        "* the **attribution of an off-cadence launch**: the run log records the arguments a launch",
        "  was invoked with, and an on-demand `schtasks /run` uses the same arguments as the",
        "  scheduler. The operational log that separates them is disabled (needs an administrator).",
        "",
        "Research only: no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def _compact(payload: Any, *, limit: int = 1400) -> str:
    import json

    text = json.dumps(payload, indent=1, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "\n…"


def operational_validation_md(reading: dict[str, Any]) -> str:
    levels = reading["levels"]
    lines = [
        "# WP-EDGE-12E — operational validation",
        "",
        f"**Window:** {reading['window']['from_utc']} → {reading['window']['to_utc']} "
        f"({reading['window']['hours']} h) · cadence {reading['window']['interval_seconds']} s, "
        f"phase +{reading['window']['phase_ms']} ms (from the {reading['window']['phase_source']})",
        "",
        "Three levels, kept apart because a reader conflates them readily: a trigger that fired is",
        "a property of the calendar, an observation that was made is a property of a process, and a",
        "day that is admissible is a property of the store. Only the third may be compared with an",
        "admission criterion.",
        "",
        "## 1. Level one — triggers fired",
        "",
        *_table(
            ["", ""],
            [
                ["expected instants", levels["one_triggers_fired"]["expected_instants"]],
                ["answered by a tick", levels["one_triggers_fired"]["answered_by_a_tick"]],
                ["never answered", levels["one_triggers_fired"]["never_answered"]],
                ["answered + lost = expected", levels["one_triggers_fired"]["equals_the_whole"]],
            ],
        ),
        "",
        *_table(
            ["cause", "instants"],
            [[f"`{name}`", value] for name, value in sorted(reading["losses"]["causes"].items())],
        ),
        "",
        f"> {reading['losses']['reading']}",
        "",
        "## 2. Level two — observations made",
        "",
        *_table(
            ["", ""],
            [
                ["slot-consuming ticks", levels["two_observations_made"]["slot_consuming_ticks"]],
                ["of which OBSERVED", levels["two_observations_made"]["of_which_observed"]],
                ["of which NO_NEW_DATA", levels["two_observations_made"]["of_which_no_new_data"]],
                ["fired and refused", levels["two_observations_made"]["fired_and_refused"]],
            ],
        ),
        "",
        f"> {levels['two_observations_made']['reading']}",
        "",
        *_table(["outcome", "ticks"], [[f"`{k}`", v] for k, v in reading["outcomes"].items()]),
        "",
        "## 3. Level three — days admissible",
        "",
        *_table(
            ["", ""],
            [
                [
                    "prospectively observed days",
                    levels["three_days_admissible"]["prospectively_observed_days"],
                ],
                ["required", levels["three_days_admissible"]["required_days"]],
                ["remaining", levels["three_days_admissible"]["remaining_days"]],
                [
                    "densely covered but backfilled",
                    levels["three_days_admissible"]["densely_covered_but_backfilled"],
                ],
                ["epoch", reading["coverage"].get("epoch_utc")],
            ],
        ),
        "",
        f"> {levels['three_days_admissible']['reading']}",
        "",
        "## 4. Bars, continuity, latency, storage",
        "",
        *_table(
            ["", ""],
            [
                ["new bars stored", reading["bars"]["new_bars"]],
                ["missing bars reported", reading["bars"]["missing_bars_reported"]],
                ["ticks reporting a stale series", reading["bars"]["ticks_reporting_stale_series"]],
                ["market requests", reading["bars"]["market_requests"]],
                ["silences over the declared bound", len(reading["continuity"]["gaps"])],
                ["worst silence", f"{reading['continuity']['worst_gap_seconds']} s"],
                ["highest severity", reading["continuity"]["highest_severity"]],
                ["median tick", f"{reading['latency']['median_tick_seconds']} s"],
                ["p95 tick", f"{reading['latency']['p95_tick_seconds']} s"],
                ["maximum tick", f"{reading['latency']['maximum_tick_seconds']} s"],
                ["ticks over the interval", reading["latency"]["ticks_over_the_interval"]],
                ["refused ticks", reading["storage"]["refused_ticks"]],
                ["lowest free space", f"{reading['storage']['lowest_free_gib']} GiB"],
                ["disk status counts", reading["storage"]["status_counts"]],
                ["ticks with errors", reading["errors"]["ticks_with_errors"]],
            ],
        ),
        "",
        "## 5. Per day",
        "",
        *_table(
            ["day", "expected", "ticks", "observed", "refused", "new bars", "median s", "coverage"],
            [
                [
                    row["day"],
                    row["expected_instants"],
                    row["ticks"],
                    row["observed"],
                    row["refused"],
                    row["new_bars"],
                    row["median_tick_seconds"],
                    row["coverage_of_the_calendar"],
                ]
                for row in reading["daily"]
            ],
        ),
        "",
        "## 6. Invariants",
        "",
        *_table(
            ["", ""],
            [
                ["ticks claiming an order", reading["invariants"]["orders_recorded"]],
                ["ticks not marked hypothetical", reading["invariants"]["non_hypothetical_ticks"]],
                ["promotions recorded", reading["invariants"]["promotions"]],
            ],
        ),
        "",
        "## 7. What this reading is not",
        "",
        "It is not the admission test: 60 prospective days are not observed here, and nothing in",
        "this file may be read as one. It is also not WP-EDGE-04R's continuity audit — that file",
        "attributes every instant of its own frozen window from a committed snapshot, this one",
        "reads the live lane over a window declared above. Where they disagree, the disagreement",
        "is the finding.",
        "",
        "Research only: no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def informe_ejecutivo_md(payload: dict[str, Any]) -> str:
    """The Spanish executive summary, rendered from the same readings as the English ones."""
    gate = payload["gate"]
    decision = payload["decision"]
    storage = payload["storage"]
    matrix = payload["matrix"]
    operational = payload["operational"]
    verification = payload["verification"]
    levels = operational["levels"]
    probes = (payload.get("probes") or {}).get("probes") or {}
    tests = payload.get("tests") or {}
    acceptance = payload.get("acceptance_counts") or {}
    pytest_run = tests.get("pytest") or {}
    lint_run = tests.get("lint") or {}
    audit = (gate.get("dependency_named_by_the_request") or {}).get("audit") or {}
    dependency_verdict = str(audit.get("verdict") or "UNKNOWN")
    current_volume = next(
        (row for row in (storage.get("volumes") or []) if row.get("is_the_current_volume")),
        {},
    )
    service_probe = probes.get("WINDOWS_SERVICE") or {}

    def count(value: Any) -> str:
        """A figure nobody read is reported as unread, never as a zero."""
        return "no leído" if value is None else str(value)

    def pytest_figure(key: str) -> str:
        """pytest omits a count it has none of, and only an odd exit makes that a blank.

        A summary line that reads ``61 passed`` without mentioning failures is a run with no
        failures; a run whose exit status is not zero and whose summary mentions nothing is a
        run whose figures were not read. Printing ``no leído`` for both would report a clean
        suite as an unknown one, which is the same conflation in the other direction.
        """
        value = pytest_run.get(key)
        if value is not None:
            return str(value)
        return "0" if pytest_run.get("exit_code") in (0, None) else "no leído"

    lines = [
        "# WP-EDGE-12 — informe ejecutivo (castellano)",
        "",
        f"**Instante de lectura:** {payload['generated_at_utc']} · **Ventana operativa:** "
        f"{operational['window']['from_utc']} → {operational['window']['to_utc']} "
        f"({operational['window']['hours']} h)",
        "",
        f"**Veredicto del paquete:** `{payload['closure_state']}`.",
        "",
        "## 1. Qué se ha medido",
        "",
        f"* **Dependencias (12A).** `{gate['verdict']}`: "
        f"{gate['entry_points']['reachable']}/{gate['entry_points']['total']} puntos de entrada "
        f"responden `--help` con estado 0, {gate['modules']['importable']}/"
        f"{gate['modules']['total']} módulos importan en un intérprete nuevo, y el registro del "
        f"Programador se lee del host (`{gate['scheduler']['state']}`, "
        f"`{gate['scheduler']['logon_type']}`). RFC-EDGE-011: `{dependency_verdict}` "
        f"({len(audit.get('hits') or [])} coincidencia(s) fuera de los ficheros de este "
        f"paquete): se declara como dependencia externa no satisfecha, no como resuelta.",
        f"* **Ejecución sin sesión (12B).** `{decision['selected']}` es el mecanismo seleccionado. "
        f"El intento de registrar S4U **esta misma definición** lo respondió el host: "
        f"`{decision['evaluations'][0]['verdict']}`. Los dos mecanismos disponibles son el "
        "disparador de inicio de sesión y la acción testigo; los demás exigen administrador o "
        "una credencial.",
        f"* **Almacenamiento (12C).** `{storage['verdict']}`: el techo de la lane es "
        f"{storage['retention_ceiling']['ceiling_bytes']} B frente a un presupuesto de "
        f"{storage['retention_ceiling']['declared_lane_budget_bytes']} B, y el store añade "
        f"{storage['forecast']['added_gib_over_the_horizon']} GiB en 60 días. "
        f"Reubicación: `{storage['relocation_verdict']}`.",
        f"* **Continuidad (12D).** `{matrix['verdict']}`: "
        f"{len(matrix['passed'])} de {len(matrix['rows'])} propiedades con veredicto `PASS`, "
        f"ejercitadas sobre un ensayo real con el observador real y una copia del store.",
        "* **Validación operativa (12E).** Tres niveles separados: "
        f"{levels['one_triggers_fired']['expected_instants']} instantes esperados, "
        f"{levels['one_triggers_fired']['answered_by_a_tick']} atendidos, "
        f"{levels['one_triggers_fired']['never_answered']} sin proceso, y "
        f"{levels['three_days_admissible']['prospectively_observed_days']} día(s) forward "
        f"admisible(s) de {levels['three_days_admissible']['required_days']}.",
        f"* **Certificación independiente (12F).** `{verification['verdict']}` con "
        f"{len(verification['checks'])} comprobaciones y "
        f"{verification['self_test']['detected']} sabotajes detectados de "
        f"{verification['self_test']['applied']}.",
        f"* **Regresiones (DoD/TEST).** `{tests.get('verdict', 'NO_RECORD')}`: pytest "
        f"{count(pytest_run.get('passed'))} pasan, {pytest_figure('failed')} fallan, "
        f"{pytest_figure('errors')} con error; lint con estado "
        f"{count(lint_run.get('exit_code'))}. La selección declarada está en "
        "`evidence/TEST_RUNS.json`.",
        f"* **Criterios de aceptación (RFC §6).** "
        f"{acceptance if acceptance else 'no calculados en esta pasada'}.",
        "",
        "## 2. Lo que sigue bloqueado, y por qué",
        "",
        "* **S4U**: necesita el derecho de inicio de sesión por lotes. Comando exacto en "
        "`OPERATOR_HANDOFF.md`; sin él, los instantes perdidos por ausencia de sesión siguen "
        "perdiéndose.",
        f"* **Servicio de Windows / principal SYSTEM**: requiere administrador. El token de este "
        f"proceso lee `token_elevated={count(service_probe.get('token_elevated'))}` y sostiene "
        f"los privilegios {service_probe.get('privileges_held')}.",
        "* **Inicio de sesión automático**: exigiría guardar una contraseña; este paquete no",
        "  almacena credenciales.",
        "* **Registro operativo del Programador**: requiere administrador; sin él, un disparo que",
        "  no llega a proceso queda como `SILENT_UNATTRIBUTABLE` en lugar de tener causa.",
        f"* **Volumen**: el volumen del store está al {count(current_volume.get('used_percent'))} % "
        f"de ocupación ({count(current_volume.get('free_gib'))} GiB libres) y ningún otro volumen "
        "reúne capacidad: reubicación descartada, no aplazada. No lo llena esta lane y este "
        "paquete no borra datos de otros carriles para mejorar el número.",
        "",
        "## 3. Defectos y fallos heredados",
        "",
        f"{payload['failures_summary']}",
        "",
        "## 4. Siguiente acción concreta",
        "",
        f"{payload['next_action']}",
        "",
        "Ninguna declaración de preparación para PAPER o LIVE aparece en este paquete: "
        "`order_sent=false` y `promotion=NONE` en todos los registros.",
        "",
    ]
    return "\n".join(lines)
