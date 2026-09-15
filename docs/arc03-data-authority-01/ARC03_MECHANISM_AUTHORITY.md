# ARC03_MECHANISM_AUTHORITY.md

> Reconstructed from the **frozen Alpha Research Universe (ARU)** authority, not invented
> here. ARC-03 existed in the research program *before* this worktree: this document binds
> the authoritative description, separates the four levels (PROJECT / PATTERN / HYPOTHESIS /
> IMPLEMENTATION), and freezes the implementation-level decisions that the ARU left open.
>
> **No economic quantity has been observed.** No returns, no PnL, no signal-return
> statistics, no threshold search. `ARC03_BACKTESTS = 0`, `ARC03_EXECUTIONS = 0`,
> `ARC03_PERFORMANCE_OBSERVED = false`.

---

## 1. Authority chain

| Authority | Artifact | What it fixes |
| --- | --- | --- |
| ARU candidate registry | `docs/alpha-research-universe-01/05_ALPHA_MECHANISM_CANDIDATES.json` | ARC-03 identity, data family, mechanism sentence, who pays, PIT class, collision class |
| ARU research queue | `docs/alpha-research-universe-01/09_NEXT_RESEARCH_QUEUE.json` | the required test shape and the kill rule |
| ARU collision matrix | `docs/alpha-research-universe-01/04_FAILED_MEMORY_COLLISION_MATRIX.json` | orthogonality risk per prior hypothesis |
| ARU final report | `docs/alpha-research-universe-01/FINAL_REPORT.md` | ARC-03 position in the queue |
| Failed research memory | `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` | mechanisms ARC-03 must **not** repackage |

### 1.1 Verbatim frozen ARC-03 record

```json
{
  "id": "ARC-03",
  "name": "Participation shock reversal",
  "data": "5m volume and returns",
  "mechanism": "liquidity-taker overshoot after abnormal participation",
  "who_pays": "urgent liquidity takers",
  "pit": "PIT_SAFE_EASY",
  "collision": "MEDIUM with H5",
  "class": "EXPERIMENT"
}
```

```json
{ "rank": 3, "id": "ARC-03", "test": "fixed abnormal-volume percentile, one reversal hold, 10bps",
  "kill": "net<=0 or collision with H5" }
```

```json
{ "ARC-03": { "H1": "LOW", "H3": "LOW", "H5": "MEDIUM", "H6": "LOW" } }
```

The ARU sentence *"ARC-03 participation-shock reversal"* is **not** a sufficient
specification on its own. The four levels below are the required reconstruction.

---

## 2. PROJECT level (what the program is testing)

An **experiment**, class `EXPERIMENT`, not a portfolio component. Its purpose is to test
whether a *transient* participation spike followed by a *failed* price extension produces
a tradable short-horizon reversal, i.e. whether the traders who supplied the liquidity at
the extreme were compensated or punished.

* **Who pays (frozen ARU claim):** *urgent liquidity takers* — market participants who pay
  the spread and cross the book to get filled at the moment of the spike.
* **PIT class (frozen ARU claim):** `PIT_SAFE_EASY` — the mechanism was admitted by the ARU
  precisely because every input is a completed-bar observation.
* **Kill rule (frozen ARU claim):** the hypothesis dies if net expectancy is non-positive
  **or** if it collides with H5. ARC-03 may not be rescued by retuning.
* **Permanent program rule:** *PROVE EDGE OR KILL THE IDEA.*

---

## 3. PATTERN level (what is observed in the market, mechanism-language only)

A **participation shock** is an abrupt, abnormal burst of trading activity relative to the
*same time-of-day* behaviour of that market.

The economically meaningful pattern is not the burst itself but its **failure**:

1. A burst of activity drives price to an extreme.
2. The burst is real participation — but the price cannot stay at the extreme.
3. The bar **closes back against the direction of the push**, giving back more than half of
   the excursion it just made.
4. The activity that pushed price up is therefore *absorbed*, not *followed*.

Interpretation: the aggressive side paid to move price and failed to hold it. The
counterparty (whoever absorbed the flow) is the natural beneficiary of the reversion.

This is why the pattern is a **reversal** pattern and not continuation: the informational
content is not in the volume direction, it is in the **rejection** of the extreme.

### 3.1 Directional semantics (pre-observed, mechanism-derived)

* rejected **upward** push (close back below the high by more than half the range) → the
  longs who pushed are offside → **SHORT**
* rejected **downward** push (close back above the low by more than half the range) → the
  shorts who pushed are offside → **LONG**

Nothing here was chosen by looking at returns.

---

## 4. HYPOTHESIS level (the falsifiable statement)

> **ARC03-HYP-1.** On Binance USD-M perpetual futures, when a completed 5m bar (a) records
> an abnormal participation extreme relative to the same time-of-day slot on each of the
> previous 30 calendar days, and (b) simultaneously records an abnormal range extreme
> against the same reference set, and (c) closes against its own push by strictly more than
> half of its range, then the following 60 minutes (12 bars) contain a reversal in the
> direction of the rejected push, large enough to exceed a 10 bps round-trip cost and to
> survive the frozen critical gates.

Explicit **non-goals** (what ARC-03 is *not*):

* Not a generic mean-reversion strategy: it requires an abnormal **participation** record,
  so the signal is conditioned on an activity event, not on price being merely stretched.
* Not a volatility strategy: the range condition is used only as the *excursion* that must
  be given back, not as a tradable state.
