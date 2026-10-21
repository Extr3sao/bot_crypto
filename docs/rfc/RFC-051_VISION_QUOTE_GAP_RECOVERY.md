# RFC-051 — Recuperación a través de un hueco de datos con evidencia de 1 minuto

- **Work package:** `WP-PAPER-QUOTE-GAP-002`
- **Estado:** implementado y verificado (ver `reports/ai-bots/WP-PAPER-QUOTE-GAP-002/FINAL_REPORT.md`)
- **Base:** `fefb077` + WP-PAPER-RESUME-001 (sin commitear en esta copia)
- **Modo:** PAPER, `LIVE_ENABLED=false`, 0 órdenes, 0 credenciales, 0 llamadas a modelo
- **Ámbito:** `src/trading_bot/vision/{gap_recovery,durable,lane,quotes}.py`,
  `scripts/{quote_gap_lab,verify_quote_gap,quote_feed_source}.py`
- **Continúa:** RFC-050 (sesión durable). No la sustituye: la desbloquea.

---

## 1. El defecto, medido

RFC-050 dejó una sola respuesta para un libro cuyo siguiente bar no es el siguiente del
dataset: `UNVERIFIED_GAP`.

```
barrier_is_continuous: ok=false
  bar 1792529400000 is missing; the next bar is 1792530300000
UNVERIFIED_GAP
  A protective exit could have been crossed inside that window and no range is
  available to prove it was not
```

La frase es correcta y la respuesta es terminal. El libro no puede avanzar, y la única
alternativa que el runtime ofrece —empezar plano— es la que el WP anterior cerró:
la exposición desaparecería con su stop y la comisión pagada volvería al saldo.

Durante la auditoría de Fase A se comprobó que el runtime **ya tenía** la fuente capaz de
contestar esa pregunta: `vision/quotes.py` carga klines públicas de 1 minuto con su sha256,
valida la rejilla, y `range_between` devuelve el rango de los minutos posteriores a un
instante. Lo que faltaba era una decisión: qué se puede afirmar con esos minutos y qué no.

## 2. La pregunta, separada en tres

Un OHLC de 1 minuto es el conjunto de precios que el venue imprimió dentro de ese minuto.
Eso permite tres afirmaciones de fuerza distinta, y el módulo las mantiene separadas:

| pregunta | respuesta | naturaleza |
| --- | --- | --- |
| ¿cada minuto del hueco está observado, en orden y sin repetir? | sí/no | **hecho** (cobertura) |
| ¿algún minuto contiene el stop o el take-profit? | no / sí, en el minuto *k* | **observación** (rango) |
| si ambos están en el **mismo** minuto, ¿cuál fue primero? | no se sabe | **ambigüedad** |

Lo que un minuto **no** puede decir: el orden entre su alto y su bajo. Tampoco puede decir
qué posición habría abierto una opinión que seguía viva cuando los datos se cortaron.

## 3. Decisión

**La recuperación se decide por evidencia, no por conveniencia.** Tres veredictos:

| veredicto | cuándo | efecto |
| --- | --- | --- |
| `CLEAR` | rejilla completa y ninguna barrera dentro de ningún minuto | se reanuda con el libro intacto |
| `RECONSTRUCT` | rejilla completa y una barrera cruzada en un minuto identificable | se reanuda **cerrando** esa posición en ese minuto, al precio de la barrera |
| `BLOCKED` | cobertura parcial, feed no independiente, ambigüedad o opinión en vuelo | no se reanuda; `RECOVERY_BLOCKED` con causa estructurada y cero órdenes |

Por posición: `INTACT`, `RECONSTRUCTIBLE`, `AMBIGUOUS`, `UNCOVERED`.

**No se resamplea.** Los cinco minutos no se agregan a una vela sintética ni se pide una
decisión sobre datos que se construyeron después. Una vela que el dataset no tiene sigue
sin existir; lo que se reconstruye es el **efecto económico** de los minutos observados,
con el mismo `check_positions_ohlc` que usa el lane para una vela real. La reconstrucción
aporta granularidad de evidencia, no un segundo modelo de ejecución.

**El convenio `stop_first` no se aplica aquí.** El bróker resuelve un doble toque dentro de
una vela con `stop_first` por defecto, y es una decisión de modelado defendible para una vela
*viva*. Aplicarla a un minuto del que no se observó el orden sería publicar un PnL cuyo signo
depende de una convención. Por eso un doble toque intraminuto **bloquea**, y el informe
declara el rango en el que la verdad está, sin elegir un punto dentro de él.

