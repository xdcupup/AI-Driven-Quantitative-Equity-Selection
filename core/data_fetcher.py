"""
AI 量化数据流水线 — 数据采集模块
===================================

职责:
  1. 获取 A 股全市场股票列表（含已退市 — 防幸存者偏差）
  2. 获取日K线行情（后复权 + 前复权）
  3. 获取复权因子
  4. 获取每日基本面（PE/PB/换手率等）
  5. 获取季度财务指标（使用 ann_date 防止前视偏差）
  6. 获取交易日历
  7. 增量更新（只拉取缺失日期）

双数据源策略:
  - AKShare（免费，零门槛） — 主数据源，负责日K线 + 复权因子 + 交易日历
  - Tushare Pro（积分制） — 补充数据源，负责财务指标 + 每日基本面
  - 配置 tushare_token="" 时仅走 AKShare

使用方式:
  from core.data_fetcher import DataFetcher
  fetcher = DataFetcher(config)
  df = fetcher.fetch_daily_kline("000001.SZ", "20240101", "20240615")
"""

import time
import random
import datetime
import threading
import json
import subprocess
import os
from contextlib import contextmanager
from typing import Optional, List, Tuple
from functools import wraps
from urllib.parse import urlencode

import pandas as pd
from loguru import logger

from core.providers.eastmoney import EastMoneyClient
from core.providers.rate_limit import EastMoneyLimiter
from core.providers.tencent import TencentKlineClient


# ============================================================================
# 工具函数
# ============================================================================

