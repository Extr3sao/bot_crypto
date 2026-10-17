# INFORME EJECUTIVO — REA-FIRST (RFC-TAP-AI-BOTS-002 v3)

## En una frase

REA se ejecutó de verdad contra **un** target (el bundle público de nof1.ai, cuatro
operaciones con `evidence_id`), **los tres defectos propios que podían producir una operación
falsa están cerrados con tests RED→GREEN**, y **ningún patrón externo se certifica** porque la
evidencia no alcanza la cadena que importa.

## Qué cambia para el proyecto

| Antes | Ahora |
| --- | --- |
| Un hash de imagen distinto se registraba y la operación seguía | `INTEGRITY_FAILURE` ⇒ sin decisión, sin fill |
| Una respuesta tardía podía rellenar al precio de una barra ya abierta | `LATE_RESPONSE` ⇒ se descarta |
| El comparador podía publicar `VISION_ADDS_VALUE` con cadencia o costes distintos | `NOT_COMPARABLE` como veredicto; la aritmética queda aparte |
| REA sólo había corrido `doctor`/`--help` | 4 operaciones reales, 4 `evidence_id`, artefacto fijado por SHA-256 |
| FenixAI figuraba como MIT | Apache-2.0, verificado por API de GitHub |

## Cifras que se pueden comprobar

* Tests: **6 failed / 9 passed** contra `HEAD` antes de los arreglos → **15 passed** después;
  suites focalizadas **372 passed**; `ruff` y `mypy` limpios.
* Verificador propio: **21 PASS / 0 FAIL** (`scripts/ai_bots_rea_verify.py`), y fue el que
  rechazó dos incoherencias del informe antes de publicarlo.
* REA: `doctor` exit 1 (motores nativos ausentes) **no** impidió nada: las cuatro operaciones
  JS/CDP salieron con exit 0.
* Disco: **2,9 GB libres** de 238 GB — el límite real de esta campaña.

## Lo que un lector no debe creer

* Que nof1.ai haya sido «auditado funcionalmente»: se observó su estructura, no su conducta.
* Que nuestros bots hayan superado una prueba económica: el único run existente es un guion
  mock y su resultado (−34,448805 USDT) es del guion.
* Que exista una llamada real al modelo: `REAL_MODEL_CALLED = false`, cero recibos.

## Decisión pedida al usuario

1. **Autorizar o no** una llamada multimodal con presupuesto acotado (hoy `BLOCKED_MODEL_API`).
2. **Liberar espacio** en disco si se quiere clonar/compilar cualquiera de los otros targets:
   sin eso siguen `DEFER` por almacenamiento, no por juicio técnico.
