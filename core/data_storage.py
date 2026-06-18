"""
AI 量化数据流水线 — DuckDB 存储模块
====================================

职责:
  1. 数据库初始化与 Schema 管理
  2. 批量写入（insert / upsert）
  3. 高效截面查询（按日期取全市场因子）
  4. 维护操作（vacuum, analyze, 分区管理）
  5. 数据版本控制

DuckDB 优势:
  列式存储，压缩比高
  单机全量数据查询比 HDF5 快 10x+
  支持 SQL 直接分析
  无需服务进程，嵌入使用

使用方式:
  from core.data_storage import QuantDB
  db = QuantDB("./data/quant.duckdb")
  db.init_schema()
  db.upsert_daily_kline(df)
  df = db.query_daily_range("000001.SZ", "2024-01-01", "2024-06-15")
"""

import os
from typing import Optional, List, Dict, Any
from datetime import datetime, date

import pandas as pd
import duckdb
from loguru import logger


# ============================================================================
# Schema 定义
# ============================================================================

SCHEMA_SQL = """
-- ====================================================================
-- 股票列表
-- ====================================================================
CREATE SEQUENCE IF NOT EXISTS seq_stock_id START 1;

CREATE TABLE IF NOT EXISTS stock_list (
    ts_code     VARCHAR PRIMARY KEY,    -- Tushare 风格代码: 000001.SZ
    symbol      VARCHAR NOT NULL,       -- 纯数字代码: 000001
    name        VARCHAR,                -- 股票名称
    exchange    VARCHAR,                -- 交易所: SSE/SZSE/BSE
    area        VARCHAR,                -- 地域
    industry    VARCHAR,                -- 行业
    list_date   DATE,                   -- 上市日期
    delist_date DATE,                   -- 退市日期
    list_status VARCHAR DEFAULT 'L',    -- L=上市, D=退市, P=暂停
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ====================================================================
-- 日K线行情表
-- ====================================================================
CREATE TABLE IF NOT EXISTS daily_kline (
    ts_code     VARCHAR NOT NULL,       -- 股票代码
    trade_date  DATE NOT NULL,          -- 交易日期
    open        DOUBLE,                 -- 开盘价（未复权）
    high        DOUBLE,                 -- 最高价（未复权）
    low         DOUBLE,                 -- 最低价（未复权）
    close       DOUBLE,                 -- 收盘价（未复权）
    vol         DOUBLE,                 -- 成交量（股）
    amount      DOUBLE,                 -- 成交额（元）
    pct_chg     DOUBLE,                 -- 涨跌幅（%）
    adj_factor  DOUBLE,                 -- 复权因子
    
    -- 前复权价格（回测用）
    adj_open_qfq   DOUBLE,
    adj_high_qfq   DOUBLE,
    adj_low_qfq    DOUBLE,
    adj_close_qfq  DOUBLE,
    
    -- 不复权价格（实盘信号用）
    raw_open    DOUBLE,
    raw_high    DOUBLE,
    raw_low     DOUBLE,
    raw_close   DOUBLE,
    
    -- 标记位
    flag_extreme    BOOLEAN DEFAULT FALSE,    -- 极端值标记
    flag_suspended  BOOLEAN DEFAULT FALSE,    -- 停牌标记
    flag_aligned    BOOLEAN DEFAULT FALSE,    -- 日历对齐标记
    flag_invalid_ohlc BOOLEAN DEFAULT FALSE,  -- OHLC 关系非法
    
    PRIMARY KEY (ts_code, trade_date)
);

-- 分区索引：按日期查询加速
CREATE INDEX IF NOT EXISTS idx_kline_date ON daily_kline (trade_date);
CREATE INDEX IF NOT EXISTS idx_kline_code ON daily_kline (ts_code);

-- ====================================================================
-- 每日基本面表
-- ====================================================================
CREATE TABLE IF NOT EXISTS daily_basic (
    ts_code       VARCHAR NOT NULL,
    trade_date    DATE NOT NULL,
    pe            DOUBLE,              -- 市盈率（动态）
    pe_ttm        DOUBLE,              -- 市盈率（TTM）
    pb            DOUBLE,              -- 市净率
    turnover_rate DOUBLE,              -- 换手率（%）
    volume_ratio  DOUBLE,              -- 量比
    circ_mv       DOUBLE,              -- 流通市值（元）
    total_mv      DOUBLE,              -- 总市值（元）
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_basic_date ON daily_basic (trade_date);

-- ====================================================================
-- 财务指标表（季频，关键：用 ann_date 防前视偏差）
-- ====================================================================
CREATE TABLE IF NOT EXISTS financial_indicators (
    ts_code       VARCHAR NOT NULL,
    ann_date      DATE NOT NULL,       -- 公告日期（用这个对齐！）
    end_date      DATE NOT NULL,       -- 报告期
    eps           DOUBLE,              -- 基本每股收益
    bps           DOUBLE,              -- 每股净资产
    roe           DOUBLE,              -- 净资产收益率
    roe_waa       DOUBLE,              -- 加权净资产收益率
    profit_yoy    DOUBLE,              -- 净利润同比增长率
    revenue_yoy   DOUBLE,              -- 营业收入同比增长率
    free_cashflow DOUBLE,              -- 自由现金流
    gross_margin  DOUBLE,              -- 毛利率
    net_margin    DOUBLE,              -- 净利率
    dt_debt_ratio DOUBLE,              -- 资产负债率
    PRIMARY KEY (ts_code, ann_date)
);

CREATE INDEX IF NOT EXISTS idx_fin_ann_date ON financial_indicators (ann_date);

-- ====================================================================
-- 原始财务报表长表（季频/年频，新浪三表）
-- ====================================================================
CREATE TABLE IF NOT EXISTS financial_statements (
    ts_code       VARCHAR NOT NULL,
    report_type   VARCHAR NOT NULL,     -- balance_sheet / income_statement / cash_flow
    end_date      DATE NOT NULL,        -- 报告期
    ann_date      DATE,                 -- 公告日期；新浪源暂缺时为空
    item_order    INTEGER NOT NULL,     -- 原始行序号，避免重复科目名覆盖
    item          VARCHAR NOT NULL,      -- 报表科目
    value         DOUBLE,               -- 可解析为数字的值
    value_text    VARCHAR,              -- 原始字符串值，保留文本科目
    item_yoy      DOUBLE,               -- 科目同比；新浪有值时写入
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, report_type, end_date, item_order)
);

CREATE INDEX IF NOT EXISTS idx_stmt_code_date
ON financial_statements (ts_code, report_type, end_date);

-- ====================================================================
-- 股票名称与 ST 历史（用于历史过滤，降低幸存者/状态偏差）
-- ====================================================================
CREATE TABLE IF NOT EXISTS stock_name_history (
    ts_code       VARCHAR NOT NULL,
    name          VARCHAR NOT NULL,
    start_date    DATE NOT NULL,
    end_date      DATE,
    change_reason VARCHAR,
    is_st         BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (ts_code, start_date, name)
);

CREATE INDEX IF NOT EXISTS idx_name_hist_code_date
ON stock_name_history (ts_code, start_date, end_date);

-- ====================================================================
-- 跨数据源抽样对账
-- ====================================================================
CREATE TABLE IF NOT EXISTS data_source_audit (
    audit_date         DATE NOT NULL,
    ts_code            VARCHAR NOT NULL,
    start_date         DATE NOT NULL,
    end_date           DATE NOT NULL,
    primary_source     VARCHAR NOT NULL,
    secondary_source   VARCHAR NOT NULL,
    compared_rows      INTEGER DEFAULT 0,
    max_close_diff_pct DOUBLE,
    status             VARCHAR,
    error_msg          VARCHAR,
    PRIMARY KEY (audit_date, ts_code, primary_source, secondary_source)
);

-- ====================================================================
-- 交易日历表
-- ====================================================================
CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date    DATE PRIMARY KEY,
    is_open       INTEGER NOT NULL,     -- 1=交易日, 0=休市
    pretrade_date DATE,                 -- 前一交易日
    day_of_week   INTEGER,              -- 周几
    week_of_year  INTEGER,              -- 年中的第几周
    month         INTEGER,              -- 月份
    year          INTEGER               -- 年份
);

CREATE INDEX IF NOT EXISTS idx_cal_year ON trade_calendar (year, month);

-- ====================================================================
-- 研究用日度股票池视图
-- ====================================================================
CREATE OR REPLACE VIEW research_daily_universe AS
WITH st_flag AS (
    SELECT
        k.ts_code,
        k.trade_date,
        BOOL_OR(COALESCE(h.is_st, FALSE)) AS is_st_on_date
    FROM daily_kline k
    LEFT JOIN stock_name_history h
      ON k.ts_code = h.ts_code
     AND k.trade_date >= h.start_date
     AND (h.end_date IS NULL OR k.trade_date <= h.end_date)
    GROUP BY k.ts_code, k.trade_date
)
SELECT
    k.*,
    s.name,
    s.exchange,
    s.area,
    s.industry,
    s.list_date,
    s.delist_date,
    s.list_status,
    COALESCE(st.is_st_on_date, FALSE) AS is_st_on_date,
    (
        (s.list_date IS NULL OR k.trade_date >= s.list_date)
        AND (s.delist_date IS NULL OR k.trade_date < s.delist_date)
    ) AS is_listed_on_date,
    (
        COALESCE(k.flag_suspended, FALSE) = FALSE
        AND COALESCE(k.flag_aligned, FALSE) = FALSE
        AND COALESCE(k.flag_invalid_ohlc, FALSE) = FALSE
        AND COALESCE(k.flag_extreme, FALSE) = FALSE
        AND COALESCE(st.is_st_on_date, FALSE) = FALSE
        AND (s.list_date IS NULL OR k.trade_date >= s.list_date)
        AND (s.delist_date IS NULL OR k.trade_date < s.delist_date)
        AND k.close > 0
    ) AS is_in_universe,
    CASE
        WHEN s.ts_code IS NULL THEN 'missing_stock_meta'
        WHEN s.list_date IS NOT NULL AND k.trade_date < s.list_date THEN 'pre_list'
        WHEN s.delist_date IS NOT NULL AND k.trade_date >= s.delist_date THEN 'delisted'
        WHEN COALESCE(st.is_st_on_date, FALSE) THEN 'historical_st'
        WHEN COALESCE(k.flag_suspended, FALSE) THEN 'suspended'
        WHEN COALESCE(k.flag_aligned, FALSE) THEN 'calendar_aligned'
        WHEN COALESCE(k.flag_invalid_ohlc, FALSE) THEN 'invalid_ohlc'
        WHEN COALESCE(k.flag_extreme, FALSE) THEN 'extreme'
        WHEN k.close <= 0 OR k.close IS NULL THEN 'invalid_close'
        ELSE NULL
    END AS exclude_reason
FROM daily_kline k
LEFT JOIN stock_list s ON k.ts_code = s.ts_code
LEFT JOIN st_flag st
  ON k.ts_code = st.ts_code
 AND k.trade_date = st.trade_date;

-- ====================================================================
-- 数据流水线日志表
-- ====================================================================
CREATE TABLE IF NOT EXISTS pipeline_log (
    id          BIGINT PRIMARY KEY,
    run_date    DATE NOT NULL,          -- 运行日期
    start_time  TIMESTAMP NOT NULL,
    end_time    TIMESTAMP,
    status      VARCHAR DEFAULT 'running',  -- running | success | failed
    stocks_fetched  INTEGER DEFAULT 0,
    stocks_cleaned  INTEGER DEFAULT 0,
    error_msg   VARCHAR,
    quality_report VARCHAR,             -- JSON 质量报告
    duration_sec    DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS seq_pipeline_id START 1;
"""


