# STRATEGY-DISCOVERY-V3 — marco y pre-registro

> Fase: STRATEGY-DISCOVERY-V3 · Fecha: 2026-09-26 · HEAD base: `a910f8d`
> Objetivo: encontrar ≥1 hipótesis con edge neto real, o cerrar con
> `STRATEGY_DISCOVERY_V3_NO_EDGE_FOUND`. Nunca relajar criterios para
> conseguir candidatas (§1). Cadena obligatoria: HYPOTHESIS → GROSS EDGE →
> COST SURVIVAL → VALIDATION → OOS → ROBUSTNESS → ADMISSION → PAPER.

## 0. Estado heredado

- RUNTIME: sano (V2 cerrado: 9.29h reales, 99.98% HEALTHY, 0 duplicaciones,
  recovery real tras suspensión de 8.4h). Runtime no es el problema.
- STRATEGY: 6/6 familias REJECT (PF<1 neto tras costes BASE). trend OOS PF
  0.94 era la menos mala.
- MULTI-STRATEGY: bloqueado por evidencia (no por wiring).

## 1. Pre-registro (§11) — escrito ANTES de ejecutar los backtests de candidatas

Este documento fija hipótesis, invalidaciones y criterios antes de ver
cualquier resultado de candidata nueva. Los resultados viven en
STRATEGY_DISCOVERY_V3_RESULTS.md/.json; el veredicto, en
STRATEGY_DISCOVERY_V3_ADMISSION.md/.json.

### D-01 · Confirmación por barra completada (timeframe superior) [Plan A]

- HYPOTHESIS: la señal 5m de las familias es mayormente ruido de alta
  frecuencia (MFE≈MAE en trend: 0.71% vs 0.73%); elevar el horizonte de
  decisión (15m/30m/1h) aumenta el signal/noise por decisión y reduce el
  turnover, de modo que el MISMO mecanismo cruza de gross≤0 a gross>0.
- MARKET MECHANISM: persistencia intradía multi-hora > persistencia
  multi-minuto; el coste round-trip (~10.4-12 bps) es fijo por trade, así
  que menos trades de mayor expectancy bruta es el palo estructural.
- EXPECTED REGIME: tendido directional (bull o bear) dentro de cada ventana.
- ASSETS: BTC, ETH, SOL · TIMEFRAMES: 15m, 30m, 1h (5m ya auditado=REJECT).
- ENTRY/EXIT: los de cada familia runtime (sin cambiar contratos) — el
  experimento es de HORIZONTE, no de señales nuevas.
- INVALIDATION: gross expectancy ≤ 0 en ≥2 de 3 TFs superiores agregado
  (Filter 1) → la hipótesis "el horizonte lo salva" muere para esa familia.
- EXPECTED HOLDING: mayor que a 5m (por construcción del TF).
- EXPECTED TURNOVER: ~1/3, 1/6, 1/12 del 5m respectivamente.
- KNOWN RISKS: menos trades → muestras pequeñas por split; riesgo de que el
  "edge" aparente sea un artefacto de poc operaciones (mitigación: umbral
  ≥30 trades OOS para cualquier afirmación; §24 escepticismo aumentado).

### D-02 · Reversión a la media tras excursión extrema vol-normalizada [Plan B]

- HYPOTHESIS: tras un movimiento adverso extremo normalizado por volatilidad
  (z-score del retorno corto vs ATR), el precio revierte parcialmente en el
  siguiente horizonte corto; la reversión supera los costes solo cuando la
  excursión es suficientemente rara (umbral fijo pre-registrado: |z| ≥ 2.0,
  medido sobre 20 barras con ATR14, ambos estándar y NO optimizados).
- MARKET MECHANISM: microestructura de liquidez — liquidaciones/cascadas
  breves sobre-extienden el precio; makers/vendedores de liquidez capturan
  el rebate de la reversión.
- EXPECTED REGIME: alta volatilidad intradía, lateral o sin tendencia fuerte.
- ASSETS: BTC, ETH, SOL · TIMEFRAME: 15m (compromiso: suficiente población
  de eventos extremos sin ruido de 5m).
- ENTRY: close < close_previo - 2.0*ATR14 (LONG) o simétrico (SHORT),
  tras 20 barras mínimas. EXIT: TP = 1.0*ATR14 desde entrada,
  SL = 1.5*ATR14, time-stop 24 barras (6h) — todos pre-registrados.
- INVALIDATION: gross expectancy ≤ 0 sobre los eventos (Filter 1), o
  win_rate de reversión ≤ 50% - 2σ binomial sobre n≥100 eventos.
- EXPECTED HOLDING: 1-6h · EXPECTED TURNOVER: bajo (eventos raros).
- KNOWN RISKS: en cripto la reversión puede estar ausente (momentum
  dominante); el coste exacto del entry en cascada (slippage real > modelo).

### D-03 · Compresión de rango → expansión (breakout direccional) [Plan C]

- HYPOTHESIS: N barras de compresión (ancho de rango decreciente, vol bajo)
  preceden expansión direccional; entrar EN la dirección de la ruptura con
  confirmación de cierre (no intrabar) filtra las falsas rupturas y el
  payoff de la expansión supera el coste.
- MARKET MECHANISM: acumulación/distribución — vol clustering: la vol baja
  agrupada se sigue de vol alta (propiedad GARCH empírica estable).
- EXPECTED REGIME: cualquier; el patrón define su propio timing.
- ASSETS: BTC, ETH, SOL · TIMEFRAME: 30m (balance población/calidad).
- ENTRY: ruptura del máximo/mínimo de las últimas 12 barras tras NR7-like
  (rango de la barra < rango medio/2), confirmada por CIERRE fuera del
  rango. EXIT: TP 1.5×rango roto, SL en el lado opuesto del rango.
