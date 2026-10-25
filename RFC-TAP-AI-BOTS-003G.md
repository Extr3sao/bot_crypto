# RFC-TAP-AI-BOTS-003G — Real 1m Market Data & Prospective PAPER Execution

**Estado:** implementado y medido; veredicto en `FINAL_REPORT.md`.
**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Base medida al abrir:** `fe9b5e2`
**Modo:** PAPER/SHADOW. **LIVE: no habilitado, sin ruta de orden.** `config/risk.yaml` sin
cambios.

> **Procedencia.** A diferencia de 003F —que se reconstruyó porque el documento no existía
> (ver `reports/ai-bots/RFC-AI-BOTS-003F/STATE_AUDIT.md` §1)— el texto de 003G lo entregó el
> operador al iniciar esta sesión. Se conserva esa circunstancia: este fichero no reconstruye
> un original perdido, sino que fija el diseño y las puertas con las que se ha ejecutado.

---

## 1. Problema

La cadena 003B–003F dejó el motor causal listo y probado con datos **históricos**: el carril
decide sobre velas cerradas, el broker y el riesgo son los de producción, y la ejecución
sub-bar puede rellenar en el primer minuto posterior a la respuesta. Faltaba la mitad que
convierte eso en un sistema PAPER real:

| Brecha medida al empezar | Evidencia |
| --- | --- |
| Ningún componente observaba el mercado en vivo; sólo había archivos históricos | `vision/quotes.py` carga `<SYM>_1m_*.json`; ningún runner lo alimenta en vivo |
| `subbar_entries` existía pero **ningún runner la activaba** | `grep subbar_entries scripts/*.py` → 0 usos fuera de tests y capturas |
| No había detección de vela en formación, stale, gaps, duplicados ni desorden sobre datos vivos | el feed histórico valida el archivo, no la llegada |
| No existía prueba de que `data_time <= decision_time` en una decisión real | el reloj causal se probó con series construidas, no con reloj de pared |

## 2. Objetivo

Conectar el carril con un colector real de velas de 1 minuto, operar **prospectivamente** en
PAPER y dejar trazas que permitan a un tercero reconstruir cada decisión desde los bytes
crudos.

## 3. Qué se ha implementado

### 3.1 Colector — `src/trading_bot/market_data/minute_collector.py`

- **Fuente:** `BinanceRestSource` (`GET /api/v3/klines`, `GET /api/v3/time`), pública, sin
  clave, sin cuenta, sin órdenes. La fuente es un protocolo (`KlineSource`), sustituible.
- **Dos relojes y tres timestamps:** `open_ms` (origen UTC de la vela), `close_ms =
  open + 60 s`, `server_time_ms` (reloj del exchange al responder) y `received_at_ms`
  (llegada al host). `delivery_latency_ms = received - close`.
- **Vela en formación:** una fila cuyo `close_ms > server_time_ms` **no se guarda**. Se
  registra `FORMING_BAR_IGNORED` una vez por minuto y no entra en ninguna serie.
- **Duplicados:** idénticos → `DUPLICATE_IDENTICAL`, se ignora. Con OHLCV distinto →
  `DUPLICATE_CONFLICT`, el símbolo se bloquea y el dato **no se sobrescribe**.
- **Desorden:** un minuto desconocido anterior al último → `OUT_OF_ORDER`, bloqueo. El
  almacén es append-only y no se reescribe jamás.
- **Gaps:** antes de aceptar un minuto que saltaría un hueco, se pide el rango que falta
  (`_fill_forward`). Si el proveedor no lo sirve, **tampoco se guarda el minuto posterior** y
  el símbolo queda `BLOCKED`, de modo que un precio posterior nunca cruza un hueco.
- **Reconexión:** `collect()` reintenta con backoff, registra `DISCONNECT`/`RECONNECT` y
  reconcilia hacia delante desde el último minuto antes de volver a operar.
- **Frescura y skew:** `STALE` si el último cierre supera `stale_after_ms`; `CLOCK_SKEW` si el
  reloj del host difiere del exchange más de 5 s. Ambos hacen el símbolo no operable.
- **Persistencia:** un JSONL por símbolo, escritura `fsync`, lock de escritor único,
  `MANIFEST.json` con `sha256` de los bytes, gaps, cola contigua y estado de salud;
  `EVENTS.jsonl` encadenado por hash.

### 3.2 Sesión prospectiva — `src/trading_bot/vision/prospective.py`

- **PAPER only:** `ProspectiveConfig(mode="LIVE")` lanza `LiveModeRefused` en el constructor;
  `run()` lo vuelve a comprobar. No hay cliente de exchange ni endpoint de orden en la ruta.
- **Medición real del retardo:** tras el warm-up espera a que cierren minutos **posteriores al
  inicio** y declara `data_delay_ms = p95(received - close)` de esas muestras. No se usa la
  latencia del bootstrap, que no es una latencia de entrega.
- **Decisión sólo desde el inicio:** `VisionLane(decision_from_ms=...)` (nuevo, opt-in) impide
  que la ventana de warm-up genere decisiones retrospectivas.
