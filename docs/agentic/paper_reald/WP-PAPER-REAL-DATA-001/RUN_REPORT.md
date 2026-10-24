# RUN_REPORT — WP-PAPER-REAL-DATA-001

**Worktree aislado**: `ff-wt-prd001` (rama `paper/reald-data-001`), base `e67194e7` (`main`).
**Nada de `main` fue modificado**: todos los cambios son ficheros nuevos (scripts + este directorio).
**Datos de mercado**: endpoints **públicos** de producción de Binance (`api.binance.com`), sin credenciales.
**Órdenes live**: 0. **Credenciales usadas**: 0. **Dinero real**: 0.

La fuente de cada número de este informe está en `RUN_REPORT.json`, ensamblado desde los artefactos
por `scripts/wp_prd001_report.py` (ningún número se escribe a mano).

---

## 1. Revalidación de la autoridad

| Comprobación | Resultado |
| --- | --- |
| Commit EXP004A `c727b614` existe | sí |
| `c727b614` es ancestro de esta rama | **no** — vive en `recovery/exp004a-02k-9983b050`, no se ha fusionado |
| `data/raw/alpha003` presente | **no** (sigue ausente) |
| `config/` con cambios sin commitear | no |
| Conclusión | EXP004A sigue **BLOCKED_WITH_EVIDENCE**; este WP no lo desbloquea ni lo toca |

## 2. ¿Puede el runtime PAPER funcionar sin el corpus 15m?

Cierre de imports por AST desde `scripts/autonomous_paper.py` (imports relativos resueltos):

- **76 módulos** del repo alcanzados.
- **0** mencionan el corpus 15m (`alpha003`, `CORPUS_15M`, `load_15m`, `_15m.json`).
- **0** fallarían sin `data/raw/alpha003/price`.
- Veredicto: `paper_path_depends_on_missing_corpus = false`.

Alcanzabilidad de estrategias, leída del ledger comprometido (no supuesta):

| Timeframe | Estrategias consideradas | Admisión PAPER | Decisión si es seleccionada |
| --- | --- | --- | --- |
| 1h | breakout, ema_crossover, mean_reversion, momentum, trend, volatility | 0 de 6 | 5× `NO_GROSS_EDGE`, 1× `SHADOW_OR_NOT_ADMITTED` (volatility +6.28 bps) |
| 5m | las mismas 6 | 0 de 6 | 5× `NO_GROSS_EDGE`, 1× `SHADOW_OR_NOT_ADMITTED` (mean_reversion +1.49 bps) |

**El ledger no admite ninguna estrategia para PAPER** (0 de 18 entradas). Es la restricción que
domina todo lo demás: sin admisión, el camino de órdenes es inalcanzable desde señales de mercado.

## 3. Acceso a datos reales: el guard que había que respetar

`config/realdata` declara `universe.exchanges[0].sandbox: true`, y `Settings` lo exige:
*«runtime.mode='paper' exige sandbox=true»*. Esa regla es gobernanza (PAPER no abre sesión de venue),
no un obstáculo a rodear. Por eso el campamento **no toca el guard ni el exchange**:

- se invoca el entrypoint de producción sin cambios (`scripts/wp_prd001_campaign.py` importa
  `autonomous_paper` y sustituye **una** función, `build_scanner_factory`);
- la fuente inyectada (`PublicKlinesSource`) solo lee rutas públicas (klines, ticker, bookTicker),
  con `apiKey: ""` y `secret: ""`, y **ninguna sesión de connector** se abre;
- probado, no declarado: el verificador exige `multi_exchange.call.* = 0` y
  `multi_exchange.connector.resolve = 0` en los logs de las tres campañas.

## 4. Calidad de datos reales (`raw/DATA_QUALITY.json`)

BTC/ETH/SOL, 1h, 200 barras por símbolo: **199 cerradas + 1 en formación descartada**.

| Comprobación | BTC | ETH | SOL |
| --- | --- | --- | --- |
| Grid alineado a 1h | ✅ | ✅ | ✅ |
| Duplicados | 0 | 0 | 0 |
| Gaps | 0 | 0 | 0 |
| Violaciones OHLCV | 0 | 0 | 0 |
| Última barra cerrada dentro del presupuesto de frescura (1.5 barras = 90 min) | ✅ (428 s) | ✅ (432 s) | ✅ (436 s) |
| Cross-check HTTP crudo vs CCXT sobre barras cerradas | 199/199 idénticas | 199/199 | 199/199 |

Ventana PIT (120 barras cerradas) con digest propio por símbolo, para atar cualquier decisión a los
bytes exactos que la produjeron. Los 200 registros de acceso están en
`raw/DATA_ACCESS_run_a.jsonl`, `…_run_b.jsonl`, `…_run_c.jsonl` con `authenticated: false`.

