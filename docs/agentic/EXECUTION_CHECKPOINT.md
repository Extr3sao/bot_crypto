## 2026-10-21 · Conciliación del paquete `EXP-003N_preflight_blocked_20261020` — el bloqueo era un identificador gastado, no un checkout ausente

**Objetivo:** decidir si el preflight recibido (sandbox sin checkout autoritativo) describe trabajo pendiente aquí, y qué parte de él es adoptable.

**Hecho**

1. **La premisa es falsa.** `origin` es `github.com/Extr3sao/bot_crypto.git`; el paquete buscó
   `Extr3sao/Bot-Trading`. El checkout es este, y `EXP-003N-GROSS-FIRST-DISCOVERY-001` está cerrado en
   `HEAD` (`cd3fc31` al abrir; `277d1df` al cerrar, por los commits de otro agente `6b0dac1` y `277d1df`).
2. **B01–B05, disueltos uno a uno** con evidencia por fichero, en
   `docs/agentic/RECONCILIATION_EXP-003N_PREREG_PRECHECK.md`. N en cifras: **13 `REJECT`**,
   **10 `INSUFFICIENT_EVIDENCE`**, **1 `EXPERIMENT`**, **0 `ADVANCE`**; verificador **12/12** y
   **10/10** controles; holdout `2026-08-06 → 2026-08-20` `CLOSED`, `holdout_opened: False`.
3. **Prueba decisiva, medida sin tocar el código recibido:** el gate del paquete, con su ledger rellenado
   con el inventario real (`inventory_completed: true`, `exp003n_executions: 1`), responde `BLOCKED`,
   exit 2, `PRIOR_EXP003N_RUNS_FOUND_RETROSPECTIVE_ONLY`. Sus 16 tests se re-ejecutaron aquí: **16/16 OK**.
   El diagnóstico es reproducible; la premisa no. Nada del paquete se copió al árbol.
4. **Dataset de N recomprobado aquí:** los tres `.jsonl.gz` de 1m coinciden byte a byte con los digests
   congelados en `design/DESIGN.json` (`7fbdfefa…`, `cf04dc37…`, `33342aac…`); los bytes quedan fuera de
   Git por regenerables y los certifica el digest, no una promesa.
5. **Un defecto se observó y dejó de existir durante la conciliación.** A `cd3fc31` faltaban `SEAL.json` y
   `SHA256SUMS.txt` y los ocho entregables estaban sin seguimiento; a `277d1df` el sello existe y
   **`sha256sum -c` → 29/29 OK**, con `design_sha256 a0776fa3…` igual al que compara V3. Se registra como
   observación cerrada por otro agente; **no se tocó** ese árbol ni se le atribuye nada a este.

**Adoptado:** la forma del preflight fail-closed (digests reales, embargo, rechazo de holdout ya
inspeccionado, `BUILDER != VERIFIER`, ledger de ejecuciones previas, prereg commiteado) como guarda
**parametrizada por identificador** para el próximo experimento.
**No adoptado:** el `preregistration.json` del sandbox (**43 `null`**,
`reconstructed_from_prior_session_summary_not_runtime`) ni su ledger de previas; rellenarlos ahora sería
fijar umbrales después de conocer el resultado.

**No ejecutado:** economía (`economic_executions: 0`); `scripts/exp_003n_verify.py` no se re-ejecutó — se leyó
su salida publicada, no se reprodujo. `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON` sigue siendo cierto.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
(cd reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 && sha256sum -c SHA256SUMS.txt)   # 29/29
git ls-tree -r --name-only HEAD | grep -c EXP-003N                                      # 31
```

---

## 2026-10-20 · EXP-003M-MAKER-FILL-REALITY-001 — fills maker contra la cinta, y evidencia reproducible

**Objetivo:** sustituir el supuesto «toque = fill» de 003L por la cinta de operaciones observada, y
entregar un pipeline que genere, verifique y selle sin poder romperse en el orden. **Rama:**
`agent/ai-bots/RFC-TAP-AI-BOTS-003` · **HEAD:** `b0e15497d967` · **Modo:** OFFLINE,
`LIVE_ENABLED=false`, 0 órdenes, 0 credenciales.

**Hecho (medido)**

1. **Predecesor reproducido antes de juzgarlo.** El sello de 003L verifica 70/70 ficheros. Las 47
   señales se extraen de su ledger con los límites re-derivados de su tabla de costes. El escenario
   F0 (supuesto de 003L: todo toque llena entero al precio mejorado) restablece lo publicado
   exactamente: tasa `0.93617`, neto/señal `-0.45225547`, neto/cierre `-0.48309107`, bruto/cierre
   `0.26690893` (deltas 0.0).
2. **Auditoría de datos.** `data.binance.vision` publica para spot **solo** `aggTrades`, `klines`
   y `trades`: no hay libro L2 ni `bookTicker` (404), así que la cola no se puede observar. La
   profundidad por bandas de USDⓈ-M existe, es otro instrumento y se usa solo como calibración.
   Cinta: **42 pares** `(símbolo, día)`, **680.484** operaciones conservadas de 27.887.409 dentro de
   las ventanas, **405,6 MiB** descargados, sin filtro por precio, lado ni resultado. Klines del
   mismo archivo contra el dataset congelado: **60.480 barras comparadas, 60.480 exactas**.
3. **Fills.** F0 44/47; F1 (cola 1x, 400 ms) 42/47 con neto/cierre `-0.5347`; F2 (cola 4x, 2 s,
   5 min, 2 bp, spot VIP0) 33/47 con `-0.9233`; F3 (cinta sin cola) 44/47 con `-0.4709`. Barrido de
   24 puntos de cola y latencia: **0 con neto por cierre positivo**. Selección adversa medida:
   `+2.06` bp en contra a 5 minutos con cinta frente a `-1.78` bp en el conjunto que F0 habría
   llenado (Δ `3.84` bp). La cola apenas muerde con 500 USDT: cambia 3 de 47 fracciones.
4. **Economía.** Techo bruto por cierre `0.2669` USDT frente a suelo de `0.75` (7.5 bp, BNB) o
   `1.00` (10 bp): cobertura **0.356x**. Fallan `G4_economics_pessimistic`, `G5_optimistic_ceiling` y
   `G7_evidence_class`. Veredicto **`REJECT`**: no hay ventaja neta tras modelar fills maker, y
   tampoco la habría con fills perfectos.
5. **Pipeline y sello.** `exp_003m_pipeline.py generate` → tests → verificación **antes** del
   informe → informe → `seal`. El verificador se niega a escribir si existe `SEAL.json`; el sello
   excluye `SHA256SUMS.txt`, `SEAL.json` y el propio manifiesto de datos (sin hash circular) y
   recorre el árbol completo con `os.walk`, no un listado truncado. **14/14 PASS, 8/8 controles
   negativos, `false_success=0`**; **18** ficheros publicados + **126** de datos sellados, ambos
   `sha256sum -c` OK; idempotencia **12/12** artefactos byte-idénticos; **25** tests, `ruff` 0,
   `mypy --strict` 0. Configuración congelada por digest (`risk.yaml` `3c27c866d5f1`,
   `runtime.yaml` `ac3cf4fce9ff`, `vision.yaml` `ba817ef6f2c8`): el motor de fills se niega a
   cotizar si `default_stop_loss_pct`/`default_take_profit_pct` o el flag live cambian.
6. **Defectos registrados.** D1 el toque no es un fill (el daño es *cuándo*, no cuántos); D2 el
   escenario base de 003L usaba el descuento BNB (0.25 USDT por operación sin declararlo); D3 el
   archivo diario publica microsegundos y el dataset congelado milisegundos (una comprobación que
   asumiera una sola unidad comparaba cero barras); D4 la cola no es observable; D5 bug propio: el
   índice del fill se calculaba con la época en vez de con el índice de barra y dejaba el 100 % de
   los fills en `OPEN_AT_END` — detectado por la distribución de estados y corregido.

**Pendiente / bloqueado**

- **Fills estimados, no observados**: no se envió ninguna orden. El techo honesto es
  `ESTIMATED_FROM_OBSERVED_TRADE_TAPE`, nunca una promoción.
- El holdout `2026-08-06 → 2026-08-20` sigue **cerrado**; el verificador falla si aparece una fila o
  una URL con fechas de esa ventana.
- La cinta y las klines (400 MiB) quedan fuera de git: un checkout limpio debe ejecutar `generate`
  (descarga cacheada) antes de que `DATASET_SHA256SUMS.txt` pueda verificar.
- Solo se juzgó `5m/mean_reversion`; no dice nada de otros timeframes ni de otras familias.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py status
./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py verify --online   # solo lectura
./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py idempotent
(cd reports/ai-bots/EXP-003M-MAKER-FILL-REALITY-001 && sha256sum -c SHA256SUMS.txt && sha256sum -c DATASET_SHA256SUMS.txt)
```

## 2026-10-20 · EXP-003L-EXECUTION-ECONOMICS-001 — el peaje, descompuesto y medido

