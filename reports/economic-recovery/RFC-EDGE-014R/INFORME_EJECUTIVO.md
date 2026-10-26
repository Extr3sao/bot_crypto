# Informe ejecutivo — WP-EDGE-14R

*2026-10-16T21:20:55Z. `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`. Sin órdenes reales, sin credenciales,
sin apalancamiento y sin cambios de riesgo.*

## En una frase

El camino de trading funciona de extremo a extremo y se detiene exactamente donde debe
detenerse —en la admisión— y ningún motor muestra rentabilidad neta positiva, así que no
hay nada que promover.

## Qué se ejecutó de verdad

| pieza | estado |
| --- | --- |
| runtime paper canónico sobre barras reales | ejecutado (879 ciclos) |
| los tres motores externos (Freqtrade, VeighNa, Jesse) | los tres ejecutados, cada uno en su entorno |
| verificación independiente | 31/31 comprobaciones |
| suite adversarial | 10/10 casos ejecutados, 0 declarados |
| holdout prospectivo | congelado y reservado, aún sin barras suficientes |

## Las cinco respuestas

1. **¿Por qué no ejecutamos operaciones paper?** Porque el ledger de admisión comprometido
   no admite ninguna estrategia: 1758 invocaciones del router,
   todas `NO_TRADE:no_strategy_passed_gates`. El freno está antes del riesgo y antes del
   broker, y es el freno correcto. Con una familia admitida en un ledger sandbox declarado
   el mismo camino produce 394 órdenes y
   347 cierres.
2. **¿Qué correcciones lo permiten sin vulnerar los gates?** Una estrategia admitida con
   evidencia medida; que el ledger registre todas las etapas (el camino CAP-004 no registra
   intención, router ni broker, por eso su cero es débil); y capacidad en disco, recuperada
   1823182848 bytes de cachés regenerables, sin borrar
   evidencia ni bajar umbrales.
3. **¿Qué frameworks externos se han ejecutado de verdad?** Freqtrade, VeighNa y Jesse, los
   tres, sobre el mismo dato y la misma regla. Jesse exigió cuatro correcciones reales,
   entre ellas que su versión 3.3.5 **no tiene hook `should_exit`**.
4. **¿Qué estrategias ofrecen rentabilidad neta positiva con evidencia suficiente?**
   Ninguna. La regla congelada pierde en los cuatro motores (≈ -1070 bps netos en el
   simulador propio sobre 44 operaciones). El holdout prospectivo está reservado y todavía
   no puede aceptar ni rechazar nada.
5. **¿Qué falta exactamente para avanzar?** Una estrategia admitida con borde bruto
   positivo tras costes; acumular barras prospectivas hasta el umbral congelado; y registrar
   las etapas intermedias del camino CAP-004. El defecto de contabilidad del broker que esta
   ronda abrió queda **cerrado** y documentado abajo (no absorbido).

## Decisiones

- `ADOPT`: ninguna. No hay ninguna estrategia con rentabilidad neta positiva.
- `EXPERIMENT`: ninguna en esta ronda.
- `DEFER`: el estado actual del runtime (no operar) y el holdout prospectivo en curso.
- `REJECT`: la regla `NEUTRAL_MA_CROSS_1H` en los cuatro motores y el arnés de conectividad
  sandbox (que sigue siendo un certificado de conectividad, nunca un candidato).

## Incidencias abiertas

- ninguna

Cerrada, no absorbida: `LEDGER_OPEN_CLOSE_RECONCILED` —
the PAPER_REPLAY sandbox arm records 348 opened fills, 347 closed fills and 1 position still open when the replay ended. Cómo:
an opening is identified by symbol, instant and execution price rather than by a timestamp two openings can share, and every close is drained from the broker's own closed-trades ledger, so the closes the engine performs inside its own cycle are recorded too.

## Lo que este paquete no hace

No habilita trading real, no guarda credenciales, no usa apalancamiento, no modifica
límites de riesgo y no presenta un replay como observación prospectiva.
