#!/usr/bin/env python
"""Prove that the formatter exemption list is exactly the certified set.

`[tool.ruff.format].exclude` exists for one reason: 24 files are byte-pinned by
committed certification records, so reformatting them invalidates evidence that other
tests re-verify. An exclusion list is a hole in a gate, and holes rot silently: a path
gets renamed, a file is formatted anyway, someone adds a directory glob "just for now",
or somebody disables lint for the same files and the hole doubles.

This script enumerates the ways that hole can widen and fails on every one of them:

1. the configured list and the declared list are the same set (no extras, no gaps);
2. every configured entry is an exact path to an existing file, never a glob or a
   directory, so it cannot quietly cover files nobody audited;
3. no global lint or top-level exclusion was added to compensate;
4. `ruff format --check .` is green;
5. clearing the exclusions makes the formatter flag exactly those 24 files, which
   proves each entry is load-bearing rather than decorative;
6. every exempted file still hashes to the bytes of the base commit;
7. the linter still analyses all 24 (absent from the formatter, not from the linter);
8. no committed certification record under `data/` changed since the base commit.

`--self-test` aims one mutation at each check and requires the check to reject it, so a
check that silently passes everything is itself caught. The mutations never touch the
working tree: the byte check is exercised through an explicit override.

Exit codes: 0 = every check passed, 1 = at least one check failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "wp00308-format-exemptions-audit/1"
DEFAULT_BASE = "1d2192b0"
DEFAULT_DECLARATION = "reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00307/EXEMPTIONS.json"
CONFIG = "pyproject.toml"
GLOB_CHARS = ("*", "?", "[", "]")


@dataclass
class Check:
    """One auditable assertion."""

    name: str
    ok: bool
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "ok": self.ok, "detail": self.detail}
        if self.data:
            payload["data"] = self.data
        return payload


def parse_toml(text: str) -> dict[str, Any]:
    """Parse TOML text, narrowing the parser's untyped result once, here."""
    parsed: dict[str, Any] = tomllib.loads(text)
    return parsed


def _table(config: dict[str, Any], *path: str) -> dict[str, Any]:
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return {}
        node = node[key]
    return node if isinstance(node, dict) else {}


def formatter_exclude(config: dict[str, Any]) -> list[str]:
    raw = _table(config, "tool", "ruff", "format").get("exclude", [])
    return [str(item).replace("\\", "/") for item in raw] if isinstance(raw, list) else []


def declared_exemptions(declaration_file: Path) -> list[str]:
    document: dict[str, Any] = json.loads(declaration_file.read_text(encoding="utf-8"))
    entries = document.get("exemptions", [])
    if not isinstance(entries, list):
        raise TypeError(f"{declaration_file}: 'exemptions' is not a list")
    return sorted(str(item).replace("\\", "/") for item in entries)


def check_config_matches(config: dict[str, Any], declared: Sequence[str]) -> Check:
    configured = sorted(formatter_exclude(config))
    wanted = sorted(declared)
    extra = sorted(set(configured) - set(wanted))
    missing = sorted(set(wanted) - set(configured))
    duplicates = len(configured) - len(set(configured))
    ok = not extra and not missing and duplicates == 0
    detail = (
        f"{len(configured)} configured == {len(wanted)} declared"
        if ok
        else f"extras={extra} missing={missing} duplicates={duplicates}"
    )
    return Check("config_matches_declaration", ok, detail, {"configured": len(configured)})


def check_entries_are_exact_files(
    config: dict[str, Any], root: Path, declared: Sequence[str]
) -> Check:
    problems: list[str] = []
    for entry in formatter_exclude(config):
        if any(char in entry for char in GLOB_CHARS):
            problems.append(f"{entry}: glob, not an exact path")
            continue
        if entry.endswith("/"):
            problems.append(f"{entry}: directory, not a file")
            continue
        if not entry.endswith(".py"):
            problems.append(f"{entry}: not a Python file")
        if not (root / entry).is_file():
            problems.append(f"{entry}: does not exist")
        if entry not in set(declared):
            problems.append(f"{entry}: excluded without a declaration")
    return Check(
        "entries_are_exact_files",
        not problems,
        "every entry is an existing, declared .py file" if not problems else "; ".join(problems),
        {"entries": len(formatter_exclude(config))},
    )