**Objetivo:** medir si el mecanismo de ejecución (taker vs maker, comisión vs spread) es lo que
mata la ventaja, o si la ventaja no existe. **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` ·
**HEAD de partida:** `b0e15497d967` · **Modo:** PAPER/OFFLINE, `LIVE_ENABLED=false`.

**Hecho (medido)**

1. **Baseline y dataset.** Los digests de `BTCUSDT`/`ETHUSDT`/`SOLUSDT` recomputan contra el
   manifiesto congelado de 003K (`7fbdfefa…`, `cf04dc37…`, `33342aac…`); `risk.yaml` y
   `vision.yaml` son idénticos a los de 003K. Diseño sellado **13:23:34Z**, corrida más temprana
   **13:36:24Z** (`VL1`). Reproducción a 5 m de las dos familias de 003K: `all_rows_identical=True`,
   `all_nets_match=True` (`VB4`).
2. **Grid ejecutado:** 4 timeframes × 2 familias = **8 corridas**, **1 430 cierres**. Celdas sin
   corrida declaradas en `TIMEFRAME_COMPARISON.md` por presupuesto de cómputo (decidido antes de
   mirar resultados de 003L).
3. **Economía.** Mejor configuración `5m/mean_reversion` (47 cierres): bruto de referencia
   `+0.426958` USDT/op frente a `1.268963` de coste, neto `-0.842005`, IC95 % `[-1.9443, 0.1845]`,
   profit factor 0.582. Taker ≈ **25.4 bp** de peaje; maker spot BNB ≈ **17.6 bp** (medido, 0.936
   de fill rate **simulado**), selección adversa `-4.84 bp`. El único escenario cercano a cero
   (`-0.0140` USDT/op) es maker de futuros a 2 bp, que este carril spot no puede ejecutar.
4. **Conclusión:** bajar el peaje recorta la pérdida, no crea la ventaja. Veredicto
   `NO_VIABLE_CANDIDATE`: 6 `REJECTED` + 2 `BLOCKED_INSUFFICIENT_EVIDENCE` (34 y 20 cierres).
   El holdout `2026-08-06 → 2026-08-20` **no se abrió**.
5. **Verificación.** `scripts/exp_003l_verify.py --negative-controls`: **15/15 PASS** y **8/8**
   controles negativos detectados (look-ahead, fill anterior a la respuesta, doble cierre, neto
   manipulado, métricas que no recomputan, éxito falso, fuga de holdout, maker vendido como
   observado), `false_success=0`. Sello `SHA256SUMS.txt` con **70 ficheros**, verificado con
   `sha256sum -c` sin discrepancias. El sello se emite **después** del verificador: correr
   `exp_003l_verify.py` tras `exp_003l_report.py` reescribe `analysis/VERIFICATION.json` y rompe
   su hash, así que el orden del bloque de reanudación no es cosmético. Tests nuevos
   `tests/unit/reports/test_exp_003l_execution.py`: **28 passed**; `ruff` 0; `mypy --strict` 0 en
   los cinco scripts del experimento.

**Pendiente / bloqueado**

- **Fills maker simulados, nunca observados.** El fill rate 0.936 y la selección adversa salen de
  barras de 1 m, no del libro. Declarado así en los 8 ficheros de ejecución (`VL15`).
- **Holdout cerrado por directiva.** `GAP-VK9_oos_scope` sigue abierto; no se contabiliza como
  superado.
- **El verificador es otro programa, no otra persona** (`INDEPENDENT_VERIFIER=PROGRAM_NOT_PERSON`).
- `reports/ai-bots/*` está ignorado por git (`.gitignore:463`): la evidencia viaja por artefactos
  locales sellados, no por commit.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/exp_003l_baseline.py
./.venv/Scripts/python.exe scripts/exp_003l_execution.py --timeframe 5m
./.venv/Scripts/python.exe scripts/exp_003l_analysis.py
./.venv/Scripts/python.exe scripts/exp_003l_verify.py --negative-controls
./.venv/Scripts/python.exe scripts/exp_003l_report.py
(cd reports/ai-bots/EXP-003L-EXECUTION-ECONOMICS-001 && sha256sum -c SHA256SUMS.txt)
```


## 2026-10-20 · EXP-003K-CANDIDATE-001 — segunda estrategia y suelo de costes

**Objetivo:** demostrar el ciclo completo PAPER y evaluar una segunda `AlphaFamily` con ventaja
económica verificable después de costes, sin tocar 003J. **Rama:**
`agent/ai-bots/RFC-TAP-AI-BOTS-003` · **HEAD de partida:** `56aea83` · **Modo:** PAPER/OFFLINE,
`LIVE_ENABLED=false`.

**Hecho (medido)**

1. **WP-1 — determinismo de 003J cerrado.** `control/research`: 3 541 filas, dos repeticiones
   idénticas y **byte-idénticas al ledger congelado**. `real/research`: 3 732 filas, repeticiones
   idénticas entre sí pero **no byte-idénticas** al congelado; la causa está medida, no supuesta:
   sobre 10 días, 986 filas en ambos lados, mismos `kind/symbol/side/intent/entry/exit/pnl`,
   140 fills, 140 cierres y neto `-191.2241394` en los dos. Lo que cambió es el **texto** de la
   decisión (`rationale`, `invalidation`, `provider.response_chars`) al generalizar el adaptador.
   Artefactos: `runs/<arm>/research/DETERMINISM.json`, `runs/real/research/SEMANTIC_PARITY.json`.
2. **WP-1 — ciclo completo.** 732 operaciones cerradas reconstruidas desde las barras congeladas:
   5 856/5 856 checks (precio de entrada desde el open citado, referencia de salida dentro del
   rango de su barra, ventana de resolución, delta de caja = PnL neto, posición retirada del libro,
   bruto recalculado desde los dos precios). `analysis/CLOSED_CYCLE.json`.
3. **WP-2 — economía.** El OOS de 003J está **dominado por costes**: bruto de referencia
   `+0.416601` USDT frente a `225.817645` de costes y `-225.401044` netos (100.18 % de la pérdida).
   El IC95 % del bruto por operación `[-0.458661, 0.433836]` contiene el cero: la entrada no tiene
   ventaja direccional demostrable. MFE medio 0.597 % frente a −0.26 % neto por operación.
   `analysis/ECONOMIC_AUDIT.json` con cuatro hipótesis refutables.
4. **WP-3 — seis familias sobre dataset nuevo.** Dataset PIT `2026-06-21 → 2026-08-20`
   (3 × 86 400 barras, 0 huecos; digests sellados antes de correr). Research: ninguna familia pasa
   las tres puertas. Mejor bruto/op `mean_reversion` `+0.426958` USDT (47 cierres) frente al suelo
   de costes de `1.29`. `ema_crossover` `-0.369793`; `momentum` `-0.037653`; `breakout` `-0.717660`;
   `trend` `-0.094225`; `volatility` `-0.012953`. Etapa B **BLOCKED / NO_VIABLE_CANDIDATE** y el
   holdout `2026-08-06 → 2026-08-20` **no se abrió**: queda intacto para el próximo experimento.
5. **WP-4 — verificación.** Verificador separado `scripts/exp_003k_verify.py`: 11 PASS, 1
   `NOT_EXECUTED` (holdout sin tocar, por diseño), **6/6 controles negativos detectados**
   (look-ahead, fill anterior a la respuesta, doble contabilización, neto manipulado, selección que
   ignora su regla, éxito falso), `false_success=0`. Tests: `325 passed` (vision+reports),
   `ruff` 0, `mypy` 0.

**Pendiente / bloqueado**

- **Ninguna familia tiene ventaja bruta.** No es un problema de salidas: el suelo de costes
  (25.8 bp round-trip sobre 500 USDT) está por encima del bruto de las seis.
- `GAP-VK9_oos_scope`: el holdout no se usó. Declarado, no contabilizado como superado.
- **003J arrastra un drift externo:** `RUN_REPORT.md` (13:39 local), `FINAL_REPORT.md` (13:35) y
  `analysis/DEFECTS.json` (13:38) fueron reescritos por otro proceso/agente después del sellado de
  las 11:45. `V17_sha256sums` da 25/28. No se reparó ni se volvió a sellar: sobrescribir ficheros
  de otro escritor destruiría la evidencia del drift. Ledgers, dataset y `RUN_REPORT.json` siguen
  intactos.
- El verificador es otro programa, no otra persona (`INDEPENDENT_VERIFIER=PROGRAM_NOT_PERSON`).

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/exp_003k_audit.py
./.venv/Scripts/python.exe scripts/exp_003k_select.py          # BLOCKED, no_viable_candidate
./.venv/Scripts/python.exe scripts/exp_003k_cycle.py --partition research
./.venv/Scripts/python.exe scripts/exp_003k_determinism.py --days 2
./.venv/Scripts/python.exe scripts/exp_003k_verify.py --negative-controls
./.venv/Scripts/python.exe scripts/exp_003k_report.py
(cd reports/ai-bots/EXP-003K-CANDIDATE-001 && sha256sum -c SHA256SUMS.txt)
```

## 2026-10-20 · EXP-003I-THROUGHPUT-001 — diagnóstico de exposición, capacidad y cierres

**Objetivo:** explicar con evidencia por qué la sesión 003I registró 0/30 cierres naturales y
35/36 señales bloqueadas, sin cambiar el runtime ni ningún límite de riesgo. **Rama:**
`agent/ai-bots/RFC-TAP-AI-BOTS-003` · **HEAD:** `5fd791d` · **Modo:** PAPER/OFFLINE.

**Hecho (medido)**

1. **Reconstrucción conciliada 11/11** contra la evidencia de 003I: 72 decisiones, 36 direccionales
   (18 LONG + 18 SHORT, todas BTC), 35 bloqueadas, 1 relleno, 0 cierres. El escenario base
   reproduce el relleno al céntimo (82381.72 @ 10:46:00Z), la equity marcada (9998.65205113) y
   el drawdown (0.030308 %).
2. **El bloqueo tiene tres capas, no una.** (a) *Generador:* `PaperScriptProvider` rota
   `LONG/NO_TRADE/SHORT/NO_TRADE` con contador global; ETH cae siempre en NO_TRADE (36/36).
   (b) *Capacidad:* `PaperBroker._positions` está indexado por símbolo, así que 1 slot/símbolo
   es estructural y `max_open_positions=3` nunca se activa; tras el primer relleno, las 35
   señales restantes del símbolo se descartan.
   (c) *Salida:* el objetivo a +75 bp quedó por encima de la excursión favorable de +45.6 bp
   (stop a −50 bp vs adversa −30.1 bp), así que la única posición viva no tenía nivel que tocar.
3. **Contrafactuales (simulados, no fills).** 2 y 3 slots: 2 y 3 rellenos, **0 cierres**, 1.0 y
   1.5 USDT de comisión, utilización 9.7 %/14.2 % — más capacidad compra exposición, no cierres.
   Reversión en caliente: 34 cierres y **−43.94 USDT** con 34.50 USDT de comisiones (0.248 % del
   notional por giro): convierte señales en cierres destruyendo economía. Rejilla de salidas en
   muestra: TP 0.45 % → 2 cierres/−2.25; TP 0.25 % → 2 cierres/+0.50; TP ≥ 0.50 % → 0 cierres.
4. **Escenario B (diversificación): NOT_EXECUTABLE.** No hay archivo de 1 m de otros símbolos para
   la ventana 2026-10-19; `data/quote-feed-1m` sólo tiene AAVE/UNI de 2021. Además el generador
   paritario repartiría el mismo patrón, no generaría opiniones nuevas.
5. **Decisión: `NO_CHANGE`.** Ningún cambio supera el criterio del RFC (mejora demostrada y
   validada fuera de muestra). Veredicto del experimento: `PARTIAL` (3 de 4 escenarios
   ejecutables); `INDEPENDENT_VERIFIER=BLOCKED`; `ECONOMIC_SAMPLE=INSUFFICIENT_SAMPLE`.

**Artefactos** — `reports/ai-bots/EXP-003I-THROUGHPUT-001/`: `RUNTIME_CAPACITY_MAP.md`,
`SIGNAL_BLOCKING_ANALYSIS.md`, `EXIT_DURATION_ANALYSIS.md`, `SCENARIO_COMPARISON.csv`,
`ECONOMIC_THROUGHPUT_REPORT.md`, `RUN_REPORT.md`, `RUN_REPORT.json`, `EVIDENCE_MANIFEST.json`.
Generador `scripts/exp_003i_throughput.py` (exige `--outdir`, exige `--overwrite` para republicar);
verificador separado `scripts/exp_003i_verify.py` (12/12: digests, entradas intactas, recuentos
re-derivados, sin CERTIFIED/PRODUCTION_READY). Los artefactos de 003I se leen en su sitio: V4
confirma que sus digests no cambiaron.

**Pendiente / bloqueado**

- La pregunta que sigue abierta no es de capacidad sino de fuente de decisión: mientras el
  proveedor sea `paper-script`, la tasa de cierres mide el script. Próxima acción: sesión con
  fuente no paritaria + rejilla de salidas preregistrada. Presupuesto de muestra con el generador
  actual: ~45 h continuas para 30 cierres incluso en el mejor caso de la rejilla.
- `INDEPENDENT_VERIFIER=BLOCKED` (mismo autor) y los dos informes raíz perdidos de 003I siguen
  declarados como no recuperables; este experimento no los reconstruye.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/exp_003i_throughput.py \
  --outdir reports/ai-bots/EXP-003I-THROUGHPUT-001 --overwrite
./.venv/Scripts/python.exe scripts/exp_003i_verify.py \
  --outdir reports/ai-bots/EXP-003I-THROUGHPUT-001
```

## 2026-10-19 · WP003I — reproducibilidad cerrada (D3/D4) y sesión prospectiva terminada

**Objetivo:** cerrar D3 (lock) y D4 (fixtures no versionadas), procesar la sesión prospectiva ya
terminada y dejar listo el paquete de verificación externa. Sin LIVE, sin tocar la estrategia.

**Rama:** `wp003i/reproducibility` en el worktree `bot-freebuff-wp003i-cert` · **HEAD:** `72702ecf` · **Base:** `5fd791d`.

**Hecho (medido)**

1. **D3 `CLOSED`.** `pyproject.toml` declaraba `matplotlib` y `uv.lock` no lo contenía (`uv lock --check` exit 1).
   Lock regenerado aditivo (0 líneas eliminadas, 0 versiones existentes cambiadas). En el worktree limpio:
   `uv lock --check` exit 0 y `uv sync --frozen` en entorno vacío exit 0, con import de `matplotlib 3.11.2`,
   `vision.lane` y `paper.broker`.
2. **D4 `PARTIALLY_CLOSED`.** Una prueba versionada (`test_edge16_pit.py`) exigía un cambio de `alpha15.py`
   sin commitear y 13 pruebas exigían `data/quote-feed-1m/**`. Versionados: quote-feed (con `-text`),
   `tests/fixtures/rfc003e/**`, `vision_panel.py`, registro PIT. Suite completa en dos worktrees limpios:
   base `5fd791d` = 114 failed + 16 errors; rama = 99 + 14; **0 fallos nuevos**, 17 reparados.
3. **Sesión prospectiva terminada** (`10:43:30Z→13:43:30Z`): 37 ciclos, 1 relleno, **0 cierres naturales**,
   0 órdenes, PnL realizado 0, equity marcado 9998.65205113. `H8-ECONOMICS = NOT_MEASURED`.
4. **Paquete externo** regenerado y verificado: `verify_package.py` exit 0 (8 escenarios 25/25, forjado
   rechazado, auditoría Decimal 16/16, 149 hashes 003G/003H OK) y nuevo `runtime_identity_check.py`
   (D5: 11/11 ficheros = blob en LF o CRLF).
5. **Veredicto `PARTIAL`**: H1–H8 PASS, `FALSE_SUCCESS = 0`, `BUILDER != VERIFIER` a nivel técnico.

**Pendiente / bloqueado**

- **113 rojos de otros WPs** en `tests/unit/research/**`: afirman contra `reports/**`, ignorado por
  `.gitignore:60/463` (229 árboles presentes pero no versionados). `BLOCKED` sobre una decisión de repositorio,
  no sobre trabajo de WP003I. Lista exacta en `REGRESSION.json` y `REPRODUCIBILITY_D3_D4.md`.
- **Independencia de autor `BLOCKED`**: el verificador es aritmética distinta del mismo autor; falta revisión
  de un tercero con identidad verificable.
- **Muestra económica insuficiente**: 1 relleno y 0 cierres en 3 h. No se acelera cambiando umbrales.

**Reanudación verificable**

```bash
cd "C:/Users/GVLLFR0035/Downloads/bot-freebuff-wp003i-cert"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe -m pytest tests/unit/reports/test_ai_bots_003i_verify.py -q   # 4 passed
cd "C:/Users/GVLLFR0035/Downloads/bot freebuff"
./.venv/Scripts/python.exe scripts/ai_bots_003i_report.py                              # verdict PARTIAL
./.venv/Scripts/python.exe reports/ai-bots/RFC-AI-BOTS-003I/EXTERNAL_VERIFIER_PACKAGE/verify_package.py
```

> Esta sección se escribe en el checkout principal sin commit: el fichero tiene otros escritores activos
> y el WP no lo reatribuye.

---

## 2026-10-18 · WP-OPS-BACKGROUND-001 — ejecución sin ventanas en Windows

**Objetivo:** que Trading Agentic Portable no abra ventanas de consola durante una ejecución
automática, sin perder stdout, stderr, exit codes, PID, timeouts ni limpieza de hijos.

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Commit:** el que contiene esta sección.

**Origen medido, no supuesto** (`scripts/ops_window_origin.py`, subsistema del PE por ancestro):

```text
explorer.exe (GUI) -> Freebuff.exe (GUI) -> bun.exe (CONSOLE) -> bash.exe -> python.exe
```

El primer proceso de consola de la cadena es `bun.exe`, hijo de una app GUI: **esa** es la
ventana de Bash/CMD. La segunda fuente, propia, era la tarea programada con `python.exe` bajo
`InteractiveToken`, que posee consola mientras dura la campaña.

**Hecho**

1. `src/trading_bot/ops/windowless.py`: una sola implementación de `CREATE_NO_WINDOW` +
   `STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)`; `run`/`spawn`, registro JSONL (spawn/exit con
   PID, comando, cwd, duración, timeout, exit code), `terminate_tree` scoped al handle de
   `Popen`, job object opcional `KILL_ON_JOB_CLOSE`. `TAP_WINDOWLESS=0` es la única salida.
2. `scripts/windowless.py`: lanzador para `pythonw.exe` con `--log`, `--event-log`, `--timeout`,
   `--keep-together`; propaga el exit code del hijo (124 timeout, 127 arranque, 130 cancelado).
3. `supervisor.py`, `cap004_supervisor.py`, `wp9_runtime_rehearsal.py`, `recovery_run_report.py`
   y `alpha002_capture.cmd` pasan por ese helper. La tarea programada registra ahora
   `pythonw.exe scripts/windowless.py … -- cap004_supervisor.py run`.
4. `scripts/ops_background_audit.py` inventaría los puntos de lanzamiento; `ops_window_origin.py`
   atribuye la ventana; `ops_windowless_probe.py` mide la adjunción de consola.

```text
RED   pytest tests/unit/ops/test_windowless.py
      ModuleNotFoundError: No module named 'trading_bot.ops'            exit 1
RED   ops_background_audit.py            HIGH 7 / MEDIUM 333            exit 1
GREEN pytest tests/unit/ops                                13 passed    exit 0
GREEN pytest tests/unit/autonomous                        284 passed    exit 0
GREEN pytest test_campaign_supervisor                      39 passed    exit 0
GREEN pytest st6_scheduler+edge12_runner+edge04r           90 passed    exit 0
GREEN pytest test_edge04_autonomous                        87 passed    exit 0
GREEN ops_background_audit.py            CLEAN 0 HIGH / 324 MEDIUM     exit 0
GREEN ruff / mypy (7 ficheros nuevos o tocados)          limpio            exit 0
GREEN pythonw windowless.py -- pytest tests/unit/ops     12 passed      exit 0
GREEN pythonw windowless.py -- ai_bots_003c_capture.py --bars 200        exit 0
GREEN pythonw windowless.py --timeout 2 --keep-together -- sleep(60)     exit 124, job_object=true
GREEN probe desde pythonw: plain 9 procesos adjuntos / guarded 2         PASS estructural
```

**Pendiente / bloqueado**

- `visual_verdict = NOT_OBSERVABLE`: la consola de este host la aloja Windows Terminal (ConPTY),
  sin `HWND`. Se declara el mecanismo y la diferencia de adjunción; no se afirma "no se vio".
- 303 `subprocess.run` acotadas y 20 `.cmd`/`.bat` históricos siguen sin el helper (MEDIUM);
  1 probe de `edge04r` usa `cmd.exe` como acción de una tarea que sólo lee su definición.
- **Ventana de Codebuff**: `orchestrator.js` pasa `windowsHide` en varias rutas pero no en el
  `Bun.spawn` del shell. No hay ajuste de usuario en la build 0.0.173; mitigación: iniciar
  Freebuff desde una consola existente. Detalle en `docs/runtime/WINDOWLESS_EXECUTION.md` §6.
- **TAP-061**: el Excel maestro no existe en este host (sólo `~$Tareas_Programadas.xlsx`, sin su
  libro). Fila lista en `reports/ops/WP-OPS-BACKGROUND-001/TAP-061_ROW.{md,json}`; no se creó un
  libro nuevo en su lugar.
- `wp9_runtime_rehearsal.py` conserva 10 errores de mypy **preexistentes en HEAD**; este WP no
  añade ninguno y no los silencia.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe -m pytest tests/unit/ops -q                      # 13 passed
./.venv/Scripts/python.exe scripts/ops_background_audit.py \
  --json reports/ops/WP-OPS-BACKGROUND-001/WINDOWLESS_AUDIT_GREEN.json      # CLEAN
./.venv/Scripts/python.exe scripts/ops_windowless_probe.py \
  --out reports/ops/WP-OPS-BACKGROUND-001/WINDOWLESS_LIVE_PROBE.json       # PASS estructural
```

---

## 2026-10-18 · RFC-TAP-AI-BOTS-003 bloque A — reloj de cierre y paridad de riesgo

**Objetivo:** que una decisión sobre el cierre de una vela no pueda existir antes de que esa vela
cierre, y que el motor de riesgo vea la misma equity neta que publica la curva.

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`, creada desde `b7e100a` (EVIDENCE-004F ya incluido).
**Commit:** `2557a9f`.

**Hecho**

1. `src/trading_bot/vision/clock.py`: `timeframe_ms` (lanza `UnknownTimeframe` en vez de adivinar)
   e `information_ms = open + timeframe + data_delay`.
2. `guards.assert_causal(bars, instant, bar_interval_ms=…)` exige que **cada vela haya cerrado**;
   el intervalo es argumento obligatorio. La prueba AIV-03 antigua comparaba aperturas y pasaba
   siempre: ahora falla en el caso que decía cubrir.
3. `lane.py`: decisión sellada en el cierre, `decision_bar_ts_ms` nombra la vela,
   `received_at_ms = cierre + latencia`, y `_marks` deja de contener el cierre de la vela antes de
   ejecutar en su apertura.
4. `lane.run`: al cerrar cada vela, `risk.mark_equity(mtm)`; la curva publica el mismo número en
   `equity` y `risk_equity`. Antes el riesgo sólo veía PnL realizado.
5. `lane.data_delay_ms` (+ `VISION_DATA_DELAY_MS`) declarado y registrado en el ledger: cero
   significa «no medido», no «instantáneo».

**Consecuencia declarada:** con el reloj correcto, cualquier latencia real descarta el fill
(la vela de ejecución abre justo cuando la respuesta vence). `NO_TRADE` es resultado legítimo.

**Verificación**

```text
pytest tests/unit/vision/test_causal_clock.py -q                      exit 0   7 passed
pytest tests/unit/vision tests/unit/intelligence tests/unit/reports -q exit 0  200 passed
ruff check src/trading_bot/vision tests/unit/vision                   exit 0
mypy src/trading_bot/vision/{clock,guards,lane,settings}.py           exit 0
scripts/evidence004_verify.py (misma rama)                            exit 0   42 PASS / 0 FAIL
RED comprobado: 5 fallos con `decision_ts_ms = bar.ts_ms`;
                paridad falla con equity 10001.37988951 vs riesgo 10000.0
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`. Sin clave ni autorización de gasto no hay llamada real.
- `data_delay_ms` no es una medición de red; es un parámetro declarado.
- Falta el bloque B (costes), y el run prospectivo VIS/CTX/CURRENT/NO_TRADE con el mismo
  calendario, capital y fricción.

**Reanudación**

```bash
cd "$(git rev-parse --show-toplevel)"
git checkout agent/ai-bots/RFC-TAP-AI-BOTS-003
git log -1 --format='%H %s'                                   # esperado: 2557a9f
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_causal_clock.py -q   # 7 passed
./.venv/Scripts/python.exe scripts/evidence004_verify.py      # 42 PASS / 0 FAIL
```

## 2026-10-18 · WP-TAP-EVIDENCE-004F — cierre de identidad, y traspaso a AI-BOTS-003

**Objetivo:** cerrar los cinco defectos residuales de EVIDENCE-004 (E4-01..E4-05) sin abrir otro
RFC ni rehacer el paquete, y publicar la reparación con verificación desde checkouts
independientes. Después, AI-BOTS-003 en una rama aparte.

**Base:** `243ba12` (rama `agent/evidence/RFC-TAP-EVIDENCE-004`).
**Commit de este bloque:** `978c485`.

**Hecho**

1. **E4-01 — un origen, una identidad.** `SourceSpan` guarda `content_sha256` en el dominio
   `TEXT_CANONICAL_LF`; clasificador, generador y verificador aplican la misma regla (antes
   `_read_source` hasheaba bytes del checkout y el verificador normalizaba a LF).
2. **E4-01b — la comprobación de spans tenía cero sujetos.** El generador publicaba eventos sin
   `sources`, así que `stored_spans_point_at_the_bytes_they_hashed` pasaba sin evaluar nada.
   Ahora los spans se publican y, sin spans, el check falla.
3. **E4-02 — texto no es bytes.** `SUPERSESSION_MANIFEST.json` v2 declara dominio y autoridad por
   documento (`preservation.content_sha256`); v1 se conserva intacto en
   `evidence-004/superseded-manifests/SUPERSESSION_MANIFEST.v1.json`.
4. **E4-03 — cifras renderizadas.** Los claims NARRATIVE se generan desde contadores; el texto
   libre con un número se rechaza. La frase publicada es «9 registradas, 7 ejecutadas, 2 no
   ejecutadas», y `CLAIMS.json` v1 queda archivado.
5. **E4-04 — verificador portable.** Detalles repo-relativos; dos raíces (LF y CRLF) producen
   `VERIFICATION.json` idéntico **byte a byte**.
6. **E4-05 — publicación transaccional.** Proyección candidata completa → relectura y re-hash →
   conmutación de `CURRENT_MANIFEST.json` → poda solo de huérfanas. La proyección anterior sobrevive
   y queda registrada en `SUPERSEDED_PROJECTIONS.json`.
7. **`.gitignore`**: `reports/*` ignoraba el árbol entero, así que cada proyección nueva nacía
   invisible para git y un checkout limpio no podría verificarla. Se re-incluye el paquete paso a
   paso, como los paquetes de evidencia anteriores.

**Verificación real (no reutilizada de informes previos)**

```text
scripts/evidence004_verify.py                     exit 0   42 PASS / 0 FAIL
scripts/evidence004_verify.py --mutations         exit 0   18/18 rechazadas
scripts/ai_bots_rea_verify.py                     exit 0   73 PASS / 0 FAIL
pytest reports+vision+intelligence                exit 0   193 passed (17 nuevos)
ruff / mypy (scripts + tests/unit/reports)        exit 0
git archive HEAD -> raíz LF                       exit 0   42 PASS / 0 FAIL
git archive HEAD -> raíz convertida a CRLF        exit 0   42 PASS / 0 FAIL
VERIFICATION.json LF vs CRLF vs commit            idénticos (cmp, sin diferencias)
--mutations sobre la extracción del archivo       exit 0   18/18 rechazadas
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`: sin credencial ni autorización de gasto. Cinco de las siete
  evidencias siguen siendo declaradas, no verificadas byte a byte.
- **AI-BOTS-003 no empezado en este checkpoint**; el siguiente bloque lo actualiza con su rama,
  su commit y sus resultados.
- Suite completa del repositorio no ejecutada: hay ficheros ajenos modificados en el árbol (otros
  agentes). Declarar un PASS global con eso en vuelo sería el defecto que este WP elimina.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'                                    # esperado: 978c485 o su sucesor
./.venv/Scripts/python.exe scripts/evidence004_verify.py       # esperado: 42 PASS / 0 FAIL, exit 0
./.venv/Scripts/python.exe -m pytest tests/unit/reports -q     # esperado: 41 passed, exit 0
git archive HEAD | tar -x -C "$TEMP/ev004-lf"                  # extracción limpia
./.venv/Scripts/python.exe scripts/evidence004_verify.py --root "$TEMP/ev004-lf"   # 42 PASS
```

# Execution checkpoint — reanudación entre sesiones

> Documento vivo. **Antes de empezar cualquier sesión**: leer este fichero y validarlo contra Git
> (`git log -1`, `git status --porcelain`, rama actual). Si hay discrepancia, manda Git y este
> fichero se corrige con el estado real. **Después de cada paquete de trabajo relevante**: actualizar
> las secciones marcadas.
>
> Política completa en `AGENTS.md` §7. Reglas de campaña: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`,
> nada de trading real, credenciales, apalancamiento ni cambios de límites de riesgo.

*Última actualización: 2026-10-17T17:30Z, sesión WP-EDGE-017F (cierre real de los defectos que
sobrevivieron a la publicación de 017, y suite definitiva sobre el commit publicado).*

**Estado publicado al cerrar esta sesión**: `HEAD` = `origin/agent/edge-recovery/WP-EDGE-00-baseline`
= el commit que contiene este párrafo (`git rev-parse HEAD`), 8 commits sobre `5c81aad`, fast-forward
verificado con `git merge-base --is-ancestor`. La suite se midió en su padre
`64da0cd8c0c2a2b72369638300e26647fb9c168c`; el delta es solo documentación, sin código ni tests, así
que `TEST_TARGET == RUNTIME_TARGET` se mantiene. Comprobarlo con `git rev-parse`, no leyéndolo aquí.

## RFC-AI-BOTS-002 — sesión 2026-10-17T22:30Z (rama `agent/ai-vision/RFC-AI-VISION-001`)

**Objetivo**: ejecutar el RFC de AI Bots sobre AI-VISION-001 sin tocar WEB-017F ni
`config/risk.yaml`. Confirmar Git antes de escribir: rama propia, `HEAD` = `091d55d` al
empezar, y varias modificaciones ajenas sin commitear en `reports/`, `data/` y
`config/vision.yaml` que **no** se han tocado ni staged.

| bloque | estado | evidencia |
| --- | --- | --- |
| P0 defectos visuales (volumen doble, margen, cuerpos) | **cerrado** | RED medido (80 rects vs 40; 34 px en borde; 5,93 px/vela) → GREEN en `tests/unit/vision/test_visual_defects.py` |
| Guards PIT/esquema y hueco de datos | **cerrado** | `guards.py` + `test_guards_and_controls.py`; el lane rechaza ejecutar en una barra no contigua |
| Registro de bots | **cerrado** | `ai_bots/registry.py`, capacidades cerradas, desactivados por defecto (`AI_BOTS_ENABLED` + `AI_BOTS_ALLOW`) |
| BOT-VIS-01 / BOT-CTX-01 | `MOCK_TEST` ejecutado | 40 llamadas cada uno, 14 cierres, mismo libro; VIS adjunta 40 PNG, CTX 0 |
| Verificación independiente | **PASS 34/0** | `scripts/ai_bots_verify.py` sobre artefactos en disco |
| Llamada multimodal real | **BLOCKED** | `--mode live` → exit 2 `MISSING_CREDENTIAL`; sin `VISION_API_KEY` no hay petición |
| Comparación económica | `NOT_EVIDENCE` | el modelo fue un guion; no se declara edge |

Suite medida en el árbol de trabajo antes de publicar: **366 passed**
(`tests/unit/{vision,intelligence,paper,risk}`), ruff y mypy limpios.
Artefactos: `reports/ai-bots/RFC-AI-BOTS-002/` (RUN_REPORT, FINAL_REPORT,
INDEPENDENT_VERIFICATION, REA_FINDINGS, manifests, ledgers) y
`docs/ai-bots/RFC-AI-BOTS-002/` (autoridad, fuentes, matriz de patrones).

**Publicado** (fast-forward sobre 091d55d): 520a6df (P0 visual y guards), 317d161
(registro y runner de bots), 76d3992 (evidencia y verificación). Comprobar con
git log --oneline -3, no leyéndolo aquí.

**Pendiente real**: credencial del proveedor para `REAL_MODEL_CALLED`; sin ella el veredicto
económico no puede existir. **No** se ha tocado riesgo, no hay ruta de orden real, y REA
quedó en `doctor/help` ejecutados con análisis de terceros `NOT_EXECUTED`.

## 0. WP-EDGE-017F — qué se cerró y con qué evidencia

**Punto de partida validado**: `HEAD` = `origin/agent/edge-recovery/WP-EDGE-00-baseline` =
`5c81aad94e1bf67b72c56d479a5ac06034397d73`. La rama ya estaba publicada; el bloqueo anterior
(6 commits locales sin subir) quedó resuelto en la sesión previa.

| bloque | estado | evidencia ejecutada |
| --- | --- | --- |
| **P0.1 ventana semanal** | **cerrado** | 11 de 14 tests fallaban antes; después **14 passed**. 12 `WEEK_BOUNDARY` por corrida, `weekly_pnl` a 0 en todos, 10 con pérdida previa ≠ 0 |
| **P0.2 replay regenerado** | **cerrado** | ejecuciones reales 1×/2×/3×: **146 / 146 / 121** fills; neto **−238.770489 / −425.692312 / −500.571772** USDT |
| **P0.3 drawdown** | **cerrado** | `EQUITY_CURVE.jsonl` (2 000 puntos MTM por corrida); **2.387705 / 4.256923 / 5.005718 %**; 12 tests; C-checks del verificador + M13/M14 |
| **P1 evidencia prospectiva** | **cerrado (manual)** | slice 9 → **24** filas, 0 conflictos, 0 ausentes; **6 al cierre**, **18 recuperadas**; 9 evaluadas, 0 propuestas, 0 fills |
| **P0.4 suite global** | **parcial / FAIL declarado** | ver §4: resultado literal en `RFC-EDGE-017/FULL_UNIT_SUITE.log`; V57/V58 clasificados |
| **Verificación independiente** | **cerrado** | `edge17_verify.py`: **31/31 checks, 14/14 fallos detectados**; `edge15_verify.py`: **35/35** tras commitear la captura |

**Cifras anteriores retiradas**: 146/110/67 fills y `drawdown_pct = 10 000.0`. Las dos eran
artefactos: la segunda era `peak_equity` (un saldo, no un porcentaje) y las primeras salieron de un
motor cuyo veto semanal no se levantaba nunca, de modo que 2× y 3× dejaban de operar tras una mala
semana.

### Lo que cambió en el código

- `src/trading_bot/risk/manager.py`: `week_start_ms_for()` (semana UTC lunes 00:00),
  `RiskManager.weekly_start_ms`, `roll_week()`, llamada en `check_signal`, `record_trade_result` y
  `reset_daily`; `extract_state`/`restore_state` transportan el ancla.
- `src/trading_bot/paper/reconciliation_v4.py`: el ancla viaja en el snapshot durable.
- `scripts/edge16_paper_lane.py`: curva de equity MTM por barra, `WEEK_BOUNDARY /
  RISK_RESET_WEEKLY` con `weekly_pnl_before_reset`, bloque `weekly_risk`.
- `src/trading_bot/research/equity_drawdown.py` (nuevo): drawdown pico-valle con estado `UNKNOWN`.
- `scripts/edge17_reports.py`: drawdown desde la curva y texto derivado de los datos.
- `scripts/edge17_capture.py`: `capture_class` por barra (al cierre / recuperada / ausente).
- `scripts/edge17_verify.py`: 3 checks de drawdown (uno por multiplicador) + M13/M14.
- Documentación: `docs/risk-policy.md` (ventana explícita) y `tasks/decisions.md` **ADR-017F-01**.

**Nada de esto cambió** `max_weekly_loss_pct` (3.0), ningún otro límite, la reserva de disco (2 GB),
el multiplicador 1.5×, la válvula de 64 MiB ni la política de fin de semana (`false`).

## 1. Estado Git

- Rama: `agent/edge-recovery/WP-EDGE-00-baseline`.
- Commits de esta ronda (se publican en el push final, fast-forward):
  - `9dbbbae` — ventana semanal UTC + persistencia + ADR-017F-01.
  - `05b977e` — drawdown desde curva de equity + verificación independiente.
  - `ff339bb` — proveniencia por barra y reportes derivados de datos.
  - `126cf95` — captura nueva (slice 9 → 24, ledger, manifiesto).
  - `7ef6458` — EDGE-015 re-verificado 35/35 tras commitear la captura.
  - `34622f3` — replay 1×/2×/3× regenerado + curvas + verificación 31/31.
  - `64da0cd` — cierre: suite real, propietario por test, `RUN_REPORT.md`, `FINAL_REPORT.md`.
  - *(cierre documental)* — suite definitiva sobre `64da0cd`, índice de evidencias reconstruido y
    este checkpoint apuntando al commit publicado.
- **Publicado**: `git push origin HEAD:agent/edge-recovery/WP-EDGE-00-baseline` →
  `5c81aad..64da0cd` (fast-forward, sin force). El remoto se comprueba con `git rev-parse`.
- La cabecera publicada se comprueba con `git rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline`,
  no leyéndola aquí.
- **No tocar** lo ajeno: `data/st6/**`, `.ci/**`, `data/recovery/wp8/**`,
  `evidence/real_decisions/**`, `reports/economic-recovery/RFC-EDGE-014*/**`,
  `reports/economic-recovery/RFC-EDGE-016/**`, `scripts/cap004c_verify.py`,
  `scripts/st6_scheduler_witness.py`, `src/trading_bot/research/economic_recovery/alpha15.py`,
  `docs/source_registry.md` y los ~165 ficheros sucios de otras líneas.

## 2. Resultados (reproducibles con §5)

| cantidad | valor |
| --- | --- |
| fills 1× / 2× / 3× | 146 / 146 / 121 |
| neto 1× / 2× / 3× | −238.770489 / −425.692312 / −500.571772 USDT |
| drawdown 1× / 2× / 3× | 2.387705 / 4.256923 / 5.005718 % |
| rechazos 1× / 2× | 3 × cooldown de pérdidas consecutivas |
| rechazos 3× | 43 × max drawdown, 1 × cooldown |
| reinicios semanales por corrida | 12 |
| veto semanal efectivo en el dataset | **0** (peor semana −120.13 USDT = 1.2 % < 3 %) |
| equivalencia frictionless vs EDGE-016 | 146/146 idénticos |
| captura: esperadas / observadas / ausentes | 24 / 24 / **0** |
| captura: al cierre / recuperadas | **6 / 18** |
| tasa del colector | 9 787 B/h (fallback 240 MB/h; sobrestimación 24 522×) |
| guardián de disco | `COHERENT`, reserva y válvula intactas |

**Evolución semanal del riesgo (1×, `weekly_pnl` antes de cada reset)**: −22.05, −14.50, −8.12,
−39.89, −4.35, −25.10, +3.76, −14.64, −33.42, −78.76 USDT (13 semanas; las dos primeras sin
pérdida cerrada). 2×/3× en `NET_RISK_REPLAY.runs.*.weekly_risk`.

## 3. Ficheros de evidencia

- `reports/economic-recovery/RFC-EDGE-017/FINAL_REPORT.md` — informe final 017F.
- `reports/economic-recovery/RFC-EDGE-017/RUN_REPORT.md` — comandos y PASS/FAIL/BLOCKED.
- `reports/economic-recovery/RFC-EDGE-017/NET_RISK_REPLAY.json` — fills, neto, drawdown, semanas.
- `reports/economic-recovery/RFC-EDGE-017/scratch/net_{1,2,3}x/EQUITY_CURVE.jsonl` — curva verificable.
- `reports/economic-recovery/RFC-EDGE-017/CAPTURE_INTEGRITY.json` — cobertura y proveniencia.
- `reports/economic-recovery/RFC-EDGE-017/INDEPENDENT_VERIFICATION.{json,md}` — 31/31, 14/14.
- `reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log` — resultado literal de la suite.

## 4. Pendiente y bloqueado (no ocultar)

1. **Suite global ejecutada dos veces**: **4070 passed, 14 failed** en 21:53 sobre `34622f3` y
   **4070 passed, 14 failed en 19:44** (exit 1, 1184.06 s) sobre el commit publicado `64da0cd`,
   con los **mismos 14 tests** en ambas corridas. Los 14 son
   **BLOCKED** ajenos al paquete: **9 cost-barrier** (el gate fija el audit `023b66ff…` mientras
   el audit comprometido en `HEAD` ya es `c6ea3438…`: inconsistencia previa a 017F), **3 WP-8**
   (`evidence/real_decisions/*.jsonl` sucios de otra línea; vista comprometida obsoleta) y
   **2 ST6** (su dato acumulado contradice su aserción de cobertura). Detalle y evidencia por
   test en `RUN_REPORT.md` §6. Ninguno se convirtió en PASS.
2. **EDGE-016 V57** — **BLOCKED**: `RFC-EDGE-016/INDEPENDENT_VERIFICATION.json` ya estaba modificado
   por otra línea al abrir la sesión y su hash no coincide con el índice.
3. **EDGE-016 V58** — **BLOCKED (causado por el paquete, evidencia congelada)**: EDGE-017 movió
   `def check_positions_ohlc` de la línea 398 a la **490** y el sha de `broker.py` de `0250fc47…` a
   `4366809a…`; el mapa de EDGE-016 sigue citando el par antiguo. Reescribirlo haría que un artefacto
   que declara describir `2536928` describiera otro código: la regeneración corresponde a EDGE-016.
4. **Sin planificador**: crear la tarea exige privilegios de administrador, no autorizados.
5. **Sin estrategia admitida** (`config/strategy_admission.json` intacto): el carril de paper del
   runtime no tiene nada que ejecutar; el carril experimental salta la admisión por diseño.
6. **Spread y latencia** siguen `NOT_MEASURED` en un replay de barras; se aplican en el entrypoint.
7. **Volumen al ~99 %** (≈4.2 GB libres). El colector consume ~9.8 KB/h, así que el disco ya no es la
   causa, pero el host no está sano.
8. **Scheduler/ST6**: la tarea programada de otra línea sigue alargando la suite por contención.

## 5. Comandos de reanudación

```bash
# 0. Estado real
git -C "$(git rev-parse --show-toplevel)" log --oneline -3
git -C "$(git rev-parse --show-toplevel)" status --porcelain | head -40
git -C "$(git rev-parse --show-toplevel)" rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline

# 1. Tests del paquete
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit/risk/test_edge17_weekly_window.py tests/unit/research/test_edge17_drawdown.py tests/unit/research/test_edge17_capture.py -q

# 2. Capturar (append-only, escritor único) y verificar
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_capture.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_reports.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_verify.py    # 31/31, 14/14
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_verify.py     # 35/35 (captura commiteada)

# 3. Replay (si hace falta regenerarlo)
cd "$(git rev-parse --show-toplevel)" && for m in 1 2 3; do ./.venv/Scripts/python scripts/edge16_paper_lane.py --cost-mode net --cost-multiplier $m --out reports/economic-recovery/RFC-EDGE-017/scratch/net_${m}x; done

# 4. Suite completa (~20 min con ST6 activa) — dejar el log dentro del paquete
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit -q --tb=short -rf -p no:cacheprovider > reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log 2>&1; echo "EXIT=$?"
```

## 6. Protocolo de actualización

- Al **cerrar un hito**: marcar la fila en §0/§2 y actualizar §4.
- Al **cortarse la sesión**: anotar el comando exacto en curso y su log.
- **Nunca** mover un elemento de §4 a §0/§2 sin evidencia ejecutada (log, artefacto, exit code).
- `reports/economic-recovery/*` está en `.gitignore`: la evidencia nueva se añade con `git add -f`,
  sólo la propia del bloque.

## RFC-TAP-AI-BOTS-002 v3 (REA-FIRST) — sesión 2026-10-18T00:20Z (rama `agent/ai-vision/RFC-AI-VISION-001`)

**Objetivo**: cerrar los P0 propios que podían producir una operación falsa y obtener
evidencia REA **real** de al menos un target externo. `HEAD` al empezar: `6f637a7`
(comprobarlo con `git log --oneline -1`, no leyéndolo aquí). No se tocó `config/risk.yaml`
ni EDGE-017F.

| bloque | estado | evidencia |
| --- | --- | --- |
| REA sobre target real | **ejecutado** | 4 operaciones, exit 0: `analyze-javascript-application` (bundle público de nof1.ai, `ev_aee35b0f…`), `list-browser-targets` (`ev_f7020db1…`), `capture-web-screenshot` (`ev_47c01acc…`), `analyze-web-bundle` (`ev_82d99570…`) |
| P0 hash de imagen | **cerrado** | `INTEGRITY_FAILURE` ⇒ `return None`: 0 decisiones, 0 fills. Test nuevo sobre `VisionLane` |
| P0 latencia | **cerrado** | `LATE_RESPONSE` al ejecutar: una respuesta posterior a la apertura de la barra no rellena. Test nuevo (control con latencia 0 sí opera) |
| P0 comparador | **cerrado** | `NOT_COMPARABLE` como veredicto si cambian cadencia/insumos; la aritmética se reporta aparte |
| Defensas + `roll_week` | **verificado existente** | `paper_cycle._defensive_verdict` falla cerrado; `RiskManager.check_signal` llama `roll_week()`; `tests/unit/risk/test_edge17_defensive_blocks.py` |
| Targets restantes | **BLOCKED medido** | disco 2,9 GB libres (99 % usado); Streamlit/Python sin superficie JS propia; FortuneMal sin licencia (API 404) |
| Llamada multimodal real | **BLOCKED** | sin credencial ni autorización de gasto: cero llamadas, `REAL_MODEL_CALLED=false` |
| Adopción externa | **not certified** | sólo nof1 tiene evidencia y no alcanza la cadena gráfico→modelo→decisión: `DEFER` |

**Medición de tests**: contra `HEAD` antes del arreglo **6 failed / 9 passed**; después
**15 passed**; suites focalizadas (`vision`, `intelligence`, `paper`, `risk`) **372 passed**;
`ruff` y `mypy` limpios. Verificador independiente propio:
`scripts/ai_bots_rea_verify.py` → **21 PASS / 0 FAIL** (rechazó dos incoherencias del informe
antes de publicarse: la cadena de licencia de FortuneMal y una afirmación de estado ausente).

**Comandos de reanudación**:

```
.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py          # 21 PASS / 0 FAIL esperado
.venv/Scripts/python.exe -m pytest tests/unit/vision -q         # tests del lane y del comparador
npx -y rea-agents@6.4.0 analyze-javascript-application <ruta> --format json --fetch-source-maps
```

**Pendiente real y siguiente paso con valor**: ampliar el análisis de nof1 con
`--fetch-source-maps` (nombres legibles) o conseguir un artefacto local autorizado de un
target Python y observar su ciclo con REA CDP; ambos necesitan espacio en disco.

---

## Cierre de la pasada de completitud (2026-10-18)

Objetivo: contrastar el entregable real contra el pliego §5/§9 y cerrar lo que faltaba.
Verificador ampliado de **21 → 31 PASS / 0 FAIL** (`scripts/ai_bots_rea_verify.py`), y las
comprobaciones nuevas se probaron **no vacuas**: al retirar `SOURCE_RUNTIME_CORRELATION.md`
del dossier de nof1 el verificador sale con exit 1 y nombra el fichero ausente.

Añadido en este cierre: `INFORME_EJECUTIVO.md`, `SOURCE_RUNTIME_CORRELATION.md` y
`RECONSTRUCTION_OBLIGATIONS.json` en los seis dossiers, `PATTERN_ADOPTION_MATRIX.md`
reescrito con la regla `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`, y punteros en
`FINAL_REPORT.md`/`RUN_REPORT.md` hacia el conjunto REA-FIRST.

**Aviso operativo para la próxima sesión**: `.gitignore:60` es `reports/*`. Los artefactos
de `reports/` hay que añadirlos con `git add -f`; si no, existen en disco y **no se publican**.

Estado sin cambios: `REAL_MODEL_CALLED=false`, ningún patrón externo certificado, disco
2,9 GB libres.

## 2026-10-18 · RFC-TAP-AI-BOTS-002 v3.1 (REA Target Authority)

**Objetivo:** corregir la atribución no demostrada entre los bundles de `www.nof1.ai` y
`195440/nof1.ai`, y ejecutar REA de verdad sobre artefactos del commit exacto de tres
proyectos.

**Base:** `a0ca055` (rama `agent/ai-vision/RFC-AI-VISION-001`).

**Hecho**

1. **P0 de procedencia, refutado con artefacto.** El commit `5d27641dfa47cc942aa0709ffb3f5237de876373`
   (árbol `b3ae235a…`) se clonó en sandbox (2,3 MB) y **no contiene Next.js**: build `tsdown`,
   cero literales `__NEXT`/`turbopack`, y su dashboard son `public/app.js` +
   `public/monitor-script.js` en `open-nof1.195440.com`. El bundle público es Turbopack
   (`__NEXT` 9/12, `turbopack` 7/12). La asociación no era sólo indemostrada: es imposible.
2. **Evidencia de la v3 preservada** en `rea/targets/T-NF-PUBLIC/` (4 `evidence_id`, hashes
   intactos), reetiquetada `UNATTRIBUTED_NO_DEPLOYMENT_RECEIPT`.
3. **REA sobre el repo exacto**: `analyze_javascript_application` sobre `public/` →
   `ev_4b2bf9c5…`, 3 ficheros, 4.812 nodos AST, exit 0.
4. **REA sobre Semantic Signal** (`65e67dc2…`, MIT): estático `ev_9b45318c…`, bundle
   `ev_b954b8b0…`, captura `ev_ee6845ff…`.
5. **REA sobre FenixAI** (`bd7373d5…`, Apache-2.0): `npm ci` + `vite build` desde el commit
   (exit 0) → `ev_be8c7d74…`, bundle `ev_fc2b6552…`, captura `ev_b3b1e837…`.
6. **Auditoría de fuente** de los tres backends: nof1 no es visual y deja el apalancamiento al
   modelo con el drawdown comentado; FenixAI manda la imagen sin hash ni símbolo; QRAK liga la
   imagen por construcción y el risk manager recorta el tamaño.
7. **Verificador ampliado** (31 → 59 → 70 → **73** comprobaciones), con mutaciones que lo rechazan:
   reatribuir el bundle público ⇒ 2 FAIL; borrar `PROVENANCE.md` del repo exacto ⇒ 2 FAIL;
   disfrazar el probe de `REA_EVIDENCE` ⇒ 2 FAIL.
8. **Ejecución instrumentada del renderizador de FenixAI** (`4dba317`): `ChartService` del
   commit `bd7373d5…` con 120 velas sintéticas en venv desechable, sin red ni claves → PNG
   181.314 B `96c7f41c…`, determinista, caché por símbolo. Hallazgos: sin `mplfinance` devuelve
   `PLACEHOLDER` con `ok=True`, y `get_cached(max_age=0)` trata el 0 como "no especificado".
   Etiquetado `INSTRUMENTED_EXECUTION_NOT_REA`; nunca se cuenta como llamada de modelo.
9. **`exit 0` dejó de contar como éxito.** `compare-source-to-bundle` devolvió `exit_code: 0`
   con resultado `NOT_EXECUTED_INVALID_INPUT`, y `RUN_REPORT.md` lo sumaba como operación
   correcta ("9 operaciones REA con exit 0"). Corregido a 7 con `evidence_id` + 2 declaradas no
   ejecutadas, y el verificador ahora comprueba la tabla fila por fila
   (`run_table_annotates_exit_zero_without_evidence`, `run_table_counts_evidenced_work_only`)
   además del log consolidado (`rea/REA_COMMAND_LOG.jsonl`, 16 entradas = suma de los 4 dossiers).
   La misma sobreafirmación estaba en otros tres sitios y los tres quedaron ligados al mismo
   número: `RUN_REPORT.json` (`rea_operations_exit_0: 9` → `rea_operations_evidenced: 7` +
   `rea_operations_not_executed: 2`), `source_registry.md` ("Las 9 operaciones REA…") y
   `REA_FINDINGS_V2.json` ("all exit 0"). Mutar cualquiera de los tres ⇒ 3 FAIL.

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`: sin credencial ni autorización de gasto.
- `import-reference-source` → **exit 1 `unsupported_host`** en Windows: `compare-source-to-bundle`
  queda bloqueado por falta de productor de `HistoricalSourceGraph`. Registrado, no simulado.
- Backends Python/TypeScript de los tres targets sin ejecutar (requieren claves/servicios).
- `T-TA-CRITIC` y `T-FM-DEMO` sin REA: sin superficie JS / sin licencia.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py | tail -2   # esperado: 73 PASS / 0 FAIL, exit 0
./.venv/Scripts/python.exe -m pytest tests/unit/vision tests/unit/intelligence -q | tail -2
./.venv/Scripts/ruff.exe check scripts/ai_bots_rea_verify.py
```

**Commits de este paquete:** `6403c71` (procedencia + REA de los tres commits), `4dba317`
(renderizador de FenixAI ejecutado) y el commit que contiene estas líneas (log consolidado y
`exit 0 != éxito` en el verificador). Comprobar con `git log --oneline -3`, no leyéndolo aquí.

**Aviso que sigue vigente:** `.gitignore:60` es `reports/*`; los artefactos nuevos de
`reports/` necesitan `git add -f` o no se publican.

**Añadido al cerrar: ejecución instrumentada (no REA) del render de FenixAI.**
`rea/targets/T-FE-FENIX/instrumentation/` guarda el probe, su salida y un README: el
`ChartService` del commit exacto corrió offline con velas sintéticas (exit 0, backend
`MPLFINANCE`, PNG 181.314 B, determinista, caché sin cruzar símbolos) y la misma corrida midió
dos defectos reales: relleno silencioso con `ok=True` cuando falta un backend, y
`get_cached(max_age=0)` que aplica el TTL por defecto porque el cero es falsy.

Verificador: **65 PASS / 0 FAIL** (antes 59). Mutación nueva comprobada: disfrazar el probe de
`REA_EVIDENCE` ⇒ 2 FAIL. La consistencia hash-probe↔dossier la vigila el propio verificador:
detectó que la baseline sólo citaba 8 caracteres del sha y se corrigió el documento, no la
comprobación.

## RFC-TAP-EVIDENCE-004 — sesión 2026-10-18 (rama `agent/evidence/RFC-TAP-EVIDENCE-004`)

> Sección añadida al final, sin reescribir las anteriores: otro agente puede tener este fichero
> abierto. Si algo aquí discrepa de Git, manda Git.

**Objetivo**: que ninguna cifra del RFC AI-BOTS-002 vuelva a contradecirse entre informes, y que
ningún `exit_code == 0` se lea como trabajo completado.

**Base**: `c4e6e3b5ec3f40090a0aa66fee2733c0b00c9546` (rama `agent/ai-vision/RFC-AI-VISION-001`).

**Hecho**

1. **Clasificador** `scripts/evidence004_ledger.py`: 16 eventos de los 5 logs crudos, merge de
   copias duplicadas con rechazo si discrepan, `execution_class` independiente de `exit_code`,
   `evidence_id` sólo válido como id de REA si cumple `ev_<64 hex>`, artefacto verificado por sha256.
2. **Generador** `scripts/evidence004_generate.py`: `CANONICAL_RUN.json` → `RUN_REPORT.json/.md`,
   `INFORME_EJECUTIVO_NUMEROS.md` y bloques numéricos en `FINAL_REPORT.md`/`INFORME_EJECUTIVO.md`.
   Claims atados a contador o `evidence_id`; escritura atómica; lock de escritor único.
3. **Verificador independiente** `scripts/evidence004_verify.py`: relee los logs por su cuenta (no
   importa clasificador ni generador), descubre todos los informes, y rechaza **14/14** mutaciones.
4. **Sello histórico**: `evidence-004/SUPERSESSION_MANIFEST.json` conserva 6 documentos con hash de
   bytes. El informe que contaba 9 operaciones por código de salida sigue en el árbol, intacto y
   marcado; no se ha reescrito para que cuadre.
5. **Dos denominadores**: 7 evidenciadas + 2 no ejecutadas (trabajo de esta iteración) y 12 ids
   distintos (los cuatro dossiers). Ningún documento los suma.

**Medido**

```text
scripts/evidence004_generate.py                 exit 0
scripts/evidence004_verify.py                   exit 0   36 PASS / 0 FAIL
scripts/evidence004_verify.py --mutations       exit 0   14/14 rechazadas
scripts/ai_bots_rea_verify.py                   exit 0   73 PASS / 0 FAIL  (sin degradar)
pytest tests/unit/reports tests/unit/vision tests/unit/intelligence
                                                exit 0   176 passed
ruff / mypy sobre los tres scripts              exit 0
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`; ninguna operación REA reejecutada: este paquete cuenta logs.
- 5 de las 7 evidencias son declaradas, sin artefacto en disco: no se certifica ningún patrón.
- Suite completa del repositorio no ejecutada (hay 169 ficheros ajenos en vuelo). Declarado, no PASS.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe scripts/evidence004_generate.py --json | head -4
./.venv/Scripts/python.exe scripts/evidence004_verify.py            # esperado: 36 PASS / 0 FAIL
./.venv/Scripts/python.exe scripts/evidence004_verify.py --mutations
./.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py | tail -2  # esperado: 73 PASS / 0 FAIL
```

**Siguiente WP**: `AI-BOTS-003` (issue #12): causalidad de `bar.ts_ms`, latencia de respuesta y MTM
neto. EVIDENCE-004 no lo bloquea; garantiza que sus cifras no puedan contradecirse.

---

## WP-TAP-AI-BOTS-003B — motor de ejecución paper causal (2026-10-18)

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Baseline:** `2921f6d` · **Motor:** `96957a2` · **Evidencia:** `e6707f9` (publicado; fast-forward sobre `2921f6d`)

**Objetivo.** Cerrar la consecuencia que el bloque A dejó escrita: con el reloj correcto,
cualquier latencia real descartaba el fill, porque el carril pedía la apertura de una vela
que ya había abierto antes de la respuesta. Un proveedor real producía `NO_TRADE` eterno.

**Hecho (verificado).**

- `src/trading_bot/vision/execution.py`: `Quote`/`quote_at`/`schedule`. Sólo una apertura de
  vela es cotización; cualquier instante dentro de una vela lanza `InsufficientResolution`
  en vez de interpolar. Ventana de la opinión declarada (`max_opinion_age_ms`, una vela por
  defecto) y registrada en la fila `RUN`.
- `lane.py`: entradas primero (la cotización es la primera apertura `>= received_at_ms`),
  después el rango de la vela para los stops, después marcas y decisiones. Cada `FILL` y
  cada `CLOSE` declaran su procedencia y su ventana.
- `paper/broker.py`: `check_positions_ohlc(..., gap_policy="open_on_gap")`; el valor por
  defecto no cambia para el resto de llamantes.
- `summary.reconciliation` con cinco identidades y `summary.execution` con la espera medida.
- `scripts/ai_bots_003b_verify.py`: verificador **independiente** (sin importar `trading_bot`)
  con 21 comprobaciones y 10 mutaciones.

```text
pytest tests/unit/vision/test_causal_execution.py   9 failed / 1 passed  ->  10 passed
pytest vision+paper+reports+intelligence            293 passed            exit 0
ruff / mypy                                         limpio                exit 0
ai_bots_003b_verify.py  VIS / CTX                   21 PASS / 0 FAIL c/u  exit 0
ai_bots_003b_verify.py --mutations  VIS / CTX       10 / 10 detectadas    exit 0
ai_bots_rea_verify.py                               73 PASS / 0 FAIL      exit 0
ai_bots_run.py --mode live (sin clave)              BLOCKED               exit 2
git archive HEAD -> raíces LF y CRLF                economía idéntica; verificación byte-idéntica
```

**Paper con 900 ms declarados:** 14 rellenos por bot (antes: 0), espera 1 h − 900 ms,
8 stops / 6 objetivos, bruto +6.70, costes −22.38, neto −15.68. `MOCK_TEST`.

**Sustituido, dicho en voz alta:** `test_a_latency_below_the_timeframe_...` afirmaba
`fills == 0` con 60 s y el test del hueco afirmaba `STALE_EXECUTION`; ambas eran la
consecuencia de B-01, no propiedades. Ahora comprueban lo que importa: ningún relleno paga
un precio anterior a la respuesta.

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`; el bloqueo de la llamada real multimodal sigue en `BLOCKED_MODEL_API`.
- Los dos bots dan el mismo resultado porque el guion mock ignora el prompt: fontanería, no paridad.
- El ledger no es byte-idéntico entre runs: cada línea sella `recorded_at_utc`. Se compara
  por contenido económico y por cadena recalculada.
- Suite completa del repositorio no ejecutada (171 ficheros ajenos en vuelo).

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_causal_execution.py -q   # esperado: 10 passed
./.venv/Scripts/python.exe scripts/ai_bots_003b_verify.py \
  --ledger reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/BOT-VIS-01_DECISIONS.jsonl \
  --summary reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/SUMMARY.json --root .   # esperado: 21 PASS / 0 FAIL
./.venv/Scripts/python.exe scripts/ai_bots_003b_verify.py \
  --ledger reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/BOT-VIS-01_DECISIONS.jsonl \
  --summary reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/SUMMARY.json --mutations   # esperado: 10/10
```

**Siguiente WP**: `AI-BOTS-003C/D` — proveedor offline listo (`NO_KEY => BLOCKED`) y colector
prospectivo con hash. La llamada real multimodal sigue necesitando clave y aprobación de coste.

---

## WP-TAP-AI-BOTS-003C — orden causal de la apertura, hueco y frescura (2026-10-18)

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Baseline:** `ffbc0ca` · **Estado:** motor,
tests y evidencia en el árbol, pendiente de commit al escribir esto.

**Objetivo.** Cerrar el P0 que dejó escrito el bloque B: los rellenos de entrada al OPEN se
ejecutaban antes de que el broker reconociese los stops que ese mismo OPEN ya había cruzado,
así que una pérdida evadía el motor de riesgo mientras la misma apertura aprobaba riesgo nuevo.

**Hecho.**

- `vision/lane.py`: `run` por fases — OPEN_GAP (posiciones preexistentes, todos los símbolos,
  antes de una sola aprobación), marca de apertura con veto `STALE_VALUATION` si un activo con
  posición no tiene apertura, entrada con la equidad que produce ese mismo OPEN, y CLOSE para
  rango intrabar + conciliación + propuestas nuevas. Nunca HIGH/LOW de la vela en una puerta de
  apertura.
- `paper/broker.py`: `stop_gapped()` compartido por ambas fases y `exit_on_open_gap()` (opt-in).
  El default `gap_policy="stop_price"` no cambia para otros llamantes.
- `vision/execution.py`: `CoverageProof`/`QuoteFeed` — un hueco sólo se cruza con prueba
  independiente de cobertura; sin ella es `DATA_GAP` y no opera.
- `test_open_phase_causality.py`: C-01…C-12, reduce-only y simetría largo/corto contra el
  `VisionLane` real, el `RiskManager` de `config/risk.yaml` y el `PaperBroker` de producción.
- `scripts/ai_bots_003c_capture.py` (5 escenarios) y `scripts/ai_bots_003c_verify.py`
  (independiente, sin importar `trading_bot`, 120 comprobaciones y 13 mutaciones con la cadena
  re-sellada). `CAPTURE.json` publica `series_sha256` de las barras consumidas y las versiones
  instaladas; el default de `--bars` pasa a 1000, que es la ventana con la que se capturó la
  evidencia (con 960 el comando documentado no reproducía sus propios artefactos).

```text
RED antes de implementar            18 failed / 1 passed     exit 1 (commit ffbc0ca)
tests/unit/vision                  160 passed                exit 0
tests/unit/paper                    73 passed                exit 0
tests/unit/risk                    147 passed                exit 0
tests/unit/intelligence             28 passed                exit 0
tests/unit/reports                  51 passed                exit 0
ruff / mypy (alcance tocado)        limpio                    exit 0
ai_bots_003c_verify.py × 5 escenarios        120 PASS / 0 FAIL   exit 0
ai_bots_003c_verify.py --mutations × 5       53/53 detectadas    exit 0
ai_bots_003b_verify.py (BLOCK-B, re-verificado) 21/21 + 10/10    exit 0
```

**P0 dentro de un instante** (`synthetic_gap_open`, escenario declarado sintético):
`seq 110 CLOSE BTC/USDT OPEN_GAP stop_loss bar_open −16.232058` precede a
`seq 111 DECISION_OUTCOME ETH/USDT risk_blocked_by=daily_loss_limit`, mismo `ts_ms`.

**Dos expectativas endurecidas, dichas en voz alta.** El test del hueco ya no acepta rellenar
porque la cotización siguiente sea posterior (ahora exige `DATA_GAP`, salvo prueba independiente
de cobertura); `exit_ts_resolution` pasa de `"bar"` a un vocabulario cerrado
(`OPEN_GAP`/`BAR_WINDOW`/`QUOTE`), aceptado por el verificador de 003B sin debilitar la regla.

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false` · `PROSPECTIVE_PAPER_VALIDATED = false`; proveedor replay.
- El hueco de apertura no existe en el dataset (mayor salto cierre→apertura 0,30 %); el camino
  está probado por construcción, no por el mercado.
- Con el stop canónico (0,5 %) las posiciones mueren en la vela en que nacen; el escenario de
  2 % es un override declarado del guion, no una política.
- Suite completa del repositorio no ejecutada (~180 ficheros ajenos en vuelo).

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_open_phase_causality.py -q   # 19 passed
./.venv/Scripts/python.exe scripts/ai_bots_003c_verify.py \
  --ledger   reports/ai-bots/RFC-AI-BOTS-003/BLOCK-C/evidence/synthetic_gap_open_ledger.jsonl \
  --summary  reports/ai-bots/RFC-AI-BOTS-003/BLOCK-C/evidence/synthetic_gap_open_summary.json \
  --coverage reports/ai-bots/RFC-AI-BOTS-003/BLOCK-C/DATA_COVERAGE_LEDGER.jsonl \
  --scenario synthetic_gap_open --root .                       # 24 PASS / 0 FAIL
```

**Siguiente WP**: `AI-BOTS-003D` (proveedor offline, `NO_KEY => BLOCKED`) y `003E` (colector
prospectivo append-only que satisfaga `QuoteFeed.prove_coverage`). Sin cotizaciones reales el
carril no opera un hueco: ahora es una fila `DATA_GAP`, no una convención del informe.


---

## 2026-10-18 · RFC-TAP-AI-BOTS-003F — ejecución sub-bar, panel real y auditoría de 003D/003E

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Base:** `fe9b5e2` · **Sin commits** (el
operador no autorizó commit/push). **LIVE no habilitado**, `config/risk.yaml` intacto.

**Procedencia P0.** `RFC-TAP-AI-BOTS-003F.md` no existía en HEAD, ramas ni worktrees
(comandos en `reports/ai-bots/RFC-AI-BOTS-003F/STATE_AUDIT.md`); se reconstruyó y se marca
como tal en el propio documento.

**Hecho**

1. 003D auditado: verificado (10 PASS / 0 FAIL, 4/4 mutaciones, 16 tests) pero **sin
   commitear** en `../bot_crypto_003d`, worktree sin venv. Su dependencia se importó al árbol
   canónico (feed, tests, scripts, datos, informes) sin tocar aquel worktree.
2. 003E implementado: `QuoteRange`/`SubBarQuoteFeed` en `vision/execution.py`,
   `MinuteBarQuoteFeed.range_between` en `vision/quotes.py`, `subbar_entries=False` por
   defecto en `vision/lane.py` con relleno en el primer minuto posterior, rechazo de feed que
   responde hacia atrás y rango de la vela de entrada limitado a minutos posteriores.
3. Economía medida (mismos 34 trades): CURRENT −97,926767 → PROPOSED −79,180509 USDT
   (+18,746258), DD −0,187463 pp, espera mediana 3 599 100 → 59 100 ms, precio +22,618 bps,
   Δnotional 0,0, llamadas/gasto 74/0,0 en ambos. Control a 0 ms idéntico.
4. Panel `VISION LANE` en el dashboard PAPER existente, alimentado por artefactos reales
   (estados ABSENT/PARTIAL/FAILED/VERIFIED, sha256 por fuente). Servido en vivo en
   `127.0.0.1:8787` (`vision_lane.state = VERIFIED`).
5. Verificación independiente: `scripts/ai_bots_003e_verify.py` **12 PASS / 0 FAIL**,
   **4/4 mutaciones**; 003C re-verificado 24/24; 003D 10/10.

```text
RED (sin QuoteRange)                 ImportError                              exit 2
GREEN sub-bar                        tests/unit/vision/test_subbar_execution  6 passed
GREEN visión / paper / riesgo / intelligence / reports    182 / 73 / 147 / 28 / 51
GREEN observabilidad / proveedor     39 / 12 passed                           exit 0
GREEN ruff + mypy (tocado)           limpio                                   exit 0
captura 4 escenarios + verify ×2     12 PASS / 0 FAIL · mutaciones 4/4        exit 0
dashboard en vivo                    /api/status vision_lane VERIFIED         exit 0
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED=false`: sin clave ni autorización de gasto; la puerta de credenciales ya
  existía (`MISSING_CREDENTIAL`, test que prueba que sin clave no hay petición HTTP).
- Feed de 1 m **vivo** inexistente: la capacidad sub-bar es opt-in y ningún runner la activa.
- `BUILDER != VERIFIER` como segundo agente sigue pendiente; G6 lo registró el constructor en
  `REGRESSION.json` y así se declara.
- Suite completa del repositorio no ejecutada (~180 rutas ajenas en vuelo).
- **Disco CRÍTICO: 0,77 GB libres**; el dashboard lo marca `CRITICAL`. Artefactos de 003E:
  1,3 MB. No se descargaron datos nuevos.
- 0 ejecuciones REA nuevas (evidencia REA existente reutilizada; disco crítico y roadmap
  prohíben repetir investigación). Ningún patrón externo pasa de `DEFER`/`EXPERIMENT`.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_subbar_execution.py -q   # 6 passed
./.venv/Scripts/python.exe scripts/ai_bots_003e_verify.py                           # 12 PASS
./.venv/Scripts/python.exe scripts/ai_bots_003e_verify.py --mutations               # 4/4
./.venv/Scripts/python.exe -m pytest tests/unit/observability/test_vision_panel.py -q  # 5 passed
./.venv/Scripts/python.exe scripts/paper_lab_dashboard.py --once | grep "VISION LANE"
```

**Siguiente WP**: `WP-TAP-AI-BOTS-003G` (`003E/NEXT_WORK_PACKAGE.md`) — colector de 1 m append-only y activación
explícita de `subbar_entries` en el runner PAPER cuando el feed vivo exista.

## 2026-10-19 · RFC-TAP-AI-BOTS-003G — colector 1 m real y sesión PAPER prospectiva

**Objetivo:** conectar el carril causal con velas reales de 1 m, operar prospectivamente en
PAPER y dejar trazas reconstruibles desde los bytes crudos. Ver `RFC-TAP-AI-BOTS-003G.md` y
`reports/ai-bots/RFC-AI-BOTS-003G/FINAL_REPORT.md`.

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Último commit:** `fe9b5e2` · **Sin commitear:**
todo el trabajo de 003G (el operador no autorizó commit/push).

**Hecho**

1. `src/trading_bot/market_data/minute_collector.py`: fuente Binance REST pública
   (`klines`/`time`), dos relojes y tres timestamps, vela en formación nunca guardada,
   duplicado idéntico ignorado / conflicto bloquea sin reescribir, desorden bloquea, huecos
   rellenados hacia delante antes de aceptar el minuto posterior, reconexión con backoff,
   frescura/skew, JSONL append-only + `MANIFEST.json` con sha256 + `EVENTS.jsonl` encadenado.
2. `src/trading_bot/vision/prospective.py`: sesión PAPER-only (`LiveModeRefused`), medición real
   de `data_delay_ms` (p95 de minutos cerrados tras el inicio), gate
   `decision_time >= data_time + delay + settle`, `BLOCKED` fail-closed, prefijo determinista
   entre ciclos.
3. `vision/lane.py`: `decision_from_ms` opt-in para que ninguna decisión use el warm-up.
4. `scripts/ai_bots_003g_paper.py`, `ai_bots_003g_compare.py`, `ai_bots_003g_verify.py`.
5. Sesión real de 32 min: 276 min × 2 símbolos, 0 gaps, 8 ciclos, 14 decisiones, **1 relleno
   sub-bar**, 0 bloqueos, retardo medido 2 956 ms. Comparación: CURRENT 0 rellenos / PROPOSED 1.
6. Defectos corregidos durante la ejecución: grupo 5 m cortado por el inicio (D1), vela revisada
   por el venue → `settle_ms` 2 500 (D2), mismo defecto en el verificador (D3).

**Pendiente / bloqueado**

- `INDEPENDENT_VERIFICATION_PENDING`: verificador propio (25 PASS / 0 FAIL, 4/4 mutaciones)
  pero `BUILDER == VERIFIER`.
- `INSUFFICIENT_SAMPLE`: 1 relleno, 0 cierres; la puerta económica de 003F exige ≥ 30.
- `REAL_MODEL_CALLED=false`: sin clave ni autorización de gasto; señal `paper-script`.
- D5 declarado, no corregido: `costs_usdt` sólo agrega operaciones cerradas (0,5 USDT de la
  posición abierta no aparecen en ese campo, sí en el equity marcado).
- G6: `test_runtime_artifacts_are_untouched_by_serving` falla si un escritor toca `reports/`
  durante la suite; aislado 14/14.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe -m pytest tests/unit/market_data tests/unit/vision/test_prospective_session.py -q
./.venv/Scripts/python.exe scripts/ai_bots_003g_verify.py \
  --session reports/ai-bots/RFC-AI-BOTS-003G/session --root .        # 25 PASS / 0 FAIL
./.venv/Scripts/python.exe scripts/ai_bots_003g_compare.py \
  --session reports/ai-bots/RFC-AI-BOTS-003G/session                 # CURRENT 0 / PROPOSED 1
```

## 2026-10-19 · RFC-TAP-AI-BOTS-003H — integridad contable y preparación PAPER

**Objetivo:** resolver D5 de 003G (contabilidad de posiciones abiertas) y los defectos de
validación pendientes, conservando la evidencia original. Ver `RFC-TAP-AI-BOTS-003H.md`.

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Último commit:** `fe9b5e2` · **Sin commitear:**
todo 003G/003H salvo lo que este WP commitee al cerrar.

**Hecho**

1. Auditoría: `costs_usdt` sólo sumaba operaciones cerradas (`lane.py:1365`), el broker ya
   calculaba el devengo y el equity marcado ya lo descontaba; la fila `FILL` no llevaba la
   comisión. Discrepancia de duración atribuida: los 50 min declarados son de
   `session-aborted-aggregation` (duration_s=3000), la sesión publicada declaró 2 400 s y
   terminó por `--max-cycles 8` a los 31 min 26 s de reloj.
2. Contrato `paper-accounting/2` en el lane: `costs_usdt` intacto; nuevos
   `costs_realised_usdt`, `entry_commissions_accrued_open_usdt`, `costs_total_usdt`,
   `pnl_realised_usdt`, `pnl_unrealised_usdt`, `pnl_total_usdt`, `marked_equity_usdt`, con
   significados publicados y cinco identidades nuevas en `reconciliation.identities`.
   La fila `FILL` publica `entry_commission_usdt`, `commission_bps`, `price_bps_per_side`.
3. Dashboard: fallo reproducido (1 fichero ajeno de 7 845 difiere) y corregido aislando el
   sujeto en `tmp_path`; 14/14 con escritor concurrente activo.
4. Tests nuevos: `tests/unit/vision/test_accounting_integrity.py` (5) y
   `tests/unit/market_data/test_data_integrity_003h.py` (6, incluidos los cuatro instantes y
   las dos esperas).
5. Verificador nuevo `scripts/ai_bots_003h_verify.py` (33 checks: los 25 de 003G por
   importación + 8 de contabilidad/instantes/settle/proyección).

**Hecho después (verificado)**

- Smoke PAPER de 10 ciclos con código congelado: **terminado**. 1 relleno, 0 cierres,
  `costs_total_usdt = 0,5`, `pnl_unrealised_usdt = +0,49443125`, `marked_equity_usdt =
  10 000,49443125`, 11 identidades, `settle` mínimo 2 544 ms. Verificador de 003H: 33/33 y
  sobre 003G 5 fallos (demuestra que no es vacuo). H1-H7 PASS, H8 `INSUFFICIENT_SAMPLE`.
  Evidencia: `reports/ai-bots/RFC-AI-BOTS-003H/{RUN_REPORT,FINAL_REPORT,INDEPENDENT_VERIFICATION}.md`.
- Regresión amplia: 671 passed, exit 0 (unit/contract/integration/runtime/wide).

**Pendiente / bloqueado**

- `INDEPENDENT_VERIFICATION_PENDING`: sin segundo agente revisor.
- Drift declarado: el verificador de 003G pasa 24/25 sobre su propia sesión porque 003H cambió
  `lane.py` y `prospective.py` (`STATE_AUDIT.md` §6.1).
- Ajenos pendientes en el árbol (no se tocan): `data/st6/**`, `reports/economic-recovery/**`,
  `scripts/paper_lab_dashboard.py`, `RUN_REPORT.*` de raíz, etc.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_accounting_integrity.py \
  tests/unit/market_data/test_data_integrity_003h.py tests/unit/observability/test_dashboard_server.py -q
./.venv/Scripts/python.exe scripts/ai_bots_003h_verify.py \
  --session reports/ai-bots/RFC-AI-BOTS-003H/smoke --root . --json-out /tmp/003h.json
```

---

## WP003I — Paper Accounting Closed-Trade Verification (en curso → completado en esta sesión)

**Objetivo.** Cerrar H8 de 003H con cierres **observados** en el runtime PAPER, reconciliados
desde el ledger por un verificador independiente, más una sesión prospectiva real informada
aparte.

**Base Git.** `5fd791d` (HEAD verificado; el runtime PAPER `vision/`, `paper/`,
`market_data/` no se modificó: `git diff 5fd791d -- <esas rutas>` vacío).

**Hecho**

- `scripts/ai_bots_003i_scenarios.py`: 8 escenarios controlados sobre `VisionLane` +
  `PaperBroker` + `RiskManager` reales, cada uno ejecutado dos veces (`run-1`/`run-2`),
  con `run_id` y digests de entrada en `RUN_META.json`/`EVIDENCE.json`.
  Resultado: 7 escenarios con cierre (3 con beneficio, 4 con pérdida), `MULTI_FILL` con
  4 rellenos/3 cierres, `OPEN_AT_END` con posición viva marcada.
- `scripts/ai_bots_003i_verify.py`: verificador que **no importa `trading_bot`**; reconstruye
  entrada, salida, efectivo, marca y disyunción abierto/cerrado desde `ledger.jsonl` +
  `bars.jsonl`, y ejecuta 13 mutaciones **re-selladas** (coste, cantidad, precio, PnL, comisión,
  `position_id`, instante, cierre duplicado, cadena, exposición) — 5 tipos en `OPEN_AT_END`,
  que no tiene cierre que mutar. 25/25 y 17/17 por escenario, **96/96 sondas** en total
  (el `82/82` de `SUPERSEDED/constructor-1320_FINAL_REPORT.md` es otro conjunto de sondas de
  otro hilo: no se cita como propio);
  los checks de divergencia D1/D2 (settle por reloj del venue, marca con la última vela cerrada)
  viven en `PRESERVED_003G` y `SESSION_003I`, no reescriben la evidencia congelada.
- `tests/unit/vision/test_closed_trade_cycle.py`: 7 tests (cierre con beneficio/pérdida,
  lado corto, comisiones una vez, cierre total, reconciliación tras reinicio, replay idéntico).
- Sesión prospectiva PAPER real (Binance 1 m, 3 h, `paper-script`): 37 ciclos, 1 relleno,
  **0 cierres naturales**; posición viva marcada. Rango medido desde la entrada:
  [82 134, 82 757,33] con stop 81 969,81 y objetivo 82 999,58 → no se cruzó ningún nivel.
- Defectos de medición encontrados en el verificador heredado de 003H, con evidencia:
  - **D1** `live_minutes_were_seen_after_they_settled` compara reloj host (`received_at_ms`) con
    reloj venue (`close_ms`); el host iba una mediana de 186 ms por detrás (rango medido 40-260 ms).
    4/358 minutos leen por debajo de `settle_ms`, pero con el reloj del venue
    (`server_time_ms - close_ms`) hay **0** violaciones y el mínimo es 2 531 ms ≥ 2 500 ms.
    Re-ejecutado con el verificador extendido: `PRESERVED_003G` 24 PASS / 1 FAIL (sólo el drift de
    runtime ya conocido) y `SESSION_003I` 31 PASS / 2 FAIL (sólo D1 y D2).
  - **D2** `marked_equity_rebuilds_from_raw_minutes` usa el minuto más nuevo, que puede pertenecer
    a una vela en formación; el lane sólo marca velas cerradas. Reconstruido con la última vela
    completa, la marca coincide con la publicada.

**Entregables exigidos (§6 de la misión)** — todos en
`reports/ai-bots/RFC-AI-BOTS-003I/ledger-accounting/` y hasheados en `EVIDENCE_MANIFEST.json`
(`files`: 7 documentos, `evidence`: 50 artefactos de origen; `missing: []`, digests
re-verificados contra disco):

`RUN_REPORT.md` · `RUN_REPORT.json` · `INDEPENDENT_VERIFICATION.md` · `ECONOMIC_VALIDATION.md` ·
`EVIDENCE_MANIFEST.json` (alias `EVIDENCE_INDEX.json`) · `FINAL_REPORT.md`, más
`LEDGER_AUDIT.md` y `EVIDENCE.md`. `INDEPENDENT_VERIFICATION.md` y `ECONOMIC_VALIDATION.md` los
emite ahora el generador, no se escriben a mano, y el manifiesto ya no hashea ficheros del
raíz compartido como si fueran propios (antes podía caer en `root/FINAL_REPORT.md`).

**Protección de evidencias (§2 de la misión)** — `--outdir` es **obligatorio** (sin él: exit 2)
y un directorio que ya contiene un manifiesto exige `--overwrite` (sin él: exit 3). Ambas guardas
probadas. Este hilo escribió el 19:34 UTC sólo `ledger-accounting/*` y
`verification/{PRESERVED_003G,SESSION_003I_003H}.json`; los informes raíz del otro hilo no se
tocaron.

**Pendiente / bloqueado**

- `INDEPENDENT_VERIFICATION_PENDING`: el verificador es aritmética distinta del mismo autor, no
  una revisión de un tercero; el veredicto no puede ser `PASS`. Dimensión `INDEPENDENT_VERIFIER`
  = `BLOCKED`; `EVIDENCE_TRACEABLE` = `PARTIAL` por los dos informes raíz perdidos.
- `H8-ECONOMICS = INSUFFICIENT_SAMPLE`: 0 cierres naturales (umbral 30). Diagnóstico
  cuantitativo en `ECONOMIC_VALIDATION.md`: 1 relleno/3 h (0,333/h ⇒ ~90 h para 30 rellenos);
  objetivo a +75 bp frente a una excursión máxima de +45,6 bp (faltaron 29,4 bp) y stop a
  −50 bp con excursión adversa −30,1 bp; **35 de 36 señales direccionales** bloqueadas por la
  posición abierta (`ALREADY_LONG`=17, `OPPOSITE_LONG_OPEN`=18); utilización de capital 5 % y
  drawdown 0,03 % sin eventos de riesgo. El techo es un slot por símbolo, no la falta de ciclos.
- **Colisión de escritor detectada (dos hilos, mismo WP, mismo directorio):** otro hilo escribe
  en `reports/ai-bots/RFC-AI-BOTS-003I/` desde otros worktrees (`wp003i-cert`, commits `cc3e84b`
  / `26fd395` / `9f3892f`) y es el autor de `GATE_MATRIX.json`, `WP003I_FILE_MANIFEST.json`,
  `REPRODUCIBILITY_D3_D4.md`, del `REGRESSION.json` V2 (13:20 UTC) y del `RUN_REPORT.md` raíz.
  No se tocan ni se reescriben sus ficheros. La evidencia de este hilo se publica aparte:
  `REGRESSION_003I_ACCOUNTING.json` y documentos en
  `reports/ai-bots/RFC-AI-BOTS-003I/ledger-accounting/` (`--outdir`). Los datos de escenarios,
  verificaciones y sesión seguían intactos (schema V1, `run_id` propios) en la última
  comprobación. **Incidente de hoy:** dos ejecuciones del generador sin `--outdir`
  reescribieron `reports/ai-bots/RFC-AI-BOTS-003I/{RUN_REPORT,FINAL_REPORT}.{md,json}` a las
  16:26 UTC, que son ficheros de ese otro hilo (ignorados por Git, no recuperables desde el
  repo). Este hilo no volverá a escribir fuera de `ledger-accounting/`; ese hilo debe
  re-generar su informe raíz.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/ai_bots_003i_scenarios.py --clean
for d in reports/ai-bots/RFC-AI-BOTS-003I/controlled/*/; do
  n=$(basename "$d")
  ./.venv/Scripts/python.exe scripts/ai_bots_003i_verify.py --run "$d/run-1" --replay "$d/run-2"     --json-out "reports/ai-bots/RFC-AI-BOTS-003I/verification/$n.json"     --md-out "reports/ai-bots/RFC-AI-BOTS-003I/verification/$n.md"
