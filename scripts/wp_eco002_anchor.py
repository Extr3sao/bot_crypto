"""WP-ECONOMIC-RECOVERY-002 — the evidence behind the admission-anchor repair.

Records, from the repository itself, the four facts the repair rests on:

1. the digest the ledger used to carry for `docs/STRATEGY_ADMISSION_MATRIX.json`
   matches no committed revision of that file — so it was not "the previous
   matrix", it was a value that never existed in git;
2. the ledger committed now is exactly what the builder derives from the
   committed matrix, byte for byte;
3. the repair changed nothing but the anchor: the ledger's payload is identical
   to the previous revision's payload once `_sources` is removed;
4. the matrix the anchor now names is *itself* not reconstructible from a clean
   checkout, because `scripts/build_admission_matrix.py` reads six
   `reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json` files that are
   gitignored and absent here. That is a blocker on the upstream link, not on
   the ledger, and it is recorded instead of being papered over.

Also records how the WP-7 cost-barrier gate sees the new digest, because that
gate pins this ledger as a declared input.

Usage:
    uv run python scripts/wp_eco002_anchor.py [--out <evidence dir>] [--previous <rev>]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("config/strategy_admission.json")
MATRIX = Path("docs/STRATEGY_ADMISSION_MATRIX.json")
MATRIX_BUILDER = Path("scripts/build_admission_matrix.py")
MATRIX_INPUTS = Path("reports/strategy-baseline")
GATE = Path("scripts/cost_barrier_gate.py")
EXPLORER = Path("data/recovery/COST_BARRIER_EXPLORER.json")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str | None:
    target = REPO_ROOT / path
    return sha256_bytes(target.read_bytes()) if target.is_file() else None


def blob(rev: str, path: Path) -> bytes | None:
    answer = subprocess.run(
        ["git", "show", f"{rev}:{path.as_posix()}"], cwd=REPO_ROOT, capture_output=True, check=False
    )
    return answer.stdout if answer.returncode == 0 else None


def load_builder() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_strategy_admission", REPO_ROOT / "scripts" / "build_strategy_admission.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rebuilt_ledger_bytes() -> bytes:
    payload = load_builder().build()
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode(
        "utf-8"
    )


def historical_matrix_digests() -> list[dict[str, str]]:
    revisions = git("log", "--all", "--format=%H", "--", MATRIX.as_posix()).split()
    rows = []
    for rev in revisions:
        payload = blob(rev, MATRIX)
        if payload is None:
            continue
        rows.append({"commit": rev[:12], "sha256": sha256_bytes(payload)})
    return rows


def gate_pin() -> dict[str, Any]:
    if not (REPO_ROOT / EXPLORER).is_file():
        return {"available": False, "reason": f"{EXPLORER.as_posix()} is absent"}
    explorer = json.loads((REPO_ROOT / EXPLORER).read_text(encoding="utf-8"))
    for source in explorer.get("sources", []):
        if source.get("path") == LEDGER.as_posix():
            return {
                "available": True,
                "explorer": EXPLORER.as_posix(),
                "pinned_sha256": source.get("sha256"),
                "pinned_state_sha256": source.get("state_sha256"),
                "gate": GATE.as_posix(),
                "declared_input_of": "WP-7 cost-barrier drift gate (pinned in the explorer's sources[])",
            }
    return {"available": False, "reason": "the explorer does not pin the admission ledger"}


def gate_status() -> dict[str, Any]:
    answer = subprocess.run(
        ["uv", "run", "python", GATE.as_posix(), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    pinned = [
        line.strip()
        for line in (answer.stdout + answer.stderr).splitlines()
        if "published_pins_match_the_declared_sources" in line
    ]
    first = (answer.stdout + answer.stderr).strip().splitlines()
    return {
        "command": f"uv run python {GATE.as_posix()} --check",
        "exit_code": answer.returncode,
        "headline": first[0] if first else "",
        "pin_check": pinned[0] if pinned else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-002")
    )
    parser.add_argument(
        "--previous",
        default="e67194e7",
        help="revision whose ledger carried the stale anchor",
    )
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    previous_payload = blob(args.previous, LEDGER) or b""
    previous_ledger = json.loads(previous_payload) if previous_payload else {}
    recorded = {source["path"]: source["sha256"] for source in previous_ledger.get("_sources", [])}
    current_ledger = json.loads((REPO_ROOT / LEDGER).read_text(encoding="utf-8"))
    current_recorded = {
        source["path"]: source["sha256"] for source in current_ledger.get("_sources", [])
    }

    history = historical_matrix_digests()
    stale = recorded.get(MATRIX.as_posix())
    matching_revisions = [row for row in history if row["sha256"] == stale]

    rebuilt = rebuilt_ledger_bytes()
    committed = (REPO_ROOT / LEDGER).read_bytes()

    def without_sources(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key != "_sources"}

    payload_unchanged = without_sources(previous_ledger) == without_sources(current_ledger)

    expected_inputs = [
        MATRIX_INPUTS / f"MULTI_FAMILY_RESULTS_{name}.json"
        for name in (
            "momentum",
            "breakout",
            "trend",
            "mean_reversion",
            "volatility",
            "ema_crossover",
        )
    ]
    input_rows = [
        {"path": path.as_posix(), "present": (REPO_ROOT / path).is_file()}
        for path in expected_inputs
    ]

    pin = gate_pin()
    ledger_digest = file_digest(LEDGER)

    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-002",
        "artefact": "ANCHOR_REPAIR",
        "commit_under_measurement": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "previous_revision": git("rev-parse", args.previous)[:12],
        "defect": "PROVENANCE_ANCHOR_STALE",
        "ledger": LEDGER.as_posix(),
        "anchor_source": MATRIX.as_posix(),
        "recorded_before": stale,
        "recorded_now": current_recorded.get(MATRIX.as_posix()),
        "matrix_digest_on_disk": file_digest(MATRIX),
        "matrix_digests_in_history": history,
        "recorded_before_matches_any_committed_revision": bool(matching_revisions),
        "matching_revisions": matching_revisions,
        "finding": (
            "the stale digest matches no committed revision of the matrix: it was produced from a "
            "matrix state that was never committed, so `--check` could never pass and the ledger "
            "carried an anchor that pointed nowhere"
        ),
        "ledger_rebuilt_equals_committed": rebuilt == committed,
        "ledger_digest_before": sha256_bytes(previous_payload) if previous_payload else None,
        "ledger_digest_now": sha256_bytes(committed),
        "ledger_payload_unchanged_except_sources": payload_unchanged,
        "strategy_entries": len(current_ledger.get("strategies", {})),
        "admitted_for_paper": sorted(
            sid
            for sid, entry in current_ledger.get("strategies", {}).items()
            if entry.get("admitted_for_paper")
        ),
        "upstream_link": {
            "builder": MATRIX_BUILDER.as_posix(),
            "inputs": input_rows,
            "inputs_present": sum(1 for row in input_rows if row["present"]),
            "reconstructible_from_this_checkout": all(row["present"] for row in input_rows),
            "declared": (
                "the matrix is not reconstructible here: its builder reads six gitignored "
                "reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json files. Re-running it with "
                "them absent would silently produce a matrix with one family instead of six, "
                "which is how an anchor goes stale in the first place. The committed matrix is "
                "therefore the authoritative anchor, and its own regeneration is a declared "
                "blocker, not something this work package invents."
            ),
        },
        "cost_barrier_gate": {
            "pin": pin,
            "ledger_digest_now": ledger_digest,
            "pin_matches_now": bool(pin.get("pinned_sha256") == ledger_digest),
            "status_now": gate_status(),
            "consequence": (
                "repairing the anchor changes the bytes of a file the WP-7 cost-barrier explorer "
                "pins as a declared input, so that gate moves from CHECK_ONLY_WITH_ADVISORIES to "
                "INTEGRITY_FAILURE. The gate is right: its certified input no longer matches the "
                "pin. The repair is to regenerate and re-verify the cost-barrier evidence, which "
                "moves published economic evidence and is out of scope here; editing the pin by "
                "hand would be forging the evidence."
            ),
        },
    }
    (args.out / "ANCHOR_REPAIR.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    print(f"recorded before : {stale}")
    print(f"matrix on disk  : {payload['matrix_digest_on_disk']}")
    print(f"matches a revision: {payload['recorded_before_matches_any_committed_revision']}")
    print(f"ledger rebuilt == committed: {payload['ledger_rebuilt_equals_committed']}")
    print(f"payload unchanged except _sources: {payload_unchanged}")
    print(f"matrix inputs present: {payload['upstream_link']['inputs_present']}/6")
    print(f"gate pin matches now: {payload['cost_barrier_gate']['pin_matches_now']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
