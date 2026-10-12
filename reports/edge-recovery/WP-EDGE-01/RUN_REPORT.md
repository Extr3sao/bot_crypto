# RUN REPORT - WP-EDGE-01 (estrategias operativas y resultados economicos)

| | |
|---|---|
| run_id | `wp-edge-01-campaign` |
| HEAD al ejecutar | `1a0a6c85299ca09ac354d3bcf797b34a806adff2` |
| rama | `agent/edge-recovery/WP-EDGE-00-baseline` |
| arbol sucio al ejecutar | `True` |
| huella del código ejecutado (sha256) | `2ccce6dc6019fe9c04d53d3c1c38e52b7721c14a82ef77fe5c6f6c9e0f63f4fe` |
| params_hash | `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77` |
| modo | backtest determinista sobre datos históricos locales; 0 órdenes, 0 claves, 0 red |
| entrypoint | `scripts/edge01_run.py` |
| generado | 2026-10-12T12:02:50.297125+00:00 |

> El `HEAD` de arriba es lo que la máquina tenía al medir; cuando el árbol
> está sucio el identificador de esta medida es la **huella del código**
> (sha256 de los módulos de `research/edge01` y sus dos entrypoints), no el commit.


## 1. Qué se ejecutó

Tres candidatos del RFC más una ablación, sobre los corpus locales del repo,
con los costes del modelo del propio proyecto (`COST_MODEL_V3`, escenario
admission de Binance spot taker), splits preinscritos DEV/VAL/OOS y tres
escenarios de coste derivados del mismo plano (BASE, 2X_FEES, ADVERSE).

## 2. Datos y procedencia

| candidato | timeframe | barras | desde | hasta | sha256 del corpus |
|---|---|---|---|---|---|
| edge_intra_01 | 15m | 70703 | 2024-10-01 | 2026-10-07 | `cd1d2ea256a97f7c…` |
| edge_intra_01 | 15m | 70703 | 2024-10-01 | 2026-10-07 | `b8fd5744cc66f635…` |
| edge_intra_01 | 15m | 70703 | 2024-10-01 | 2026-10-07 | `72a268137cbe944b…` |
| edge_intra_02 | 15m | 70703 | 2024-10-01 | 2026-10-07 | `cd1d2ea256a97f7c…` |
| edge_intra_02 | 15m | 70703 | 2024-10-01 | 2026-10-07 | `b8fd5744cc66f635…` |
| edge_intra_02 | 15m | 70703 | 2024-10-01 | 2026-10-07 | `72a268137cbe944b…` |
| edge_intra_02_no_fvg | 15m | 70703 | 2024-10-01 | 2026-10-07 | `cd1d2ea256a97f7c…` |
| edge_intra_02_no_fvg | 15m | 70703 | 2024-10-01 | 2026-10-07 | `b8fd5744cc66f635…` |
| edge_intra_02_no_fvg | 15m | 70703 | 2024-10-01 | 2026-10-07 | `72a268137cbe944b…` |
| edge_trend_01_4h | 4h | 15665 | 2019-01-01 | 2026-02-28 | `f4d16c3664c142d1…` |
| edge_trend_01_4h | 4h | 15665 | 2019-01-01 | 2026-02-28 | `365046d4738aa7b1…` |
| edge_trend_01_4h | 4h | 12153 | 2020-08-11 | 2026-02-28 | `847d8eb45eafebd8…` |
| edge_trend_01_1d | 1d | 2596 | 2019-01-01 | 2026-02-28 | `f4d16c3664c142d1…` |
| edge_trend_01_1d | 1d | 2596 | 2019-01-01 | 2026-02-28 | `365046d4738aa7b1…` |
| edge_trend_01_1d | 1d | 2017 | 2020-08-12 | 2026-02-28 | `847d8eb45eafebd8…` |

## 3. Método

- Splits fijados antes de medir: **intraday** DEV 2024-10-01..2025-06-30, VAL 2025-07-01..2025-12-31, OOS 2026-01-01..2026-10-07; **trend** DEV 2019-01-01..2023-12-31, VAL 2024-01-01..2024-12-31, OOS 2025-01-01..2026-02-28
- Reglas congeladas: `params_hash=d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77`; ningún parámetro se
  ajustó sobre VAL ni OOS.
- Costes: plano del modelo del proyecto, escenario `BINANCE_SPOT_STANDARD_TAKER`; el componente contractual es la comisión y el resto es modelo de microestructura.
- Tamaño: límites de `config/risk.yaml` tal cual (riesgo por operación, tope por
  activo, exposición total, nótional mín/máx, máximo de operaciones diarias,
  cooldown por pérdidas consecutivas y kill switch por drawdown).
