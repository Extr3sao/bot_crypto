# WP-EDGE-05R — storage diagnosis: where the volume went, and what is mine to move

*Read at `2026-10-14T05:45:20Z` on `DESKTOP-4CHO695`. Read-only: this file sizes things and says who owns them; it deletes nothing.*

## 1. The volume

| | |
| --- | --- |
| Volume | `C:` |
| Free | **5.48 GiB** (5883957248 bytes) |
| Total | 255041990656 bytes (237.5 GiB) |
| Used | 97.69 % |
| Critical floor (the lane's own) | 2147483648 bytes (2 GiB) |
| Healthy floor (the lane's own) | 5368709120 bytes (5 GiB) |

This repository is **5.331 GiB** (5724066394 bytes, 26178 files), which is **2.24 %** of the volume. The rest of the 237.5 GiB is outside this repository and outside this workstream's authority: it is not touched, not measured further, and only named as context for the owner.

## 2. Every top-level subtree, by kind of bytes and by owner

| Path | Size | Files | Kind | Owner | Basis of the attribution |
| --- | --- | --- | --- | --- | --- |
| `reports/` | 4,731.9 MiB | 7032 | EVIDENCE | mixed — see the breakdown | its children are attributed one by one below |
| `.venv/` | 453.6 MiB | 11333 | ENVIRONMENT | n/a — not a workstream | a kind of bytes, not an owner |
| `data/` | 197.3 MiB | 873 | MARKET_DATA_AND_LIVE_STATE | mixed — see the breakdown | its children are attributed one by one below |
| `.git/` | 45.3 MiB | 5050 | VERSION_HISTORY | n/a — not a workstream | a kind of bytes, not an owner |
| `scripts/` | 7.7 MiB | 321 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `logs/` | 7.7 MiB | 93 | OPERATIONAL_LOGS | repository tooling | a repository file, not a workstream's artefact |
| `src/` | 5.2 MiB | 425 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `tests/` | 2.7 MiB | 251 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `docs/` | 2.5 MiB | 514 | EVIDENCE | repository tooling | a repository file, not a workstream's artefact |
| `evidence/` | 1.8 MiB | 12 | EVIDENCE | mixed — see the breakdown | its children are attributed one by one below |
| `.ci/` | 1.1 MiB | 82 | EVIDENCE | repository tooling | a repository file, not a workstream's artefact |
| `research/` | 0.9 MiB | 105 | EVIDENCE | repository tooling | a repository file, not a workstream's artefact |
| `uv.lock` | 0.5 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `tasks/` | 0.2 MiB | 6 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `context/` | 0.1 MiB | 6 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `config/` | 0.1 MiB | 16 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `.ai/` | 0.0 MiB | 23 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `.github/` | 0.0 MiB | 5 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `bdd/` | 0.0 MiB | 8 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `quality/` | 0.0 MiB | 3 | SOURCE | repository tooling | a repository file, not a workstream's artefact |
| `PAPER_DATA_24H_REPORT.json` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `.gitignore` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `README.md` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `pr-body-TASK-103.5.md` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `PAPER_DATA_24H_REPORT.md` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `AGENTS.md` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `pyproject.toml` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `reqs.txt` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `FINAL_REPORT.md` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `RUN_REPORT.md` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `RUN_REPORT.json` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `.env.example` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `docker-compose.yml` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `.gitattributes` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `evals/` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `notebooks/` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `.rfc048v_certify.log` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `.freebuff/` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `.python-version` | 0.0 MiB | 1 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |
| `-p/` | 0.0 MiB | 0 | UNCLASSIFIED | repository tooling | a repository file, not a workstream's artefact |

> An owner is stated from a **path prefix**, and the basis is printed next to it. Where no rule matches, the row says `UNATTRIBUTED` rather than inventing an owner.

### `data/`, one level down

| Path | Size | Files | Owner | Basis |
| --- | --- | --- | --- | --- |
| `data/raw/` | 145.0 MiB | 132 | UNATTRIBUTED | no rule matched |
| `data/st6/` | 17.7 MiB | 366 | st6 | path prefix 'data/st6' |
| `data/forward/` | 17.2 MiB | 115 | UNATTRIBUTED | no rule matched |
| `data/rfc049/` | 5.5 MiB | 94 | UNATTRIBUTED | no rule matched |
| `data/swing/` | 4.2 MiB | 19 | UNATTRIBUTED | no rule matched |
| `data/rfc048/` | 3.2 MiB | 28 | UNATTRIBUTED | no rule matched |
| `data/recovery/` | 1.9 MiB | 89 | wp8-recovery | path prefix 'data/recovery' |
| `data/rfc035e/` | 1.1 MiB | 3 | rfc035e | path prefix 'data/rfc035e' |
| `data/rfc035s3/` | 0.7 MiB | 4 | UNATTRIBUTED | no rule matched |
| `data/economic001/` | 0.6 MiB | 7 | UNATTRIBUTED | no rule matched |
| `data/rfc046/` | 0.1 MiB | 9 | UNATTRIBUTED | no rule matched |
| `data/pgate035/` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `data/storage/` | 0.0 MiB | 4 | UNATTRIBUTED | no rule matched |
| `data/backtests/` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `data/processed/` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |

### `reports/`, one level down

| Path | Size | Files | Owner | Basis |
| --- | --- | --- | --- | --- |
| `reports/microstructure-forward-continuous/` | 1,661.3 MiB | 1132 | UNATTRIBUTED | no rule matched |
| `reports/cap004/` | 1,126.2 MiB | 52 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab/` | 530.7 MiB | 421 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward/` | 360.2 MiB | 107 | UNATTRIBUTED | no rule matched |
| `reports/rfc010/` | 232.8 MiB | 75 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-v1/` | 92.4 MiB | 67 | UNATTRIBUTED | no rule matched |
| `reports/paper-burn-in/` | 83.8 MiB | 163 | UNATTRIBUTED | no rule matched |
| `reports/positioning-data/` | 52.4 MiB | 22 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-ops01/` | 47.4 MiB | 122 | UNATTRIBUTED | no rule matched |
| `reports/edge-recovery/` | 43.4 MiB | 205 | WP-EDGE-00 | path prefix 'reports/edge-recovery' |
| `reports/alpha-diversified-v1/` | 42.4 MiB | 155 | UNATTRIBUTED | no rule matched |
| `reports/strategy-baseline/` | 39.8 MiB | 130 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-cert01/` | 37.6 MiB | 94 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-headcert/` | 35.8 MiB | 220 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-08/` | 34.2 MiB | 86 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-06/` | 28.6 MiB | 147 | UNATTRIBUTED | no rule matched |
| `reports/autonomous-paper/` | 28.3 MiB | 219 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-recert-7b14297/` | 24.2 MiB | 252 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-headcert-222078b/` | 23.9 MiB | 300 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-03/` | 22.6 MiB | 55 | UNATTRIBUTED | no rule matched |
| `reports/managed-futures-v1/` | 21.2 MiB | 79 | UNATTRIBUTED | no rule matched |
| `reports/alpha-expansion-v1/` | 18.6 MiB | 54 | UNATTRIBUTED | no rule matched |
| `reports/alpha-recovery-v1-4/` | 16.6 MiB | 51 | UNATTRIBUTED | no rule matched |
| `reports/carry/` | 14.6 MiB | 40 | UNATTRIBUTED | no rule matched |
| `reports/paper-lab/` | 13.6 MiB | 205 | UNATTRIBUTED | no rule matched |
| `reports/perp-tsmom/` | 12.5 MiB | 257 | UNATTRIBUTED | no rule matched |
| `reports/wp-strat-08/` | 11.3 MiB | 72 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-05/` | 9.1 MiB | 53 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-04/` | 6.3 MiB | 21 | UNATTRIBUTED | no rule matched |
| `reports/rfc020/` | 5.6 MiB | 18 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-v2/` | 5.5 MiB | 7 | UNATTRIBUTED | no rule matched |
| `reports/strategy-audit/` | 5.4 MiB | 14 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-07/` | 4.8 MiB | 44 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-smoke/` | 3.7 MiB | 46 | UNATTRIBUTED | no rule matched |
| `reports/edge-discovery/` | 3.6 MiB | 108 | UNATTRIBUTED | no rule matched |
| `reports/baseline/` | 3.0 MiB | 20 | UNATTRIBUTED | no rule matched |
| `reports/alpha002/` | 2.9 MiB | 16 | UNATTRIBUTED | no rule matched |
| `reports/external-alpha/` | 2.9 MiB | 93 | UNATTRIBUTED | no rule matched |
| `reports/paper-strategy-lifecycle-shadow-02/` | 2.2 MiB | 23 | UNATTRIBUTED | no rule matched |
| `reports/alpha001/` | 2.2 MiB | 46 | UNATTRIBUTED | no rule matched |
| `reports/agentic-campaign-cap003/` | 1.4 MiB | 33 | UNATTRIBUTED | no rule matched |
| `reports/small-capital-v1/` | 1.2 MiB | 46 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-smoke-cert4/` | 0.9 MiB | 61 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-writercert/` | 0.8 MiB | 22 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-smoke-cert2/` | 0.7 MiB | 40 | UNATTRIBUTED | no rule matched |
| `reports/paper/` | 0.7 MiB | 14 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-smoke-cert/` | 0.7 MiB | 40 | UNATTRIBUTED | no rule matched |
| `reports/agentic-pilot-cap002/` | 0.7 MiB | 14 | UNATTRIBUTED | no rule matched |
| `reports/small-capital-dual-momentum-v1/` | 0.7 MiB | 35 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-lab-smoke-cert3/` | 0.7 MiB | 40 | UNATTRIBUTED | no rule matched |
| `reports/dashboard.log` | 0.6 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-storage-policy/` | 0.5 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-diskguard/` | 0.5 MiB | 16 | UNATTRIBUTED | no rule matched |
| `reports/manifest-blocked-probe/` | 0.5 MiB | 15 | UNATTRIBUTED | no rule matched |
| `reports/paper-strategy-lifecycle-shadow-01/` | 0.5 MiB | 37 | UNATTRIBUTED | no rule matched |
| `reports/rfc035/` | 0.4 MiB | 32 | UNATTRIBUTED | no rule matched |
| `reports/alpha003/` | 0.4 MiB | 22 | UNATTRIBUTED | no rule matched |
| `reports/cap004d/` | 0.4 MiB | 14 | UNATTRIBUTED | no rule matched |
| `reports/structural-carry/` | 0.3 MiB | 39 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-preservation-check/` | 0.3 MiB | 56 | UNATTRIBUTED | no rule matched |
| `reports/generalization/` | 0.3 MiB | 36 | UNATTRIBUTED | no rule matched |
| `reports/directional/` | 0.2 MiB | 33 | UNATTRIBUTED | no rule matched |
| `reports/headcert-222078b.log` | 0.2 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/rfc035e/` | 0.2 MiB | 16 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle-verification/` | 0.2 MiB | 32 | UNATTRIBUTED | no rule matched |
| `reports/recert-7b14297.log` | 0.2 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/cap004c/` | 0.2 MiB | 19 | UNATTRIBUTED | no rule matched |
| `reports/obs-strat-01/` | 0.2 MiB | 15 | UNATTRIBUTED | no rule matched |
| `reports/profitability_gate035/` | 0.2 MiB | 13 | UNATTRIBUTED | no rule matched |
| `reports/data-integrity/` | 0.2 MiB | 21 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-headcert.log` | 0.1 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/alpha-recovery-v1-1/` | 0.1 MiB | 47 | UNATTRIBUTED | no rule matched |
| `reports/profitability-v2/` | 0.1 MiB | 22 | UNATTRIBUTED | no rule matched |
| `reports/runs/` | 0.1 MiB | 12 | UNATTRIBUTED | no rule matched |
| `reports/business-opportunity-radar/` | 0.1 MiB | 18 | UNATTRIBUTED | no rule matched |
| `reports/wp-strat-09/` | 0.1 MiB | 22 | UNATTRIBUTED | no rule matched |
| `reports/alpha-recovery-v1-2/` | 0.1 MiB | 29 | UNATTRIBUTED | no rule matched |
| `reports/rfc046/` | 0.1 MiB | 4 | UNATTRIBUTED | no rule matched |
| `reports/alpha-recovery-v1/` | 0.1 MiB | 36 | UNATTRIBUTED | no rule matched |
| `reports/strategy-dashboard-independent-verification/` | 0.1 MiB | 24 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle-independent-verification/` | 0.1 MiB | 18 | strategy-lifecycle | path prefix 'reports/strategy-lifecycle-independent-verification' |
| `reports/source-runtime-verification/` | 0.1 MiB | 18 | UNATTRIBUTED | no rule matched |
| `reports/smoke-cert4.log` | 0.1 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/managed-futures-decision/` | 0.1 MiB | 22 | UNATTRIBUTED | no rule matched |
| `reports/paper-certification/` | 0.1 MiB | 35 | UNATTRIBUTED | no rule matched |
| `reports/execution-economics/` | 0.1 MiB | 36 | UNATTRIBUTED | no rule matched |
| `reports/source-runtime-reconciliation/` | 0.1 MiB | 7 | UNATTRIBUTED | no rule matched |
| `reports/cap004b/` | 0.1 MiB | 28 | UNATTRIBUTED | no rule matched |
| `reports/smoke-cert2.log` | 0.1 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/smoke-cert3.log` | 0.1 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/smoke-cert.log` | 0.1 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/arp-012-exp-019-independent/` | 0.1 MiB | 29 | UNATTRIBUTED | no rule matched |
| `reports/strategy-closure/` | 0.1 MiB | 18 | UNATTRIBUTED | no rule matched |
| `reports/exp-arp-008-oos-verification/` | 0.1 MiB | 23 | UNATTRIBUTED | no rule matched |
| `reports/source-ingestion/` | 0.1 MiB | 43 | UNATTRIBUTED | no rule matched |
| `reports/strategy-dynamic/` | 0.1 MiB | 24 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle-hardening/` | 0.1 MiB | 19 | UNATTRIBUTED | no rule matched |
| `reports/post-oos-recovery/` | 0.1 MiB | 18 | UNATTRIBUTED | no rule matched |
| `reports/tsmom-remediation/` | 0.1 MiB | 23 | UNATTRIBUTED | no rule matched |
| `reports/alpha-recovery-v1-3/` | 0.1 MiB | 31 | UNATTRIBUTED | no rule matched |
| `reports/profitability-operating-model/` | 0.1 MiB | 18 | UNATTRIBUTED | no rule matched |
| `reports/rfc000/` | 0.1 MiB | 19 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle-persistence/` | 0.0 MiB | 20 | UNATTRIBUTED | no rule matched |
| `reports/business-freeze/` | 0.0 MiB | 14 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle-gate0/` | 0.0 MiB | 11 | UNATTRIBUTED | no rule matched |
| `reports/failure-injection/` | 0.0 MiB | 10 | UNATTRIBUTED | no rule matched |
| `reports/reentry-watch/` | 0.0 MiB | 8 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle-router/` | 0.0 MiB | 10 | UNATTRIBUTED | no rule matched |
| `reports/rfc030-short-data/` | 0.0 MiB | 11 | UNATTRIBUTED | no rule matched |
| `reports/arp-011-exp-019/` | 0.0 MiB | 21 | UNATTRIBUTED | no rule matched |
| `reports/rfc030/` | 0.0 MiB | 13 | UNATTRIBUTED | no rule matched |
| `reports/orthogonal-data/` | 0.0 MiB | 10 | UNATTRIBUTED | no rule matched |
| `reports/agentic-spike-cap001/` | 0.0 MiB | 11 | UNATTRIBUTED | no rule matched |
| `reports/RFC029_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC038_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/arp-010-exp-022/` | 0.0 MiB | 19 | UNATTRIBUTED | no rule matched |
| `reports/agentic-spike-cap002/` | 0.0 MiB | 11 | UNATTRIBUTED | no rule matched |
| `reports/arp-009-exp-021/` | 0.0 MiB | 17 | UNATTRIBUTED | no rule matched |
| `reports/recovery/` | 0.0 MiB | 2 | UNATTRIBUTED | no rule matched |
| `reports/managed-futures-refutation/` | 0.0 MiB | 34 | UNATTRIBUTED | no rule matched |
| `reports/strategy-lifecycle/` | 0.0 MiB | 11 | UNATTRIBUTED | no rule matched |
| `reports/status-failinject.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP003_CAMPAIGN_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/rfc021/` | 0.0 MiB | 6 | UNATTRIBUTED | no rule matched |
| `reports/CAP003_CAMPAIGN_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC028_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP002_REAL_PILOT_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP002_REAL_PILOT_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC010B_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC036_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/recovery_pytest.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/EDGE_DISCOVERY_SPRINT002_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC023_GENERALIZATION_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/microstructure-forward-headcert-report.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC041_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC037_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC020_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/headcert_replay.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/recert-replay.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/cert01_replay.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/final_pytest.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC025_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC023_GENERALIZATION_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC021_EDGE001_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/ALPHA_SCORECARD.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP002_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/ECONOMIC_STRATEGY_CHECKPOINT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC040_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/headcert_report.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/cert01_report.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC026_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC039_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP002_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC030_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/paper-lab-ops-hardening/` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC031_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC041_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/EDGE_DISCOVERY_SPRINT002_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/PROFITABILITY_DECISION.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/EDGE_DISCOVERY_SPRINT001_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC030_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/alpha001_driver.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC027_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC032_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC033_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/paper-lab-continuous-02.launch.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/final_pytest2.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/recovery_pytest2.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC040_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC031_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP001_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/CAP001_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/tmp-guard-debug/` | 0.0 MiB | 2 | UNATTRIBUTED | no rule matched |
| `reports/paper-lab-cert-01.launch.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC038_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC039_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC042_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC034_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC035_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC043_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC025_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC032_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC035_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC033_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC042_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/_rfc033_universe_probe.txt` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC028_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC034_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC037_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/ALPHA_SCORECARD.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/FINAL_STRATEGIC_PROJECT_DECISION.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/carry_run.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC044_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC029_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC043_FINAL_REPORT.json` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC026_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/mf_ef.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/mf_cd.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/mf_ab.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/fetch_baseline.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC036_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/fetch_extended_v1_4.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC044_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/carry_fetch.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/RFC027_FINAL_REPORT.md` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/_rfc033_fetch.log` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/.gitkeep` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |
| `reports/status-failinject.err` | 0.0 MiB | 1 | UNATTRIBUTED | no rule matched |

### `evidence/`, one level down

| Path | Size | Files | Owner | Basis |
| --- | --- | --- | --- | --- |
| `evidence/real_decisions/` | 1.8 MiB | 12 | cap-003/004 | path prefix 'evidence/real_decisions' |

## 3. The largest individual files

| Size | Path | Owner |
| --- | --- | --- |
| 545.59 MiB | `reports/cap004/archive/legacy-20261007T1556Z/daily/2026-10-06.json.gz` | UNATTRIBUTED |
| 474.73 MiB | `reports/cap004/archive/legacy-20261007T1556Z/daily/2026-10-07.json.gz` | UNATTRIBUTED |
| 176.24 MiB | `.venv/Lib/site-packages/_polars_runtime_32/_polars_runtime.pyd` | UNATTRIBUTED |
| 104.43 MiB | `reports/cap004/archive/legacy-20261007T1556Z/cycles.jsonl.gz` | UNATTRIBUTED |
| 53.84 MiB | `reports/microstructure-forward/segments/binance/perp/ETHUSDT/book_ticker/2026-09-28/160000.jsonl.gz` | UNATTRIBUTED |
| 50.58 MiB | `reports/microstructure-forward/segments/binance/perp/BTCUSDT/book_ticker/2026-09-28/160000.jsonl.gz` | UNATTRIBUTED |
| 40.36 MiB | `reports/rfc010/runs/RFC010B-SAMPLE-1/traces.jsonl` | UNATTRIBUTED |
| 31.30 MiB | `.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-caad452230ae4ddb57899b8b3a33c55c.dll` | UNATTRIBUTED |
| 30.81 MiB | `.venv/Scripts/ruff.exe` | UNATTRIBUTED |
| 28.37 MiB | `reports/microstructure-forward/segments/binance/spot/BTCUSDT/book_ticker/2026-09-28/160000.jsonl.gz` | UNATTRIBUTED |
| 28.09 MiB | `data/raw/alpha002/CAPTURE_LOG.jsonl` | UNATTRIBUTED |
| 27.82 MiB | `reports/microstructure-forward/segments/binance/perp/ETHUSDT/book_ticker/2026-09-28/150000.jsonl.gz` | UNATTRIBUTED |
| 26.62 MiB | `reports/microstructure-forward/segments/binance/perp/BTCUSDT/book_ticker/2026-09-28/150000.jsonl.gz` | UNATTRIBUTED |
| 24.86 MiB | `reports/microstructure-forward-continuous/segments/binance/perp/BTCUSDT/book_ticker/2026-09-30/020000.jsonl.gz` | UNATTRIBUTED |
| 23.20 MiB | `reports/microstructure-forward/segments/binance/perp/SOLUSDT/book_ticker/2026-09-28/160000.jsonl.gz` | UNATTRIBUTED |
| 23.13 MiB | `reports/microstructure-forward-lab/segments/binance/perp/BTCUSDT/book_ticker/2026-10-01/180000.jsonl.gz` | UNATTRIBUTED |
| 22.98 MiB | `reports/microstructure-forward-lab/segments/binance/perp/ETHUSDT/book_ticker/2026-10-01/180000.jsonl.gz` | UNATTRIBUTED |
| 22.19 MiB | `reports/microstructure-forward-lab/segments/binance/perp/BTCUSDT/book_ticker/2026-10-01/161500.jsonl.gz` | UNATTRIBUTED |
| 21.77 MiB | `reports/microstructure-forward/segments/binance/spot/ETHUSDT/book_ticker/2026-09-28/160000.jsonl.gz` | UNATTRIBUTED |
| 20.16 MiB | `reports/microstructure-forward-continuous/segments/binance/perp/BTCUSDT/book_ticker/2026-09-30/194500.jsonl.gz` | UNATTRIBUTED |

## 4. The reclaim plan, and the proof behind every row

Rule: only a tool cache a tool regenerates, that git does not track and that .gitignore names; every row carries its own three checks.

**Safe to reclaim: 19.81 MiB (20771371 bytes).**

* 18.89 MiB — interpreter bytecode inside the project environment
* 0.91 MiB — repository tool cache

| Path | Size | Scope | Regenerated by | Tracked by git | Ignored | Safe |
| --- | --- | --- | --- | --- | --- | --- |
| `.venv/Lib/site-packages/ccxt/__pycache__` | 10,164.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/abstract/__pycache__` | 2,703.9 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/rich/__pycache__` | 689.0 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `src/trading_bot/research/__pycache__` | 587.0 KiB | repository tool cache | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pydantic/__pycache__` | 559.2 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/base/__pycache__` | 531.6 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pydantic/_internal/__pycache__` | 506.9 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/structlog/__pycache__` | 274.9 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/yaml/__pycache__` | 269.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/requests/__pycache__` | 255.6 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/urllib3/__pycache__` | 253.7 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/marshmallow/__pycache__` | 227.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/attr/__pycache__` | 218.4 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/__pycache__` | 183.7 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pydantic_settings/sources/providers/__pycache__` | 171.8 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pydantic_core/__pycache__` | 162.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/toolz/__pycache__` | 160.1 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/ethereum/abi/__pycache__` | 134.8 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/ecdsa/__pycache__` | 124.7 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/charset_normalizer/__pycache__` | 114.8 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/urllib3/util/__pycache__` | 112.4 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `scripts/__pycache__` | 91.4 KiB | repository tool cache | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pygments/__pycache__` | 88.9 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/tenacity/__pycache__` | 87.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pygments/lexers/__pycache__` | 82.1 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/starkware/crypto/__pycache__` | 74.9 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `src/trading_bot/market_data/__pycache__` | 74.3 KiB | repository tool cache | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/ethereum/utils/__pycache__` | 74.1 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/cryptography/hazmat/primitives/serialization/__pycache__` | 73.9 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/parsimonious/__pycache__` | 72.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/coincurve/__pycache__` | 63.2 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `src/trading_bot/backtesting/__pycache__` | 62.4 KiB | repository tool cache | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/msgpack/__pycache__` | 57.0 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/idna/__pycache__` | 56.5 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `src/trading_bot/config/__pycache__` | 53.6 KiB | repository tool cache | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/ccxt/static_dependencies/bip/bip32/__pycache__` | 52.1 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pydantic_settings/sources/__pycache__` | 51.2 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/cryptography/hazmat/primitives/asymmetric/__pycache__` | 47.4 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/pydantic_settings/__pycache__` | 43.3 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| `.venv/Lib/site-packages/colorama/__pycache__` | 41.4 KiB | interpreter bytecode inside the project environment | python (bytecode cache) | False | True | True |
| *(53 more rows in the JSON)* | | | | | | |

market data, evidence, other workstreams' artefacts, source and the environment are sized here and left alone: deleting them is a decision for the owner, not a cleanup.

## 5. Every figure above, with the instant it was read at

| Figure | Value | Unit | as_of_utc | Source artefact | Source digest | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| `volume_free_bytes` | 5883957248 | bytes | 2026-10-14T05:45:20Z | operating system, disk_usage of the repository volume | `b3a2bd4835cac7fd…` | volume C: as seen from C:\Users\GVLLFR0035\Downloads\bot freebuff |
| `repo_bytes` | 5724066394 | bytes | 2026-10-14T05:45:20Z | repository tree walk (this script) | `939ea912177ea0dd…` | every file under the repository root, excluding .git internals |
| `safe_reclaimable_bytes` | 20771371 | bytes | 2026-10-14T05:45:20Z | git check-ignore + git ls-files + a walk for cache names | `8aab0cc422935881…` | tool caches only, each verified untracked and ignored |

*`run_id` for every figure in this file: `EDGE05R-STORE-20261014T054520Z`. Two figures with different `as_of_utc` are two readings of a moving system, never one total.*
