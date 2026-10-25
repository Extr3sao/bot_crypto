# FINAL_REPORT — WP-ECONOMIC-BLOCKER-001

**Auditoría de costes y admisión de estrategias.**
Commit medido `e67194e79a42`, rama `audit/economic-blocker-001`, Python 3.11.15.
Todo lo que sigue se puede recomputar con los scripts del WP; ningún número está
tecleado a mano.

---

## 1. Las cinco preguntas del criterio de aceptación

### 1.1 ¿Por qué no opera cada estrategia?

Por **tres puertas independientes**, y basta con que una esté cerrada:

| puerta | estado | detalle |
| --- | --- | --- |
| gate de admisión | **cerrada** | `paper_candidates = []` → el builder no *puede* emitir `PAPER_CANDIDATE` para nada |
| evidencia | **cerrada en 18 de 24** | `sample_trades = 0`: el artefacto no publica nº de operaciones a 15m/30m/1h |
| economía | **cerrada en 24 de 24** | mejor bruto medido +8,91 bps vs coste 22,79 bps |

Las 24 entradas (6 familias × 4 timeframes) con su motivo exacto están en
[`STRATEGY_ADMISSION_AUDIT.md`](STRATEGY_ADMISSION_AUDIT.md) §2–§3, y en formato
máquina en [`STRATEGY_ECONOMICS_MATRIX.csv`](STRATEGY_ECONOMICS_MATRIX.csv).

Reparto de motivos (cuentan motivos, no estrategias): 17 `ECONOMIC_NEGATIVE_GROSS`,
7 `ECONOMIC_BELOW_RUNTIME_COST`, 18 `EVIDENCE_SAMPLE_UNPROVEN`,
24 `ADMISSION_GATE_NO_PAPER_CANDIDATES`, 24 `CRITERIA_UNCOMPUTED`
(`c6_dd` y `c8_no_window_dominance` siguen sin calcular).

Y el fallo **no** está repartido: las seis familias fallan los checks
pre-registrados c2/c3/c4/c5/c7 en el estudio de admisión, y su bruto *antes de
comisiones* ya es negativo (−83,91 a −485,74 USD). Es decir, en ese dataset no
había ni siquiera una ventaja que las comisiones pudieran arruinar.

> Nota de lectura: el ledger (24 entradas) y la matriz (6 familias) son **dos
> estudios distintos**, con distinto nº de operaciones y distinta unidad
> (bps/trade vs USD). Para `mean_reversion` incluso difieren de signo. No se
> usan uno para validar el otro; ambos se reportan tal cual
> ([`STRATEGY_ADMISSION_AUDIT.md`](STRATEGY_ADMISSION_AUDIT.md) §5).

### 1.2 ¿Cuánto cuesta realmente cada operación?

**22,79 bps** (BTC) · **22,83 bps** (ETH) · **23,79 bps** (SOL) por ida y vuelta
a 1 000 USD, en el escenario `BINANCE_SPOT_STANDARD_TAKER`:

| componente | bps | clase | cómo se conoce |
| --- | ---: | --- | --- |
| comisión de entrada | 10,0 | KNOWN | tarifa publicada, VIP0, pago en quote |
| comisión de salida | 10,0 | KNOWN | ídem |
| spread | 0,001–1,0 | OBSERVED | `spread_bps` del snapshot del ciclo |
| slippage | 2,63 | ESTIMATED | 1,0 bps × tamaño 1,316 × volatilidad 1,0 |
| impacto | 0,16 | ESTIMATED | desplazamiento por tamaño |
| funding | 0 | KNOWN | spot |

- **87,75 % del coste es KNOWN.** Ninguna re-estimación de slippage/impacto
  cambia ningún veredicto: con slippage e impacto a cero, el neto de la mejor
  estrategia sigue siendo **−11,09 bps**.
- Recomputación: los **24/24** bloques `CostBreakdown` que el runtime PAPER
  registró en `WP-PAPER-REAL-DATA-001` se reproducen con Δ ≤ **5,0e-09 bps**.
  El rango "22,8–23,8" no era incertidumbre: era **diferencia de activo**.
  Detalle en [`COST_MODEL_AUDIT.md`](COST_MODEL_AUDIT.md).