- Baseline: buy & hold del mismo activo, misma ventana, mismo plano de coste, una
  sola operación (entrada en el primer open, salida en el último close).
- Causalidad: las decisiones se toman con el cierre de la barra y se ejecutan al
  open de la barra siguiente; el pivote/FVG sólo se usa una vez confirmado.

## 4. Resultados por candidato

| candidato | split | trades | net (BASE) | net (ADVERSE) | veredicto | potencia |
|---|---|---|---|---|---|---|
| edge_intra_01 | DEV | 290 | -496.43 | -496.17 | - | - |
| edge_intra_01 | VAL | 344 | -479.18 | -504.82 | - | - |
| edge_intra_01 | OOS | 63 | -94.81 | -125.04 | REJECT | powered (oos n=63 >= 30) |
| edge_intra_02 | DEV | 135 | -189.88 | -256.89 | - | - |
| edge_intra_02 | VAL | 72 | -102.58 | -171.88 | - | - |
| edge_intra_02 | OOS | 14 | -12.63 | -30.80 | REJECT | underpowered (oos n=14 < 30) |
| edge_intra_02_no_fvg | DEV | 270 | -500.83 | -501.75 | - | - |
| edge_intra_02_no_fvg | VAL | 207 | -289.00 | -447.25 | - | - |
| edge_intra_02_no_fvg | OOS | 45 | -69.10 | -84.72 | REJECT | powered (oos n=45 >= 30) |
| edge_trend_01_4h | DEV | 223 | 1,921.18 | 1,682.98 | - | - |
| edge_trend_01_4h | VAL | 58 | 4.53 | -58.76 | - | - |
| edge_trend_01_4h | OOS | 52 | 208.01 | 146.89 | INSUFFICIENT_EVIDENCE | powered (oos n=52 >= 30) |
| edge_trend_01_1d | DEV | 39 | 926.51 | 905.38 | - | - |
| edge_trend_01_1d | VAL | 20 | 86.54 | 76.40 | - | - |
| edge_trend_01_1d | OOS | 13 | -118.60 | -126.57 | INSUFFICIENT_EVIDENCE | underpowered (oos n=13 < 30) |

### Veredictos y por qué

- **edge_intra_01** → `REJECT` (powered (oos n=63 >= 30)). Net por ventana (BASE): DEV=-496.4298, VAL=-479.1833, OOS=-94.8077.
  - oos net -94.81 USDT <= 0 after costs
  - oos expectancy -1.5049 USDT/trade <= 0
  - oos has 0 profitable regime(s), fewer than the required 1
  - oos net turns negative under 2x fees (-133.20 USDT): no cost margin
  - net negative in every window (DEV=-496.43, VAL=-479.18, OOS=-94.81 USDT)
- **edge_intra_02** → `REJECT` (underpowered (oos n=14 < 30)). Net por ventana (BASE): DEV=-189.8769, VAL=-102.5803, OOS=-12.6286.
  - oos net -12.63 USDT <= 0 after costs
  - oos expectancy -0.902 USDT/trade <= 0
  - oos has 0 profitable regime(s), fewer than the required 1
  - oos net turns negative under 2x fees (-31.50 USDT): no cost margin
  - net negative in every window (DEV=-189.88, VAL=-102.58, OOS=-12.63 USDT)
  - oos trades 14 < required 30 (unpowered sample)
- **edge_intra_02_no_fvg** → `REJECT` (powered (oos n=45 >= 30)). Net por ventana (BASE): DEV=-500.8327, VAL=-289.0006, OOS=-69.0987.
  - oos net -69.10 USDT <= 0 after costs
  - oos expectancy -1.5355 USDT/trade <= 0
  - oos has 0 profitable regime(s), fewer than the required 1
  - oos net turns negative under 2x fees (-82.83 USDT): no cost margin
  - net negative in every window (DEV=-500.83, VAL=-289.00, OOS=-69.10 USDT)
- **edge_trend_01_4h** → `INSUFFICIENT_EVIDENCE` (powered (oos n=52 >= 30)). Net por ventana (BASE): DEV=1921.1792, VAL=4.5253, OOS=208.0056.
  - the largest single trade is 0.80 of the oos net
