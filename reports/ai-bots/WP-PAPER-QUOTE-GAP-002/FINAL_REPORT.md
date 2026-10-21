# FINAL_REPORT — WP-PAPER-QUOTE-GAP-002

**Un hueco ya no termina en «no se puede saber»: termina en una prueba o en un bloqueo con nombre.**

**Fecha:** 2026-10-21 · **Rama:** `wp/paper-resume-001` · **HEAD:** `fefb077`
**Árbol:** este WP y RFC-050 están **sin commitear**; el informe describe el árbol de trabajo.
**Modo:** PAPER · **LIVE:** no habilitado · **`live_orders = 0`** · **`FALSE_SUCCESS = 0`**
**Veredicto:** laboratorio y verificador independiente en **PASS**; drill A/B sobre minutos reales
en **PASS** (4/4 criterios). Una limitación del experimento de muerte se declara en §6.

Artefactos: [RUN_REPORT.md](RUN_REPORT.md) · [RUN_REPORT.json](RUN_REPORT.json) · [GAP_LAB.json](lab/GAP_LAB.json) ·
[SHA256SUMS](lab/SHA256SUMS) · [VERIFICATION.json](VERIFICATION.json) · [DRILL.md](drill/DRILL.md) ·
[DRILL.json](drill/DRILL.json) · [MANIFEST.json](archive/MANIFEST.json) ·
[RFC-051](../../../docs/rfc/RFC-051_VISION_QUOTE_GAP_RECOVERY.md) ·
[mapa de autoridad](../../../docs/runtime/runtime_authority_map.md)

---

## 1. Qué estaba roto

RFC-050 dejó el libro en disco, pero con una sola respuesta cuando la vela siguiente al corte no
estaba en el dataset: `UNVERIFIED_GAP`. La frase es correcta y la respuesta es terminal:

```
barrier_is_continuous: ok=false
  bar 1792529400000 is missing; the next bar is 1792530300000
UNVERIFIED_GAP
```

Una sesión que muere con exposición y vuelve con el dataset incompleto no podía avanzar. La única
alternativa que el runtime ofrecía —empezar plano— es exactamente el defecto que RFC-050 cerró:
la exposición desaparece con su stop y la comisión pagada vuelve al saldo.

El runtime **ya tenía** el feed capaz de responder esa pregunta: `vision/quotes.py` carga klines
públicas de 1 minuto con su sha256 y valida la rejilla. Lo que faltaba era una decisión: qué se
puede afirmar con esos minutos y qué no. Eso es este WP.

## 2. Qué se construyó

**`src/trading_bot/vision/gap_recovery.py`** (nuevo) — el dictamen, separado en tres afirmaciones
de fuerza distinta: cobertura (hecho), toque de una barrera (observación en un minuto nombrado) y
orden dentro de un minuto (ambigüedad, no se elige). Tres veredictos —`CLEAR`, `RECONSTRUCT`,
`BLOCKED`— y cuatro estados por posición. No importa `durable` ni el bróker: las fórmulas de stop
y take-profit están escritas de nuevo y un test las ata a `PaperPosition`, para que un verificador
no compruebe que el código coincide consigo mismo.

**`src/trading_bot/vision/lane.py`** — `_apply_gap_plan`: recorre los minutos del hueco en orden y
llama al **mismo** `check_positions_ohlc(..., gap_policy="open_on_gap")` que el bucle de velas.
Cada cierre queda con `phase="GAP_RECONSTRUCTION"`, `exit_ts_resolution="MINUTE_WINDOW"` y su
ventana de minuto. El reloj del lane se apunta al minuto antes de cerrar (`closed_at` dejaba de
mentir) y el cruce de día UTC dispara `reset_daily()` como lo haría el bucle.

**`src/trading_bot/vision/durable.py`, `quotes.py`, `prospective.py`, `ledger.py`** — el contrato
de evidencia se ata al libro: `reconcile_book` exige que la ventana y los `position_id` de la
evaluación coincidan (`GAP_EVIDENCE_STALE`), y la recuperación se publica en `RUN`.