## 5. RUN-A — campaña 1h sobre datos reales

`--provider ccxt --timeframe 1h --cycles 3 --assets BTC,ETH,SOL` → **exit 0**.

| Métrica | Valor |
| --- | --- |
| Decisiones | 9 (3 ciclos × 3 activos) |
| Ventana de contexto | 1 (barra 15:00, repetida: los 3 ciclos evaluaron el mismo cierre) |
| Modos | `NO_TRADE` 9 |
| Clasificación | `NO_GROSS_EDGE` 9 |
| Verificador independiente | `PASS` 9/9 (incluye `pit_slice_exact`) |
| Risk | `PASS` 9/9 (advisory; sizing 500 USDT) |
| Órdenes | **0** |
| Gross esperado | −0.96 … −0.22 bps |
| Coste del modelo | 22.79 … 23.79 bps |
| Hash chain del trace | intacta |

Razón textual de cada decisión: `gross_edge_not_positive:-0.2200bps` (BTC/ETH) y
`-0.9600bps` (SOL). **No se forzó ninguna señal.**

## 6. RUN-B — campaña 5m multi-vela sobre datos reales

`--timeframe 5m --cycles 3 --interval 300`, arrancada ~30 s tras un cierre → **exit 0**.

- **3 cierres distintos**: ventanas `16:10`, `16:15`, `16:20` (prueba real de continuidad entre barras).
- 9 decisiones, `NO_TRADE` 9, `NO_GROSS_EDGE` 9, verificador `PASS` 9/9, risk `PASS` 9/9.
- Órdenes 0. Gross −4.56 … −1.65 bps contra coste 22.79 … 23.79 bps.

Hallazgo operativo: el gate de frescura presupuesta **1.5 barras medidas desde la APERTURA** de la
última barra cerrada. En 5m eso deja una ventana útil de ~2.5 min tras cada cierre. Un ciclo lanzado
3 s *antes* de un cierre ve contexto `stale_context` (observado y registrado en el primer intento de
RUN-C). Las campañas deben alinearse al cierre — que es exactamente lo que hace
`--cadence bar-close`, y lo que hace este harness por construcción.

## 7. RUN-C — camino de órdenes, etiquetado como prueba controlada

Sin admisión no hay orden posible desde el mercado, así que la ruta de ejecución se probó con
**dos entradas sustituidas y declaradas** (`raw/CONTROLLED_EXEC.json`):

- admisión: fixture `fixtures/TEST_ONLY_admission_ledger.json` (`PAPER_CANDIDATE`, gross 100 bps
  **sintéticos**), fuera de `config/` y nunca cargado por un run de producción;
- señal: familia `test_signal` determinista;
- **todo lo demás es el runtime real**: ciclo `AutonomousPaperRuntime`, 5 agentes, verificador
  independiente, `RiskManager` con los límites comprometidos, `PaperBroker` (1 bp slippage, 5 bp
  comisión), `StartupReconcilerV4`, y **precios reales** del feed público.

| Hecho verificado | Valor |
| --- | --- |
| Ciclo 1 | 3 `TRADE_PAPER` (`PAPER_ADMITTED`), 3 fills |
| Nocional por orden | 500 USDT ≤ tope 1 000 (10 % de 10 000) |
| Comisión | 0.25 USDT por lado = 500 × 5 bp (recalculado) |
| Slippage de entrada | precio = referencia del trace × 1.0001 (recalculado) |
| Ciclo 2 (barra posterior, 17:00) | 3 posiciones cerradas por `take_profit` con precios reales |
| PnL bruto / neto por posición | +4.9495 / **+4.4495** USDT (bruto − 2×0.25) |
| Equity | 10 000 → **10 013.3485** (Δ = Σ PnL neto, exacto) |
| Reconciliación post-trade | `CONSISTENT` |
| Reconciliación tras recargar estado | `RECOVERED`, equity preservado |
| Nuevas entradas en ciclo 2 | 3 `RISK_VETO`: *Max open positions reached (3)* — el libro de riesgo se sincroniza **antes** de que la reconciliación cierre por TP; conservador, no peligroso (ver §11) |
| Checks internos de la ruta | 13/13 `TEST_EXECUTION_PASS` |

Los precios de salida son reales; **no** se usó el cierre forzado a precio de test porque el TP se
alcanzó en el mercado. La etiqueta del artefacto lo dice: `label: TEST_EXECUTION`,
`forced_exit_price: TEST parameter`, `signal_source: FIXTURE`.

## 8. Verificación independiente (`VERIFIER.json`)

