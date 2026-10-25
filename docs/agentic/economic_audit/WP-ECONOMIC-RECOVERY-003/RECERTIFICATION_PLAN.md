# WP-ECONOMIC-RECOVERY-003 — Plan mínimo de recertificación

> Procedimiento para devolver la cadena del cost-barrier a un estado coherente **sin
> tocar un solo número económico**. No se ejecuta en este WP: se describe, con las
> precondiciones, el orden y el rollback medidos.
>
> El detalle causal está en [`DEPENDENCY_GRAPH.md`](DEPENDENCY_GRAPH.md); la evidencia
> de la simulación, en [`evidence/`](evidence/).

---

## 1. Qué es y qué no es esta recertificación

| | recertificación de **integridad** (este plan) | regeneración de **resultados** (fuera de alcance) |
| --- | --- | --- |
| qué mueve | digests, `head`, `branch`, `generated_at_utc`, actas de verificación y certificación | métricas: costes, fees, slippage, horizontes, PF, veredictos |
| qué NO mueve | ninguna cifra económica, ni código de estrategia, ni criterios de admisión | — |
| qué lo demuestra | el payload del explorer reconstruido es `4383d812…`, idéntico al publicado: el cuerpo de 212 351 bytes sólo difiere en 5 hojas, todas de procedencia | un backtest nuevo sobre datos nuevos |
| requisito | el input del bundle debe existir (lo hay: copia exacta) | el corpus congelado (no lo hay) |

La separación no es retórica. `data/recovery/COST_BARRIER_EXPLORER.json` guarda dos
cosas distintas: el **payload** (los números y su derivación, hasheado aparte) y las
**hojas volátiles** (`head`, `branch`, `generated_at_utc`) más `sources[]` (los pines de
sus entradas). Reconstruirlo reescribe lo segundo y reproduce lo primero byte a byte.

---

## 2. Estado de partida (medido)

```
$ uv run python scripts/cost_barrier_gate.py --check
cost-barrier drift gate: INTEGRITY_FAILURE (check mode) exit 5
  checks 10/11 PASS · controls 6/6
  [FAIL] inputs:published_pins_match_the_declared_sources
         config/strategy_admission.json content drift (pin 6c4dd0be1fc2...)
```

Tres desviaciones, de naturaleza distinta y con arreglo distinto:

| # | nodo | estado | causa | se arregla con |
| - | ---- | ------ | ----- | -------------- |
| D1 | `config/strategy_admission.json` | `DRIFT` | el ledger se reparó en `eb53e631`; el pin publicado es el de **antes** (`6c4dd0be…`), y además está calculado sobre la representación **CRLF** de `ddaf14d1`, que no es ningún blob | recertificar el bundle: el pin pasa a `5e2ccc57…` (LF) |
| D2 | `reports/strategy-baseline/COST_BARRIER.json` | `ABSENT` | gitignoreado; `--check` lo tolera, el **modo completo** no | materializar desde la copia de evidencia (bytes idénticos, §3.1) |
| D3 | `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | `EOL_ONLY` | su pin de bytes es un render CRLF; lo cubre el `state_sha256` semántico, por eso el gate lo acepta como `state-exact` | recertificar (el pin de bytes pasa a LF) — **no urgente**, pero se corrige en el mismo paso |

Nota que decide el diseño del plan: **sólo D1 bloquea**. D2 es recuperable de forma
exacta y D3 ya está cubierto por el pin de estado. El plan no debe convertir D2/D3 en
razones para tocar economía.

---

## 3. Precondiciones (todas comprobables, ninguna opcional)

1. **Autorización explícita** para escribir evidencia publicada. Este WP no la tiene.
2. Rama limpia y dedicada; el árbol de trabajo sin cambios en
   `config/`, `data/recovery/`, `src/`, `scripts/cost_barrier_*.py`, `.github/workflows/`.
3. `config/strategy_admission.json` **estable**: es el ledger reparado de `eb53e631`
   (`5e2ccc57…`). Si el árbol no está en ese contenido, parar: se estaría
   recertificando un estado distinto.
4. Checkout con `core.autocrlf` irrelevante: `.gitattributes` fija `-text` para el
   ledger, la matriz, los resultados V3 y el modelo de costes. Verificarlo antes de
   capturar ningún pin (`git check-attr -a config/strategy_admission.json`).
5. **Ningún pin se edita a mano** en ningún paso. Si un paso no produce el digest
   esperado, se para y se investiga.
6. `uv run python scripts/cost_barrier_gate.py --check` ejecutado antes de empezar,
   con su salida guardada: es la línea base contra la que se compara el final.

---

## 4. Procedimiento, en orden

Cada paso es un comando del repositorio; ninguno inventa cifras. La simulación completa
en un clon temporal (nunca en este árbol) está en
[`evidence/simulated_certification_record.json`](evidence/simulated_certification_record.json).

### Paso 0 — línea base

```bash
uv run python scripts/cost_barrier_gate.py --check  > gate_before.txt   # exit 5, 10/11
uv run python -m pytest tests/unit/research/test_cost_barrier_explorer.py \
  tests/unit/research/test_cost_barrier_gate.py \
  tests/unit/research/test_cost_barrier_adversarial.py \
  tests/unit/research/test_cost_barrier_ci_parity.py -q > tests_before.txt  # 19 failed / 74 passed
