"""prereg_gate — the fail-closed preregistration gate, parameterised by experiment id.

**Where this comes from.** An external preflight package (`EXP-003N_preflight_blocked_20261020`,
2026-10-20) tried to open a new experiment and refused to. Its premise was wrong — it searched a
repository that is not this one, and claimed no dataset digests, no prior runs and no verifier for an
experiment that had already run, been verified and been published under ``reports/ai-bots/``. Its
*mechanism*, however, was the most useful artefact it carried, and it is kept here unchanged in
substance and generalised in one direction only: the identifier it guards is a parameter instead of
the string ``EXP-003N`` written into eleven error codes.

**Why a gate at all.** The expensive mistake in this repository is not a bad backtest; it is a
preregistration that is written *after* the numbers are known and then described as prospective. The
checks below are the ones that make that mistake mechanically detectable rather than a matter of
somebody's word:

* digests of the exact ``raw`` and ``normalized`` bytes, recomputed here, not copied from a report;
* three ordered splits that do not overlap inside an embargo, with timestamps that must be UTC;
* a holdout that may not intersect any window already inspected — the exclusion list lives *in* the
  preregistration, so a later experiment cannot quietly forget it;
* ``BUILDER != VERIFIER``, ``OFFLINE_ONLY``, a sealed holdout, and a prior-runs ledger that must be
  completed and must count zero executions for this identifier;
* an identifier that must not already have a published run directory under ``runs_root`` — a spent
  identifier is the one defect no amount of paperwork repairs;
* in ``authorize`` mode, the manifest, registry and ledger must be *committed*, *clean* and have a
  commit of their own, and the candidate's code commit must be an ancestor of ``HEAD``.

**What it does not do.** It imports nothing from a strategy, a broker, a backtester or an exchange. It
executes no economics and reports ``economic_executions: 0`` for the same reason a smoke alarm does
not put out fires: the gate's only job is to say whether a run may start.

**Exit status is part of the contract.** ``0`` means authorized for one offline economic run and
nothing else. A tidy but unauthorised inspection returns ``3``, never ``0``, so that "the script
exited zero" cannot be quoted as "the experiment was approved". Defects return ``2``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

__all__ = [
    "AUTHORIZED",
    "BLOCKED",
    "GATE_VERSION",
    "INSPECTION_ONLY",
    "REQUIRED_SPLITS",
    "discover_existing_runs",
    "evaluate",
    "git",
    "main",
    "normalise_id",
    "parse_utc",
    "prior_executions",
    "safely_under_repo",
    "sha256_file",
    "validate_split_rules",
]

GATE_VERSION = "PREREG_GATE_V1"

AUTHORIZED = "AUTHORIZED_FOR_SINGLE_OFFLINE_ECONOMIC_RUN"
INSPECTION_ONLY = "INSPECTION_ONLY_NO_RUN"
BLOCKED = "BLOCKED"

REQUIRED_SPLITS = ("discovery", "validation", "holdout")
_FROZEN_STATUSES = ("READY_TO_FREEZE", "FROZEN")
_DECISIONS = {AUTHORIZED: 0, INSPECTION_ONLY: 3, BLOCKED: 2}

HEX64 = re.compile(r"^[0-9a-f]{64}$")
_NON_ID = re.compile(r"[^A-Z0-9]+")

HYPOTHESIS_FIELDS = (
    "null",
    "alternative",
    "candidate_id",
    "candidate_family",
    "candidate_code_commit",
    "baseline_id",
    "baseline_config_path",
    "candidate_config_path",
    "expected_mechanism",
)
DESIGN_FIELDS = (
    "primary_metric",
    "secondary_metrics",
    "statistical_method",
    "bootstrap_seed",
    "bootstrap_iterations",
    "multiple_comparisons_plan",
)
ECONOMICS_FIELDS = (
    "venue",
    "instrument_type",
    "fee_schedule_source",
    "maker_fee_bps_per_side",
    "taker_fee_bps_per_side",
    "slippage_bps_per_side",
    "latency_ms",
    "queue_assumptions",
    "post_only_rejections",
    "partial_fill_policy",
    "unfilled_orders_policy",
    "adverse_selection_model",
    "minimum_notional_usdt",
    "tick_size_source",
    "lot_size_source",
    "max_leverage",
    "max_position_notional_usdt",
    "risk_rejection_policy",
)
ACCEPTANCE_FIELDS = (
    "min_oos_completed_trades",
    "min_oos_trading_days",
    "max_drawdown_usdt",
    "min_profit_factor",
    "stop_conditions",
)
CONTROL_FIELDS = (
    "point_in_time_join_policy",
    "lookahead_test_path",
    "leakage_test_path",
    "future_mutation_test_path",
    "execution_command",
    "builder_identity",
    "independent_verifier_identity",
    "independent_verification_command",
    "preexisting_runs_ledger_path",
    "code_scope_paths",
)
DATASET_FIELDS = (
    "dataset_id",
    "asset",
    "venue",
    "instrument_type",
    "timeframe",
    "provider",
    "source_url",
    "period_start_utc",
    "period_end_utc",
    "raw_file",
    "raw_sha256",
    "normalized_file",
    "normalized_sha256",
    "generator_command",
    "generator_parameters",
    "generator_code_commit",
    "row_count",
)


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    """Digest of the bytes on disk, streamed so a 2 GB archive costs no RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc(value: Any) -> datetime:
    """Parse a timestamp that must say ``Z``.

    A naive ``2026-08-06T00:00:00`` is ambiguous and an offset is not UTC, so both are refused rather
    than silently coerced: a split boundary that shifts by two hours can move a trade across the
    embargo boundary.
    """
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("requires explicit UTC Z timestamp")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return moment


