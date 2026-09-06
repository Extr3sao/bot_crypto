# ADR-MA-0009 — Natural agreement evidence authority (MA-4, DEF-MA4-003)

- **Status**: Decidido — MODEL A. Reparación del builder; verificador sin cambios (`decision-package-verifier-v3`).
- **Checkpoint**: CP-MA4-POSTCERT-001.
- **Origen**: POC01 setup (impl `11e76cc`, evidence `57f300f`) — bounded fixture y real-public-market runs produjeron
  `verifier_rejected_natural_output` con `checks=['selected_evidence_binding']`
  en paquetes generados honestamente por el runtime certificado (momentum LONG + trend LONG con acuerdo direccional).
  Clasificado como DEF-MA4-003 `NATURAL_AGREEMENT_EVIDENCE_AUTHORITY_MISMATCH`.

## CLAIM

El rechazo del verificador sobre salida natural multi-proposal es una
desviación del **builder** (MA-4 DecisionEngine), no del verificador: el
motor une evidencia derivada del debate (`DebateReport.supporting_evidence`,
que agrega la evidencia de *todos* los participantes del debate) al campo
`DecisionCandidate.supporting_evidence_refs`, violando la autoridad de
evidencia fijada en ADR-MA-0007, que define ese campo como la evidencia del
`TradeProposal` terminal canónico con igualdad canónica por conjunto.

## SOURCE (jerarquía de autoridad consultada)

1. **ADR-MA-0007** (`tasks/decisions.md`, CP-MA-004.2): «la autoridad de
   evidencia del candidato seleccionado se origina en el `TradeProposal`
   terminal canonico. El verificador reconstruye de forma independiente
   `selected_candidate.final_proposal_id -> terminal proposal` y exige
   `supporting_evidence_refs != vacio`, `terminal.evidence_refs != vacio` e
   **igualdad canonica por conjunto de identidades**». Rechaza
   EVIDENCE_STRIPPED / PARTIALLY_STRIPPED / SWAPPED / ADDED / DUPLICATED /
   UNKNOWN / FOREIGN_RUN / FOREIGN_TRACE.
2. **ADR-MA-0008** (`tasks/decisions.md`, CP-MA-004.3): mantiene el inventario
   de claims autoritativos con `supporting_evidence_refs -> terminal
   TradeProposal` clasificado **ALREADY_REDERIVED (CP-MA-004.2)** — la fuente
   de re-derivación no cambió al pasar a v3. No existe ninguna decisión que
   autorice un closure decision-level de evidencia soporte.
3. **Contrato `DecisionCandidate`** (`contracts/decision.py`): docstring
   «One **terminal proposal lineage** evaluated by the decision engine»; el
   campo `supporting_evidence_refs` es la evidencia soporte **del linaje**.
   El contrato tiene campos explícitos de procedencia de debate separados
   (`debate_id`, `debate_outcome`, `material_dissent`, `challenged_by`,
   `counter_evidence_refs`) — la corroboraación de debate no necesita (ni está
   autorizada a) vivir en `supporting_evidence_refs`.
4. **Contrato `TradeProposal` / MA-3**: las revisiones del debate producen
   propuestas terminales actualizadas cuyo propio `evidence_refs` absorbe la
   evidencia nueva de SU linaje (`TerminalProposalResolver`); el
   `DebateReport` conserva la corroboraación agregada en SUS campos
   (`supporting_evidence`, `evidence_attribution`, critiques). El debate nunca
   transfiere evidencia de un linaje a otro.
5. **Runtime (repro)**: `decision.py::_debate_facts` expone
   `facts.supporting_refs = report.supporting_evidence`; el builder hacía
   `supporting = sorted({*final_proposal.evidence_refs, *facts.supporting_refs})`.
   Con ≥2 propuestas mismo-dirección en un debate, `report.supporting_evidence`
   contiene E1+E2 → el candidato del ganador lleva E1+E2 → superset del
   terminal (E1) → `selected_evidence_binding` REJECT. Reproducido en POC01
   fixture (3/3 assets) y real-market (BTC).

## EVIDENCE

