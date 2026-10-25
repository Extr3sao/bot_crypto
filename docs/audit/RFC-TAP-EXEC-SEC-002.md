# RFC-TAP-EXEC-SEC-002 — Autorización explícita de trading live y exenciones seguras de reducción

**Estado:** PROPOSED · NO IMPLEMENTADO · NO AUTORIZA TRADING REAL  
**Prioridad:** P0 (seguridad de órdenes)  
**Proyecto:** Trading Agentic Portable  
**Predecesor:** P0-LIVE-GATE (`P0_VERIFIED_SCOPED`)  
**Referencia de partida declarada:** commits `82e8b3ac` (export verificado), `1b4e1896` (árbol limpio reportado), `43e1ce2c` (HEAD final reportado). **Verificar la relación real entre ellos antes de trabajar.**

## 1. Contexto y evidencia

La auditoría P0 encontró `LiveTradingGate` sin importadores en `src/`: diez configuraciones rechazadas terminaban con una llamada al broker y `exit 0`. La corrección integró `_evaluate_live_gate` en los entrypoints y en `_live_order_boundary`. El informe reporta diez rechazos con **0 llamadas al broker, `exit 2`**, 473 tests, 7/7 mutantes, 19/19 hashes y verificación 15/15 sobre un export limpio. Estas son **afirmaciones del informe recibido**, no una nueva ejecución de este RFC.

Quedan riesgos sin cerrar:
- **DEF-P0-04:** `run --auto-trade` no requiere `--confirm-live`.
- La exención del gate para `close-position`, `set-tpsl`, `CLOSE` y `sell` se prueba por el camino invocado, pero el informe no demuestra que toda orden exenta sea incapaz de **aumentar exposición, invertir una posición o empeorar el riesgo**.
- La validación se realizó con brokers grabadores; no demuestra aceptación por Bitunix ni por otros exchanges.

**Problema:** la seguridad no debe depender únicamente del nombre del comando, del lado `sell` ni de un check en el CLI. Debe mantenerse en la frontera final anterior a la llamada del broker.

## 2. Objetivos

1. Exigir confirmación explícita para cualquier apertura o incremento de riesgo en modo live por `run --auto-trade`.
2. Conservar `LiveTradingGate` como comprobación **fail-closed**, tanto en entrada como en el sink.
3. Permitir saltar las comprobaciones de *apertura* únicamente a órdenes cuya semántica de reducción esté verificada y, cuando proceda, respaldada por un mecanismo de reducción impuesto por el exchange.
4. Preservar el hot stop y las reducciones de emergencia válidas sin convertirlas en bypass para aperturas.
5. Demostrar el comportamiento en el runtime realmente alcanzable, con evidencias trazables.

## 3. Fuera de alcance

- Activar trading live, enviar órdenes reales, usar credenciales reales, hacer push, merge o despliegues.
- Rediseñar `DecisionEngine`, riesgo de cartera, estrategia, agentes, orquestador o broker genérico.
- Resolver G-4 (`run --demo`), DEF-P0-03 (SQLite/cwd) o GATE-009/010; conservarlos en el registro de defectos.
- Refactorizaciones y nuevas dependencias ajenas al cierre de estos controles.

## 4. Contratos y requisitos

### REQ-01 — Confirmación live explícita

- `run --auto-trade`, **si produce o puede producir órdenes live**, debe requerir `--confirm-live` como consentimiento explícito de esa invocación. Sin el flag: diagnóstico sin secretos, `exit 2`, **0 llamadas al broker** y sin iniciar scanner/cliente de órdenes.
- La comprobación distingue de forma determinista `LIVE` de `PAPER/DEMO`; no bloqueará estos últimos por carecer del flag.
- El flag **no** sustituye a `LiveTradingGate`, permisos, riesgo, límites, datos frescos ni hot stop; tampoco habilita trading real por defecto.
- Conservar los flags y la interfaz compatible donde no haya conflicto de seguridad; identificar y documentar los entrypoints existentes.

### REQ-02 — Autorización en el sink

- Toda ruta de apertura/incremento de riesgo debe atravesar una única evaluación de autorización efectiva antes de `order_boundary`/llamada al broker. Los controles tempranos son defensa adicional, no autoridad única.
- El sink recibe el contexto tipado indispensable para diferenciar live/paper, identidad de ejecución, confirmación, settings y semántica de orden; **sin defaults permisivos**. No debe confiar en un `approved=True` derivado solo del CLI.
- Errores, settings ausentes, datos inconsistentes o excepciones de gate producen denegación sin llamada al broker; nunca se convierten en PASS por `except`, valor por defecto o error de tipo.

### REQ-03 — Clasificación real de reducciones

