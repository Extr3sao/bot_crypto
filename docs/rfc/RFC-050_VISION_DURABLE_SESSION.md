# RFC-050 — Sesión PAPER durable: el libro sobrevive al proceso

- **Work package:** `WP-PAPER-RESUME-001`
- **Estado:** implementado y verificado (ver `reports/ai-bots/WP-PAPER-RESUME-001/FINAL_REPORT.md`)
- **Base:** `fefb077` · **Modo:** PAPER, `LIVE_ENABLED=false`, 0 órdenes, 0 credenciales
- **Ámbito:** `src/trading_bot/vision/{durable,lane,prospective}.py`, `scripts/paper_resume_drill.py`
- **Sustituye a:** el hueco declarado al final de `docs/runtime/runtime_authority_map.md`
  («sesión abierta: no corregido»)

---

## 1. El defecto, medido

La corrida `roundtrip-5m` (5 m, ETH+SOL, 4 h, commit `b0e1549`) abrió cuatro posiciones y
cerró dos por `stop_loss`. Al congelar la evidencia **quedaban dos cortos abiertos**
(−1,55330798 USDT no realizado). `RUN_END` los publicó… y nada los restauró:

- `VisionLane.__init__` construía `PaperBroker(...)` **en memoria**; no había
  `PaperStateStore`, ni `StartupReconciler`, ni `restore` en `vision/*`;
- `ProspectiveSession.run()` borraba `STREAM.jsonl` y fijaba `decision_from_ms = started`,
  así que un proceso nuevo **no decidía** sobre las velas anteriores y arrancaba plano;
- consecuencia: la exposición desaparecía con el proceso, su stop dejaba de evaluarse, y
  la comisión de entrada ya pagada volvía al saldo como si nunca se hubiera cobrado.

No era un problema de tests: era que el libro no existía en ningún sitio que sobreviviera
al `finally`.

## 2. Decisión

**El libro es la verdad económica y se escribe en disco.** El ledger deja de ser la
autoridad del estado y pasa a ser su proyección por sesión: una fila `CLOSE` que no está
en el libro nunca ocurrió, y una posición que está en el libro es exposición aunque ningún
ledger la mencione.

Tres piezas, ninguna nueva base de datos:

| pieza | fichero | papel |
| --- | --- | --- |
| `LaneBookStore` | `vision/durable.py` | documento JSON atómico (`tmp`+`fsync`+`replace`), generación previa, digest de integridad, digest económico, eventos |
| `SessionLock` | `vision/durable.py` | un solo escritor por libro; relevo verificado de un dueño muerto |
| `reconcile_book` | `vision/durable.py` | una sola respuesta: `FRESH`, `RECOVERED` o `BLOCKED` con el check que falló |

Se reutiliza lo que ya existía y funciona: `PaperBroker.restore` (con la secuencia de
identificadores continuada), `RiskManager.restore_state` y el patrón atómico de
`paper/paper_state_store.py`. No se introduce SQLite porque el documento es un único
objeto de estado con un solo escritor: un fichero reemplazado atómicamente ya da
«todo o nada», y una tabla añadiría transacciones que aquí no hacen falta.

## 3. Punto de confirmación: el final de cada vela

Todo efecto económico de una vela —gaps de apertura, entradas, salidas intrabar, marcas y
las opiniones formadas en su cierre— es función pura del libro al abrir la vela, de los
datos que el lane puede ver y de las respuestas ya recibidas. Por eso:

```
OPEN(ts) → gaps → mark → entradas → CLOSE(ts+Δ) → salidas → marks → decisiones → COMMIT
```

`COMMIT` escribe el libro completo y sella `barrier.bar_open_ms = ts`. Un proceso que muere
en la vela *n* deja el libro en *n−1*; la vela *n* se **re-ejecuta** desde ese libro. La
alternativa —commit a mitad de vela— obligaría a persistir un estado parcial que no es
reconciliable, y la alternativa —no commitear nunca hasta el final— es exactamente el
defecto original.

De ahí sale el invariante que hacen falta tres condiciones para romper y ninguna se da:

1. el relleno de una vela no comprometida no existe en el libro, así que no puede
   duplicarse;
2. la vela comprometida no se vuelve a procesar (`timeline` arranca en `barrier + Δ`);
3. los identificadores se re-emiten desde la secuencia restaurada, así que un relleno
   repetido tendría el mismo `position_id` y el mismo `trade_id` — y no ocurre.

**Consecuencia declarada:** un libro durable exige un `provider` determinista para que la
re-ejecución de una vela incompleta sea byte-idéntica. `strategy_experimental`
(`ema_crossover`) lo es; un modelo no, y por eso la re-ejecución de una vela no
comprometida en un libro de modelo puede producir *otra* decisión — nunca dos ejecuciones
de la misma. Un modelo con posición abierta sigue siendo recuperable: la posición está en
el libro y su stop se evalúa; lo que no se promete es que la opinión en vuelo sea la misma.

## 4. Qué se persiste

```jsonc
{
  "schema": "vision-lane-book/1",
  "digest": "…",          // integridad: todo el cuerpo
  "state_digest": "…",    // economía: sin linaje ni contadores operativos
  "body": {
    "contract": { "book_id", "timeframe", "interval_ms", "equity", "cost_multiplier",
                  "window_bars", "decision_every_bars", "risk_policy", "provider",
                  "dataset": { "<símbolo>": { "bars", "last_open_ms", "sha256" } } },
    "barrier": { "bar_open_ms", "bar_close_ms", "bars_committed", "session_end" },
    "broker": { "equity", "initial_equity", "fills_opened", "fills_closed" },
    "open_positions": [ /* PaperPosition.to_row(), con position_id y comisión devengada */ ],
    "closed_trades": [ /* filas netas, con ambas comisiones y el coste de ejecución */ ],
    "closed_digest": "…",
    "risk": { /* contadores del RiskManager */ },
    "risk_equity": 0.0, "marked_equity": 0.0,
    "pending": { "<símbolo>": { /* PendingOrder + VisionDecision completa */ } },
    "entry_provenance": {}, "marks": {}, "counters": {}, "calls": 0, "spend_usd": 0.0
  }
}
```

