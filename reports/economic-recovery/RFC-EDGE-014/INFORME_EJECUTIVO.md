# RFC-EDGE-014 — informe ejecutivo

*A `2026-10-16T12:50:42Z`.*

## Qué se ha hecho de verdad

Se ha **ejecutado** trabajo, no descrito: `6` brazos de backtest sobre datos reales cobrando
costes reales, la ventana real del ledger auditada, la contradicción de comisiones reconstruida desde su
fuente primaria, y `3` repositorios externos clonados con su licencia leída en el commit exacto.

## Los tres hallazgos que importan

1. **La contradicción de costes era de población, no de aritmética.** El "32.5 bps" es la media de la
   comisión sobre cuatro venues distintas; dividirla por la barrera de admisión da 1.3863 y no significa
   nada. La cifra correcta es **la comisión es el 85.9% del ida y vuelta de admisión**. Se reproduce el
   número publicado para demostrarlo, y no se edita el original.
2. **La segunda contradicción tampoco lo era.** 144.061/día cuenta inicios solapados condicionados; 48.018/día
   cuenta ventanas que no se solapan. Son métricas distintas y solo la segunda son operaciones.
3. **El muro económico se reprodujo de forma independiente.** El cruce de medias neutro gana 21.98 bps
   brutos por operación en BTC y la barrera de 23 bps se los lleva: neto negativo. No es un fallo de
   indicadores, es aritmética.

## Qué NO se ha conseguido, y por qué

- **Ninguna ventaja neta.** Los seis brazos ejecutados son neto-negativos.
- **Ninguna validación inferencial**: no queda corpus sin leer, así que el OOS es temporal dentro de un
  corpus consumido. Sin datos frescos no hay promoción posible, y eso es un límite de datos, no de permiso.
- **Ningún motor externo ejecutado**: los pines están verificados y las licencias leídas, pero comparar
  motores exige un OOS que aún no existe.

## Estado

`RESEARCH_COMPLETED_NO_EDGE` · `ECONOMIC_INTEGRITY_RECONCILED` · `TRADE_PATH_DIAGNOSED` ·
`PAPER_BLOCKED_BY_GATE` · verificación independiente **VERIFICATION_PASS**
(12/12), sabotajes **30/30**.
`FALSE_SUCCESS = 0`, ninguna orden enviada.

## Lo siguiente, por impacto económico

Capturar un OOS fresco y repetir la medición es lo único que puede cambiar el veredicto. Después, ejecutar
la paridad ya planificada y medir un modelo de fills maker. Las 24 condiciones de aceptación están
respondidas criterio a criterio en `ACCEPTANCE.json`.

Research only: ninguna orden, ninguna credencial, ningún capital.
