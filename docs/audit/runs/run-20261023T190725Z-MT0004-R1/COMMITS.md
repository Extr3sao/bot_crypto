# Inventario de commits — MT-0004-R1

| # | Commit | Ficheros | Contenido | Verificado |
|---|---|---|---|---|
| 1 | `ef7955dc5973ab863f010e02a1297a455ef276da` | 6 nuevos, +1326 | contratos (`docs/audit/`), arnés de mutantes, 15 tests negativos, guardia de contratos | **sí** — `verification.json`, 13/13 sobre ese commit |
| 2 | el commit que introduce este fichero (`git log -1 --format=%H -- docs/audit/runs`) | 15, +1266 | informes del run, evidencia con hashes, addendum del mapa de autoridad, estado del backlog | n/a: solo registro |

El commit 2 no puede nombrarse a sí mismo; por eso la fila dice cómo obtenerlo en
lugar de transcribir un SHA que cambiaría al escribirlo. Su padre es `ef7955dc`.

## Qué introdujo cada uno

**`ef7955dc`** — la entrega verificada:

- `docs/audit/runtime_authority_map.md`
- `docs/audit/MT-0004-R1.md`
- `docs/audit/AUDIT_BACKLOG.yaml`
- `scripts/audit/negative_controls.py`
- `tests/unit/autonomous/test_kill_switch_negative.py`
- `tests/unit/test_audit_contracts_tracked.py`

**El commit de registro** — nada ejecutable: `RUN_REPORT.md`, `RUN_REPORT.json`,
`FINAL_REPORT.md`, `verification.json`, siete ficheros de `evidence/`, el
addendum §7 del mapa de autoridad y el cambio de `MT-0004-R1` a `done` con su
`verified_commit`.

## Qué no cambió en ninguno de los dos

```bash
git diff --name-only ef7955dc^ HEAD --   src .github pyproject.toml .gitignore uv.lock   tests/unit/autonomous/test_decision_kill_switch.py   tests/unit/test_app_cli_contract.py
# (vacío)
```

## Cómo comprobarlo

```bash
git log --oneline ef7955dc^..HEAD
git show --stat ef7955dc
git show --stat HEAD
```