done
./.venv/Scripts/python.exe scripts/ai_bots_003i_report.py   --regression REGRESSION_003I_ACCOUNTING.json --outdir reports/ai-bots/RFC-AI-BOTS-003I/ledger-accounting --overwrite
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_closed_trade_cycle.py -q
```

Cada comando produce artefacto y exit code; el informe recalcula H1-H8 desde ficheros y falla si
falta uno.

---

## DEF-RUN-014 — cierre del contrato del stop (2026-10-20, hilo `agent/ai-bots/RFC-TAP-AI-BOTS-003`)

> Sección añadida por el hilo de DEF-RUN-014. No reescribe nada de las secciones anteriores;
> otro hilo sigue siendo el dueño de su propio estado y de sus ficheros.

**Objetivo**: que el stop declarado por la estrategia sea el que el libro arriesga, con origen
publicado, y que un stop que no puede pagar su fricción sea `NO_TRADE` con causa.

**Último commit**: `b0e15497d967ff1c1d3015203ffb7cbfcf0a70a0` (árbol de trabajo sucio; esta
corrección **no** se ha commiteado).

**Hecho (con evidencia)**

- `risk/manager.py`: `StopResolution`, `resolve_stop`, `risk_at_stop_usdt`, `sizing_basis`,
  `cost_bps_for`, `stop_cost_policy` (`OFF`/`REPORT`/`REJECT`), bloqueos `invalid_stop` y
  `stop_inside_costs`.
- `vision/lane.py`: el modelo entrega su stop/objetivo; la orden lleva el efectivo; el ledger
  publica el contrato completo en `DECISION_OUTCOME` y `FILL`; `REJECT` activo.
- `paper/broker.py`: `STOP_LOSS_REQUIRED` en vez del 1 % silencioso.
- Tests nuevos: `tests/unit/risk/test_def_run_014_stop_contract.py` (13),
  `tests/unit/vision/test_def_run_014_lane_contract.py` (4). Contra `HEAD`: **15 failed, 2
  passed**; con la corrección: **17 passed** (26 con DEF-RUN-015).
- Suites: `tests/unit/risk tests/unit/paper tests/unit/vision` → 508 passed;
  `tests/integration` → 24 passed.
- Verificador independiente `scripts/def_run_verify.py` (stdlib, sin importar runtime):
  **147/147 PASS** sobre la captura, el E2E determinista y tres sesiones PAPER reales. Dos
  controles negativos fallan como deben (incluida una mentira con hash recalculado).
- Runtime PAPER real: `DEF-RUN-PAPER/de3-*` (4 ciclos, 1 fill), `-model-*` (12 ciclos, 0 fills,
  1 `stop_inside_costs` con 8.41 ≤ 24.79 bps), `-real-20261020T170319Z` (60 ciclos, 1 fill,
  0 cierres, identidades 11/11).
- Informes: `reports/ai-bots/RFC-DEF-RUN-014/{RUN_REPORT.md,RUN_REPORT.json,DEF-RUN-014_FINAL_REPORT.md}`.

**Pendiente**

- `REAL_RUNTIME_PAPER_E2E` = `NOT_OBSERVED`: ninguna sesión real ha cerrado una posición.
- `DEF-RUN-016` (nuevo): `SUPERSEDED_BY_NEWER_OPINION` — 5 de 12 opiniones del modelo expiran
  antes de tener cotización ejecutable con `decision_every_bars=1` y 30 s de latencia.

**Bloqueos**

- La suite global no completa: `tests/unit/research` se cuelga (>10 min, 51 %). Muestras
  ejecutadas fallan por artefactos de campaña obsoletos (`test_active_recovery_wp.py`: "the
  committed view is stale"), ajenos a este defecto.
- `tests/unit/market_structure` no colecciona (`ImportError` circular `trade_journal ↔
  market_structure`), pre-existente.
- `tick_size_check = NOT_AVAILABLE`: sin metadatos de instrumento.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe -m pytest tests/unit/risk/test_def_run_014_stop_contract.py \
  tests/unit/vision/test_def_run_014_lane_contract.py -q -p no:cacheprovider
./.venv/Scripts/python.exe scripts/def_run_verify.py --root reports/ai-bots \
  --session reports/ai-bots/DEF-RUN-PAPER/de3-20261020T152902Z \
  --session reports/ai-bots/DEF-RUN-PAPER/model-20261020T170635Z \
  --session reports/ai-bots/DEF-RUN-PAPER/real-20261020T170319Z
# sesión de mercado para intentar el cierre real (no fabricar el resultado):
./.venv/Scripts/python.exe scripts/ai_bots_003g_paper.py --mode PAPER --symbols BTCUSDT ETHUSDT \
  --timeframe 15m --window-bars 24 --decision-every-bars 1 --duration-s 21600 \
  --poll-s 30 --latency-ms 30000 --warmup-minutes 1440 \
  --signal-source strategy_experimental --strategy-id mean_reversion \
  --out reports/ai-bots/DEF-RUN-PAPER/close-<stamp>
```

