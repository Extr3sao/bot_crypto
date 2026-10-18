# SOURCE_RUNTIME_CORRELATION — T-TA-CRITIC

**Source:** `TauricResearch/TradingAgents` @ `e8f5503e9b86d5c2710b0c76b1f686703968c9df` (Apache-2.0)
**Acquired:** 2026-10-18 as a detached checkout (9.5 MB, `--filter=blob:none`), never a runtime dependency.

This document links four *separate* claims. Each link is a hash or a native identifier, not a
narrative. The links are deliberately not merged into one "verification" statement.

## 1. Claim A — the source is pinned

`SOURCE_MANIFEST.json` records the commit, the licence SHA-256, and the SHA-256 + git blob id of
every exercised file. The harness re-checks the commit and licence before importing anything and
fails closed if they differ (`UPSTREAM_HARNESS_META.json`, 21/21 checks).

| Object | Hash / id |
| --- | --- |
| Commit | `e8f5503e9b86d5c2710b0c76b1f686703968c9df` |
| `tradingagents/agents/researchers/bull_researcher.py` | `e1bd66b62510fab9fcdc76f9ffca6ed6b3f417d0d08ddfe5e68e17abb8208f73` |
| `tradingagents/agents/researchers/bear_researcher.py` | `82d808a519b60d6324c1eb2f3f72278398a9b20bc2ac63805a0a8a68866c98e1` |
| `tradingagents/agents/managers/research_manager.py` | `7663292ed1db015dfcec57cddfd3f43011b4421824096a16ac64c266e379c380` |
| `tradingagents/graph/conditional_logic.py` | `64d79bc5fd04134774089bd80f6e2a9f99b8433b53786b89ff4458a6fdbce380` |
| `tradingagents/reporting.py` | `76b89887dffd1df37a1a9925842aef7362c7bf1c2738a766702e3802bb6fa902` |
| `tradingagents/report_html.py` | `6d7db41aa9d3064c22fdcf260b9fd570b95161582c2a3ed5ba6392bba3246087` |

## 2. Claim B — the original Python nodes ran, offline, with a stub model

`UPSTREAM_PYTHON_TRACE.jsonl` (9 rows, `source_stage=UPSTREAM_PYTHON_INSTRUMENTED_NOT_REA`)
records the state chain. `network_calls=0` on every row is measured by a socket guard installed
before the imports; `orders=0` is structural (the harness has no order path); `MODEL_STATUS=STUB`
because every `llm.invoke` is a local fixture.

| # | Agent | Input state | Output state | Router |
| --- | --- | --- | --- | --- |
| 1 | Bull Researcher (opening) | `c49cf5d1b1dd…` | `010cbaceedad…` | — |
| 2 | ConditionalLogic | `010cbaceedad…` | — | `Bear Researcher` |
| 3 | Bear Researcher (rebuttal) | `010cbaceedad…` | `4bdca81ccb02…` | — |
| 4 | ConditionalLogic | `4bdca81ccb02…` | — | `Research Manager` |
| 5 | ConditionalLogic (over-budget recheck) | `4bdca81ccb02…` | — | `Research Manager` |
| 6 | Research Manager (structured) | `4bdca81ccb02…` | `dd4b6211618e…` | — |
| 7 | ResearchPlan schema rejection | — | — | — |
| 8 | Research Manager free-text fallback | `4bdca81ccb02…` | — | — |
| 9 | Research Manager without structured support | — | — | — |

Verified chain links: bull output = bear input = manager input (`010cbaceedad…` → `4bdca81ccb02…`),
the first speaker receives an explicit "has not spoken yet" marker, and the bear receives the
real bull argument. Upstream focal tests: **64 passed** (`UPSTREAM_TESTS.json`), exit 0 each.

**Permitted claim:** the upstream debate code followed this sequence with a stub provider.
**Forbidden claim:** a model reasoned, or REA observed this sequence.

## 3. Claim C — the HTML came from that state through the original renderer

`write_report_tree(final_state, "BTC/USDT", …, html=True)` from the pinned `reporting.py`
produced `upstream/report_tree/complete_report.html`.

| Link | Value |
| --- | --- |
| `final_state` canonical SHA-256 | `dd4b6211618e35ebef6908fb5e1fe00b9ed02ff563f0763b00d9fcadbe3297fd` |
| `complete_report.html` SHA-256 | `7949425ac495b75dc796a2c1e79812c5bd6a921f2467bf4d2a921ec25da92f9c` |
| Bytes | 29 375 |
| JavaScript | none (`<script` absent) |
| Remote assets | none (`img`/`link`/`iframe`/`embed` absent) |

The analyst reports are declared fixture inputs; the research-debate sections are the harness's
own output. The page is not a mock-up: the bytes were written by the pinned renderer.

## 4. Claim D — REA observed that page in a real browser

`REA_TARGET_EVIDENCE.json`, status `REA_UI_OBSERVED`, served read-only at
`http://127.0.0.1:9184/complete_report.html` and opened in a disposable headless Chrome profile
with CDP on loopback.

| Operation | Native evidence id | Result |
| --- | --- | --- |
| `list_browser_targets` | `ev_e2b98a29dc18bdbd25a09f99efc10fd01e8d4d64d043e8ed93f0a4b7bcabb058` | 1 page target at the allowed origin |
| `inspect_web_page` | `ev_3548a228b86c7d375c0c317ebbd24ee0cea8330aab57582ed4e1f4bcd6051197` | 362 DOM nodes, 0 scripts, headings present |
| `capture_web_screenshot` | `ev_64fa51447fe7b98d693aa0c7d32bcada61e85af72d3133f3453b3f6ac3256166` | 1262×1904 PNG, `a155d92efa7e5e4db195b6ec7ef29da4cd3b681b533e1e7c52ee1864051b1e21` |

- Browser target: `FC69F1F46EE8D0F152F070970D0DC3A5` (Chrome/155.0.8059.40).
- `inspect_web_page` accessibility tree contains the headings **Bull Researcher**, **Bear
  Researcher** and **Research Manager**, and `scripts.total = 0`.
- The screenshot's decoded base64 equals the saved PNG byte for byte.
- `doctor` exited 1 because Ghidra/Hopper are absent; that is recorded in the dossier and does
  not affect a web observation. It is not reported as a pass.

**Permitted claim:** a real REA process observed the rendered page, listed its target, captured
its DOM/accessibility structure, and produced a screenshot with native evidence.
**Forbidden claim:** REA verified the debate, the reasoning, or the profitability.

## 5. What remains unproven

| Question | Status | Why |
| --- | --- | --- |
| Did a real model produce these arguments? | **No** — `MODEL_STATUS=STUB` | no API key or spend authorisation in scope |
| Does BOT-CRI-01 improve net PnL? | **UNMEASURED** | scripted critic, historical synthetic data, no prospective sample |
| Can the critic block an exit? | **No**, by contract and test | `ACC-CRI-15`, 4 protective probes |
| May GATED_PAPER run? | **No** | AI-BOTS-003C validation absent on this branch |
| Is the verifier institutionally independent? | **Structurally yes, institutionally limited** | same agent wrote builder and verifier; the verifier imports no builder module and recomputes every value |

`NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`: the REA evidence here covers the page
surface only. The critic pattern is certified as *implemented against a pinned source*, not as
externally validated by REA.
