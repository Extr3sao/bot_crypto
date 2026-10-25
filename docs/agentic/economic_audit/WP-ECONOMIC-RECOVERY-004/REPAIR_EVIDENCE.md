# WP-ECONOMIC-RECOVERY-004 — Evidencia de la reparación

> Qué se cambió, por qué cada cambio está justificado por la evidencia, y qué **no** se
> cambió. Cada cifra de este documento sale de un comando cuya transcripción está en
> [`evidence/`](evidence/).

---

## 1. Autoridad del ledger: por qué la revisión de `HEAD` y no otra

El pin publicado (`6c4dd0be…`) no coincide con ningún blob commiteado. Reproducido
([`evidence/authority_reproduction.txt`](evidence/authority_reproduction.txt)):

| revisión | blob (LF) | render CRLF | ¿es el pin? |
| --- | --- | --- | --- |
| `65b3821d` (2026-09-28 06:57) | `64184cb0…` | `c1186fe0…` | no |
| `ddaf14d1` (2026-09-28 11:35) | `92aab541…` | **`6c4dd0be…`** | **sí, como CRLF** |
| `eb53e631` (2026-10-25 11:38) = `HEAD` | `5e2ccc57…` | `21a642de…` | no |

Y el diff entre `ddaf14d1` y `HEAD` es **una sola línea**:

```diff
-      "sha256": "5f794c36829f947ff56de3995b68bb4f374d770bb32bd6147bff59a014ea05bf"
+      "sha256": "4e15882cd3b9bc31e0f4922fddd65d325fc949648b542bef9e03ebe0f822af81"
```

Es el ancla de la matriz: `5f794c36…` no corresponde a ninguna revisión commiteada de
`docs/STRATEGY_ADMISSION_MATRIX.json` (sólo hay una, `3271a975`, cuyo digest es
`4e15882c…`), y WP-002 la sustituyó por el digest real. Por tanto:

- **contenido autoritativo** = `HEAD` (`5e2ccc57…`), porque es el único que cita la
  matriz commiteada y el que `build_strategy_admission.py --check` reproduce (exit 0,
  comprobado en la verificación independiente);
- el pin `6c4dd0be…` **nunca describió un fichero del repositorio**: es la representación
  CRLF de una copia de trabajo de `ddaf14d1` en una máquina Windows, anterior a fijar
  `-text` en [`.gitattributes`](../../../../.gitattributes).

No se eligió "la revisión más reciente" por ser la más reciente: se eligió porque es la
que satisface sus propias dependencias, y la anterior no.

---

## 2. Los dos defectos reparados

### DEF-1 — El pin del ledger era un artefacto de máquina

| | antes | después |
| --- | --- | --- |
| `sources[].sha256` (ledger) | `6c4dd0be…` (CRLF de `ddaf14d1`) | `5e2ccc57…` (bytes del blob en `HEAD`) |
| `sources[].state_sha256` | `null` | `4d1b1e6a…` (contrato v1) |
| `sources[].state_contract` | — | `strategy-admission-ledger-identity-v1` |

El mismo defecto de convención existía en `ACTIVE_ECONOMIC_AUDIT.json`
(`e05be22b…` = CRLF de `8a101e88…`), pero allí era inofensivo porque el `state_sha256`
semántico ya lo cubría. La reparación lo normaliza también: `8a101e88…` (LF).

### DEF-2 — Los escritores dejaban que el host eligiera los finales de línea

Descubierto al reconstruir: `Path.write_text(...)` sin `newline="\n"` traduce `\n` al
separador del sistema, así que un rebuild en Windows reescribió **21 605 líneas** del
explorer publicado sin cambiar un número, y lo mismo en la verificación y los sidecars.
Es exactamente el defecto que WP-002 arregló en el builder del ledger, y que aquí
invalidaba cualquier recertificación hecha en este host.

Corregido en los cinco escritores del lane (`cost_barrier_explorer.py`,
`cost_barrier_verify.py`, `cost_barrier_evidence.py`, `cost_barrier_certify.py`,
`cost_barrier_adversarial.py`) con `newline="\n"`, y sujeto por un test que reconstruye
en un directorio temporal y exige **cero** `\r\n` en los artefactos producidos y en los
commiteados.

Prueba del efecto: antes del arreglo, `git diff --stat` del explorer era
`21605 +++++-----`; después, `13 ++--`.

---

## 3. Contrato de identidad semántica (v1)

Documentado en [`LEDGER_INTEGRITY_CONTRACT.md`](LEDGER_INTEGRITY_CONTRACT.md). Resumen de
lo que cambia en el gate:

```
estado    = documento sin _generated_by
envelope  = {"contract": "strategy-admission-ledger-identity-v1", "state": estado}
digest    = sha256(json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False))
```

Decisión del gate para una entrada con `state_sha256`:

```
EXACT_STATE  ⟺  state recalcula igual  AND  bytes == pin  ó  bytes == render LF/CRLF
DRIFT        en cualquier otro caso
```