def retry_with_backoff(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = (Exception,),
):
    """
    带 jitter 的指数退避重试装饰器。
    
    比起固定间隔重试，指数退避 + 随机抖动 (jitter) 能:
    1. 避免所有重试在同一时刻爆发
    2. 给 API 服务端足够的恢复时间
    3. 高并发场景下更友好
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟上限（秒）
        retryable_exceptions: 哪些异常需要重试
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        # 指数退避: 1, 2, 4, 8, 16... 秒
                        delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                        logger.warning(
                            f"{func.__name__} 第 {attempt}/{max_retries} 次重试 "
                            f"(等待 {delay:.1f}s) — {e}"
                        )
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


def ts_code_to_symbol(ts_code: str) -> str:
    """将 Tushare 格式 '000001.SZ' 转为数字代码 '000001'"""
    return ts_code.split(".")[0]


def symbol_to_akshare_code(symbol: str, exchange: str = "SZ") -> str:
    """转为 AKShare 格式"""
    return f"{symbol}"  # AKShare 直接传数字代码


def parse_date(date_str: str) -> str:
    """统一日期格式为 YYYYMMDD"""
    if isinstance(date_str, datetime.date):
        return date_str.strftime("%Y%m%d")
    if date_str.lower() == "today":
        return datetime.date.today().strftime("%Y%m%d")
    # 去掉 - 分隔符
    return date_str.replace("-", "")


def parse_date_std(date_str: str) -> str:
    """转为标准 YYYY-MM-DD 格式"""
    d = parse_date(date_str)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def is_long_history_request(start: str, end: str, max_bars: int = 1900) -> bool:
    """判断请求区间是否可能超过腾讯单次 K 线条数上限。"""
    start_dt = pd.Timestamp(parse_date(start))
    end_dt = pd.Timestamp(parse_date(end))
    if end_dt < start_dt:
        return False
    return len(pd.bdate_range(start_dt, end_dt)) > max_bars


PROXY_ENV_KEYS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]


def build_no_proxy_env() -> dict:
    """构造禁用系统代理的环境变量，给 subprocess/curl 使用。"""
    env = os.environ.copy()
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


@contextmanager
def bypass_system_proxy():
    """临时禁用 requests 可见的代理，避免 macOS 系统代理劫持东财。"""
    old_values = {key: os.environ.get(key) for key in PROXY_ENV_KEYS + ["NO_PROXY", "no_proxy"]}
    try:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ============================================================================
# 主类
# ============================================================================

class DataFetcher:
    """
    数据采集器 — 统一接口，屏蔽 AKShare / Tushare 差异。
    
    使用示例:
        fetcher = DataFetcher({"data_source": {"tushare_token": ""}})
        
        # 获取股票列表
        stocks = fetcher.fetch_stock_list()
        
        # 获取日K线
        df = fetcher.fetch_daily_kline("000001.SZ", "20240101", "20240615")
        
        # 获取交易日历
        cal = fetcher.fetch_trade_calendar(2024)
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 全局配置 dict（从 config.yaml 加载）
        """
        self.config = config
        self._tushare_pro = None
        self._tushare_token = config.get("data_source", {}).get("tushare_token", "")
        self._primary = config.get("data_source", {}).get("primary", "akshare")
        eastmoney_cfg = config.get("providers", {}).get("eastmoney", {})
        self._eastmoney_client = EastMoneyClient(
            limiter=EastMoneyLimiter(
                min_interval_sec=float(eastmoney_cfg.get("min_interval_sec", 1.0))
            )
        )
        self._tencent_kline_client = TencentKlineClient()
        
        # 初始化数据源
        self._init_akshare()
        if self._tushare_token:
            self._init_tushare()
            
        # 限频控制（API 友好）
        self._last_request_time = 0.0
        self._min_request_interval = 0.3  # 300ms，根据实际情况调整
        self._rate_limit_lock = threading.Lock()
    
    def _rate_limit(self):
        """限频：确保两次请求之间至少间隔 min_request_interval 秒"""
        with self._rate_limit_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
            self._last_request_time = time.time()

    def _init_akshare(self):
        """延迟导入 AKShare（避免在无网络环境崩溃）"""
        try:
            import akshare as ak
            self._ak = ak
            logger.info("AKShare 数据源初始化成功")
        except ImportError:
            logger.error("AKShare 未安装: pip install akshare")
            self._ak = None
        except Exception as e:
            logger.error(f"AKShare 初始化失败: {e}")
            self._ak = None

    def _init_tushare(self):
        """初始化 Tushare Pro"""
        try:
            import tushare as ts
            ts.set_token(self._tushare_token)
            self._tushare_pro = ts.pro_api()
            logger.info("Tushare Pro 数据源初始化成功")
        except ImportError:
            logger.warning("Tushare 未安装，仅使用 AKShare")
            self._tushare_pro = None
        except Exception as e:
            logger.warning(f"Tushare 初始化失败: {e}，仅使用 AKShare")
            self._tushare_pro = None

    # ========================================================================
    # 公开接口
    # ========================================================================

    def fetch_stock_list(self) -> pd.DataFrame:
        """
        获取全市场 A 股股票列表（含已退市 — 防幸存者偏差）。
        
        Returns:
            DataFrame columns: ts_code, symbol, name, area, industry, 
                               list_date, delist_date, list_status, exchange
        """
        logger.info("开始获取 A 股股票列表...")
        
        # 优先用 Tushare（数据更准）
        if self._tushare_pro:
            return self._fetch_stock_list_tushare()
        
        # 否则用 AKShare
        return self._fetch_stock_list_akshare()

    def fetch_daily_kline(
        self,
        code: str,           # "000001.SZ" 或 "000001"
        start_date: str,
        end_date: str,
        adjust: str = "hfq", # hfq=后复权, qfq=前复权
    ) -> pd.DataFrame:
        """
        获取个股日 K 线。
        
        Args:
            code: 股票代码（支持 ts_code 格式 "000001.SZ" 或纯代码 "000001"）
            start_date: 起始日期 YYYYMMDD 或 YYYY-MM-DD
            end_date: 截止日期
            adjust: 复权类型
            
        Returns:
            DataFrame columns: ts_code, trade_date, open, high, low, close, 
                               vol, amount, pct_chg
        """
        start = parse_date(start_date)
        end = parse_date(end_date)
        symbol = code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
        
        logger.debug(f"获取日K线: {code} [{start} -> {end}]")

        primary = getattr(
            self,
            "_primary",
            self.config.get("data_source", {}).get("primary", "akshare"),
        )

        if primary == "tushare" and self._tushare_pro:
            df = self._fetch_kline_tushare(code, start, end)
            if not df.empty:
                return df

        if primary == "eastmoney":
            df = self._fetch_kline_eastmoney(symbol, start, end, adjust)
            if not df.empty:
                return df
        
        if self._ak:
            return self._fetch_kline_akshare(symbol, start, end, adjust)
        
        if self._tushare_pro:
            return self._fetch_kline_tushare(code, start, end)
        
        raise RuntimeError("无可用数据源，请安装 AKShare 或配置 Tushare Token")

    def fetch_adj_factor(self, ts_code: str) -> pd.DataFrame:
        """
        获取复权因子。
        
        Returns:
            DataFrame columns: ts_code, trade_date, adj_factor
        """
        symbol = ts_code.split(".")[0]
        
        if self._tushare_pro:
            return self._fetch_adj_tushare(ts_code)

        if self._ak:
            return self._fetch_adj_akshare(symbol)
        
        raise RuntimeError("无可用数据源")

    def fetch_trade_calendar(self, year: int) -> pd.DataFrame:
        """
        获取指定年份的交易日历。
        
        Returns:
            DataFrame columns: trade_date, is_open, pretrade_date
        """
        if self._tushare_pro:
            return self._fetch_calendar_tushare(year)
        
        if self._ak:
            return self._fetch_calendar_akshare(year)
        
        raise RuntimeError("无可用数据源")

    def fetch_daily_basic(self, trade_date: str) -> pd.DataFrame:
        """
        获取某日全市场基本面数据（PE/PB/换手率/流通市值等）。
        
        Args:
            trade_date: 交易日 YYYYMMDD
            
        Returns:
            DataFrame columns: ts_code, trade_date, pe, pb, turnover_rate, 
                               circ_mv, total_mv, volume_ratio
        """
        date = parse_date(trade_date)
        
        # 仅 Tushare 支持
        if self._tushare_pro:
            return self._fetch_daily_basic_tushare(date)
        
        logger.warning("每日基本面需要 Tushare Pro Token")
        return pd.DataFrame()

    def fetch_financial_indicators(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取个股财务指标（季频）。
        
        关键: 用 ann_date（公告日期）对齐，防止前视偏差。
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame columns: ts_code, ann_date, end_date, eps, bps, roe, 
                               profit_yoy, revenue_yoy, free_cashflow, ...
        """
        # 仅 Tushare 支持
        if self._tushare_pro:
            return self._fetch_financial_tushare(ts_code, parse_date(start_date), parse_date(end_date))
        
        logger.warning("财务数据需要 Tushare Pro Token")
        return pd.DataFrame()

    def fetch_stock_name_history(self, ts_code: str) -> pd.DataFrame:
        """
        获取股票名称变更历史，用于还原历史 ST 状态。

        Returns:
            DataFrame columns: ts_code, name, start_date, end_date,
                               change_reason, is_st
        """
        if self._tushare_pro:
            return self._fetch_name_history_tushare(ts_code)

        logger.debug("股票名称历史需要 Tushare Pro Token")
        return pd.DataFrame()

    def compare_market_sources(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        tolerance_pct: float = 1.0,
        secondary: str = "sina",
    ) -> dict:
        """对比腾讯和第二数据源的收盘价，用于抽样发现数据源漂移。"""
        symbol = ts_code.split(".")[0]
        start = parse_date(start_date)
        end = parse_date(end_date)
        result = {
            "audit_date": pd.Timestamp.today().normalize(),
            "ts_code": ts_code,
            "start_date": pd.Timestamp(start),
            "end_date": pd.Timestamp(end),
            "primary_source": "tencent",
            "secondary_source": secondary,
            "compared_rows": 0,
            "max_close_diff_pct": None,
            "status": "failed",
            "error_msg": None,
        }

        try:
            primary = self._fetch_kline_tencent(symbol, start, end, "none")
            secondary_df = self._fetch_secondary_audit_source(
                secondary, symbol, start, end
            )
            if primary.empty or secondary_df.empty:
                result["error_msg"] = "source returned empty data"
                return result

            merged = primary[["trade_date", "close"]].merge(
                secondary_df[["trade_date", "close"]],
                on="trade_date",
                how="inner",
                suffixes=("_primary", "_secondary"),
            )
            if merged.empty:
                result["error_msg"] = "no overlapping trade dates"
                return result

            base = merged["close_primary"].abs()
            diff = (
                (merged["close_primary"] - merged["close_secondary"]).abs()
                / base.where(base != 0)
                * 100
            )
            max_diff = float(diff.max())
            result["compared_rows"] = int(len(merged))
            result["max_close_diff_pct"] = round(max_diff, 6)
            result["status"] = "warning" if max_diff > tolerance_pct else "normal"
            return result
        except Exception as e:
            result["error_msg"] = str(e)
            return result

    def _fetch_secondary_audit_source(
        self, source: str, symbol: str, start: str, end: str
    ) -> pd.DataFrame:
        """按名称获取对账源行情。"""
        if source == "sina":
            return self._fetch_kline_sina(symbol, start, end)
        if source == "eastmoney":
            return self._fetch_kline_akshare_hist(symbol, start, end, "none")
        raise ValueError(f"unsupported audit source: {source}")

    def fetch_batch_daily_kline(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        adjust: str = "hfq",
        batch_size: int = 50,
    ) -> pd.DataFrame:
        """
        批量获取多只股票日 K 线。
        
        分批采集，每批之间限频，失败重试。
        
        Returns:
            合并后的 DataFrame
        """
        all_dfs = []
        total = len(codes)
        
        for i in range(0, total, batch_size):
            batch = codes[i:i + batch_size]
            logger.info(f"批量获取日K线 [{i + 1}-{min(i + batch_size, total)}/{total}]")
            
            for code in batch:
                try:
                    df = self.fetch_daily_kline(code, start_date, end_date, adjust)
                    if not df.empty:
                        all_dfs.append(df)
                except Exception as e:
                    logger.error(f"获取 {code} 日K线失败: {e}")
                self._rate_limit()
        
        if not all_dfs:
            return pd.DataFrame()
        
        return pd.concat(all_dfs, ignore_index=True)

    # ========================================================================
    # 内部实现 — AKShare
    # ========================================================================

    def _fetch_stock_list_akshare(self) -> pd.DataFrame:
        """AKShare: 获取股票列表（含已退市）"""
        self._rate_limit()
        try:
            df = self._ak.stock_info_a_code_name()
            if df.empty:
                return df
            
            # 标准化字段
            df = df.rename(columns={"code": "symbol", "name": "name"})
            
            # 识别交易所
            def _detect_exchange(symbol):
                if symbol.startswith("6"):
                    return "SSE"
                elif symbol.startswith("0") or symbol.startswith("3"):
                    return "SZSE"
                elif symbol.startswith(("4", "8", "9")):
                    return "BSE"
                return "UNKNOWN"
            
            # Tushare 风格 ts_code
            exchange_map = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
            
            rows = []
            for _, row in df.iterrows():
                sym = str(row["symbol"]).zfill(6)
                ex = _detect_exchange(sym)
                suffix = exchange_map.get(ex)
                if suffix is None:
                    logger.warning(f"未知交易所股票跳过: {sym} {row['name']}")
                    continue
                rows.append({
                    "ts_code": f"{sym}.{suffix}",
                    "symbol": sym,
                    "name": row["name"],
                    "exchange": ex,
                    "list_status": "L",       # 默认上市
                    "list_date": None,
                    "delist_date": None,
                })
            
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"AKShare 获取股票列表失败: {e}")
            return pd.DataFrame()

    def _fetch_kline_akshare(self, symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
        """获取日 K 线
        
        主方案：East Money（含成交额、换手率，数据完整）
           - 900xxx B 股跳过，直接走腾讯
           - 请求间隔 1s+ 防封 IP
        降级方案：腾讯财经 API（稳定，无成交额）
        """
        # B 股东财不支持，直接降级
        if symbol.startswith("9"):
            return self._fetch_kline_tencent(symbol, start, end)
        
        # ----- 主方案: East Money (AKShare, 含成交额/换手率) -----
        # 东财限频：每次请求间隔至少 1 秒
        original_rate = getattr(self, "_min_request_interval", 0.3)
        self._min_request_interval = max(original_rate, 1.0)
        
        df = self._fetch_kline_eastmoney(symbol, start, end, adjust)
        
        # 恢复原限频
        self._min_request_interval = original_rate
        
        if not df.empty:
            return df
        logger.warning(f"East Money 不可用 ({symbol}), 降级到腾讯")
        
        # ----- 降级方案: 腾讯 API -----
        return self._fetch_kline_tencent(symbol, start, end)

    def _fetch_kline_eastmoney(
        self, symbol: str, start: str, end: str, adjust: str
    ) -> pd.DataFrame:
        """East Money 日 K 线，用作可选主行情源。"""
        if self._ak:
            df = self._fetch_kline_akshare_hist(symbol, start, end, adjust)
            if not df.empty:
                return df
        return self._fetch_kline_eastmoney_curl(symbol, start, end, adjust)

    def _fetch_kline_akshare_hist(self, symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
        """AKShare East Money 历史行情，支持按日期区间请求并带成交额。"""
        self._rate_limit()
        adjust_map = {"hfq": "hfq", "qfq": "qfq", "none": ""}
        adj_param = adjust_map.get(adjust, "")
        try:
            with bypass_system_proxy():
                df = self._ak.stock_zh_a_hist(
                    symbol=symbol, period="daily",
                    start_date=start, end_date=end, adjust=adj_param,
                )
            return self._normalize_akshare_kline(df, symbol)
        except Exception as e:
            logger.warning(f"East Money 降级也失败 ({symbol}): {type(e).__name__}")
            return self._fetch_kline_eastmoney_curl(symbol, start, end, adjust)

    def _fetch_kline_sina(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """新浪日 K 线，用作轻量对账源。"""
        import requests

        exchange = "sz" if symbol.startswith(("0", "3")) else "sh" if symbol.startswith("6") else "bj"
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        # 新浪接口只支持 datalen，不支持日期区间；多取一些再本地过滤。
        datalen = max(10, len(pd.bdate_range(start_ts, end_ts)) + 10)
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.get(
                "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData",
                params={
                    "symbol": f"{exchange}{symbol}",
                    "scale": "240",
                    "ma": "no",
                    "datalen": str(datalen),
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            if resp.status_code != 200:
                return pd.DataFrame()
            rows = resp.json()
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            df = df.rename(
                columns={
                    "day": "trade_date",
                    "volume": "vol",
                }
            )
            for col in ["open", "high", "low", "close", "vol"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df[
                (df["trade_date"] >= start_ts) & (df["trade_date"] <= end_ts)
            ].copy()
            suffix = "SZ" if symbol.startswith(("0", "3")) else "SH" if symbol.startswith("6") else "BJ"
            df["ts_code"] = f"{symbol}.{suffix}"
            df["amount"] = float("nan")
            return df.sort_values("trade_date").reset_index(drop=True)
        except Exception as e:
            logger.warning(f"新浪对账源失败 ({symbol}): {type(e).__name__}")
            return pd.DataFrame()

    def _fetch_kline_eastmoney_curl(
        self, symbol: str, start: str, end: str, adjust: str
    ) -> pd.DataFrame:
        """用系统 curl 强制 IPv4 拉 East Money，避开 macOS 代理和 IPv6 断连。"""
        client = getattr(self, "_eastmoney_client", None)
        if client is not None:
            try:
                resp = client.get_kline(symbol, start, end, adjust=adjust, timeout=20)
                if resp.status_code == 200 and resp.text:
                    return self._parse_eastmoney_kline_payload(
                        resp.text, symbol, adjust
                    )
            except Exception as e:
                logger.warning(
                    f"East Money client 兜底失败 ({symbol}): {type(e).__name__}"
                )

        market_code = "1" if symbol.startswith("6") else "0"
        adjust_map = {"none": "0", "qfq": "1", "hfq": "2"}
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101",
            "fqt": adjust_map.get(adjust, "0"),
            "secid": f"{market_code}.{symbol}",
            "beg": start,
            "end": end,
        }
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            + urlencode(params)
        )
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-4",
                    "-L",
                    "--silent",
                    "--show-error",
                    "--noproxy",
                    "*",
                    "--max-time",
                    "20",
                    url,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=build_no_proxy_env(),
            )
            if completed.returncode != 0:
                logger.warning(
                    f"East Money curl 兜底失败 ({symbol}): {completed.stderr.strip()}"
                )
                return pd.DataFrame()
            return self._parse_eastmoney_kline_payload(
                completed.stdout, symbol, adjust
            )
        except Exception as e:
            logger.warning(f"East Money curl 兜底异常 ({symbol}): {type(e).__name__}")
            return pd.DataFrame()

    def _parse_eastmoney_kline_payload(
        self, payload: str, symbol: str, adjust: str
    ) -> pd.DataFrame:
        data = json.loads(payload)
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return pd.DataFrame()

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 11:
                continue
            rows.append({
                "trade_date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "vol": float(parts[5]) * 100,
                "amount": float(parts[6]),
                "pct_chg": float(parts[8]),
            })
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        suffix = "SZ" if symbol.startswith(("0", "3")) else "SH" if symbol.startswith("6") else "BJ"
        df["ts_code"] = f"{symbol}.{suffix}"
        if adjust == "none":
            for col in ["open", "high", "low", "close"]:
                df[f"raw_{col}"] = df[col]
        df["adj_factor"] = float("nan")
        df["price_type"] = adjust
        df["flag_extreme"] = False
        df["flag_suspended"] = False
        return df.sort_values("trade_date").reset_index(drop=True)
    
    def _fetch_kline_tencent(self, symbol: str, start: str, end: str, adjust_param: str = "none") -> pd.DataFrame:
        """降级方案：用 requests + 腾讯财经 API 获取日 K 线。
        
        腾讯财经接口 (web.ifzq.gtimg.cn) 用标准 requests 即可访问，
        不受系统代理和 curl_cffi 影响，比 Sina 和 East Money 更稳定。
        """
        self._rate_limit()
        try:
            client = getattr(self, "_tencent_kline_client", TencentKlineClient())
            df = client.fetch_daily_kline(
                symbol, start, end, adjust=adjust_param
            )
            logger.info(f"腾讯API: {symbol} ({len(df)} rows, {adjust_param})")
            return df
        except Exception as e:
            logger.warning(f"腾讯API降级也失败 ({symbol}): {type(e).__name__}")
            return pd.DataFrame()
    
    def _fetch_kline_akshare_v2(self, symbol: str, start: str, end: str, adj_param: str) -> pd.DataFrame:
        """第三方案：AKShare 的其他接口
        
        尝试使用 stock_zh_a_daily（requests 协议，不依赖 curl_cffi）。
        """
        self._rate_limit()
        try:
            # stock_zh_a_daily 可能已弃用，做个 try
            df = self._ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start,
                end_date=end,
                adjust=adj_param or "qfq",
            )
            if df.empty:
                return df
            
            df = self._normalize_akshare_kline(df, symbol)
            logger.info(f"AKShare v2 成功: {symbol} ({len(df)} rows)")
            return df
        except Exception as e:
            logger.error(f"所有方案均失败 ({symbol}): {type(e).__name__}")
            return pd.DataFrame()
    
    def _normalize_akshare_kline(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """统一字段名，各个 AKShare 函数输出格式可能不同"""
        # 中文列名 → 英文
        rename_map = {
            "日期": "trade_date", "开盘": "open", "最高": "high", 
            "最低": "low", "收盘": "close", "成交量": "vol", "成交额": "amount",
            "振幅": "amplitude", "涨跌幅": "pct_chg", "涨跌额": "price_change",
            "换手率": "turnover_rate",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        
        # 确认必选字段
        for col in ["trade_date", "open", "close", "vol"]:
            if col not in df.columns:
                return pd.DataFrame()
        
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["ts_code"] = f"{symbol}.{'SZ' if symbol.startswith(('0','3')) else 'SH' if symbol.startswith('6') else 'BJ'}"
        
        if "vol" in df.columns:
            df["vol"] = df["vol"].astype(float)
        if "amount" in df.columns:
            df["amount"] = df["amount"].astype(float)
        
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def _fetch_adj_akshare(self, symbol: str) -> pd.DataFrame:
        """获取复权因子
        
        腾讯财经 API 直���返回前复权数据，无需单独获取复权因子。
        AKShare 的 stock_zh_a_adjust 在新版已被移除。
        
        Returns:
            空 DataFrame（无可靠复权因子时保持为空）
        """
        logger.debug(f"复权因子: {symbol} 跳过（腾讯API已含复权数据）")
        return pd.DataFrame()

    def _fetch_calendar_akshare(self, year: int) -> pd.DataFrame:
        """AKShare: 获取交易日历
        
        AKShare 只返回交易日列表，需要自行补全非交易日形成完整日历。
        """
        self._rate_limit()
        try:
            trade_dates = self._ak.tool_trade_date_hist_sina()
            if trade_dates.empty:
                return pd.DataFrame()
            
            trade_dates["trade_date"] = pd.to_datetime(trade_dates["trade_date"])
            
            # 筛选年份
            trade_dates = trade_dates[trade_dates["trade_date"].dt.year == year]
            if trade_dates.empty:
                # 年份无数据则生成那年所有日期，全部标记为交易日（以防缺失）
                start = pd.Timestamp(f"{year}-01-01")
                end = pd.Timestamp(f"{year}-12-31")
                all_dates = pd.date_range(start, end, freq="D")
                return pd.DataFrame({
                    "trade_date": all_dates,
                    "is_open": 1,
                    "pretrade_date": [None] * len(all_dates),
                })
            
            # 生成当年完整日期范围
            start = pd.Timestamp(f"{year}-01-01")
            end = pd.Timestamp(f"{year}-12-31")
            all_dates = pd.date_range(start, end, freq="D")
            
            trade_set = set(trade_dates["trade_date"].dt.date)
            
            df = pd.DataFrame({
                "trade_date": all_dates,
                "is_open": [1 if d.date() in trade_set else 0 for d in all_dates],
            })
            
            # 计算前一交易日
            open_dates = df[df["is_open"] == 1]["trade_date"].tolist()
            def _prev_trade(d):
                prev = [od for od in open_dates if od < d]
                return prev[-1] if prev else None
            df["pretrade_date"] = df.apply(lambda row: _prev_trade(row["trade_date"]) if row["is_open"] == 1 else None, axis=1)
            
            return df
        except Exception as e:
            logger.error(f"AKShare 获取交易日历失败: {e}")
            return pd.DataFrame()

    # ========================================================================
    # 内部实现 — Tushare
    # ========================================================================

    @retry_with_backoff(max_retries=3)
    def _fetch_stock_list_tushare(self) -> pd.DataFrame:
        """Tushare: 获取股票列表（含已退市）"""
        self._rate_limit()
        fields = (
            "ts_code,symbol,name,area,industry,list_date,delist_date,"
            "market,exchange"
        )
        
        # 上市股票
        listed = self._tushare_pro.stock_basic(
            exchange="", list_status="L",
            fields=fields,
        )
        
        # 退市股票（防幸存者偏差！）
        delisted = self._tushare_pro.stock_basic(
            exchange="", list_status="D",
            fields=fields,
        )
        
        if listed.empty and delisted.empty:
            return pd.DataFrame()
        
        df = pd.concat([listed, delisted], ignore_index=True)
        df["list_status"] = df["ts_code"].apply(
            lambda x: "D" if x in delisted["ts_code"].values else "L"
        )
        for col in ["list_date", "delist_date"]:
            if col not in df.columns:
                df[col] = pd.NaT
            df[col] = pd.to_datetime(df[col], errors="coerce")
        
        return df

    @retry_with_backoff(max_retries=3)
    def _fetch_kline_tushare(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """Tushare: 获取日 K 线"""
        self._rate_limit()
        try:
            df = self._tushare_pro.daily(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
            )
            if df.empty:
                return df
            if "amount" in df.columns:
                df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000
            
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("trade_date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} 日K线失败: {e}")
            return pd.DataFrame()

    @retry_with_backoff(max_retries=3)
    def _fetch_adj_tushare(self, ts_code: str) -> pd.DataFrame:
        """Tushare: 获取复权因子"""
        self._rate_limit()
        try:
            df = self._tushare_pro.adj_factor(ts_code=ts_code)
            if df.empty:
                return df
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} 复权因子失败: {e}")
            return pd.DataFrame()

    @retry_with_backoff(max_retries=3)
    def _fetch_calendar_tushare(self, year: int) -> pd.DataFrame:
        """Tushare: 获取交易日历"""
        self._rate_limit()
        try:
            df = self._tushare_pro.trade_cal(
                start_date=f"{year}0101",
                end_date=f"{year}1231",
            )
            if df.empty:
                return df
            df["trade_date"] = pd.to_datetime(df["cal_date"])
            df["is_open"] = df["is_open"].astype(int)
            return df
        except Exception as e:
            logger.error(f"Tushare 获取交易日历失败: {e}")
            return pd.DataFrame()

    @retry_with_backoff(max_retries=3)
    def _fetch_daily_basic_tushare(self, trade_date: str) -> pd.DataFrame:
        """Tushare: 获取每日基本面"""
        self._rate_limit()
        try:
            df = self._tushare_pro.daily_basic(
                trade_date=trade_date,
                fields="ts_code,trade_date,pe,pb,turnover_rate,volume_ratio,circ_mv,total_mv"
            )
            if df.empty:
                return df
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df
        except Exception as e:
            logger.error(f"Tushare 获取每日基本面失败: {e}")
            return pd.DataFrame()

    @retry_with_backoff(max_retries=3)
    def _fetch_financial_tushare(self, ts_code: str, start: str, end: str) -> pd.DataFrame:
        """Tushare: 获取财务指标（用 ann_date 对齐！）"""
        self._rate_limit()
        try:
            # fina_indicator 包含最常用的财务指标
            df = self._tushare_pro.fina_indicator(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields=(
                    "ts_code,ann_date,end_date,eps,bps,roe,roe_waa,"
                    "profit_dedt,ocfps,cfps,free_cashflow,"
                    "profit_yoy,revenue_yoy,op_yoy,dt_debt_to_assets,"
                    "gross_margin,net_margin"
                ),
            )
            if df.empty:
                return df
            
            df["ann_date"] = pd.to_datetime(df["ann_date"])
            df["end_date"] = pd.to_datetime(df["end_date"])
            df = df.rename(
                columns={"dt_debt_to_assets": "dt_debt_ratio"}
            )
            
            # 关键：按公告日期排序
            df = df.sort_values("ann_date").reset_index(drop=True)
            
            return df
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} 财务数据失败: {e}")
            return pd.DataFrame()

    @retry_with_backoff(max_retries=3)
    def _fetch_name_history_tushare(self, ts_code: str) -> pd.DataFrame:
        """Tushare: 获取名称变更历史，用名称和变更原因标记 ST 区间。"""
        self._rate_limit()
        try:
            df = self._tushare_pro.namechange(
                ts_code=ts_code,
                fields="ts_code,name,start_date,end_date,change_reason",
            )
            if df.empty:
                return df

            for col in ["start_date", "end_date"]:
                df[col] = pd.to_datetime(df[col], errors="coerce")
            upper_name = df["name"].fillna("").str.upper()
            upper_reason = df["change_reason"].fillna("").str.upper()
            df["is_st"] = upper_name.str.contains("ST") | upper_reason.str.contains("ST")
            df = df.sort_values("start_date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} 名称历史失败: {e}")
            return pd.DataFrame()


# ============================================================================
# 便捷函数
# ============================================================================

def build_stock_code_set(
    fetcher: DataFetcher,
    config: dict,
    stock_df: Optional[pd.DataFrame] = None,
) -> List[str]:
    """
    根据配置构建待选股票池代码列表。
    
    处理:
      - 交易所过滤
      - ST 剔除
      - 次新股剔除（上市不足 N 天）
      - 测试模式：仅返回前 N 只
    """
    df = stock_df.copy() if stock_df is not None else fetcher.fetch_stock_list()
    if df.empty:
        return []
    
    pool_config = config.get("stock_pool", {})
    exclude_st = pool_config.get("exclude_st", {}).get("enabled", True)
    exclude_ipo_days = pool_config.get("exclude_ipo_within_days", 60)
    include_exchanges = pool_config.get("include_exchanges", [])
    test_mode = pool_config.get("test_mode", False)
    
    # 交易所过滤
    exchange_map = {"SZSE": "SZ", "SSE": "SH", "BSE": "BJ"}
    if include_exchanges:
        wanted = [exchange_map.get(ex) for ex in include_exchanges if ex in exchange_map]
        df = df[df["ts_code"].str.endswith(tuple(f".{w}" for w in wanted))]
    
    # 仅保留上市股票（L 状态）
    df = df[df["list_status"] == "L"].copy()
    
    if exclude_st and "name" in df.columns:
        before = len(df)
        df = df[~df["name"].fillna("").str.upper().str.contains("ST")].copy()
        logger.info(f"ST 股票过滤: {before - len(df)} 只")

    if exclude_ipo_days and "list_date" in df.columns:
        list_dates = pd.to_datetime(df["list_date"], errors="coerce")
        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(
            days=exclude_ipo_days
        )
        known_date = list_dates.notna()
        df = df[~known_date | (list_dates <= cutoff)].copy()

    ts_codes = df["ts_code"].tolist()
    
    # 测试模式：仅返回前 5 只
    if test_mode:
        ts_codes = ts_codes[:5]
        logger.info(f"测试模式: 仅处理前 {len(ts_codes)} 只股票")
        return ts_codes
    
    logger.info(f"初步股票池: {len(ts_codes)} 只")
    
    return ts_codes
