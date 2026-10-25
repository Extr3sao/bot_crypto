# MICROSTRUCTURE_ADMISSION_V2

> Máquina: `docs/MICROSTRUCTURE_ADMISSION_V2.json`. Criterios:
> `docs/MICROSTRUCTURE_HYPOTHESES_V2.md` §5-6. Coste:
> `docs/EXECUTION_COST_MODEL_V4.json`.

Fecha: 2026-09-28. Escenario de admission: `BINANCE_SPOT_STANDARD_TAKER`
(Binance Spot, VIP0, market/market, 1,000 USD, liquidez normal).
`ADMISSION_SAFETY_MULTIPLE = 1.5`.

## 1. Escalera aplicada

```text
Filter 0 INFO CONTENT   — |IC| >= 0.01, n >= 100 en DEV
Filter 1 GROSS EDGE     — expectancy bruta DEV > 0
Filter 2 COST SURVIVAL  — gross - coste_V4(activo) > 0
Filter 3 SPLITS         — DEV > 0, VAL > 0, OOS > 0
Filter 4 COST STRESS    — 1.25x y 1.5x, con margen net > 0.25 x coste
Filter 5 ADMISSION      — n_total >= 100, n_OOS >= 30, PF_OOS > 1.0
```

## 2. Matriz

| candidata | F0 info | F1 gross>0 | F2 net>0 | F3 splits+ | F4 stress 1.5x | F5 muestra/PF | Admitida |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| M-02-BTC | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |
| M-02-ETH | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |
| M-02-SOL | ✔ | ✔ | ✘ | ✔ | ✘ | ✘ | **NO** |
| M-07-BTC/ETH/SOL | — | — | — | — | — | — | **NO** (`LIMITED_HISTORY`) |
| M-09-BTC→ETH | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |
| M-09-BTC→SOL | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |
| M-10-BTC | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |
| M-10-ETH | ✔ | ✔ | ✘ | ✔ | ✘ | ✘ | **NO** |
| M-10-SOL | ✘ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |
| M-10-PANEL-DISPERSION | ✘ | ✔ | ✘ | ✘ | ✘ | ✘ | **NO** |

```text
ADMITTED = []
PAPER_CANDIDATES = []
FALSE_SUCCESS = 0
```

Ninguna candidata pasa Filter 2: el **net DEV más alto es −17.33 bps**.
Ninguna candidata pasa F4/F5 aunque se ignore Filter 2.

## 3. Cost-aware decision (§9): gross positivo ≠ trade

La comprobación explícita pedida por la fase, por candidata, está en
`cost_aware_decision_check` del JSON:

| candidata | gross>0 | net>0 | ¿habría sido trade? | requerido 1.5x |
| --- | :-: | :-: | :-: | ---: |
| M-02-ETH (mejor gross) | ✔ (+6.427) | ✘ (−17.334) | **NO** | 35.641 bps |
| M-02-SOL | ✔ (+5.119) | ✘ (−19.568) | **NO** | 37.030 bps |
| M-09-BTC→ETH | ✔ (+0.606) | ✘ (−23.155) | **NO** | 35.641 bps |
| M-10-ETH | ✔ (+0.283) | ✘ (−23.478) | **NO** | 35.641 bps |

Seis candidatas tienen gross esperado positivo y **ninguna** es un trade: la
diferencia gross−coste las mata antes de llegar a la puerta de riesgo. Ese es el
comportamiento diseñado — el runtime no convierte un bruto positivo en una
decisión de operar.

## 4. Diagnóstico zero-cost (nunca admission)

Incluso con coste cero, el mejor gross DEV de la fase es **+6.427 bps**. Con el
coste realista, el déficit mínimo es **−17.07 bps** y el déficit frente al
umbral de admission (`required 1.5x`) es de **−28.8 bps** como mínimo.

```text
el bloqueo no es sólo la tarifa: la señal disponible es ~4x más pequeña
que la tarifa sola (20 bps de fee)
```

## 5. Estado de la fase

```text
FINAL STATUS: MICROSTRUCTURE_NO_EDGE_FOUND (ampliado)
```

Calificación honesta: el no-edge aplica a las hipótesis **históricamente
testeables**, ahora incluidas M-02, M-09 y M-10 (nuevas medidas). M-07 queda
`LIMITED_HISTORY` (medida pero no testeable por retención de OI) y M-03 sigue
`FORWARD_COLLECTION_REQUIRED`. No se declara nada sobre datos que no existen y
no se declara rentabilidad con muestras de n≈130-168.

Próximo paso recomendado (uno solo): **MICROSTRUCTURE-FORWARD-COLLECTION-V1**
— continuar la captura forward (book + OI + liquidez) que ya está implementada
y validada, porque las dos dimensiones que quedan vivas (M-03 book imbalance y
M-07 OI con DEV/VAL reales) **no** pueden resolverse con histórico.
