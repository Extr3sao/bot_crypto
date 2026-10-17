# Informe ejecutivo — WP-EDGE-015

*2026-10-17T09:05Z, `87b9c6a`. `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`. Sin órdenes reales, sin
credenciales, sin apalancamiento y sin ningún cambio de límites de riesgo.*

## En una frase

Se han corregido los cuatro defectos de certificación que quedaban abiertos y se ha buscado ventaja
económica de verdad: **no hay ninguna estrategia que gane sus costes**, así que el resultado es
`NO_ECONOMIC_EDGE_FOUND`, el carril de investigación se mantiene y el holdout prospectivo queda
congelado y acumulando en lugar de inventarse.

## Qué se ha ejecutado

| pieza | estado |
| --- | --- |
| protocolo prospectivo congelado en un commit y capturado en otro | ejecutado, `ORDER_VERIFIED` |
| cuatro familias medidas con costes por venue y sensibilidad adversa | ejecutado (5 años, 9 activos) |
| carril paper aislado sobre barras nuevas con el broker y el riesgo reales | ejecutado (6 003 barras, 210 ciclos, 28 órdenes simuladas, 14 operaciones cerradas) |
| verificación independiente (sin importar el código del constructor) | 34/34, veredicto `VERIFIED` |
| suite de comportamiento del broker y de causalidad de las familias | 8 + 10 pruebas, todas pasan |
| divergencias de Jesse y VeighNa | ambas resueltas con descomposición exacta |

## Los defectos, cerrados

1. **El holdout no podía probar su propio orden.** Su manifiesto decía literalmente
   `order_check=false`. Ahora el protocolo se congela en un commit (`b4ff588`, 07:15:28Z) y la
   captura corre después, en otro proceso (07:20:21Z); el orden se comprueba de tres formas
   independientes y el veredicto es `ORDER_VERIFIED`. Los datos anteriores se conservan como
   evidencia **descriptiva**, etiquetada. La captura posterior (09:01:39Z) ya contiene **3 barras
   prospectivas** reales (una por símbolo, apertura 08:00Z), sin puntuar; además el manifiesto ya no
   guarda rutas absolutas de esta máquina, y dos comprobaciones nuevas (V33/V34) fallan si el paquete
   no se puede releer desde un checkout limpio o si el fichero que el manifiesto hashea no es el que
   Git publica.
2. **El verificador era el constructor.** Importaba el mismo módulo que fabricó los artefactos que
   juzgaba. El import se ha eliminado (no acotado) y hay una comprobación estructural que falla si
   vuelve.
3. **La identidad de las operaciones se deducía de un reloj.** Dos ejecuciones en el mismo segundo
   podían compartir identidad. Ahora el broker acuña sus propios identificadores por libro, los
   continúa tras una recuperación y el carril usa un libro por símbolo. Lo encontró precisamente la
   verificación independiente: 56 identificadores, 24 distintos, por culpa de compartir libro. El
   mismo defecto llegaba a la evidencia del carril: `opened_at`/`closed_at` salían del reloj de la
   máquina, así que dos ejecuciones de las mismas barras escribían ficheros distintos y ningún hash
   sobre ellos podía sostenerse. El broker acepta ahora un reloj, el carril le pasa la barra que
   procesa y el fichero de 14 operaciones hashea idéntico entre ejecuciones (`889734699a8d…`,
   medido).
4. **Una sola cifra de equity no decía qué se había movido.** Ahora se separan realizado, no
   realizado, caja y patrimonio a mercado, con la comisión de entrada devengada como término propio
   y cuatro identidades comprobadas.
5. **Quedaban dos divergencias sin explicar.** Los 7,021359 bps de Jesse son exactamente tres
   términos (6,985523 de precio en las dos operaciones abiertas al final, +0,095587 de convención de
   comisión propia y −0,059751 porque su comisión realizada no es 20 bps), con error de
   descomposición 0,0. Las dos operaciones extra de VeighNa son las dos últimas entradas de la regla.

## Qué dice la búsqueda de ventaja

| familia | operaciones (cola reservada) | bruto/operación | neto 1× | neto 2× | decisión |
| --- | ---: | ---: | ---: | ---: | --- |
| reversión a la media con filtros de volatilidad y liquidez | 811 | +54,84 bps | +21 075 bps | −2 326 bps | **EXPERIMENT** (frágil al coste) |
| ruptura por régimen de volatilidad | 171 | +223,79 bps | +33 367 bps | +28 465 bps | **REJECT** (depende de 5 operaciones) |
| pullback en tendencia | 895 | −37,04 bps | −58 809 bps | −84 464 bps | **REJECT** |
| rotación relativa multi-activo | 355 | −35,63 bps | −11 465 bps | −16 605 bps | **REJECT** |
| maker | — | — | — | — | **DEFER**: no hay modelo de ejecución |