Es **más estricto** que juzgar sólo por estado: el control adversarial que sustituye el pin
del ledger por un digest válido de otro fichero (`foreign pin`) sigue siendo un hallazgo,
porque los bytes dejan de coincidir. La única tolerancia nueva es la representación
LF/CRLF, que es el defecto que el contrato elimina.

---

## 4. Secuencia exacta ejecutada

| paso | comando | resultado |
| --- | --- | --- |
| 1 | `cost_barrier_evidence.py --materialize` | **exit 2**: rechaza porque `scripts/cost_barrier_explorer.py` cambió y el manifiesto de productores aún no se había re-capturado |
| 2 | `cost_barrier_evidence.py --capture` | **exit 3**: rechaza porque el input gitignoreado no está en la máquina |
| 2a | restaurar el input desde la copia de evidencia + verificar digest | `2437f446…` == pin publicado (`MATCH: True`, 3822 bytes) |
| 3 | `cost_barrier_evidence.py --capture` | `CAPTURED`, exit 0 |
| 4 | `cost_barrier_evidence.py --materialize` | exit 0, `already_present`, `same_content: True` |
| 5 | `cost_barrier_explorer.py` | payload `4383d812…`, `checks_failed: 0` |
| 6 | `cost_barrier_verify.py` | `PASS`, `checks_failed 0`, `controls 13/13`, `false_success 0` |
| 7 | `cost_barrier_evidence.py --capture` | re-captura con el artefacto ya publicado |
| 8 | `cost_barrier_explorer.py` (en `HEAD` = `7311e553`, el commit del contrato) | payload `4383d812…` (**idéntico**), `checks_failed: 0` |
| 9 | `cost_barrier_verify.py` | `PASS`, `controls_missed 0`, `false_success 0` |
| 10 | `cost_barrier_evidence.py --capture` | `CAPTURED`, input `EXACT` (`2437f446…`) |
| 11 | `cost_barrier_gate.py` (modo completo) | `FULL_REPRODUCTION_PASS`, 13/13, exit 0 |

Los pasos 8-10 existen porque el artefacto de los pasos 5-7 se había generado cuando `HEAD`
era `2bd6e346`, y su bloque de procedencia (`head`, `branch`, `generated_at_utc`) habría
nombrado un commit cuyo código no produjo los pines que el fichero publica —el mismo defecto
de trazabilidad que este WP repara—. Se reconstruyó en el commit que sí los produce; el
`payload_sha256` no cambió.

### Dependencia circular declarada (DEF-3, no reparada)

`--materialize` exige productores pinneados; `--capture` exige el input presente. En una
máquina que nunca tuvo el input y cuyo productor cambió, ambos se bloquean mutuamente. Se
resolvió restaurando el input desde su copia de evidencia **byte-idéntica** y verificando el
digest contra el pin publicado antes de nada más (`evidence/repair_02a_restore_input.txt`):
es la misma operación que hace el materializador, hecha a mano porque la herramienta no
puede hacerla en ese orden. Queda como defecto de herramienta para un WP de ergonomía; no
afecta a la integridad, y no se amplió el alcance para arreglarlo.

---

## 5. Qué cambió, byte a byte

[`evidence/repair_diff_summary.json`](evidence/repair_diff_summary.json):

| objeto | antes | después |
| --- | --- | --- |
| explorer `payload_sha256` | `4383d812…` | `4383d812…` (**idéntico**) |
| explorer bytes | `02388981…` (blob de `HEAD`, render CRLF) | `fdc6892f…` (LF; contenido: `generated_at_utc`, `head`, `branch` y 2 pines) |
| ledger bytes | `5e2ccc57…` | `5e2ccc57…` (**idéntico**) |
| ledger byte pin | `6c4dd0be…` | `5e2ccc57…` |
| ledger state pin | `null` | `4d1b1e6a…` |
| audit byte pin | `e05be22b…` (CRLF) | `8a101e88…` (LF) |
| audit state pin | `023b66ff…` | `023b66ff…` (idéntico) |

El diff del explorer son **13 líneas**: tres hojas volátiles y los dos pines de `sources[]`.
Ninguna cifra de coste, comisión, slippage, horizonte, celda o veredicto aparece en él.

---

## 6. Lo que **no** se tocó

- `config/strategy_admission.json`: byte-idéntico a `2bd6e346` (`unchanged_vs_head: true`),
  y `build_strategy_admission.py --check` sigue en exit 0.
- `docs/STRATEGY_ADMISSION_MATRIX.json`, `docs/STRATEGY_DISCOVERY_V3_RESULTS.json`,
  `docs/COST_MODEL_V3.json`, `src/trading_bot/research/microstructure/cost_model_v3.py`:
  sin cambios.
- La precedencia del gate (`integrity → blocked → reproduction`) y el test
  `test_a_missing_required_input_blocks_rather_than_fails`: sin cambios. Ese nodo pasa
  ahora **porque la deriva desapareció**, no porque el test se haya relajado.
- Ninguna estrategia, backtest, comisión, balance ni regla de riesgo.
- Los seis `MULTI_FAMILY_RESULTS_*.json` siguen sin existir en ningún commit: no se
  inventaron para que un informe saliera más verde.