## 2026-10-20 · EXP-003N-GROSS-FIRST-DISCOVERY-001 — de dónde sale el ingreso bruto

**Objetivo:** decidir si existe al menos un candidato con expectativa económica neta antes de
gastar más en modelar fills maker. **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Modo:**
research offline, `LIVE_ENABLED=false`, 0 órdenes, holdout `2026-08-06 → 2026-08-20` **cerrado**.

**Fase 0 — integración de 003M (hecha, con defectos reparados)**

1. `sha256sum -c` en el árbol de trabajo: **18/18** artefactos publicados y **126/126** datos.
2. Commits trazables de 003M sin la cinta: `f014813` (scripts + tests), `10919df` (artefactos,
   diseño, análisis, manifiestos; `.gitignore` publica el informe y deja fuera los 400 MiB).
3. **Checkout limpio** (`git worktree --detach`): el sello verificaba **0/18** porque
   `core.autocrlf=true` reescribía los ficheros a CRLF. Reparado en `9800925`
   (`.gitattributes ... -text`); después **18/18**. Segundo defecto: 8 de 25 tests sellaban
   usando `EXP-003L/SHA256SUMS.txt`, un árbol no commiteado, y pasaban solo en esta máquina.
   Reparado en `fefb077` (el sello nombra la ausencia en vez de fallar); después **25/25** en un
   worktree que nunca tuvo 003L.
