# WP-EDGE-017 — informe ejecutivo

## Qué se corrigió

- **El colector ya no destruye la muestra.** Cada `--capture` truncaba el holdout y lo
  reescribía con una sola página. Ahora fusiona por `(símbolo, hora)`, conserva el primer
  valor capturado, escribe de forma atómica (`os.replace`), reanuda desde la última barra
  que ya tiene, pagina y confirma las páginas cortas, y rechaza la hora que aún no ha
  cerrado. Un registro independiente (`OOS_CAPTURE_LEDGER.jsonl`) deja de depender del
  propio fichero para saber qué se vio.
- **La cobertura ya cuenta barras.** Antes reducía todo a `{símbolo: último timestamp}`;
  ahora hay una fila por `(símbolo, hora)` y la identidad `esperadas = observadas +
  faltantes` se comprueba por símbolo. Una hora sin colector es `MISSING_NO_COLLECTOR`,
  nunca un día tranquilo.
- **El coste se paga dentro del libro, antes de que decida el riesgo.** El broker cobra
  comisión, medio spread y slippage por símbolo; cada operación publica
  `pnl = bruto de referencia − coste de ejecución − comisiones`. `RiskManager` se marca al
  equity neto del broker antes de cada `check_signal`, así que pérdida diaria, pérdida
  semanal, drawdown y tamaño se calculan sobre neto.
- **Los cuatro bloqueos defensivos se evalúan.** Spread, ATR, latencia y fin de semana se
  aplican en el camino canónico de paper y fallan cerrado si falta la medición. La política
  no se tocó: `weekend_trading` sigue en `false` y live sigue desactivado.

## Las cinco preguntas

**¿Cuántas barras prospectivas consecutivas se han capturado, validado y evaluado?**
Tres por símbolo (nueve en total), de 08:00Z a 10:00Z del 2026-10-17, las nueve validadas
y evaluadas por el carril. **Las nueve fueron rellenadas por la primera ejecución
corregida** (desfase máximo 2,648 h), no observadas en vivo al cierre; el registro lo dice.
Cero propuestas y cero ejecuciones sobre ellas.

**¿Cuántas faltan y por qué?** Ninguna en la ventana congelada: 9 esperadas, 9 observadas,
0 faltantes. La reanudación rellenó todas las horas cerradas desde el congelado. En el
futuro, una hora sin ejecución manual será `MISSING_NO_COLLECTOR`.

**¿Qué operaciones paper permite realmente el riesgo después de costes?**
146 a 1×, 110 a 2× y 67 a 3×, frente a las 146 que aprobaba el riesgo bruto. A 1× el
resultado no cambia porque el drawdown es 2,39 % frente a un límite del 5 %; a 2× y 3× el
límite semanal rechaza 55 y 105 entradas que antes se aprobaban. Esa diferencia es la
prueba del defecto corregido, con los mismos datos y la misma política.

**¿Coinciden el PnL neto del broker, el equity del RiskManager y la reconciliación?**
Sí, en las tres ejecuciones: cada operación reconstruye su neto, el equity del broker es
10 000 + realizado + no realizado, y el equity del riesgo es exactamente ese número.

**¿Qué bloqueos operativos siguen impidiendo un paper prospectivo continuo?**
No hay planificador autorizado (crear una tarea de Windows exige privilegios de
administrador, que este paquete no intentó); el colector es manual; no hay ninguna
estrategia admitida en `config/strategy_admission.json`, así que el camino de paper del
runtime no tiene nada que ejecutar y el carril experimental salta la admisión por diseño;
y el volumen está al 99 % — el colector cuesta ~9,6 KB/h, así que el disco ya no es la
razón, pero el volumen no está sano.

## Lo que cambió en los números

| | antes (bruto) | ahora (neto 1×) | neto 2× | neto 3× |
| --- | ---: | ---: | ---: | ---: |
| operaciones | 146 | 146 | 110 | 67 |
| resultado USDT | −53,3845 | **−238,7705** | −293,0325 | −294,0563 |

El guardián de disco no se relajó: se le dio la tasa real medida (9 576,3 B/h en lugar de
los 240 MB/h de otro carril) y devuelve `COHERENT` para 24 h. `CAPTURE_BLOCKED_DISK` era un
diagnóstico equivocado.

## Honestidad del paquete

Verificación independiente: **27/27 comprobaciones y 11/11 fallos inyectados detectados**,
sin importar los módulos constructores. No se ejecutaron el ensayo de clon limpio, la
re-verificación multi-motor ni la creación del planificador; se declaran como no ejecutados,
no como superados. Sigue sin haber evidencia prospectiva de trading: nueve barras rellenadas
y cero propuestas no son una muestra.
