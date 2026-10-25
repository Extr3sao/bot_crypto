# STRATEGY_ADMISSION_AUDIT — WP-ECONOMIC-BLOCKER-001

> **Pregunta**: ¿por qué ninguna estrategia opera en PAPER desde señales reales?
>
> **Respuesta corta**: por tres razones independientes, y basta con una sola. La
> lista de `paper_candidates` del artefacto de admisión está **vacía**, así que el
> builder del ledger *no puede* emitir `PAPER_CANDIDATE` para nada. Además, 18 de
> las 24 entradas declaran `sample_trades = 0` y la mejor ventaja bruta medida
> (+8,91 bps) no llega ni a la mitad del coste de ejecución (22,79 bps).
>
> Este documento no declara que el sistema esté roto: declara **qué** falta.

Datos: [`STRATEGY_ADMISSION_AUDIT.json`](STRATEGY_ADMISSION_AUDIT.json),
generado por [`scripts/wp_eco001_admission_audit.py`](../../../../scripts/wp_eco001_admission_audit.py)
sobre el commit auditado. Ningún número de esta página se ha tecleado a mano:
todos salen del JSON o de los ficheros fuente que cita.

---

## 1. Qué lee realmente el runtime

`AdmissionLedger.load()` lee `config/strategy_admission.json`. Su política ante
lo desconocido es **fail closed**: una estrategia que no aparece en el ledger
recibe `AdmissionStatus.UNKNOWN` y `admitted_for_paper = False`. Por tanto:

- el ledger es la única fuente de verdad de admisión;
- si el ledger está vacío o no cuadra con sus fuentes, el resultado es *no operar*,
  nunca *operar a ciegas*.

El ledger tiene 24 entradas: **6 familias × 4 timeframes** (`5m`, `15m`, `30m`,
`1h`). Las 18 entradas de `15m`/`30m`/`1h` son las "18 estrategias" del
enunciado del WP; las 6 de `5m` son las que tienen muestra medida.

El builder reproduce el fichero commiteado entrada por entrada:
`builder_reproduces_committed_entries = true`, 0 entradas distintas.

## 2. Las 24 entradas, con su economía

`cost` es el round-trip de `COST_MODEL_V3` al escenario de admisión
(`BINANCE_SPOT_STANDARD_TAKER`, 1 000 USD, spread por defecto 1,0 bps ≈ el spread
medido más ancho de los tres activos que operó el runtime). `net` = `gross − cost`.

| strategy | gross bps | muestra | cost bps | net bps | veredicto |
| --- | ---: | ---: | ---: | ---: | --- |
| `breakout@5m` | -0.11 | 2426 | 23.79 | -23.90 | NET_NEGATIVE_AFTER_COST |
| `breakout@15m` | -1.82 | 0 | 23.79 | -25.61 | NET_NEGATIVE_AFTER_COST |
| `breakout@30m` | -1.79 | 0 | 23.79 | -25.58 | NET_NEGATIVE_AFTER_COST |
| `breakout@1h` | -0.22 | 0 | 23.79 | -24.01 | NET_NEGATIVE_AFTER_COST |
| `ema_crossover@5m` | -4.56 | 1725 | 23.79 | -28.35 | NET_NEGATIVE_AFTER_COST |
| `ema_crossover@15m` | -1.12 | 0 | 23.79 | -24.91 | NET_NEGATIVE_AFTER_COST |
| `ema_crossover@30m` | -0.73 | 0 | 23.79 | -24.52 | NET_NEGATIVE_AFTER_COST |
| `ema_crossover@1h` | -0.96 | 0 | 23.79 | -24.75 | NET_NEGATIVE_AFTER_COST |
| `mean_reversion@5m` | +1.49 | 3190 | 23.79 | -22.30 | NET_NEGATIVE_AFTER_COST |
| `mean_reversion@15m` | +2.71 | 0 | 23.79 | -21.08 | NET_UNPROVEN_SAMPLE |
| `mean_reversion@30m` | +5.47 | 0 | 23.79 | -18.32 | NET_UNPROVEN_SAMPLE |
| `mean_reversion@1h` | -2.23 | 0 | 23.79 | -26.02 | NET_NEGATIVE_AFTER_COST |
| `momentum@5m` | -1.88 | 2526 | 23.79 | -25.67 | NET_NEGATIVE_AFTER_COST |
| `momentum@15m` | -3.97 | 0 | 23.79 | -27.76 | NET_NEGATIVE_AFTER_COST |
| `momentum@30m` | -2.61 | 0 | 23.79 | -26.40 | NET_NEGATIVE_AFTER_COST |
| `momentum@1h` | -2.33 | 0 | 23.79 | -26.12 | NET_NEGATIVE_AFTER_COST |
| `trend@5m` | -1.65 | 1291 | 23.79 | -25.44 | NET_NEGATIVE_AFTER_COST |
| `trend@15m` | +1.28 | 0 | 23.79 | -22.51 | NET_UNPROVEN_SAMPLE |
| `trend@30m` | +2.21 | 0 | 23.79 | -21.58 | NET_UNPROVEN_SAMPLE |
| `trend@1h` | -1.25 | 0 | 23.79 | -25.04 | NET_NEGATIVE_AFTER_COST |
| `volatility@5m` | -4.73 | 520 | 23.79 | -28.52 | NET_NEGATIVE_AFTER_COST |
| `volatility@15m` | -7.06 | 0 | 23.79 | -30.85 | NET_NEGATIVE_AFTER_COST |
| `volatility@30m` | +8.91 | 0 | 23.79 | -14.88 | NET_UNPROVEN_SAMPLE |
| `volatility@1h` | +6.28 | 0 | 23.79 | -17.51 | NET_UNPROVEN_SAMPLE |