Antes de eximir una orden del gate de *apertura*, clasificarla de forma determinista como:
- `OPEN_OR_INCREASE`: apertura, incremento, reversión o cualquier cambio no demostrado como reducción.
- `PROVEN_REDUCTION`: cierre/reducción cuya imposibilidad de aumentar exposición está respaldada por las capacidades y parámetros del broker/exchange.
- `UNKNOWN`: falta de información, semántica no soportada o estado inconsistente; **se trata como no exenta**.

La clasificación deberá considerar, según aplique, instrumento spot/futuros, dirección y magnitud de la posición, lado, cantidad, `positionSide`/modo hedge y características del venue. **`sell`, `CLOSE` o `close-position` no son prueba suficiente.** Para exención, exigir una primitiva de cierre/reducción reconocida por el venue o una protección equivalente impuesta por el broker, como `reduceOnly` soportado y propagado realmente al payload. Una comprobación local con snapshot de posición, por sí sola, no garantiza protección ante carreras.

Casos con posición inexistente, cantidad excesiva, inversión involuntaria, modo hedge ambiguo, protección `reduceOnly` no soportada/no enviada o datos obsoletos deben **bloquear la exención**. Si no puede demostrarse una reducción segura, no enviar la operación mientras el gate de apertura la rechace. Para aperturas autorizadas, aplicar todos los controles habituales; nunca reinterpretar `UNKNOWN` como permiso.

### REQ-04 — Tratamiento de TP/SL

`set-tpsl` no se considera automáticamente reducción: mover, retirar o sustituir protección puede aumentar riesgo sin modificar tamaño. Definir y verificar una política determinista específica para cambios protectores admitidos. Si la operación no puede demostrarse segura con el contrato real del broker, **no eximirla** del control aplicable. Documentar cualquier cambio de comportamiento respecto a P0.

### REQ-05 — Prioridad del hot stop y evidencia

- El estado de hot stop continúa bloqueando nuevas aperturas/incrementos antes de autorizar una orden. Preservar el comportamiento G-3 existente del proceso ya parado (`skip`, `exit 0`), con evidencia de no llamada.
- Una reducción de emergencia **realmente probada** no queda bloqueada solo por fallar el gate de apertura, siempre que respete los controles independientes que evitan que incremente riesgo.
- Registrar por cada decisión: `run_id`, entrypoint, categoría de orden, razón, gate evaluado/exento, regla aplicada, hash/contexto de configuración no sensible y resultado del boundary. Nunca registrar secretos.

## 5. Flujo requerido

`CLI/runtime → comprobar hot stop → resolver entorno y confirmación → construir intención y contexto de orden → clasificador determinista → {PROVEN_REDUCTION: guardias de reducción | OPEN_OR_INCREASE/UNKNOWN: confirmación live + 10 checks del gate + controles normales} → sink revalida → broker recorder/paper`.

Ajustar el orden exacto al runtime existente sin introducir rutas alternativas. No relajar controles de riesgo generales al eximir solo el gate pensado para *apertura*.

## 6. Tests obligatorios

| ID | Escenario | Aceptación |
|---|---|---|
| T01 | `run --auto-trade` live sin `--confirm-live` | `exit 2`, 0 llamadas, 0 scanner/cliente de órdenes |
| T02 | Live con confirmación pero 1/10 checks rechazado (cada check) | 0 llamadas, gate identificado, `exit 2` |
| T03 | Settings ilegibles, gate lanza o report incompleto | 0 llamadas, `exit 2` |
| T04 | Paper/demo sin confirmación | No sufre bloqueo *por ese flag*; comportamiento anterior intacto |
| T05 | Cierre largo/corto, spot/futuros, one-way/hedge cuando el venue lo soporte | Exención solo con reducción garantizada por el broker |
| T06 | `sell` abre short, reversión, cantidad excesiva, posición cero | Nunca obtiene exención de reducción |
| T07 | `reduceOnly` omitido, degradado, no soportado o eliminado del payload | 0 llamadas si el gate de apertura rechaza |
| T08 | Posición/estado stale, ausencia de `positionSide`, excepción, carrera simulada | No exención insegura; resultado trazado |
| T09 | `set-tpsl` aumenta o retira protección | No se trata automáticamente como reducción |
| T10 | Hot stop activo, incluso con `--confirm-live` | 0 llamadas; preservar `skip/exit 0` de G-3 donde aplique |
| T11 | Entrada CLI protegida pero llamada directa al sink | La frontera final bloquea el bypass |
| T12 | Regresión P0/G-3/CLI y mutation tests | Suites existentes PASS, mutantes nuevos eliminados |

