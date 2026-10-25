"""Publish the event schema and the state machine from the code that enforces them.

    python scripts/exp_003p_schema.py

``ORDER_EVENT_SCHEMA.json``, ``ORDER_EVENT_SCHEMA.md`` and ``STATE_MACHINE.md`` are rendered
from ``trading_bot.paper.lifecycle.contracts`` instead of being typed by hand: a schema
documented next to the contract drifts, a schema generated from it cannot.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import Any, get_args, get_origin

REPO = Path(__file__).resolve().parents[1]
for candidate in (REPO / "scripts", REPO / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from exp_003p_contract import OUT, RUN_ID, write_json  # noqa: E402

from trading_bot.paper.lifecycle import contracts  # noqa: E402


def _type_name(annotation: Any) -> str:
    if annotation is None or annotation is type(None):
        return "null"
    if isinstance(annotation, str):
        return annotation
    origin = get_origin(annotation)
    if origin is not None:
        args = [ _type_name(arg) for arg in get_args(annotation) ]
        if origin is list:
            return f"array<{args[0]}>"
        if origin is dict:
            return f"object<{args[0]},{args[1]}>"
        if origin is tuple:
            return f"array<{','.join(args)}>"
        if str(origin).endswith("Union"):
            return " | ".join(args)
    return getattr(annotation, "__name__", str(annotation))


def _dataclass_schema(cls: type) -> dict[str, Any]:
    fields = []
    for field in dataclasses.fields(cls):
        fields.append(
            {
                "name": field.name,
                "type": _type_name(field.type),
                "required": field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING,
                "default": (
                    None
                    if field.default is dataclasses.MISSING
                    else repr(field.default)
                ),
            }
        )
    return {"dataclass": cls.__name__, "fields": fields}


def payload() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "schema_version": contracts.SCHEMA_VERSION,
        "generated_from": "src/trading_bot/paper/lifecycle/contracts.py",
        "provenances": list(contracts.PROVENANCES),
        "provider_environments": list(contracts.PROVIDER_ENVIRONMENTS),
        "provenance_environment_pairs": {
            key: sorted(value) for key, value in contracts.PROVENANCE_ENVIRONMENTS.items()
        },
        "order_states": list(contracts.ORDER_STATES),
        "terminal_states": sorted(contracts.TERMINAL_STATES),
        "event_types": dict(contracts.EVENT_STATES),
        "transitions": {key: sorted(value) for key, value in contracts.ALLOWED_TRANSITIONS.items()},
        "anomalies": list(contracts.ANOMALIES),
        "reconciliation_results": list(contracts.RECONCILIATION_RESULTS),
        "records": {
            "ExecutionEnvelope": _dataclass_schema(contracts.ExecutionEnvelope),
            "OrderIntent": _dataclass_schema(contracts.OrderIntent),
            "FillFact": _dataclass_schema(contracts.FillFact),
            "ReconciliationResult": _dataclass_schema(contracts.ReconciliationResult),
        },
        "rules": [
            "event_id is deduplicated inside (provenance, provider_environment)",
            "an envelope is refused before persistence if provenance and environment disagree",
            "LIVE is never a paper provider_environment",
            "received_time_utc >= event_time_utc >= decision_time_utc >= data_cutoff_utc",
            "a fill key books exactly once inside its provenance namespace",
            "ACK never moves quantity; only a fill fact does",
            "a terminal state is never reopened; a contradiction is audited, not applied",
            "UNKNOWN blocks any further send for that intent until a primary source resolves it",
        ],
    }


def render_schema_markdown(schema: dict[str, Any]) -> str:
    lines = [
        "# ORDER EVENT SCHEMA — EXP-003P",
        "",
        f"> Generated from `{schema['generated_from']}`; schema version "
        f"`{schema['schema_version']}`.",
        "",
        "## Provenance",
        "",
        "| provenance | allowed `provider_environment` | what it proves |",
        "| --- | --- | --- |",
    ]
    meaning = {
        "OFFLINE_SIMULATED": "what this code does with a given input; never that a venue accepted it",
        "REPLAY_CAPTURED": "that a captured session replays identically; not a new order or fill",
        "VENUE_REPORTED_PAPER": "that a paper/testnet venue reported the event; not a real fill",
    }
    for provenance, environments in schema["provenance_environment_pairs"].items():
        lines.append(
            f"| `{provenance}` | `{', '.join(environments)}` | {meaning.get(provenance, '')} |"
        )
    lines += [
        "",
        "## ExecutionEnvelope",
        "",
        "| field | type | required |",
        "| --- | --- | --- |",
    ]
    for field in schema["records"]["ExecutionEnvelope"]["fields"]:
        lines.append(f"| `{field['name']}` | `{field['type']}` | {field['required']} |")
    lines += [
        "",
        "## OrderIntent",
        "",
        "| field | type | required |",
        "| --- | --- | --- |",
    ]
    for field in schema["records"]["OrderIntent"]["fields"]:
        lines.append(f"| `{field['name']}` | `{field['type']}` | {field['required']} |")
    lines += [
        "",
        "## FillFact",
        "",
        "| field | type | required |",
        "| --- | --- | --- |",
    ]
    for field in schema["records"]["FillFact"]["fields"]:
        lines.append(f"| `{field['name']}` | `{field['type']}` | {field['required']} |")
    lines += [
        "",
        "## ReconciliationResult",
        "",
        "| field | type | required |",
        "| --- | --- | --- |",
    ]
    for field in schema["records"]["ReconciliationResult"]["fields"]:
        lines.append(f"| `{field['name']}` | `{field['type']}` | {field['required']} |")
    lines += [
        "",
        "## Event types and the state they assert",
        "",
        "| event_type | asserted state |",
        "| --- | --- |",
    ]
    for event, state in schema["event_types"].items():
        lines.append(f"| `{event}` | `{state}` |")
    lines += [
        "",
        "## Rules",
        "",
    ]
    lines += [f"- {rule}" for rule in schema["rules"]]
    lines += [
        "",
        "## Defect vocabulary",
        "",
        "`" + "`, `".join(schema["anomalies"]) + "`",
        "",
    ]
    return "\n".join(lines)


def render_state_machine(schema: dict[str, Any]) -> str:
    lines = [
        "# STATE MACHINE — EXP-003P",
        "",
        f"> Generated from `{schema['generated_from']}`.",
        "",
        "| from | allowed next states |",
        "| --- | --- |",
    ]
    for state, targets in schema["transitions"].items():
        rendered = ", ".join(f"`{target}`" for target in targets) or "— (terminal)"
        marker = " **(terminal)**" if state in schema["terminal_states"] else ""
        lines.append(f"| `{state}`{marker} | {rendered} |")
    lines += [
        "",
        "## Reading rules",
        "",
        "- `ACK != FILL`: only an event carrying a fill fact changes quantity.",
        "- A fill that arrives before its acknowledgement is reported as "
        "`FILL_WITHOUT_ACK`; no ACK is invented to complete the sequence.",
        "- Events are projected in `(event_time_utc, arrival order)`; a transport reorder is "
        "reported as `OUT_OF_ORDER_EVENT` and the raw event is preserved.",
        "- A terminal order never reopens: a contradictory later event becomes "
        "`TERMINAL_STATE_MUTATION` and is not applied.",
        "- `UNKNOWN` is not terminal. It blocks any further send for that intent until a "
        "primary source resolves it through `ORDER_STATE_RESOLVED`.",
        "- `cum_filled_qty` is monotonic and bounded by the ordered quantity "
        "(`QUANTITY_EXCEEDED` otherwise).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P schema publication")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)

    schema = payload()
    write_json(out / "ORDER_EVENT_SCHEMA.json", schema)
    (out / "ORDER_EVENT_SCHEMA.md").write_text(
        render_schema_markdown(schema), encoding="utf-8", newline="\n"
    )
    (out / "STATE_MACHINE.md").write_text(
        render_state_machine(schema), encoding="utf-8", newline="\n"
    )
    print(
        f"[003p-schema] records={len(schema['records'])} events={len(schema['event_types'])} "
        f"states={len(schema['order_states'])} anomalies={len(schema['anomalies'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