- **edge_trend_01_1d** → `INSUFFICIENT_EVIDENCE` (underpowered (oos n=13 < 30)). Net por ventana (BASE): DEV=926.5089, VAL=86.5381, OOS=-118.6003.
  - oos net -118.60 USDT <= 0 after costs
  - oos expectancy -9.1231 USDT/trade <= 0
  - oos has 0 profitable regime(s), fewer than the required 1
  - oos net turns negative under 2x fees (-125.16 USDT): no cost margin
  - oos trades 13 < required 30 (unpowered sample)

## 5. Por qué no operó (motivos de rechazo, OOS/BASE)

El embudo completo, del universo a la orden. Un motivo listado aquí es una
decisión del candidato o del riesgo, no un error de datos.

- edge_intra_01: candidate:trend_filter_fail=2282, candidate:volume_filter_fail=309, candidate:level_already_traded=102, candidate:rr_below_minimum=10, risk:risk_loss_cooldown=8, candidate:stop_too_wide=5, candidate:reward_below_cost=2
- edge_intra_02: candidate:trend_filter_fail=2264, candidate:volume_filter_fail=307, candidate:retest_not_confirmed=171, candidate:no_confirmed_fvg=118, candidate:level_already_traded=86, candidate:no_retest_confirmed=64, candidate:rr_below_minimum=4, candidate:reward_below_cost=3
- edge_intra_02_no_fvg: candidate:trend_filter_fail=2273, candidate:volume_filter_fail=310, candidate:retest_not_confirmed=119, candidate:level_already_traded=81, candidate:no_retest_confirmed=33, candidate:rr_below_minimum=27, candidate:reward_below_cost=16, risk:risk_loss_cooldown=3
- edge_trend_01_4h: candidate:trend_filter_fail=205
- edge_trend_01_1d: candidate:trend_filter_fail=27

Señales impresas por el candidato (antes de riesgo y ejecución): edge_intra_01=85, edge_intra_02=16, edge_intra_02_no_fvg=53, edge_trend_01_4h=203, edge_trend_01_1d=38

## 6. Comparación con el baseline

| candidato | ventana | net estrategia (BASE) | retorno de la estrategia | buy & hold BTC / ETH / SOL |
|---|---|---|---|---|
| edge_intra_01 | DEV | -496.43 | -4.96% | 70.80% / -3.94% / 0.35% |
| edge_intra_01 | VAL | -479.18 | -4.79% | -17.70% / 19.07% / -19.57% |
| edge_intra_01 | OOS | -94.81 | -0.95% | -2.60% / -9.39% / -3.49% |
| edge_intra_02 | DEV | -189.88 | -1.90% | 70.80% / -3.94% / 0.35% |
| edge_intra_02 | VAL | -102.58 | -1.03% | -17.70% / 19.07% / -19.57% |
| edge_intra_02 | OOS | -12.63 | -0.13% | -2.60% / -9.39% / -3.49% |
| edge_intra_02_no_fvg | DEV | -500.83 | -5.01% | 70.80% / -3.94% / 0.35% |
| edge_intra_02_no_fvg | VAL | -289.00 | -2.89% | -17.70% / 19.07% / -19.57% |
| edge_intra_02_no_fvg | OOS | -69.10 | -0.69% | -2.60% / -9.39% / -3.49% |
| edge_trend_01_4h | DEV | 1,921.18 | 19.21% | 1036.81% / 1633.43% / 3289.28% |
| edge_trend_01_4h | VAL | 4.53 | 0.05% | 118.26% / 46.03% / 86.30% |
| edge_trend_01_4h | OOS | 208.01 | 2.08% | -29.85% / -42.48% / -56.92% |
| edge_trend_01_1d | DEV | 926.51 | 9.27% | 1039.71% / 1631.80% / 2976.50% |
| edge_trend_01_1d | VAL | 86.54 | 0.87% | 120.78% / 45.93% / 85.67% |
| edge_trend_01_1d | OOS | -118.60 | -1.19% | -28.60% / -41.28% / -55.55% |

## 7. Defectos encontrados al ejecutar (y corregidos aquí)

