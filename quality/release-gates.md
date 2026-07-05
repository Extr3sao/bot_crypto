# Release Gates

> Gates de release (paper y live). Si una sola caja no está verde,
> el release NO procede.

---

## Bloque 1 — Calidad de código

- [ ] Code quality gates: `quality/code-quality.md`.
- [ ] Risk quality gates: `quality/risk-quality-gates.md`.
- [ ] `pytest` en verde.
- [ ] `mypy` en verde.
- [ ] `ruff` en verde.

## Bloque 2 — Estrategia / backtest / paper

- [ ] Estrategia en estado correcto (paper o live_candidate).
- [ ] Backtest firmado por `backtest-engineer` y `quant-researcher`.
- [ ] Walk-forward con métricas mínimas.
- [ ] Paper con métricas mínimas (si promoción a live).

## Bloque 3 — Riesgo y seguridad

- [ ] `risk-manager` y `security-reviewer` firmaron.
- [ ] Sin secretos en el repo.
- [ ] `safety` y `pip-audit` limpios.

## Bloque 4 — Operación

- [ ] Logs estructurados funcionando.
- [ ] Health checks activos.
- [ ] Runbook de incidentes disponible.

## Bloque 5 — Promoción a LIVE

> Bloque adicional si el release promueve a `live`.

- [ ] `docs/live-trading-checklist.md` completo y firmado.
- [ ] `LIVE_TRADING_ENABLED=true` y `I_UNDERSTAND_THE_RISKS=true` confirmados.
- [ ] Operador principal + peer firmaron.
- [ ] ADR firmado y publicado.

## Procedimiento

1. Copiar este checklist al inicio del PR/release.
2. Marcar cada ítem con `[x]`, `[ ]` o `NO_APLICA` con justificación.
3. Adjuntar evidencias (enlaces a informes, logs, ADR).
4. Firmar cada bloque.
5. Sin firmas NO hay release.

## Política de excepción

No hay excepción. Si un ítem falla, se documenta en `tasks/decisions.md`
con:
- Justificación escrita.
- Mitigación propuesta.
- Plan de remediación con fecha.
- Firma humana.

---

## Bloque 6 — Branch Protection Rules (TSK-009)

> Reglas recomendadas para `main` en GitHub. Aplicar via GitHub UI o
> `gh api` con un PAT admin. Ninguna se aplica automáticamente al bot
> si el repo no concede permisos de admin — son **recomendaciones**
> operadas por humanos con permisos de owner.

### Required status checks (alineados a `docs/ci.md` §3)

| Job name (en `.github/workflows/ci.yml`) | Gate que pinea                          |
| ---------------------------------------- | -------------------------------------- |
| `format-and-lint`                        | `ruff format --check` + `ruff check`   |
| `type-check`                             | `mypy .` strict                        |
| `pip-audit`                              | `pip-audit -r reqs.txt`                |
| `tests-and-coverage`                     | `pytest --cov --cov-fail-under=90`     |
| `validate-local` (opcional)              | `python -m trading_bot.config --validate` |

Todos estos jobs deben tener `Required: ✅` para que un PR pueda
mergear a `main`. Si un job renombra, hay que actualizar aquí y en
`docs/ci.md` simultáneamente — pinear consistencia entre los 3
archivos.

### Required reviewers (alineados a `.github/CODEOWNERS`)

- `required_approving_review_count = 1` mínimo globalmente.
- **2 required reviewers** para paths sensibles (CODEOWNERS fuerza
  automáticamente la doble firma cuando un path listado cambia):
  - `src/trading_bot/risk/`
  - `src/trading_bot/execution/`
  - `src/trading_bot/config/`
  - `.env.example`, secrets handlers
  - `.github/workflows/`
  - `config/risk.yaml`, `config/runtime.yaml`
  - `pyproject.toml`, `uv.lock`, `.python-version`

### Restrictions extra (binarias)

- `require_code_owner_reviews: true` (CODEOWNERS es el gate humano).
- `dismiss_stale_reviews_on_push: true` (reviews caducan al recibir
  nuevos commits en el PR).