**Dos defectos de durabilidad corregidos** (ninguno introducido aquí; los dos afectaban a la
recuperación, con test de regresión):

1. `save` rotaba `BOOK.json → .prev` y luego reemplazaba: morir entre las dos dejaba **sólo**
   `.prev`, `load()` leía «no hay libro» y la sesión **empezaba plano con exposición**. Ahora la
   generación anterior se copia antes de reemplazar, y un `BOOK.json` ausente con `.prev` presente
   se rechaza (`CorruptBook`).
2. El relevo del cerrojo en carrera permitía que dos procesos creyeran tener el libro. Se
   serializa con `takeover` (`O_EXCL`), se relee el titular y el ganador verifica que el fichero
   en disco sigue siendo el suyo.

## 3. La evidencia

**Datos.** 720 minutos por símbolo grabados del venue (`binance_spot_1m`, `gaps: []`, health `OK`,
extremes `2026-10-20T08:55Z → 20:54Z`), agregados a **144 velas de 5 m** por símbolo con sus
sha256 en `archive/MANIFEST.json`. Cero ticks inventados: los grupos incompletos se cuentan y se
descartan.

**Drill A/B** (`scripts/paper_resume_drill.py`, commit `fefb077`): la misma campaña dos veces, `A`
de un tirón y `B` partida por un hijo **matado con `TerminateProcess`** a los 12,0 s (`killed=true`,
exit 1) y otro que reanuda. Resultado: `verdict=PASS`, `REC-03/04/05/RT-07 = PASS`,
`comparison.differences = []`. `live_orders = 0`.

**Laboratorio de casos** (`lab/GAP_LAB.json`), con el feed de minutos controlado:

| caso | A | B | salida |
| --- | --- | --- | --- |
| `split` (sin hueco) | RAN | RAN | misma economía, campo a campo |
| `quiet` (hueco, nada tocado) | RAN | RAN | `CLEAR` → reanuda con el libro intacto |
| `stop` (stop dentro del hueco) | RAN | RAN | `RECONSTRUCT` → cierre en el minuto observado |
| `take` (take-profit dentro) | RAN | RAN | `RECONSTRUCT` → cierre en el minuto observado |
| `both` (stop y TP en el mismo minuto) | RAN | **BLOCKED** | `GAP_EXIT_AMBIGUOUS` |
| `partial` (4/5 minutos) | RAN | **BLOCKED** | `GAP_NOT_COVERED` |

Además: feed corrupto → **`REFUSED_AT_LOAD`** (el veredicto no llega a existir); segundo escritor
→ **`REFUSED`**; 12 muertes durante el guardado → 12 libros **`READABLE`**, 0 fallos.

## 4. Por qué esto no se aprueba a sí mismo

- El verificador (`scripts/verify_quote_gap.py`) **no importa** `gap_recovery` ni el laboratorio:
  recalcula con aritmética propia. **83/83** comprobaciones, **10/10** controles negativos
  detectados (`negative_controls_undetected = []`), `FALSE_SUCCESS = 0`.
- Entre los controles hay uno que no mata el hash sino la aritmética: `pnl_inflado` cae en
  `stop.same_economics_as_continuous`.
- La última comprobación del verificador es sobre sí mismo: `report.ok_matches_its_own_evidence`
  recompone el `ok` del laboratorio y lo compara (`report says ok=True, recomputed True`).
- El digest **no** se usa como prueba donde no puede serlo: el brazo con hueco nunca comprometió
  esa vela, y su cierre se observó al minuto, no al cierre de la vela. `digests_equal = false` se
  publica tal cual, junto a una comparación campo a campo con las rutas exentas **nombradas y
  justificadas** (`state_digest`, `closed_digest`, `integrity_digest`, `closed_trades[0]/closed_at`,
  `risk/last_loss_ms`, linaje de sesión, contadores de proceso). `differences = []`.

## 5. Estado de verificación

