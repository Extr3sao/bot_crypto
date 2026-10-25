# PROFITABILITY_FIRST_FREEZE

> **ADDENDUM DE CIERRE — 2026-10-08 (RFC-046 activation, ADR-0024)**
> RFC-035 ha cerrado con `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY` (`REPLICATE_P0 = NONE`) y el
> propietario ha aprobado la alternativa 5A: una excepcion limitada y fechada de RFC-041 que activa
> RFC-046 **solo en investigacion offline**. Este documento se conserva **integro** como registro
> historico de la politica `PROFITABILITY-FIRST-2026-002`; su estado operativo pasa a
> `CLOSED_RFC035_ENDED` (ver "## 8. Cierre formal" al final). El cuerpo anterior no se reescribe.


- policy_id: PROFITABILITY-FIRST-2026-002
- ACTIVE_RFC: **RFC-035 — EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY**
- mode: `PROFITABILITY_FIRST`
- status: **ACTIVE** while RFC-035 is open
- relation to prior governance: runs *inside* RFC-041 `BUSINESS-FREEZE-2026-001`
 (`docs/research/BUSINESS_REENTRY_POLICY.md`, `docs/research/ECONOMIC_STATE.json`). It does not lift the
 business freeze; it is the evidence-collection mechanism that freeze requires (trigger A).

## 1. Purpose

While RFC-035 is active, work is admitted only if it moves the single question:

> Does at least one **external** trading opportunity carry enough evidence to justify an exact replication
> inside Trading Agentic Portable?

Anything else is a distraction and is deferred, however interesting it is.

## 2. Frozen (do not start while RFC-035 is active)

```text
new agents
new strategy generators
new indicators without an external hypothesis
new orchestration frameworks
dynamic routing
memory improvements
new dashboards
UI redesign
self-improvement loops
new sentiment agents
new macro agents
new execution features
new optimization engines
```

Also frozen, as a direct consequence of the mission (§12 of the RFC): our own backtest, parameter search,
asset sweep, timeframe sweep, ensemble building, strategy modification, and any change to CAP-004.

## 3. Admission form (every piece of new work)

Before any new artifact is created, it must declare, in this order:

```text
ACTIVE_RFC       = RFC-035
DIRECT_PROFITABILITY_LINK = <how it changes the RFC-035 answer>
BLOCKER_IF_NOT_IMPLEMENTED = <what RFC-035 cannot conclude without it>
EVIDENCE        = <file or measurement that shows it>
```

If `DIRECT_PROFITABILITY_LINK` cannot be filled with something that changes the RFC-035 verdict:

```text
DEFER
```

A `DEFER` is not a rejection of the idea; it is a postponement beyond RFC-035.

## 4. Single exception

```text
BLOCKER_FOR_RFC035
```

Work that is not itself research may be done only when it is a **demonstrated blocker**: it must already
have produced a wrong or unusable verdict, an unreadable artifact, or an unrecordable measurement.
Example already used in this RFC: the CAP-004C verifier published `storage_not_verified` when run under an
interpreter that lacked the project dependencies — an environment artefact presented as a storage verdict.
That blocked certifying the RFC-035 baseline, so a fail-closed guard was added. Nothing else qualified.

## 5. Evidence hierarchy (unchanged, applied by the source registry)

```text
REAL_EXECUTION > FORWARD_PAPER > INDEPENDENT_REPLICATION > REPRODUCIBLE_CODE
> ACADEMIC_PAPER > AUTHOR_BACKTEST > UNVERIFIED_CLAIM
```

Unavailable to this RFC by construction: REAL_EXECUTION, FORWARD_PAPER (of an external line) and
INDEPENDENT_REPLICATION (of an external line). Therefore no RFC-035 verdict may claim, imply or paraphrase
`EDGE_CONFIRMED`, `PROFITABLE`, `READY_FOR_LIVE`. The only admissible positive verdict is
`EXTERNAL_OPPORTUNITY_WORTH_REPLICATING`.

## 6. Reject conditions inherited from the reentry policy

```text
new RSI variation · different moving average · different threshold · another crypto pair
more LLM agents · new sentiment source · adding ML to old features
parameter optimization · same strategy with renamed rules
```

Consequence for RFC-035: an external paper that re-describes a family the project has already closed
(price-directional momentum, cross-sectional momentum/reversal/low-vol, tick order-flow imbalance, carry)
cannot enter as a "new" opportunity. It must be registered against the closed line, with the internal
result attached as counter-evidence.

## 7. Exit condition

RFC-035 ends with exactly one of:

```text
PASS            — one REPLICATE_P0 selected, frozen, independently verified
NO_SUITABLE_OPPORTUNITY  — registry complete, no candidate clears the minimum-evidence filter
FAIL            — an inconsistency was found in the selected candidate at verification
```

On PASS, this freeze remains active until RFC-036 (replication spec) is authorized; the next gate is
`RFC-036_IMMUTABLE_STRATEGY_REPLICATION_SPEC`, never live trading and never ALPHA-004.


## 8. Cierre formal (2026-10-08) — RFC-046 ACTIVATION

- **Estado del freeze**: `CLOSED_RFC035_ENDED`. La politica `PROFITABILITY-FIRST-2026-002` deja de
  estar activa porque RFC-035 termino con `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY`
  (`reports/profitability_gate035/FINAL_REPORT.json`).
- **Evidencia conservada**: los artefactos de RFC-035 (runds, verificaciones, `gates.json`, captura
  de 24 h) permanecen donde estaban; este cierre no borra ni reescribe ninguno. El archivo se
  versiona en git a partir de esta fecha (antes vivia sin versionar, TD-5).
- **Que sustituye a este freeze**: la admision y la parada de la investigacion pasan a
  `docs/governance/DISCOVERY_ADMISSION_POLICY.md` y `docs/governance/DISCOVERY_STOP_RULES.md`,
  bajo RFC-046 (`APPROVED / ACTIVE`, ADR-0024).
- **Que NO cambia**: `G_BUSINESS_REENTRY` sigue **distinto de PASS**, `LIVE_TRADING` sigue
  **DISABLED**, `TRADES_AUTHORIZED = 0`, y ninguna familia cerrada por RFC-041 puede reentrar
  renombrada. El cierre de este freeze no es una promocion ni una relajacion.
