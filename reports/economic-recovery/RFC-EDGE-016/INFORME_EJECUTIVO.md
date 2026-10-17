# WP-EDGE-016 — informe ejecutivo

## 1. El defecto

El 100% de las 7081 salidas de WP-EDGE-015 se ejecutaba al **open de la misma barra** cuyo cierre había decidido la salida: un precio que ya había ocurrido cuando se tomó la decisión. Además, el carril de paper calculaba la lista completa de operaciones antes de reproducirlas, de modo que la propuesta de entrada ya contenía el resultado futuro.

## 2. Lo reparado

- Contracto temporal explícito: decisión al cierre de la barra *t*, ejecución al open de *t+1*; una posición abierta al final se **marca**, no se ejecuta.
- Las estrategias son incrementales: sólo ven el prefijo ya cerrado y la propuesta no puede contener precio de salida, bruto ni resultado.
- El riesgo es el del runtime: RiskManager.check_signal, sin copias ni subconjuntos manuales.
- Un solo libro de 10 000 USDT para los tres símbolos; los tres libros de 015 se etiquetan como tres simulaciones independientes y sus saldos no son capital.
- Stop y objetivo tocados en la misma barra se resuelven en contra de la posición (política del broker), y una barra desordenada se rechaza.

## 3. Lo que dicen los números

| familia (research reestimado) | operaciones | 1x | 2x | 3x |
| --- | --- | --- | --- | --- |
| mean_reversion_vol_liq | 947 | -240.86 | -1150.32 | -2059.78 |
| trend_pullback | 860 | -1954.84 | -2775.1 | -3595.35 |
| vol_regime_breakout | 242 | -187.08 | -418.33 | -649.58 |

Cifras en USDT sobre la cola reservada, con el tamaño que fija la política de riesgo. El carril experimental (146 operaciones) pasa de -53.384527 USDT brutos a -239.7503 / -426.1162 / -612.482 con coste real de venue a 1x/2x/3x.

Veredicto: **NO_RESTATED_EDGE_SURVIVES**. Ninguna estrategia se adopta y el runtime actual sigue plano (0 operaciones admitidas).

## 4. Evidencia prospectiva

3 barras observadas y 3 evaluadas: cero decisiones, cero ejecuciones, cero PnL prospectivo. El guardián de disco está en CAPTURE_BLOCKED_DISK y no se ha relajado; no se ha creado ninguna tarea programada. La captura prospectiva queda como **no automatizada**, con el motivo escrito.

## 5. Verificación

Un verificador independiente, que no importa ninguno de los módulos que construyeron los artefactos, reconstruye el orden temporal a partir de las velas crudas, rehace la tabla económica desde los registros por operación y después **muta** los artefactos: 38 de 38 fallos inyectados se detectan. Un artefacto que miente no pasa.

## 6. Lo que bloquea

- the disk guard reports INSUFFICIENT_FREE_SPACE for the declared collection window: no new collector is started
- a scheduled collector needs a governance decision and free space before it exists
- 7/7 trading conflicts with blocks.weekend_trading=false and needs an ADR
- 5 policy fields are declared in config/risk.yaml and read by no runtime component
- the prospective sample is empty, so no strategy can be adopted on it

Ninguna de estas cosas se resuelve escribiendo más código: hace falta espacio en disco, una decisión de gobierno (fin de semana) o tiempo de mercado hacia delante.