4. Datos externos **regenerados** en el checkout limpio: 3 × 86 400 barras desde
   `/api/v3/klines` con los digests congelados exactos, y **126/126** ficheros de cinta/klines
   re-descargados de `data.binance.vision` byte-idénticos (`TAPE_MANIFEST.json`
   `2d515444…`). Evidencia: `reports/ai-bots/EXP-003N-…/evidence/CLEAN_CHECKOUT_REHEARSAL.*`.
   La ventana de Git dentro del worktree quedó en **0 líneas**.

**Fase 1 — inventario real**

`design/STRATEGY_UNIVERSE.json` se deriva del árbol (AST: imports y llamadas, no prosa):
**6** `RUNTIME_REACHABLE` (las seis AlphaFamilies del adaptador PAPER), **1** `TEST_ONLY`
(`EmaCrossoverStrategy`), **3** `EXPERIMENTAL` (cand001-cand003, ya `REJECTED_INITIAL_EXPERIMENT`),
**6** `RESEARCH_ONLY` (máquinas PIT de WP-EDGE-015 y las tres carteras de research). No se
inventó ninguna estrategia ni se duplicó una implementación: se llaman las clases reales.

**Fase 2/3 — screening económico (protocolo congelado en disco antes de mirar ninguna cifra)**

24 celdas (6 familias × 5m/1h/4h + 3 familias WP-EDGE-015 × 1h/4h) sobre BTC/ETH/SOL, 46 días,
IS 06-21→07-11 / VAL 07-11→07-26 / TEST 07-26→08-06. Retorno forward por señal a 6 horizontes,
entrada en el open siguiente, bloque de 5 días, 10 000 remuestreos, BH q=0,10.

