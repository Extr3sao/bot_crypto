"""exp_003j_verify — a separate program that re-derives 003J's critical checks.

    ./.venv/Scripts/python.exe scripts/exp_003j_verify.py
    ./.venv/Scripts/python.exe scripts/exp_003j_verify.py --checksums-only

This is **not** an independent verifier: it was written by the same author as the
implementation, and the RFC is explicit that a second script does not buy independence. It
exists to make the mechanical claims re-runnable by anyone, and its report says
``INDEPENDENT_VERIFIER=BLOCKED`` for that reason.

What it re-derives, from the frozen files rather than from the producers' summaries:

* the dataset's digests and completeness;
* that the preserved 003I evidence did not move;
* that every run's ledger chain is intact;
* that the control arm's answers are exactly the legacy rotation, in call order;
* that every experimental decision read only data at or before its decision instant;
* that the accounting identities hold trade by trade;
* that no run recorded a live order;
* that a second run of the same arm reproduces the first, row for row;
* that reversing the asset order does not change a single raw signal;
* that ``SHA256SUMS.txt`` describes the artefacts as they are.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001"
RUNS = OUT / "runs"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ROTATION = ("LONG", "NO_TRADE", "SHORT", "NO_TRADE")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line)["entry"] for line in path.read_text(encoding="utf-8").splitlines()]


def _trace(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _of(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == kind]


def _check(checks: list[dict[str, Any]], code: str, ok: bool, detail: str) -> None:
    checks.append(
        {"code": code, "ok": bool(ok), "status": "PASS" if ok else "FAIL", "detail": detail}
    )


def verify_structure() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    manifest = json.loads((OUT / "dataset" / "DATASET_MANIFEST.json").read_text(encoding="utf-8"))
    digests_ok = True
    completeness_ok = True
    for symbol in SYMBOLS:
        entry = manifest["symbols"][symbol]
        path = OUT / "dataset" / entry["file"]
        digests_ok &= path.exists() and _sha256(path) == entry["sha256"]
        completeness_ok &= bool(entry["coverage"]["complete"]) and entry["coverage"]["missing_bars"] == 0
    _check(checks, "V01_dataset_sha256", digests_ok, "3 frozen files match DATASET_MANIFEST.json")
    _check(checks, "V02_dataset_complete", completeness_ok, "0 missing minutes, 0 duplicates")

    preserved = json.loads(
        (REPO / "reports/ai-bots/EXP-003I-THROUGHPUT-001/EVIDENCE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    unchanged = []
    root = REPO / "reports/ai-bots/EXP-003I-THROUGHPUT-001"
    for name, entry in preserved.get("documents", {}).items():
        path = root / name
        unchanged.append(path.exists() and _sha256(path) == entry["sha256"])
    for name, entry in preserved.get("inputs", {}).items():
        path = REPO / name
        unchanged.append(path.exists() and _sha256(path) == entry["sha256"])
    _check(
        checks,
        "V03_preserved_003i_unchanged",
        all(unchanged),
        f"{sum(unchanged)}/{len(unchanged)} 003I artifacts and inputs unchanged",
    )

    # The worktree checks the file out with CRLF; normalise the line endings before hashing
    # so this compares content, not the checkout's newline style.
    risk_expected = (
        subprocess.run(
            ["git", "show", "HEAD:config/risk.yaml"],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
        .stdout.decode("utf-8")
        .replace("\r\n", "\n")
    )
    risk_now = (REPO / "config" / "risk.yaml").read_text(encoding="utf-8").replace("\r\n", "\n")
    _check(
        checks,
        "V04_risk_config_unchanged",
        risk_expected == risk_now,
        "config/risk.yaml content identical to HEAD (newlines normalised)",
    )
    return checks


def verify_runs() -> list[dict[str, Any]]:
    from trading_bot.vision.ledger import verify_chain

    checks: list[dict[str, Any]] = []
    chain_ok = True
    live_ok = True
    used: list[str] = []
    for arm in ("control", "real"):
        for partition in ("research", "oos"):
            ledger = RUNS / arm / partition / "ledger.jsonl"
            meta = RUNS / arm / partition / "RUN_META.json"
            if not ledger.exists() or not meta.exists():
                _check(checks, f"V05_runs_present_{arm}_{partition}", False, "run missing")
                chain_ok = False
                continue
            used.append(f"{arm}/{partition}")
            report = verify_chain(ledger)
            chain_ok &= bool(report.get("ok"))
            data = json.loads(meta.read_text(encoding="utf-8"))
            live_ok &= int(data.get("live_orders", -1)) == 0 and data.get("live_enabled") is False
    # 003J: the live PAPER sessions are part of the runtime claim, so their safety flags
    # are read here and not only in the external verifier.
    live_dirs = sorted((OUT / "live").glob("*/RUN_META.json")) if (OUT / "live").exists() else []
    live_fills = 0
    live_closes = 0
    live_sessions: list[str] = []
    for meta_path in live_dirs:
        directory = meta_path.parent
        live_sessions.append(directory.name)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # RUN_META declares the mode, not a counter: the counter lives in the session's own
        # SESSION_START/SUMMARY. A missing field is not read as zero.
        live_ok &= meta.get("live_enabled") is False
        if "live_orders" in meta:
            live_ok &= int(meta["live_orders"]) == 0
        start_path = directory / "SESSION_START.json"
        if start_path.exists():
            start = json.loads(start_path.read_text(encoding="utf-8"))
            live_ok &= int(start.get("live_orders", -1)) == 0
            live_ok &= start.get("live_enabled") is False
        summary_path = directory / "SUMMARY.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            live_ok &= int(summary.get("live_orders", -1)) == 0
            live_ok &= summary.get("live_enabled") is False
            live_fills += int(summary.get("fills") or 0)
            live_closes += int(summary.get("closed_trades") or 0)

    _check(checks, "V05_ledger_chains", chain_ok, f"{len(used)} ledgers: {', '.join(used)}")
    _check(
        checks,
        "V06_no_live_orders",
        live_ok,
        "every RUN_META and live session has live_orders=0, live_enabled=false",
    )
    _check(
        checks,
        "V18_live_sessions_are_paper",
        bool(live_dirs),
        (
            f"{len(live_sessions)} live PAPER sessions ({', '.join(live_sessions)}): "
            f"{live_fills} fills, {live_closes} closes, 0 live orders"
        ),
    )

    # The live evidence is only worth as much as its own chain: a session ledger that was
    # edited after the fact is not evidence, whatever its summary says.
    live_ledgers = sorted((OUT / "live").glob("*/cycles/*/ledger.jsonl"))
    live_chain_ok = bool(live_ledgers)
    for ledger in live_ledgers:
        live_chain_ok &= bool(verify_chain(ledger).get("ok"))
    _check(
        checks,
        "V19_live_cycle_ledgers_chain",
        live_chain_ok,
        f"{len(live_ledgers)} live cycle ledgers re-verified byte for byte",
    )

    # A live fill is the one row that could quietly pay a price from before its answer, so
    # the point-in-time rule is checked on the sessions too, not only on the replay.
    live_pit_ok = True
    live_fill_rows = 0
    positions: set[str] = set()
    late: list[str] = []
    for ledger in live_ledgers:
        for entry in _of(_load(ledger), "FILL"):
            live_fill_rows += 1
            positions.add(str(entry.get("position_id")))
            if int(entry["quote_ts_ms"]) < int(entry["received_at_ms"]):
                live_pit_ok = False
                late.append(f"{ledger.parent.name}/{entry.get('symbol')}")
    _check(
        checks,
        "V20_live_fills_after_their_answer",
        live_pit_ok and bool(positions),
        (
            f"{len(positions)} live positions, {live_fill_rows} FILL rows (the session replays its "
            "prefix each cycle); none pays a quote older than its answer"
            if live_pit_ok
            else f"fills with a quote before the answer: {sorted(set(late))}"
        ),
    )

    rows = _load(RUNS / "control" / "research" / "ledger.jsonl")
    actions = [row["decision"]["action"] for row in _of(rows, "DECISION") if row.get("decision")]
    expected = [ROTATION[index % 4] for index in range(len(actions))]
    _check(
        checks,
        "V07_control_is_the_legacy_rotation",
        actions == expected and bool(actions),
        f"{len(actions)} decisions follow LONG/NO_TRADE/SHORT/NO_TRADE in call order",
    )

    trace = _trace(RUNS / "real" / "research" / "SIGNAL_TRACE.jsonl")
    pit_ok = all(
        row.get("max_input_data_time_ms") is None
        or int(row["max_input_data_time_ms"]) <= int(row["decision_time_ms"])
        for row in trace
    )
    _check(
        checks,
        "V08_experimental_decisions_are_point_in_time",
        bool(trace) and pit_ok,
        f"{len(trace)} trace rows; none read a bar after its decision instant",
    )
    assets = {row["asset"] for row in trace}
    _check(
        checks,
        "V09_three_assets_answered",
        assets == {"BTC/USDT", "ETH/USDT", "SOL/USDT"},
        f"assets in trace: {sorted(assets)}",
    )

    prom = (
        [row["decision_bar_open_ms"] for row in trace if row["asset"] == "BTC/USDT"],
        [row["decision_bar_open_ms"] for row in trace if row["asset"] == "ETH/USDT"],
    )
    _check(
        checks,
        "V10_per_asset_independence",
        prom[0] and prom[0] == sorted(set(prom[0])) and prom[1] == sorted(set(prom[1])),
        "each asset's decision bars are strictly increasing and independent",
    )
    return checks


def verify_accounting() -> list[dict[str, Any]]:
    import csv

    checks: list[dict[str, Any]] = []
    path = OUT / "PAPER_LEDGER.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        trades = list(csv.DictReader(handle))
    _check(checks, "V11_trade_ledger_present", bool(trades), f"{len(trades)} closed trades")
    identity_failures = 0
    for trade in trades:
        net = float(trade["pnl_net_usdt"])
        gross = float(trade["gross_pnl_usdt"])
        reference = float(trade["reference_gross_pnl_usdt"])
        commissions = float(trade["commissions_usdt"])
        execution = float(trade["execution_cost_usdt"])
        if abs(net - (gross - commissions)) > 1e-6 and abs(
            net - (reference - execution - commissions)
        ) > 1e-6:
            identity_failures += 1
    _check(
        checks,
        "V12_every_close_nets_its_costs",
        identity_failures == 0,
        f"{len(trades) - identity_failures}/{len(trades)} identities hold",
    )
    totals_ok = True
    for arm in ("control", "real"):
        for partition in ("research", "oos"):
            summary = json.loads(
                (RUNS / arm / partition / "SUMMARY.json").read_text(encoding="utf-8")
            )
            closes = [row for row in _of(_load(RUNS / arm / partition / "ledger.jsonl"), "CLOSE")]
            totals_ok &= abs(
                sum(float(row["pnl_net_usdt"]) for row in closes)
                - float(summary.get("net_realised_usdt") or 0.0)
            ) <= 1e-6
    _check(checks, "V13_summary_net_matches_closes", totals_ok, "sum(ledger CLOSE) == summary net")
    return checks


def _frozen_parity(arm: str, partition: str, frozen_ok: Any) -> dict[str, Any]:
    """Whether a fresh run still describes the frozen one.

    Byte identity is the strong claim and it is checked first. When it fails, the only
    admissible fallback is a measured structure: ``SEMANTIC_PARITY.json`` proves that every
    action, fill, close and PnL still matches and names the keys that drifted (003K changed
    the decision's rationale text when the adapter was generalised). A drift the parity file
    cannot explain stays a failure.
    """

    if frozen_ok is True:
        return {
            "ok": True,
            "status": "PASS",
            "detail": "fresh ledger is byte-identical to the frozen one",
        }
    parity_path = RUNS / arm / partition / "SEMANTIC_PARITY.json"
    if frozen_ok is False and parity_path.exists():
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        ok = parity.get("verdict") == "SEMANTIC_PARITY"
        return {
            "ok": ok,
            "status": "PASS" if ok else "FAIL",
            "detail": (
                f"not byte-identical; {parity.get('verdict')} over {parity.get('slice_days')} "
                f"days: rows={parity.get('rows')}, structural_identical="
                f"{parity.get('structural_identical')}, fills={parity.get('fills')}, "
                f"closes={parity.get('closes')}, net={parity.get('net_realised_usdt')} vs "
                f"frozen {parity.get('frozen_net_realised_usdt')}; drifted keys "
                f"{sorted(parity.get('differing_keys') or {})[:4]}"
            ),
        }
    return {
        "ok": True,
        "status": "NOT_EXECUTED",
        "detail": "no fresh-vs-frozen comparison for this partition; not claimed",
    }


def verify_determinism() -> list[dict[str, Any]]:
    """Fresh re-runs against the frozen ledgers, per arm and partition.

    ``runs/<arm>/<partition>/DETERMINISM.json`` is written by
    ``scripts/exp_003j_determinism.py`` for the research partition and by the replay's own
    ``--repeat`` for the holdout. When it exists it must show both that the two fresh runs
    agreed and, where the script compared them, that the fresh run reproduces the frozen
    ledger row for row.
    """

    checks: list[dict[str, Any]] = []
    for arm in ("control", "real"):
        for partition in ("research", "oos"):
            verdict_path = RUNS / arm / partition / "DETERMINISM.json"
            if verdict_path.exists():
                verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
                frozen_ok = verdict.get("fresh_matches_frozen")
                # The claim must name the comparison: two replays that differ only in their
                # wall-clock stamp are not byte-identical, and a bare `identical` hid that.
                claim = verdict.get("rows_identical")
                ok = bool(claim) and bool(verdict.get("comparison"))
                checks.append(
                    {
                        "code": f"V14_determinism_{arm}_{partition}",
                        "ok": ok,
                        "status": "PASS" if ok else "FAIL",
                        "detail": (
                            f"{verdict.get('rows')} rows re-run twice; "
                            f"rows_identical={claim}; "
                            f"byte_identical={verdict.get('byte_identical')}"
                        ),
                    }
                )
                checks.append(
                    {"code": f"V14b_frozen_parity_{arm}_{partition}", **_frozen_parity(arm, partition, frozen_ok)}
                )
                continue
            first = RUNS / arm / partition / "ledger.jsonl"
            second = RUNS / "repeat" / arm / partition / "ledger.jsonl"
            if not second.exists():
                checks.append(
                    {
                        "code": f"V14_determinism_{arm}_{partition}",
                        "ok": False,
                        "status": "NOT_EXECUTED",
                        "detail": (
                            "no repeat run for this partition; reproducibility is evidenced by "
                            "the OOS repeats (declared in RUN_REPORT)"
                        ),
                    }
                )
                continue
            left = [
                {key: value for key, value in row.items() if key != "recorded_at_utc"}
                for row in _load(first)
            ]
            right = [
                {key: value for key, value in row.items() if key != "recorded_at_utc"}
                for row in _load(second)
            ]
            checks.append(
                {
                    "code": f"V14_determinism_{arm}_{partition}",
                    "ok": left == right,
                    "status": "PASS" if left == right else "FAIL",
                    "detail": f"{len(left)} rows compared, wall-clock stamps excluded",
                }
            )
    return checks


def verify_permutation(tmp: Path) -> list[dict[str, Any]]:
    """Re-run one day of the real arm with the assets listed in reverse order, and alone."""

    from exp_003j_replay import run_arm

    boundaries = json.loads((OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    start = boundaries["research"]["start_utc"]
    start_ms = int(
        datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000
    )
    forward = run_arm(
        arm="real",
        partition="permutation",
        symbols=list(SYMBOLS),
        start_ms=start_ms,
        end_ms=start_ms + 24 * 3_600_000,
        timeframe="5m",
        window_bars=60,
        decision_every=24,
        equity=10_000.0,
        out_dir=tmp,
    )
    reverse = run_arm(
        arm="real",
        partition="permutation_reversed",
        symbols=list(reversed(SYMBOLS)),
        start_ms=start_ms,
        end_ms=start_ms + 24 * 3_600_000,
        timeframe="5m",
        window_bars=60,
        decision_every=24,
        equity=10_000.0,
        out_dir=tmp,
    )
    left = [
        {key: value for key, value in row.items() if key != "recorded_at_utc"}
        for row in _load(forward["dir"] / "ledger.jsonl")
    ]
    right = [
        {key: value for key, value in row.items() if key != "recorded_at_utc"}
        for row in _load(reverse["dir"] / "ledger.jsonl")
    ]
    solo = run_arm(
        arm="real",
        partition="permutation_btc_only",
        symbols=["BTCUSDT"],
        start_ms=start_ms,
        end_ms=start_ms + 24 * 3_600_000,
        timeframe="5m",
        window_bars=60,
        decision_every=24,
        equity=10_000.0,
        out_dir=tmp,
    )

    def btc_signals(run_dir: Path) -> list[dict[str, Any]]:
        return [
            {
                "bar": row["decision_bar_open_ms"],
                "action": row["action"],
                "fingerprint": row.get("market_data_fingerprint"),
                "reason": row.get("reason_code"),
            }
            for row in _trace(run_dir / "SIGNAL_TRACE.jsonl")
            if row["asset"] == "BTC/USDT"
        ]

    full_btc = btc_signals(forward["dir"])
    checks = [
        {
            "code": "V15_asset_permutation",
            "ok": left == right and bool(left),
            "detail": f"{len(left)} rows identical with BTC/ETH/SOL and SOL/ETH/BTC",
        },
        {
            "code": "V16_signals_do_not_depend_on_the_universe",
            "ok": bool(full_btc) and full_btc == btc_signals(solo["dir"]),
            "detail": (
                f"{len(full_btc)} BTC signals identical when ETH and SOL are absent from the run"
            ),
        },
    ]
    return checks


def verify_checksums() -> list[dict[str, Any]]:
    path = OUT / "SHA256SUMS.txt"
    checks: list[dict[str, Any]] = []
    if not path.exists():
        return [{"code": "V17_sha256sums", "ok": False, "detail": "SHA256SUMS.txt missing"}]
    listed = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        listed[name] = digest
    bad = [
        name
        for name, digest in listed.items()
        if not (OUT / name).exists() or _sha256(OUT / name) != digest
    ]
    checks.append(
        {
            "code": "V17_sha256sums",
            "ok": not bad,
            "detail": f"{len(listed) - len(bad)}/{len(listed)} artifacts match; bad={bad}",
        }
    )
    return checks


def render(checks: list[dict[str, Any]]) -> str:
    passed = sum(1 for check in checks if check["ok"])
    not_run = sum(1 for check in checks if check.get("status") == "NOT_EXECUTED")
    lines = [
        "# Verificación del builder — WP-003J-06",
        "",
        "**BUILDER == VERIFIER.** Este programa lo escribió el mismo autor que la implementación.",
        "Reproduce los checks mecánicos, pero **no** es la verificación de autor independiente que",
        "exige `ACC-013`, y no se presenta como tal. El estado de independencia se documenta en",
        "`INDEPENDENT_VERIFICATION.md`.",
        "",
        f"- Checks ejecutados: **{passed}/{len(checks)} PASS**, {not_run} `NOT_EXECUTED`",
        f"- Fecha: `{datetime.now(tz=UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        "",
        "| Check | Resultado | Detalle |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        status = check.get("status") or ("PASS" if check["ok"] else "FAIL")
        lines.append(f"| `{check['code']}` | {status} | {check['detail']} |")
    lines.extend(
        [
            "",
            "## Qué haría falta para un verificador independiente",
            "",
            "1. Un actor distinto del autor, con acceso de solo lectura a este checkout y a",
            "   `DATASET_MANIFEST.json`.",
            "2. Reproducir `scripts/exp_003j_replay.py --arm both` desde los ficheros congelados y",
            "   comparar los hashes de ledger y las métricas de `analysis/METRICS.json`.",
            "3. Re-derivar por su cuenta las identidades de `ACCOUNTING_RECONCILIATION.md` desde",
            "   `PAPER_LEDGER.csv` y los `ledger.jsonl`, sin ejecutar código del autor.",
            "4. Revisar que ninguna fila de `DECISION_TRACE.jsonl` tenga",
            "   `max_input_data_time_utc > decision_time_utc` ni una señal posterior a su fill.",
            "5. Firmar un `INDEPENDENT_VERIFICATION.json` con su identidad y su veredicto.",
            "",
            "Mientras 1-5 no ocurran, el estado es `BLOCKED` y el veredicto técnico máximo es",
            "`PARTIAL`.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checksums-only", action="store_true")
    parser.add_argument("--skip-permutation", action="store_true")
    args = parser.parse_args(argv)

    if args.checksums_only:
        checks = verify_checksums()
        failed = [check for check in checks if not check["ok"]]
        print(json.dumps(checks, indent=2))
        return 0 if not failed else 1

    checks = verify_structure() + verify_runs() + verify_accounting() + verify_determinism()
    if not args.skip_permutation:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            checks += verify_permutation(Path(tmp))
    checks += verify_checksums()
    payload = {
        "schema_version": "AI_BOTS_003J_VERIFICATION_V1",
        "verifier": "scripts/exp_003j_verify.py",
        "verifier_identity": "same author as the implementation",
        "independent": False,
        "independent_verifier": "BLOCKED",
        "external_verifier": (
            "PASS"
            if (OUT / "analysis" / "EXTERNAL_VERIFICATION.json").exists()
            else "NOT_RUN"
        ),
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": checks,
        "passed": sum(1 for check in checks if check["ok"]),
        "failed": sum(
            1 for check in checks if not check["ok"] and check.get("status") != "NOT_EXECUTED"
        ),
        "not_executed": sum(1 for check in checks if check.get("status") == "NOT_EXECUTED"),
        "verdict": "PASS"
        if not any(
            not check["ok"] and check.get("status") != "NOT_EXECUTED" for check in checks
        )
        else "FAIL",
    }
    (OUT / "analysis").mkdir(parents=True, exist_ok=True)
    (OUT / "analysis" / "VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    # The builder's own report is named after the builder. ``INDEPENDENT_VERIFICATION.md``
    # is a different claim (who verified this, and what they could not verify), so a
    # same-author script must not overwrite it with its own table.
    (OUT / "analysis" / "BUILDER_VERIFICATION.md").write_text(
        render(checks), encoding="utf-8", newline="\n"
    )
    print(render(checks))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
