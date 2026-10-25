# T-QR-SIGNAL · decisión de adopción

**Decisión: `DEFER` para código, `EQUIVALENT_ON_TESTED_CASES` para el invariante
"gráfico desde el mismo contexto".**

| eje | estado | base |
| --- | --- | --- |
| `REA_EXECUTED` | **YES** — 3 operaciones, 3 `evidence_id` | `ev_9b45318c072de54798bb93a37354c38ec82b2bccf31d3cd1fbf9be0898a16b99`, `ev_b954b8b016f1736a766bc45627a3d21f600503c1d4294e7147133a7ce461c46c`, `ev_ee6845ff71d389439559036e9c661edbaee90a518ac18bd29639ef72995417a3` |
| `REA_EVIDENCE_APPLICABLE` | sí, para la superficie del dashboard | 14/14 scripts, `complete` |
| `SOURCE_AUDIT` | sí | cadena Python leída en el commit exacto |
| `UPSTREAM_RUNTIME_REPRODUCED` | NO | backend no arrancado: requiere configuración del usuario |
| `LICENSE` | MIT | compatible, sin copia |
| `ADOPT` | ninguno | no hay capacidad que falte |

## Por qué no se adopta nada

Su cadena coincide con la nuestra en lo esencial y es **más laxa** en el punto crítico: no
liga la imagen a un hash. Adoptar su diseño sería perder el `INTEGRITY_FAILURE` que acabamos
de blindar.

## Qué haría falta para cambiar

Un caso en el que su preflight de prompt (lint de tokens, `validate_and_warn`) encuentre
fallos que el nuestro no detecte, medido sobre nuestro ledger.