- **13 `REJECT`**, **10 `INSUFFICIENT_EVIDENCE`**, **1 `EXPERIMENT`**, **0** `ADVANCE`.
- Mejor celda con muestra suficiente: `momentum@1h` — bruto **23.49 bps**/señal en VAL frente a
  **27.31 bps** de coste completo (suelo de comisiones 20 bps; 24.786 en BTC/ETH, 27.31 en SOL):
  neto **-3.82 bps**/señal y **-37.58 bps** por operación cerrada sobre 576 cierres.
- `5m/mean_reversion`: **-51.82 bps** por cierre, mismo signo que 003M (-48.31) por otro método.
- El único neto positivo (+234.90 bps) es `volatility@4h` con **1** operación: se publica como
  `INSUFFICIENT_EVIDENCE`, no como candidato.
- Lane B (WP-EDGE-015) no produce muestra: el warm-up de percentiles (720 h) consume la ventana
  de 46 días. Ceros declarados `INSUFFICIENT_EVIDENCE`, nunca `REJECT`.

**Fase 4/5 — verificación y entrega**

Verificador separado `scripts/exp_003n_verify.py`: **12/12** comprobaciones, **10/10** controles
negativos detectados, `false_success=0`, **6 692** retornos forward recalculados desde las barras
(0 discrepancias), **35** operaciones cerradas recalculadas (0 discrepancias). Ocho entregables
más `ECONOMIC_SCREENING.csv`, `SEAL.json` (29 ficheros) y `SHA256SUMS.txt` (`c65d92ef…`).

