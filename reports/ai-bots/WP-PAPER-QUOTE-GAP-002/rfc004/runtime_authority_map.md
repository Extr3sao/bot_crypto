# Mapa de autoridad del runtime — WP-PAPER-QUOTE-GAP-002 / RFC004

Lectura del árbol real a `0c074fb` (`src/`, `tests/`, `scripts/`), sin ejecutar nada que
escriba. La pregunta que responde es la del gate de diseño del RFC: **¿qué operación es
durable y qué evento define `COMMIT`?**

## Clasificación

| Artefacto | Clase | Qué es | Quién lo juzga |
|---|---|---|---|
| `state/BOOK.json` | **RUNTIME_AUTHORITATIVE** | el estado económico completo, con `digest` (integridad) y `state_digest` (economía) dentro | `LaneBookStore.load` → `CorruptBook`; `reconcile_book` → `RECOVERED`/`BLOCKED` |
| `state/BOOK.json.prev` | RUNTIME_AUTHORITATIVE (una generación atrás) | copia fsynced de la generación anterior; **no** se lee mientras exista `BOOK.json` | `load()` sólo para detectar una rotación interrumpida |
| `state/BOOK.json.tmp` | NO AUTORITATIVO | fichero de trabajo del `save`; un `tmp` huérfano nunca se adopta | `recover()` lo nombra y lo ignora |
| `state/BOOK_EVENTS.jsonl` | PROYECCIÓN de auditoría | una fila por `COMMIT`/`RECOVERY`/`REPAIR`; dice *cómo* se hizo verdad | `recover()` (congruencia y cola rota) |
| `state/BOOK.lock` | exclusión mutua | pid+host+token; no es estado | `SessionLock` (`pid_alive`) |
| `*.jsonl` de sesión | PROYECCIÓN append-only | cadena hash de decisiones, fills y cierres, con `operation_id` | `verify_chain`, y ahora la deduplicación del propio ledger |
| `*.jsonl.torn.json` | EVIDENCIA de reparación | qué cola se recortó, cuántos bytes, en qué offset | el verificador la lista |
| `tests/unit/vision/*` | TEST_ONLY | incluida la regresión de recuperación | pytest |
| `scripts/quote_gap_lab.py`, `paper_resume_drill.py`, `verify_quote_gap.py` | RESEARCH_ONLY (labs de RFC002/003) | no los ejecuta el lane | sus propios verificadores |
| `src/trading_bot/app.py::_cmd_place_order` | RUNTIME_REACHABLE + LIVE | orden real, gateada por `--confirm-live` | `risk-manager`/`security-reviewer`; **fuera** del alcance de este WP |
| `src/trading_bot/market_data/exchange_connector.py`, `research/economic_recovery/paper_exec.py` | RUNTIME_REACHABLE fuera del lane | importan `ccxt` | no se tocan; el laboratorio los niega a nivel de proceso |

No se ha encontrado código muerto en la ruta durable: `durable.py`, `ledger.py` y
`lane.py` se ejecutan en cada corrida y sus tests existen.

## La semántica real de `COMMIT`

```
bar n:
  decisiones → fills → cierres       (efectos en memoria)
  ledger.append(CLOSE/FILL)          (fsync por fila — proyección, puede ir POR DELANTE del libro)
  _commit(barrier_ms=n):
      store.save(body):
          escribir BOOK.json.tmp → flush → fsync        ← (1)
          copiar BOOK.json → BOOK.json.prev → fsync      ← (2)
          os.replace(tmp, BOOK.json)                     ← (3)  **COMMIT**
          fsync del directorio (no-op en nt)             ← (4)
      store.event("COMMIT", digest)  → append+fsync      ← (5)  **ACK**
```

- **`COMMIT` = (3)**. `save()` sólo vuelve después del `replace`, y desde ese instante
  `load()` devuelve un libro con el `digest` del estado nuevo. El ACK (5) es posterior y su
  ausencia no invalida el commit: el libro lleva su propio digest.
- **El ledger va por delante**, no por detrás: sus filas se escriben antes del commit del
  compás. Por eso una caída entre (1) y (3) deja filas que la cuenta no comprometió, y la
  reanudación las re-ejecuta. La identidad `operation_id` (`<book>|CLOSE|<position>`) es lo
  que impide que esa re-ejecución escriba una segunda fila, y `OperationConflict` lo que
  impide que la escriba con otro número.
- **La barrera manda sobre el replay.** Una sesión reanudada no vuelve a procesar compases
  `<= barrier`; el libro ya contiene sus efectos. Esa es la razón por la que el ledger puede
  repetir una fila sin que la economía se repita.
- **Un commit intermedio es un commit.** El plan de hueco cierra posiciones y llama a
  `_commit()` *antes* de la primera vela posterior, con la barrera sin avanzar. Ese estado
  tiene que ser reanudable por sí mismo; no lo era (ver `BASELINE.md`, defecto 1).

## Desviación declarada respecto del RFC

§5.1 propone `canonical_book_state = deterministic_replay(valid_committed_ledger_prefix)`.
En este runtime el ledger **no** es autoritativo: es la proyección de *una* sesión, y dos
sesiones pueden escribir en ficheros distintos. Invertir la autoridad exigiría que el
ledger contuviera todo lo que el libro contiene (riesgo, pendientes, contrato, marcas) y
romper la compatibilidad con los libros históricos de RFC003.

Decisión: se conserva la autoridad del libro, y el invariante que se demuestra es el que el
RFC pide de verdad —*exactly-once a nivel de efecto económico*— con la proyección
verificada contra la autoridad:

```
book        = source of truth
ledger      = projection, at-least-once, deduplicated by operation_id
events      = audit of how the book became true
recover()   = classify(book, events, projection) ∈ {NO_CHANGE, RECOVERED, REFUSED_*, BLOCKED_LOCK}
```

Una migración a ledger autoritativo sería un WP propio con migración reversible de los
libros existentes; este WP no la hace porque ningún fallo medido la exige.
