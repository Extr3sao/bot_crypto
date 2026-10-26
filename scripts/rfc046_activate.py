"""RFC-046 governance activation (owner decision 2026-10-08, option 5A).

This script applies the seven changes the owner approved, and nothing else:

1. ADR-0024 in ``tasks/decisions.md`` (the approval record itself).
2. A dated, limited exemption in ``docs/research/BUSINESS_REENTRY_POLICY`` (.md + .json)
   and in its generator ``scripts/rfc041_run.py`` so a regeneration preserves it.
   ``G_BUSINESS_REENTRY`` stays ``NOT_PASS``.
3. The operating-model trigger (``docs/research/PROFITABILITY_OPERATING_MODEL`` .json + .md,
   generator ``scripts/rfc043_run.py``) so Controlled Discovery can start.
4. Formal closure of the RFC-035 freeze in ``docs/governance/PROFITABILITY_FIRST_FREEZE.md``
   (addendum at the top + closure section at the end; body preserved).
5. Phase 10 in ``tasks/roadmap.md``.
6. Versioned ``docs/roadmap/RFC_REGISTRY.json`` built from ``data/rfc046/audit.json``.
7. RFC-046 status flip to APPROVED / ACTIVE in its own .md + .json.

Every edit is fail-closed: if the expected text is missing or appears more than once, the
script raises instead of guessing. It is idempotent (markers are checked before writing), so
re-running it after a partial failure is safe. It writes no market data and touches no
runtime module.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ADR_ID = "ADR-0024"
APPROVAL_DATE = "2026-10-08"
MARK = "RFC-046 ACTIVATION"  # idempotency marker for appended sections

EXEMPTION_MARK = "EXCEPCION LIMITADA Y FECHADA"
FREEZE_MARK = "ADDENDUM DE CIERRE"
ROADMAP_MARK = "## Fase 10 - Investigacion cuantitativa controlada (RFC-046)"
REGISTRY_PATH = REPO / "docs" / "roadmap" / "RFC_REGISTRY.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = read(path)
    if old not in text and new in text:
        print(f"skip (already applied): {label}")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 occurrence in {path}, found {count}")
    write(path, text.replace(old, new, 1))


def append_once(path: Path, block: str, marker: str, label: str) -> None:
    text = read(path)
    if marker in text:
        print(f"skip (already applied): {label}")
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + block)
    print(f"applied: {label}")


def insert_after_h1(path: Path, block: str, marker: str, label: str) -> None:
    text = read(path)
    if marker in text:
        print(f"skip (already applied): {label}")
        return
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("# "):
        raise SystemExit(f"{label}: {path} does not start with an H1")
    write(path, lines[0] + "\n" + block + "".join(lines[1:]))
    print(f"applied: {label}")


# --------------------------------------------------------------------------- #
# 1 - ADR-0024
# --------------------------------------------------------------------------- #

ADR_0024 = f"""
## {ADR_ID} - RFC-046: excepcion limitada y fechada de RFC-041 para Controlled Discovery (offline)

> {MARK} — registrada el {APPROVAL_DATE}. No usa footnotes "next free" (regla post-ADR-0023).

- **Estado**: Decidido y aprobado por el propietario.
- **Contexto**: RFC-035 cerro sin candidato (`CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY`,
  `REPLICATE_P0 = NONE`) y RFC-041 dejo el proyecto sin siguiente movimiento admitido: su gate
  `G_BUSINESS_REENTRY` exige un trigger cualificado (A-E) y ninguno ha disparado. La unica via
  que RFC-041 admite es nueva evidencia externa o un cambio estructural, lo que impide buscar
  ventaja economica internamente. RFC-046 propone investigacion cuantitativa controlada, offline,
  preregistrada y con presupuesto cerrado.
- **Opciones**:
  - esperar un trigger cualificado (coste: parada indefinida, sin linea de investigacion);
  - excepcion general a RFC-041 (rechazada: abriria produccion sin evidencia);
  - excepcion limitada, fechada y offline (aprobada, opcion 5A).
