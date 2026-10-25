# FINAL_REPORT — WP-ECONOMIC-RECOVERY-007

**Clasificación: `NO_ADMITTED_STRATEGY`.** Ninguna de las seis familias supera la
barrera de costes en el muestreo evaluado. Autorización: **`BLOCKED`** — no hay nada que
llevar a PAPER, y `admitted_for_paper` sigue en `0/24` sin tocar.

## 1. Qué se ejecutó realmente

Seis familias productivas (`trading_bot.research.families.*`, el código que corre en
paper) sobre **datos reales de exchange**, evaluadas por el motor reparado en WP-006:

| Campo | Valor |
| --- | --- |
| Fuente | Binance USDⓈ-M `fapi/v1/klines` (público, sin credenciales) |
| Activos | BTCUSDT, ETHUSDT, SOLUSDT |
| Barra | 5m |
| Periodo | 2026-06-27T17:40Z → 2026-10-25T17:35Z (120 días, 34 560 barras/activo) |
| Huecos | 0 (validado en WP-006) |
| Particiones | DEV 2026-06-27→2026-08-26, VAL →2026-09-25, OOS →2026-10-25 |
| Operaciones evaluadas | 23 444 (todas reconciliadas y verificadas) |
| Costes | 5 bps comisión + 1 bp slippage por lado, spread declarado 0 bps |

Reproducción: `scripts/multi_family_backtest.py --dump-trades` → `reports/economic/w006/`,
`scripts/w007_classify.py` → `ECONOMIC_CLASSIFICATION.json`.

## 2. Resultados económicos netos