- POC01 bounded run real (`evidence/bounded_public_campaign_report.json`):
  `VERIFIER_REJECTED=1`, error
  `verifier_rejected_natural_output decision_id=decision:e878de49a042f31c checks=['selected_evidence_binding']`,
  detalle del check: `proposal=['evidence:proposal:6b59e4f742ef93cbbfbb669b']
  candidate=['evidence:proposal:6b59e4f742ef93cbbfbb669b',
  'evidence:proposal:f90bc32cbd1ac52201f35cf3']` — el segundo ref es la
  evidencia de la propuesta trend aliada, no del terminal momentum.
- Comportamiento del paquete: el nivel **package** ya expone la unión
  agregada de evidencia soporte (`DecisionPackage.evidence_refs` = unión de
  todos los candidatos) — la procedencia decision-level existe arriba sin
  tocar el campo authority-critical del candidato.
- El verificador no cambió: v2 (ADR-MA-0007) ya exigía igualdad de conjunto;
  v3 (ADR-MA-0008) la mantuvo. Si el campo fuese contractualmente un closure,
  el verificador habría sido inconsistente durante tres certificaciones — la
  lectura consistente es que el builder se desvió.

## DECISION

**MODEL A — PROPOSAL-ONLY SUPPORT.**

```text
DecisionCandidate.supporting_evidence_refs == terminal TradeProposal.evidence_refs
(set equality, canonical identity set, no ordering semantics)
```

- **Builder repair** (única línea semántica, `decision.py`):
  `supporting = tuple(sorted(set(final_proposal.evidence_refs)))` — elimina la
  unión con `facts.supporting_refs`. La corroboraación/agreement sigue
  observable en: `DecisionPackage.evidence_refs` (unión decision-level),
  `DebateReport.supporting_evidence` + `evidence_attribution` (procedencia
  MA-3), y los campos de debate del candidato (`debate_id`, `debate_outcome`,
  `material_dissent`, `challenged_by`).
- **Verifier**: sin cambios de semántica — permanece
  `decision-package-verifier-v3` (§10: solo se bumpa si cambia semántica del
  verificador; aquí el verificador ya era correcto). `BUILDER != VERIFIER`
  se preserva.
- **Scoring**: sin cambio — `facts.supporting_refs` nunca alimentó scores
  (solo materiality de challenges standing); META_RANKER y pesos intactos.
- **NO es un loosening**: no se acepta `candidate refs ⊇ terminal refs`; la
  igualdad exacta de ADR-MA-0007 queda como invariant, ahora satisfecha por
  el builder para salida natural.

## REJECTED_ALTERNATIVE

- **MODEL B — Authorized decision support closure** (redefinir
  `EXPECTED_SUPPORT_EVIDENCE = terminal + debate/agreement autorizada` y que
  el verificador re-derive ese closure): **RECHAZADO** porque (a) ningún
  contrato ni ADR define tal closure — habría sido autoridad inventada en
  retroactivo; (b) requeriría cambiar la semántica del verificador (bump a v4)
  y re-abrir la superficie de aceptación de evidencia en el check más
  authority-critical, con riesgo de reintroducir los vectores de
  EVIDENCE_SWAPPED/ADDED que ADR-MA-0007 cerró (cualquier error de derivación
  del closure convierte adición no autorizada en aceptada); (c) la información
  decision-level ya tiene superficie propia (`DecisionPackage.evidence_refs`,
  DebateReport) sin debilitar el binding.
- **Loosening puro** (`candidate refs ⊇ terminal refs`): **RECHAZADO**
  explícitamente por §2 — reabre evidence-injection.
- **No tocar nada / clasificar como expected fail-closed**: **RECHAZADO** —
  el rechazo de salida natural válida es semánticamente incorrecto, bloquea
  TODO trade multi-strategy concordante y contamina el baseline POC01
  (§16 exige `NATURAL_VERIFIER_REJECTIONS = 0`).

## Protecciones preservadas (§4)

`foreign-run`, `foreign-trace`, `unregistered`, `future`,
strip/partial-strip, swap, adición no autorizada, promoción de
counter-evidence, non-terminal binding, forjas UNRESOLVED/INSUFFICIENT:
todas siguen REJECT — el binding exacto + `final_proposal_binding` +
`run_authority_*` + re-derivación de blockers (ADR-MA-0006/0007/0008) quedan
intactos. Sin regresión a DEF-MA4-001 / DEF-MA4-002 /
CERT-MA4-001-RETRY-001 / CERT-MA4-001-RETRY-2-001 (matriz completa re-ejecutada en CERT-MA4-002).