* Not H5: H5 is `WITH the aggressive flow` (continuation) on **1h** bars using taker-side
  order-flow imbalance. ARC-03 is `AGAINST` the failing push on **5m** bars and uses only
  `volume` (never `taker_buy_volume`). The two are opposite-signed on any shared window.
* Not H1 (regime state), H3 (relative value), H6 (open interest), ARC-01 (funding carry),
  ARC-02 (BTC→alt lead-lag). No OI, funding, cross-asset or regime input is read.

### 4.1 Why this can be a *transient* participation effect and not persistent information

The design answers the question *"why should this identify transient participation rather
than information-driven trend?"* at three points:

1. **Same-slot reference.** Comparing a 5m bar to the *same* 5m slot on the previous 30 days
   removes the dominant source of spurious "abnormal volume" in crypto — the intraday
   activity cycle — so a record is genuinely abnormal rather than merely seasonal.
2. **Extreme, not merely high.** The threshold is *strictly greater than every one of the 30
   same-slot references*. That is the 100th percentile of a 30-sample, seasonality-controlled
   reference set: an event, not a level.
3. **Rejection is required.** Persistent information moves price and *keeps* it. Requiring
   the bar to give back more than half its excursion is a direct, contemporaneous test that
   the flow was absorbed. If information were persistent, the rejection condition would
   filter those bars out.

---

## 5. IMPLEMENTATION level (frozen for the primary discovery)

All parameter-free by construction. Every constant below is frozen **before** any economic
observation and lives in `src/trading_bot/research/arc03/arc03_authority.py`.

| Element | Frozen value | Basis |
| --- | --- | --- |
| Data | official Binance USD-M 5m klines (`volume` + OHLC) | ARU: *"5m volume and returns"* |
| Decision timeframe | 5m bar, decided at the bar's **close** | ARU cadence + `PIT_SAFE_EASY` |
| Participation field | `volume` (base units) | ARU: *"5m volume"*; each asset evaluated independently |
| Participation shock | `volume(t) > max(volume(t − 1d·j))`, `j = 1..30` (same 5m slot, same calendar day offset) | "fixed abnormal-volume percentile" = the 100th percentile of a 30-sample same-slot reference set |
| Reference requirement | all 30 observations present; else fail closed | no synthesis, no partial admission |
| Excursion record | `range(t) = high − low > max(range(ref))` over the same 30 references | the price response must be *disproportionate*, not merely present |
| Exhaustion | `body > 0` and `(high − close) > range/2` → SHORT; `body < 0` and `(close − low) > range/2` → LONG | strict majority retracement of the excursion |
| Direction | contrarian to the rejected push | mechanism (§3.1); identical to H5's *opposite* by construction |
| Price context | `PRICE_CONTEXT = NONE` beyond OHLC used by the definition itself | no filter added to make the hypothesis look selective |
| Entry | first bar with `open_time > decision_time`, at that bar's **OPEN** | strictly causal, no same-bar entry |
| Exit | 1h of holding = the OPEN of the bar at `entry_open + 12 · 5m` | single primary horizon: the mechanism is short-horizon flow absorption |
| Stop / TP | `STOP = NONE`, `TAKE_PROFIT = NONE` | no optimisation surface |
| Cooldown | `COOLDOWN = NONE` | no parameter |
| Overlap | skip same-asset signals while a position is open; no queue, no pyramiding; assets independent | one position per asset |
| Costs | primary round trip `10 bps`; frozen scenarios `0/10/20/40 bps` | program standard (same as H5) |
| Funding | **applicable**: a 12-bar 5m hold = 1h < 8h settlement spacing, so *for the BTC/ETH 8h schedule* no settlement can fall inside the hold; SOL's 2h/4h 2022 regime **can** be crossed, so deterministic funding accounting is preregistered | declared ex ante, not assessed from outcomes |

### 5.1 Frozen NO_SIGNAL reason codes (deterministic precedence)

```
OUTSIDE_COMMON_WINDOW
REFERENCE_HISTORY_INCOMPLETE
NO_PARTICIPATION_SHOCK
NO_EXCURSION_RECORD
NO_EXHAUSTION
POSITION_ALREADY_OPEN
INSUFFICIENT_FORWARD_PRICE_DATA
```

First satisfied reason wins. There is no discretionary fallback path.

---

## 6. What was deliberately **not** decided at this level

Deferred to the preregistration artifacts (and frozen there), not to runtime:

* the critical gate set and their exact computational conventions;
* the four falsification controls and their pass-consequence;
* the robustness plan (parameter neighbourhoods) — **not executed** at discovery;
* the H5 collision contract (see `ARC03_SPEC_V1.json` → `orthogonality`), because the ARU
  kill rule names H5 collision while ARC-03's own discovery stage must remain
  performance-blind.

---

## 7. Provenance / defense against repackaging

ARC-03 must not revive a failed mechanism under a new name. The failed-memory review
(`docs/external-audit-01/FAILED_RESEARCH_MEMORY.md`) is re-checked here at the mechanism
level:

* **not** a price-shape pattern (no Fibonacci, no candle names, no breakout level);
* **not** a regime-state conditioner (no H1-style regime labels);
* **not** relative value or cross-sectional (single asset, no pairs);
* **not** carry/funding (no funding input at all in the signal);
* **not** time-of-day seasonality *as a strategy* — the time-of-day structure is used only
  to **remove** seasonality from the reference set, which is the opposite of trading it;
* **not** trailing-z of price (H3 territory) — nothing in the signal is a z-score of return.

**ARC-01 is recorded as immutable failed memory** in the preregistration artifacts and may
never be retested or retuned under its hypothesis id; it is not a source of ARC-03 design.