- `require_linear_history: true` (no merge commits).
- `allow_force_pushes: false` (salvo rama admin-only con justificación
  explícita en ADR).
- `allow_deletions: false`.
- `block_creations: false` (PRs desde forks permitidos para externos).
- `required_conversation_resolution: false` durante bootstrap
  (muchos bots dejan hilos abiertos en PRs hasta madurar). Activar
  a `true` solo cuando los bots auto-resuelvan sus propios comentarios
  (ADR firmada cuando se cambie).
- `lock_branch: false` (no se freeze main durante hotfixes; el kill
  switch existe a nivel runtime, no a nivel git).
- `required_signatures: false` (signed commits opcionales en fase
  temprana; activar en fase de review de seguridad con ADR firmada).

### Comandos `gh api` para aplicar las reglas

> Pre-flight: confirma que `gh auth status` reporta scope `repo` +
> `admin:org`. Si no, `gh auth refresh -s admin:org,repo`.

```powershell
# 1. (Opcional) Ver estado actual antes de tocar
gh api /repos/Extr3sao/bot_crypto/branches/main/protection `
  --jq '{required_status_checks, required_pull_request_reviews, allow_force_pushes, required_linear_history}'

# 2. Aplicar protection rules vía PUT con JSON inline
$rules = @'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "format-and-lint",
      "type-check",
      "pip-audit",
      "tests-and-coverage"
    ]
  },
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1,
    "bypass_pull_request_allowances": {
      "users": [],
      "teams": ["Extr3sao/maintainers"]
    }
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
'@
$rules | gh api --method PUT `
  -H "Accept: application/vnd.github+json" `
  /repos/Extr3sao/bot_crypto/branches/main/protection `
  --input -
```

Si prefieres desde bash:

```bash
cat > branch-protection.json <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["format-and-lint", "type-check", "pip-audit", "tests-and-coverage"]
  },
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": false
}
EOF

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/Extr3sao/bot_crypto/branches/main/protection \
  --input branch-protection.json
```

### Post-apply validation

```powershell
# Confirmar que las reglas quedaron aplicadas
gh api /repos/Extr3sao/bot_crypto/branches/main/protection `
  --jq '.required_status_checks.contexts, .required_pull_request_reviews.required_approving_review_count, .required_linear_history, .allow_force_pushes'

# Smoke test: abrir un PR dummy y verificar que el job `format-and-lint`
# es required. NO mergear — cerrarlo inmediatamente.
gh pr create --base main --title "chore(test): branch protection smoke test" --body "Will be closed immediately. Validates branch-protection rules only."
```

### Riesgos y mitigaciones (CODEOWNERS + branch protection)

| Riesgo                                                              | Mitigación                                                                                              |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Equipos CODEOWNERS no existen aún en el org → CODEOWNERS no bloquea | Pre-flight: `gh api /orgs/Extr3sao/teams --jq '.[].slug'` antes de mergear `.github/CODEOWNERS`.        |
| Status check names no coinciden entre `ci.yml` y branch protection  | Tras aplicar protection, abrir PR dummy de prueba. Cerrarlo sin mergear. Validar manualmente.          |
| `main` queda infranqueable si CODEOWNERS no tiene aprobador         | Consortium role (CODEOWNERS fallback `@Extr3sao/maintainers`) con 2-3 personas como miembros.          |
| Force-push sigue permitido para admins                               | Cambiar `enforce_admins: true` en `required_pull_request_reviews` cuando se quiera veto absoluto.       |
| CODEOWNERS pierde track tras renombre de usuario                   | Validar handles con `gh api /repos/{org}/{repo}/codeowners/errors` post-merge del archivo CODEOWNERS.   |

### Procedimiento de revisión periódica

Cada cierre de sprint, revisar:

1. ¿Las reglas aplicadas coinciden con las de este documento y
   `.github/CODEOWNERS`?
2. ¿Los status check jobs todavía existen (no fueron renombrados)?
3. ¿Los equipos CODEOWNERS siguen existiendo con miembros activos?
4. ¿Algún path crítico nuevo en el repo necesita estar listado?

Desviaciones → ADR firmada y actualización simultánea de los 3 archivos:
`.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`,
`quality/release-gates.md`.
