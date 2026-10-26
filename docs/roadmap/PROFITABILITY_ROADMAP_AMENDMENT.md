# PROFITABILITY ROADMAP AMENDMENT — proposal in waiting

| field | value |
| --- | --- |
| status | **PROPOSED — NOT APPLIED** |
| vehicle | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` |
| applies to | `tasks/roadmap.md`, `docs/research/PROFITABILITY_OPERATING_MODEL.json`, `docs/governance/PROFITABILITY_FIRST_FREEZE.md`, `tasks/decisions.md` |
| applied_today | **NONE** — all four documents are byte-identical to their pre-amendment state on disk |
| activation precondition | explicit human approval, then the four changes below in one commit, with the ADR in §4 |

> This file exists so that the amendment is **reviewable** instead of implied. Nothing in it is in force. If it is
> never approved, the correct reading of the repository is unchanged: RFC-035 is closed, the business freeze stands,
> and no discovery work is authorized.

---

## 1. Why an amendment is needed at all

RFC-035 closed as `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY` with `REPLICATE_P0 = NONE`. The closure was correct and the
criteria were not bent. But its four governing documents were all written for a search that had somewhere to look:

| document | what it says today | why it now blocks everything |
| --- | --- | --- |
| `docs/research/BUSINESS_REENTRY_POLICY.md` | `next_rfc_requires`: `G_BUSINESS_REENTRY = PASS` | no trigger A–E has fired, so no RFC that starts research can be opened |
| `docs/research/PROFITABILITY_OPERATING_MODEL.json` | `next_action_policy.trigger`: only a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE reopens evaluation | a discovery programme is neither, so the operating model forbids it |
| `docs/governance/PROFITABILITY_FIRST_FREEZE.md` | `ACTIVE_RFC: RFC-035`, `status: ACTIVE while RFC-035 is open`; §2 freezes our own backtest/parameter search | RFC-035 is closed, so the freeze's own exit rule (`PASS` / `NO_SUITABLE_OPPORTUNITY` / `FAIL`) has fired but nothing deactivated the document |
| `tasks/roadmap.md` | SDD phases 0–9, last real state 2026-07-04; no RFC numbering, no profitability programme | a reader cannot find the profitability programme in the roadmap at all |

The three governance documents thus leave the project in a state with **no legal next move**: the search that was
allowed has ended, and the thing that would replace it is forbidden by a rule written before anyone knew how the
search would end. Amending them is a decision for the owner, not an implementation detail; this document only makes
the decision concrete.

---

## 2. Amendment 1 — `tasks/roadmap.md`

**Proposed: append one phase. Do not rewrite the existing phases.** The current roadmap is an SDD phase list; the
profitability programme runs alongside it and should be recorded as such, not smuggled into Fase 4.

Proposed text to append (verbatim):

```markdown
## Fase 10 - Profitabilidad verificada (RFC-046, PROPUESTO)

> Precedida por RFC-035 EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY, cerrada como
> CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY (3 rondas, 75 fuentes, 33 oportunidades,
> 0 aceptadas). Fase 10 es el programa que sustituye la busqueda externa por
> descubrimiento cuantitativo controlado.

- Hipotesis economicas preregistradas con fuente externa y mecanismo explicito
  (maximo 3 por campana).
- Especificacion congelada y hasheada antes de medir.
- Datos PIT con `data_time <= decision_time` verificado mecanicamente.
- Gate PROFITABILITY_GATE_V1 (`docs/governance/DISCOVERY_ADMISSION_POLICY.md`).
- Verificador independiente con derecho a FAIL (FALSE_SUCCESS = 0).
- Reglas de parada (`docs/governance/DISCOVERY_STOP_RULES.md`); una parada es un
  resultado y no se rellena automaticamente.

**Vehiculo**: RFC-046 (`docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md`).

**Salida**: una de dos, y nunca una tercera:
`DISCOVERY_CAMPAIGN_FAILED` (sin candidato sobre el gate neto) o
`PROFITABILITY_GATE_V1 = PASS` para un candidato, que abre su propio gate de
promocion a paper.