- **Decision**: opcion **5A**. Se aprueba una excepcion especifica de RFC-041 que activa RFC-046
  **exclusivamente en investigacion offline**. `G_BUSINESS_REENTRY` permanece **distinto de PASS**.
  No se autoriza paper, live, ordenes reales, despliegue de capital, promocion automatica,
  modificacion automatica del Risk Engine, ni optimizacion sobre OOS.
- **Razon**: permite buscar ventaja economica neta con un presupuesto acotado y evidencia
  verificable, sin relajar ninguna puerta de produccion ni reescribir los contratos historicos.
- **Consecuencias aplicadas en esta activacion**:
  - `RFC-046 = APPROVED / ACTIVE`; `DISCOVERY_OFFLINE = AUTHORIZED`; `LIVE_TRADING = DISABLED`;
    `TRADES_AUTHORIZED = 0`; `G_BUSINESS_REENTRY != PASS`; `RISK_ENGINE = DETERMINISTIC`;
    `BUILDER != VERIFIER`; `FALSE_SUCCESS = 0`.
  - Excepcion fechada en `docs/research/BUSINESS_REENTRY_POLICY.*`.
  - Trigger de `docs/research/PROFITABILITY_OPERATING_MODEL.*` ampliado solo para Controlled Discovery.
  - Cierre formal de `docs/governance/PROFITABILITY_FIRST_FREEZE.md` (evidencia RFC-035 conservada).
  - `Fase 10` en `tasks/roadmap.md` y registro de identificadores `docs/roadmap/RFC_REGISTRY.json`.
  - Parada: `docs/governance/DISCOVERY_STOP_RULES.md`. Agotado el presupuesto o fallada la campana
    se emite `DISCOVERY_CAMPAIGN_FAILED` y **no hay refill automatico de hipotesis**.
  - Revocable por el propietario en cualquier momento; sin efecto sobre produccion.
"""


def activate_adr() -> None:
    path = REPO / "tasks" / "decisions.md"
    if f"## {ADR_ID}" in read(path):
        print("skip (already applied): ADR-0024")
        return
    append_once(path, ADR_0024, f"## {ADR_ID} - RFC-046", "ADR-0024")


# --------------------------------------------------------------------------- #
# 2 - RFC-041 limited exemption
# --------------------------------------------------------------------------- #

EXEMPTION_MD = f"""> **{EXEMPTION_MARK} — RFC-046 (aprobada {APPROVAL_DATE}, ADR-0024)**
> El propietario aprueba la alternativa **5A**: una excepcion especifica de RFC-041 que activa
> RFC-046 **exclusivamente en investigacion offline** (Controlled Discovery). Esta excepcion:
> - **no** modifica `G_BUSINESS_REENTRY`, que permanece **distinto de PASS**;
> - **no** autoriza paper, live, ordenes reales ni despliegue de capital (`TRADES_AUTHORIZED = 0`);
> - **no** relaja `business_edge_requirement` ni los `reject_conditions` de este documento;
> - solo admite investigacion offline preregistrada bajo `docs/governance/DISCOVERY_ADMISSION_POLICY.md`
>   y `docs/governance/DISCOVERY_STOP_RULES.md`;
> - esta fechada, es revocable, y su alcance se agota con el stop rule de RFC-046.
> La unica puerta que abre es la de investigacion; todas las puertas de produccion siguen intactas.

