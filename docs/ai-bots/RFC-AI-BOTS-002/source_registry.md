# SOURCE_REGISTRY — fuentes externas y qué se adoptó de cada una

**Regla:** `PROJECT != PATTERN != IMPLEMENTATION`. Ninguna fila de esta tabla afirma que
un proyecto externo haya sido validado funcionalmente. La columna *evidencia* dice lo que
realmente se hizo en este paquete.

| SOURCE_ID | Proyecto | Licencia | Qué se leyó | Evidencia en esta sesión | Adopción |
| --- | --- | --- | --- | --- | --- |
| SRC-FENIX | FenixAI (Python) | MIT declarada por el proyecto | Descripción pública y estructura de agentes | Lectura de referencia; **sin clon local** (`NOT_EXECUTED`) | PATTERN: separación analista/ejecutor; **sin código** |
| SRC-SEMSIG | Semantic Signal (Python) | MIT declarada | Descripción de pipeline de señales | Referencia; `NOT_EXECUTED` | REJECT para copia: su capa de señal no aporta nada que el lane canónico no tenga |
| SRC-TRADAGENTS | TradingAgents (Python) | Apache-2.0 | Descripción del grafo bull/bear/manager | Referencia; `NOT_EXECUTED` | EXPERIMENT (BOT-CRI-01) con ablación obligatoria; **sin workflow copiado** |
| SRC-NOF1 | Open nof1.ai (TypeScript) | AGPL-3.0 | Descripción pública, operativa numérica | **Prohibido importar**; `NOT_EXECUTED` (sin build local) | REJECT para código; PATTERN: ledger de decisiones |
| SRC-FORTUNE | FortuneMal | Sin licencia declarada | Descripción pública | **Prohibido reutilizar** sin licencia | REJECT |
| SRC-QRAK | qrak | MIT (según el autor) | Descripción de render Plotly→PNG y JSON | Referencia; `NOT_EXECUTED` | PATTERN: PNG determinista + contrato estricto (ya existía en AI-VISION-001) |

## Lo que sí es nuestro y está probado

| Componente | Origen | Prueba |
| --- | --- | --- |
| PNG causal, ventana fija, sin barra futura | AI-VISION-001 + correcciones P0 de este RFC | `tests/unit/vision/test_chart.py`, `test_visual_defects.py` |
| Contrato `VisionDecision` / `AITradeOpinion` | propio | `test_contract.py`, `test_registry_contracts_runner.py` |
| Guards PIT/esquema | propio | `test_guards_and_controls.py` |
| Ledger encadenado | propio | `test_ledger.py` + verificación independiente del run |
| Registro de capacidades cerrado | propio (patrón de plugin registry) | `test_registry_contracts_runner.py` |
| Prompt estructurado MTF (control sin imagen) | propio, **no traducido de AGPL** | `test_structured_prompt_never_claims_an_image` |

## Licencias

No se ha copiado código de ningún proyecto externo en este paquete. Por eso no hay avisos
MIT/Apache nuevos que añadir: todo `src/trading_bot/intelligence/ai_bots/` y
`src/trading_bot/vision/guards.py` es código propio de este repositorio.

## Gaps conocidos

1. La auditoría de fuentes externas es **documental**, no funcional: no hay clones, ni
   `REA evidence_id` de análisis estático de terceros.
2. REA 6.4.0 corre en el host pero **sin motores de análisis** (`doctor.json`), por lo que
   `analyze-javascript-application` no se ejecutó.
3. Los patrones adoptados se justifican por el RFC y por nuestros tests, no por el
   rendimiento reportado por sus autores.