Reparto: **18** `NET_NEGATIVE_AFTER_COST`, **6** `NET_UNPROVEN_SAMPLE`,
**0** positivas.

## 3. Taxonomía de rechazos (por qué no opera cada una)

Cada entrada puede acumular varios motivos; cuentan motivos, no estrategias:

| clase | motivo | entradas | qué significa |
| --- | --- | ---: | --- |
| ECONÓMICO | `ECONOMIC_NEGATIVE_GROSS` | 17 | la ventaja bruta a coste cero ya es ≤ 0: ninguna mejora de costes la salva |
| ECONÓMICO | `ECONOMIC_BELOW_RUNTIME_COST` | 7 | bruta positiva pero por debajo del round-trip real (22,79 bps) |
| ECONÓMICO | `ECONOMIC_BELOW_RESEARCH_BARRIER` | 24 | por debajo del propio umbral de investigación (12 bps) usado en la admisión |
| EVIDENCIA | `EVIDENCE_SAMPLE_UNPROVEN` | 18 | `sample_trades = 0`: el artefacto no publica número de operaciones a ese timeframe |
| GATE | `ADMISSION_GATE_NO_PAPER_CANDIDATES` | 24 | la lista `paper_candidates` está vacía: el builder no *puede* admitir |
| CRITERIOS | `CRITERIA_UNCOMPUTED` | 24 | `c6_dd` y `c8_no_window_dominance` son `null` en la matriz: no se calcularon |

Separación pedida por el WP:

- **Económico**: 17 negativas + 7 por debajo del coste. Unánime.
- **De evidencia**: 18 sin muestra publicada.
- **De configuración/gate**: 6 familias en `rejected`, `paper_candidates = []`.
- **De criterios**: 2 de los 9 checks pre-registrados quedaron sin calcular
  (drawdown y dominancia de ventana) en las 6 familias.

## 4. La matriz pre-registrada (`docs/STRATEGY_ADMISSION_MATRIX.json`)

Checks `c1..c8` de `docs/STRATEGY_ADMISSION_CRITERIA.md` (pre-registrado en
`c1ffbaa`), con los totales del estudio de admisión en USD:

| familia | estado | c1 | c2 | c3 | c4 | c5 | c6 | c7 | c8 | gross$ | fees$ | net$ | PF | OOS net$ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| ema_crossover | REJECT | PASS | FAIL | FAIL | FAIL | FAIL | n/a | FAIL | n/a | -485.74 | 780.40 | -1266.16 | 0.5017 | -144.38 |
| momentum | REJECT | PASS | FAIL | FAIL | FAIL | FAIL | n/a | FAIL | n/a | -461.30 | 1217.99 | -1679.33 | 0.6462 | -205.41 |
| breakout | REJECT | PASS | FAIL | FAIL | FAIL | FAIL | n/a | FAIL | n/a | -289.44 | 1137.96 | -1427.46 | 0.6612 | -138.81 |
| trend | REJECT | PASS | FAIL | FAIL | FAIL | FAIL | n/a | FAIL | n/a | -232.76 | 644.04 | -876.83 | 0.7226 | -17.35 |
| mean_reversion | REJECT | PASS | FAIL | FAIL | FAIL | FAIL | n/a | FAIL | n/a | -83.91 | 1430.38 | -1514.34 | 0.6746 | -169.88 |
| volatility | REJECT | PASS | FAIL | FAIL | FAIL | FAIL | n/a | FAIL | n/a | -169.26 | 259.52 | -428.79 | 0.6175 | -52.11 |

