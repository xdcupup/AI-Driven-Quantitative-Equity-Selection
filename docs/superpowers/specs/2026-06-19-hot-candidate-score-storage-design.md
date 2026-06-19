# 短线候选评分入库与回测读取设计

## 背景

当前项目已经具备短线候选评分器和 CSV 回测入口：

- `core/scoring/hot_candidate.py` 负责按 100 分规则生成各维度分数。
- `core/backtest/hot_candidate.py` 可以把评分结果转换成回测因子。
- `scripts/run_hot_candidate_backtest.py` 支持从 CSV 读取评分结果并回测。

缺口是评分结果没有持久化。每日评分、回测、复盘和后续 AI 迭代无法稳定追溯同一批信号。

## 目标

本轮实现“评分结果入库 + 回测从库读取”的闭环桥接：

1. 新增 DuckDB 表保存短线候选评分结果。
2. 增加 `QuantDB` 的写入和查询方法。
3. 扩展热榜候选回测脚本，支持从数据库读取评分结果。
4. 保留现有 CSV 回测模式，避免破坏已有用法。

## 非目标

本轮不实现自动候选生成器，不改变现有评分规则，不新增 AI 训练或自动调参逻辑。

## 数据表设计

新增表：`hot_candidate_scores`

主键：`trade_date, ts_code, strategy_name`

核心字段：

- `trade_date`：信号日期。
- `ts_code`：股票代码。
- `strategy_name`：评分策略版本，默认 `hot_candidate_v1`。
- 八个维度分数：`buyability_score`、`capital_persistence_score`、`seal_quality_score`、`support_quality_score`、`safety_filter_score`、`liquidity_structure_score`、`sector_resonance_score`、`leader_status_score`。
- `theme_validation_score`：题材验证分，暂不计入总分。
- `total_score`：排序总分。
- `score_level`：S/A/B/C/D/REJECT。
- `is_rejected`：是否被安全过滤拒绝。
- `score_reason`：缺失字段、拒绝原因等文本说明。
- `source`：数据来源或生成入口。
- `updated_at`：写入时间。

这个 schema 优先保证复盘可读性。后续如果要保存原始候选特征，可以新增 `hot_candidate_features` 或把特征快照写入单独表。

## 接口设计

在 `QuantDB` 增加：

- `upsert_hot_candidate_scores(df, strategy_name="hot_candidate_v1") -> int`
- `query_hot_candidate_scores(start_date, end_date, strategy_name="hot_candidate_v1", min_score=None, include_rejected=False) -> DataFrame`

写入方法会补齐 `strategy_name`、`source`、`updated_at`，并把日期和布尔字段规范化。

查询方法默认排除被拒绝候选，按 `trade_date ASC, total_score DESC, ts_code ASC` 排序，直接可交给回测适配器使用。

## 回测脚本设计

`scripts/run_hot_candidate_backtest.py` 保留 `--scores-csv`，新增数据库模式：

```bash
python scripts/run_hot_candidate_backtest.py \
  --from-db \
  --strategy-name hot_candidate_v1 \
  --start 2026-06-01 \
  --end 2026-06-19 \
  --min-score 60 \
  --top-n 10 \
  --max-positions 10
```

输入规则：

- `--scores-csv PATH`：从 CSV 回测。
- `--from-db`：从 `hot_candidate_scores` 查询评分结果。
- 两者不能同时使用。
- 两者必须至少提供一种。

## 错误处理

- 评分表为空时返回空 DataFrame，脚本输出 0 交易天数和 0 收益，不抛异常。
- CSV 缺字段时沿用现有适配器的保守空结果行为。
- 数据库查询日期支持 `YYYY-MM-DD` 和 `YYYYMMDD`。
- 未知 `strategy_name` 查询不到数据时按空结果处理。

## 测试计划

1. `tests/test_data_storage.py`
   - 写入一批评分结果后可按日期和策略名查回。
   - 默认过滤 `is_rejected=True`。
   - `min_score` 能过滤低分候选。

2. `tests/test_hot_candidate_backtest.py`
   - 数据库查询结果可以直接进入 `run_hot_candidate_backtest`。
   - CSV 读取模式继续通过。

3. 脚本级检查
   - `python -m py_compile scripts/run_hot_candidate_backtest.py`
   - 全量 `unittest discover`。

## 后续演进

下一轮可以在这个基础上新增“候选生成 -> enrich -> score -> upsert”的流水线命令，让每日运行直接产生可回测、可复盘的评分快照。