- El coste **no baja alargando el horizonte** (spot, sin funding): pasar de 5 min
  a 240 min no mueve el coste ni una décima. Alargar la operación no amortiza la
  comisión; solo reducir el número de operaciones lo haría.
- El runtime calculó con `volatility_bps = 0`, así que el coste registrado es
  **optimista**: el coste real es ≥ 22,79, nunca menor.

### 1.3 ¿Alguna estrategia merece validación económica posterior?

**Ninguna está cerca de ser rentable, y no se admite ninguna.** Dicho eso, la
pregunta útil es qué información falta, no qué está cerca:

| entrada | bruto | muestra | neto | por qué no se admite |
| --- | ---: | ---: | ---: | --- |
| `volatility@30m` | +8,91 | 0 | −14,88 | falta la muestra; y su versión 5m es −4,73 |
| `mean_reversion@30m` | +5,47 | 0 | −18,32 | falta la muestra; 5m sólo +1,49 |
| `volatility@1h` | +6,28 | 0 | −17,51 | falta la muestra |
| `trend@30m` | +2,21 | 0 | −21,58 | falta la muestra |

Lo que justifica mirarlas de nuevo **no** es la proximidad al coste (nadie está a
menos de 14 bps), sino que son las únicas con bruto positivo en un timeframe largo
**sin contador de operaciones**. Es un hueco de reporte, no una ventaja: el
artefacto del que salen publica bps/trade pero no `trades`.

Prioridad propuesta, en este orden y sin admitir nada:
1. publicar muestra y OOS de `volatility@30m` y `mean_reversion@30m` (los datos
   ya existen aguas arriba; no hace falta capturar mercado nuevo);
2. sólo si aparecen ≥ 100 trades y ≥ 30 OOS, recalcular neto con el coste de §1.2;
3. sólo si el neto sale positivo, entrar por el gate de admisión completo.

### 1.4 ¿Qué evidencia falta para habilitar un PAPER end-to-end?

1. **Una familia admitida**: alguien tiene que poner evidencia en
   `paper_candidates`, hoy `[]`. Ningún cambio de código puede sustituir eso sin
   convertirse en un override.
2. **Muestra publicada** para 15m/30m/1h (`sample_trades = 0` en las 18 entradas).
3. **Bruto > 22,79 bps** por operación, con muestra, o un tier de comisión mejor
   demostrado con volumen real. Hoy el máximo medido es 8,91 (2,6× por debajo).
4. **`c6_dd` y `c8_no_window_dominance` calculados**: sin ellos la matriz no
   puede decir "todos los checks evaluados", sólo "ningún obligatorio fallido y
   dos sin evaluar".
5. **Un feed de primera clase** en el runtime: la ejecución PAPER desde señales
   reales se demostró (en el WP anterior) sólo inyectando el feed por la costura
   de inyección, no por un proveedor de primera clase.

### 1.5 ¿Qué bloqueos son de software y cuáles de ausencia de ventaja?

| bloqueo | naturaleza | ¿lo arregla código? |
| --- | --- | --- |
| `paper_candidates = []` | estado del artefacto de admisión | no: requiere evidencia |
| `sample_trades = 0` (18 entradas) | hueco de reporte en artefactos de research | sí, sin datos nuevos (publicar `trades`) |
| `c6_dd` / `c8_null` | análisis no ejecutado | sí, calculable con los datos actuales |
| coste 22,79 > bruto 8,91 | **ausencia de ventaja estadística** | no |
| umbral de admisión 12 bps vs coste real 22,79 | gobernanza del modelo de costes (dos supuestos en dos sitios) | sí: unificar |
| hash de procedencia caducado | higiene de auditoría | sí, regenerando el ledger |
| 103 fallos de test preexistentes | higiene: tests que dependen de `reports/**` no versionados | sí, sin tocarlos aquí |

Sólo la cuarta fila es economía. Las demás son deuda que **oscurece** la
economía, y por eso el WP las separa en lugar de sumarlas en un "no funciona".