| id | síntoma | causa | corrección | evidencia |
|---|---|---|---|---|
| `DEF-EDGE01-01` | EDGE-TREND-01 printed signals and never traded one of them. | A candidate exiting on a trailing stop has no fixed objective, so the reward/risk gate compared the modelled objective with the very stop distance it is derived from: unsatisfiable by construction. | min_rr=None for that candidate; it is judged by whether its modelled objective clears cost, which is the only promise its exit rule makes. | scripts/edge01_verify.py check EDGE_TREND_01_TRADES_PRESENT |
| `DEF-EDGE01-02` | Every long window was truncated by the 5% drawdown kill switch after its first trade; the equity curve jumped up on entry and fell on exit. | Opening a position never debited cash, while equity added the position's mark-to-market value: an open position was counted twice (once as cash, once as exposure), so the recorded peak equity was fake. | Entry debits qty x fill, exit credits proceeds net of exit fees, and the trade's net is the difference; final_equity == start + sum(net) holds to the cent. | scripts/edge01_verify.py checks EQUITY_CONSERVATION and EQUITY_CURVE_MATCHES_TRADES |
| `DEF-EDGE01-03` | With three assets on one clock, a pending breakout on one asset could be aged, expired or fired by another asset's bars. | One candidate object was reused across assets with a single state slot. | Per-series state keyed by the identity of the bar list the caller walked; prepare() is idempotent. | tests/unit/research/test_edge01_pit.py::test_state_is_per_series |
| `DEF-EDGE01-04` | A verdict could not be told apart from an unpowered measurement: the gate returned on the first failing criterion. | Single-reason early return, no sample-size statement. | Every reason is collected; REJECT needs either a powered sample or a net that is negative in all three windows; the verdict carries power and evidence fields. | tests/unit/research/test_edge01_gate_and_artifacts.py |
| `DEF-EDGE01-05` | STRATEGY_RESULTS.json and RUN_REPORT.json were ~86 MB each. | Per-bar working buffers (buy & hold bar returns, the equity curve) were serialised into the published JSON. | _public() strips private keys recursively; the buffers stay in memory. | artefact inventory (bytes) in RUN_REPORT.json |
| `DEF-EDGE01-06` | The 1h trend filter of the two intraday candidates read a 1h bar whose close had not happened yet: up to 45 minutes of look-ahead. | OHLCVBar.ts is the bar's OPEN time, but the as-of read compared it directly with the decision instant instead of with the bar's close (open + duration). | last_closed_index takes the context bar's own span and requires ts + span <= decision_ts; ContextSeries passes the span of its timeframe. | tests/unit/research/test_edge01_pit.py::test_context_bar_is_unreadable_until_it_closes |
| `DEF-EDGE01-07` | In TRADES.csv the ablation and the 4h/1d runs were indistinguishable: every row of edge_intra_02_no_fvg said edge_intra_02, and both trend runs said edge_trend_01, so a reader grouping by that column merged runs that must be compared, not merged. | The candidate id inside the signal was unpacked AFTER the run key, so it overwrote it. | The run key is written last and the id that printed the signal is kept in its own ``strategy`` column. | scripts/edge01_verify.py check EQUITY_CONSERVATION (grouped by run key) |
| `DEF-EDGE01-08` | A position still open when the window ended was settled at the last bar of the whole corpus: a 2023 DEV decision could be closed with a 2026 price, and the equity curve (which stops with the window) no longer matched the sum of the trade results. Found by the verifier's EQUITY_CONSERVATION check, not by reading the code. | The end-of-window settlement used bars[-1] instead of the last bar inside the measured window. | The simulator resolves the last in-window bar per asset before walking the timeline and settles there, keeping exit_ts inside the window. | scripts/edge01_verify.py check EQUITY_CONSERVATION; tests/unit/research/test_edge01_pit.py::test_end_of_window_settlement_stays_in_the_window |

## 8. Verificación

Reproducir esta medida (sin red, sin claves):

```bash
.venv/Scripts/python.exe scripts/edge01_run.py --outdir reports/edge-recovery/WP-EDGE-01
.venv/Scripts/python.exe scripts/edge01_verify.py --dir reports/edge-recovery/WP-EDGE-01
.venv/Scripts/python.exe -m pytest tests/unit/research/test_edge01_pit.py \
    tests/unit/research/test_edge01_gate_and_artifacts.py -q
```

- Verificador independiente: `scripts/edge01_verify.py`. Proceso aparte, no
  importa `trading_bot.research.edge01`: re-deriva las métricas desde
  `TRADES.csv` y `EQUITY_CURVE.csv` y aplica sus propios controles negativos
  (incluye mutaciones al CSV para comprobar que cada chequeo puede fallar).
- Tests de causalidad y contabilidad: `tests/unit/research/test_edge01_pit.py`
  (look-ahead en pivotes y FVG, estado por serie, identidad de caja).
- Tests del veredicto y de los artefactos:
  `tests/unit/research/test_edge01_gate_and_artifacts.py`.
- Cada artefacto lleva su sha256 y su tamaño en `RUN_REPORT.json`.
  El backtester no comparte código de decisión con el runtime.