`scripts/wp_prd001_verify.py` no importa ninguno de los builders. Reimplementa el hash chain,
recalcula la aritmética de dinero desde los rows del broker, **re-descarga** la ventana PIT de 120
barras por símbolo y la compara con el digest registrado, y relee el ledger comprometido y el bloqueo
de EXP004A.

```
{"checks": 43, "passed": 43, "failed": 0}
verdict: EVIDENCE_CONSISTENT      false_success: 0      exit 0
```

Cuatro defectos de la propia evidencia se encontraron **por este verificador** y se corrigieron
(no se relajó ninguna comprobación): clave `name` vs `check` en los checks del trace; selección de
ventana por ISO truncado a segundos (perdía una barra con sellos `…999 ms`); referencia de slippage
por símbolo en vez de por decisión; y estado de paper heredado de un intento anterior que convertía
el arranque en `RECOVERED`.

## 9. Tests

| Suite | Resultado | Exit |
| --- | --- | --- |
| `tests/unit/autonomous` | 267 passed | 0 |
| `tests/unit/paper` | 57 passed | 0 |
| `tests/unit/scanner` | 123 passed | 0 |
| `tests/unit/market_data` | 103 passed | 0 |
| `tests/unit/config` | 50 passed | 0 |
| `tests/unit/risk` | 117 passed, **2 failed** | 1 |
| `tests/unit/research` | 1727 passed, **88 failed, 14 errors**, 30 skipped | 1 |

Salidas crudas en `raw/tests/*.stdout.txt`. Los fallos **no** son de este cambio:

- `risk`: `test_futures_independent_verifier.py` (RFC-048V) — fichero y `data/rfc048/*` comprometidos,
  sin relación con ningún módulo que este WP importe.
- `research`: dependen de artefactos generados y no versionados
  (`reports/profitability_gate035/FINAL_REPORT.json` y similares); en un checkout limpio no existen.

`ruff check` sobre los 6 scripts nuevos: **limpio**.

## 10. Comandos (todos reproducibles)

```bash
uv run python scripts/wp_prd001_paper_reachability.py --out <ev>/raw
uv run python scripts/wp_prd001_data_quality.py     --out-dir <ev>/raw
uv run python scripts/wp_prd001_campaign.py --cycles 3 --timeframe 1h --assets BTC,ETH,SOL \
    --config-dir config/realdata --run-id run-a-1h --run-root <ev>/raw/runs \
    --state-path <ev>/raw/paper_state_run_a.json --audit-jsonl <ev>/raw/DATA_ACCESS_run_a.jsonl
uv run python scripts/wp_prd001_campaign.py --cycles 3 --interval 300 --timeframe 5m ... --run-id run-b-5m
uv run python scripts/wp_prd001_controlled_exec.py --out <ev>/raw
uv run python scripts/wp_prd001_report.py --evidence <ev>
uv run python scripts/wp_prd001_verify.py --evidence <ev>
```

## 11. Defectos y observaciones (no maquillados)

1. **Sin admisión no hay ejecución por mercado.** 0/18 entradas admitidas; el coste medido del modelo
   (22.8–23.8 bps round trip) supera cualquier gross registrado (máximo +6.28 bps en `volatility@1h`).
   No es un bug del runtime: es el resultado económico.
2. **`paper ⇒ sandbox` impide usar el feed real desde el connector.** Con `sandbox: true` el feed es
   testnet (simulado). Validar mercado real exige la costura de inyección (lo que hace este WP) o un
   proveedor de datos de primera clase en el runtime. Recomendación, no implementada aquí.
3. **Frescura medida desde la apertura**: en 5m la ventana útil es ~2.5 min por cierre; un ciclo
   desalineado produce `stale_context` sin que haya nada malo en los datos.
4. **Orden de sincronización de riesgo**: `_sync_risk_positions()` corre antes de `_reconcile()`, así
   que una posición cerrada por SL/TP en el mismo ciclo sigue contando para `max_open_positions` y
   bloquea entradas nuevas durante ese ciclo. Conservador (fail-closed), pero retrasa la re-entrada.
5. **`broker.closed_trades_rows()` no expone nocional ni comisiones**, así que verificar fees obliga a
   leer el dataclass. La evidencia lo hizo así en lugar de confiar en el resumen del broker.

## 12. Siguiente bloqueo operativo

`EXECUTION_PASS` desde señales de mercado sigue **NOT_TESTED**, y no por defecto del runtime sino
porque **ninguna estrategia está admitida** y ninguna supera el coste. El siguiente paso real no es
más infraestructura: es una estrategia con edge bruto > ~23 bps tras costes, o una revisión
económica explícita del modelo de costes por parte de research/risk. Mientras eso no exista, este
WP no puede —ni debe— declarar `PAPER_RUNTIME_VALIDATED` completo.