- **`data_time <= decision_time`:** una vela de 5 m sólo se usa cuando
  `decision_time >= data_time + data_delay + settle`; la fila `CYCLE` graba ambos instantes y
  el runner aborta si se viola.
- **Ejecución sub-bar:** la MISMA `VisionLane` de producción con
  `subbar_entries=True` y `MinuteBarQuoteFeed` construido con los minutos reales. Es el único
  punto que activa la capacidad, y sólo en PAPER.
- **Trazabilidad:** `STREAM.jsonl` encadenado (`SESSION_START`, `DELAY_MEASURED`, `CYCLE`,
  `BLOCKED`, `WARMING_UP`, `SESSION_END`) + un ledger por ciclo con la cadena completa
  `DECISION → DECISION_OUTCOME → FILL → CLOSE`.
- **Determinismo del prefijo:** cada ciclo re-ejecuta el carril sobre el prefijo cerrado y se
  compara fila a fila con el ciclo anterior (ignorando `RUN`, que describe el dataset, y la
  fase `RUN_END`, que cierra una orden que aún no tenía cotización). Una decisión pasada que
  cambie aborta la sesión (`PREFIX_DIVERGENCE`).

### 3.3 Comparación — `scripts/ai_bots_003g_compare.py`

Reconstruye la serie de 5 m desde los minutos crudos, comprueba que su hash coincide con el
publicado y ejecuta CURRENT (`subbar_entries=False`) y PROPOSED (`True`) con el mismo guion,
latencia declarada, capital, costes y política. Si la serie no coincide, no compara.

### 3.4 Verificador — `scripts/ai_bots_003g_verify.py`

No importa `trading_bot`. Reconstruye desde el JSONL crudo: cierre de cada minuto, serie de
5 m por ciclo, `data_time <= decision_time`, precio de cada relleno contra la apertura de 1 m
observada, rango post-relleno minuto a minuto, identidad `neto = bruto - comisiones - coste de
ejecución`, cadena de cada ledger, prefijo determinista, hashes del runtime usado y ausencia
de ruta LIVE.

## 4. Garantías exigidas

| Garantía | Dónde se impone |
| --- | --- |
| `data_time <= decision_time` | `prospective.run` (gate + aborto) y verificador |
| Una vela en formación no se usa como cerrada | `MinuteBar.__post_init__` / `_parse_page` |
| Nunca precios ni información futuros | serie filtrada por `close <= data_time`; re-ejecución por prefijo |
| Datos incompletos o proveedor caído → `NO_TRADE`/`BLOCKED` | bloqueo por gap/stale/skew; `BLOCKED` en `STREAM.jsonl` |
| Reconciliación tras desconexión | `MinuteCollector.collect` + `_fill_forward` |
| Persistencia reproducible | JSONL append-only + `MANIFEST.json` con sha256 |
| Sin LIVE | constructor y `run()`; sin cliente de órdenes; verificador de rutas |

## 5. Fuera de alcance (duro)

- Trading LIVE, claves de exchange, apalancamiento, admisión de estrategias.
- Modificar `config/risk.yaml`, `risk/manager.py`, el broker en su comportamiento por defecto
  o los límites.
- Declarar edge o rentabilidad con un proveedor `paper-script`.
- Sustituir el motor, el broker o el riesgo por dobles: la sesión usa los de producción.

## 6. Puertas de aceptación

| Puerta | Umbral | Medición |
| --- | --- | --- |
| G1 causalidad | 0 rellenos con `quote_ts_ms < received_at_ms` | verificador sobre el ledger |
| G2 frescura | 0 ciclos con datos stale/gap/skew | `STREAM.jsonl` + `MANIFEST.json` |
| G3 no-look-ahead | 0 decisiones con `data_time > decision_time` | `CYCLE.data_time_le_decision_time` |
| G4 precio real | 100 % de rellenos a una apertura de 1 m observada | verificador contra el JSONL |
| G5 costes | identidad neto = bruto − comisiones − ejecución en cada cierre | verificador |
| G6 regresión | 0 fallos nuevos en las suites tocadas | mismas suites, mismo comando |
| G7 LIVE | 0 órdenes y 0 rutas de orden | verificación estática + `live_orders=0` |

G4 económico de 003F (Δneto > 0, ΔDD ≤ +0,10 pp, ≥ 30 cierres) se reporta con su número; si
la muestra no llega a 30 cierres, el veredicto es `INSUFFICIENT_SAMPLE`, no PASS.

## 7. Reglas de evidencia

- `FALSE_SUCCESS=0`: cada cifra sale de un comando con su exit code real.
- `BUILDER != VERIFIER`: el verificador no importa el runtime; aun así, **no sustituye** una
  segunda revisión por otro agente. Sin ella el estado es `INDEPENDENT_VERIFICATION_PENDING`.
- Un resultado negativo se publica con su número.
- Nada de otro WP se reatribuye.

## 8. Criterio de terminación

`PAPER_VALIDATED` sólo con un ciclo prospectivo completo sobre datos reales, trazas, puertas de
riesgo y **verificación independiente por un tercero**. En su ausencia: `PARTIAL` con
`INDEPENDENT_VERIFICATION_PENDING`, conservando todo el trabajo verificable.
