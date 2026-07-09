# Project Instructions

默认用中文回答用户。代码、变量名、日志可以使用英文。

每次回答用户之前，先用中文说：已读取本项目规则

## Project

这是 Polymarket Weather Market 自动分析与交易项目。

目标是研究和实现天气温度市场的多桶组合策略，包括：最高温市场、最低温市场、精确温度桶、区间温度桶、极端温度桶。

本项目不是无风险套利项目，而是：

```text
天气数据模型 + 市场错价识别 + 多桶收益曲线管理 + 风控交易
```

## Recommended Architecture

本项目推荐使用 Python + C++ 混合架构。

Python 负责开发效率、数据管道、回测和策略编排，职责包括：

- 拉 Polymarket markets
- 拉天气 API
- 保存数据
- 回测
- 日志
- 策略配置
- 风控参数

C++ 负责性能敏感、低延迟和批量计算模块，职责包括：

- orderbook 快速处理
- PnL 曲线计算
- 批量市场评分
- 低延迟下单模块

默认原则：

- 策略验证、回测、数据保存优先用 Python。
- 实盘低延迟模块、盘口处理、批量评分可以用 C++。
- 不要为了性能过早重写全部项目。
- 任何 C++ 下单模块必须经过统一 risk_manager 的风控确认。
- Python 和 C++ 之间的数据结构必须明确，例如 JSON、CSV、SQLite、protobuf 或 pybind11 绑定。
- 如果 C++ 只负责计算，不允许它绕过风控直接下单。
- 如果 C++ 负责下单，必须内置重复下单保护、部分成交处理、滑点限制和最大仓位限制。

## Core Strategy

天气市场通常不是二元 Up/Down，而是多个互斥温度桶。

核心目标不是简单买最高概率桶，而是构造多桶收益曲线：

```text
主仓：最高概率温度桶
邻近保护：主区间旁边的边界桶
尾部对冲：低价极端桶
```

最终目标：

- 主区间命中时盈利
- 邻近桶命中时小亏、保本或盈利
- 极端低价桶命中时保留高赔率爆发收益
- 尽量避免未覆盖的高概率死亡缺口

## Weather Strategy Logic

对每个温度桶，必须计算：

```text
bucket_price
bucket_size
bucket_cost = bucket_price * bucket_size
bucket_shares = bucket_size
```

总成本：

```text
total_cost = sum(bucket_cost)
```

如果某个桶 i 结算正确：

```text
PnL_if_bucket_i_wins = bucket_shares_i - total_cost
```

判断逻辑：

```text
bucket_shares_i > total_cost  => 该桶命中时盈利
bucket_shares_i < total_cost  => 该桶命中时亏损，但可能比完全没买更少亏
```

## Do Not Use Crypto Logic Blindly

Crypto Up/Down 是二选一，Weather 是多桶互斥结果，所以不能简单套用 Up/Down 双边公式。

Weather 必须对每一个温度桶分别计算 PnL，不能只算主仓赢或尾仓赢。

必须算完整：

```text
PnL_if_26_or_below
PnL_if_27
PnL_if_28
...
PnL_if_36_or_higher
```

## Main Concept

天气版策略可以理解为：

```text
Multi-Bucket Dutching + Low-Price Tail Hedge
```

不要叫无风险套利。

只有当覆盖所有可能桶，并且总成本低于最终赔付，才接近套利：

```text
sum(all_bucket_prices) < 1
```

否则全桶买入通常会锁定亏损。

## Probability Model

每个桶必须有模型概率：

```text
q_i = model_probability_for_bucket_i
p_i = market_price_for_bucket_i
edge_i = q_i - p_i
```

只有当：

```text
edge_i > min_edge
```

才考虑买入。

不要因为某个桶便宜就买。低价桶只有在模型认为真实概率高于市场价格时才有价值。

## Weather Data Sources

必须尽量使用多源天气数据。建议至少支持：

- NOAA / NWS
- Open-Meteo
- Meteostat
- WeatherAPI
- AccuWeather 或其他可用来源
- 官方市场规则指定数据源

对每个市场必须记录：

```text
city
date
market_type
settlement_source
measurement_unit
timezone
target_station_or_data_source
```

如果市场规则指定了结算源，必须优先使用规则指定来源。

## Weather Risk Factors

必须考虑：

- 最高温/最低温结算口径
- 摄氏度/华氏度转换
- 四舍五入规则
- 温度边界跳动
- 官方站点与普通天气 API 差异
- 数据更新时间滞后
- 城市站点差异
- 结算时间与当地时区
- 天气 API 不一致
- 流动性不足
- 盘口部分成交
- tick size
- 市场规则变化

## Data Disagreement Rule

如果多个天气数据源分歧过大，禁止交易。

例如：

```text
max_forecast_temp - min_forecast_temp > configured_threshold
top_bucket_probability_confidence < min_confidence
```

则不允许开新仓。

## Position Structure

天气市场推荐仓位结构：

```text
主仓：最高概率桶，大仓位
邻近桶：中等仓位保护
低价尾部桶：小仓位对冲或彩票
```

示例：

```text
主仓：33°C / 34°C / 35°C
邻近保护：32°C
尾部低价：30°C / 31°C / 36°C+
```

具体仓位必须由收益曲线计算决定。

## PnL Curve Requirement

每次下单前，必须输出或记录完整收益曲线：