**Estado**: PROPUESTO. La fase no esta activa hasta registrar el cambio de
gobernanza y su ADR. Live trading sigue deshabilitado y TRADES_AUTHORIZED = 0.
```

Also proposed: a one-line pointer near the top of the roadmap, so a reader is not left to discover Fase 10 by
accident — `> Programa de rentabilidad: Fase 10 (RFC-046, PROPUESTO) + docs/governance/`.

**Not proposed:** any change to Fases 0–9, their exit criteria, or the `Regla de salto`. The jump rule still applies
to every phase, including this one.

---

## 3. Amendment 2 — `docs/research/PROFITABILITY_OPERATING_MODEL.json`

Current value (unchanged on disk):

```json
"next_action_policy": {
  "trigger": "ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE reopens evaluation",
  "no_periodic_rfc": "No RFC-044/RFC-045 merely because time passes",
  "opportunity_watch": "human process: NEW EVIDENCE -> BUSINESS_REENTRY_CHECKLIST (no daemon, no new infrastructure)"
}
```

Proposed replacement of the `trigger` value only:

```json
"trigger": "ONLY a NEW QUALIFIED OPPORTUNITY, a MATERIAL CAPITAL / INSTRUMENT CHANGE, or an APPROVED PREREGISTERED DISCOVERY CAMPAIGN (RFC-046) reopens evaluation"
```

Two properties this preserves deliberately:

- `no_periodic_rfc` stays verbatim and gains a companion line recording that RFC-046 is **not** a periodic RFC: it
  was triggered by RFC-035's written closure on the day it closed.
- `opportunity_watch` stays verbatim: the programme adds no daemon, no watcher and no new infrastructure.

Anything beyond this one string is out of scope of the amendment. In particular `reference_capital_usdt`,
`capital_tiers`, `any_tier_authorized`, `priority_order` and `leverage_policy` are untouched.

---

## 4. Amendment 3 — `docs/governance/PROFITABILITY_FIRST_FREEZE.md`

RFC-035 is closed, so the freeze must be closed explicitly rather than left claiming to be active. Proposed:

1. Change `ACTIVE_RFC: RFC-035` to `ACTIVE_RFC: none — RFC-035 closed CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY`.
2. Change `status: ACTIVE while RFC-035 is open` to `status: **CLOSED 2026-10-08** by the RFC-035 closure`.
3. Add a §8 recording, in one sentence each:
   - the freeze ended because its exit condition fired, not because the criteria were relaxed;
   - the RFC-035-scoped prohibition in §2 (our own backtest, parameter search, asset sweep, timeframe sweep,
     ensemble building, strategy modification) **lapses with the freeze**;
   - the RFC-041 `BUSINESS-FREEZE-2026-001` it runs inside does **not** lift, and `G_BUSINESS_REENTRY` is still
     required except for the bounded exemption in §5 below;
   - discovery is admissible again **only** under `docs/governance/DISCOVERY_ADMISSION_POLICY.md` and
     `DISCOVERY_STOP_RULES.md`, with `PROFITABILITY_GATE_V1` as the gate.
4. Note that the file is currently untracked, and that a governance document other documents depend on should be
   versioned before it is amended — otherwise the amendment itself is not durable.

---

## 5. The RFC-041 question, stated rather than assumed

RFC-041 says a next RFC requires `G_BUSINESS_REENTRY = PASS`, and its trigger A is *"new external evidence:
independent publication/replication of persistent post-publication risk-adjusted excess return"*. RFC-046 does not
satisfy trigger A, and pretending otherwise would be a fabrication on the scale of the RFC-036 "reserved" claim that
had to be corrected.

Two honest resolutions exist. **The owner must choose one; this document does not choose for them.**

| option | meaning | cost |
| --- | --- | --- |
| **5A — explicit dated exemption** (recommended) | RFC-041 gains a recorded exemption: one bounded discovery campaign may run offline without trigger A, under the admission policy, with the business freeze otherwise intact | weakens the freeze by exactly one bounded hole, in writing, with an expiry: the exemption dies with the campaign |
| **5B — no exemption** | the programme waits until trigger A/B/C/D/E fires or the owner changes the policy on its merits | leaves the project with no legal next move after RFC-035; the correct action stays route A (wait) |

If 5B is chosen, RFC-046 stays `PROPOSED` indefinitely and that is a legitimate outcome. It is recorded here so
that "no decision" is visibly a decision.

---

## 6. Amendment 4 — `tasks/decisions.md`, one ADR

**Not written yet, deliberately.** An ADR is a record that a decision was taken; RFC-046 has not been approved, so
recording one now would manufacture an approval that does not exist. Draft text, to be inserted only on approval:

```markdown
## ADR-0025 — Controlled quantitative strategy discovery (RFC-046)

