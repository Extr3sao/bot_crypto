# ECONOMICS COMPARISON — EXP-003M

Mismas 47 señales, mismas salidas, mismo horizonte de investigación y las mismas tablas de comisiones. Lo único que cambia es cómo se llena la entrada.

| escenario | llenadas | tasa | bruto/cierre | comisiones/cierre | neto/cierre | neto/señal | IC95 % neto/señal | mitad 1 | mitad 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `F0_touch_full` | 44 | 93.6 % | 0.266909 | 0.750000 | -0.483091 | -0.452255 | [-1.597596, 0.703727] | -0.7919 | -0.1779 |
| `F1_tape_base` | 42 | 89.4 % | 0.205964 | 0.740655 | -0.534691 | -0.477809 | [-1.472685, 0.609189] | -0.9347 | -0.1087 |
| `F2_tape_pessimistic` | 33 | 70.2 % | 0.076738 | 1.000000 | -0.923262 | -0.648248 | [-1.599922, 0.417521] | -1.0721 | -0.3059 |
| `F3_tape_no_queue` | 44 | 93.6 % | 0.267925 | 0.738865 | -0.470940 | -0.440880 | [-1.533134, 0.704954] | -0.8293 | -0.1272 |

## El techo y el suelo

- Suelo de costes por operación cerrada (spot VIP0 pagando en BNB): **0.750000 USDT** sobre 500 USDT de nocional.
- Techo de ingreso bruto por operación cerrada, medido en el escenario más generoso (F0, todo toque lleno al precio mejorado, cola cero): **0.266909 USDT**.
- Cobertura del suelo por el techo: **0.356x**.

Un modelo de llenado más realista no puede aumentar el bruto por cierre: como mucho reproduce el techo, y lo normal es que lo reduzca (entradas peores o más tardías). Si el techo no cubre el suelo, el problema no es de fills.

## La trampa del «no operar es gratis»

- F1 llena 42 de 47 señales; F0, 44.
- Neto por señal: F0 `-0.452255`, F1 `-0.477809`, F2 `-0.648248`.
- Neto por cierre: F0 `-0.483091`, F1 `-0.534691`, F2 `-0.923262`.

Cuando la tasa de llenado baja, el neto por señal **puede mejorar** aunque cada operación siga perdiendo, porque se ejecutan menos operaciones malas. Eso no es una ventaja: es una estrategia que gana dinero no operando. La puerta económica se aplica por tanto a las dos magnitudes a la vez, y un resultado que mejore solo por llenar menos no se promociona.

## Puertas

| puerta | resultado | detalle |
| --- | --- | --- |
| `G1_reproduces_003l` | `PASS` | {'fill_rate': 0.0, 'gross_per_fill_usdt': 0.0, 'net_per_fill_usdt': 0.0, 'net_per_signal_usdt': 0.0} |
| `G4_economics_pessimistic` | `FAIL` | {'ci_lower': -1.59992186, 'net_per_fill_usdt': -0.92326194, 'net_per_signal_usdt': -0.64824774} |
| `G5_optimistic_ceiling` | `FAIL` | {'fees_per_fill_usdt': 0.75, 'gross_per_fill_usdt': 0.26690893, 'net_per_fill_usdt': -0.48309107, 'statement': 'F0 fills every touch at the improved price with no queue. Its gross per fill is the ceiling any fill model can reach on this sample'} |
| `G7_evidence_class` | `FAIL` | {'class': 'ESTIMATED_FROM_OBSERVED_TRADE_TAPE', 'reason': 'no order was ever sent to an exchange; fills are inferred from the tape'} |

Veredicto: **`REJECT`**. Puertas falladas: `G4_economics_pessimistic`, `G5_optimistic_ceiling`, `G7_evidence_class`.
