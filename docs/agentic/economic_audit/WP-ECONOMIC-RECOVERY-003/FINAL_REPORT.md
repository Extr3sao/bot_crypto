# WP-ECONOMIC-RECOVERY-003 — Impacto de la evidencia económica

**Veredicto:** la cadena del cost-barrier se puede **recertificar de forma exacta** —sin
mover un solo número económico— porque su entrada ausente está preservada byte a byte. La
capa `MULTI_FAMILY_RESULTS` **no se puede reconstruir** y no debe intentarse: su único
registro válido es la matriz ya publicada. Un bloqueo real, un plan de 3 commits, ninguna
ampliación del framework.

| campo | valor |
| --- | --- |
| rama | `repro/economic-recovery-002` |
| commit auditado | `2bd6e346` |
| evidencia publicada modificada | **ninguna** |
| resultados económicos modificados | **ninguno** |
| verificador independiente | [`INDEPENDENT_VERIFICATION.json`](INDEPENDENT_VERIFICATION.json) — **14/14 PASS**, exit 0 |
| bloqueos para WP-004 | 1 (ver §7) |

---

## 1. El bloqueo, medido

```
$ uv run python scripts/cost_barrier_gate.py --check
INTEGRITY_FAILURE (check mode) exit 5 · checks 10/11 PASS · controls 6/6
[FAIL] inputs:published_pins_match_the_declared_sources
       config/strategy_admission.json content drift (pin 6c4dd0be1fc2...)
```

Un único check falla, y falla por una razón concreta: **el pin que el explorer publicó
para el ledger no describe ningún fichero commiteado**. Es el render CRLF de la revisión
`ddaf14d1` (el ledger *anterior* a la reparación del ancla):

| revisión del ledger | blob (LF) | render CRLF | ¿es el pin `6c4dd0be…`? |
| --- | --- | --- | --- |
| `ddaf14d1` (vigente cuando se publicó el explorer) | `92aab541…` | `6c4dd0be…` | **sí** |
| `eb53e631` = `HEAD` (ancla reparada) | `5e2ccc57…` | `21a642de…` | no |

Dos defectos en un valor: la **convención** (se hashearon los bytes de una copia de
trabajo Windows, no del blob) y el **contenido** (el ledger cambió al reparar el ancla).
WP-002 lo describió como "el pin del ledger con el ancla caducada": era cierto, pero
incompleto — ese pin nunca fue el hash de un fichero del repositorio.

La asimetría que lo hizo pasar desapercibido: `data/recovery/ACTIVE_ECONOMIC_AUDIT.json`
tiene **el mismo defecto de convención** (`e05be22b…` es el CRLF de `8a101e88…`) y sin
embargo es inofensivo, porque el explorer publica además un `state_sha256` semántico que
el gate lee. Al ledger **le falta ese pin de estado**. Ésa es la lección estructural que
WP-004 debería cerrar, y la razón por la que este WP no la arregla a la vez que recertifica.

---

## 2. Qué cambiaría una recertificación (tarea 4)

Simulada en un clon temporal, nunca en este árbol. 18 nodos, 21 pines:

| efecto | nodos |
| --- | --- |
| **se reconstruyen con payload idéntico** | `ACTIVE_ECONOMIC_AUDIT`, `COST_BARRIER_EXPLORER`, `COST_BARRIER_VERIFICATION`, copia del input |
| **se reescriben (actas/bundles)** | `INPUT_EVIDENCE`, `PRODUCER_PINS`, `ADVERSARIAL_REPORT`, `CERTIFICATION` |
| **no se tocan** | corpus, resultados multi-familia, matriz, criterios, `cost_model_v3` (código y doc), `STRATEGY_DISCOVERY_V3_RESULTS` |
| **registro histórico** | `CLEAN_CHECKOUT_REHEARSAL_REPORT` (fija lo que observó en su commit) |

**El payload no se mueve.** El explorer reconstruido hashea `4383d812…`, exactamente el
publicado, sobre un cuerpo de 212 351 bytes en el que sólo cambian 5 hojas: `branch`,
`generated_at_utc`, `head` y los digests de `sources[0]` (CRLF→LF) y `sources[2]` (ancla
reparada). El verifier reconstruido da `PASS`, `0` checks fallidos, `13/13` controles.

Firma de la suite en la simulación:

