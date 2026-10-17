# T-QR-SIGNAL · Decisión de adopción

**Decisión: `DEFER`.**

* `REA_EXECUTED = NO`. Ningún `evidence_id` de este target: no se ha ejecutado REA contra él.
* Operación que aplicaría: inspect_web_page / capture-browser-scenario sobre panel local.
* Motivo medido: la UI es Streamlit: el DOM y el JS que vería REA son del framework, no de la lógica del proyecto; capturarla probaría la existencia del panel, no su cadena de decisión. La lógica está en Python y se audita con fuente/tests, no con REA. No se clonó ni sirvió localmente el target: el disco del host está al 99 % (2,9 GB libres de 238 GB) y el RFC prohíbe relajar el guardián de almacenamiento o borrar trabajo ajeno para hacer sitio. Es un BLOCKED_STORAGE medido, no una imposibilidad técnica afirmada.
* Licencia: MIT.

No se atribuye a este target ninguna certificación `REA_AUDITED`, `BEHAVIOR_RECONSTRUCTED`
ni `ADOPT_VERIFIED`. Si aparece un artefacto local autorizado y hay espacio, el dossier se
completa con `TARGET_BASELINE` + `REA_COMMAND_LOG` + `REA_EVIDENCE` reales.