Probar la integridad del payload **en el último punto antes del broker**, no solo el objeto intención. Emplear broker recorder y fixtures herméticos; no contactar exchanges reales.

## 7. Plan de implementación acotado

**WP-00 · Auditoría read-only.** Identificar los entrypoints y sinks realmente alcanzables, el contrato actual de `--confirm-live`, la clasificación implícita de `CLOSE/sell/set-tpsl`, capacidades reales de adaptadores y baseline exacta de git/tests. Registrar gaps antes de editar.

**WP-01 · Confirmación live.** Añadir el control en `run --auto-trade` con tests negativos y positivos; cerrar la posibilidad de esquivar el control llamando al sink.

**WP-02 · Exenciones verificables.** Sustituir exenciones por nombre/lado por una clasificación determinista anclada a las capacidades y payloads reales. Cubrir TP/SL, one-way y hedge solo donde el adaptador lo soporte; en el resto, `UNKNOWN`/no exento.

**WP-03 · Verificación separada.** Repetir regresión, tests adversariales, mutation tests y ejecución offline sobre un export limpio del commit final. Comprobar diferencias respecto al baseline, hashes y trazabilidad. No pasar al siguiente WP si el anterior tiene evidencia roja sin resolver.

## 8. Criterios de aceptación (ACC)

- **ACC-01:** ningún `run --auto-trade` live sin confirmación puede llegar al broker; los modos paper/demo no quedan bloqueados por el flag.
- **ACC-02:** ninguna orden `OPEN_OR_INCREASE` o `UNKNOWN` atraviesa el sink live con gate rechazado, roto o sin evaluar.
- **ACC-03:** ninguna exención por reducción puede abrir, incrementar o invertir exposición, incluso al mutar el payload final; si no puede probarse se bloquea.
- **ACC-04:** `set-tpsl` no queda exento por su nombre y la política protectora queda cubierta con tests negativos.
- **ACC-05:** hot stop y cierres de emergencia probadamente seguros conservan su funcionamiento esperado, con cero apertura bajo stop.
- **ACC-06:** tests de regresión y mutación relevantes PASS sobre el commit exacto; fallos previos y nuevos se conservan en evidencia.
- **ACC-07:** verificador separado reproduce resultados usando export limpio, manifiesto de hashes y runner claramente identificados; `FALSE_SUCCESS=0` para todos los escenarios ejecutados.

Cualquier test omitido, conector no cubierto o capacidad no verificable se declara `NOT_VERIFIED`/`BLOCKED`, nunca `PASS`. La verificación offline **no certifica aceptación de órdenes por un exchange real**.

## 9. Fallos, rollback y gobernanza

- Fallar cerrado ante dudas de semántica, firma/payload, settings o broker capabilities.
- Mantener detección y registro explícitos de cambios incompatibles en CLI; no degradar silenciosamente a un camino sin gate.
- Rollback por reversión de commits del RFC, **solo a un baseline que mantenga la corrección P0**; nunca restaurar el bypass original del live gate.
- Prohibido push, despliegue, órdenes live o uso de secretos. Cualquier activación futura requiere autorización humana expresa y certificación de integración por separado.

## 10. Entregables para Codex

- RFC registrado y enlazado en roadmap/registro de defectos.
- `runtime_authority_map` incremental para los entrypoints/sinks afectados; baseline y diff.
- Código y tests mínimos de WP-01/02, commits separados por WP.
- `COVERAGE_MATRIX.md`, `BEFORE_AFTER.md`, manifiesto SHA-256.
- `RUN_REPORT.md`, `RUN_REPORT.json`, `FINAL_REPORT.md`, `verification.json` con `run_id`, commit exacto, entorno, tests, mutantes, fallos, skip, artefactos y limitaciones.

**Estado de salida permitido:** `P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED` solo tras ACC-01…07 con evidencia reproducible; de lo contrario `PARTIAL`/`BLOCKED`. Mantener `LIVE_NO_GO` y `PRODUCTION_READY = false` independientemente del resultado de este RFC.

## 11. Instrucción de ejecución para Codex

Implementa **exclusivamente este RFC** en el repositorio actual. Empieza por WP-00 y evidencia la versión/runtime autoritativos. Resuelve de manera autónoma decisiones locales, reversibles y seguras. No añadas funcionalidades ni RFCs nuevos. Desarrolla WP-01/02 por separado, prueba con grabadores y datos herméticos, verifica con un proceso separado sobre export limpio, y entrega informes, diffs, hashes y commits exactos. **No contactes brokers live, no operes, no hagas push ni despliegues.** Si un control no se puede demostrar, bloquea la ruta y registra el defecto; nunca declares un PASS ficticio.