def check_no_global_disable(config: dict[str, Any]) -> Check:
    problems: list[str] = []
    if "exclude" in _table(config, "tool", "ruff"):
        problems.append("top-level [tool.ruff].exclude would hide files from every tool")
    if "exclude" in _table(config, "tool", "ruff", "lint"):
        problems.append("[tool.ruff.lint].exclude would stop the linter seeing the pins")
    raw = _table(config, "tool", "ruff").get("extend-exclude", [])
    extend: list[str] = [str(item) for item in raw] if isinstance(raw, list) else []
    unexpected = [item for item in extend if item != "*.sh"]
    if unexpected:
        problems.append(f"unexpected entries in extend-exclude: {unexpected}")
    return Check(
        "no_global_disable",
        not problems,
        "formatter-only exclusion; lint coverage untouched"
        if not problems
        else "; ".join(problems),
        {"extend_exclude": extend},
    )


def check_formatter_is_green(exit_code: int, output: str) -> Check:
    lines = output.strip().splitlines()
    tail = lines[-1] if lines else "(no output)"
    return Check("formatter_is_green", exit_code == 0, tail, {"exit_code": exit_code})


def flagged_files(output: str) -> list[str]:
    found: list[str] = []
    for line in output.splitlines():
        if line.startswith("Would reformat:"):
            found.append(line.split("Would reformat:", 1)[1].strip().replace("\\", "/"))
    return sorted(found)


def check_exemptions_are_necessary(
    configured: Sequence[str], still_flagged: Sequence[str]
) -> Check:
    wanted = sorted(configured)
    got = sorted(still_flagged)
    ok = got == wanted
    detail = (
        f"clearing format.exclude flags exactly the {len(wanted)} exempted files"
        if ok
        else f"flagged_not_exempted={sorted(set(got) - set(wanted))} "
        f"exempted_but_clean={sorted(set(wanted) - set(got))}"
    )
    return Check("exemptions_are_necessary", ok, detail, {"flagged": len(got)})


def _git_blob(root: Path, base: str, entry: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{base}:{entry}"], cwd=root, capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def check_protected_bytes(
    entries: Sequence[str],
    root: Path,
    base: str,
    overrides: Mapping[str, bytes] | None = None,
) -> Check:
    changed: list[str] = []
    digests: dict[str, str] = {}
    for entry in entries:
        current = (
            overrides[entry] if overrides and entry in overrides else (root / entry).read_bytes()
        )
        original = _git_blob(root, base, entry)
        if original is None:
            changed.append(f"{entry}: not in {base}")
            continue
        digest = hashlib.sha256(current).hexdigest()
        digests[entry] = digest
        if digest != hashlib.sha256(original).hexdigest():
            changed.append(entry)
    return Check(
        "protected_bytes_unchanged",
        not changed,
        f"{len(entries)} files byte-identical to {base}"
        if not changed
        else f"differ from {base}: {changed}",
        {"digests": digests},
    )


def check_linter_still_covers(entries: Sequence[str], linted: Sequence[str]) -> Check:
    seen = {Path(item).resolve().as_posix() for item in linted}
    missing = [entry for entry in entries if Path(entry).resolve().as_posix() not in seen]
    return Check(
        "linter_still_covers",
        not missing,
        f"{len(entries)}/{len(entries)} exempted files are still linted"
        if not missing
        else f"not linted: {missing}",
        {"linted_files": len(seen)},
    )


def check_records_unchanged(root: Path, base: str) -> Check:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD", "--", "data/"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    touched = [line for line in result.stdout.splitlines() if line.strip()]
    return Check(
        "certification_records_unchanged",
        result.returncode == 0 and not touched,
        "no committed record under data/ changed since the base commit"
        if not touched
        else f"records changed: {touched[:5]}",
        {"touched": len(touched)},
    )


