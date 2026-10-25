# CANDIDATE DECISION — EXP-003M

**Veredicto: `REJECT`**

Promoción permitida: **no**. Holdout abierto: **no**. Órdenes live: **no**.

## Razón

The candidate loses under the pessimistic maker model and already loses under the most generous one. Fill realism is not the binding constraint: the gross edge per fill is smaller than the fees it must clear, so a better fill rate has nothing to rescue.

## Lo que sostiene el veredicto

- Techo (F0, todo toque lleno al precio mejorado): neto por cierre `-0.483091` USDT, bruto `0.266909` frente a `0.750000` de comisiones.
- Pesimista (F2, cola 4x, 2 s, 5 min, 2 bp, spot VIP0): neto por cierre `-0.923262`, neto por señal `-0.648248`, IC95 % inferior `-1.599922`.
- Muestra: 47 señales, por encima del mínimo de 40, así que el veredicto no es de muestra insuficiente.

## Por qué no es `INSUFFICIENT_EVIDENCE`

La evidencia de fills es estimada y eso impediría promocionar aunque los números salieran positivos. Pero la economía no es ambigua: el techo de ingreso por operación no cubre las comisiones. `REJECT` no depende de la calidad del modelo de fills, y por eso no se rebaja a una falta de datos.

## Qué haría falta para revisar esta decisión

1. Un mecanismo cuyo bruto por operación supere el suelo de comisiones en el techo, no en el escenario favorable.
2. Fills observados de órdenes reales o de paper trading con libro en vivo, no inferidos.
3. Una ventana forward preregistrada distinta del holdout, que sigue intacto.
