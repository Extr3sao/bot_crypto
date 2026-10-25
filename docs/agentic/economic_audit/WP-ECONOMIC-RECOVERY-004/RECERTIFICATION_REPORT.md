# WP-ECONOMIC-RECOVERY-004 — Recertificación

> Lo que el gate dice **después** de la reparación, con qué comandos se obtuvo y qué no
> certifica. Cada número procede de una transcripción en [`evidence/`](evidence/).

---

## 1. El gate, antes y después

| | antes (`2bd6e346`) | después (`265d09ed`) |
| --- | --- | --- |
| modo | `--check` (parcial) | **completo** |
| estado | `INTEGRITY_FAILURE` | **`FULL_REPRODUCTION_PASS`** |
| exit code | **5** | **0** |
| checks | 10/11 PASS | **13/13 PASS** |
| controles de mutación | 6/6 | 6/6 |
| `integrity_failures` | 1 (`config/strategy_admission.json` content drift) | **0** |
| certificación completa satisfecha | `False` | **`True`** |
| entrada ausente tolerada | `reports/strategy-baseline/COST_BARRIER.json` | presente y verificada (9/9) |

Transcripciones: [`evidence/gate_before.txt`](evidence/gate_before.txt),
[`evidence/gate_after_full.txt`](evidence/gate_after_full.txt).

El mismo gate en `--check` (sin re-ejecutar el builder) pasa de `INTEGRITY_FAILURE` (raw
exit 5) a `CHECK_ONLY_PASS` 12/12 (raw exit 2, parcial por diseño; raw exit distinto de 0
porque no ha reproducido). No se ha ascendido un resultado parcial a certificación:
[`evidence/gate_after_check.txt`](evidence/gate_after_check.txt).

El `INTEGRITY_FAILURE` que WP-003 registró **desaparece por la causa identificada**, no por
cambio de umbral: `inputs:published_pins_match_the_declared_sources` pasa a
`9/9 present; pinned: 3 byte-exact, 2 state-exact, 0 line-ending-only, 0 drifted`.

---

## 2. Reemisión del registro de certificación

El registro commiteado describía los artefactos **anteriores** a la reparación, así que su
tabla `evidence_digests` ya no coincidía con el árbol. Se reemitió dos veces, y las dos
están documentadas:

| intento | resultado | causa |
| --- | --- | --- |
| 1 | `FAILED`, exit 4 | `contract_tests` falló: el propio registro describía digests previos a la reparación. El paso de tests corre **antes** de escribir el registro, así que el certificador no puede arreglar por sí mismo el artefacto que uno de sus tests valida. Transcripción: [`evidence/certify_run.txt`](evidence/certify_run.txt); registro tal cual quedó: [`evidence/CERTIFICATION_ATTEMPT_1_REFUSED.json`](evidence/CERTIFICATION_ATTEMPT_1_REFUSED.json) |
| 2 | **`CERTIFIED`, exit 0** | con el registro del intento 1 en el árbol, los digests coinciden, la suite de contrato pasa y los cinco pasos llegan a 0 |

Transcripción del intento 2: [`evidence/certify_run_2.txt`](evidence/certify_run_2.txt).

```
cost-barrier certification: CERTIFIED (exit 0)
  candidate 265d09ed9fdc (repro/economic-recovery-002), dirty watched paths 0
  full certification satisfied: True
  gate status FULL_REPRODUCTION_PASS
  [PASS] contract_tests      exit 0
  [PASS] materialize_inputs  exit 0
  [PASS] input_integrity     exit 0
  [PASS] full_reproduction   exit 0
  [PASS] adversarial         exit 0
```

**DEF-4 (defecto de herramienta, no reparado):** existe una dependencia circular de
arranque entre el registro y la suite que lo valida. No se ha tocado el orden de los pasos
ni se ha relajado el test: se ha ejecutado dos veces y se conservan los dos resultados. Un
WP de ergonomía debería permitir reemitir el registro con la suite en cuarentena explícita
(declarada como "artefacto en reparación"), en vez de exigir dos ejecuciones.

Reemisión encadenada: el registro nuevo conserva la identidad del que reemplaza.

| campo | valor |
| --- | --- |
| `previous_fingerprint` | `0cfdb13e9800a145…` |
| `previous_candidate_head` | `e07ce6cc…` |
| `previous_status` | `CERTIFIED` |
| `previous_evidence_digests_sha256` | `1aef413ebbf9…` |

El certificador ancla la cadena en el registro del **commit** (`git show HEAD:…`), no en el
fichero local; por eso el intento rechazado no aparece en la cadena, y por eso se conserva
como evidencia aparte en lugar de desaparecer.

---

## 3. Suites

### 3.1 Suite de contrato y de lane (7 ficheros)

| fichero | tests |
| --- | --- |
| `tests/unit/research/test_ledger_identity_contract.py` | 24 |
| `tests/unit/research/test_cost_barrier_gate.py` | 32 |
| `tests/unit/research/test_cost_barrier_adversarial.py` | 34 |
| `tests/unit/research/test_cost_barrier_explorer.py` | 17 |
| `tests/unit/research/test_cost_barrier_ci_parity.py` | 11 |
| `tests/unit/research/test_recovery_determinism.py` | 15 |
| `tests/unit/research/test_strategy_admission_ledger.py` | 4 |