def run_ruff(root: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, f"{result.stdout}\n{result.stderr}"


def measure(root: Path, base: str) -> list[Check]:
    config = parse_toml((root / CONFIG).read_text(encoding="utf-8"))
    declared = declared_exemptions(root / DEFAULT_DECLARATION)
    configured = formatter_exclude(config)

    format_code, format_out = run_ruff(root, "format", "--check", ".")
    cleared_code, cleared_out = run_ruff(
        root, "format", "--check", "--config", "format.exclude=[]", "."
    )
    lint_code, lint_out = run_ruff(root, "check", "--show-files")
    linted = [line.strip() for line in lint_out.splitlines() if line.strip().endswith(".py")]

    necessity = (
        check_exemptions_are_necessary(configured, flagged_files(cleared_out))
        if cleared_code in (0, 1)
        else Check("exemptions_are_necessary", False, cleared_out.strip()[-300:])
    )
    coverage = (
        check_linter_still_covers(declared, linted)
        if lint_code in (0, 1)
        else Check("linter_still_covers", False, lint_out.strip()[-300:])
    )
    return [
        check_config_matches(config, declared),
        check_entries_are_exact_files(config, root, declared),
        check_no_global_disable(config),
        check_formatter_is_green(format_code, format_out),
        necessity,
        check_protected_bytes(declared, root, base),
        coverage,
        check_records_unchanged(root, base),
    ]


def _records_detector_works(root: Path) -> bool:
    """The record check must react to a real, historical change under `data/`."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "data/"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    sha = result.stdout.strip()
    if not sha:
        return False
    return not check_records_unchanged(root, f"{sha}^").ok


def self_test(root: Path, base: str) -> Check:
    """Aim one mutation at each check; every one must be rejected."""
    text = (root / CONFIG).read_text(encoding="utf-8")
    declared = declared_exemptions(root / DEFAULT_DECLARATION)
    configured = formatter_exclude(parse_toml(text))
    results: list[str] = []

    def record(label: str, rejected: bool) -> None:
        results.append(f"{label}={'rejected' if rejected else 'ACCEPTED'}")

    trimmed = text.replace(f'  "{configured[0]}",\n', "", 1)
    record("drop_entry", not check_config_matches(parse_toml(trimmed), declared).ok)

    padded = text.replace(
        "exclude = [\n", 'exclude = [\n  "scripts/aggtrades_experiments.py",\n', 1
    )
    record("add_undeclared_entry", not check_config_matches(parse_toml(padded), declared).ok)
    record(
        "exempt_without_declaration",
        not check_entries_are_exact_files(parse_toml(padded), root, declared).ok,
    )

    globbed = text.replace(f'"{configured[0]}"', '"scripts/*.py"', 1)
    record("glob_entry", not check_entries_are_exact_files(parse_toml(globbed), root, declared).ok)

    disabled = text.replace("[tool.ruff.lint]\n", '[tool.ruff.lint]\nexclude = ["scripts"]\n', 1)
    record("lint_exclude", not check_no_global_disable(parse_toml(disabled)).ok)

    record("formatter_red", not check_formatter_is_green(1, "1 file would be reformatted").ok)

    decorative = sorted(set(declared) | {"scripts/aggtrades_experiments.py"})
    record("decorative_exemption", not check_exemptions_are_necessary(decorative, declared).ok)
    record("hidden_unformatted_file", not check_exemptions_are_necessary(configured, []).ok)

    tampered = {declared[0]: (root / declared[0]).read_bytes() + b" "}
    record("tampered_bytes", not check_protected_bytes([declared[0]], root, base, tampered).ok)

    record("lint_coverage_lost", not check_linter_still_covers(declared, declared[1:]).ok)
    record("records_detector", _records_detector_works(root))

    ok = all("ACCEPTED" not in item for item in results)
    return Check("self_test", ok, ", ".join(results), {"controls": len(results)})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("--base", default=DEFAULT_BASE, help="base commit the pins refer to")
    parser.add_argument("--json", dest="json_out", default=None, help="write the audit here")
    parser.add_argument("--self-test", action="store_true", help="run the negative controls")
    args = parser.parse_args(argv)

    root = Path(args.repo).resolve()
    checks = measure(root, args.base)
    if args.self_test:
        checks.append(self_test(root, args.base))

    for check in checks:
        print(f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.detail}")

    failed = [check.name for check in checks if not check.ok]
    verdict = "PASS" if not failed else "FAIL"
    print(f"VERDICT={verdict} ({len(checks) - len(failed)}/{len(checks)})")

    if args.json_out:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip()
        payload = {
            "schema": SCHEMA,
            "base": args.base,
            "head": head,
            "checks": [check.as_dict() for check in checks],
            "verdict": verdict,
            "failed": failed,
        }
        Path(args.json_out).write_text(
            json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
