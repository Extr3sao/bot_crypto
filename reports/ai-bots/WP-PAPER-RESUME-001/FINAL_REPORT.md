# FINAL_REPORT — WP-PAPER-RESUME-001

**Una sesión PAPER que muere con exposición ya no la pierde.**

**Fecha:** 2026-10-20 · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Modo:** PAPER · **LIVE:** no habilitado · **`FALSE_SUCCESS=0`**
**Veredicto:** el A/B sobre minutos reales da **PASS** con las cuatro criterios medidos
(`RT-07`, `REC-03`, `REC-04`, `REC-05`) y los nueve controles negativos detectados.

Artefactos: [RUN_REPORT.md](RUN_REPORT.md) · [RUN_REPORT.json](RUN_REPORT.json) ·
[DRILL.md](drill/DRILL.md) · [VERIFICATION.json](VERIFICATION.json) ·
[RFC-050](../../../docs/rfc/RFC-050_VISION_DURABLE_SESSION.md) ·
[mapa de autoridad](../../../docs/runtime/runtime_authority_map.md)

---

## 1. Qué estaba roto

La ruta de visión mantenía el libro **en memoria**. Al terminar el dataset publicaba `RUN_END`
con las posiciones abiertas y se iba. En `roundtrip-5m` eso dejó **dos cortos sin nadie que los
cerrara**: el proceso que podía hacerlo ya no existía, y un reinicio construía un `PaperBroker`
vacío. El propio mapa de runtime lo tenía anotado como hueco, sin dueño.

La consecuencia no era sólo «se pierden dos posiciones»: el siguiente arranque dimensionaba contra
un capital que ya no era el real, y el PnL de esas dos posiciones desaparecía del historial. Un
libro que se puede perder al reiniciar no es un libro.

## 2. Qué se construyó

**`src/trading_bot/vision/durable.py`** (nuevo, 878 líneas) — el libro en disco:

| pieza | contrato |
| --- | --- |
| `LaneBookStore.save` | `tmp` + `fsync` + `replace` atómico + `.prev`, y **después** la fila `COMMIT` en `BOOK_EVENTS.jsonl` con `fsync`. El orden importa: si el proceso muere entre ambos, el libro es más nuevo que el log, nunca al revés. |
| `LaneBookStore.load` | verifica el `state_digest` del cuerpo antes de devolver nada. Un libro que no se autentica se trata como inexistente, no como vacío. |
| `SessionLock` | `O_CREAT\|O_EXCL` con pid y `session_id`; releva a un dueño **probado muerto** (`TerminateProcess`, no `SIGTERM`) y deja `lock_taken_over` en el log. Dos escritores sobre un libro operarían la misma vela dos veces. |
| `reconcile_book` | 9 checks en orden de coste: identidad → dinero → estructura → tiempo. **Un solo fallo bloquea la recuperación entera**: no hay restauración parcial. Un libro con la identidad de capital rota y las posiciones aparentemente bien ya perdió un fill, y restaurar las posiciones escondería la pérdida. |

**`src/trading_bot/vision/lane.py`** — punto de commit único por vela (`_commit`) y arranque que
**se niega a empezar plano** si hay libro (`_apply_recovery`). Al final del dataset, en modo
durable, las opiniones en vuelo se conservan; el comportamiento histórico
(`RUN_ENDED_WITH_ORDER_PENDING`) queda intacto para quien no active el modo.

**`src/trading_bot/vision/prospective.py`** — modo durable opt-in: `STATE/` propio, lock, lectura
del libro comprometido en cada ciclo, y `RECOVERY_BLOCKED` como fila de `CYCLE` con cero fills si
la reconciliación no pasa. Sin libro, el comportamiento es el de siempre (11 tests previos verdes).

## 3. La evidencia, en una línea

Misma campaña de 144 velas 5m de minutos reales, dos veces: `A` de un tirón, `B` partida por un
proceso **matado a los 9 s con dos posiciones abiertas** y otro que reanuda. Los dos libros
terminan con el **mismo `state_digest`**, 16 cierres y 2 posiciones abiertas. Cero diferencias
campo a campo.

## 4. Por qué esto no es un test que se aprueba a sí mismo

- El drill **no** compara un proceso consigo mismo: mata con `TerminateProcess` y comprueba
  `killed=True`. Si el hijo sale limpio antes del plazo, el veredicto es `FAIL` y el `DRILL.json`
  lleva una `note` diciendo que no se midió nada. (Ese caso ocurrió de verdad en esta pasada: el
  arnés heredaba libros de la corrida anterior y publicaba `PASS` sin haber matado a nadie. Está
  corregido y el borrado de `A/`/`B/` es incondicional.)
- El verificador (`scripts/verify_paper_resume.py`) **no importa** el verificador de la librería.
- Nueve controles negativos, y **siete de ellos no los mata el hash** sino la aritmética: equity
  que no se financia, posición duplicada, posición a la vez abierta y cerrada, nocional que no es
  precio × cantidad, riesgo que no coincide con la marca, cierres borrados, y un libro sin
  reinicio real detrás.
- El libro real expuso un defecto propio que ningún test unitario veía: `RECOVERY.checks`
  publicaba la frase del fallo al lado de `ok: true` («initial 10000.0 + … != equity 10008.285»).
  Corregido separando `detail` de `fail_detail`, con test que lo sostiene.

## 5. Estado de verificación

| comprobación | resultado |
| --- | --- |
| tests del WP (durable + recovery + sesión + prospective) | **51 passed**, exit 0 |
| suite amplia (vision + paper + risk + market_data) | **641 passed**, 14 fallos **por fixture ausente** — con `data/quote-feed-1m` presente, esos dos ficheros dan **22 passed**, exit 0 |
| `ruff` sobre 10 ficheros nuevos o tocados | exit 0 |
| `mypy` sobre `durable`/`prospective`/`lane` | exit 0 |
| verificador independiente | **26/26**, **9/9** controles, `FALSE_SUCCESS=0` |
| drill A/B | **PASS** (4/4 criterios) |

## 6. Límites explícitos

- **LIVE:** nada. No hay ruta de orden en esta cadena; `live_orders=0` en todo el drill.
- **Red:** el drill corre sobre minutos ya archivados; no mide latencia ni reconexión.
- **Modelo:** el provider es el determinista del replay, no el modelo real.
- **Alcance del lock:** cubre dos procesos sobre el mismo directorio. No pretende coordinar
  libros distintos que compartan `book_id` en máquinas distintas.
- **`data/quote-feed-1m`:** no está en esta copia del repo. Los 14 fallos de la suite amplia se
  reportan como lo que son, y se verificó con el fixture copiado y borrado después.

## 7. Qué queda abierto

1. **Reconciliación contra el exchange** cuando exista ruta de orden: hoy el libro se reconcilia
   consigo mismo y con el dataset, no con un exchange que podría haber ejecutado el stop.
2. **Retención:** `BOOK_EVENTS.jsonl` y `.prev` crecen sin política de poda.
3. **Reanudación con hueco probado:** si falta la vela siguiente a la barrera, el libro se bloquea
   (`UNVERIFIED_GAP`) aunque un feed de minutos pudiera demostrar que no se cruzó ningún stop.
   Ese feed existe en la ruta de quotes; conectarlo al reconciliador es el siguiente paso natural.
