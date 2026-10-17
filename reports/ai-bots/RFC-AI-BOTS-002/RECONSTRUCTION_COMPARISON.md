# RECONSTRUCTION_COMPARISON — original observado vs nuestros bots

## Qué se puede comparar (y qué no)

| Caso | Original (observado con REA) | Nuestro runtime | Verdict |
| --- | --- | --- | --- |
| Estructura de la app | Bundle Next.js de 12 chunks, 10 módulos, 43 scripts en la captura | No aplica: nuestro bot es Python sin UI | `NOT_COMPARABLE` |
| Endpoints declarados | 7 nodos `endpoint`, todos minificados (`dpl`, `a`, `b`, `cookie`, `/_next/image`) | Rutas internas explícitas (`/api/health`, etc.) | `NOT_COMPARABLE` (no hay semántica legible en el original) |
| Gráfico → llamada multimodal | **No observado** (REA no ejecuta el JS; el bundle no expone la llamada) | `vision/lane.py` construye PNG + hash y llama al proveedor con recibo | `UNKNOWN` en el original |
| Decisión → riesgo → paper | **No observado** | `RiskManager.check_signal` → `PaperBroker` en la ruta canónica | `UNKNOWN` en el original |
| Hash de imagen alterado | No observable | **Fail-closed**: `INTEGRITY_FAILURE` ⇒ 0 decisiones, 0 fills (test nuevo) | propio, verificado |
| Respuesta tardía | No observable | **Fail-closed**: `LATE_RESPONSE` ⇒ no se rellena (test nuevo) | propio, verificado |
| Comparación de valor | No observable | `comparison()` devuelve `NOT_COMPARABLE` si cambian cadencia/insumos/capital/costes | propio, verificado |

**Conclusión:** no existe hoy evidencia que permita decir que nuestro bot «se parece» al
original en la cadena que importa, porque del original no hay traza de esa cadena. Lo que sí
está probado es que nuestros tres defectos P0 ya no pueden producir una operación falsa.

## Divergencias que sí podemos afirmar

1. Nuestro bot exige un **contrato cerrado** (`AITradeOpinion`, prohibido `quantity`,
   `leverage`, `notional_usdt`, `execute`); en el bundle analizado no hay contrato legible.
2. Nuestro lane **no ejecuta** lo que el modelo propone sin pasar por riesgo y por la barra
   siguiente; del original no se observó ninguna regla equivalente.
3. Nuestra comparación económica **se niega a emitir veredicto** cuando los insumos difieren;
   el comparador anterior podía publicar `VISION_ADDS_VALUE` con cadencia distinta. Ese
   defecto está cerrado y tiene test.

## Lo que NO se afirma

* No se afirma equivalencia funcional, ni superioridad, ni que el original sea peor.
* No se afirma que el patrón de nof1 añada valor: `DEFER`, sin datos económicos.
