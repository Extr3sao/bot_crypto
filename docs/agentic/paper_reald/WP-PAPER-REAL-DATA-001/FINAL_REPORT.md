# FINAL_REPORT — WP-PAPER-REAL-DATA-001

**Objetivo**: demostrar que Trading Agentic Portable procesa datos de mercado **reales**, evalúa
estrategias existentes, produce decisiones trazables y ejecuta su ciclo PAPER, con verificación
independiente. Sin arquitectura nueva, sin estrategia nueva, sin tocar `main`.

| Veredicto | Valor | Base |
| --- | --- | --- |
| `RUNTIME_PASS` | **SÍ** | 3 campañas, exit 0, hash chain intacta, contratos y reconciliación ejercidos |
| `DECISION_PASS` | **SÍ** | 18 decisiones sobre datos reales, todas con motivo explícito, verificador `PASS` 18/18 |
| `EXECUTION_PASS` | **TEST_ONLY** | ruta de órdenes validada con fixture etiquetado; desde señales de mercado: `NOT_TESTED` |
| `TRADING_PERFORMANCE` | **NOT_ASSESSED** | ninguna estrategia admitida; sin rentabilidad que afirmar |
| `PAPER_RUNTIME_VALIDATED` | **NO (parcial)** | falta ejecución *desde señales de mercado*; ver §6 |

---

## 1. Qué se ejecutó de verdad

| Campaña | Datos | Ciclos | Decisiones | Órdenes | Ventanas distintas |
| --- | --- | --- | --- | --- | --- |
| RUN-A (1h) | públicas de producción, sin auth | 3 | 9 `NO_TRADE` | 0 | 1 (misma barra, 3 ciclos) |
| RUN-B (5m) | ídem | 3 (300 s) | 9 `NO_TRADE` | 0 | **3** (16:10, 16:15, 16:20) |
| RUN-C (5m, test) | ídem para precios | 2 | 3 `TRADE_PAPER` + 3 `RISK_VETO` | **3** | 2 |

Ninguna decisión fue forzada: en RUN-A/B el motor seleccionó estrategias reales del ledger
(`breakout@1h`, `ema_crossover@1h`, `ema_crossover@5m`, `momentum@5m`, `trend@5m`) y las rechazó por
economía, no por avería.

## 2. Lo que bloquea todo, dicho sin rodeos

`config/strategy_admission.json` **no admite ninguna estrategia para PAPER** (0 de 18). Además, el
coste que el propio modelo aplica en cada ciclo es de **22.8–23.8 bps round trip**, mientras que el
mejor gross registrado en el ledger es **+6.28 bps** (`volatility@1h`). Con esos números, la ruta de
órdenes es inalcanzable por diseño: no es un defecto de software, es el resultado económico.

Por eso `EXECUTION_PASS` se declara **TEST_ONLY**: se probó la ruta completa
(Market Data → Decision → Risk → PaperBroker → Reconciliation) con precios reales y con **dos
entradas sustituidas y declaradas** — un ledger fixture `TEST_ONLY` y una señal determinista — nunca
presentadas como validación de mercado.

## 3. La ruta de órdenes, medida

- 3 fills de 500 USDT (tope por activo 1 000), comisión 0.25 por lado = 5 bp del nocional (recalculada).
- Entrada con slippage de 1 bp sobre la referencia del trace (recalculado, no leído del log).
- Cierre por `take_profit` con **precios reales** en la barra siguiente: bruto +4.9495, neto
  **+4.4495** por posición; equity 10 000 → **10 013.3485** (= Σ PnL neto, exacto).
- Reconciliación `CONSISTENT` tras operar y `RECOVERED` al recargar el estado, con el equity intacto.
- 13/13 invariantes de la ruta en verde.

Ningún precio de salida fue sintético: el cierre forzado a precio de test estaba previsto y **no fue
necesario**.

## 4. Datos reales: procedencia y PIT

- Fuente: `api.binance.com/api/v3/klines` (público), 199 barras cerradas por símbolo, 0 gaps, 0
  duplicados, 0 violaciones OHLCV, 1 barra en formación descartada por símbolo.
- **Cross-check de dos caminos de cliente** (HTTP crudo vs CCXT) sobre las barras cerradas: 199/199
  idénticas. La barra en formación se excluye de la comparación a propósito: cambia entre dos
  lecturas y compararla marcaría el progreso del mercado como defecto de datos.
