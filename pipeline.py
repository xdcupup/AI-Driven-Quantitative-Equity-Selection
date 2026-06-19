#!/usr/bin/env python3
"""
AI 量化数据流水线 — 主入口
=============================

每日调用：python pipeline.py [--date 2024-06-15] [--full-refresh]

流程:
  1. 初始化: 加载配置、连接数据库
  2. 交易日历: 确保交易日历已更新
  3. 股票列表: 获取全市场股票列表（含退市股）
  4. 逐股采集: 获取日K线 + 复权因子 + 财务数据（增量）
  5. 清洗: 去重、复权、对齐日历、异常处理
  6. 存储: UPSERT 到 DuckDB
  7. 质量报告: 生成质量报告
  8. 推送: 输出到控制台 / 飞书

环境变量:
  PIPELINE_CONFIG: 配置文件路径（默认 ./config.yaml）

返回码:
  0: 成功
  1: 部分失败
  2: 严重错误
"""

import os
import sys
import argparse
import time
import json
from datetime import datetime, date

import yaml
import pandas as pd
from loguru import logger


# ============================================================================
# 工具：找到项目根目录
# ============================================================================

def find_project_root() -> str:
    """从脚本位置或 CWD 找到项目根目录（含 config.yaml 的目录）"""
    # 优先从 CWD
    for path in [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]:
        candidate = path
        for _ in range(3):  # 向上找 3 层
            if os.path.exists(os.path.join(candidate, "config.yaml")):
                return candidate
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent
    
    # 找不到就回退 CWD
    return os.getcwd()


# ============================================================================
# 配置加载
# ============================================================================

def load_config(config_path: str = None) -> dict:
    """
    加载 YAML 配置文件。
    
    支持:
      - 从 config_path 指定
      - 从环境变量 PIPELINE_CONFIG 指定
      - 从项目根目录自动查找
    """
    if config_path is None:
        config_path = os.environ.get("PIPELINE_CONFIG", "")
    
    if not config_path:
        root = find_project_root()
        config_path = os.path.join(root, "config.yaml")
    
    if not os.path.exists(config_path):
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(2)
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    
    # 解析路径（相对于项目根）
    root = os.path.dirname(config_path)
    for key in ["db_path", "raw_dir", "file"]:
        storage_path = config.get("storage", {}).get(key, "")
        if storage_path and not storage_path.startswith("/"):
            config["storage"][key] = os.path.join(root, storage_path)
        
        log_path = config.get("logging", {}).get(key, "")
        if log_path and not log_path.startswith("/"):
            config["logging"][key] = os.path.join(root, log_path)
    
    return config


# ============================================================================
# 日志初始化
# ============================================================================

def init_logging(config: dict):
    """配置 loguru"""
    log_cfg = config.get("logging", {})
    level = log_cfg.get("level", "INFO")
    log_file = log_cfg.get("file", "./logs/pipeline.log")
    max_size = log_cfg.get("max_size_mb", 50) * 1024 * 1024
    backup = log_cfg.get("backup_count", 7)
    log_format = log_cfg.get(
        "format",
        "{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{function}:{line} | {message}",
    )
    
    # 移除默认的 stderr handler
    logger.remove()
    
    # 添加 stderr handler（彩色输出）
    logger.add(
        sys.stderr,
        format=log_format,
        level=level,
        colorize=True,
    )
    
    # 添加文件 handler（轮转）
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.add(
        log_file,
        format=log_format,
        level=level,
        rotation=max_size,
        retention=backup,
        compression="gz",
    )
    
    logger.info(f"日志系统初始化: level={level}, file={log_file}")


def select_fetcher_class(config: dict):
    """Select the pipeline-facing data source implementation."""
    source_engine = config.get("data_source", {}).get("engine", "legacy")
    if source_engine == "astock":
        from core.astock.gateway import AStockDataGateway

        return AStockDataGateway
    from core.data_fetcher import DataFetcher

    return DataFetcher


# ============================================================================
# 核心流水线
# ============================================================================