## 4. El contrato de evidencia

`vision/gap_recovery.py` no importa `durable` ni el bróker: un verificador que reutilizara el
código bajo prueba comprobaría que el código coincide consigo mismo. Las fórmulas de stop y
take-profit están escritas de nuevo, y un test las ata a `PaperPosition` para que un cambio
en una sin la otra falle.

Para que un hueco se cruce, todo esto tiene que cumplirse:

1. **Feed presente e independiente.** `feed.name` no puede ser `bar_open`: la prueba no puede
   venir de los datos que tienen el hueco.
2. **Rejilla completa por símbolo con exposición.** `[barrier + Δ, resume)` minuto a minuto,
   consecutivos, sin duplicados, con el último minuto exactamente en `resume − 1 min`.
   Un `59/60` no es cobertura: es un hueco dentro del hueco.
3. **Nada de otro símbolo.** Los minutos de ETH no juzgan una posición de SOL. La tabla se
   guarda por `(símbolo, minuto)` y el veredicto de una posición sólo lee su serie.
4. **Sin opiniones en vuelo que pudieran llenarse dentro.** Una opinión ejecutable cuando los
   datos se cortaron puede haber abierto una posición que el libro no tiene; los minutos
   pueden poner precio a un fill, no decir qué posición habría existido después. Si su
   ventana ya venció antes del hueco, no bloquea.
5. **Evidencia nombrada.** El veredicto publica, por símbolo, `feed`, minutos observados,
   primer y último minuto, `window_sha256` (los OHLC usados) y `series_sha256` (la serie
   cargada). Un verificador puede recomputar el toque con esos números.
6. **La evaluación corresponde a este libro.** `reconcile_book` exige que la ventana
   (`barrier`, `resume`, `interval`) y los `position_id` coincidan con el libro en disco; si
   no, `GAP_EVIDENCE_STALE`. Una evaluación de otro libro no es evidencia de éste.

## 5. Aplicación: dónde y en qué orden

```
VisionLane.__init__
  └─ _apply_recovery → reconcile_book(..., gap=assess_gap(...))
       └─ RECOVERED + reconstruction plan (o BLOCKED, que lanza)
VisionLane.run
  ├─ ledger.open()
  ├─ RUN            (publica el veredicto y la evidencia)
  ├─ _apply_gap_plan  ← cierra lo que el hueco prueba, minuto a minuto
  └─ nueva barrera  (la primera vela real, procesada normal)
```

`_apply_gap_plan` recorre los minutos en orden y llama al **mismo**
`PaperBroker.check_positions_ohlc(..., gap_policy="open_on_gap")` que el bucle de velas. Cada
cierre se registra con `phase="GAP_RECONSTRUCTION"`, `exit_ts_resolution="MINUTE_WINDOW"` y la
ventana del minuto (`lower = minuto`, `upper = minuto + 60 s`). Después se hace `COMMIT`: el
cierre es durable cuando está en el libro, no cuando está en memoria.

Tres detalles que no son cosméticos:

- **`_current_ms` se apunta al minuto.** El bróker sella `closed_at` con el reloj del lane, que
  durante la recuperación seguía en la primera vela del dataset; sin esto, un cierre de las
  14:40 se fechaba a las 00:00 y `bars_held` mentía.
- **El día se cruza donde toca.** Si el minuto del cierre cae en otro día UTC, se llama a
  `risk.reset_daily()` como lo haría el bucle, para que la pérdida no caiga en el presupuesto
  del día siguiente.
- **Contradicción = bloqueo.** Si el bróker cierra una posición que la evaluación juzgó
  intacta (`GAP_PLAN_CONTRADICTED`) o no cierra una que juzgó cerrada (`GAP_PLAN_UNAPPLIED`),
  se lanza antes de comprometer nada. El libro y su evidencia no pueden discrepar y seguir.

Idempotencia: un proceso que muere después de `COMMIT` deja la posición cerrada; el siguiente
no la vuelve a cerrar porque ya no está en el libro. Si muere antes, el libro sigue con la
posición y la reconstrucción se recalcula desde los mismos minutos. No hay un tercer estado;
el experimento `kill-resume` lo repite 14 veces con muertes reales.

## 6. Dos defectos de durabilidad encontrados en la auditoría

Ninguno de los dos lo introdujo este WP; los dos afectaban a la recuperación y se corrigieron
con test de regresión.

