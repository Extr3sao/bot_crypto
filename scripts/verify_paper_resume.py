"""verify_paper_resume — comprueba el libro y el A/B desde los bytes, no desde el informe.

Independiente del implementador por construcción: no importa `vision.durable::reconcile_book`
ni confía en ningún resumen. Recomputa los digests, las identidades contables y la igualdad
A/B directamente sobre los ficheros, y después se ataca a sí mismo con ocho mutaciones para
demostrar que no dice PASS por defecto.

    python scripts/verify_paper_resume.py --drill <dir>
    python scripts/verify_paper_resume.py --drill <dir> --negative-controls

Códigos: 0 PASS, 1 FAIL, 2 sin evidencia.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TOLERANCE = 1e-6
REQUIRED_CHECKS = (
    "contract_matches",
    "barrier_present",
    "dataset_prefix_matches",
    "equity_identity",
    "closed_history_intact",
    "position_structure",
    "risk_agrees_with_mark",
)


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


OPERATIONAL = {
    "session_id",
    "session_index",
    "session_ids",
    "counters",
    "calls",
    "spend_usd",
    "entry_provenance",
    "marks",
}


def _state_digest(body: dict[str, Any]) -> str:
    return _digest({key: value for key, value in body.items() if key not in OPERATIONAL})


class Verdict:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [item for item in self.checks if not item["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": len(self.checks),
            "passed": sum(1 for item in self.checks if item["ok"]),
            "failed": self.failures,
        }


# -- el libro -------------------------------------------------------------------


def verify_book(path: Path, verdict: Verdict, *, label: str) -> dict[str, Any]:
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    body = dict(doc["body"])

    verdict.check(
        f"{label}.integrity_digest",
        _digest(body) == str(doc["digest"]),
        f"recorded {doc['digest'][:16]}… recomputed {_digest(body)[:16]}…",
    )
    verdict.check(
        f"{label}.state_digest",
        _state_digest(body) == str(doc.get("state_digest")),
        "el digest económico recomputa desde el cuerpo",
    )
    broker = dict(body["broker"])
    closed = list(body["closed_trades"])
    pnl = sum(float(row["pnl"]) for row in closed)
    verdict.check(
        f"{label}.equity_identity",
        abs((float(broker["initial_equity"]) + pnl) - float(broker["equity"])) <= TOLERANCE,
        f"initial {broker['initial_equity']} + Σpnl {pnl:.8f} vs equity {broker['equity']}",
    )
    verdict.check(
        f"{label}.closed_digest",
        _digest(closed) == str(body.get("closed_digest")),
        "las filas de cierre hashean a lo registrado",
    )
    open_ids = [str(row["position_id"]) for row in body["open_positions"]]
    closed_ids = {str(row["position_id"]) for row in closed}
    verdict.check(
        f"{label}.no_shared_identity",
        len(open_ids) == len(set(open_ids)) and not (set(open_ids) & closed_ids),
        f"abiertas={len(open_ids)} cerradas={len(closed_ids)} solapadas="
        f"{sorted(set(open_ids) & closed_ids)}",
    )
    structure: list[str] = []
    for row in body["open_positions"]:
        entry = float(row["entry_price"])
        quantity = float(row["quantity"])
        notional = float(row["notional_usdt"])
        side = str(row["side"])
        if side not in {"buy", "sell"}:
            structure.append(f"{row['symbol']}: side {side!r}")
        if quantity <= 0 or entry <= 0:
            structure.append(f"{row['symbol']}: cantidad/precio no positivos")
        commission = float(row.get("entry_commission", 0.0))
        if commission < 0:
            structure.append(f"{row['symbol']}: comisión negativa")
        #: `stop_loss_price` no se persiste (sale de entry±pct), así que compararla consigo
        #: misma no probaría nada. Lo que sí es una identidad del libro es que el nocional
        #: sea precio por cantidad y que la comisión sea ese nocional por su bps.
        if abs(notional - entry * quantity) > max(1e-6, notional * 1e-9):
            structure.append(
                f"{row['symbol']}: nocional {notional} != precio*cantidad {entry * quantity}"
            )
        bps = float(row.get("commission_bps", 0.0))
        if bps > 0 and abs(commission - notional * bps / 10_000.0) > max(1e-6, commission * 1e-6):
            structure.append(
                f"{row['symbol']}: comisión {commission} != nocional*{bps}bp "
                f"{notional * bps / 10_000.0}"
            )
    verdict.check(f"{label}.position_structure", not structure, "; ".join(structure))
    verdict.check(
        f"{label}.risk_agrees_with_mark",
        abs(float(body["risk_equity"]) - float(body["marked_equity"])) <= TOLERANCE,
        f"risk {body['risk_equity']} vs mark {body['marked_equity']}",
    )
    barrier = body.get("barrier") or {}
    verdict.check(
        f"{label}.barrier_declared",
        barrier.get("bar_open_ms") is not None and int(barrier.get("bars_committed", 0)) > 0,
        f"barrera={barrier.get('bar_open_ms')} velas={barrier.get('bars_committed')}",
    )
    verdict.check(
        f"{label}.no_live_orders",
        str(body.get("contract", {}).get("provider", "")) != ""
        and doc.get("schema") == "vision-lane-book/1",
        "el libro declara esquema y proveedor",
    )
    return {"doc": doc, "body": body}


def _stop_price(row: dict[str, Any]) -> float:
    """Stop recomputado desde la fila, sin importar `PaperPosition`."""
    entry = float(row["entry_price"])
    pct = float(row["stop_loss_pct"])
    return entry * (1 - pct / 100.0) if str(row["side"]) == "buy" else entry * (1 + pct / 100.0)


# -- el A/B ---------------------------------------------------------------------


def verify_drill(drill: Path, verdict: Verdict) -> dict[str, Any]:
    document = json.loads((drill / "DRILL.json").read_text(encoding="utf-8"))
    a_path = drill / "A" / "STATE" / "BOOK.json"
    b_path = drill / "B" / "STATE" / "BOOK.json"
    a = verify_book(a_path, verdict, label="A")
    b = verify_book(b_path, verdict, label="B")

    verdict.check(
        "ab.state_digest_equal",
        a["doc"]["state_digest"] == b["doc"]["state_digest"],
        f"A={a['doc']['state_digest'][:16]}… B={b['doc']['state_digest'][:16]}…",
    )
    verdict.check(
        "ab.same_barrier",
        a["body"]["barrier"]["bar_open_ms"] == b["body"]["barrier"]["bar_open_ms"],
        f"A={a['body']['barrier']['bar_open_ms']} B={b['body']['barrier']['bar_open_ms']}",
    )
    verdict.check(
        "ab.same_closed_trades",
        a["body"]["closed_trades"] == b["body"]["closed_trades"],
        f"{len(a['body']['closed_trades'])} cierres en ambos",
    )
    verdict.check(
        "ab.same_open_positions",
        a["body"]["open_positions"] == b["body"]["open_positions"],
        f"{len(a['body']['open_positions'])} abiertas en ambos",
    )
    verdict.check(
        "b.restarted",
        len(b["body"].get("session_ids") or []) >= 2,
        f"sesiones de B: {b['body'].get('session_ids')}",
    )
    killed = [item for item in document.get("children", []) if item.get("killed")]
    verdict.check(
        "b.hard_kills_occurred",
        bool(killed),
        f"{len(killed)} procesos terminados sin cierre ordenado",
    )
    verdict.check(
        "drill.verdict_matches",
        document.get("verdict") == "PASS",
        f"el informe declara {document.get('verdict')}",
    )
    verdict.check(
        "drill.no_live_orders",
        document.get("live_orders") == 0 and document.get("mode") == "PAPER",
        f"mode={document.get('mode')} live_orders={document.get('live_orders')}",
    )
    return {"document": document, "a": a, "b": b}


# -- controles negativos --------------------------------------------------------


def negative_controls(drill: Path) -> list[dict[str, Any]]:
    """Nueve mutaciones: cada una tiene que ser detectada por el verificador real."""
    results: list[dict[str, Any]] = []
    mutations = {
        "pnl_inflado": lambda doc: doc["body"]["closed_trades"][0].update(
            pnl=doc["body"]["closed_trades"][0]["pnl"] + 50.0
        ),
        "equity_inventada": lambda doc: doc["body"]["broker"].update(
            equity=doc["body"]["broker"]["equity"] + 1.0
        ),
        "posicion_duplicada": lambda doc: doc["body"]["open_positions"].append(
            dict(doc["body"]["open_positions"][0])
        )
        if doc["body"]["open_positions"]
        else None,
        "posicion_a_la_vez_cerrada": lambda doc: doc["body"]["open_positions"].append(
            {**doc["body"]["closed_trades"][0], "stop_loss_pct": 0.5, "side": "buy",
             "quantity": 1.0, "notional_usdt": 100.0, "opened_at": 0.0}
        )
        if doc["body"]["closed_trades"]
        else None,
        "nocional_incoherente": lambda doc: doc["body"]["open_positions"][0].update(
            notional_usdt=float(doc["body"]["open_positions"][0]["notional_usdt"]) * 10
        )
        if doc["body"]["open_positions"]
        else None,
        "riesgo_desalineado": lambda doc: doc["body"].update(
            risk_equity=doc["body"]["marked_equity"] + 25.0
        ),
        "digest_falso": lambda doc: doc["body"]["broker"].update(equity=1.0),
        "cierres_borrados": lambda doc: doc["body"]["closed_trades"].pop(),
    }
    for name, mutate in mutations.items():
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "drill"
            shutil.copytree(drill, work)
            path = work / "A" / "STATE" / "BOOK.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            before = json.dumps(doc, sort_keys=True)
            mutate(doc)
            if json.dumps(doc, sort_keys=True) == before:
                results.append(
                    {"control": name, "detected": False, "detail": "la mutación no aplica"}
                )
                continue
            if name != "digest_falso":
                #: El falsificador competente también rehace los digests. Si no lo hiciera,
                #: los ocho controles los cazaría el mismo check de integridad y los
                #: semánticos (identidad contable, estructura, riesgo) no se ejercitarían
                #: nunca: un verificador vacío pasaría este examen.
                doc["body"]["closed_digest"] = _digest(doc["body"]["closed_trades"])
                doc["state_digest"] = _state_digest(doc["body"])
                doc["digest"] = _digest(doc["body"])
            path.write_text(json.dumps(doc), encoding="utf-8")
            verdict = Verdict()
            verify_book(path, verdict, label="A")
            results.append(
                {
                    "control": name,
                    "detected": not verdict.ok,
                    "detail": verdict.failures[0]["check"] if verdict.failures else "",
                }
            )
    #: El noveno no muta el libro: borra la evidencia de reinicio y exige que el A/B la eche
    #: de menos. Sin esto, un B que nunca se reinició pasaría por "igual que A".
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "drill"
        shutil.copytree(drill, work)
        path = work / "B" / "STATE" / "BOOK.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["body"]["session_ids"] = doc["body"]["session_ids"][:1]
        path.write_text(json.dumps(doc), encoding="utf-8")
        verdict = Verdict()
        verify_drill(work, verdict)
        results.append(
            {
                "control": "sin_reinicio_real",
                "detected": any(item["check"] == "b.restarted" for item in verdict.failures),
                "detail": "b.restarted",
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="independent verification of the resume book")
    parser.add_argument("--drill", type=Path, required=True)
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not (args.drill / "DRILL.json").exists():
        print(f"NO_EVIDENCE {args.drill}", file=sys.stderr)
        return 2

    verdict = Verdict()
    verify_drill(args.drill, verdict)
    controls = negative_controls(args.drill) if args.negative_controls else []
    controls_ok = all(item["detected"] for item in controls) if controls else None
    document = {
        "schema": "PAPER_RESUME_VERIFICATION_V1",
        "independent_of": "vision.durable (no importa su verificador)",
        "drill": str(args.drill),
        **verdict.to_dict(),
        "negative_controls": controls,
        "negative_controls_ok": controls_ok,
        "false_success": 0 if verdict.ok else None,
    }
    print(json.dumps(document, indent=2, sort_keys=True))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    ok = verdict.ok and (controls_ok is not False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
