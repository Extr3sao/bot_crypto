# ENMIENDA 01 — corrección de la lista de escenarios de coste

**Hipótesis:** `TDM11-H1`
**Documento enmendado:** `PREREGISTRATION.md`, SHA-256 `ef68b4c3b520435391420b0e3ed11d7224790015bcb347c4973fc86b7c53f949`
(firmado 2026-10-25T11:49:52Z, **no se modifica**)
**Motivo:** error factual en §4 del preregistro
**Efecto sobre el diseño primario:** **ninguno**

---

## 1. Qué se corrige

El preregistro §4 declaraba:

> Escenarios secundarios, descriptivos, prefijados … `41,25 bps` … y `18,7906 bps` … El `9,25 bps` citado por
> TDM-10 **no es un escenario del repo** (G0-5 H-01) y no se usa aquí.

Esa frase es **falsa**. `9,25 bps` **sí** es un escenario del repo: `BINANCE_USDM_PERP_MAKER`
(maker 2,0 ×2 + adverse selection 1,0 + missed fill 0,25 + inflación 1/p 4,0 = 9,2500 a 30 min y 1 000 USD).
El error nació de una tabla de consola truncada por un `UnicodeEncodeError` (tier con `Ⓢ`), no de una
discrepancia en el modelo. Ver `COST_MODEL_AUDIT.md` §3 y `RUN_REPORT.json → errors E4`.

## 2. Lista corregida de escenarios prefijados

| ID | Escenario | bps | Rol |
| --- | --- | --- | --- |
| `S0` | coste cero | 0,00 | lema de independencia del coste (§4 del preregistro) |
| `S1` | `BINANCE_USDM_PERP_MAKER` (p=0,5) | 9,25 | suelo del modelo, el más barato |
| `S2` | `BINANCE_USDM_PERP_TAKER` | 13,7906 | corto ejecutable con coste de taker |
| `S3` | `BINANCE_SPOT_BNB_TAKER` | 18,7906 | spot más barato |
| `S4` | **`BINANCE_SPOT_STANDARD_TAKER`** | **23,7906** | **primario, sin cambios** |
| `S5` | `BINANCE_SPOT_STANDARD_MAKER` (p=0,5) | 41,25 | maker con fill incierto |

## 3. Qué NO cambia

- Hipótesis, regla, activos, timeframe, latencia, horizonte y filtro de régimen: **idénticos**.
- Escenario **primario**: `S4` = 23,7906 bps. El veredicto se emite contra él.
- Mínimo de muestra: **36 operaciones** (MDE = 23,7906 bps, α unilateral 0,05, potencia 0,80).
- Contrato de decisión: idéntico.
- La independencia del coste se sigue aplicando tal cual: `gross_ci95_upper < 0 ⇒ NO_GO` para todo coste ≥ 0.

## 4. Secuencia y no-retroactividad

1. `PREREGISTRATION.md` firmado y hasheado (11:49:52Z).
2. Evaluación retrospectiva en DEV ejecutada; **verifica el hash del preregistro antes de correr**.
3. Verificador `V8` detecta el error de la lista de escenarios.
4. Esta enmienda se escribe y la tabla de sensibilidad se **re-ejecuta** con `S1` y `S2` añadidos.

La enmienda llega **después** de ver el resultado, así que se declara como tal y se comprueba que **no puede
cambiar el veredicto**: la fila `S0` (coste cero) ya incumple el umbral (`net = −12,58`, IC95 superior
−0,39), y todo escenario adicional tiene coste ≥ 0, por lo que solo puede empeorar el neto. La
re-ejecución lo confirma: `S1` −21,83, `S2` −26,37, `S3` −31,37, `S4` −36,37, `S5` −53,83.

**Ningún resultado publicado en la revisión 1 se ha recalculado con datos distintos de los ya usados**, y
la ventana confirmatoria sigue sin abrirse (`confirmatory_bars_read = 0`).

## 5. Estado

`AMENDMENT_APPLIED`. El SHA del preregistro original permanece `ef68b4c3…` y es el que se reporta en
`RUN_REPORT.json → preregistration.sha256`; esta enmienda se identifica por su propio hash en el manifiesto
de evidencias.