def git(repo: Path, *args: str) -> tuple[bool, str]:
    """Run one read-only git command; returns ``(ok, stdout_or_stderr)``."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    return False, completed.stderr.strip()


def safely_under_repo(repo: Path, raw: Any) -> Path | None:
    """Resolve a declared path only if it lands inside the repository and exists.

    Preregistrations name files. A path that is absolute or escapes the checkout would let the gate
    inspect something the experiment then does not use, so it resolves to ``None`` and is reported as
    a missing path instead of being followed.
    """
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        return None
    root = repo.resolve()
    path = (root / raw).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def normalise_id(experiment_id: str) -> str:
    """``exp-004a`` and ``EXP_004A`` are the same identifier; ``EXP004A`` too."""
    return _NON_ID.sub("_", str(experiment_id).upper()).strip("_")


def discover_existing_runs(
    repo: Path, experiment_id: str, runs_root: str = "reports/ai-bots"
) -> list[str]:
    """Run directories that already belong to this identifier.

    The match is on a *separator boundary*, not on a bare string prefix: ``EXP-004A`` matches
    ``EXP-004A-KELLY-001`` but not ``EXP-004AB-…``, so a neighbour's directory cannot be mistaken for a
    spent identifier and a spent identifier cannot be excused as a neighbour's.
    """
    root = repo / runs_root
    if not root.is_dir():
        return []
    wanted = normalise_id(experiment_id)
    if not wanted:
        return []
    found: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        name = normalise_id(child.name)
        if name == wanted or name.startswith(wanted + "_"):
            found.append(child.name)
    return found


def prior_executions(ledger: Mapping[str, Any], experiment_id: str) -> int:
    """How many runs of this identifier the ledger admits to.

    Three shapes are read so that a ledger cannot pass by being written in the *other* shape: an
    ``executions`` mapping, the legacy ``<slug>_executions`` scalar, and a ``runs`` list. The answer is
    the largest of them, because a ledger that disagrees with itself is not evidence of zero.
    """
    counts: list[int] = []
    wanted = normalise_id(experiment_id)
    executions = ledger.get("executions")
    if isinstance(executions, Mapping):
        for key, value in executions.items():
            if normalise_id(str(key)) == wanted:
                counts.append(_as_count(value))
    for key, value in ledger.items():
        name = str(key)
        if name.lower().endswith("_executions") and normalise_id(name[: -len("_executions")]) == wanted:
            counts.append(_as_count(value))
    runs = ledger.get("runs")
    if isinstance(runs, list):
        matched = 0
        for row in runs:
            if isinstance(row, Mapping) and normalise_id(str(row.get("experiment_id"))) == wanted:
                matched += 1
        counts.append(matched)
    return max(counts) if counts else 0


def _as_count(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    return 1


def validate_split_rules(
    splits: Any, embargo_minutes: Any, holdout_exclusions: Sequence[str]
) -> list[str]:
    """Ordered, non-overlapping splits, and no holdout that has already been looked at."""
    errors: list[str] = []
    if type(embargo_minutes) is not int or embargo_minutes < 0:
        errors.append("SPLIT_EMBARGO_NOT_FROZEN")
        return errors
    periods: list[tuple[str, datetime, datetime]] = []
    for name in REQUIRED_SPLITS:
        block = splits.get(name) if isinstance(splits, Mapping) else None
        if not isinstance(block, Mapping):
            errors.append(f"SPLIT_{name.upper()}_MISSING")
            continue
        try:
            start = parse_utc(block.get("start_utc"))
            end = parse_utc(block.get("end_utc"))
            if start >= end:
                raise ValueError("start >= end")
        except (ValueError, TypeError, AttributeError):
            errors.append(f"SPLIT_{name.upper()}_INVALID_UTC")
            continue
        periods.append((name, start, end))
    periods.sort(key=lambda row: row[1])
    for (_, _, previous_end), (name, current_start, _) in pairwise(periods):
        if previous_end + timedelta(minutes=embargo_minutes) > current_start:
            errors.append(f"SPLIT_{name.upper()}_OVERLAP_OR_EMBARGO")
    for _, start, end in periods:
        for exclusion in holdout_exclusions:
            try:
                first, last = str(exclusion).split("/")
                forbid_start = datetime.fromisoformat(first).replace(tzinfo=UTC)
                forbid_end = datetime.fromisoformat(last).replace(tzinfo=UTC) + timedelta(days=1)
            except (ValueError, TypeError):
                errors.append("INVALID_HOLDOUT_EXCLUSION")
                continue
            if start < forbid_end and end > forbid_start:
                errors.append("REUSED_PREVIOUSLY_INSPECTED_HOLDOUT")
    return errors


def require_fields(obj: Any, path: str, keys: Sequence[str], errors: list[str]) -> None:
    """A field is present only if it says something: ``null``, ``""``, ``[]`` and ``{}`` are absent."""
    if not isinstance(obj, Mapping):
        errors.append(f"{path}.NOT_OBJECT")
        return
    for key in keys:
        value = obj.get(key)
        if value is None or value == "" or (isinstance(value, (list, dict)) and not value):
            errors.append(f"{path}.{key}.MISSING")


def _dataset_file(repo: Path, raw: Any) -> Path | None:
    """Dataset bytes may sit on a read-only volume outside the checkout, but must be a real file."""
    if not isinstance(raw, str) or not raw:
        return None
    path = (Path(raw) if Path(raw).is_absolute() else repo / raw).resolve()
    return path if path.is_file() else None


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
def evaluate(
    *,
    repo: Path,
    experiment_id: str | None = None,
    manifest_path: str = "config/preregistration.json",
    registry_path: str = "config/dataset_registry.json",
    mode: str = "inspect",
    runs_root: str = "reports/ai-bots",
) -> dict[str, Any]:
    """Judge one preregistration. Reads only; never writes into the repository it inspects."""
    if mode not in ("inspect", "authorize"):
        raise ValueError(f"unknown mode {mode!r}")
    repo = Path(repo)
    errors: list[str] = []
    checks: list[str] = []

    def load(relative: str, name: str) -> dict[str, Any]:
        path = safely_under_repo(repo, relative)
        if path is None:
            errors.append(f"{name}_NOT_ACCESSIBLE")
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{name}_INVALID_JSON")
            return {}
        return payload if isinstance(payload, dict) else {}

    manifest = load(manifest_path, "PREREG")
    registry = load(registry_path, "REGISTRY")

    declared = manifest.get("experiment_id")
    requested = experiment_id or declared
    if not isinstance(requested, str) or not requested:
        errors.append("EXPERIMENT_ID_NOT_DECLARED")
        requested = "UNKNOWN"
    for name, doc in (("PREREG", manifest), ("REGISTRY", registry)):
        if doc.get("experiment_id") != requested:
            errors.append(f"EXPERIMENT_ID_MISMATCH_{name}")

    # --- a spent identifier needs no further argument ---------------------- #
    existing = discover_existing_runs(repo, requested, runs_root)
    for name in existing:
        errors.append(f"SPENT_EXPERIMENT_IDENTIFIER:{name}")
    if not existing:
        checks.append(f"IDENTIFIER_UNSPENT:{requested}")

    # --- status ------------------------------------------------------------ #
    if manifest.get("status") not in _FROZEN_STATUSES:
        errors.append("PREREG_NOT_READY_TO_FREEZE")
    if manifest.get("origin") == "reconstructed_from_prior_session_summary_not_runtime":
        checks.append("PREREG_ORIGIN_DECLARED_RECONSTRUCTED")
    if mode == "authorize" and manifest.get("status") != "FROZEN":
        errors.append("PREREG_NOT_FROZEN")

    # --- hypothesis, design, economics, acceptance, controls --------------- #
    hypothesis = manifest.get("hypothesis") or {}
    design = manifest.get("design") or {}
    economics = manifest.get("economics") or {}
    acceptance = manifest.get("acceptance") or {}
    controls = manifest.get("controls") or {}

    require_fields(hypothesis, "hypothesis", HYPOTHESIS_FIELDS, errors)
    require_fields(design, "design", DESIGN_FIELDS, errors)
    require_fields(economics, "economics", ECONOMICS_FIELDS, errors)
    require_fields(acceptance, "acceptance", ACCEPTANCE_FIELDS, errors)
    require_fields(controls, "controls", CONTROL_FIELDS, errors)

    baseline = design.get("baseline")
    if baseline not in (None, "NO_TRADE") and hypothesis.get("baseline_id") != "NO_TRADE":
        errors.append("BASELINE_MISMATCH")
    if design.get("sample_selection_predefined") is not True:
        errors.append("SAMPLE_SELECTION_NOT_PREDEFINED")
    iterations = design.get("bootstrap_iterations")
    if iterations is not None and (type(iterations) is not int or iterations < 1000):
        errors.append("BOOTSTRAP_ITERATIONS_INSUFFICIENT")

    errors.extend(
        validate_split_rules(
            design.get("splits"),
            design.get("embargo_minutes"),
            design.get("holdout_past_consumed_exclusion") or [],
        )
    )
    # An empty exclusion list is indistinguishable from a forgotten one, and the second is how a holdout
    # gets reused without anybody lying. It is allowed only on an explicit assertion that nothing has
    # been consumed yet, which is itself a claim the git history can contradict.
    if not design.get("holdout_past_consumed_exclusion") and (
        controls.get("no_previously_consumed_holdout") is not True
    ):
        errors.append("HOLDOUT_EXCLUSIONS_NOT_DECLARED")

    for key in ("maker_fee_bps_per_side", "taker_fee_bps_per_side", "slippage_bps_per_side", "latency_ms"):
        value = economics.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
        ):
            errors.append(f"INVALID_ECONOMIC_VALUE_{key}")

    for key in ("min_oos_completed_trades", "min_oos_trading_days"):
        value = acceptance.get(key)
        if value is not None and (type(value) is not int or value < 1):
            errors.append(f"INVALID_ACCEPTANCE_{key}")
    if acceptance.get("require_positive_lower_95ci") is not True:
        errors.append("MISSING_POSITIVE_CI_GATE")
    for key in ("reject_if_any_data_lookahead", "reject_on_missing_realistic_costs"):
        if acceptance.get(key) is not True:
            errors.append(f"MISSING_SAFETY_GATE_{key}")

    for key in ("data_time_not_after_decision_time", "no_retune_on_holdout"):
        if controls.get(key) is not True:
            errors.append(f"INVALID_CONTROL_{key}")
    if controls.get("execution_mode") != "OFFLINE_ONLY":
        errors.append("EXECUTION_NOT_OFFLINE_ONLY")
    builder = controls.get("builder_identity")
    if builder is not None and builder == controls.get("independent_verifier_identity"):
        errors.append("BUILDER_EQUALS_VERIFIER")
    if controls.get("holdout_opened") is not False:
        errors.append("HOLDOUT_NOT_SEALED")

    previous = controls.get("previous_results_exist")
    if previous is None:
        for legacy in controls:
            if str(legacy).endswith("_results_exists"):
                previous = controls[legacy]
                break
    if previous is not False:
        errors.append("PREVIOUS_RESULTS_UNRESOLVED_OR_EXISTS")

    # --- paths ------------------------------------------------------------- #
    for field in ("baseline_config_path", "candidate_config_path"):
        if hypothesis.get(field) is not None and safely_under_repo(repo, hypothesis[field]) is None:
            errors.append(f"CONFIG_MISSING_{field}")
    for field in (
        "lookahead_test_path",
        "leakage_test_path",
        "future_mutation_test_path",
        "preexisting_runs_ledger_path",
    ):
        if controls.get(field) is not None and safely_under_repo(repo, controls[field]) is None:
            errors.append(f"EVIDENCE_PATH_MISSING_{field}")

    # --- datasets ---------------------------------------------------------- #
    entries = registry.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("NO_DATASETS_REGISTERED")
    else:
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            name = f"DATASET_{index}"
            if not isinstance(entry, Mapping):
                errors.append(f"{name}_INVALID")
                continue
            require_fields(entry, name, DATASET_FIELDS, errors)
            dataset_id = entry.get("dataset_id")
            if isinstance(dataset_id, str):
                if dataset_id in seen:
                    errors.append("DUPLICATE_DATASET_ID")
                seen.add(dataset_id)
            try:
                start = parse_utc(entry.get("period_start_utc"))
                end = parse_utc(entry.get("period_end_utc"))
                if start >= end:
                    raise ValueError("start >= end")
            except (TypeError, ValueError, AttributeError):
                errors.append(f"{name}_PERIOD_INVALID")
            for prefix in ("raw", "normalized"):
                digest = entry.get(f"{prefix}_sha256")
                path = _dataset_file(repo, entry.get(f"{prefix}_file"))
                if not isinstance(digest, str) or not HEX64.fullmatch(digest):
                    errors.append(f"{name}_{prefix.upper()}_SHA256_MISSING_OR_INVALID")
                    continue
                if path is None:
                    errors.append(f"{name}_{prefix.upper()}_FILE_MISSING")
                elif sha256_file(path) != digest:
                    errors.append(f"{name}_{prefix.upper()}_SHA256_MISMATCH")
                else:
                    checks.append(f"{name}_{prefix.upper()}_SHA256_OK")
            if entry.get("reproduction_status") not in (
                "VERIFIED_INDEPENDENTLY",
                "VERIFIED_LOCALLY",
            ):
                errors.append(f"{name}_PROVENANCE_NOT_VERIFIED")

    # --- the prior-runs ledger --------------------------------------------- #
    ledger_path = controls.get("preexisting_runs_ledger_path")
    ledger_file = safely_under_repo(repo, ledger_path)
    if ledger_file is not None:
        try:
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            errors.append("PRIOR_RUNS_LEDGER_UNREADABLE")
            ledger = {}
        if not isinstance(ledger, Mapping):
            errors.append("PRIOR_RUNS_LEDGER_UNREADABLE")
            ledger = {}
        if ledger.get("experiment_id") != requested:
            errors.append("PRIOR_RUNS_LEDGER_WRONG_EXPERIMENT")
        if ledger.get("inventory_completed") is not True:
            errors.append("PRIOR_RUNS_INVENTORY_NOT_COMPLETED")
        found = prior_executions(ledger, requested)
        if found:
            errors.append(f"PRIOR_RUNS_FOUND_{normalise_id(requested)}_RETROSPECTIVE_ONLY")
        else:
            checks.append(f"NO_PRIOR_RUNS:{requested}")
    for marker in controls.get("previous_run_marker_paths") or []:
        if safely_under_repo(repo, marker) is not None:
            errors.append("EXISTING_RUN_MARKER:" + str(marker))

    # --- git freeze (authorize only) --------------------------------------- #
    if mode == "authorize":
        ok, head = git(repo, "rev-parse", "HEAD")
        if not ok:
            errors.append("GIT_REPOSITORY_NOT_AVAILABLE")
        else:
            checks.append(f"GIT_HEAD={head}")
            frozen = [manifest_path, registry_path]
            if isinstance(ledger_path, str) and ledger_path:
                frozen.append(ledger_path)
            for relative in frozen:
                ok, _ = git(repo, "ls-files", "--error-unmatch", "--", relative)
                if not ok:
                    errors.append(f"GIT_NOT_TRACKED:{relative}")
                    continue
                ok, status = git(repo, "status", "--porcelain", "--", relative)
                if not ok or status:
                    errors.append(f"GIT_DIRTY:{relative}")
                ok, commit = git(repo, "log", "-1", "--format=%H", "--", relative)
                if not ok or not commit:
                    errors.append(f"PREREG_COMMIT_NOT_FOUND:{relative}")
                else:
                    checks.append(f"PREREG_FILE_COMMIT:{relative}:{commit}")
            code_commit = hypothesis.get("candidate_code_commit")
            if code_commit:
                ok, _ = git(repo, "merge-base", "--is-ancestor", str(code_commit), "HEAD")
                if not ok:
                    errors.append("CODE_COMMIT_NOT_ANCESTOR")
            scope = controls.get("code_scope_paths")
            for path in scope if isinstance(scope, list) else []:
                # A scope path that does not exist scopes nothing, and `git status` on it is silent.
                if not (repo / str(path)).exists():
                    errors.append("RUNTIME_CODE_SCOPE_MISSING:" + str(path))
                    continue
                ok, status = git(repo, "status", "--porcelain", "--", str(path))
                if not ok or status:
                    errors.append("RUNTIME_CODE_DIRTY:" + str(path))

    checks.append("OFFLINE_PREFLIGHT_ONLY_NO_ECONOMIC_EXECUTION")
    unique_errors = sorted(set(errors))
    decision = BLOCKED
    if not unique_errors:
        decision = AUTHORIZED if mode == "authorize" else INSPECTION_ONLY
    return {
        "gate_version": GATE_VERSION,
        "experiment_id": requested,
        "mode": mode,
        "decision": decision,
        "exit_code": _DECISIONS[decision],
        "economic_executions": 0,
        "verification_scope": "prereg_and_dataset_preflight_only",
        "errors": unique_errors,
        "checks": sorted(set(checks)),
        "runtime_earning_or_execution_validated": False,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--experiment-id", default=None, help="identifier to guard (default: from manifest)")
    parser.add_argument("--manifest", default="config/preregistration.json")
    parser.add_argument("--registry", default="config/dataset_registry.json")
    parser.add_argument("--mode", choices=("inspect", "authorize"), default="inspect")
    parser.add_argument("--runs-root", default="reports/ai-bots")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    result = evaluate(
        repo=args.repo,
        experiment_id=args.experiment_id,
        manifest_path=args.manifest,
        registry_path=args.registry,
        mode=args.mode,
        runs_root=args.runs_root,
    )
    payload = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    target = args.json_out or args.output
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8", newline="\n")
    for check in result["checks"]:
        print(f"[prereg-gate] OK   {check}")
    for error in result["errors"]:
        print(f"[prereg-gate] FAIL {error}", file=sys.stderr)
    print(
        f"[prereg-gate] {result['decision']} · {result['experiment_id']} · {args.mode} · "
        f"{len(result['errors'])} defect(s) · economic_executions={result['economic_executions']}"
    )
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