**137 passed, 0 failed, exit 0**
([`evidence/lane_suite_after.txt`](evidence/lane_suite_after.txt)). Incluye los dos nodos
que la reparación había dejado en rojo por motivos de orden —el registro reemitido y el
ensayo de checkout limpio, que exige que los pines del lane estén commiteados—.

### 3.2 Suite completa del repositorio

| | antes (`2bd6e346`) | después (`265d09ed`) |
| --- | --- | --- |
| nodos rojos (`FAILED`+`ERROR`) | **104** (90 F + 14 E) | **85** (71 F + 14 E) |
| passed | 3270 | 3314 |
| skipped | 31 | 31 |
| cerrados | — | **19**, todos `test_cost_barrier_*` |
| introducidos | — | **0** |
| rojos en el lane | 19 | **0** |

Comparado **por identidad de nodo**, no por recuento: el conjunto diferencia es exactamente
el lane ([`evidence/full_suite_before.txt`](evidence/full_suite_before.txt),
[`evidence/full_suite_after.txt`](evidence/full_suite_after.txt)). Los 85 fallos
preexistentes siguen visibles, incluidos los 14 `ERROR`, y ninguno es del lane.

Cuatro nodos que estaban verdes **no** se han vuelto rojos: los dos que la reparación
rompió temporalmente (registro y ensayo de checkout limpio) están verdes en la corrida
final, y los dos `test_recovery_determinism` que dependen de los pines commiteados también.

---

## 4. Verificación independiente

[`INDEPENDENT_VERIFICATION.json`](INDEPENDENT_VERIFICATION.json) — `scripts/wp_eco004_verify.py`,
commit verificado `265d09ed`, **22/22 PASS, exit 0**
([`evidence/independent_verification_run.txt`](evidence/independent_verification_run.txt)).

El verificador no importa ni el explorer (productor del pin) ni el gate (que lo
re-deriva): reimplementa el contrato desde
[`LEDGER_INTEGRITY_CONTRACT.md`](LEDGER_INTEGRITY_CONTRACT.md). Lo que comprueba:

- el pin de estado publicado es el valor del contrato, y el contrato declarado es el que
  implementa;
- identidad física de los cinco inputs citados (todos `EXACT`) y de la copia de evidencia
  del input (`2437f446…`);
- el ledger es byte-idéntico al commit anterior (`diff_vs_2bd6e346 = none`) y sigue
  reconstruyéndose (`build_strategy_admission.py --check` exit 0);
- las 24 entradas económicas son idénticas, el `payload_sha256` del explorer es
  `4383d812…` antes y después, y ningún flag de gobernanza se movió;
- el gate real llega a `FULL_REPRODUCTION_PASS` con `false_success 0`;
- **no lavado**: 19 nodos cerrados, todos del lane, 0 introducidos, 85 siguen rojos, y
  `reports/strategy-baseline` no aparece en ningún commit.

---

## 5. Procedencia que **no** se reescribió

Los artefactos históricos que nombran una revisión anterior siguen nombrando lo que
midieron, y eso se conserva:

- `data/recovery/wp7/COST_BARRIER_ADVERSARIAL_REPORT.json` identificaba el gate en
  `a551fdc` (digest `6ff2793a…`). El gate reparado es `a533e33f…`. El informe **no** se ha
  regenerado: describe honestamente lo que probó, y regenerarlo habría reescrito evidencia
  histórica para que pareciera contemporánea. La cobertura vigente la aporta la corrida
  adversarial del certificador (17/17 detectados, 0 evadidos, 0 legs fallidos) y el gate.
  Queda anotado como deuda de procedencia, no como certificación.
- Los informes de WP-001/002/003, sus hashes y `WP-ECONOMIC-RECOVERY-003/*` no se tocan.

---

## 6. Qué **no** dice esta recertificación

- **No** es una recuperación económica: el `payload_sha256` del explorer es el mismo antes
  y después, así que ninguna celda, horizonte, comisión o veredicto económico ha mejorado.
- **No** autoriza PAPER, promoción ni trading: `NOT_AUTHORIZED`, 0 trades,
  `authorizes_promotion: false`, `authorizes_live_trading: false`, `admitted_for_paper`
  sigue siendo `false` en las 24 entradas.
- **No** cierra los 85 fallos preexistentes ni la ausencia de resultados multifamilia: los
  seis `MULTI_FAMILY_RESULTS_*.json` siguen sin existir en ningún commit.
- **No** es una certificación global de la plataforma: certifica que el lane del
  cost-barrier reproduce desde sus fuentes en este commit.

---

## 7. Reproducción

```bash
python scripts/cost_barrier_gate.py                 # 13/13, FULL_REPRODUCTION_PASS, exit 0
python scripts/cost_barrier_gate.py --check         # 12/12, CHECK_ONLY_PASS, raw exit 2
python -m pytest tests/unit/research/test_ledger_identity_contract.py \
                 tests/unit/research/test_cost_barrier_*.py \
                 tests/unit/research/test_strategy_admission_ledger.py \
                 tests/unit/research/test_recovery_determinism.py -q     # 137 passed
python scripts/wp_eco004_verify.py                  # 22/22, exit 0
python scripts/cost_barrier_certify.py --supersedes-reason "…"          # CERTIFIED, exit 0
```

El gate completo necesita `reports/strategy-baseline/COST_BARRIER.json`; en un checkout
limpio se restaura con `python scripts/cost_barrier_evidence.py --materialize`, que lo
verifica contra el pin publicado (`2437f446…`) antes de escribirlo.