**Reproducción desde checkout limpio (hecha, no prometida)**

`scripts/exp_003n_rehearsal.py --commit cd3fc31` materializa el commit en un `git worktree`
`--detach` (0 líneas en `git status` antes de empezar), copia las tres cajas de 1 minuto solo
después de que su SHA-256 coincida con el que fijó el diseño, y re-ejecuta screening, validación,
verificación y tests **dentro** de ese worktree. Resultado: **24/24** celdas de screening
idénticas, **24/24** de validación idénticas, **0** diferencias hoja a hoja, veredicto
`NO_VIABLE_CANDIDATES` en ambos lados, **12/12** comprobaciones y **10/10** controles del
verificador en el worktree, **20** tests pasan. Evidencia:
`reports/ai-bots/EXP-003N-…/evidence/CLEAN_CHECKOUT_REPRODUCTION.{json,_STDOUT.txt}`.

Reproducir encontró un defecto que el constructor no vio: **DEF-003N-01** —
`exp_003n_screen.py` imprimía `target.relative_to(REPO)` y lanzaba `ValueError` cuando `--out`
caía fuera del repositorio (ruta corta 8.3 del worktree), **después** de haber escrito
`SCREENING.json`, `SIGNALS.jsonl.gz` y `ECONOMIC_SCREENING.csv`. Un llamador que solo mirase el
exit code habría tirado un resultado correcto. Reparado con un guard `is_relative_to`; no se tocó
código de medida. Es la razón por la que la reproducción existe.

