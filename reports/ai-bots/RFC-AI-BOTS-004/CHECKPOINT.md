# CHECKPOINT — RFC-TAP-AI-BOTS-004 / BOT-CRI-01

**Actualizado:** 2026-10-18
**Rama:** `agent/ai-critic/RFC-TAP-AI-BOTS-004`
**Worktree:** `C:/Users/GVLLFR0035/Downloads/bot_crypto_004` (creado desde `b7e100a`)
**Base:** `b7e100a` · **C1:** ver `git log -1 --format=%H` (implementación + evidencia)
**Estado:** `IMPLEMENTED / SHADOW_ONLY` · `ECONOMIC_VALUE=UNMEASURED` · `GATED_PAPER=BLOCKED`

## 1. Objetivo

Crear BOT-CRI-01 (crítico epistemológico) a partir del mecanismo estudiado en
`TauricResearch/TradingAgents` @ `e8f5503e…`, con REA real sobre la página renderizada por el
upstream y conducta Python probada offline. Primero `SHADOW_ONLY`; sin cambios en fills,
PnL, riesgo ni cierres.

## 2. Hecho

1. Worktree aislado; el árbol de AI-BOTS-003C no se inspeccionó ni modificó.
2. Fuente pinneada y licencia verificada; 15 ficheros con SHA (`SOURCE_MANIFEST.json`).
3. Harness offline con los nodos originales: 21/21 checks, 0 llamadas de red, 0 órdenes,
   `MODEL_STATUS=STUB`; 9 filas de traza con cadena de estados.
4. Tests upstream focales: 64 passed, exit 0.
5. `complete_report.html` generado por el renderizador original (sin JS, sin assets remotos).
6. REA 6.4.0 real: target listado, DOM inspeccionado, screenshot capturado; 3 evidence ids
   nativos; estado `REA_UI_OBSERVED`.
7. Paquete `trading_bot.intelligence.ai_critic` con contratos `extra=forbid`, hash congelado,
   evidencia autenticada, presupuesto/deadline, fail-closed y política de gate mínima.
8. `BOT-CRI-01` registrado **OFF**; sin herramientas de ejecución.
9. ACC-CRI-01..16: RED en `b7e100a` (exit 2), GREEN en HEAD (17 passed).
10. Ablación NO_CRITIC / SHADOW / NO_TRADE con economía idéntica; GATED no ejecutado.
11. Verificador independiente 59/59 y 7/7 mutaciones rechazadas por regla.

## 3. Pendiente / bloqueado

- `GATED_PAPER` — bloqueado hasta que AI-BOTS-003C esté certificado. No activar el flag.
- Llamada real a modelo — requiere credencial y autorización de gasto explícita.
- Ablación prospectiva — sin muestra OOS; `ECONOMIC_VALUE=UNMEASURED`.
- `RFC_TAP_AI_BOTS_004_REA_INDEPENDENT_CRITIC.md` no estaba adjunto; ACC reconstruido.
- Segundo agente debe re-ejecutar el verificador (mismo autor en builder y verifier).

## 4. Reanudación exacta

```bash
cd "C:/Users/GVLLFR0035/Downloads/bot_crypto_004"
git status --porcelain                       # esperado: limpio en el commit publicado
git log -1 --format='%H %s'
PYTHONPATH="$PWD/src" "/c/Users/GVLLFR0035/Downloads/bot freebuff/.venv/Scripts/python.exe" \
  -m pytest tests/unit/intelligence/ai_critic tests/unit/intelligence/ai_bots -q
../ta_lab/.venv/Scripts/python.exe scripts/ai_critic/verify_rfc004.py \
  --root reports/ai-bots/RFC-AI-BOTS-004 --mutations
```

Resultado esperado: 45 passed; verificador `PASS` con 59/59 checks y 7/7 mutaciones.

## 5. Reglas que no se relajan

`FALSE_SUCCESS=0` · `BUILDER != VERIFIER` (estructural) · `TEST_TARGET==RUNTIME_TARGET`
(`trading_bot.intelligence.ai_critic`) · `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`.

Un checkpoint no declara terminado lo no ejecutado: `GATED_PAPER` y `REAL_CRITIC_MODEL_CALLED`
siguen en falso hasta que exista evidencia.
