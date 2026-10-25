# BASELINE — EXP-003M

## El punto de partida, restado de EXP-003L sin volver a medirlo

EXP-003L cerró con `NO_VIABLE_CANDIDATE` sobre el candidato `5m/mean_reversion`: 47 señales, bruto de referencia `0.266909` USDT por operación frente a `1.269004` USDT de coste, neto por señal `-0.842046`.

| mecanismo (EXP-003L) | cierres | neto/señal | neto/cierre | bruto/cierre | comisiones/cierre |
| --- | ---: | ---: | ---: | ---: | ---: |
| taker en el open | 47 | -0.842046 | -0.842046 | 0.157954 | 1.000000 |
| maker base (15 min, 0 bp, spot VIP0 BNB) | 44 | -0.452255 | -0.483091 | 0.266909 | 0.750000 |
| maker esquina pesimista (5 min, 2 bp, spot VIP0) | 37 | -0.687937 | -0.873866 | 0.126134 | 1.000000 |

## Qué quedaba sin resolver

El escenario maker de 003L supone que **cualquier toque** del rango de una barra de 1 minuto sobre el límite nos llena **enteros** al precio mejorado. Es un techo, no un mecanismo: no hay cola, no hay latencia, no hay parciales y no hay selección adversa. La conclusión económica de 003L, en cambio, se apoyaba en que incluso ese techo daba pérdidas. Ese razonamiento solo es válido si el techo está bien construido.

EXP-003M responde a dos preguntas que 003L dejó abiertas:

1. **¿Se sostiene el techo con la cinta de operaciones real?** El modelo F0 reproduce el supuesto de 003L; F1/F2 lo sustituyen por volumen agresor observado, cola declarada, latencia y llenado parcial.
2. **¿Se puede reproducir la evidencia?** Un pipeline único genera, verifica y sella, y el verificador no puede reescribir lo sellado.

## Reproducción del predecesor antes de juzgarlo

- Escenario objetivo: `maker_resting__spot_vip0_bnb__h15__o0`.
- Tolerancia: `1e-08` USDT.
- ¿Coincide todo (tasa de llenado, neto/señal, neto/cierre, bruto/cierre)? **sí**

| magnitud | publicado por 003L | medido por 003M | delta |
| --- | ---: | ---: | ---: |
| `fill_rate` | 0.93617000 | 0.93617000 | 0.0000000000 |
| `net_per_signal_usdt` | -0.45225547 | -0.45225547 | 0.0000000000 |
| `net_per_fill_usdt` | -0.48309107 | -0.48309107 | 0.0000000000 |
| `gross_per_fill_usdt` | 0.26690893 | 0.26690893 | 0.0000000000 |

Si esa tabla no cuadrara, `G1_reproduces_003l` fallaría y el experimento quedaría `BLOCKED`: un experimento que no puede restablecer a su predecesor no tiene autoridad para contradecirlo.

## Lo que este experimento no vuelve a hacer

- No re-optimiza el candidato ni cambia la señal, el riesgo, las salidas ni las comisiones.
- No abre el holdout `2026-08-06 → 2026-08-20`.
- No envía órdenes ni usa credenciales privadas.