| medición | antes | después |
| --- | --- | --- |
| suite de contrato del gate (93 nodos) | 19 rojos | **93 verdes** |
| suite completa, identidad de nodos | 104 rojos | 85 rojos, `closed=19`, `introduced=0` |
| gate | `INTEGRITY_FAILURE`, exit 5 | `FULL_REPRODUCTION_PASS`, exit 0 |
| certificación | — | `CERTIFIED`, exit 0 |

Y una advertencia medida: si la recertificación se hace **a medias** —reconstruir
explorer y verificación pero no re-capturar los pines de productores— quedan **3 nodos
rojos** de 108. El orden no es formalismo, es parte del resultado.

---

## 3. Integridad frente a economía (tarea 5)

La distinción no se afirma: se comprueba.

| categoría | ¿cambia? | prueba |
| --- | --- | --- |
| métricas económicas (costes, fees, slippage, horizontes) | **no** | payload `4383d812…` idéntico; el input se materializa byte a byte (`2437f446…`) |
| estrategias, familias, señales | **no** | `src/` sin cambios; el verificador lo comprueba contra `2bd6e346` |
| criterios de admisión | **no** | `docs/STRATEGY_ADMISSION_CRITERIA.md` no está en el radio de la recertificación (nodo 4, `NOT_TOUCHED`) |
| digests, `head`, `branch`, `generated_at` | **sí** | 5 hojas de procedencia |
| veredictos de admisión publicados | **no** | la matriz no se regenera |

Es decir: la recertificación es un acto de **procedencia**. Lo que la vuelve legítima es
justamente que el payload no se mueva; si se moviera, habría dejado de ser recertificación
y habría que tratarla como resultados nuevos.

---

## 4. Lo que no se puede recuperar (tareas 2 y 3)

Los seis `MULTI_FAMILY_RESULTS_*.json` **no están en ningún commit**
(`git log --all -- reports/strategy-baseline` no devuelve nada) y su directorio está
excluido por `.gitignore:55`. El productor está versionado, pero sus entradas no, y **la
matriz publicada no registra ni un digest, ni un commit, ni una fecha** de corrida.

| entrada | reconstruible exactamente |
| --- | --- |
| `momentum`, `breakout`, `trend`, `mean_reversion`, `volatility` | **no** — sin corpus, sin digests, sin revisión del productor ni entorno |
| `ema_crossover` | **sí como fila**: su baseline está versionado (`21f78880`) |

Re-ejecutar el productor sobre klines re-descargados produce **números nuevos**. Llamar a
eso reconstrucción sería el error que este WP existe para impedir. Por eso la matriz
commiteada sigue siendo el ancla, tal como WP-002 declaró.

El camino honesto para esa capa es otro: re-ejecución **pre-registrada**, con corpus
capturado y digests escritos en el artefacto, conviviendo con el resultado publicado (no
sustituyéndolo). Eso es un WP de resultados, no de recuperación.

---

## 5. Las dependencias ausentes (tarea 6)

19 rutas: **16 recuperables por re-ejecución** (productor versionado, línea exacta
identificada), **1 exacta** (`COST_BARRIER.json`, copia byte-idéntica), **1 de host**
(`ST6_HEALTH_STATUS.json`), **1 irrecuperable**
(`docs/research/work_packages/WP-HTF-PIT-001_htf_availability_unit_fix.md`: ningún script
lo escribe, sólo se lo cita). Detalle y fundamento en
[`SOURCE_RECOVERY_ASSESSMENT.md`](SOURCE_RECOVERY_ASSESSMENT.md).

Dos correcciones a WP-002, ambas con fundamento ejecutable:

1. WP-002 contó **dos** entregables nunca commiteados; hay **uno**.
   `reports/rfc046/IMPACT_ASSESSMENT.md` sí tiene productor:
   `scripts/rfc046_audit.py:732` escribe la constante `IMPACT` cuyo valor es exactamente
   esa ruta. Su ausencia se debe al `.gitignore`, no a una pérdida.
2. WP-002 atribuyó el rojo a "un nodo"; sobre un checkout limpio son **19**, de los que
   **10** son sólo el input ausente y **9** la deriva. Su diagnóstico era correcto en su
   escenario (input materializado, midiendo el delta de su reparación); el total se leyó
   como si fuera otra cosa.

Ninguna de las 19 bloquea la recertificación.

---

## 6. El test que falla (tarea 7)

`tests/unit/research/test_cost_barrier_gate.py::test_a_missing_required_input_blocks_rather_than_fails`
falla con:

```
assert 'INTEGRITY_FAILURE' == 'BLOCKED_MISSING_INPUT'
```

