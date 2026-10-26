# MICROSTRUCTURE_INFORMATION_CONTENT_V2 — Filter 0

> Máquina: `docs/MICROSTRUCTURE_INFORMATION_CONTENT_V2.json`.

Fecha: 2026-09-28. Umbral pre-registrado: |IC Spearman| ≥ **0.01** con
**n ≥ 100** en DEV (Spearman con rangos promedio, *tie-aware*; V1 usaba una
variante sin empates y los números no son directamente comparables).

## 1. Medición

| candidata | n | IC DEV | top−bottom (bps) | monotonicidad | estado |
| --- | :-: | ---: | ---: | :-: | --- |
| M-02-BTC | 137 | +0.0479 | +0.62 | −0.1 | HAS_INFORMATION |
| M-02-ETH | 168 | −0.0141 | **+8.08** | +0.1 | HAS_INFORMATION |
| M-02-SOL | 131 | **−0.1129** | −2.76 | −0.5 | HAS_INFORMATION |
| M-07-BTC/ETH/SOL | 0 | — | — | — | INSUFFICIENT_DATA (sin DEV) |
| M-09-BTC→ETH | 3,948 | +0.0270 | +3.67 | **+1.0** | HAS_INFORMATION |
| M-09-BTC→SOL | 3,948 | +0.0247 | +3.12 | **+0.9** | HAS_INFORMATION |
| M-10-BTC | 3,962 | +0.0101 | +0.35 | +0.7 | HAS_INFORMATION |
| M-10-ETH | 3,962 | −0.0275 | −2.49 | −0.9 | HAS_INFORMATION |
| M-10-SOL | 3,962 | −0.0043 | +2.57 | +0.1 | NO_INFORMATION |
| M-10-PANEL-DISPERSION | 3,962 | −0.0033 | −0.91 | −0.3 | NO_INFORMATION |

```text
HAS_INFORMATION 7 | NO_INFORMATION 2 | INSUFFICIENT_DATA 3
```

## 2. Qué dice este filtro y qué no

**Sí dice**: existe relación estadística débil y, en algunos casos, ordenada
entre las features nuevas y el retorno futuro. M-09 (lead/lag de flujo BTC) es
el caso estructuralmente más limpio medido en el proyecto: n≈3,950, IC +0.027 y
monotonicidad **+1.0** en ETH (el quintil más alto de flujo BTC predice
sistemáticamente el mejor retorno futuro de ETH). M-02-SOL tiene el mayor |IC|
de la fase (−0.113) en la muestra más pequeña.

**No dice**: que la relación sea explotable. La magnitud es el problema, no la
existencia. El mejor diferencial top−bottom medido es **+8.08 bps**
(M-02-ETH, n=168) frente a un coste round-trip de **23.5–24.7 bps** y un
`REQUIRED_GROSS_EDGE_BPS` de **35.25–37.03 bps**.

```text
información detectada  = SÍ (débil, monotónica en M-09)
información suficiente = NO  (déficit ≥ 15 bps frente al break-even,
                              ≥ 27 bps frente al umbral de admission)
```

## 3. Por qué no se promociona ninguna

El propio pre-registro fija que Filter 0 es **necesario pero no suficiente**:
una candidata con `HAS_INFORMATION` que no sobrevive Filter 1/2 (gross y coste)
se clasifica igualmente `COST_KILLED`. Las 7 candidatas con información
detectada cayeron exactamente ahí: 5 `COST_KILLED` y 2 en `LIMITED_HISTORY`
por datos, con gross DEV entre +0.008 y +6.427 bps.

Calificación honesta de M-02 y M-09:

```text
OBSERVED          — la relación se observa y está medida
INSUFFICIENT_SAMPLE / COST_KILLED — no es un edge y no se declara como tal
```

En particular M-02-SOL: 3 splits positivos pero **6/14 días positivos**, con
dos días aportando casi todo el resultado. La información existe; la
explotabilidad no.
