# FILL REALISM — EXP-003M

## Cinta observada

- Pares `(símbolo, día UTC)` descargados: **42**.
- Operaciones conservadas: **680.484** de **27.887.409** presentes en esos días (el resto está fuera de las ventanas de las señales).
- Descarga: **405.6 MiB**.
- Selección: every (symbol, UTC day) that contains at least one pre-registered signal, and inside it every trade in [decision-60 s, decision+16 min] for those signals. No filter on price, side or outcome; missed signals are impossible to hide.

Cada par conserva **todas** las operaciones de la ventana, sin filtrar por precio ni por resultado: una señal que no se llena no se puede esconder recortando la cinta.

## Tasa de llenado por mecanismo

| escenario | señales | llenadas | tasa | fracción media | seg. hasta llenar (mediana) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `F0_touch_full` | 47 | 44 | 93.6 % | 1.0000 | — |
| `F1_tape_base` | 47 | 42 | 89.4 % | 0.9875 | 12.1 |
| `F2_tape_pessimistic` | 47 | 33 | 70.2 % | 1.0000 | 41.6 |
| `F3_tape_no_queue` | 47 | 44 | 93.6 % | 0.9852 | 8.9 |

### Por qué fallan las señales que fallan

| escenario | motivo | señales |
| --- | --- | ---: |
| `F0_touch_full` | `NO_TOUCH_IN_OHLC` | 3 |
| `F1_tape_base` | `NO_AGGRESSOR_AT_LIMIT` | 3 |
| `F1_tape_base` | `QUEUE_NEVER_REACHED` | 2 |
| `F2_tape_pessimistic` | `NO_AGGRESSOR_AT_LIMIT` | 12 |
| `F2_tape_pessimistic` | `QUEUE_NEVER_REACHED` | 2 |
| `F3_tape_no_queue` | `NO_AGGRESSOR_AT_LIMIT` | 3 |

`NO_AGGRESSOR_AT_LIMIT` significa que en el horizonte no hubo ni una operación agresora que tocara nuestro precio: el libro no llegó. `QUEUE_NEVER_REACHED` significa que sí hubo operaciones a nuestro precio, pero el volumen no alcanzó para consumir la cola declarada más nuestra orden. Son dos formas distintas de no operar y no se suman en una sola cifra.

## Selección adversa

Convención: **positivo = el mercado se movió en contra de la posición**. Se compara el conjunto llenado por la cinta con el conjunto que 003L habría llenado por toque, en los mismos horizontes.

| escenario | llenadas | adverso +1 min | adverso +5 min | adverso +15 min | Δ +5 min vs F0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `F0_touch_full` (referencia) | 44 | -4.835920 | -1.779905 | 2.362074 | — |
| `F1_tape_base` | 42 | -3.370451 | 2.057490 | 6.225917 | 3.837 |
| `F2_tape_pessimistic` | 33 | -2.504843 | 5.307905 | 5.075807 | 7.088 |
| `F3_tape_no_queue` | 44 | -4.835920 | -1.779905 | 2.362074 | 0.000 |

Una orden maker solo se llena cuando alguien cruza hacia ella. La tabla mide si ese «alguien» llega cuando el precio va a seguir en nuestra contra, que es la razón por la que un modelo de toques sobreestima el resultado de operar pasivo.

## Sensibilidad a la cola y a la latencia

| cola (x orden) | latencia | llenadas | tasa | neto/señal | neto/cierre | bruto/cierre |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.00 | 0 ms | 44 | 93.6 % | -0.4409 | -0.4709 | 0.2679 |
| 0.00 | 400 ms | 44 | 93.6 % | -0.4409 | -0.4709 | 0.2679 |
| 0.00 | 2000 ms | 43 | 91.5 % | -0.4880 | -0.5334 | 0.2098 |
| 0.25 | 0 ms | 44 | 93.6 % | -0.4389 | -0.4688 | 0.2615 |
| 0.25 | 400 ms | 44 | 93.6 % | -0.4389 | -0.4688 | 0.2615 |
| 0.25 | 2000 ms | 43 | 91.5 % | -0.4701 | -0.5138 | 0.2250 |
| 0.50 | 0 ms | 44 | 93.6 % | -0.4384 | -0.4683 | 0.2531 |
| 0.50 | 400 ms | 44 | 93.6 % | -0.4384 | -0.4683 | 0.2531 |
| 0.50 | 2000 ms | 43 | 91.5 % | -0.4537 | -0.4959 | 0.2382 |
| 1.00 | 0 ms | 42 | 89.4 % | -0.4778 | -0.5347 | 0.2060 |
| 1.00 | 400 ms | 42 | 89.4 % | -0.4778 | -0.5347 | 0.2060 |
| 1.00 | 2000 ms | 42 | 89.4 % | -0.4778 | -0.5347 | 0.2060 |
| 2.00 | 0 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 2.00 | 400 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 2.00 | 2000 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 4.00 | 0 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 4.00 | 400 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 4.00 | 2000 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 10.00 | 0 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 10.00 | 400 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 10.00 | 2000 ms | 41 | 87.2 % | -0.5082 | -0.5826 | 0.1674 |
| 100.00 | 0 ms | 39 | 83.0 % | -0.6359 | -0.7663 | -0.0163 |
| 100.00 | 400 ms | 39 | 83.0 % | -0.6359 | -0.7663 | -0.0163 |
| 100.00 | 2000 ms | 39 | 83.0 % | -0.6359 | -0.7663 | -0.0163 |

El mejor punto del barrido es cola `0.50` y latencia `0 ms` con `-0.4384` USDT por señal. El peor es cola `100.00` y latencia `0 ms` con `-0.6359`.

El barrido mejora cuando **menos** señales se llenan. Eso no es una mejora: es la aritmética de que cada operación llenada pierde dinero. Por eso la decisión no se toma sobre el neto por señal, sino sobre el neto por cierre.