Dos lecturas que importan más que los signos:

- La familia de ruptura **parece** excelente y no lo es: sus cinco mejores operaciones son **1,31
  veces todo su bruto** y su operación mediana pierde dinero. Es un boleto de lotería, no una
  expectativa dimensionable, y se rechaza por esa concentración, con el número delante.
- La reversión a la media es la única cuyo bruto se repite en los dos segmentos (+54,84 y +54,76) y
  está **a un solo doblar de costes de cero**: +26 bps/operación a coste central, −2,87 bps a coste
  doble. No es todavía una ventaja sobre la que arriesgar capital.

El problema de fondo es aritmético: los niveles alternativos cuestan 25–29 bps por vuelta completa a
200 USDT, así que hacen falta ~30 bps brutos por operación para sobrevivir al coste central y ~58
bps para sobrevivir al adverso. Casi nada en estos datos logra ambas cosas.

## El carril experimental prospectivo

6 003 barras exploradas, 210 ciclos de decisión con el broker y la política de riesgo reales: 182
`NO_TRADE`, 14 entradas, 14 salidas protectoras, **28 órdenes simuladas** (14 de entrada y 14 de
salida), −12,81 USDT realizado, todas las identidades contables correctas y el ledger de admisión
autoritativo **sin cambios** (hash idéntico antes y después). Cada ciclo lleva la etiqueta
`EXPERIMENTAL_PROSPECTIVE_PAPER`; las familias rechazadas se registran como negativas a operar con su
motivo; no se envió ninguna orden.

El carril consume ahora las barras capturadas, así que `PROSPECTIVE` no es una etiqueta que se pone
solo: entraron **3 barras prospectivas** (una por símbolo) y **ninguna familia propuso nada en
ellas** — 0 ciclos prospectivos, 0 señales forzadas. Por eso el PnL se separa así: `DESCRIPTIVE`
−12,809961 USDT y `PROSPECTIVE` 0,000000 USDT. Una barra a la que se llega saltando más de 1,5 horas
se trata como calentamiento (`NO_TRADE/GAP_BRIDGE_WARMUP`) en vez de operarse, porque las familias
leen sus filtros sobre barras consecutivas.

Su resultado es más de riesgo que de estrategia: los stops por defecto (0,5 % / 0,75 %) son mucho más
estrechos que el horizonte que necesita la familia superviviente, así que todas las posiciones
cerraron por stop antes de que su tesis pudiera desarrollarse. Tocar esos límites es decisión del
risk-manager con su propio RFC.

## Lo que no se afirma

- **Sin inferencia económica fuera de muestra**: los corpus están consumidos y la rebanada
  prospectiva tiene **3 barras, ninguna puntuada**. Tres velas horarias no aceptan ni rechazan una
  familia cuyo horizonte es de días, y la selección no ha leído ninguna.
- **Sin adopción, y `ADOPT` es hoy imposible**: exige superar todos los umbrales en datos que la
  selección nunca tocó.
- El filtro de percentil de ATR es una **aproximación de 50 cubos** (declarada); por eso la familia
  decisiva publica su evidencia por operación y el verificador re-deriva cada decisión contra las
  barras que existían cuando se tomó.
- El guardián de disco sigue en `INSUFFICIENT_FREE_SPACE` (4,17 GiB libres ahora, frente a 5,9 al
  principio de la sesión) y **no se ha relajado**; no se escribió ningún corpus nuevo grande.
- Los motores externos no se han re-ejecutado: se han re-derivado sus filas publicadas.

## Siguiente hipótesis

La restricción activa es el coste, no la señal. Se busca por tanto una familia cuyo bruto por
operación supere con margen su propia vuelta completa en su nivel (≥ 24 bps en un par de primer nivel
y ≥ 29 bps en un alt fino, presupuestando el multiplicador adverso), con dos direcciones concretas:
**menos operaciones y más grandes en los pares de primer nivel** (el round trip allí es 23,35 bps y
ahí no se gastaron las operaciones), y **un brazo maker solo cuando exista un modelo de fills**
validado contra ejecuciones reales — hasta entonces la familia maker queda diferida, no aproximada.
