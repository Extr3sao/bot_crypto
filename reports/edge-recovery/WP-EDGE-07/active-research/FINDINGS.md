# WP-EDGE-07 Track C — what the ACTIVE investigation found

*Written after the two registered candidates were screened and after the ceiling was measured.
Nothing in this file was used to change a parameter: the candidates' parameters are the registered
ones, the independent window was **not** read by either candidate (the registration's C0 screen
stopped both before it), and the proposal in §4 is a proposal for a future registration, not a run.*

## 1. The two registered candidates did not survive the screen

| Book | DEV trades | Per day | Gross/trade | Net (DEV) | Avg duration | Exits |
| --- | --- | --- | --- | --- | --- | --- |
| `edge07_active_thrust` | 338 | 0.185 | **−5.39 bps** | −492.92 USDT | 174 min | 206 stop / 132 target |
| `edge07_active_fade` | 255 | 0.140 | **−15.76 bps** | −503.99 USDT | 462 min | 192 stop / 63 target |

Both were rejected by the registered screen `C0` — negative **gross** expectation, before a single
fee — and both are also an order of magnitude short of the mission's three trades a day. Neither
read the independent window, exactly as the registration required: a setup that loses before costs
cannot be repaired by costs, so measuring it on unread data would only have spent the window.

Two facts from the refusals are worth keeping, because they say *why* the frequency is low rather
than merely that it is:

- `edge07_active_fade` refused 49,328 setups on the stretch filter and recorded `risk_drawdown_halt`
  2,342 times: the dislocations it wants are common, the ones wide enough to pay for themselves are
  not, and the book spent much of DEV halted by the 5 % drawdown rule.
- `edge07_active_thrust` refused 1,908 setups on the reward/risk floor and 20 on the cost gate
  itself: at a one-hour clock the 1.5 ATR objective clears the cost gate only sometimes, and the
  ones that clear it do not win often enough to pay for the ones that stop out.

## 2. The ceiling, measured — and it is the interesting part

The report `COST_BARRIER_ACTIVE.md` measures the two sides on the actual bars: the round trip
(`COST_MODEL_V3`, **23.79 bps**) and what a *perfect* direction call would have captured at each
holding horizon, entering at the next bar's open and leaving `H` bars later.

**The fraction of the available move a book must capture merely to break even**, on the independent
window (2026-03-01 … 2026-10-14):

| Horizon | Trades/day (3 assets) | BTC | ETH | SOL |
| --- | --- | --- | --- | --- |
| H = 1 h | 72 | **86 %** | 67 % | 58 % |
| H = 2 h | 36 | 60 % | 47 % | 40 % |
| H = 4 h | 18 | 43 % | 33 % | 28 % |
| H = 8 h | 9 | 30 % | 23 % | 20 % |
| H = 24 h | 3 | 16 % | 12 % | 11 % |

The table is the mission's own frequency question answered numerically, and it reads in two
directions:

1. **High frequency is closed by arithmetic, not by a bad candidate.** At an hour's holding, a book
   has to capture 58–86 % of the *entire* open-to-open move just to pay the round trip — a capture
   fraction no real rule reached (both candidates captured ≈0 % of it and lost). Three trades a day
   per asset is not a strategy problem that a better entry solves; it is a cost problem.
2. **The mission's target itself is not closed.** Three trades a day *across the universe* is one
   trade a day per asset — the `H = 24` line — where the requirement drops to 11–16 % of the move,
   and where the frozen daily trend book's problem was never cost but sample size. That is the
   direction the evidence points.

The ceiling is a *necessary, never sufficient* condition: it is what an oracle earns. Its value here
is that it separates "nobody has found the setup yet" from "the setup cannot exist at this
frequency", and at an hourly clock it is the second one.

## 3. Where the loss comes from

The candidates' own exit mixes (`ACTIVE_RESEARCH.md` §3, `ACTIVE_TRADES.csv`) say the same thing the
intraday book said in WP-EDGE-06: stops dominate targets. `thrust` paid 206 stops for 132 targets;
`fade` paid 192 for 63. Neither book was carried by a runner, and neither had a positive gross to
protect. The registered cost margin (1.25×) refused only 22 setups between the two books, so the
instrument's own guard was not what kept the frequency low — the setups was.

## 4. The proposal for a new registration (not run, not measured here)

> **P-ACTIVE-DAILY** — a three-asset daily-hold book that aims at three trades a day *across* the
> universe (≈1 entry per asset per day), on a clock where the barrier is 11–16 % instead of 58–86 %.
> It would be its own pre-registration with its own parameters, windows and criteria, and it would
> have to answer the question the frozen daily trend book did not: not "is the edge real" but "is
> there enough of it to pay 23.79 bps and still clear the gate".

Recorded here as a proposal only. The rule the earlier work packages wrote down — a parameter or a
structure that would have helped becomes a *new registration*, never an edit — is why it is in this
file and not in the code.

## 5. What Track C did and did not establish

- **Established**: two structurally different ACTIVE books lose before costs and do not reach the
  frequency target; the capture fraction required at an hourly clock is 58–86 %, measured; the
  frequency target is affordable at a daily clock, measured; nothing here promotes anything
  (`promotion: NONE`, `order_sent: false`).
- **Not established**: that no ACTIVE book can work. Two candidates is two candidates, and both were
  registered at an hourly clock where §2 shows the odds. The ceiling table is the durable part.
- **Never done**: no filter, parameter, stop or target was changed after seeing a result; the
  independent window was read by neither candidate; no risk limit was touched.