| comprobación | resultado |
| --- | --- |
| `tests/unit/vision` (6 ficheros del WP: durable, gap, gap_venue, sesión ×2, prospective) | **90 passed**, exit 0 |
| `tests/unit/vision` (resto, grupo 1: contabilidad, reloj, causalidad, contrato, guards, ledger) | **100 passed**, exit 0 |
| `tests/unit/vision` (resto, grupo 2: charts, lane, open-phase, provider, señales, subbar) | **128 passed**, exit 0 |
| `tests/unit/vision` (minutos + subbar, subconjunto que el generador re-ejecuta) | **22 passed**, exit 0 |
| `tests/unit/paper` + `tests/unit/risk` | **220 passed**, exit 0 |
| suite amplia `vision + paper + risk + market_data` en una invocación | **694 passed**, `EXIT=0` (554,16 s) |
| `ruff` sobre los 17 ficheros del WP (runtime + scripts + tests) | **exit 0** |
| `mypy` sobre `gap_recovery`/`durable`/`quotes`/`lane`/`prospective`/`broker`/`manager` | **exit 0** |
| verificador independiente | **83/83**, **10/10** controles, `FALSE_SUCCESS=0` |
| laboratorio (6 casos + corrupción + concurrencia + 26 muertes reales) | **`ok=true`** |
| drill A/B | **PASS** (4/4 criterios) |
| generador de evidencia (`make_quote_gap_evidence.py`) | **7 checks, 0 failed**, exit 0 |

Nota de método: `pytest tests/unit/vision` **completo en una sola invocación supera los 10 min** en
este host (los cinco tests de `test_open_phase_causality` suman ~182 s y el resto de charts es
lento), así que la suite amplia se lanzó en segundo plano con su log (`$ comando` + `EXIT=`) y el
generador lo consumió con `--suite-log` en vez de re-ejecutarla dentro de un script que ya tarda
minutos. La tabla de arriba no omite ningún fichero: los 694 son la invocación completa, y las
invocaciones parciales son los mismos tests agrupados para poder verlos terminar.

## 6. Límites explícitos

- **La muerte del hijo siempre cayó antes del `COMMIT`.** Los 14 intentos de `kill-resume`
  mataron al proceso con la posición aún abierta (`closed 0 → 0`, `open 1`) y el libro no cambió
  en ninguno: eso prueba la rama «muere antes → se recalcula desde los mismos minutos». La rama
  «muere después del `COMMIT` → no se vuelve a cerrar» la sostiene
  `test_a_close_that_already_happened_is_not_booked_twice`, no una muerte real. Se declara como
  tal en vez de contarla como cubierta por el experimento.
- **El hueco tiene que empezar en la barrera.** Una vela ausente *después* de reanudar la salta el
  bucle de velas y no se evalúa con minutos a mitad de corrida; corregirlo cambia la semántica de
  `DATA_GAP` que otros tests fijan.
- **Opiniones en vuelo:** se bloquean (`GAP_PENDING_OPINION`), no se reconstruyen.
- **Feed en vivo:** probado con minutos archivados y con minutos sintéticos controlados; la
  latencia de entrega y los minutos parciales del venue no están medidos aquí.
- **Modelo:** proveedor de guion, cero llamadas.
- **LIVE:** no hay ruta de orden en esta cadena; `live_orders = 0` se comprueba, no se promete.
- **Sin commit:** todo el WP está sin commitear en esta copia; el informe describe el árbol de
  trabajo, no un commit.

## 7. Qué queda abierto

1. **Huecos a mitad de corrida** (§6): la evaluación de minutos sólo existe en el arranque.
2. **Feed de 1 minuto en vivo** dentro del reconciliador: hoy se inyecta un `MinuteFeed` ya
   cargado, no el collector.
3. **Reconciliación contra el exchange** cuando exista ruta de orden: el libro se reconcilia
   consigo mismo y con el dataset, no con un venue que pudiera haber ejecutado el stop.
4. **Retención** de `BOOK_EVENTS.jsonl` y `.prev`.