---

## 2. Lo que este WP no hace

- **No declara `PAPER_RUNTIME_VALIDATED`.** No hubo ejecución desde señales
  porque no hay ninguna estrategia admitida; el hueco no se rellena con un test.
- **No declara rentabilidad** ni expectativa positiva para nada.
- **No modifica** `src/`, `config/`, ni reglas de admisión, ni comisiones, ni
  riesgo. Comprobado por el verificador (`E1`), no por promesa.
- **No repara** el hash de procedencia caducado: el remedio toca `config/`, el
  artefacto bajo auditoría. Queda declarado con su comando exacto.
- **No re-ejecuta** PAPER ni usa credenciales privadas.

## 3. Defectos y límites declarados

1. **`PROVENANCE_ANCHOR_STALE`** (cadena de auditoría, inerte en runtime): el
   SHA-256 registrado para `docs/STRATEGY_ADMISSION_MATRIX.json` no coincide con
   el fichero ni con ninguna revisión commiteada; `build_strategy_admission.py
   --check` sale **1**. Los estados de admisión sí se reproducen byte a byte.
2. **Baseline de tests**: 103 nodos fallan en el árbol y 103 de ellos también en
   un checkout limpio (⊆), más **21 que sólo fallan en limpio** porque dependen de
   `reports/**` no versionado. Ninguno es regresión de este WP; los 21 son
   evidencia de que un "verde local" no es reproducible.
   Detalle en [`TEST_BASELINE_COMPARISON.md`](TEST_BASELINE_COMPARISON.md).
3. **`TEST_SUITE_WRITES_TRACKED_DATA`**: la propia suite modifica un fichero
   versionado (`data/st6/RFC047_RUNTIME_VERIFICATION.json`, reescrito por dos
   tests de research). Restaurado a `HEAD` tras medir; se declara porque significa
   que ejecutar tests **cambia el repo**, y eso contamina cualquier comparación
   futura de "antes/después".
4. **Coste como punto, no como distribución**: 3 runs, 24 bloques, 3 activos.
   No se extrapola a otros regímenes.
5. **Spread observado en snapshot**, no ejecutado: no hay evidencia de fill real
   (el `maker_gate` de V4 ya lo marcaba FAIL).
6. **Dos mediciones de gross no intercambiables** (ledger vs matriz), declarado
   en §1.1.

## 4. Verificación independiente

[`INDEPENDENT_VERIFICATION.json`](INDEPENDENT_VERIFICATION.json) re-deriva las
cifras desde las fuentes primarias sin importar los scripts de auditoría:

- **27 PASS · 0 FAIL · 0 NOT_ASSESSED · 1 defecto declarado**, exit 0.
- Incluye recomputar los 24 bloques de coste, el inventario de componentes, la
  aritmética neta del CSV, la cobertura exacta de ids del ledger, el estado de
  los hashes y la contención de conjuntos del baseline de tests.

## 5. Qué haría cambiar esta respuesta

- Una estrategia con bruto > 22,79 bps **y** muestra publicada **y** OOS
  positivo: cambiaría §1.3 y §1.4 de golpe.
- Un tier de comisión real mejor (evidencia de volumen): bajaría el listón de
  22,79 a lo que sea ese tier, aunque hoy no hay tal evidencia en el repo.
- Un cambio en el modelo de costes que el propio motor aplicara (hoy el runtime
  ya usa 22,79; el umbral de research usa 12). Ese desajuste de 10,79 bps es lo
  primero que conviene alinear antes de juzgar cualquier estrategia.

## 6. Reproducir todo

```bash
uv run python scripts/wp_eco001_admission_audit.py
uv run python scripts/wp_eco001_cost_audit.py
uv run python scripts/wp_eco001_economics.py
uv run python scripts/wp_eco001_test_baseline.py --phase working   # ~4 min
uv run python scripts/wp_eco001_test_baseline.py --phase clean     # ~4 min
uv run python scripts/wp_eco001_test_baseline.py --phase healthy
uv run python scripts/wp_eco001_test_baseline.py --phase assemble
uv run python scripts/wp_eco001_verify.py
```