# ============================================================================
# 主类
# ============================================================================

class QuantDB:
    """
    DuckDB 量化数据库。

    封装所有数据库操作，提供：
      - 初始化与 Schema 管理
      - 批量写入（upsert）
      - 高效查询
      - 数据维护
      - 流水线日志
    """

    def __init__(self, db_path: str, config: dict = None):
        """
        Args:
            db_path: DuckDB 文件路径（如 "./data/quant.duckdb"）
            config: 全局配置（可选）
        """
        self.db_path = os.path.abspath(db_path)
        self.config = config or {}
        
        # 确保目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        logger.info(f"QuantDB 初始化: {self.db_path}")

    # ====================================================================
    # 连接管理
    # ====================================================================

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """懒加载数据库连接"""
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path)
            # 优化配置
            self._conn.execute("PRAGMA threads=4")
            self._conn.execute("PRAGMA memory_limit='2GB'")
            self._conn.execute("SET default_null_order='NULLS LAST'")
        return self._conn

    def close(self):
        """关闭连接"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("数据库连接已关闭")

    def __del__(self):
        self.close()

    # ====================================================================
    # Schema 管理
    # ====================================================================

    def init_schema(self):
        """初始化数据库 Schema（幂等：已存在的表不重复创建）"""
        statements = [s.strip() for s in SCHEMA_SQL.split(";") if s.strip()]
        for stmt in statements:
            try:
                self.conn.execute(stmt)
            except Exception as e:
                logger.warning(f"Schema 语句执行警告: {e}\n{stmt[:100]}...")

        # 兼容已有数据库的增量 schema 迁移
        self.conn.execute(
            "ALTER TABLE daily_kline ADD COLUMN IF NOT EXISTS flag_invalid_ohlc BOOLEAN DEFAULT FALSE"
        )
        self.conn.execute(
            "ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS value_text VARCHAR"
        )
        self.conn.execute(
            "ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS item_order INTEGER DEFAULT 0"
        )
        self.conn.execute(
            "ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS item_yoy DOUBLE"
        )
        self.conn.execute(
            "ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS source VARCHAR"
        )
        self.conn.execute(
            "ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )

        logger.info("数据库 Schema 初始化完成")

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        result = self.conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name]
        ).fetchone()
        return result[0] > 0

    def get_table_info(self, table_name: str) -> pd.DataFrame:
        """获取表结构信息"""
        return self.conn.execute(f"DESCRIBE {table_name}").fetchdf()

    # ====================================================================
    # 写入操作
    # ====================================================================

    def upsert_daily_kline(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        required = {"ts_code", "trade_date", "close"}
        missing = required - set(df.columns)
        if missing:
            logger.error(f"日K线数据缺少必要字段: {missing}")
            return 0

        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        
        self.conn.register("_tmp_kline", df)
        
        count = self.conn.execute("""
            INSERT INTO daily_kline (ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, adj_factor, flag_extreme, flag_suspended)
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg, adj_factor, flag_extreme, flag_suspended
            FROM _tmp_kline
            ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                open          = EXCLUDED.open,
                high          = EXCLUDED.high,
                low           = EXCLUDED.low,
                close         = EXCLUDED.close,
                vol           = EXCLUDED.vol,
                amount        = EXCLUDED.amount,
                pct_chg       = EXCLUDED.pct_chg,
                adj_factor    = EXCLUDED.adj_factor,
                flag_extreme  = EXCLUDED.flag_extreme,
                flag_suspended = EXCLUDED.flag_suspended
        """).fetchone()[0]
        
        logger.debug(f"日K线 UPSERT: {count} 行 ({df['ts_code'].iloc[0] if 'ts_code' in df.columns else 'batch'})")
        return count

    def upsert_daily_kline_batch(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        
        # 只保留 upsert 需要的列，排除 cleaner 生成的额外列
        upsert_cols = [
            "ts_code", "trade_date", "open", "high", "low", "close",
            "vol", "amount", "pct_chg", "adj_factor",
            "adj_open_qfq", "adj_high_qfq", "adj_low_qfq", "adj_close_qfq",
            "raw_open", "raw_high", "raw_low", "raw_close",
            "flag_extreme", "flag_suspended", "flag_aligned",
            "flag_invalid_ohlc",
        ]
        available_cols = [c for c in upsert_cols if c in df.columns]
        if not available_cols:
            logger.error("日K线 UPSERT: 无可用字段")
            return 0
        
        df_subset = df[available_cols]
        
        self.conn.register("_tmp_kline_batch", df_subset)
        
        col_list = ", ".join(available_cols)
        set_clause = ",\n                ".join(
            f"{col} = EXCLUDED.{col}" for col in available_cols 
            if col not in ("ts_code", "trade_date")
        )
        
        sql = f"""
            INSERT INTO daily_kline ({col_list})
            SELECT {col_list}
            FROM _tmp_kline_batch
            ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                {set_clause}
        """
        
        count = self.conn.execute(sql).fetchone()[0]
        
        logger.info(f"批量日K线 UPSERT: {count} 行")
        return count

    def upsert_daily_basic(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        
        self.conn.register("_tmp_basic", df)
        
        count = self.conn.execute("""
            INSERT INTO daily_basic (ts_code, trade_date, pe, pb, turnover_rate, volume_ratio, circ_mv, total_mv)
            SELECT ts_code, trade_date, pe, pb, turnover_rate, volume_ratio, circ_mv, total_mv
            FROM _tmp_basic
            ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                pe            = EXCLUDED.pe,
                pb            = EXCLUDED.pb,
                turnover_rate = EXCLUDED.turnover_rate,
                volume_ratio  = EXCLUDED.volume_ratio,
                circ_mv       = EXCLUDED.circ_mv,
                total_mv      = EXCLUDED.total_mv
        """).fetchone()[0]
        
        logger.debug(f"每日基本面 UPSERT: {count} 行")
        return count

    def upsert_financial(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        
        df = df.copy()
        df["ann_date"] = pd.to_datetime(df["ann_date"])
        if "end_date" in df.columns:
            df["end_date"] = pd.to_datetime(df["end_date"])
        
        self.conn.register("_tmp_fin", df)
        
        count = self.conn.execute("""
            INSERT INTO financial_indicators (ts_code, ann_date, end_date, eps, bps, roe, roe_waa, profit_yoy, revenue_yoy, free_cashflow, gross_margin, net_margin, dt_debt_ratio)
            SELECT ts_code, ann_date, end_date, eps, bps, roe, roe_waa, profit_yoy, revenue_yoy, free_cashflow, gross_margin, net_margin, dt_debt_ratio
            FROM _tmp_fin
            ON CONFLICT (ts_code, ann_date) DO UPDATE SET
                end_date      = EXCLUDED.end_date,
                eps           = EXCLUDED.eps,
                bps           = EXCLUDED.bps,
                roe           = EXCLUDED.roe,
                roe_waa       = EXCLUDED.roe_waa,
                profit_yoy    = EXCLUDED.profit_yoy,
                revenue_yoy   = EXCLUDED.revenue_yoy,
                free_cashflow = EXCLUDED.free_cashflow,
                gross_margin  = EXCLUDED.gross_margin,
                net_margin    = EXCLUDED.net_margin,
                dt_debt_ratio = EXCLUDED.dt_debt_ratio
        """).fetchone()[0]
        
        logger.debug(f"财务指标 UPSERT: {count} 行")
        return count

    def upsert_financial_statements(self, df: pd.DataFrame) -> int:
        """写入原始财务报表长表。"""
        if df.empty:
            return 0

        required = {"ts_code", "report_type", "end_date", "item", "value"}
        missing = required - set(df.columns)
        if missing:
            logger.error(f"原始财报数据缺少必要字段: {missing}")
            return 0

        df = df.copy()
        df["end_date"] = pd.to_datetime(df["end_date"])
        if "ann_date" not in df.columns:
            df["ann_date"] = pd.NaT
        df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce")
        if "source" not in df.columns:
            df["source"] = None
        if "item_yoy" not in df.columns:
            df["item_yoy"] = None
        if "item_order" not in df.columns:
            df["item_order"] = (
                df.groupby(["ts_code", "report_type", "end_date"]).cumcount() + 1
            )
        df["item_order"] = pd.to_numeric(df["item_order"], errors="coerce").fillna(0).astype(int)

        raw_value = df["value"]
        if "value_text" not in df.columns:
            df["value_text"] = raw_value.where(raw_value.notna(), None).astype("string")
        df["value"] = pd.to_numeric(raw_value, errors="coerce")
        df["item_yoy"] = pd.to_numeric(df["item_yoy"], errors="coerce")

        upsert_cols = [
            "ts_code",
            "report_type",
            "end_date",
            "ann_date",
            "item_order",
            "item",
            "value",
            "value_text",
            "item_yoy",
            "source",
        ]
        self.conn.register("_tmp_financial_statements", df[upsert_cols])
        count = self.conn.execute("""
            INSERT INTO financial_statements (
                ts_code, report_type, end_date, ann_date, item_order, item,
                value, value_text, item_yoy, source
            )
            SELECT
                ts_code, report_type, end_date, ann_date, item_order, item,
                value, value_text, item_yoy, source
            FROM _tmp_financial_statements
            ON CONFLICT (ts_code, report_type, end_date, item_order) DO UPDATE SET
                ann_date   = EXCLUDED.ann_date,
                item       = EXCLUDED.item,
                value      = EXCLUDED.value,
                value_text = EXCLUDED.value_text,
                item_yoy   = EXCLUDED.item_yoy,
                source     = EXCLUDED.source,
                updated_at = now()
        """).fetchone()[0]

        logger.debug(f"原始财报 UPSERT: {count} 行")
        return count

    def upsert_stock_name_history(self, df: pd.DataFrame) -> int:
        """写入股票名称/ST 历史。"""
        if df.empty:
            return 0

        df = df.copy()
        df["start_date"] = pd.to_datetime(df["start_date"])
        if "end_date" in df.columns:
            df["end_date"] = pd.to_datetime(df["end_date"])

        self.conn.register("_tmp_name_history", df)
        count = self.conn.execute("""
            INSERT INTO stock_name_history (
                ts_code, name, start_date, end_date, change_reason, is_st
            )
            SELECT ts_code, name, start_date, end_date, change_reason, is_st
            FROM _tmp_name_history
            ON CONFLICT (ts_code, start_date, name) DO UPDATE SET
                end_date      = EXCLUDED.end_date,
                change_reason = EXCLUDED.change_reason,
                is_st         = EXCLUDED.is_st
        """).fetchone()[0]

        logger.debug(f"股票名称历史 UPSERT: {count} 行")
        return count

    def upsert_source_audit(self, df: pd.DataFrame) -> int:
        """写入跨数据源抽样对账结果。"""
        if df.empty:
            return 0

        df = df.copy()
        for col in ["audit_date", "start_date", "end_date"]:
            df[col] = pd.to_datetime(df[col])

        self.conn.register("_tmp_source_audit", df)
        count = self.conn.execute("""
            INSERT INTO data_source_audit (
                audit_date, ts_code, start_date, end_date,
                primary_source, secondary_source, compared_rows,
                max_close_diff_pct, status, error_msg
            )
            SELECT
                audit_date, ts_code, start_date, end_date,
                primary_source, secondary_source, compared_rows,
                max_close_diff_pct, status, error_msg
            FROM _tmp_source_audit
            ON CONFLICT (
                audit_date, ts_code, primary_source, secondary_source
            ) DO UPDATE SET
                start_date         = EXCLUDED.start_date,
                end_date           = EXCLUDED.end_date,
                compared_rows      = EXCLUDED.compared_rows,
                max_close_diff_pct = EXCLUDED.max_close_diff_pct,
                status             = EXCLUDED.status,
                error_msg          = EXCLUDED.error_msg
        """).fetchone()[0]

        logger.debug(f"数据源对账 UPSERT: {count} 行")
        return count

    def upsert_trade_calendar(self, df: pd.DataFrame) -> int:
        """写入交易日历"""
        if df.empty:
            return 0
        
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        
        # 补充辅助字段
        df["day_of_week"] = df["trade_date"].dt.dayofweek
        df["week_of_year"] = df["trade_date"].dt.isocalendar().week.astype(int)
        df["month"] = df["trade_date"].dt.month
        df["year"] = df["trade_date"].dt.year
        
        # DuckDB: 用 explicit column list + VALUES 替代 BY NAME + EXCLUDED
        self.conn.register("_tmp_cal", df)
        
        count = self.conn.execute("""
            INSERT INTO trade_calendar (trade_date, is_open, pretrade_date, day_of_week, week_of_year, month, year)
            SELECT trade_date, is_open, pretrade_date, day_of_week, week_of_year, month, year
            FROM _tmp_cal
            ON CONFLICT (trade_date) DO UPDATE SET
                is_open       = EXCLUDED.is_open,
                day_of_week   = EXCLUDED.day_of_week,
                week_of_year  = EXCLUDED.week_of_year,
                month         = EXCLUDED.month,
                year          = EXCLUDED.year
        """).fetchone()[0]
        
        logger.debug(f"交易日历 UPSERT: {count} 行")
        return count

    # ====================================================================
    # 查询操作
    # ====================================================================

    def query_daily_range(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        columns: str = "*",
    ) -> pd.DataFrame:
        """
        查询某只股票在日期范围内的日K线。
        """
        sql = f"""
            SELECT {columns} FROM daily_kline
            WHERE ts_code = ?
              AND trade_date BETWEEN ?::DATE AND ?::DATE
            ORDER BY trade_date
        """
        return self.conn.execute(sql, [ts_code, start_date, end_date]).fetchdf()

    def query_cross_section(self, trade_date: str) -> pd.DataFrame:
        """
        查询某一交易日全市场截面数据（所有股票的K线）。
        
        在对齐的交易日历下做截面分析时使用。
        """
        sql = """
            SELECT k.*, b.pe, b.pb, b.turnover_rate, b.circ_mv, b.total_mv
            FROM daily_kline k
            LEFT JOIN daily_basic b ON k.ts_code = b.ts_code AND k.trade_date = b.trade_date
            WHERE k.trade_date = ?::DATE
              AND k.close > 0
        """
        return self.conn.execute(sql, [trade_date]).fetchdf()

    def query_research_universe(
        self,
        trade_date: str,
        only_in_universe: bool = True,
    ) -> pd.DataFrame:
        """查询研究用日度股票池，默认只返回可投资样本。"""
        where = ["trade_date = ?::DATE"]
        if only_in_universe:
            where.append("is_in_universe = TRUE")
        sql = f"""
            SELECT *
            FROM research_daily_universe
            WHERE {' AND '.join(where)}
            ORDER BY ts_code
        """
        return self.conn.execute(sql, [trade_date]).fetchdf()

    def query_recent_trade_dates(self, n: int = 5) -> pd.Series:
        """获取最近 N 个交易日"""
        df = self.conn.execute(f"""
            SELECT trade_date FROM trade_calendar
            WHERE is_open = 1 AND trade_date <= CURRENT_DATE
            ORDER BY trade_date DESC
            LIMIT {n}
        """).fetchdf()
        return df["trade_date"]

    def query_stock_list(self, status: str = "L") -> pd.DataFrame:
        """查询股票列表"""
        return self.conn.execute(
            "SELECT * FROM stock_list WHERE list_status = ? ORDER BY ts_code",
            [status]
        ).fetchdf()

    def get_latest_trade_date(self) -> Optional[date]:
        """获取数据库中最近的交易日"""
        result = self.conn.execute("""
            SELECT MAX(trade_date) FROM daily_kline
        """).fetchone()
        return result[0] if result else None

    def get_latest_trade_date_for_stock(self, ts_code: str) -> Optional[date]:
        """获取单只股票已经落库的最近交易日。"""
        result = self.conn.execute(
            "SELECT MAX(trade_date) FROM daily_kline WHERE ts_code = ?",
            [ts_code],
        ).fetchone()
        return result[0] if result else None

    def get_latest_trade_dates_by_stock(self) -> Dict[str, date]:
        """批量获取每只股票的最新落库日期。"""
        if not self.table_exists("daily_kline"):
            return {}
        df = self.conn.execute("""
            SELECT ts_code, MAX(trade_date) AS latest_date
            FROM daily_kline
            GROUP BY ts_code
        """).fetchdf()
        return dict(zip(df["ts_code"], df["latest_date"]))

    def get_stock_count(self, trade_date: str = None) -> int:
        """获取某交易日有数据的股票数量"""
        if trade_date:
            result = self.conn.execute(
                "SELECT COUNT(DISTINCT ts_code) FROM daily_kline WHERE trade_date = ?::DATE",
                [trade_date]
            ).fetchone()
        else:
            result = self.conn.execute(
                "SELECT COUNT(DISTINCT ts_code) FROM daily_kline"
            ).fetchone()
        return result[0] if result else 0

    def query_sql(self, sql: str, params: list = None) -> pd.DataFrame:
        """执行原生 SQL 查询"""
        if params:
            return self.conn.execute(sql, params).fetchdf()
        return self.conn.execute(sql).fetchdf()

    # ====================================================================
    # 维护操作
    # ====================================================================

    def vacuum(self):
        """压缩数据库（释放磁盘空间）"""
        logger.info("开始压缩数据库...")
        before = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        self.conn.execute("VACUUM")
        after = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        saved = before - after
        logger.info(f"数据库压缩完成: {before / 1e6:.1f}MB -> {after / 1e6:.1f}MB (节省 {saved / 1e6:.1f}MB)")

    def analyze(self):
        """更新统计信息（帮助查询优化器）"""
        self.conn.execute("ANALYZE")
        logger.info("数据库统计信息已更新")

    def table_row_count(self, table_name: str) -> int:
        """获取表行数"""
        result = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return result[0] if result else 0

    def database_size_mb(self) -> float:
        """获取数据库文件大小（MB）"""
        if os.path.exists(self.db_path):
            return os.path.getsize(self.db_path) / (1024 * 1024)
        return 0.0

    # ====================================================================
    # 流水线日志
    # ====================================================================

    def log_pipeline_start(self, run_date: date = None) -> int:
        """记录流水线开始，返回日志 ID"""
        if run_date is None:
            run_date = date.today()
        
        log_id = self.conn.execute("SELECT nextval('seq_pipeline_id')").fetchone()[0]
        
        self.conn.execute("""
            INSERT INTO pipeline_log (id, run_date, start_time, status)
            VALUES (?, ?, CURRENT_TIMESTAMP, 'running')
        """, [log_id, run_date])
        
        return log_id

    def log_pipeline_end(
        self,
        log_id: int,
        status: str,
        stocks_fetched: int = 0,
        stocks_cleaned: int = 0,
        error_msg: str = None,
        quality_report: str = None,
    ):
        """记录流水线结束"""
        self.conn.execute("""
            UPDATE pipeline_log SET
                end_time = CURRENT_TIMESTAMP,
                status = ?,
                stocks_fetched = ?,
                stocks_cleaned = ?,
                error_msg = ?,
                quality_report = ?,
                duration_sec = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - start_time))
            WHERE id = ?
        """, [status, stocks_fetched, stocks_cleaned, error_msg, quality_report, log_id])

    def get_recent_pipeline_logs(self, n: int = 10) -> pd.DataFrame:
        """获取最近 N 次流水线运行日志"""
        return self.conn.execute(f"""
            SELECT * FROM pipeline_log
            ORDER BY run_date DESC
            LIMIT {n}
        """).fetchdf()