"""

EXEMPTION_JSON = {
    "rfc046_limited_exemption": {
        "approved_by": "owner",
        "approved_at": APPROVAL_DATE,
        "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
        "scope": "Controlled Discovery (RFC-046): offline hypotheses, offline experiments, independent verification",
        "not_authorized": [
            "paper trading",
            "live trading",
            "real orders",
            "capital deployment",
            "automatic promotion",
            "automatic risk-engine modification",
            "OOS optimisation",
        ],
        "gate_state": {
            "G_BUSINESS_REENTRY": "NOT_PASS",
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
        },
        "stop": "DISCOVERY_STOP_RULES.md; no automatic refill; revocable by the owner",
        "adr": f"tasks/decisions.md {ADR_ID}",
    }
}

EXEMPTION_PY = """        "rfc046_limited_exemption": {
            "approved_by": "owner",
            "approved_at": "2026-10-08",
            "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
            "gate_state": {"G_BUSINESS_REENTRY": "NOT_PASS", "LIVE_TRADING": "DISABLED", "TRADES_AUTHORIZED": 0},
            "adr": "tasks/decisions.md ADR-0024",
        },
        "next_rfc_requires": "G_BUSINESS_REENTRY = PASS","""


def activate_reentry() -> None:
    insert_after_h1(
        REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.md",
        EXEMPTION_MD,
        EXEMPTION_MARK,
        "business reentry exemption (md)",
    )
    json_path = REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.json"
    policy = json.loads(read(json_path))
    if "rfc046_limited_exemption" not in policy:
        merged: dict[str, Any] = {}
        for key, value in policy.items():
            if key == "next_rfc_requires":
                merged.update(EXEMPTION_JSON)
            merged[key] = value
        if "rfc046_limited_exemption" not in merged:
            raise SystemExit("business reentry json: next_rfc_requires anchor not found")
        write(json_path, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        print("applied: business reentry exemption (json)")
    else:
        print("skip (already applied): business reentry exemption (json)")
    replace_once(
        REPO / "scripts" / "rfc041_run.py",
        '        "next_rfc_requires": "G_BUSINESS_REENTRY = PASS",',
        EXEMPTION_PY,
        "business reentry generator",
    )


# --------------------------------------------------------------------------- #
# 3 - operating-model trigger
# --------------------------------------------------------------------------- #

OLD_TRIGGER_JSON = (
    '"trigger": "ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE '
    'reopens evaluation",'
)
NEW_TRIGGER_JSON = """"trigger": "ONLY a NEW QUALIFIED OPPORTUNITY, a MATERIAL CAPITAL / INSTRUMENT CHANGE, or the owner-approved RFC-046 limited exemption of 2026-10-08 (offline research only) reopens evaluation",
    "rfc046_limited_exemption": {
      "approved_by": "owner",
      "approved_at": "2026-10-08",
      "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
      "scope": "Controlled Discovery (RFC-046): offline hypotheses, offline experiments, independent verification",
      "not_authorized": [
        "paper trading",
        "live trading",
        "real orders",
        "capital deployment",
        "automatic promotion",
        "automatic risk-engine modification",
        "OOS optimisation"
      ],
      "gate_state": {"G_BUSINESS_REENTRY": "NOT_PASS", "LIVE_TRADING": "DISABLED", "TRADES_AUTHORIZED": 0},
      "stop": "DISCOVERY_STOP_RULES.md; no automatic refill; revocable by the owner",
      "adr": "tasks/decisions.md ADR-0024"
    },"""

OLD_TRIGGER_MD = (
    "  - **trigger**: ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE "
    "reopens evaluation"
)
NEW_TRIGGER_MD = """  - **trigger**: ONLY a NEW QUALIFIED OPPORTUNITY, a MATERIAL CAPITAL / INSTRUMENT CHANGE, or the owner-approved RFC-046 limited exemption of 2026-10-08 (offline research only) reopens evaluation
  - **rfc046_limited_exemption**: approved by owner 2026-10-08 (option 5A); offline Controlled Discovery only; `G_BUSINESS_REENTRY` stays NOT_PASS; no paper, no live, no orders (`TRADES_AUTHORIZED = 0`); stop rule + no refill; ADR-0024"""

OLD_TRIGGER_PY = """            "trigger": (
                "ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT "
                "CHANGE reopens evaluation"
            ),"""
NEW_TRIGGER_PY = """            "trigger": (
                "ONLY a NEW QUALIFIED OPPORTUNITY, a MATERIAL CAPITAL / INSTRUMENT "
                "CHANGE, or the owner-approved RFC-046 limited exemption of 2026-10-08 "
                "(offline research only) reopens evaluation"
            ),
            "rfc046_limited_exemption": {
                "approved_by": "owner",
                "approved_at": "2026-10-08",
                "decision": "option 5A - specific, dated RFC-041 exemption; offline research only",
                "gate_state": {
                    "G_BUSINESS_REENTRY": "NOT_PASS",
                    "LIVE_TRADING": "DISABLED",
                    "TRADES_AUTHORIZED": 0,
                },
                "adr": "tasks/decisions.md ADR-0024",
            },"""


def activate_trigger() -> None:
    replace_once(
        REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json",
        OLD_TRIGGER_JSON,
        NEW_TRIGGER_JSON,
        "operating model trigger (json)",
    )
    replace_once(
        REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.md",
        OLD_TRIGGER_MD,
        NEW_TRIGGER_MD,
        "operating model trigger (md)",
    )
    replace_once(
        REPO / "scripts" / "rfc043_run.py",
        OLD_TRIGGER_PY,
        NEW_TRIGGER_PY,
        "operating model trigger (generator)",
    )


# --------------------------------------------------------------------------- #
# 4 - RFC-035 freeze closure
# --------------------------------------------------------------------------- #

FREEZE_ADDENDUM = f"""> **{FREEZE_MARK} — {APPROVAL_DATE} (RFC-046 activation, {ADR_ID})**
> RFC-035 ha cerrado con `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY` (`REPLICATE_P0 = NONE`) y el
> propietario ha aprobado la alternativa 5A: una excepcion limitada y fechada de RFC-041 que activa
> RFC-046 **solo en investigacion offline**. Este documento se conserva **integro** como registro
> historico de la politica `PROFITABILITY-FIRST-2026-002`; su estado operativo pasa a
> `CLOSED_RFC035_ENDED` (ver "## 8. Cierre formal" al final). El cuerpo anterior no se reescribe.