**Estado**: propuesta de ADR, se registra al aprobarse RFC-046.

**Contexto**: RFC-035 cerro sin candidato replicable. La busqueda externa agoto su
universo admisible. El modelo operativo vigente (RFC-043) prohibe abrir evaluacion
sin un trigger cualificado, y RFC-041 exige G_BUSINESS_REENTRY = PASS.

**Decision**: admitir hipotesis economicas soportadas externamente en un pipeline
de investigacion preregistrado, acotado y offline, bajo PROFITABILITY_GATE_V1 y un
verificador independiente, con reglas de parada explicitas y sin autorizar trading
real, paper, leverage ni cambios en el Risk Engine.

**Consecuencias**: se preserva la autoridad REAL_RUNTIME > ... > ASSUMPTION; el
criterio de negocio no se relaja; DISCOVERY_CAMPAIGN_FAILED es un resultado
esperado y aceptable; toda campaña futura requiere su propia autorizacion.

**Trazabilidad**: docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md,
docs/governance/DISCOVERY_ADMISSION_POLICY.md, docs/governance/DISCOVERY_STOP_RULES.md,
reports/rfc046/IMPACT_ASSESSMENT.md.
```

The number `ADR-0025` is a proposal: the current highest ADR heading in `tasks/decisions.md` is `ADR-0023`, and the
repo's own history has a documented ID-collision precedent (`TSK-022`) plus a numbering-policy ADR (`ADR-0023`)
whose lesson is exactly *check before you open*. The writer of the ADR must re-check the highest heading at that
moment; `ADR-0025` is not reserved by this document.

---

## 7. Amendment 5 — a real RFC registry (proposed, not created)

The RFC-046 numbering audit had to reconstruct the number space from artefacts and prose, because no registry
exists. That is how a false "RFC-036 is reserved" claim survived three rounds. The audit found **26 occupied
numbers, 17 of which have no versioned declaration at all**, and it confirmed that `RFC-045` is asserted absent by
four campaign verifier scripts. Proposed: a tracked `docs/roadmap/RFC_REGISTRY.json` mapping each number to its
`status` (`OCCUPIED` / `VACANT_BY_CONTROL` / `FREE`), title, artefact and opening commit — with `RFC-045` recorded
as `VACANT_BY_CONTROL` so nobody "helpfully" fills the gap four verifiers assert must stay empty, and with the 17
unversioned numbers recorded as occupied-but-unarchived rather than silently free.

Not created now: creating a registry is itself a governance change, and doing it unasked inside a proposal would
repeat the mistake this RFC exists to correct.

---

## 8. What is explicitly *not* being amended

- `docs/STRATEGY_ADMISSION_CRITERIA.md` c1–c9 stay as pre-registered; `PROFITABILITY_GATE_V1` adds requirements and
  tightens two, and never re-scores a closed candidate.
- The risk engine, sizing rules, leverage policy and kill switch: untouched.
- `docs/research/CANDIDATE_ARCHIVE.json`: untouched; closed candidates stay closed with their reentry conditions.
- `config/runtime.yaml` and `config/risk.yaml`: `live_trading_enabled: false` stays.
- The 200 USDT reference capital and `TIER_0 CANARY`: unchanged; `any_tier_authorized` stays `false`.

## 9. Verification of "not applied"

The four invariants in §1 are checked mechanically by `scripts/rfc046_verify.py` and by
`tests/unit/research/test_rfc046_discovery_proposal.py`: the roadmap contains no Fase 10, the operating model's
trigger string is unchanged, the freeze still declares `ACTIVE_RFC: RFC-035`, and `tasks/decisions.md` contains no
ADR heading mentioning RFC-046. When the amendment is finally approved, those checks are what must be updated —
in the same commit that applies the amendment, never before.