```

`19 failed, 74 passed` es la firma medida de este estado; cualquier otro número significa
que el árbol no es el que este WP midió.

### Paso 1 — materializar la entrada (recuperación exacta)

```bash
uv run python scripts/cost_barrier_evidence.py --materialize
# target: reports/strategy-baseline/COST_BARRIER.json
# sha256: 2437f446051d97ec15bd1bd95de550d46db3fb4d555ccab6557a3a2b2bac1fd4
```

El digest **debe** ser `2437f446…` (= pin del explorer). Si no lo es, parar: la copia de
evidencia y el pin ya no coinciden y el problema es otro.

Efecto medido de este paso aislado: los nodos rojos de la suite de contrato bajan de 19
a 9 ([`evidence/contract_suite_with_input_materialised.txt`](evidence/contract_suite_with_input_materialised.txt)).
Los 10 que se cierran aquí no eran deriva: eran el input ausente.

### Paso 2 — reconstruir explorer y verificación

```bash
uv run python scripts/cost_barrier_explorer.py --out-dir <tmp>
uv run python scripts/cost_barrier_verify.py --explorer <tmp>/COST_BARRIER_EXPLORER.json \
                                             --out <tmp>/COST_BARRIER_VERIFICATION.json
```

**Control obligatorio antes de publicar**: el `payload_sha256` del explorer reconstruido
debe ser `4383d812d6e18928c53894c7ee3ba063723d351ab945fcfc206373dfaa2621fb`. Si cambia,
la recertificación dejó de ser de integridad y hay que parar y abrir un WP de resultados.
Las únicas hojas que pueden diferir son `branch`, `generated_at_utc`, `head` y los dos
digests de `sources[]` ([`evidence/explorer_rebuild_diff.txt`](evidence/explorer_rebuild_diff.txt)).

### Paso 3 — publicar y capturar los pines que citan lo publicado

```bash
# publicar explorer + verification; commit
uv run python scripts/cost_barrier_evidence.py --capture   # INPUT_EVIDENCE + PRODUCER_PINS
# commit
```

El orden no es decorativo: capturar los pines **antes** de publicar ancla digests de
ficheros que aún no existen, y publicar sin capturar deja la cadena medio pinneada. En
la simulación, saltarse este paso deja **3 nodos rojos** de 108
([`evidence/recertified_partial_tests.txt`](evidence/recertified_partial_tests.txt)):
`test_the_pinned_producers_match_their_manifest`,
`test_a_changed_producer_is_a_named_failure` y
`test_the_certification_record_digests_content_not_a_checkout`.

### Paso 4 — certificar en dos tiempos

```bash
uv run python scripts/cost_barrier_certify.py     # borrador: se niega, escribe digests frescos
# commit
uv run python scripts/cost_barrier_certify.py     # certifica: exit 0
```

La certificación se niega a certificar sobre un árbol sucio: el commit intermedio es
parte del procedimiento, no una comodidad. Resultado simulado:
`status CERTIFIED`, `exit_code 0`,
`satisfies_full_certification true`.

### Paso 5 — verificación independiente y cierre

```bash
uv run python scripts/cost_barrier_gate.py --check            # FULL_REPRODUCTION_PASS, exit 0
uv run python scripts/cost_barrier_verify.py ...              # PASS, 0 failed, 13/13 controls
uv run python -m pytest <las 4 suites> -q                     # 93 passed
uv run python -m pytest tests -q                              # 85 rojos, 0 en cost-barrier
```

La firma de éxito es doble y ambas partes son obligatorias:

- **verde donde debe**: 93/93 en la suite de contrato; set diferencia de nodos rojos
  contra el estado inicial = exactamente 19, `introduced = []`
  ([`EVIDENCE_IMPACT_MATRIX.json`](EVIDENCE_IMPACT_MATRIX.json) → `simulation.full_suite.set_difference`);
- **igual donde importa**: `payload_sha256` del explorer sin cambios. Un verde con un
  payload distinto sería un fallo disfrazado de éxito.

---

## 5. Rollback

El procedimiento completo cabe en **tres commits** (publicar explorer+verification;
capturar pines; certificar). El rollback es la reversión de esos tres, en orden inverso:

```bash
git revert --no-edit <certificación> <pines> <explorer+verification>
uv run python scripts/cost_barrier_gate.py --check     # debe volver a exit 5, 10/11
```

Criterio de rollback correcto: el gate vuelve exactamente al estado de partida
(`INTEGRITY_FAILURE`, `10/11`, mismo pin `6c4dd0be…`). Si no vuelve, el rollback fue
parcial y hay que tratarlo como incidente, no como vuelta atrás.

No se hace `reset --hard` ni se reescribe historia: la evidencia publicada es un
registro, y su corrección también.

---

## 6. Verificación independiente del propio plan

Un verificador independiente (`scripts/wp_eco003_verify.py`, salida en
[`INDEPENDENT_VERIFICATION.json`](INDEPENDENT_VERIFICATION.json)) re-deriva, sin
importar el script de auditoría:

1. que los digests publicados y los del disco coinciden con lo que afirma el informe;
2. que el pin `6c4dd0be…` es el CRLF de `ddaf14d1` y de ningún blob;
3. que la copia de evidencia del input reproduce `2437f446…`;
4. que los seis `MULTI_FAMILY_RESULTS_*.json` no están en ningún commit (`git log --all`);
5. que la matriz no contiene ningún digest;
6. que el árbol no cambió en `src/`, `config/`, `data/` respecto de `2bd6e346`;
7. que el estado de la suite y del gate es el declarado.

Un plan cuyas afirmaciones no sobreviven a eso no es un plan: es una intención.

---

## 7. Lo que este plan deliberadamente **no** hace

- No añade un `state_sha256` al pin del ledger en el mismo commit: es un cambio de
  contrato del explorer y merece su propia revisión (recomendación para WP-004, §4 del
  informe final). Mezclarlo aquí haría la recertificación irreversible en la práctica.
- No intenta reconstruir `MULTI_FAMILY_RESULTS_*.json` (imposible, ver
  [`SOURCE_RECOVERY_ASSESSMENT.md`](SOURCE_RECOVERY_ASSESSMENT.md)).
- No relaja ningún check del gate, ni reordena la precedencia integrity→blocked, ni
  toca `test_a_missing_required_input_blocks_rather_than_fails`.
- No declara PASS global: el repositorio seguirá con 85 nodos rojos preexistentes, y el
  informe lo dice.
