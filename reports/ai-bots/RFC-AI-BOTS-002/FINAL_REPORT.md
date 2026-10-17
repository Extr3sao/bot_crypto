# FINAL_REPORT — RFC-TAP-AI-BOTS-002 v3.1 (REA Target Authority)

**Fecha:** 2026-10-18 · **Rama:** `agent/ai-vision/RFC-AI-VISION-001`
**Estado global:** `REA_FOUNDATION_READY` · `TARGET_REA_AUDITED` en 4 superficies ·
`AI_BOTS_RUNTIME_TESTED` · **`REAL_MODEL_CALLED = false`** ·
`EXTERNAL_PATTERN_CERTIFIED = 0` · `NO_ECONOMIC_EDGE_FOUND`.

## 0. El P0 que abrió esta iteración

La v3 presentó los 12 chunks de `https://nof1.ai/` como artefacto de
`195440/nof1.ai @ 5d27641`. **Era falso.** El commit medido no contiene Next.js en ningún
fichero y su propio dashboard son dos scripts estáticos en `open-nof1.195440.com`. Un árbol
sin Next.js no produce chunks de Turbopack.

Consecuencia aplicada:

- la evidencia de la v3 se conserva **sin tocar un hash** en `rea/targets/T-NF-PUBLIC/`,
  reetiquetada `UNATTRIBUTED_NO_DEPLOYMENT_RECEIPT`;
- se creó `rea/targets/T-NF-NOF1/` sobre el commit exacto, con evidencia REA nueva.

## 1. Por target

| target | `REA_EXECUTED` | artefacto | `REA_EVIDENCE_ID` | observado | decisión |
| --- | --- | --- | --- | --- | --- |
| `T-NF-NOF1` | **YES** | `public/` del commit `5d27641dfa47…` | `ev_4b2bf9c5c313530cc7e1e399d4cde5c175ecdd0018a9f608ee12782522ea9ade` | dashboard estático: 2 JS, 22 nodos de grafo, 0 módulos | `REJECT_CODE`, `EXPERIMENT_MTF` |
| `T-NF-PUBLIC` | **YES** (v3, conservado) | chunks servidos por www.nof1.ai | 4 ids (`ev_aee35b0f…` …) | Next.js/Turbopack, 43 scripts | `NO_ADOPTION` (origen desconocido) |
| `T-QR-SIGNAL` | **YES** | `src/dashboard/static` del commit `65e67dc2…` + página en loopback | `ev_9b45318c…`, `ev_b954b8b0…`, `ev_ee6845ff…` | 14 módulos JS, 15.628 nodos AST, `complete` | `DEFER_CODE`, invariante ya cubierto |
| `T-FE-FENIX` | **YES** | `frontend/dist` construido desde `bd7373d5…` + página en loopback | `ev_be8c7d74…`, `ev_fc2b6552…`, `ev_b3b1e837…` | bundle 868 kB, 256.917 nodos AST, `/login` | `DEFER_CODE`, `REJECT` transporte de imagen |
| `T-TA-CRITIC` | NO | — | — | sin superficie JS; un HTML no prueba orquestación | `EXPERIMENT` |
| `T-FM-DEMO` | NO | — | — | sin licencia | `REJECT` |
| `T-TAP-OWN` | NO aplica | — | — | no hay JS propio | verificado con pytest + verificador |

## 2. Hallazgos de fondo (no de forma)

1. **nof1 no es un bot visual.** Cero `image_url`, cero `savefig`, cero payload multimodal en
   todo `src/`. El RFC lo listaba como candidato de visión; la fuente lo desmiente.
2. **nof1 invierte la autoridad.** El LLM emite `leverage` (hasta 15×) y `amountUsdt`. Nuestro
   contrato lo prohíbe; es una diferencia de arquitectura, no de grado.
3. **nof1 declara guardas que no aplica.** El drawdown de cuenta está comentado en el código.
4. **FenixAI transporta la imagen como cadena base64 suelta.** No hay hash, ni símbolo, ni
   reloj ligados a lo que se envía al modelo. Es exactamente el defecto que corregimos.
5. **Semantic Signal es el más cercano a nosotros** y aun así no liga la imagen a un hash:
   logra coherencia por construcción. Nuestro lane es más estricto.

## 2b. Ejecución instrumentada (no REA) del render de FenixAI

`instrumentation/fenix_chart_probe.py` corre el `ChartService` del commit exacto con velas
sintéticas, offline y sin claves: **exit 0**, backend `MPLFINANCE`, PNG de 181.314 B
(sha256 `96c7f41c…`), determinista con las mismas velas, y caché que no cruza símbolos.
La misma ejecución encontró dos defectos reales: sin `mplfinance` el servicio devuelve
`ok=True` con backend `PLACEHOLDER` (`"No chart data available"`), y `get_cached(max_age=0)`
aplica el TTL por defecto porque el cero es falsy. Se etiqueta como
`INSTRUMENTED_EXECUTION_NOT_REA`: REA no ejecuta Python y no se le atribuye.

## 3. Límites técnicos medidos (no excusas)

- `import-reference-source` → **exit 1, `unsupported_host`**: REA no puede importar árboles de
  fuente en Windows (falta *safe no-follow file opens*). Por tanto
  `compare-source-to-bundle` no se pudo ejecutar: exige un `HistoricalSourceGraph` que sólo
  produce el importador bloqueado. Registrado, no simulado.
- Backend Python de QRAK/FENIX y backend TypeScript de nof1 **no se ejecutaron**: requieren
  claves y servicios. Se auditó por fuente; la etiqueta dice fuente, no REA.
- Disco: 2.3 GB libres al empezar. Los tres checkouts (2.3 MB + 6.3 MB + 18 MB) y el build de
  FenixAI (205 MB de `node_modules`) cupieron con margen; no se borró nada ajeno.

## 4. Lo que sigue bloqueado

| bloqueo | estado | qué lo desbloquea |
| --- | --- | --- |
| `REAL_MODEL_CALLED` | **BLOQUEADO** por credencial y presupuesto | autorización explícita de gasto + clave fuera del chat |
| comparación económica | `NOT_EVIDENCE` | una llamada real y corridas con reloj propio |
| `ADOPT_VERIFIED` de patrón externo | 0 | evidencia REA + runtime del upstream reproducido |
| TradingAgents | `EXPERIMENT` | encontrar una superficie que REA pueda observar |

## 5. Verificación

`scripts/ai_bots_rea_verify.py` comprueba los artefactos, no las afirmaciones: ids de 64 hex,
commit completo de 40, hashes de build, ausencia de atribución en el dossier público, y que
el P0 siga cerrado en el runtime. Se probó por mutación: quitar un fichero del dossier debe
hacer fallar el verificador.

## 6. Siguiente paso

Convertir la superficie de nof1 en conducta: `source maps` del despliegue, o levantar el
backend TypeScript en laboratorio con el proveedor mockeado. Cualquier otra cosa es leer un
README con más ceremonia.
