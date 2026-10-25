# T-NF-PUBLIC · Decisión de adopción

**Decisión: `DEFER` (código `REJECT`; patrón `EXPERIMENT`).**

* `REA_EXECUTED = YES` sobre el artefacto **compilado** público (4 operaciones, 4 evidence_id
  reales, exit 0 todos).
* `REA_EVIDENCE_ID` válidos: `ev_aee35b0f…`, `ev_f7020db1…`, `ev_47c01acc…`, `ev_82d99570…`.
* `UPSTREAM_RUNTIME_REPRODUCED = NO`: REA no ejecuta el JS y el bundle minificado no expone
  la cadena gráfico→modelo→decisión.
* `LICENSE = AGPL-3.0` (verificada por API de GitHub). **No se importa ni se traduce código.**
* Valor observado: el sitio sirve un frontend Next.js con chunks separados y endpoints
  minificados; nada que nuestro `BOT-VIS-01` no tenga ya con contrato explícito.

**Qué haría falta para subir de DEFER a ADOPT/REJECT razonado**: un build de laboratorio
con source maps (`--fetch-source-maps`) o el árbol TS con nombres legibles, y una captura
de red que muestre la petición al modelo. Sin eso, cualquier afirmación sobre su
comportamiento sería una suposición.
