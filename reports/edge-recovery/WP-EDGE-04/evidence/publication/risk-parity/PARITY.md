# EDGE-03 — research budget vs runtime Risk Engine

Verdict: **PARITY_PASS**

Cases: 544 — `AGREE_APPROVED` 79, `AGREE_REFUSED_SAME_RULE` 155, `RESEARCH_ONLY_REFUSAL` 9, `RULE_NOT_MODELLED_BY_RESEARCH` 72, `RULE_ORDER_DIFFERS` 194, `SIZING_ROUNDING_ONLY` 35.

| class | declared | shadow |
| --- | --- | --- |
| `AGREE_APPROVED` | 25 | 54 |
| `AGREE_REFUSED_SAME_RULE` | 155 | 0 |
| `RESEARCH_ONLY_REFUSAL` | 9 | 0 |
| `RULE_NOT_MODELLED_BY_RESEARCH` | 53 | 19 |
| `RULE_ORDER_DIFFERS` | 194 | 0 |
| `SIZING_ROUNDING_ONLY` | 7 | 28 |

## Divergences

| case | class | research | runtime | detail |
| --- | --- | --- | --- | --- |
| `boundary:drawdown:4.99` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_drawdown) | the runtime refuses under daily_drawdown, which the research budget does not model |
| `boundary:drawdown:5.0` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_drawdown) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_drawdown: both refuse, different rule named first |
| `boundary:drawdown:5.01` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_drawdown) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_drawdown: both refuse, different rule named first |
| `boundary:drawdown:6.0` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_drawdown) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_drawdown: both refuse, different rule named first |
| `boundary:cooldown:streak0:61.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak0:60.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak0:59.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak0:1.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak2:61.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak2:60.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak2:59.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:cooldown:streak2:1.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (risk_loss_cooldown) | APPROVED (None) | the research budget refuses (risk_loss_cooldown) where the runtime admits the entry |
| `boundary:daily_loss:1.0` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `boundary:daily_loss:1.01` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `boundary:daily_loss:1.5` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `boundary:weekly_loss:3.0` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (weekly_loss_limit) | the runtime refuses under weekly_loss_limit, which the research budget does not model |
| `boundary:weekly_loss:3.01` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (weekly_loss_limit) | the runtime refuses under weekly_loss_limit, which the research budget does not model |
| `boundary:weekly_loss:4.0` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (weekly_loss_limit) | the runtime refuses under weekly_loss_limit, which the research budget does not model |
| `boundary:daily_drawdown:2.0` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_drawdown) | the runtime refuses under daily_drawdown, which the research budget does not model |
| `boundary:daily_drawdown:2.01` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_drawdown) | the runtime refuses under daily_drawdown, which the research budget does not model |
| `boundary:daily_drawdown:3.0` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_drawdown) | the runtime refuses under daily_drawdown, which the research budget does not model |
| `boundary:notional_floor` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 26.041461 vs runtime 26.04 (gap 0.001461 USDT, inside the runtime's published cent rounding) |
| `boundary:exposure:2000.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:exposure:2499.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:exposure:2500.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:exposure:2600.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:asset_cap:900.0` | `RESEARCH_ONLY_REFUSAL` | REFUSED (position_already_open) | APPROVED (None) | the research budget refuses (position_already_open) where the runtime admits the entry |
| `boundary:asset_cap:999.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:asset_cap:1000.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:asset_cap:1100.0` | `RULE_ORDER_DIFFERS` | REFUSED (position_already_open) | REFUSED (position_sizing) | research fired position_already_open (maps to max_positions), runtime fired position_sizing: both refuse, different rule named first |
| `boundary:kill_switch` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0000` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (kill_switch) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0001` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0002` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0003` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (weekly_loss_limit) | research fired risk_exposure_cap (maps to position_sizing), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0005` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0006` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0010` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (kill_switch) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0012` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (kill_switch) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0013` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0016` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0019` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0021` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0023` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0024` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0028` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0029` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0030` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (daily_loss_limit) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0031` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0033` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0038` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0040` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0041` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (daily_drawdown) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0042` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0043` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (daily_loss_limit) | research fired risk_exposure_cap (maps to position_sizing), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0044` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0048` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (daily_loss_limit) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0049` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0051` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (weekly_loss_limit) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0052` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (weekly_loss_limit) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0053` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0055` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (daily_loss_limit) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0059` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0062` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0064` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (daily_drawdown) | research fired risk_exposure_cap (maps to position_sizing), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0065` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0068` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (kill_switch) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0069` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0071` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0072` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0073` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0075` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0076` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0080` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0081` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0083` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0086` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0087` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0088` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0089` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 498.206279 vs runtime 498.21 (gap 0.003721 USDT, inside the runtime's published cent rounding) |
| `sweep:0091` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0092` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0093` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0097` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0100` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0101` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0102` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0103` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0104` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0105` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0106` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0108` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0111` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0113` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0114` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (kill_switch) | research fired risk_exposure_cap (maps to position_sizing), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0115` | `RULE_ORDER_DIFFERS` | REFUSED (risk_loss_cooldown) | REFUSED (daily_drawdown) | research fired risk_loss_cooldown (maps to consecutive_loss_cooldown), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0117` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0118` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0122` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0123` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0124` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0125` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0128` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (daily_loss_limit) | research fired risk_exposure_cap (maps to position_sizing), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0129` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_drawdown) | the runtime refuses under daily_drawdown, which the research budget does not model |
| `sweep:0130` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 498.206279 vs runtime 498.21 (gap 0.003721 USDT, inside the runtime's published cent rounding) |
| `sweep:0131` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0132` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 41.661404 vs runtime 41.66 (gap 0.001404 USDT, inside the runtime's published cent rounding) |
| `sweep:0134` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0135` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0136` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0137` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0145` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0147` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0148` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0149` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0150` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 41.244790 vs runtime 41.24 (gap 0.004790 USDT, inside the runtime's published cent rounding) |
| `sweep:0151` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0152` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0153` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (weekly_loss_limit) | the runtime refuses under weekly_loss_limit, which the research budget does not model |
| `sweep:0154` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0155` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0156` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0157` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0159` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0161` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0162` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0163` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0165` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0166` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0167` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0169` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0171` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0172` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0173` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (weekly_loss_limit) | research fired risk_exposure_cap (maps to position_sizing), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0176` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (kill_switch) | research fired risk_exposure_cap (maps to position_sizing), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0177` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0178` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0179` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0180` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0181` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0184` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0185` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0186` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0187` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0190` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0192` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_drawdown) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0193` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0195` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 485.751122 vs runtime 485.75 (gap 0.001122 USDT, inside the runtime's published cent rounding) |
| `sweep:0196` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0198` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0199` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (weekly_loss_limit) | the runtime refuses under weekly_loss_limit, which the research budget does not model |
| `sweep:0200` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0201` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0202` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0209` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_loss_limit: both refuse, different rule named first |
| `sweep:0210` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0212` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0213` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_drawdown) | the runtime refuses under daily_drawdown, which the research budget does not model |
| `sweep:0215` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0216` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0218` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0222` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0223` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (daily_drawdown) | research fired risk_exposure_cap (maps to position_sizing), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0224` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0225` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0226` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0227` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0228` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0230` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0233` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0234` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0235` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0236` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0238` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0240` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0241` | `SIZING_ROUNDING_ONLY` | APPROVED (parity_approved) | APPROVED (None) | research 99.943185 vs runtime 99.94 (gap 0.003185 USDT, inside the runtime's published cent rounding) |
| `sweep:0242` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (kill_switch) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0243` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0245` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0246` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0249` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0251` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_drawdown) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0253` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0255` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0256` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0258` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (weekly_loss_limit) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0259` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0260` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (kill_switch) | research fired risk_max_open_positions (maps to max_positions), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0261` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0262` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0263` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (weekly_loss_limit) | research fired risk_exposure_cap (maps to position_sizing), runtime fired weekly_loss_limit: both refuse, different rule named first |
| `sweep:0265` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0268` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (kill_switch) | the runtime refuses under kill_switch, which the research budget does not model |
| `sweep:0269` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_open_positions) | REFUSED (daily_trade_limit) | research fired risk_max_open_positions (maps to max_positions), runtime fired daily_trade_limit: both refuse, different rule named first |
| `sweep:0270` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0271` | `RULE_ORDER_DIFFERS` | REFUSED (risk_max_trades_per_day) | REFUSED (kill_switch) | research fired risk_max_trades_per_day (maps to daily_trade_limit), runtime fired kill_switch: both refuse, different rule named first |
| `sweep:0274` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |
| `sweep:0276` | `RULE_ORDER_DIFFERS` | REFUSED (risk_exposure_cap) | REFUSED (daily_drawdown) | research fired risk_exposure_cap (maps to position_sizing), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0277` | `RULE_ORDER_DIFFERS` | REFUSED (risk_drawdown_halt) | REFUSED (daily_drawdown) | research fired risk_drawdown_halt (maps to max_drawdown), runtime fired daily_drawdown: both refuse, different rule named first |
| `sweep:0278` | `RULE_NOT_MODELLED_BY_RESEARCH` | APPROVED (parity_approved) | REFUSED (daily_loss_limit) | the runtime refuses under daily_loss_limit, which the research budget does not model |

## Captured decisions reproduced from their own state

101 of 101 captured decision(s) reproduced by the research budget fed the state it recorded.

> parity between two risk models says nothing about profit; no limit is changed by this comparison and nothing here promotes a strategy

```json
{
  "cost_model_version": "COST_MODEL_V3",
  "fee_bps": 20.0,
  "funding_bps": 0.0,
  "horizon_minutes": 1440.0,
  "impact_bps": 0.158114,
  "other_bps": 0.0,
  "round_trip_bps": 23.790569,
  "scenario_id": "BASE",
  "size_usd": 1000.0,
  "slippage_bps": 2.632456,
  "spread_bps": 1.0
}
```
