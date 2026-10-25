# WP-TDM-12B — RETROSPECTIVE TRIAGE REPORT

**Universo:** 24 celdas ya existentes (6 familias × 4 timeframes), parámetros congelados, sin refit.
**Ventanas:** HOLD `2026-09-25→10-24` (expuesta) y DEV `2026-06-25→09-25` (expuesta).
**Coste primario:** 23,7906 bps (spot taker). **Mínimo de muestra:** propio de cada celda (§3).
**Decisión:** **`NO_ELIGIBLE_CANDIDATE`** · **Evidencia:** `CANDIDATE_REGISTRY.csv`,
`CANDIDATE_REGISTRY.json`, `.tdm12/triage.json`.

---

## 1. Resultado en una línea

Ninguna de las 24 celdas gana dinero después de costes en ninguna de las dos ventanas. La mejor gana
**+7,05 bps brutos** en HOLD y **−16,74 netos**; la mejor en DEV gana **+11,30 brutos** y **−12,49 netos**.
**0/24 netas positivas en HOLD, 0/24 en DEV.**

## 2. Tabla completa

bps por operación. `req n` = muestra necesaria para 80 % de potencia al efecto = coste, calculada con la
dispersión **de esa celda** (no se hereda el 36 de TDM-11).

| Celda | HOLD n | HOLD bruto | HOLD neto | DEV n | DEV bruto | DEV neto | req n | potencia |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `volatility@5m` | 58 | **+7,05** | −16,74 | 274 | +0,07 | −23,72 | 15 | sí |
| `breakout@30m` | 180 | +2,79 | −21,00 | 593 | −0,71 | −24,50 | 19 | sí |
| `trend@1h` | 252 | +2,65 | −21,14 | 1 044 | +1,59 | −22,20 | 43 | sí |
| `mean_reversion@15m` | 279 | +2,32 | −21,47 | 920 | +2,01 | −21,78 | 11 | sí |
| `breakout@15m` | 351 | +1,94 | −21,85 | 1 088 | −2,74 | −26,53 | 20 | sí |
| `mean_reversion@30m` | 150 | +0,96 | −22,83 | 499 | −2,38 | −26,17 | 16 | sí |
| `trend@30m` | 345 | +0,65 | −23,14 | 1 311 | +0,85 | −22,95 | 24 | sí |
| `ema_crossover@30m` | 1 814 | +0,46 | −23,33 | 5 972 | +0,51 | −23,28 | 13 | sí |
| `momentum@5m` | 1 020 | +0,13 | −23,66 | 3 316 | −1,61 | −25,40 | 27 | sí |
| `mean_reversion@5m` | 771 | −0,11 | −23,90 | 2 443 | +1,49 | −22,31 | 16 | sí |
| `momentum@30m` | 1 002 | −0,11 | −23,90 | 3 285 | +0,06 | −23,73 | 16 | sí |
| `ema_crossover@5m` | 3 511 | −0,70 | −24,50 | 10 976 | −0,53 | −24,32 | 13 | sí |
| `ema_crossover@15m` | 2 574 | −0,65 | −24,44 | 8 199 | −0,30 | −24,09 | 12 | sí |
| `momentum@15m` | 1 105 | −0,74 | −24,53 | 3 621 | −0,83 | −24,62 | 18 | sí |
| `ema_crossover@1h` | 832 | −1,08 | −24,87 | 2 890 | +0,66 | −23,14 | 24 | sí |
| `trend@15m` | 272 | −3,13 | −26,92 | 1 041 | +0,37 | −23,43 | 34 | sí |
| `breakout@5m` | 836 | −3,57 | −27,36 | 2 690 | −2,04 | −25,83 | 20 | sí |
| `momentum@1h` | 578 | −3,71 | −27,50 | 1 955 | +1,78 | −22,01 | 28 | sí |
| `mean_reversion@1h` | 73 | −3,91 | −27,70 | 226 | −0,03 | −23,82 | 71 | sí |
| `breakout@1h` | 85 | **−6,76** | −30,55 | 290 | **+11,30** | −12,49 | 58 | sí |
| `volatility@15m` | 55 | −9,19 | −32,98 | 156 | −7,35 | −31,14 | 8 | sí |
| `trend@5m` | 125 | −7,75 | −31,54 | 481 | −1,77 | −25,57 | 45 | sí |
| `volatility@30m` | 31 | −2,38 | −26,17 | 110 | −2,10 | −25,90 | 29 | sí |
| `volatility@1h` | 17 | −7,76 | −31,55 | 48 | +4,16 | −19,63 | 24 | **no** |