"""

FREEZE_CLOSURE = f"""

## 8. Cierre formal ({APPROVAL_DATE}) — {MARK}

- **Estado del freeze**: `CLOSED_RFC035_ENDED`. La politica `PROFITABILITY-FIRST-2026-002` deja de
  estar activa porque RFC-035 termino con `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY`
  (`reports/profitability_gate035/FINAL_REPORT.json`).
- **Evidencia conservada**: los artefactos de RFC-035 (runds, verificaciones, `gates.json`, captura
  de 24 h) permanecen donde estaban; este cierre no borra ni reescribe ninguno. El archivo se
  versiona en git a partir de esta fecha (antes vivia sin versionar, TD-5).
- **Que sustituye a este freeze**: la admision y la parada de la investigacion pasan a
  `docs/governance/DISCOVERY_ADMISSION_POLICY.md` y `docs/governance/DISCOVERY_STOP_RULES.md`,
  bajo RFC-046 (`APPROVED / ACTIVE`, {ADR_ID}).
- **Que NO cambia**: `G_BUSINESS_REENTRY` sigue **distinto de PASS**, `LIVE_TRADING` sigue
  **DISABLED**, `TRADES_AUTHORIZED = 0`, y ninguna familia cerrada por RFC-041 puede reentrar
  renombrada. El cierre de este freeze no es una promocion ni una relajacion.
"""


def activate_freeze() -> None:
    insert_after_h1(
        REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md",
        FREEZE_ADDENDUM,
        FREEZE_MARK,
        "RFC-035 freeze addendum",
    )
    append_once(
        REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md",
        FREEZE_CLOSURE,
        f"{MARK}",
        "RFC-035 freeze closure section",
    )


# --------------------------------------------------------------------------- #
# 5 - Phase 10 in the roadmap
# --------------------------------------------------------------------------- #

PHASE_10 = f"""{ROADMAP_MARK}

- Vehiculo: `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` — `APPROVED / ACTIVE` desde {APPROVAL_DATE} ({ADR_ID}).
- Alcance: investigacion **offline** con presupuesto cerrado (3 hipotesis maximo, 1 candidata por
  hipotesis); sin promocion automatica a paper ni a live.