Lectura: **c1 (muestra) pasa en las seis**; fallan las seis en c2/c3/c4/c5/c7.
El bruto **antes de comisiones** ya es negativo en las seis familias de ese
estudio (de −83,91 a −485,74 USD), así que en ese dataset no hay ni un problema
de costes: no hay ventaja que cobrar.

## 5. Dos mediciones distintas de "gross" que no son intercambiables

Esto es una trampa de lectura y queda declarada:

- el ledger toma `gross_bps_per_trade` de `docs/STRATEGY_DISCOVERY_V3_RESULTS.json`
  (diagnóstico a coste cero, nº de trades distintos: p. ej. `breakout@5m` = 2 426);
- la matriz agrega otro estudio (p. ej. `breakout` = 2 276 trades, y su
  `gross` está en USD, no normalizado por notional).

Consecuencia: para `mean_reversion` el signo difiere entre artefactos
(ledger +1,49 bps/trade; matriz `gross = −83,91 USD` en 2 861 trades). No es una
contradicción aritmética —son estudios y ponderaciones diferentes— pero **no se
puede usar uno para validar el otro**. Ambos se reportan tal cual y ninguno se
recalcula ni se "arregla".

## 6. Hallazgo: ancla de procedencia caducada (`KNOWN_DEFECT`)

El ledger declara los SHA-256 de sus dos fuentes. Uno **no coincide**:

| fuente | sha256 registrado | sha256 en disco | ¿existe en algún commit? |
| --- | --- | --- | --- |
| `docs/STRATEGY_DISCOVERY_V3_RESULTS.json` | `74024caf…` | `74024caf…` | sí (`5b4051ee280b`) |
| `docs/STRATEGY_ADMISSION_MATRIX.json` | `5f794c36…` | `4e15882c…` | **no** (la única revisión commiteada, `3271a975c7b3`, tiene `4e15882c…`) |

Prueba ejecutable:

```
uv run python scripts/build_strategy_admission.py --check
→ ADMISSION_LEDGER_STALE: regenerate with build_strategy_admission.py   (exit 1)
```

Alcance real, sin exagerarlo: el runtime lee `_sources` **solo** para construir
`evidence_ids()`; el estado y `admitted_for_paper` de cada entrada salen de
`entries`, que sí es reproducible byte a byte. Es decir, **el defecto es de
cadena de auditoría, no de comportamiento**: no cambia ninguna decisión de
admisión. Aun así rompe la propiedad "el ledger se puede reconstruir desde
commit" que el propio builder se atribuye, y por eso aparece como defecto
declarado en `INDEPENDENT_VERIFICATION.json` y no como PASS.

No se repara en este WP: regenerar el ledger tocaría `config/`, que es
exactamente el artefacto bajo auditoría. El remedio es una línea
(`uv run python scripts/build_strategy_admission.py`), y queda propuesto como
trabajo posterior con su propio commit.

## 7. Qué falta para habilitar PAPER (condiciones, no un plan de trading)

Para que **una sola** estrategia llegue a PAPER hacen falta las tres cosas a la
vez; hoy no se cumple ninguna:

1. **Gate**: que exista al menos una familia en `paper_candidates` con evidencia
   que lo justifique (hoy la lista es literalmente `[]`).
2. **Evidencia**: muestra publicada ≥ 100 trades y ≥ 30 OOS en el propio
   artefacto que se cita (hoy 18 entradas declaran 0).
3. **Economía**: ventaja bruta por operación > 22,79 bps (hoy el máximo medido es
   8,91 bps, y con las comisiones conocidas —20 bps— ya sería negativo: −11,09 bps
   incluso ignorando slippage e impacto).

Además, `c6_dd` y `c8_no_window_dominance` deberían calcularse: sin ellos la
matriz no puede declarar "todos los checks evaluados", solo "ningún check
obligatorio fallido y dos sin evaluar".

## 8. Reproducir

```bash
uv run python scripts/wp_eco001_admission_audit.py     # este informe
uv run python scripts/build_strategy_admission.py --check   # el defecto de §6
uv run python scripts/wp_eco001_verify.py              # verificación independiente
```