**a. Ventana sin `BOOK.json`.** `LaneBookStore.save` rotaba `BOOK.json → BOOK.json.prev` y
luego hacía `replace(tmp, BOOK.json)`. Un proceso que muere entre las dos operaciones deja
sólo `.prev`; `load()` leía "no hay libro" y la sesión **empezaba plano con exposición
abierta** — exactamente el defecto que RFC-050 cierra. Ahora la generación anterior se
**copia** antes de reemplazar, así que nunca hay un instante sin libro completo; y un
`BOOK.json` ausente con `.prev` presente se rechaza (`CorruptBook`) en vez de leerse como
alta nueva.

**b. Relevo del cerrojo en carrera.** Dos procesos que ven al mismo dueño muerto podían
deshacer y recrear el cerrojo cada uno: el primero escribía en un inodo huérfano y el segundo
se quedaba con la ruta. Los dos creían tener el libro, que es el fallo que el cerrojo existe
para impedir. El relevo se serializa ahora con `BOOK.lock.takeover` (`O_EXCL`), se relee el
titular bajo el guardián, y el que gana **verifica que el fichero en disco sigue siendo el
suyo** antes de darse por dueño. Un guardián abandonado por un proceso muerto se puede
reemplazar pasado el umbral.

## 7. Cuándo se bloquea, con nombre

| código | significado |
| --- | --- |
| `UNVERIFIED_GAP` | hueco sin feed de 1 minuto; el comportamiento anterior, intacto |
| `GAP_NOT_COVERED` | rejilla incompleta, símbolo ausente o último minuto antes del resume |
| `GAP_FEED_NOT_INDEPENDENT` | el único feed es la fuente de velas que se está replicando |
| `GAP_EXIT_AMBIGUOUS` | stop y take-profit dentro del mismo minuto |
| `GAP_PENDING_OPINION` | una opinión podía llenarse dentro del hueco |
| `GAP_EVIDENCE_STALE` | la evaluación no describe este libro, esta barrera o este resume |
| `GAP_PLAN_CONTRADICTED` | el bróker cerró algo que la evaluación juzgó intacto |
| `GAP_PLAN_UNAPPLIED` | la evaluación cerró algo que el bróker no cerró |

Todos devuelven `RECOVERY_BLOCKED`, cero órdenes, y el libro en disco sin tocar.

## 8. Alternativas rechazadas

| alternativa | por qué no |
| --- | --- |
| Resamplear 1 m → 5 m y reanudar como si la vela existiera | pediría decisiones sobre una vela que nadie observó, y haría depender el PnL del agregador en vez del mercado |
| Aplicar `stop_first` al minuto ambiguo | publica un signo elegido por convención sobre un orden que no se observó |
| Empezar plano cuando el hueco no se puede probar | es el defecto de RFC-050: pierde exposición y devuelve comisiones pagadas |
| Usar la vela posterior al hueco como "prueba" | un precio posterior no dice qué pasó dentro; el guard `DATA_GAP` ya lo rechaza para las órdenes |
| Reanudar y dejar que el stop se evalúe en el resume | el stop se habría cruzado antes y a otro precio; la primera vela después del hueco puede abrir muy lejos |
| Un verificador que importe `gap_recovery` | comprobaría que el código coincide consigo mismo; el verificador recalcula con aritmética propia |

## 9. Límites que este RFC no esconde

- **El hueco tiene que empezar en la barrera.** Si falta una vela *después* de reanudar, el
  bucle de velas la salta: `check_positions_ohlc` sólo ve las velas presentes y no hay
  evaluación de minutos a mitad de corrida. El experimento lo verificó (una vela 31 presente
  hacía que la barrera avanzara y el hueco dejara de ser de la recuperación). Corregirlo
  cambia la semántica de `DATA_GAP` que otros tests fijan; queda como siguiente WP.
- **Opiniones en vuelo.** Se bloquea, no se reconstruyen. Reconstruir la entrada exigiría
  decidir el precio de un fill que no se observó y la posición que habría quedado abierta.
- **Feed en vivo.** El camino está probado con minutos archivados y con minutos sintéticos
  controlados, no con un collector en vivo: la latencia de entrega y los minutos parciales
  del venue no están medidos aquí.
- **Modelo real.** El experimento usa un proveedor de guion. No se llama a ningún modelo, así
  que nada de esto dice nada sobre la calidad de las decisiones.
- **Sólo PAPER.** No hay ruta de orden real en esta cadena; `live_orders = 0` se comprueba,
  no se promete.