**Límite de procedencia (declarado, no maquillado)**

El protocolo se congeló en disco a las `18:38:16Z` y el screening corrió a las `19:32:34Z`, pero
`design/DESIGN.json` y `design/PREREGISTRATION.md` **entraron en Git después** de que existiera
el análisis. El congelamiento está anclado por contenido (`SCREENING.json` guarda el
`design_sha256`; el verificador V3 lo compara) y **no** por tiempo. El análisis es
**retrospectivo con protocolo declarado**, no prospectivo; así consta en `RUN_REPORT.md`,
`FINAL_REPORT.md` y `RUN_REPORT.json → preregistration.prospective = false`.

**Commits del experimento**

| commit | contenido |
| --- | --- |
| `a5bda8f` | protocolo (`design/`), preregistración legible, los seis programas y su test |
| `cd3fc31` | análisis publicado (señales, screening, validación, decisión, verificación, tests) + evidencia de la Fase 0 |
| `6b0dac1` | entregables, evidencia de reproducción, `DEF-003N-01`, sello y este checkpoint |

**Sello comprobado en un checkout limpio.** `git worktree add --detach /tmp/003n-sealcheck 6b0dac1`
con `git status` en **0** líneas: `cd reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 &&
sha256sum -c SHA256SUMS.txt` → **29/29 OK**, y `pipeline status` informa `seal OK (29 files)`.
Matiz de lectura: `SEAL.json → sealed_commit` vale `cd3fc31` porque es el HEAD que existía al
escribir el sello; los 29 ficheros sellados se publican en `6b0dac1`, cuyo árbol es ese mismo
contenido más `SEAL.json` y `SHA256SUMS.txt` (excluidos del manifiesto por construcción).

**Pendiente / bloqueado**

- El verificador **no regenera las señales**: recalcula retorno, coste, puertas y veredicto desde
  las barras para los timestamps publicados. Un look-ahead dentro de la ventana PIT de una familia
  lo cubren los tests, que no son independientes del constructor.
- `NO_VIABLE_CANDIDATES` no es una propiedad del mercado: es lo que ocurre con las 9 familias
  implementadas, 3 activos y 46 días. Una familia nueva no está probada; está sin escribir.
- `tests/unit/research` sigue colgándose (>10 min) — pre-existente, ajeno a este experimento.
- El verificador es un programa, no una persona (`INDEPENDENT_VERIFIER=PROGRAM_NOT_PERSON`).

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/exp_003n_preregister.py --check
./.venv/Scripts/python.exe scripts/exp_003n_pipeline.py status
./.venv/Scripts/python.exe scripts/exp_003n_verify.py --negative-controls --json-out /tmp/003n-verify.json
./.venv/Scripts/python.exe scripts/exp_003n_rehearsal.py --commit cd3fc31 --resume
(cd reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 && sha256sum -c SHA256SUMS.txt)
# un re-sello exige borrar SEAL.json y SHA256SUMS.txt: el pipeline se niega a sellar dos veces
```

---

## 2026-10-21 · Recuperación de experimentos: `EXP-003N` reproducido desde `HEAD` limpio, gate reutilizable, y ningún experimento nuevo autorizado

**Objetivo:** establecer autoridad real, reproducir el verificador de `EXP-003N` en vez de citarlo, conservar `N`
cerrado, extraer el gate fail-closed como componente reutilizable, auditar la cadena económica y decidir si existe
un siguiente experimento legítimo.

**Hecho**

1. **Autoridad:** este checkout, `origin = bot_crypto.git`, rama `agent/ai-bots/RFC-TAP-AI-BOTS-003`, `HEAD 277d1df`,
   **13 commits por delante** de su remoto y 0 por detrás, 21 worktrees, 58 ficheros modificados y 211 sin seguimiento
   (ajenos). Detalle en `docs/agentic/RUNTIME_AUTHORITY_REPORT.md`.
2. **Verificador reproducido, no citado.** El árbol sellado se niega (`SEAL.json` → exit 4, correcto). Sobre un
   worktree **detachado en `277d1df`** con los tres `.jsonl.gz` congelados copiados y el sello excluido solo en la
   copia: **12/12 checks, 10/10 controles, verdict `PASS`, exit 0**, y las listas `checks`/`controls` **idénticas
   campo a campo** a `analysis/VERIFICATION.json`. Antes se había ejecutado también en el árbol sucio: mismo
   resultado. La reproducción limpia es la que cuenta.
3. **`EXP-003N` sigue cerrado.** Los 43 `null` del borrador recibido siguen siendo 43 y `DRAFT_UNFROZEN`: el
   borrador vive solo en el zip, nunca en este repositorio (`config/preregistration.json` no existe aquí).
4. **Gate extraído:** `src/trading_bot/research/prereg_gate.py` (`PREREG_GATE_V1`), parametrizado por identificador,
   con `SPENT_EXPERIMENT_IDENTIFIER`, ledger de ejecuciones previas en tres formatos (se toma el máximo) y contrato
   de salida `0` autorizado / `3` inspección / `2` bloqueado. Tests: **51 passed, 1 skipped** (symlink sin privilegio
   en Windows); `ruff` y `mypy` limpios. Contra este repositorio: `EXP-003N` → **BLOCKED, exit 2,
   `SPENT_EXPERIMENT_IDENTIFIER:EXP-003N-GROSS-FIRST-DISCOVERY-001`**.
5. **Tres hallazgos de auditoría** (`EXPERIMENT_INVENTORY.md`, `ECONOMIC_EVIDENCE_REPORT.md`):
   `EXP-003J` **es** el brazo `real` de `EXP-003K` (mismos 505 cierres, mismo −225.401044), no una segunda
   confirmación; la ventana `2026-08-06→2026-08-20` **la leyó `003K`** (131 + 175 cierres) aunque `N` la marque
   `CLOSED`; y el corpus forward es **229 días `DENSE_BUT_BACKFILLED` frente a 5 `PROSPECTIVELY_OBSERVED`** de 235.
6. **Ningún experimento autorizado.** Mejor gross medido en todo el repositorio: **14.80 bps contra 24.79–27.31 bps**
   de ida y vuelta (5 mediciones independientes, 0.08×–0.67× del peaje). Se propone `EXP-004A` (medir el peaje real
   sobre cotizaciones observadas prospectivamente) y **no se ejecuta**: exige 90 días prospectivos y un freeze en dos
   fases que el gate todavía no sabe expresar (`NEXT_EXPERIMENT_PROPOSAL.md` §4).

**Pendiente / bloqueado**

- `EXP-004A` **no autorizado**: faltan 85 de 90 días prospectivos y el freeze en dos fases no existe. No se relaja el
  chequeo de digests para rodearlo.
- El verificador de `N` es un programa, no una persona: `INDEPENDENT_VERIFIER=PROGRAM_NOT_PERSON`.
- `EXP-003J` sigue **sin seguimiento en Git** (run completo, verificado y negativo). No se commitea aquí porque es de
  otro workstream; queda registrado como riesgo en `RUNTIME_AUTHORITY_REPORT.md` §4.
- Un test del gate queda **skipped** (symlink en Windows): esa rama no está verificada en esta máquina.
- El comando de reanudación de la entrada anterior (`exp_003n_verify.py --negative-controls --json-out /tmp/...`)
  ahora devuelve **exit 4**: el sello existe. Es correcto; para reproducir hay que usar una copia sin `SEAL.json`.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s' && git rev-list --count origin/agent/ai-bots/RFC-TAP-AI-BOTS-003..HEAD   # 13
(cd reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 && sha256sum -c SHA256SUMS.txt)               # 29/29
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prereg_gate.py -q                       # 51 passed, 1 skipped
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate --repo . --experiment-id EXP-003N --mode authorize
./.venv/Scripts/python.exe -c "import json;c=json.load(open('data/forward/edge04/coverage.json'));from collections import Counter;print(Counter(d['class'] for d in c['days']))"
# reproducir el verificador desde HEAD limpio: ver FINAL_REPORT.md, bloque "Reproduce this report", paso 3
```

---

## 2026-10-21 — TAP-EXP-004A-FOUNDATION (freeze en dos fases, admisión prospectiva, coste medido)

**Objetivo:** preparar la validación económica prospectiva sin ejecutarla.
**Base auditada:** `f831c66` (y su gemelo pre-amend `39153a0`, mismo padre `277d1df`: difieren en 3 líneas de
`FINAL_REPORT.md`). **Ningún experimento autorizado.** `economic_executions: 0`, `live_orders: 0`.

**Hecho**

1. **Gate en dos fases** (`prereg_gate.py` + `docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md`): `PROTOCOL_FROZEN`
   (fase 1) es inspeccionable (exit 3) y **nunca autorizable** (`TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`, exit 2);
   los digests se difieren por dataset, explícitamente, y **no** en fase 2. El orden se verifica contra el reloj de
   git, no contra el manifiesto: commit del protocolo < `capture.start_utc`, commit del registro ≥ `capture.end_utc`,
   y `period_start >= start` / `period_end <= end` para cada dataset. Sin reloj verificable → `TWO_PHASE_TIMING_UNVERIFIABLE`.
2. **Admisión prospectiva sellada** (`src/trading_bot/research/prospective/`): 234 atestaciones para el carril 1h
   (702 digests de serie) y 14 para 1h+15m (84), **verificadas contra los bytes, 0 errores**. Segunda ejecución:
   **0 registros añadidos** y sigue verificando (idempotente). `sealable_through` impide sellar un día cuyos barras
   aún pueden llegar legítimamente.
3. **Discrepancia de 235 días resuelta**: 235 días con barra → 234 clasificables → **229 backfilled** → **5**
   prospectivos en 1h → **4** exigiendo 1h+15m. La diferencia 5/4 es `2026-10-15` (22/24 barras 1h dentro del bound,
   79/96 en 15m). El carril 15m empieza `2026-10-07`, que es también donde acaba el corpus 15m congelado.
4. **Coste medido** (`execution_cost/`, sin aritmética nueva: fee de `VENUE_SPECS`, spread y depth del tape ST-6):
   **BTC 20.0012**, ETH 20.0408, SOL 20.9414 bps medianos a **200 USDT**, clase `OBSERVED`. El peaje es el fee:
   95.5–99.99 % del total. A **500 USDT** —el notional declarado— el tape nunca caminó ese tamaño:
   `DECLARED_SIZE_NOT_WALKED` y cota inferior, no medición.
5. **Independencia**: 4 afirmaciones de experimento → **3 ventanas independientes**. `EXP-003J` ≡ `EXP-003K`.
6. **Tests**: **115 passed, 1 skipped**. `ruff` y `mypy` limpios. El hueco del symlink queda **cerrado en esta
   máquina** con una junction real (`mklink /J`, sin privilegios) más un control positivo; el skip que queda es el
   test antiguo de `symlink_to`, sustituido, no arreglado.
7. **`EXP-004A` fase 1 commiteado** en `config/preregistrations/EXP-004A.{json,datasets.json,prior_runs.json}` y
   **rechazado por su propio gate** (exit 2). `discover_existing_runs('EXP-004A')` sigue `[]`: el informe vive en
   `docs/agentic/exp004a/`, fuera de `reports/ai-bots/`, para no gastar el identificador que prepara.

**Pendiente / bloqueado**

- **4 de 90 días** admitidos. El observador produce ~5 días admisibles por 234 días liquidados: el cuello de botella
  es la cobertura del observador, no el protocolo.
- **500 USDT nunca caminado**: o se extiende el colector antes del `capture.start_utc` (2026-10-22), o el
  experimento se declara en 200 USDT. No se escala el impacto.
- **Verificador no escrito**: `independent_verifier_identity = NOT_YET_ASSIGNED`; no lo puede escribir el builder.
- Fase 2 (registro de digests) **no existe** y no puede existir antes del cierre de la captura.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe scripts/exp004a_foundation.py
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate --repo . --experiment-id EXP-004A \
    --manifest config/preregistrations/EXP-004A.json \
    --registry config/preregistrations/EXP-004A.datasets.json --mode authorize    # BLOCKED, exit 2
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prospective_admission.py \
    tests/unit/research/test_execution_cost_measured.py \
    tests/unit/research/test_prereg_gate_two_phase.py \
    tests/unit/research/test_prereg_gate_escape.py -q                              # 64 passed
```

> **Nota de alcance (misma sesión):** el conteo/seal de admisión es **automático en la observación**
> (el observer de WP-EDGE-03 corre por el planificador del host) pero **invocado a mano en el conteo**: el paso
> es append-only e idempotente (segunda ejecución: **0** registros añadidos), así que invocarlo a diario añade solo
> días nuevos. Engancharlo al supervisor existente es un cambio de estado del host y no se hizo aquí.