- **`dataset.sha256` es el prefijo hasta la barrera**, no el fichero entero: las velas
  posteriores son justamente las que este libro no ha visto, y hashearlas cambiaría el
  contrato en cada vela nueva.
- **`pending` viaja con el libro** porque una opinión ya pagada no es reconstruible: si el
  proceso muriera antes de su primer hueco ejecutable, el reinicio o la pierde o la paga
  otra vez.
- **`calls`/`spend_usd` viajan** para que un bucle de reinicios no reinicie el presupuesto.
- **`state_digest` excluye** linaje de sesión y contadores operativos, para que «este
  reinicio no cambió nada» sea una igualdad de digests y no una comparación a mano.

## 5. Reconciliación: una sola respuesta

`reconcile_book` aplica, en este orden, y **para en el primer fallo**:

| # | check | qué demuestra | código si falla |
| --- | --- | --- | --- |
| 1 | `contract_matches` | es el mismo experimento (equity, costes, riesgo, timeframe, ventana, proveedor) | `CONTRACT_MISMATCH` |
| 2 | `barrier_present` | hay una vela comprometida | `BARRIER_MISSING` |
| 3 | `dataset_prefix_matches` | las velas que produjeron el libro son las del disco | `DATASET_MISMATCH` |
| 4 | `equity_identity` | `initial + Σ pnl_net == equity` | `EQUITY_IDENTITY` |
| 5 | `closed_history_intact` | las filas de cierre hashean a lo registrado | `CLOSED_HISTORY` |
| 6 | `position_structure` | ids únicos, símbolos del universo, lados válidos, sin posición a la vez abierta y cerrada | `POSITION_INVALID` |
| 7 | `risk_agrees_with_mark` | el motor de riesgo arranca con la equity de la marca, no con otra | `RISK_MISMATCH` |
| 8 | `resume_bar_available` | hay una vela posterior… o el reinicio ocurrió entre dos velas (espera) | — |
| 9 | `barrier_is_continuous` | la vela siguiente existe: no hay hueco donde un stop pudo cruzarse sin rango | `UNVERIFIED_GAP` |

Un libro ilegible no se repara: `CorruptBook`, los bytes se conservan como
`BOOK.corrupt.<ms>.json` y la sesión publica `RECOVERY_BLOCKED` sin tocar el mercado.

## 6. Concurrencia

El cerrojo es del **libro**, no de la instancia, y se toma antes de leer. Un segundo
proceso recibe `SessionBusy` y no arranca. Un dueño muerto se releva: en Windows la
comprobación de vida **no** puede ser `os.kill(pid, 0)` (cualquier señal que no sea
CTRL_C/CTRL_BREAK *termina* el proceso), así que se abre el handle con
`PROCESS_QUERY_LIMITED_INFORMATION` y se lee `GetExitCodeProcess`; si no se puede saber,
se trata como vivo y el relevo exige que el fichero supere la ventana de obsolescencia.

## 7. Reinicios: política explícita

| situación | respuesta |
| --- | --- |
| libro ausente | `FRESH`: la sesión abre la cuenta (`decision_from_ms = arranque`) |
| libro válido, velas nuevas | `RECOVERED`: continúa desde `barrier + Δ`; `decision_from_ms = None` (la barrera ya acota el pasado) |
| libro válido, sin velas nuevas | `RECOVERED`: espera en `barrier + Δ`, no escribe nada |
| libro ilegible / de otro experimento / con historia cambiada | `RECOVERY_BLOCKED` |
| hueco entre la barrera y la vela siguiente | `UNVERIFIED_GAP` (un stop pudo cruzarse sin rango que lo pruebe) |
| segundo proceso | `SessionBusy`, sin tocar el libro |
| sesión anterior terminó | el libro sigue siendo la cuenta: un proceso nuevo la continúa (no se abre otra) |

## 8. Alternativas rechazadas

1. **Persistir sólo `RUN_END`.** Muere el proceso a mitad de sesión y no hay libro: es el
   defecto original con otro nombre.
2. **Re-derivar el libro replicando el ledger en cada arranque.** Depende de que el
   proveedor reproduzca exactamente sus respuestas; con un modelo no ocurre, y con la
   estrategia exigiría re-renderizar cada gráfico de la historia.
3. **Commit por evento (fill a fill).** Obliga a persistir estados intermedios inválidos
   (posición abierta sin su `mark`, cierre sin su fila) y a una recuperación a mitad de
   vela que no es reconciliable con OHLC.
4. **SQLite.** Un documento único con un escritor único no gana nada con transacciones; sí
   añade un esquema que migrar.

## 9. Límites que este RFC no esconde

- La resolución de un stop intrabar sigue siendo `BAR_WINDOW`: la recuperación no conoce
  mejor el instante del toque que la corrida continua.
- Un hueco de datos **no** se rellena inventando precios: se bloquea, salvo que el feed
  demuestre cobertura.
- `state_digest` igual no demuestra rentabilidad: demuestra que dos campañas con los mismos
  datos y las mismas reglas dejaron el mismo libro.
- El libro no es una cuenta de exchange: es un libro PAPER. Nada aquí acerca al trading
  real por sí mismo.