- `INDEPENDENT_VERIFICATION.json` lo produce el verificador DESPUÉS de esta medida, así que no está en el inventario de integridad de arriba: es el resultado de comprobar los otros cinco, no una medida más.
- `TEST_TARGET == RUNTIME_TARGET`: el WP no ha tocado ningún fichero del runtime. Los tests y el runner importan el mismo paquete (`trading_bot.research.edge01`) y el verificador no importa nada del proyecto.

## 9. PAPER

- Integrado: `False` — No candidate reached ADMIT. Wiring a rejected candidate into the PAPER runtime would have made the runtime execute rules whose only measured property is losing money after costs.
- Runtime: src/trading_bot/autonomous/** and the paper pipeline were not modified by this WP: the runtime remains the authority for PAPER and keeps its deterministic risk and execution behaviour.
- No se activa dinero real: 0 órdenes en este WP.

## 10. Hipótesis para la siguiente iteración

- **H1**: The intraday funnel is dominated by trend_filter_fail (>=2000 refusals per window against ~60 trades): the 1h trend filter, not the breakout, is what decides participation. — *Test:* Re-run the frozen EDGE-INTRA-01 with the trend filter removed as an ablation and compare on DEV only; a candidate whose edge lives in a filter must be visible there before VAL is touched.
- **H2**: Gross is negative in DEV/VAL/OOS for the breakouts, so the loss is not only cost: the entry is late relative to the level it breaks. — *Test:* Measure the post-entry MFE/MAE distribution by distance from the broken level. If MFE is already spent at entry, the entry rule has to move earlier (retest or limit at the level), not the stop.
- **H3**: EDGE-TREND-01 4h is positive in DEV (+2,140 USDT) and in OOS (+208), but the OOS net is 80% one trade, so it may be a fat tail rather than an edge. — *Test:* Re-run it on the 1h corpus over 2019-2026 with the same rules and check whether the positive tail repeats across calendar years, with the single-trade share reported per year.
- **H4**: EDGE-TREND-01 has no separate volatility entry filter: volatility only reaches it through the ATR-scaled stop, so it trades quiet and violent regimes alike, and the losses may concentrate where a trend starts from a dead-volatility base. — *Test:* Declare a small grid of minimum-ATR thresholds BEFORE looking at VAL or OOS, pick on DEV only, freeze, then measure once. If the filter cannot be justified on DEV, it does not go in — a filter chosen after the out-of-sample window has been read proves nothing.

## 11. Limitaciones

- The 15m corpus spans 2024-10-01..2026-10-07 and the 1h corpus 2019-01-01..2026-02-28; there is no data outside those windows, so no candidate is measured through 2018 or the 2021 top on 15m.
- No historical order book: the spread is the project's modelled default for the venue, not an observed one. Only the fee component is contractual.
- Slippage and impact come from COST_MODEL_V3 at a fixed 1000 USDT intent; the positions are capped at 500 USDT, so the realised cost is at most the declared one. Both are reported per trade.
- The 4h and 1d corpora are aggregated from 1h, so a full 1-day bar exists only where 24 contiguous 1h bars exist; partial days are dropped, not interpolated.
- Regime labels are computed from the same close series the candidates trade, with no look-ahead, but they are a research taxonomy, not the runtime's.
- Long-only: the runtime trades Binance spot, so no short side was simulated for any candidate even where a down-breakout would be symmetric.
- EDGE-TREND-01 has a trend filter (EMA50 > EMA200 and price above EMA200) but no SEPARATE volatility entry filter: volatility enters the ruleset through the ATR used for the stop distance, the modelled objective and the trailing exit, and through the cost-coverage gate, which grows with the volatility it expects to pay for. Adding a volatility filter now, after seeing the results, would be exactly the post-hoc adjustment this WP refuses to make; it is stated here and carried forward as hypothesis H4 instead.
- No parameter was tuned on VAL or OOS; the rulesets are frozen in candidates.FROZEN_PARAMS with a recorded hash. This also means the candidates are untuned, and an untuned first iteration is expected to lose.
- Nothing here is real money, live performance, or a promise of profitability.

## 12. Artefactos

| artefacto | contenido |
|---|---|
| `STRATEGY_RESULTS.md` | veredictos y métricas por candidato, split y escenario |
| `STRATEGY_RESULTS.json` | lo mismo en JSON, más scope, params congelados y procedencia |
| `TRADES.csv` | una fila por operación cerrada, con costes desglosados y R múltiple |
| `EQUITY_CURVE.csv` | curva de capital por candidato y split (escenario BASE) |
| `RUN_REPORT.json` | metadatos de la medida, integridad (sha256/tamaño) y veredictos |