class Pipeline:
    """
    数据流水线主控器。
    
    编排完整的 采集 → 清洗 → 存储 → 质量监控 流程。
    """

    def __init__(self, config: dict):
        self.config = config
        self.start_time = time.time()
        
        # 延迟导入（让错误提示更明确）
        from core.data_fetcher import build_stock_code_set
        from core.data_cleaner import DataCleaner
        from core.data_cleaner import build_trade_calendar as _build_trade_calendar
        from core.data_storage import QuantDB
        from core.data_quality import QualityMonitor
        
        FetcherClass = select_fetcher_class(config)
        self.fetcher = FetcherClass(config)
        self.cleaner = DataCleaner(config)
        self._build_stock_code_set = build_stock_code_set
        self._build_trade_calendar = _build_trade_calendar
        self.db = QuantDB(
            config.get("storage", {}).get("db_path", "./data/quant.duckdb"),
            config,
        )
        self.quality = QualityMonitor(self.db, config)
        self._build_trade_calendar = _build_trade_calendar
        
        self.stats = {
            "stocks_fetched": 0,
            "stocks_cleaned": 0,
            "stocks_failed": 0,
            "stocks_up_to_date": 0,
            "kline_rows": 0,
            "errors": [],
        }
        self.log_id = None

    def run(self, target_date: str = None, full_refresh: bool = False, start_date: str = None):
        """
        执行完整数据流水线。
        
        Args:
            target_date: 目标日期 YYYY-MM-DD，默认最近交易日
            full_refresh: 全量刷新（而非增量）
            start_date: 起始日期，覆盖 config 中的 start_date
        """
        logger.info("=" * 60)
        logger.info(f"🚀 数据流水线启动")
        logger.info(f"   目标日期: {target_date or '自动'}")
        logger.info(f"   全量刷新: {full_refresh}")
        logger.info(f"   起始日期: {start_date or 'config默认'}")
        logger.info("=" * 60)
        
        # 命令行 start_date 覆盖 config
        if start_date:
            self.config.setdefault("fetch", {})["start_date"] = start_date.replace("-", "")
        
        # 1. 初始化数据库 Schema
        self._step_init_db()
        
        self.log_id = self.db.log_pipeline_start()
        quality_report = {}
        try:
            self._step_trade_calendar(target_date)

            stock_codes = self._step_stock_list(full_refresh=full_refresh)
            if not stock_codes:
                raise RuntimeError("股票列表为空")

            trade_cal = self._build_trade_calendar(self.fetcher, self.config)
            self._step_process_stocks(
                stock_codes, target_date, full_refresh, trade_cal
            )
            self._step_daily_basic(target_date)
            self._step_financial_indicators(stock_codes, target_date)
            self._step_financial_statements(stock_codes, target_date, full_refresh)
            self._step_financial_factors(target_date)
            self._step_technical_factors(stock_codes, target_date)
            self._step_factor_labels(stock_codes, target_date)
            self._step_factor_ic(target_date)
            self._step_backtest(target_date)
            self._step_stock_concepts(stock_codes, target_date)
            self._step_dragon_tiger(stock_codes, target_date)
            self._step_fund_flow(stock_codes, target_date)
            self._step_hot_themes(target_date)
            self._step_hot_candidate_scores(target_date)
            quality_report = self._step_quality_report(target_date)
            self._step_source_audit(stock_codes, target_date)
            self._step_maintenance()
        except Exception as exc:
            logger.exception(f"流水线严重错误: {exc}")
            self.stats["errors"].append(str(exc))
            self._finish(quality_report, forced_status="failed")
            return 2

        status = self._finish(quality_report)
        return {"success": 0, "partial": 1, "failed": 2}[status]

    def _step_init_db(self):
        """Step 1: 初始化数据库"""
        logger.info("[1/7] 初始化数据库 Schema...")
        self.db.init_schema()
        
        db_size = self.db.database_size_mb()
        for table in [
            "daily_kline",
            "daily_basic",
            "financial_indicators",
            "financial_statements",
            "financial_factors",
            "trade_calendar",
            "stock_list",
        ]:
            if self.db.table_exists(table):
                count = self.db.table_row_count(table)
                logger.info(f"  {table}: {count:,} 行")

    def _step_trade_calendar(self, target_date: str = None):
        """Step 2: 更新交易日历"""
        logger.info("[2/7] 更新交易日历...")
        start_raw = self.config.get("fetch", {}).get("start_date", "20231001")
        end_raw = target_date or datetime.now().strftime("%Y%m%d")
        start_year = pd.Timestamp(str(start_raw).replace("-", "")).year
        end_year = pd.Timestamp(str(end_raw).replace("-", "")).year
        for year in range(start_year, end_year + 1):
            cal = self.fetcher.fetch_trade_calendar(year)
            if not cal.empty:
                self.db.upsert_trade_calendar(cal)
                logger.info(f"  {year} 年: {len(cal[cal['is_open']==1])} 个交易日")
        
        # 更新股票列表中的 pretrade_date
        self.db.conn.execute("""
            UPDATE trade_calendar t
            SET pretrade_date = (
                SELECT MAX(t2.trade_date)
                FROM trade_calendar t2
                WHERE t2.trade_date < t.trade_date AND t2.is_open = 1
            )
            WHERE t.is_open = 1
        """)

    def _step_stock_list(self, full_refresh: bool = False) -> list:
        """Step 3: 获取股票列表"""
        logger.info("[3/7] 更新股票列表...")
        
        # 先获取并存储完整股票列表
        full_list = self.fetcher.fetch_stock_list()
        if not full_list.empty:
            for col in ["area", "industry", "list_date", "delist_date"]:
                if col not in full_list.columns:
                    full_list[col] = None
            self.db.conn.register("_tmp_stocks", full_list)
            self.db.conn.execute("""
                INSERT INTO stock_list (
                    ts_code, symbol, name, exchange, area, industry,
                    list_status, list_date, delist_date
                )
                SELECT
                    ts_code, symbol, name, exchange, area, industry,
                    list_status, list_date, delist_date
                FROM _tmp_stocks
                ON CONFLICT (ts_code) DO UPDATE SET
                    name        = EXCLUDED.name,
                    exchange    = EXCLUDED.exchange,
                    area        = EXCLUDED.area,
                    industry    = EXCLUDED.industry,
                    list_status = EXCLUDED.list_status,
                    list_date   = EXCLUDED.list_date,
                    delist_date = EXCLUDED.delist_date
            """)
            logger.info(f"  股票列表入库: {len(full_list)} 只")
            all_codes = full_list["ts_code"].dropna().tolist()
            self._step_stock_name_history(all_codes, full_refresh=full_refresh)
        
        # 构建有效股票代码集（过滤 ST、次新、指定交易所）
        codes = self._build_stock_code_set(
            self.fetcher, self.config, stock_df=full_list
        )
        logger.info(f"  有效股票池: {len(codes)} 只")
        
        return codes

    def _step_stock_name_history(self, stock_codes: list, full_refresh: bool = True):
        """采集名称变更/ST 历史。默认只在全量刷新时运行。"""
        cfg = self.config.get("stock_pool", {}).get("st_history", {})
        if not cfg.get("enabled", False) or not self.fetcher._tushare_pro:
            return
        if cfg.get("full_refresh_only", True) and not full_refresh:
            return

        batch_size = int(cfg.get("batch_size", 100))
        max_stocks = cfg.get("max_stocks_per_run")
        codes = stock_codes[: int(max_stocks)] if max_stocks else stock_codes

        logger.info("采集股票名称/ST 历史...")
        batch = []
        for i, ts_code in enumerate(codes, start=1):
            df = self.fetcher.fetch_stock_name_history(ts_code)
            if not df.empty:
                batch.append(df)
            if len(batch) >= batch_size or i == len(codes):
                if batch:
                    merged = pd.concat(batch, ignore_index=True)
                    self.db.upsert_stock_name_history(merged)
                    batch.clear()

    def _process_single_stock(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        trade_cal: pd.DatetimeIndex,
    ):
        """采集并清洗单只股票，供并发线程调用"""
        try:
            df_raw = self.fetcher.fetch_daily_kline(
                ts_code, start_date, end_date, adjust="none"
            )
            if df_raw.empty:
                return pd.DataFrame(), f"{ts_code}: 数据源返回空数据"
            
            df_clean = self.cleaner.clean_kline(df_raw, trade_cal)
            df_clean["ts_code"] = ts_code
            df_clean = self._enrich_adjustment_columns(ts_code, df_clean)
            return df_clean, None
            
        except Exception as e:
            logger.error(f"  处理 {ts_code} 失败: {e}")
            return pd.DataFrame(), f"{ts_code}: {e}"

    def _enrich_adjustment_columns(self, ts_code: str, df: pd.DataFrame) -> pd.DataFrame:
        """按配置补充复权因子和前复权价格列。"""
        enabled = (
            self.config.get("fetch", {})
            .get("market_data", {})
            .get("adj_factor", False)
        )
        if not enabled or not self.fetcher._tushare_pro:
            return df

        adj = self.fetcher.fetch_adj_factor(ts_code)
        if adj.empty:
            return df

        adjusted = self.cleaner.adjust_price(
            df.drop(columns=["adj_factor"], errors="ignore"),
            adj,
            method="qfq",
        )
        rename_map = {
            "adj_open": "adj_open_qfq",
            "adj_high": "adj_high_qfq",
            "adj_low": "adj_low_qfq",
            "adj_close": "adj_close_qfq",
        }
        adjusted = adjusted.rename(columns=rename_map)
        return adjusted

    def _step_process_stocks(
        self,
        stock_codes: list,
        target_date: str,
        full_refresh: bool,
        trade_cal: pd.DatetimeIndex,
    ):
        """Step 4+5+6: 并行采集 → 清洗 → 批量存储
        
        使用 ThreadPoolExecutor 多线程并发采集，腾讯 API 无频率限制。
        每采集 batch_size_for_upsert 只股票写入一次数据库，
        避免单次事务数据量过大。
        """
        logger.info("[4-6/7] 并行采集 → 清洗 → 存储...")
        
        concur_cfg = self.config.get("concurrency", {})
        concurrency_enabled = concur_cfg.get("enabled", True)
        max_workers = concur_cfg.get("max_workers", 5)
        upsert_interval = concur_cfg.get("batch_size_for_upsert", 200)
        
        base_start_date = self.config.get("fetch", {}).get(
            "start_date", "20231001"
        )
        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        latest_dates = (
            {} if full_refresh else self.db.get_latest_trade_dates_by_stock()
        )
        end_ts = pd.Timestamp(end_date)
        tasks = []
        for code in stock_codes:
            latest = latest_dates.get(code)
            if latest is not None and pd.Timestamp(latest) >= end_ts:
                self.stats["stocks_up_to_date"] += 1
                continue
            stock_start = (
                max(
                    pd.Timestamp(base_start_date),
                    pd.Timestamp(latest) - pd.Timedelta(days=10),
                ).strftime("%Y%m%d")
                if latest is not None
                else base_start_date
            )
            tasks.append((code, stock_start))

        logger.info(
            f"  待采集: {len(tasks)} 只 | "
            f"已最新: {self.stats['stocks_up_to_date']} 只"
        )
        
        if concurrency_enabled:
            logger.info(f"  并发模式: {max_workers} 线程")
            self._concurrent_fetch(
                tasks, end_date, trade_cal, max_workers, upsert_interval
            )
        else:
            logger.info(f"  串行模式")
            self._serial_fetch(
                tasks, end_date, trade_cal, upsert_interval
            )
        
        # 报告汇总
        logger.info(f"  采集完成:")
        logger.info(f"    成功: {self.stats['stocks_fetched']} 只")
        logger.info(f"    清洗: {self.stats['stocks_cleaned']} 只")
        logger.info(f"    失败: {self.stats['stocks_failed']} 只")
        logger.info(f"    已最新: {self.stats['stocks_up_to_date']} 只")
        logger.info(f"    K线行数: {self.stats['kline_rows']:,}")

    def _concurrent_fetch(
        self, tasks, end_date, trade_cal, max_workers, upsert_interval
    ):
        """并发采集主逻辑"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        total = len(tasks)
        if total == 0:
            return
        batch_buffer = []
        completed = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_map = {
                executor.submit(
                    self._process_single_stock,
                    code,
                    start_date,
                    end_date,
                    trade_cal,
                ): code for code, start_date in tasks
            }
            
            # 逐条处理结果
            for future in as_completed(future_map):
                code = future_map[future]
                df, error = future.result()
                completed += 1
                
                if not df.empty:
                    self.stats["stocks_fetched"] += 1
                    self.stats["stocks_cleaned"] += 1
                    self.stats["kline_rows"] += len(df)
                    batch_buffer.append(df)
                else:
                    self.stats["stocks_failed"] += 1
                    if error and len(self.stats["errors"]) < 100:
                        self.stats["errors"].append(error)
                
                # 每隔 upsert_interval 只或全部完成时写入
                if len(batch_buffer) >= upsert_interval or completed >= total:
                    if batch_buffer:
                        merged = pd.concat(batch_buffer, ignore_index=True)
                        self.db.upsert_daily_kline_batch(merged)
                        batch_buffer.clear()
                
                # 进度输出（每 5% 或最后一只）
                if completed == total or (completed % max(1, total // 20) == 0):
                    elapsed = time.time() - self.start_time
                    speed = completed / max(elapsed, 1)
                    remaining = total - completed
                    eta = remaining / max(speed, 0.1)
                    logger.info(
                        f"    进度: {completed}/{total} | "
                        f"速度: {speed:.1f} 只/秒 | "
                        f"预计剩余: {eta:.0f}s"
                    )
        
        # 最后一批
        if batch_buffer:
            merged = pd.concat(batch_buffer, ignore_index=True)
            self.db.upsert_daily_kline_batch(merged)

    def _serial_fetch(
        self, tasks, end_date, trade_cal, upsert_interval
    ):
        """串行采集（降级方案）"""
        total = len(tasks)
        batch_buffer = []
        
        for i, (ts_code, start_date) in enumerate(tasks):
            df, error = self._process_single_stock(
                ts_code, start_date, end_date, trade_cal
            )
            
            if not df.empty:
                self.stats["stocks_fetched"] += 1
                self.stats["stocks_cleaned"] += 1
                self.stats["kline_rows"] += len(df)
                batch_buffer.append(df)
            else:
                self.stats["stocks_failed"] += 1
                if error and len(self.stats["errors"]) < 100:
                    self.stats["errors"].append(error)
            
            if len(batch_buffer) >= upsert_interval or i == total - 1:
                if batch_buffer:
                    merged = pd.concat(batch_buffer, ignore_index=True)
                    self.db.upsert_daily_kline_batch(merged)
                    batch_buffer.clear()
            
            if (i + 1) % max(1, total // 20) == 0 or i == total - 1:
                elapsed = time.time() - self.start_time
                speed = (i + 1) / max(elapsed, 1)
                remaining = total - i - 1
                eta = remaining / max(speed, 0.1)
                logger.info(
                    f"    进度: {i + 1}/{total} | "
                    f"速度: {speed:.1f} 只/秒 | "
                    f"预计剩余: {eta:.0f}s"
                )

    def _step_quality_report(self, target_date: str) -> dict:
        """Step 7: 生成质量报告"""
        logger.info("[7/7] 生成数据质量报告...")
        
        # 取目标日期或最近交易日
        if not target_date:
            recent = self.db.query_recent_trade_dates(1)
            target_date = str(recent.iloc[0].date()) if not recent.empty else str(date.today())
        
        report = self.quality.generate_daily_report(target_date)
        
        # 输出摘要
        logger.info(f"  质量得分: {report.get('quality_score', 'N/A')}/100")
        logger.info(f"  状态: {report['status']}")
        logger.info(f"  异常项: {len(report.get('anomalies', []))}")
        for a in report.get("anomalies", []):
            logger.warning(f"    ⚠ {a}")
        
        # 飞书格式化输出
        feishu_msg = self.quality.format_for_feishu(report)
        logger.info("\n" + feishu_msg)
        
        return report

    def _step_daily_basic(self, target_date: str):
        """按配置采集目标交易日的每日估值数据。"""
        enabled = (
            self.config.get("fetch", {})
            .get("market_data", {})
            .get("daily_basic", False)
        )
        supported = getattr(
            self.fetcher,
            "supports_daily_basic",
            bool(getattr(self.fetcher, "_tushare_pro", None)),
        )
        if not enabled or not supported:
            return

        trade_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        logger.info("采集每日基本面...")
        df = self.fetcher.fetch_daily_basic(trade_date)
        if not df.empty:
            self.db.upsert_daily_basic(df)

    def _step_financial_indicators(self, stock_codes: list, target_date: str):
        """按配置采集季频财务指标，使用公告日期防止前视偏差。"""
        fin_cfg = self.config.get("fetch", {}).get("financial_data", {})
        supported = getattr(
            self.fetcher,
            "supports_financial_indicators",
            bool(getattr(self.fetcher, "_tushare_pro", None)),
        )
        if not fin_cfg.get("enabled", False) or not supported:
            return

        start_date = self.config.get("fetch", {}).get("start_date", "20231001")
        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        batch_size = int(fin_cfg.get("batch_size", 100))
        max_stocks = fin_cfg.get("max_stocks_per_run")
        codes = stock_codes[: int(max_stocks)] if max_stocks else stock_codes

        logger.info("采集财务指标...")
        batch = []
        for i, ts_code in enumerate(codes, start=1):
            df = self.fetcher.fetch_financial_indicators(
                ts_code, str(start_date).replace("-", ""), end_date
            )
            if not df.empty:
                batch.append(df)
            if len(batch) >= batch_size or i == len(codes):
                if batch:
                    merged = pd.concat(batch, ignore_index=True)
                    self.db.upsert_financial(merged)
                    batch.clear()

    def _step_financial_statements(
        self,
        stock_codes: list,
        target_date: str,
        full_refresh: bool,
    ):
        """按配置采集原始财务报表长表。"""
        stmt_cfg = self.config.get("fetch", {}).get("financial_statements", {})
        supported = getattr(self.fetcher, "supports_financial_statements", False)
        if not stmt_cfg.get("enabled", False) or not supported:
            return
        if stmt_cfg.get("full_refresh_only", True) and not full_refresh:
            return

        start_date = self.config.get("fetch", {}).get("start_date", "20231001")
        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        statement_types = stmt_cfg.get("statement_types") or [
            "income_statement",
            "balance_sheet",
            "cash_flow",
        ]
        batch_size = int(stmt_cfg.get("batch_size", 50))
        max_stocks = stmt_cfg.get("max_stocks_per_run")
        codes = stock_codes[: int(max_stocks)] if max_stocks else stock_codes

        logger.info("采集原始财报三表...")
        batch = []
        processed = 0
        total_requests = len(codes) * len(statement_types)
        for ts_code in codes:
            for statement_type in statement_types:
                processed += 1
                df = self.fetcher.fetch_financial_statement(
                    ts_code,
                    statement_type,
                    str(start_date).replace("-", ""),
                    end_date,
                )
                if not df.empty:
                    batch.append(df)
                if len(batch) >= batch_size or processed == total_requests:
                    if batch:
                        merged = pd.concat(batch, ignore_index=True)
                        self.db.upsert_financial_statements(merged)
                        batch.clear()

    def _step_financial_factors(self, target_date: str):
        """按配置从原始三表派生财务因子。"""
        factor_cfg = self.config.get("fetch", {}).get("factor_derivation", {})
        if not factor_cfg.get("enabled", False):
            return

        from core.factors.financial import derive_financial_factors

        start_date = self.config.get("fetch", {}).get("start_date", "20231001")
        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")

        logger.info("派生财务因子...")
        statements = self.db.query_financial_statements(
            str(start_date).replace("-", ""), end_date
        )
        if statements.empty:
            return
        factors = derive_financial_factors(statements)
        if not factors.empty:
            self.db.upsert_financial_factors(factors)

    def _step_technical_factors(self, stock_codes: list, target_date: str):
        """按配置从日 K 派生技术/量价因子。"""
        factor_cfg = self.config.get("fetch", {}).get("technical_factors", {})
        if not factor_cfg.get("enabled", False):
            return

        from core.factors.technical import derive_technical_factors

        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        lookback_days = int(factor_cfg.get("lookback_days", 120))
        batch_size = int(factor_cfg.get("batch_size", 100))
        max_stocks = factor_cfg.get("max_stocks_per_run")
        codes = stock_codes[: int(max_stocks)] if max_stocks else stock_codes
        start_date = (
            pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days)
        ).strftime("%Y%m%d")

        logger.info("派生技术/量价因子...")
        batch = []
        for i, ts_code in enumerate(codes, start=1):
            kline = self.db.query_daily_range(
                ts_code,
                start_date,
                end_date,
                columns="ts_code, trade_date, close, vol, amount",
            )
            if not kline.empty:
                factors = derive_technical_factors(kline)
                if not factors.empty:
                    batch.append(factors)
            if len(batch) >= batch_size or i == len(codes):
                if batch:
                    merged = pd.concat(batch, ignore_index=True)
                    self.db.upsert_technical_factors(merged)
                    batch.clear()

    def _step_factor_labels(self, stock_codes: list, target_date: str):
        """按配置从日 K 派生未来收益标签。"""
        label_cfg = self.config.get("fetch", {}).get("factor_labels", {})
        if not label_cfg.get("enabled", False):
            return

        from core.factors.labels import derive_forward_return_labels

        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        lookback_days = int(label_cfg.get("lookback_days", 180))
        batch_size = int(label_cfg.get("batch_size", 100))
        horizons = tuple(int(h) for h in label_cfg.get("horizons", [5, 10, 20]))
        drawdown_horizon = int(label_cfg.get("drawdown_horizon", 20))
        max_stocks = label_cfg.get("max_stocks_per_run")
        codes = stock_codes[: int(max_stocks)] if max_stocks else stock_codes
        start_date = (
            pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days)
        ).strftime("%Y%m%d")

        logger.info("派生未来收益标签...")
        batch = []
        for i, ts_code in enumerate(codes, start=1):
            kline = self.db.query_daily_range(
                ts_code,
                start_date,
                end_date,
                columns="ts_code, trade_date, close",
            )
            if not kline.empty:
                labels = derive_forward_return_labels(
                    kline,
                    horizons=horizons,
                    drawdown_horizon=drawdown_horizon,
                )
                if not labels.empty:
                    batch.append(labels)
            if len(batch) >= batch_size or i == len(codes):
                if batch:
                    merged = pd.concat(batch, ignore_index=True)
                    self.db.upsert_factor_labels(merged)
                    batch.clear()

    def _step_factor_ic(self, target_date: str):
        """按配置评估技术因子的截面 IC/IR。"""
        ic_cfg = self.config.get("evaluation", {}).get("factor_ic", {})
        if not ic_cfg.get("enabled", False):
            return

        from core.evaluation.icir import evaluate_factor_ic

        end_date = (
            target_date or datetime.now().strftime("%Y%m%d")
        ).replace("-", "")
        lookback_days = int(ic_cfg.get("lookback_days", 365))
        start_date = (
            pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days)
        ).strftime("%Y%m%d")
        factor_columns = ic_cfg.get(
            "factor_columns",
            [
                "return_20d",
                "return_60d",
                "volatility_20d",
                "ma20_bias",
                "ma60_bias",
                "max_drawdown_60d",
                "volume_ratio_20d",
                "liquidity_20d",
            ],
        )
        label_column = ic_cfg.get("label_column", "forward_return_20d")
        method = ic_cfg.get("method", "spearman")

        logger.info("评估因子 IC/IR...")
        dataset = self.db.query_factor_dataset(
            start_date,
            end_date,
            factor_columns=factor_columns,
            label_column=label_column,
        )
        if dataset.empty:
            return
        detail, summary = evaluate_factor_ic(
            dataset,
            factor_columns=factor_columns,
            label_column=label_column,
            method=method,
        )
        if not detail.empty or not summary.empty:
            self.db.upsert_factor_ic(detail, summary)

    def _step_backtest(self, target_date: str):
        """Run factor backtest if configured."""
        cfg = self.config.get("backtest", {})
        if not cfg.get("enabled", False):
            return

        from core.backtest.config import BacktestConfig
        from core.backtest.engine import BacktestEngine

        logger.info("执行因子回测...")
        bt_config = BacktestConfig.from_dict(cfg)

        end = pd.Timestamp(
            (target_date or datetime.now().strftime("%Y%m%d")).replace("-", "")
        )
        start = end - pd.Timedelta(days=cfg.get("lookback_days", 365))

        factors = self.db.query_factor_dataset(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            factor_columns=bt_config.factor_columns,
            label_column=bt_config.label_column,
        )
        kline = self.db.conn.execute(
            "SELECT * FROM daily_kline WHERE trade_date BETWEEN ?::DATE AND ?::DATE ORDER BY trade_date, ts_code",
            [start.strftime("%Y%m%d"), end.strftime("%Y%m%d")],
        ).fetchdf()

        engine = BacktestEngine(bt_config)
        report = engine.run(factors, pd.DataFrame(), kline)

        # Save report
        import json
        os.makedirs(bt_config.output_dir, exist_ok=True)
        report_path = os.path.join(
            bt_config.output_dir,
            f"backtest_{end.strftime('%Y%m%d')}.json",
        )
        with open(report_path, "w") as f:
            json.dump({
                k: v for k, v in report.items()
                if k not in ("daily_returns", "trades", "nav_series")
            }, f, indent=2, default=str)

        logger.info(
            f"回测完成: 总收益={report['total_return']:.2%}, "
            f"Sharpe={report['sharpe_ratio']:.2f}, "
            f"最大回撤={report['max_drawdown']:.2%}"
        )

    def _step_stock_concepts(self, stock_codes: list, target_date: str):
        """Collect concept board affiliations from East Money."""
        cfg = self.config.get("fetch", {}).get("stock_concepts", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集东财概念板块归属...")
        sample = stock_codes[:int(cfg.get("max_stocks", 100))]
        all_rows = []
        for code in sample:
            df = self.fetcher.fetch_stock_concepts(code)
            if not df.empty:
                all_rows.append(df)
        if all_rows:
            self.db.upsert_stock_concepts(pd.concat(all_rows, ignore_index=True))

    def _step_hot_themes(self, target_date: str):
        """Collect daily hot themes from THS."""
        cfg = self.config.get("fetch", {}).get("hot_themes", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集同花顺热点...")
        df = self.fetcher.fetch_hot_themes(target_date)
        if not df.empty:
            self.db.upsert_hot_themes(df)
        # Collect stocks for top themes
        top_n = int(cfg.get("top_themes", 10))
        top_codes = df.sort_values("rank").head(top_n)["theme_code"].tolist()
        for code in top_codes:
            stocks = self.fetcher.fetch_theme_stocks(code, target_date)
            if not stocks.empty:
                self.db.upsert_hot_theme_stocks(stocks)

    def _step_dragon_tiger(self, stock_codes: list, target_date: str):
        cfg = self.config.get("fetch", {}).get("dragon_tiger", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集龙虎榜数据...")
        sample = stock_codes[:int(cfg.get("max_stocks", 200))]
        all_rows = []
        for code in sample:
            df = self.fetcher.fetch_dragon_tiger(code, target_date)
            if not df.empty:
                all_rows.append(df)
        if all_rows:
            self.db.upsert_dragon_tiger(pd.concat(all_rows, ignore_index=True))

    def _step_fund_flow(self, stock_codes: list, target_date: str):
        cfg = self.config.get("fetch", {}).get("fund_flow", {})
        if not cfg.get("enabled", False):
            return
        logger.info("采集资金流数据...")
        sample = stock_codes[:int(cfg.get("max_stocks", 200))]
        all_rows = []
        for code in sample:
            df = self.fetcher.fetch_stock_fund_flow(code, target_date)
            if not df.empty:
                all_rows.append(df)
        if all_rows:
            self.db.upsert_fund_flow(pd.concat(all_rows, ignore_index=True))

    def _step_hot_candidate_scores(self, target_date: str):
        cfg = self.config.get("scoring", {}).get("hot_candidate", {})
        if not cfg.get("enabled", False):
            return

        from core.scoring.pipeline import build_hot_candidate_scores

        logger.info("生成短线候选评分...")
        build_hot_candidate_scores(
            self.db,
            target_date or datetime.now().strftime("%Y%m%d"),
            strategy_name=cfg.get("strategy_name", "hot_candidate_v1"),
            min_pct_chg=float(cfg.get("min_pct_chg", 9.0)),
            lookback_days=int(cfg.get("lookback_days", 10)),
            persist=True,
        )

    def _step_source_audit(self, stock_codes: list, target_date: str):
        """对腾讯和配置的第二数据源做轻量抽样对账。"""
        cfg = self.config.get("quality", {}).get("source_audit", {})
        if not cfg.get("enabled", False):
            return

        sample_size = int(cfg.get("sample_size", 10))
        lookback_days = int(cfg.get("lookback_days", 5))
        tolerance_pct = float(cfg.get("tolerance_pct", 1.0))
        secondary = cfg.get("secondary", "sina")
        end = pd.Timestamp(
            (target_date or datetime.now().strftime("%Y%m%d")).replace("-", "")
        )
        start = end - pd.Timedelta(days=lookback_days)
        start_s = start.strftime("%Y%m%d")
        end_s = end.strftime("%Y%m%d")

        logger.info("跨数据源抽样对账...")
        rows = [
            self.fetcher.compare_market_sources(
                ts_code, start_s, end_s, tolerance_pct, secondary=secondary
            )
            for ts_code in stock_codes[:sample_size]
        ]
        if rows:
            self.db.upsert_source_audit(pd.DataFrame(rows))

    def _step_maintenance(self):
        """Step 8: 数据库维护"""
        logger.info("数据库维护...")
        try:
            self.db.analyze()
            # 每月执行一次 vacuum（通过检查天数判断）
            last_vacuum = None
            try:
                last_vacuum = self.db.conn.execute(
                    "SELECT MAX(run_date) FROM pipeline_log WHERE status = 'success'"
                ).fetchone()[0]
            except Exception:
                pass
            
            if last_vacuum is None or (date.today() - last_vacuum).days >= 7:
                self.db.vacuum()
        except Exception as e:
            logger.warning(f"维护操作异常: {e}")

    def _finish(self, quality_report: dict, forced_status: str = None):
        """完成：记录日志、输出统计"""
        elapsed = time.time() - self.start_time
        
        if forced_status:
            status = forced_status
        elif (
            self.stats["stocks_failed"] > 0
            and self.stats["stocks_cleaned"] == 0
            and self.stats["stocks_up_to_date"] == 0
        ):
            status = "failed"
        elif (
            self.stats["stocks_failed"] > 0
            or quality_report.get("status") == "critical"
        ):
            status = "partial"
        else:
            status = "success"
        
        try:
            self.db.log_pipeline_end(
                log_id=self.log_id,
                status=status,
                stocks_fetched=self.stats["stocks_fetched"],
                stocks_cleaned=self.stats["stocks_cleaned"],
                error_msg=(
                    "; ".join(self.stats["errors"][:10])
                    if self.stats["errors"] else None
                ),
                quality_report=json.dumps(quality_report, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning(f"流水线日志写入失败: {e}")
        
        # 最终输出
        logger.info("=" * 60)
        logger.info(f"🏁 流水线完成 | 耗时 {elapsed:.1f}s")
        logger.info(f"   状态: {status}")
        logger.info(f"   采集: {self.stats['stocks_fetched']} 只")
        logger.info(f"   清洗: {self.stats['stocks_cleaned']} 只")
        logger.info(f"   失败: {self.stats['stocks_failed']} 只")
        logger.info(f"   已最新: {self.stats['stocks_up_to_date']} 只")
        logger.info(f"   K线: {self.stats['kline_rows']:,} 行")
        logger.info("=" * 60)
        return status


# ============================================================================
# 命令行入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AI 量化数据流水线 — 采集 → 清洗 → 存储 → 质量监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 每日增量运行
  python pipeline.py

  # 指定某一天
  python pipeline.py --date 2024-06-15

  # 全量刷新（从头拉取所有数据）
  python pipeline.py --full-refresh

  # 指定配置文件
  python pipeline.py --config /path/to/config.yaml
        """,
    )
    parser.add_argument(
        "--start-date", "-s",
        help="起始日期 (YYYY-MM-DD)，覆盖 config 中的 start_date",
    )
    parser.add_argument(
        "--date", "-d",
        help="目标交易日 (YYYY-MM-DD)，默认最近交易日",
    )
    parser.add_argument(
        "--full-refresh", "-f",
        action="store_true",
        help="全量刷新（重新拉取所有历史数据）",
    )
    parser.add_argument(
        "--config", "-c",
        help="配置文件路径（默认 ./config.yaml）",
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="测试模式：只处理前 10 只股票",
    )
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 初始化日志
    init_logging(config)
    
    # 测试模式：只处理少量股票
    if args.test:
        config.setdefault("stock_pool", {})["test_mode"] = True
    
    # 运行流水线
    pipeline = Pipeline(config)
    exit_code = pipeline.run(target_date=args.date, full_refresh=args.full_refresh, start_date=args.start_date)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