- PIT: cada traza guarda `pit_slice_exact` del verificador interno y `market_time_ms ≤
  decision_time_ms`; el verificador externo lo recalcula y además **re-descarga** la ventana de 120
  barras y compara el digest registrado. 43/43 comprobaciones, `false_success: 0`.

## 5. Aislamiento y gobernanza

- Worktree `ff-wt-prd001`, rama `paper/reald-data-001`; `main` **intacto**.
- `config/` sin cambios (verificado por el verificador vía `git status`). Límites de riesgo, ledger
  comprometido y pins de EXP004A sin tocar.
- **Cero credenciales**: no existe `.env`, no hay variables de API en el entorno, y el journal de
  accesos marca `authenticated: false` en las 3 campañas.
- **Cero sesión de venue**: los logs no contienen ni un `multi_exchange.call.*`. La fuente inyectada
  solo lee rutas públicas. Ninguna orden live, ningún endpoint de órdenes.

## 6. Por qué `PAPER_RUNTIME_VALIDATED` NO se declara

La definición exige una campaña completa con datos reales verificables que atraviese todos los
componentes y cierre con reconciliación y evidencia independiente. Lo conseguido:

- datos reales → decisión → riesgo → reconciliación: **sí, dos veces** (1h y 5m, multi-vela);
- decisión → riesgo → **ejecución** → reconciliación: **sí, pero con señal de fixture**.

Falta el eslabón exacto que el propio sistema bloquee: una estrategia admitida que emita señales de
mercado. Declarar `PAPER_RUNTIME_VALIDATED` ahora sería FALSE_SUCCESS.

## 7. Defectos y hallazgos (todos abiertos, ninguno maquillado)

1. **`paper ⇒ sandbox`**: el runtime no puede componer un feed de producción en PAPER. Validar
   mercado real obliga a la costura de inyección (lo que hace este WP). Propuesta: proveedor
   `market_data.provider = public_rest` de primera clase; hoy no existe y no se ha inventado.
2. **Frescura medida desde la apertura** de la barra: en 5m la ventana útil es ~2.5 min tras cada
   cierre; un ciclo desalineado da `stale_context` con datos sanos. Requiere cadencia alineada.
3. **`_sync_risk_positions()` antes de `_reconcile()`**: una posición cerrada por SL/TP en el mismo
   ciclo sigue contando para `max_open_positions` y bloquea entradas nuevas ese ciclo (conservador,
   pero retrasa la re-entrada). Observado en RUN-C: 3 `RISK_VETO` por *Max open positions reached (3)*
   con el libro ya plano.
4. **`closed_trades_rows()` omite nocional y comisiones**: verificar fees exige leer el dataclass.
5. **Cuatro defectos de mi propia evidencia**, encontrados por el verificador y corregidos sin
   relajar comprobaciones: clave `name` vs `check`; ventana PIT seleccionada por ISO truncado a
   segundos (perdía una barra con sellos `…999 ms`); referencia de slippage por símbolo en vez de por
   decisión; estado de paper heredado de un intento anterior.

## 8. Tests

| Suite | Resultado | Exit |
| --- | --- | --- |
| autonomous / paper / scanner / market_data / config | 267 / 57 / 123 / 103 / 50 — **600 verdes** | 0 |
| risk | 117 verdes, **2 fallos preexistentes** (RFC-048V, ficheros ajenos a este WP) | 1 |
| research | 1727 verdes, **88 fallos + 14 errores preexistentes** (dependen de `reports/**` generados y no versionados) | 1 |

`ruff check` limpio en los 6 scripts nuevos. Los fallos se declaran, no se silencian.

Nota de honestidad: correr la suite `research` reescribe artefactos versionados en `data/st6/`; se
revirtieron a su estado de `HEAD` para no ensuciar el diff.

## 9. Commits

- Implementación + campañas + evidencia: `2a3ee67` *(este rama)*.
- Informes y registro del verificador: commit inmediatamente posterior en `paper/reald-data-001`
  (contiene este fichero, `RUN_REPORT.md`, `RUN_REPORT.json` y `VERIFIER.json`).

La convención del repo es no nombrar en un informe el commit que lo contiene; el hash exacto se
resuelve con `git log -1 --format=%H -- docs/agentic/paper_reald`.

## 10. Próximo bloqueo operativo

No es infraestructura: es **economía**. Hace falta una estrategia con edge bruto > ~23 bps tras
costes, o una revisión explícita del modelo de costes por research/risk con evidencia nueva. Hasta
entonces `EXECUTION_PASS` desde señales de mercado seguirá `NOT_TESTED` y este WP no puede declarar
`PAPER_RUNTIME_VALIDATED`.