- Puertas: `PROFITABILITY_GATE_V1` (`docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json`) y el coste auditado
  de **23.7906 bps** round-trip (Binance Spot VIP0, taker, ~1.000 USD notional; stress 1.5x = 35.6859 bps).
- Politicas: admision `docs/governance/DISCOVERY_ADMISSION_POLICY.md`, parada
  `docs/governance/DISCOVERY_STOP_RULES.md`, flujo `docs/architecture/DISCOVERY_EXECUTION_FLOW.md`.
- Evidencia: cada ejecucion versiona `RUN_REPORT.md` / `RUN_REPORT.json`; `FALSE_SUCCESS = 0`;
  `BUILDER != VERIFIER`.
- Parada: agotado el presupuesto se emite `DISCOVERY_CAMPAIGN_FAILED` (por candidata:
  `CANDIDATE_REJECTED`) y la campana se detiene **sin refill automatico** de hipotesis.
- Runtime invariante: `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`, `G_BUSINESS_REENTRY != PASS`.

"""


def activate_roadmap() -> None:
    path = REPO / "tasks" / "roadmap.md"
    text = read(path)
    if ROADMAP_MARK in text:
        print("skip (already applied): roadmap phase 10")
        return
    anchor = "## Regla de salto"
    if text.count(anchor) != 1:
        raise SystemExit("roadmap: 'Regla de salto' anchor not unique")
    write(path, text.replace(anchor, PHASE_10 + anchor, 1))
    print("applied: roadmap phase 10")


# --------------------------------------------------------------------------- #
# 6 - RFC identifier registry
# --------------------------------------------------------------------------- #

REGISTRY_RULE = (
    "A new RFC number must be checked against this registry first. The next free number is the "
    "smallest integer above 046 that this registry does not list as occupied. Numbers are never "
    "reused. 045 stays empty by control: four campaign verifiers assert that no RFC-045 artefact "
    "exists, so filling it would break a real invariant rather than merely reuse a number."
)


def build_registry() -> None:
    audit = json.loads(read(REPO / "data" / "rfc046" / "audit.json"))
    collision = audit["governance"]["collision"]
    numbers: dict[str, dict[str, Any]] = {}
    for number, entry in collision["occupied"].items():
        declared = entry.get("declared_in_tracked_docs") or []
        artefacts_versioned = bool(entry.get("artefacts_versioned"))
        if artefacts_versioned:
            strength = "VERSIONED_ARTEFACT"
        elif declared:
            strength = "TRACKED_DOCUMENT"
        else:
            strength = "UNVERSIONED_ARTEFACT"
        numbers[number] = {
            "state": "OCCUPIED",
            "declaration_strength": strength,
            "declared_in_tracked_docs": declared,
            "artefacts_versioned": artefacts_versioned,
            "artefact_count": len(entry.get("artefacts") or []),
        }
    for number, entry in collision["vacant_by_control"].items():
        numbers[number] = {
            "state": "VACANT_BY_CONTROL",
            "reason": entry.get("reason"),
            "asserting_files": entry.get("asserting_files"),
            "assertion_count": entry.get("assertion_count"),
        }
    taken = collision["taken_by_this_rfc"]["046"]
    numbers["046"] = {
        "state": "OCCUPIED",
        "declaration_strength": "TRACKED_DOCUMENT",
        "declared_in_tracked_docs": ["docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md"],
        "artefacts_versioned": True,
        "artefact_count": 2,
        "occupant": "RFC-046 CONTROLLED QUANTITATIVE STRATEGY DISCOVERY",
        "status": "APPROVED / ACTIVE",
        "approved_at": APPROVAL_DATE,
        "approval_record": f"tasks/decisions.md {ADR_ID}",
        "prior_artefacts": taken.get("prior_artefacts") or [],
        "mentions_only_before_this_rfc": taken.get("naming_mentions")
        or taken.get("mentions")
        or [],
    }
    unversioned = sorted(
        n for n, e in numbers.items() if e.get("declaration_strength") == "UNVERSIONED_ARTEFACT"
    )
    registry = {
        "registry": "RFC_IDENTIFIER_REGISTRY",
        "schema_version": 1,
        "updated_at_utc": f"{APPROVAL_DATE}T00:00:00Z (activation; timestamps are author-declared, TD-4)",
        "source_of_truth": "data/rfc046/audit.json (artefact scan + tracked-document declarations)",
        "generated_by": "scripts/rfc046_activate.py",
        "allocation_rule": REGISTRY_RULE,
        "next_free_number_above_046": _next_free(numbers),
        "current_rfc": {
            "number": "046",
            "status": "APPROVED / ACTIVE",
            "approval": f"{ADR_ID} ({APPROVAL_DATE})",
            "offline_only": True,
        },
        "counts": {
            "occupied": sum(1 for e in numbers.values() if e["state"] == "OCCUPIED"),
            "vacant_by_control": sum(
                1 for e in numbers.values() if e["state"] == "VACANT_BY_CONTROL"
            ),
            "unversioned_occupancy": len(unversioned),
        },
        "unversioned_occupancy_numbers": unversioned,
        "numbers": dict(sorted(numbers.items())),
        "known_limitations": [
            "Occupancy was reconstructed from artefacts and tracked documents, not from a historical "
            "registry (none existed before this file).",
            "Artefacts under reports/* are gitignored, so 'versioned artefact' means the declaration is "
            "tracked, not the artefact.",
            "A snapshot ages: an RFC artefact added later by another workstream must be added here.",
        ],
    }
    write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    print(f"applied: RFC registry ({registry['counts']})")


def _next_free(numbers: dict[str, dict[str, Any]]) -> str:
    for candidate in range(47, 1000):
        if f"{candidate:03d}" not in numbers:
            return f"{candidate:03d}"
    raise SystemExit("registry: no free number below 1000")


# --------------------------------------------------------------------------- #
# 7 - RFC-046 status flip
# --------------------------------------------------------------------------- #


def activate_rfc046() -> None:
    json_path = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
    state = json.loads(read(json_path))
    if state.get("status") == "APPROVED":
        print("skip (already applied): RFC-046 status")
    else:
        state["status"] = "APPROVED"
        state["approved"] = True
        state["active"] = True
        state["approval"] = {
            "approved_by": "owner",
            "approved_at": APPROVAL_DATE,
            "decision": "option 5A - specific, dated RFC-041 exemption",
            "scope": "offline controlled discovery only",
            "adr": f"tasks/decisions.md {ADR_ID}",
            "activates": [
                "docs/research/BUSINESS_REENTRY_POLICY.md - dated exemption applied",
                "docs/research/PROFITABILITY_OPERATING_MODEL.json - trigger amended",
                "docs/governance/PROFITABILITY_FIRST_FREEZE.md - RFC-035 freeze closed",
                "tasks/roadmap.md - Fase 10 added",
                "docs/roadmap/RFC_REGISTRY.json - registry created",
            ],
        }
        state["runtime_state"]["discovery_offline_authorized"] = True
        state["runtime_state"]["live_trading_enabled"] = False
        state["runtime_state"]["trades_authorized"] = 0
        state["runtime_state"]["profitability_verified"] = False
        state["next_gate"] = "FIRST_CAMPAIGN_RUN_AND_INDEPENDENT_VERIFICATION"
        state["invariants_while_active"] = {
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "G_BUSINESS_REENTRY": "NOT_PASS",
            "RISK_ENGINE": "DETERMINISTIC",
            "BUILDER": "NOT_VERIFIER",
            "FALSE_SUCCESS": 0,
            "real_orders": "REFUSED_BY_POLICY",
        }
        del state["invariants_while_proposed"]
        del state["required_amendments_before_activation"]
        write(json_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        print("applied: RFC-046 status (json)")

    md_path = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.md"
    text = read(md_path)
    if "APPROVAL RECORD" in text:
        print("skip (already applied): RFC-046 status (md)")
        return
    replacements = [
        (
            "| STATUS | **PROPOSED — NOT APPROVED — NOT ACTIVE** |",
            "| STATUS | **APPROVED / ACTIVE — owner decision 2026-10-08 (option 5A, ADR-0024)** |",
        ),
        (
            "| MODE | documentation and governance only; no programme is running |",
            "| MODE | offline controlled quantitative research (`DISCOVERY_OFFLINE = AUTHORIZED`); no paper, no live |",
        ),
    ]
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"rfc046 md: anchor not unique: {old}")
        text = text.replace(old, new, 1)
    proposal_note = re.search(
        r"> \*\*This document is a proposal\.\*\*.*?Until then the correct action is route A: wait\.",
        text,
        flags=re.DOTALL,
    )
    if not proposal_note:
        raise SystemExit("rfc046 md: proposal note not found")
    text = text.replace(
        proposal_note.group(0),
        "> **This document is a decision now.** The owner approved option 5A on 2026-10-08 "
        "(`tasks/decisions.md ADR-0024`): RFC-046 is **APPROVED / ACTIVE for offline research only**. "
        "`G_BUSINESS_REENTRY` stays `NOT_PASS`, `LIVE_TRADING` stays `DISABLED`, `TRADES_AUTHORIZED` stays `0`. "
        "The approval authorizes no capital and no production promotion.",
        1,
    )
    approval_section = f"""