El test inyecta un input requerido inexistente y espera `BLOCKED_MISSING_INPUT`. Lo que
recibe es la deriva real del ledger, porque `decide_status` evalúa **primero integridad y
después bloqueo**:

```python
if integrity:  return INTEGRITY_FAILURE
if blocked:    return BLOCKED_MISSING_INPUT
```

Es decir: el mecanismo de bloqueo **no está roto**; está enmascarado por un fallo de
integridad verdadero que tiene precedencia legítima. Un gate que reportara "bloqueado"
mientras su propia evidencia se contradice estaría eligiendo el diagnóstico cómodo.

Por eso el test **no se toca**:

- reordenar la precedencia haría que una inconsistencia real de integridad se reportara
  como "falta un fichero" — un fallo identificable convertido en uno benigno;
- aceptar `blocked or integrity` convertiría un fallo no identificado en un pase;
- relajar la aserción elimina la única prueba de que el bloqueo existe.

La resolución correcta es la del §2: **reparar la deriva**. En la simulación, el nodo
vuelve a verde **sin modificarse**, junto con los otros 92 de la suite de contrato. La
obligación se preserva porque se satisface, no porque se silencie.

---

## 7. Recomendación concreta para WP-004

> **WP-ECONOMIC-RECOVERY-004 — Recertificación de integridad del bundle del cost-barrier.**
> Alcance: 3 commits, 6 pasos, cero cambios económicos. Autorizar sólo esto.

**Alcance mínimo autorizable**

1. materializar el input desde la copia de evidencia (digest `2437f446…` obligatorio);
2. reconstruir explorer + verificación y **comprobar el payload `4383d812…` antes de
   publicar** — si cambia, abortar: ya no es recertificación;
3. publicar, y en el commit siguiente re-capturar `INPUT_EVIDENCE` + `PRODUCER_PINS`;
4. certificar en dos tiempos (borrador que se niega + certificación);
5. `gate --check` → `FULL_REPRODUCTION_PASS`; `93/93` en la suite de contrato;
6. rollback ensayado: `git revert` de los tres commits devuelve el gate a `10/11` y al pin
   `6c4dd0be…`.

**Fuera de alcance, y por qué**

- **No** añadir `state_sha256` al pin del ledger en el mismo WP. Es un cambio de contrato
  del explorer: merece su propio commit, revisión y test (el gate tendría que preferir el
  pin de estado al de bytes para ese nodo, como ya hace con el audit). Mezclarlo haría que
  un fallo de recertificación no se pudiera distinguir de un fallo del contrato nuevo.
- **No** reconstruir `MULTI_FAMILY_RESULTS_*`: imposible (§4). Si se quiere resolver esa
  capa, es un WP de re-ejecución pre-registrada, con corpus congelado y digests dentro del
  artefacto.
- **No** tocar tests, gates, umbrales ni `src/`. Este WP no encontró ni un defecto de
  lógica económica: encontró un pin que nombra bytes que ningún commit contiene.

**Definition of done de WP-004**

| criterio | umbral |
| --- | --- |
| payload del explorer | `4383d812…` sin cambios |
| gate | `FULL_REPRODUCTION_PASS`, exit 0 |
| suite de contrato | 93/93 |
| nodos cerrados / introducidos | `closed = 19`, `introduced = 0` |
| evidencia económica | byte-idéntica salvo hojas de procedencia y los 4 bundles reescritos |
| certificación | `CERTIFIED`, exit 0, `satisfies_full_certification: true` |
| rollback | probado y documentado antes de publicar |

**Riesgo residual declarado:** tras WP-004 el repositorio seguirá con **85 nodos rojos**
preexistentes, ninguno de cost-barrier. No es un fallo de la recertificación; es el rojo
que ya existía y que este WP no arregla.

---

## 8. Límites de este informe

1. Nada publicado se regeneró: la recertificación se **simuló** en un clon temporal y sus
   transcripciones están en [`evidence/`](evidence/).
2. Las dos corridas completas recolectan totales distintos (~3405 vs ~1982); la
   comparación es por **identidad de nodo**, no por recuento (§2).
3. `reports/strategy-baseline/data/` no existe y `data/raw/` está vacío: la capa
   multi-familia queda fuera de toda recuperación exacta.
4. No se declara PASS global: hay un bloqueo (el pin del ledger), 85 rojos preexistentes y
   una capa entera no reconstruible. Todo ello está declarado, no mitigado.