Reproducción cruzada: `volatility@5m` +7,0531 y `breakout@1h` DEV +11,2977 coinciden con las cifras
publicadas por TDM-10, y `ema_crossover@5m` 3 511 operaciones en HOLD también. El arnés de TDM-12 mide lo
mismo que el de TDM-10 desde cero.

## 3. Potencia, celda por celda

- **23 de 24** celdas alcanzan su propio mínimo de muestra (`req n`) al efecto = coste.
- Solo `volatility@1h` no lo alcanza (17 de 24 necesarias) → su resultado es `INSUFFICIENT_EVIDENCE`, no
  un rechazo.
- No se ha usado el mínimo de 36 de TDM-11 en ninguna celda: cada una tiene el suyo (11 a 71).

## 4. Lo que la tabla dice de verdad

1. **El patrón es "bruto ≈ 0, neto ≈ −coste".** Casi todas las celdas oscilan entre −4 y +3 bps brutos:
   están bien medidas y no tienen edge. La distribución es la de una moneda justa menos comisiones.
2. **Hay dos celdas con bruto positivo en ambas ventanas**: `trend@1h` (+2,65 / +1,59) y
   `mean_reversion@15m` (+2,32 / +2,01). Son el hallazgo más interesante del triaje — consistentes, no
   ruido de una sola ventana — y **aun así pierden ~21 bps netos**. Consistencia no es rentabilidad.
3. **`breakout@1h` es la trampa clásica**: +11,30 en DEV y −6,76 en HOLD. Cualquiera que hubiera mirado
   solo DEV habría tenido un candidato; el cambio de mes lo desmonta.
4. **`ema_crossover` es el mayor quemador de comisiones**: 3 511 operaciones en 30 días a 5m con bruto
   −0,70. Su cota superior de edge bruto es ~0: los datos **excluyen** que pague.
5. **Ninguna celda neta positiva ni con coste cero en ambas ventanas.** El problema no es la tarifa: es
   que no hay señal.

## 5. Pista ACTIVE y pista QUALITY (B6)

| Pista | Requisito | Resultado |
| --- | --- | --- |
| `ACTIVE` | ≥3 operaciones/día de portfolio, 7 días/semana | **20 de 24** celdas ya superan 3 trades/día por sí solas (`ema_crossover@5m` llega a 119,9/día), **pero 0 de ellas es neta positiva** |
| `QUALITY` | net edge positivo y robusto, cualquier frecuencia | **0 de 24** |

La restricción de frecuencia **no es la que bloquea**: el sistema ya opera de sobra. Lo que bloquea es la
expectativa. Subir frecuencia para "llegar a 3/día" no selecciona nada aquí, y forzarla sería el error que
el RFC prohíbe.

## 6. Gates por candidato

| Gate | Resultado |
| --- | --- |
| `runtime_reachable` | 24/24 sí (familias instanciadas por el runtime de paper) |
| `admitted_for_paper` | **0/24** (ledger: 17 `NO_GROSS_EDGE`, 7 `COST_KILLED`) |
| `lookahead_gate` | 24/24 PASS (PIT + control de 12 barras: −12,58 → +17,05 si se mira el futuro) |
| `stale_data_gate` | 24/24 PASS (0 huecos, 0 duplicados, 0 solape) |
| `parameter_freeze` | 24/24 PASS (hash de módulo registrado) |
| `cost_verified` | **0/24** (`UNVERIFIED_COST`) |
| `sample_sufficient` | 23/24 |
| `net_positive_hold` | **0/24** |
| `net_positive_dev` | **0/24** |

## 7. Decisión

**`NO_ELIGIBLE_CANDIDATE`.** No se emite `PREREG_CANDIDATE`:

- ningún candidato supera el gate económico en HOLD, y ninguno lo supera tampoco en DEV;
- los dos que son consistentes (`trend@1h`, `mean_reversion@15m`) están a ~21 bps del umbral, no cerca;
- el coste no está verificado en ninguna celda, así que incluso un empate habría sido `INCONCLUSIVE`;
- la ventana que podría decidir no existe todavía.

**Obstáculos medibles para el próximo RFC** (no "falta investigación", cifras):
1. Falta una entrada con **bruto > 23,79 bps** en dos ventanas independientes; el máximo observado es 7,05.
2. Falta **spread observado** (hoy 1 bp estimado) y **funding/fills** para poder usar el 9,25 como algo
   más que un suelo teórico.
3. Falta una **ventana confirmatoria**: la única admisible arranca en 2026-10-24T16:00Z.
4. Falta **independencia de autor** para certificar cualquier resultado futuro.

**Siguiente gate:** un RFC nuevo, con hipótesis específica derivada de estos obstáculos. Nada de
promoción, paper, live ni cambios de parámetros en este WP.