| familia | clase | ops | WR % | PF | gross | costes | net BASE | net 2X | net stressed | net zero |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ema_crossover` | REJECT | 826 | 26,51 | 0,52 | −94,47 | 495,60 | −590,08 | −939,01 | −880,53 | −90,85 |
| `momentum` | REJECT | 1313 | 38,84 | 0,62 | −202,87 | 787,96 | −990,82 | −1643,52 | −1513,59 | −219,53 |
| `breakout` | REJECT | 1168 | 34,33 | 0,59 | −154,09 | 700,97 | −855,06 | −1414,88 | −1300,62 | −159,86 |
| `trend` | REJECT | 523 | 56,98 | 0,75 | −0,06 | 313,93 | −313,99 | −575,59 | −523,27 | −0,06 |
| `mean_reversion` | EXPERIMENT | 1748 | 48,00 | 0,70 | **+242,81** | 1048,87 | −806,06 | −1409,73 | −1300,04 | **+205,02** |
| `volatility` | REJECT | 347 | 38,33 | 0,54 | −152,17 | 208,23 | −360,40 | −533,93 | −499,22 | −153,96 |

Capital inicial 10 000, sizing 0,25 % de equity por operación con tope de 500 de nocional
(el tope es el que se aplica en todas las familias). `net zero` es diagnóstico de
señal, **nunca** base de admisión.

### Por partición

| familia | DEV net | VAL net | OOS net | DEV gross(0c) | VAL gross(0c) | OOS gross(0c) |
| --- | --- | --- | --- | --- | --- | --- |
| `ema_crossover` | −322,95 | −179,73 | −87,40 | −44,74 | −80,03 | +33,92 |
| `momentum` | −544,82 | −229,76 | −216,24 | −159,76 | −12,55 | −47,22 |
| `breakout` | −487,14 | −187,90 | −180,02 | −143,12 | −11,43 | −5,31 |
| `trend` | −209,99 | −14,53 | −89,47 | −73,77 | +98,98 | −25,27 |
| `mean_reversion` | −429,11 | −149,91 | −227,05 | **+69,96** | **+120,30** | **+14,76** |
| `volatility` | −171,67 | −124,04 | −64,69 | −60,69 | −68,21 | −25,07 |

Ninguna familia gana en DEV **y** VAL **y** OOS de forma simultánea con costes. Solo
`mean_reversion` es consistente en las tres particiones **antes** de costes (esperanza
bruta positiva en DEV, VAL y OOS), y pierde en las tres después de costes.

### Por activo (BASE)

| familia | neto BTC | neto ETH | neto SOL | ops BTC | ops ETH | ops SOL |
| --- | --- | --- | --- | --- | --- | --- |
| `ema_crossover` | −164,17 | −185,73 | −240,18 | 192 | 270 | 364 |
| `momentum` | −257,58 | −325,11 | −408,13 | 311 | 507 | 495 |
| `breakout` | −210,26 | −244,22 | −400,58 | 312 | 404 | 452 |
| `trend` | −22,92 | −107,98 | −183,09 | 72 | 182 | 269 |
| `mean_reversion` | −268,84 | −183,52 | −353,70 | 473 | 629 | 646 |
| `volatility` | −104,16 | −106,36 | −149,89 | 81 | 134 | 132 |

Ningún activo rescata a ninguna familia: el signo es negativo en los nueve pares
familia-activo, salvo el caso ya descrito de `mean_reversion` antes de costes.

## 3. La causa: la barrera de costes, medida

| familia | ops/día/activo | gross/op | coste/op | net/op | edge/coste | break-even (bps ida+vuelta) |
| --- | --- | --- | --- | --- | --- | --- |
| `breakout` | 3,24 | −0,1319 | 0,6001 | −0,7321 | −0,22 | −2,64 |
| `ema_crossover` | 2,29 | −0,1144 | 0,6000 | −0,7144 | −0,19 | −2,29 |
| `mean_reversion` | 4,86 | **+0,1389** | 0,6000 | −0,4611 | **0,231** | **2,78** |
| `momentum` | 3,65 | −0,1545 | 0,6001 | −0,7546 | −0,26 | −3,09 |
| `trend` | 1,45 | −0,0001 | 0,6002 | −0,6004 | −0,00 | −0,00 |
| `volatility` | 0,96 | −0,4385 | 0,6001 | −1,0386 | −0,73 | −8,77 |

Lectura honesta de la única familia con señal: `mean_reversion` gana **0,1389 por
operación** antes de costes y paga **0,60**. Necesitaría un coste de ida y vuelta de
**2,78 bps** para empatar; se le cobran **12 bps** (2 lados × (5 comisión + 1 slippage)).
El edge es **4,3 veces demasiado pequeño** para la estructura de costes del producto, no
un 5 % demasiado pequeño. Cuatro de las seis familias además pierden **antes** de costes,
lo que descarta el argumento «el edge existe pero los costes lo comen» para ellas.

## 4. Criterios aplicados

Declarados en `scripts/w007_classify.py` **antes** de mirar los resultados:

- **ADMIT** — neto > 0 con BASE, 2X_COST y STRESSED_SLIPPAGE; neto > 0 en DEV y en OOS;
  ≥ 100 operaciones.
- **EXPERIMENT** — gross > 0 con BASE, o neto > 0 a coste cero con ≥ 100 operaciones.
- **REJECT** — sin evidencia de edge bruto.

Resultado: 1 `EXPERIMENT` (`mean_reversion`), 5 `REJECT`, 0 `ADMIT`. No se ha ajustado
ningún hiperparámetro sobre OOS porque no se ha ajustado ninguno en absoluto: las seis
familias son las que corren en producción, con sus parámetros por defecto.

## 5. Robusto frente a costes: qué sobrevive al estrés

El escenario 2X_COST **duplica comisiones y spread** y el STRESSED_SLIPPAGE **quintuplica
slippage**. Ninguna familia cambia de signo: todas empeoran. La ordenación por pérdida
neta se mantiene (`volatility` la peor por operación, `mean_reversion` la mejor), lo que
indica que el resultado no depende del escenario de costes elegido sino de la relación
edge/coste, que es negativa en las seis.

## 6. Lo que este informe NO puede concluir

- Que estas familias no tengan edge en otro marco temporal. Aquí solo se ha medido 5m.
  La barrera de costes en 5m es estructural: 12 bps por operación exige ≥ 12 bps de edge.
- Que `mean_reversion` sea rentable con menos operaciones. Es una hipótesis plausible
  (el edge por operación sube al alargar el mantenimiento) pero **no medida**.
- Nada sobre ejecución real: no hay modelo de cola, ni de adverse selection, ni datos de
  libro. El spread es una suposición declarada (0 bps) y el escenario 2X_COST la estresa.
- Nada sobre 3 operaciones/día como objetivo: la frecuencia observada (0,96–4,86
  ops/día/activo) no se ha forzado ni premiado.

## 7. Experimentos acotados propuestos (sin nuevas arquitecturas)

1. **Umbral de coste, no de señal.** Sobre `mean_reversion` únicamente: medir si el edge
   bruto por operación crece más rápido que la caída de frecuencia al exigir umbrales más
   altos de desviación. Criterio de éxito fijado de antemano: gross/op ≥ 12 bps del
   nocional en DEV **y** VAL, con ≥ 100 operaciones en DEV. OOS se abre una sola vez.
2. **Marco temporal.** Repetir la matriz en 15m y 1h remuestreando las mismas barras
   (misma fuente, mismo manifiesto). Si el edge por operación no supera los 12 bps en
   ningún marco, la conclusión «estas familias no pagan sus costes en este producto» queda
   cerrada con evidencia, no con una corazonada.
3. **Modelo de fill maker explícito.** Solo si (1) o (2) dan edge bruto: modelar entrada
   limit con probabilidad de fill y haircut por adverse selection, con el coste resultante
   declarado por escenario. Sin ese modelo, ningún resultado maker es evidencia.

Ninguno de los tres autoriza PAPER por sí mismo; los tres producen números que se pueden
verificar con `scripts/w006_verify.py`.

## 8. Estado de autorización y siguiente acción

- `BLOCKED` para PAPER. Sin estrategia admitida no se ejecuta WP-008.
- Siguiente acción ejecutable: experimento (2) — el más barato, no requiere código nuevo,
  y decide si el problema es de señal o de marco temporal. Después, (1) sobre
  `mean_reversion` con el criterio ya fijado.
- LIVE_LIMITED (WP-009): **no preparado**. Preparar el mecanismo sin estrategia validada
  sería trabajo sin destinatario; queda pendiente hasta que exista un `ADMIT`.