- INVALIDATION: gross ≤ 0 (Filter 1) o las rupturas confirmadas no difieren
  de las no confirmadas en expectancy bruta (hipótesis de confirmación muerta).
- EXPECTED HOLDING: horas · EXPECTED TURNOVER: muy bajo.
- KNOWN RISKS: pocos eventos (puede no alcanzar n≥30 OOS por activo);
  si no llega a muestra, queda RESEARCH_REQUIRED sin promoción (§26).

### D-04 · Momentum relativo cross-sectional BTC/ETH/SOL [Plan D]

- HYPOTHESIS: el activo con momentum 24h relativo más fuerte (retorno
  normalizado por su propia vol) continúa superando a los otros en el
  siguiente horizonte de 12-24h; long del líder (o long líder/short laggard
  conceptualmente) captura el spread.
- MARKET MECHANISM: flujo institucional rotativo entre majors; el capital
  entra primero por BTC y rota a ETH/SOL — el ranking relativo anticipa
  continuidad.
- EXPECTED REGIME: tendido idiosincrático entre activos (dispersión alta).
- ASSETS: BTC, ETH, SOL (los 3, señales RELATIVAS) · TIMEFRAME: 1h.
- ENTRY: rank 24h-return/vol cada barra; LONG al líder si su z-rel > +1.0
  (pre-registrado). EXIT: TP 1.0%, SL 1.0%, time-stop 24h, o pérdida de
  liderazgo (rank change).
- INVALIDATION: gross ≤ 0 del long-líder vs baseline buy-all-equal.
- EXPECTED TURNOVER: bajo-medio.
- KNOWN RISKS: correlación estructural entre majors reduce el spread
  aprovechable; el runtime actual es single-asset-long/short — esto sería
  solo long del líder (sin pierna short) en paper.

### D-05 · Régimen point-in-time como filtro (no como estrategia) [Plan E]

- HYPOTHESIS: la expectancy bruta de las familias existentes está
  concentrada en regímenes específicos (p.ej. trend solo rinde en
  ADX-alto/vol-media); condicionar la SEÑAL al régimen PIT (medido con
  ventanas ≥50 barras, sin lookahead) puede rescatar edge neto positivo
  aunque el global sea negativo.
- MARKET MECHANISM: el edge de momentum/tendencia es regime-dependent por
  literatura; ejecutar la señal en el régimen equivocado invierte su signo.
- ASSETS: BTC, ETH, SOL · TIMEFRAMES: 15m/30m (post D-01).
- ENTRY/EXIT: los de la familia, habilitados solo en su régimen.
- INVALIDATION: si ningún (familia × régimen) muestra gross>0 en DEV y
  sobrevive a VAL, la hipótesis muere — NO re-segmentar regímenes buscando
  positivos (evitar garden of forking paths).
- KNOWN RISKS: múltiples comparaciones implícitas (familia×régimen) — se
  registra el número exacto de celdas evaluadas (§24) y el criterio OOS
  exige el mismo régimen sin re-etiquetado.

### D-06 · Exit research dirigido por MFE/MAE (solo si hay señal viva) [Plan F]

- HYPOTHESIS: si alguna variante muestra señal direccional real
  (gross>0) pero exit pobre (MFE >> realizado), un time-stop o trailing
  (pre-registrado por hipótesis, sin grid) recupera el edge.
- GATE: esta línea SOLO se activa con evidencia de D-01..D-05 con gross>0
  y MFE/MAE asimétrico a favor. Si no hay señal viva, no se ejecuta (§21).
- KNOWN RISKS: optimización de exits = overfitting barato; por eso exige
  señal previa y una sola variante por hipótesis.

## 2. Transaction-cost barrier (§5) — marco de referencia

Coste round-trip BASE = fees 10 bps + slippage 2 bps = **12 bps** (2X_COST
24 bps, STRESSED 32 bps). Break-even expectancy por trade = 12 bps del
notional; a TP fijo 0.75% eso exige WR·payoff > 12/75 de cadatrade.
El experimento ZERO_COST separa señal (gross) de cost drag (§17).
Detalles numéricos por TF en RESULTS.

## 3. Splits y datos (§15-16)

- W1-W4 (2026-03..06) DEV · W5-W6 (07-08) VAL · W7 (09-01..24) OOS.
- 3 activos × 7 ventanas mensuales, 5m fuente + resamples deterministas
  15m/30m/1h (sanity-checked contra la fuente). El día del paper run
  (25-09) queda fuera de todas las ventanas (OOS limpio vs V2).
- No se mueven fechas bajo ningún resultado (§15).

## 4. Presupuesto de cómputo (§41)

Familias runtime 6 × TFs {15m,30m,1h} × 3 escenarios BASE/ZERO (audit) ≈
54 simulaciones de datasets reducidos + candidatas D-01..D-05 con variantes
pre-registradas (1 por hipótesis, sin grids) ≈ <100 simulaciones totales.
Registro de experimentos en STRATEGY_DISCOVERY_V3_EXPERIMENTS.md.

## 5. Criterios de admission (§25) — SIN CAMBIOS

Los de docs/STRATEGY_ADMISSION_CRITERIA.md (pre-registrados en c1ffbaa,
antes de resultados): ≥100 trades y ≥30 OOS, net>0 y expectancy>0 BASE,
PF>1, OOS net>0 y PF>1, PF_DEV>0.8, DD≤10%, 2X_COST PF>0.9, ninguna ventana
>60% del net positivo, sin NEGATIVE_ROBUST. ZERO_COST nunca admite.