## 00 — APPROVAL RECORD ({APPROVAL_DATE})

- **Decision**: option 5A — a specific, dated RFC-041 exemption that activates RFC-046 **only in
  offline research**.
- **Recorded in**: `tasks/decisions.md {ADR_ID}`.
- **Applied changes**: dated exemption in `docs/research/BUSINESS_REENTRY_POLICY.*`; trigger amended in
  `docs/research/PROFITABILITY_OPERATING_MODEL.*`; RFC-035 freeze closed in
  `docs/governance/PROFITABILITY_FIRST_FREEZE.md`; `Fase 10` in `tasks/roadmap.md`; identifier registry
  `docs/roadmap/RFC_REGISTRY.json`.
- **Unchanged**: `G_BUSINESS_REENTRY != PASS`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
  `RISK_ENGINE = DETERMINISTIC`, `BUILDER != VERIFIER`, `FALSE_SUCCESS = 0`, and every RFC-041 reject
  condition. The approval opens the research door only.
- **Stop**: `docs/governance/DISCOVERY_STOP_RULES.md`; `DISCOVERY_CAMPAIGN_FAILED` ends the programme
  with no automatic refill.
"""
    marker = "## 01 — PRESERVE EXISTING AUTHORITY"
    if text.count(marker) != 1:
        raise SystemExit("rfc046 md: section 01 anchor not unique")
    text = text.replace(marker, approval_section.strip() + "\n\n" + marker, 1)
    state_lines = (
        (
            "RFC-046        = PROPOSED",
            "RFC-046        = APPROVED / ACTIVE (2026-10-08, option 5A)",
        ),
        ("DISCOVERY      = NOT_ACTIVE", "DISCOVERY      = ACTIVE (offline only)"),
        (
            "Until explicit approval of the governance change:",
            "Owner decision 2026-10-08 (ADR-0024). The pre-approval state is kept for the record:",
        ),
        (
            "After the governance change is approved and the four amendments in §12.3 are registered:",
            "Applied on 2026-10-08 (ADR-0024), together with the RFC identifier registry:",
        ),
    )
    for old, new in state_lines:
        if text.count(old) != 1:
            raise SystemExit(f"rfc046 md: state line not found or ambiguous: {old!r}")
        text = text.replace(old, new, 1)
    write(md_path, text)
    print("applied: RFC-046 status (md)")


def main() -> int:
    activate_adr()
    activate_reentry()
    activate_trigger()
    activate_freeze()
    activate_roadmap()
    build_registry()
    activate_rfc046()
    print("RFC-046 activation complete; rebuild data/rfc046/audit.json next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