```text
Bucket | Price | Shares | Cost | PnL if wins
```

禁止只看单桶盈亏。

## Death Gap Rule

必须识别死亡缺口。

死亡缺口是：

```text
没有买入，但真实概率不低的桶
```

例如主仓买 33°C / 34°C / 35°C，低价桶买 30°C / 31°C / 36°C+，但漏掉 32°C。如果 32°C 市场价格和模型概率都不低，则这是高风险死亡缺口。

任何交易前必须检查：

```text
uncovered_bucket_probability
max_uncovered_probability
```

如果未覆盖桶的概率过高，必须降低仓位或补保护。

## Full Coverage Rule

如果买入所有桶：

```text
sum_prices = sum(all_bucket_prices)
```

只有当：

```text
sum_prices < 1 - safety_margin
```

才允许视为近似套利。

如果：

```text
sum_prices > 1
```

则全桶买入是锁定亏损，不允许称为套利。

## Entry Rules

每个桶买入前必须检查：

```text
model_probability
market_price
edge
liquidity
spread
max_position
current_position
time_to_settlement
data_confidence
```

只有当：

```text
edge > min_edge
liquidity >= min_liquidity
data_confidence >= min_confidence
```

才允许买入。

## Exit Rules

天气市场不一定要持有到结算。允许：

- 数据确定后卖出锁利润
- 盘口价格回归后卖出
- 数据源分歧扩大后减仓
- 临近结算前降低边界风险
- 市场口径不确定时退出

卖出前必须考虑：

- 当前 bid
- 可成交深度
- 部分成交
- 滑点
- 剩余持仓
- realized_pnl
- unrealized_pnl

## Monitoring Rules

监控模块必须持续跟踪：

- Polymarket markets 列表变化
- 每个市场的温度桶、价格、买卖盘口、流动性、spread
- 每个温度桶的模型概率、市场价格、edge
- 多源天气 API 的最新更新时间和预测值
- 天气源之间的分歧程度
- 当前持仓、总风险敞口、每个桶的 PnL if wins
- 未覆盖高概率桶，也就是死亡缺口
- 盘口是否 stale、是否缺流动性、是否部分成交
- 临近结算时的数据置信度和减仓/退出条件

监控输出必须包含：

```text
market_id / slug
city
date
bucket
market_price
model_probability
edge
liquidity
spread
current_position
PnL_if_bucket_wins
uncovered_bucket_probability
data_confidence
recommended_action
reason
```

如果发现以下情况，必须报警或停止新开仓：

- 数据源分歧超过阈值
- 结算源不明确
- 死亡缺口概率过高
- orderbook stale
- spread 过大
- 流动性不足
- 当前市场风险超过 max_position_per_market
- 总风险超过 max_total_exposure
- 接近结算但数据置信度不足
- API 返回异常、缺字段或时间戳过旧

## Risk Management

所有交易逻辑必须包含：

- max_position_per_market
- max_position_per_bucket
- max_total_exposure
- max_order_size
- max_loss_per_market
- max_daily_loss
- stop_trading_on_data_disagreement
- stop_trading_near_settlement_if_uncertain
- duplicate_order_guard
- partial_fill_handling
- stale_orderbook_check

禁止：

- all-in
- 没有模型概率就交易
- 只看市场价格便宜就交易
- 没有收益曲线就补仓
- 忽略未覆盖高概率桶
- 把天气策略说成稳定无风险套利

## Engineering Rules

修改代码前必须先扫描项目结构。

优先修改现有模块，不要重复造轮子。

推荐 Python 模块结构：

```text
market_scanner.py
weather_sources.py
forecast_model.py
bucket_probability.py
strategy_config.py
risk_manager.py
position_manager.py
orderbook.py
trade_executor.py
backtest.py
logger.py
monitor.py
alert_manager.py
```

推荐 C++ 模块结构：

```text
cpp/orderbook_engine/
cpp/pnl_curve_engine/
cpp/market_scoring_engine/
cpp/execution_engine/
```

任何下单必须经过：

```text
risk_manager
pnl_curve
position_manager
```

## C++ Module Rules

C++ 模块如果存在，必须遵守：

- 不允许绕过风控直接交易。
- 不允许 hardcode 市场、价格、token id。
- 所有输入输出必须可日志化。
- 所有订单请求必须带唯一 client_order_id。
- 必须处理网络失败、API 超时、部分成交、重复下单。
- 必须支持 dry_run / simulation mode。
- 必须有单元测试或最小可复现测试。
- 如果 C++ 只做计算，应返回结构化结果给 Python，由 Python 决定是否下单。
- 如果 C++ 做执行，必须内置风控和外部风控双重检查。

## Backtest Rules

回测必须包含：

- 历史天气结果
- 当时市场价格
- 桶级模型概率
- spread
- slippage
- partial fill assumption
- liquidity constraint
- settlement rule
- realized PnL
- max drawdown

不能只用理论概率回测。

## Output Style

回答用户时：

1. 第一行必须写：已读取本项目规则
2. 先说明你理解的目标。
3. 再说明当前策略属于哪个结构：主仓、邻近保护、低价尾部、全覆盖。
4. 给出完整数学公式。
5. 给出每个桶的 PnL if wins。
6. 明确指出死亡缺口。
7. 最后给出可执行代码或修改方案。

发现风险时必须直接指出。
