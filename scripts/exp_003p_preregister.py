"""Write (or verify) the frozen protocol of EXP-003P.

    python scripts/exp_003p_preregister.py
    python scripts/exp_003p_preregister.py --check

The protocol is rendered from ``exp_003p_contract`` only. ``--check`` re-renders it in
memory and compares the bytes with what is on disk, so a protocol edited after the run —
to match a result — is detected rather than trusted.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003p_contract import (  # noqa: E402
    OUT,
    SCENARIOS,
    SUCCESS_RULES,
    WINDOW,
    canonical_json,
    git,
    protocol_payload,
    write_json,
)

PROTOCOL = OUT / "design" / "PROTOCOL.json"
PREREGISTRATION = OUT / "design" / "PREREGISTRATION.md"
DESIGN_SEAL = OUT / "design" / "DESIGN.sha256"


def render_markdown(payload: dict) -> str:
    lines = [
        "# EXP-003P — PREREGISTRATION (frozen before the first rehearsal)",
        "",
        f"- run: `{payload['run_id']}`",
        f"- frozen at: `{payload['frozen_at_utc']}`",
        f"- mode: `{payload['mode']}`; live enabled: `{payload['live']['enabled']}`; "
        f"live orders allowed: `{payload['live']['orders_allowed']}`",
        f"- dependency: `{payload['dependency']['experiment']}` "
        f"(`{payload['dependency']['status']}`)",
        f"- config digest: `{payload['config_digest']}`",
        f"- protocol sha256: `{hashlib.sha256(canonical_json(payload).encode()).hexdigest()}`",
        "",
        "## What is frozen",
        "",
        "| item | value |",
        "| --- | --- |",
        f"| runtime entrypoint | `{payload['runtime']['entrypoint']}` |",
        f"| execution boundary | `{payload['runtime']['execution_boundary']}` |",
        f"| window | `{WINDOW['start_utc']}` → `{WINDOW['end_utc']}` |",
        f"| symbols | `{', '.join(WINDOW['symbols'])}` |",
        f"| timeframe / cadence | `{WINDOW['timeframe']}` / every "
        f"`{WINDOW['decision_every_bars']}` bars |",
        f"| equity | `{WINDOW['equity_usdt']}` USDT (paper) |",
        "",
        "## Success rules",
        "",
    ]
    for dimension, rule in SUCCESS_RULES.items():
        lines.append(f"### {dimension}")
        if isinstance(rule, dict):
            for key, value in rule.items():
                lines.append(f"- **{key}**: {value}")
        else:
            lines.append(f"- {rule}")
        lines.append("")
    lines.append("## Scenario scripts")
    lines.append("")
    lines.append("| id | mode | side | quantity | tranches | delays (ms) | duplicates | reorder |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in SCENARIOS:
        lines.append(
            "| {scenario_id} | {mode} | {side} | {quantity} | {tranches} | "
            "{fill_delays_ms} | {duplicate_last} | {deliver_fills_before_ack} |".format(**row)
        )
    lines += [
        "",
        "## Declared limits (frozen with the protocol, not added afterwards)",
        "",
    ]
    lines += [f"- {limit}" for limit in payload["declared_limits"]]
    lines += [
        "",
        "## Sequence",
        "",
        "1. this file and `PROTOCOL.json` are written before any rehearsal;",
        "2. the rehearsal records the protocol digest it ran under;",
        "3. `--check` refuses a protocol whose bytes moved after that record.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P preregistration")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    payload = protocol_payload()
    rendered = canonical_json(payload)
    if args.check:
        if not PROTOCOL.exists():
            print("[003p-preregister] MISSING protocol; the run has no preregistration")
            return 5
        current = PROTOCOL.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "[003p-preregister] REFUSED — PROTOCOL.json no longer matches the frozen "
                "contract; a protocol edited after the fact is not a preregistration"
            )
            return 6
        print("[003p-preregister] OK — the protocol matches the frozen contract")
        return 0

    write_json(PROTOCOL, payload)
    PREREGISTRATION.parent.mkdir(parents=True, exist_ok=True)
    PREREGISTRATION.write_text(render_markdown(payload), encoding="utf-8", newline="\n")
    digest = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    DESIGN_SEAL.write_text(
        f"{digest}  design/PROTOCOL.json\n"
        f"{hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest()}  design/PREREGISTRATION.md\n",
        encoding="utf-8",
        newline="\n",
    )
    commit = git("log", "-1", "--format=%h", "--", str(PROTOCOL.relative_to(REPO)).replace("\\", "/"))
    print(
        "[003p-preregister] written "
        f"protocol={digest[:16]}… commit={commit or 'UNCOMMITTED'} "
        f"frozen_at={payload['frozen_at_utc']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
