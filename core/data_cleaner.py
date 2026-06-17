"""
AI 量化数据流水线 — 数据清洗模块
===================================

职责:
  1. 去重与排序
  2. 交易日历对齐（填补节假日缺口）
  3. 停牌处理（成交量=0 时价格前向填充）
  4. 复权计算（前复权 / 后复权）
  5. 异常值检测与标记（不改写原始行情）
  6. ST/*ST 标记剔除
  7. 缺失值处理

使用方式:
  from core.data_cleaner import DataCleaner
  cleaner = DataCleaner(config)
  df_clean = cleaner.clean_kline(df_raw)
  df_clean = cleaner.adjust_price(df, adj_df, method="hfq")
"""

import pandas as pd
import numpy as np
from loguru import logger


# ============================================================================
# 异常值检测器
# ============================================================================

class OutlierDetector:
    """
    离群值检测器，支持三种主流方法。
    
    MAD 法（推荐）:
      比 Z-Score 更稳健，对极端值不敏感。
      阈值 5 意味着: 超过中位数 ± 5 × MAD 的值被标记。
      对于正态分布，这大约相当于 ±3.35σ。
    
    Z-Score 法:
      传统的标准化方法，但对极端值本身敏感（掩盖效应）。
      阈值 3 意味着: 超过均值 ± 3σ 的值被标记。
    
    IQR 法:
      基于四分位距，适合偏态分布。
      倍数 1.5 意味着: 超过 Q1 - 1.5×IQR 或 Q3 + 1.5×IQR 的值被标记。
    """

    def __init__(self, method: str = "mad", mad_threshold: float = 5.0,
                 zscore_threshold: float = 3.0, iqr_multiplier: float = 1.5):
        """
        Args:
            method: "mad" | "zscore" | "iqr"
            mad_threshold: MAD 倍数
            zscore_threshold: Z-Score 阈值
            iqr_multiplier: IQR 倍数
        """
        self.method = method
        self.mad_threshold = mad_threshold
        self.zscore_threshold = zscore_threshold
        self.iqr_multiplier = iqr_multiplier

    def detect(self, series: pd.Series) -> pd.Series:
        """
        返回布尔 Series，True = 异常值。
        
        Args:
            series: 输入数据
            
        Returns:
            布尔掩码（True = 异常值）
        """
        series = series.dropna()
        if len(series) < 10:
            # 数据太少时不做检测
            return pd.Series(False, index=series.index)
        
        if self.method == "mad":
            return self._mad(series)
        elif self.method == "zscore":
            return self._zscore(series)
        elif self.method == "iqr":
            return self._iqr(series)
        else:
            logger.warning(f"未知异常检测方法 {self.method}，使用 MAD")
            return self._mad(series)

    def clip(self, series: pd.Series) -> pd.Series:
        """
        截断（Winsorize）异常值到边界值，而非删除。
        
        对于时序数据，截断优于删除 — 因为删除会破坏时间连续性。
        """
        series = series.copy()
        
        if self.method == "mad":
            median = series.median()
            mad = (series - median).abs().median()
            if mad == 0:
                return series
            lower = median - self.mad_threshold * mad
            upper = median + self.mad_threshold * mad
        elif self.method == "zscore":
            mean = series.mean()
            std = series.std()
            if std == 0:
                return series
            lower = mean - self.zscore_threshold * std
            upper = mean + self.zscore_threshold * std
        elif self.method == "iqr":
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                return series
            lower = q1 - self.iqr_multiplier * iqr
            upper = q3 + self.iqr_multiplier * iqr
        else:
            return series
        
        return series.clip(lower=lower, upper=upper)

    def _mad(self, series: pd.Series) -> pd.Series:
        """MAD（Median Absolute Deviation）检测"""
        median = series.median()
        mad = (series - median).abs().median()
        if mad == 0:
            return pd.Series(False, index=series.index)
        deviation = (series - median).abs() / mad
        return deviation > self.mad_threshold

    def _zscore(self, series: pd.Series) -> pd.Series:
        """Z-Score 检测"""
        mean = series.mean()
        std = series.std()
        if std == 0:
            return pd.Series(False, index=series.index)
        z = (series - mean).abs() / std
        return z > self.zscore_threshold

    def _iqr(self, series: pd.Series) -> pd.Series:
        """IQR 检测"""
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            return pd.Series(False, index=series.index)
        return (series < q1 - self.iqr_multiplier * iqr) | (
            series > q3 + self.iqr_multiplier * iqr
        )


# ============================================================================
# 主清洗类
# ============================================================================

class DataCleaner:
    """
    数据清洗器 — 将原始日K线数据清洗为标准化的干净数据。
    
    处理流程:
      raw_data
        → deduplicate (去重)
        → sort (排序)
        → align_calendar (对齐交易日历)
        → handle_suspension (处理停牌)
        → adjust_price (复权)
        → mark_extreme (标记极端值)
        → fill_missing (填充缺失)
        → clean_data
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 全局配置 dict（从 config.yaml 加载）
        """
        clean_cfg = config.get("cleaning", {})
        self.max_daily_pct = clean_cfg.get("max_daily_pct", 15.0)
        self.min_trading_days = clean_cfg.get("min_trading_days", 20)
        
        # 异常检测器
        method = clean_cfg.get("outlier_method", "mad")
        self.outlier_detector = OutlierDetector(
            method=method,
            mad_threshold=clean_cfg.get("mad_threshold", 5.0),
            zscore_threshold=clean_cfg.get("zscore_threshold", 3.0),
            iqr_multiplier=clean_cfg.get("iqr_multiplier", 1.5),
        )

    def clean_kline(
        self,
        df: pd.DataFrame,
        trade_calendar: pd.Series = None,
    ) -> pd.DataFrame:
        """
        清洗单只股票的日K线数据。
        
        Args:
            df: 原始K线 DataFrame（必须含 trade_date, open, high, low, close, vol, amount）
            trade_calendar: 交易日历 Series（交易日期的 pd.DatetimeIndex），可选
            
        Returns:
            清洗后的 DataFrame，增加字段:
              - adj_close / adj_open / adj_high / adj_low（复权价格）
              - flag_extreme（极端值标记）
              - flag_suspended（停牌标记）
              - pct_chg（日收益率 %）
        """
        if df.empty:
            return df
        
        df = df.copy()
        
        # Step 1: 去重
        df = self._deduplicate(df)
        
        # Step 2: 排序
        df = self._sort(df)
        
        # Step 3: 处理无穷/NA 值
        df = self._clean_numeric(df)
        
        # Step 4: 按交易日历对齐（可选）
        if trade_calendar is not None and not trade_calendar.empty:
            df = self._align_calendar(df, trade_calendar)
        
        # Step 5: 缺失值处理
        df = self._fill_missing(df)
        
        # Step 6: 停牌、收益率和异常标记
        df = self._mark_suspension(df)
        df = self._calc_returns(df)
        if "flag_aligned" in df.columns:
            aligned = df["flag_aligned"].fillna(False)
            df.loc[aligned, ["pct_chg", "log_ret"]] = 0.0
        df = self._mark_extreme_daily(df)
        df = self._mark_invalid_ohlc(df)

        # 数据采集层保留短历史股票，因子层再按 min_trading_days 过滤
        if "ts_code" in df.columns and len(df) < self.min_trading_days:
            logger.debug(f"{df['ts_code'].iloc[0]} 交易天数不足 {self.min_trading_days}")
        
        return df

    def adjust_price(
        self,
        df: pd.DataFrame,
        adj_factor_df: pd.DataFrame,
        method: str = "hfq",
    ) -> pd.DataFrame:
        """
        对日K线进行复权处理。
        
        复权方式说明:
          - 后复权 (hfq): 价格连续，不会出现负值。早期价格看起来很高，
            因子计算时推荐使用。
          - 前复权 (qfq): 最新价格等于实际价格，历史价格按比例缩放。
            回测时推荐使用，更贴近真实交易场景。
          - 不复权 (none): 原始价格，有除权除息跳空。
            实盘信号生成时使用，配合除权日特殊处理。
        
        Args:
            df: K线 DataFrame（需含 trade_date 列）
            adj_factor_df: 复权因子 DataFrame（需含 trade_date, adj_factor 列）
            method: "hfq" | "qfq" | "none"
            
        Returns:
            复权后的 DataFrame（新增 adj_close, adj_open, adj_high, adj_low 列）
        """
        if method == "none":
            df["adj_close"] = df["close"]
            df["adj_open"] = df["open"]
            df["adj_high"] = df["high"]
            df["adj_low"] = df["low"]
            if "adj_factor" not in df.columns:
                df["adj_factor"] = np.nan
            return df

        if adj_factor_df is None or adj_factor_df.empty:
            logger.warning(f"缺少复权因子，无法计算 {method} 价格")
            for col in ["open", "high", "low", "close"]:
                df[f"adj_{col}"] = np.nan
            if "adj_factor" not in df.columns:
                df["adj_factor"] = np.nan
            return df
        
        # 合并复权因子
        adj = adj_factor_df[["trade_date", "adj_factor"]].copy()
        adj["trade_date"] = pd.to_datetime(adj["trade_date"])
        
        df = df.drop(columns=["adj_factor"], errors="ignore")
        df = df.merge(adj, on="trade_date", how="left")
        
        # 前向填充缺失的复权因子
        df["adj_factor"] = df["adj_factor"].ffill().bfill()
        
        if method == "hfq":
            # 后复权：以首日为基准，当前价格随累计复权因子增长
            first_factor = df["adj_factor"].iloc[0]
            for col in ["open", "high", "low", "close"]:
                df[f"adj_{col}"] = df[col] * df["adj_factor"] / first_factor
                
        elif method == "qfq":
            # 前复权：以最新日为基准，最新价格保持实际值
            latest_factor = df["adj_factor"].iloc[-1]
            for col in ["open", "high", "low", "close"]:
                df[f"adj_{col}"] = df[col] * df["adj_factor"] / latest_factor
        else:
            logger.warning(f"未知复权方法 {method}，使用后复权")
            return self.adjust_price(df, adj_factor_df, "hfq")
        
        return df

    def flag_st_stocks(self, df: pd.DataFrame, st_list: list = None) -> pd.Series:
        """
        根据股票代码列表标记 ST / *ST。
        
        在因子计算时应当排除 ST 股票，因为它们的数据在
        涨跌幅限制（5%）和流动性上有系统性差异。
        
        Args:
            df: K线 DataFrame
            st_list: ST 股票代码列表（可从 AKShare 获取实时列表）
            
        Returns:
            Boolean Series, True = ST 股票
        """
        if st_list is None:
            return pd.Series(False, index=df.index)
        
        return df["ts_code"].isin(st_list)

    # ========================================================================
    # 内部方法
    # ========================================================================

    def _deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """去重：同一只股票同一天只有一条数据"""
        before = len(df)
        df = df.drop_duplicates(subset=["ts_code", "trade_date"] if "ts_code" in df.columns else ["trade_date"])
        after = len(df)
        if before != after:
            logger.debug(f"去重: {before} -> {after} 行")
        return df

    def _sort(self, df: pd.DataFrame) -> pd.DataFrame:
        """按日期排序"""
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def _calc_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算日收益率"""
        if "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100  # 百分比
            df["log_ret"] = np.log(df["close"] / df["close"].shift(1))  # 对数收益率
        return df

    def _mark_extreme_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """标记单日涨跌幅超过阈值的极端值"""
        df["flag_extreme"] = False
        if "pct_chg" in df.columns:
            df.loc[df["pct_chg"].abs() > self.max_daily_pct, "flag_extreme"] = True
        return df

    def _mark_invalid_ohlc(self, df: pd.DataFrame) -> pd.DataFrame:
        """标记违反 OHLC 关系的数据，但不修改供应商原始价格。"""
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            return df
        invalid = (
            (df["high"] < df[["open", "close", "low"]].max(axis=1))
            | (df["low"] > df[["open", "close", "high"]].min(axis=1))
            | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        )
        df["flag_invalid_ohlc"] = invalid.fillna(True)
        df.loc[df["flag_invalid_ohlc"], "flag_extreme"] = True
        return df

    def _mark_suspension(self, df: pd.DataFrame) -> pd.DataFrame:
        """标记停牌：当日成交量为 0 或 NaN"""
        df["flag_suspended"] = False
        if "vol" in df.columns:
            df.loc[df["vol"].fillna(0) == 0, "flag_suspended"] = True
        return df

    def _clean_numeric(self, df: pd.DataFrame) -> pd.DataFrame:
        """清理无穷值和极端 NA"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
        return df

    def _align_calendar(self, df: pd.DataFrame, trade_calendar: pd.Series) -> pd.DataFrame:
        """
        按交易日历对齐数据。
        
        停牌日的处理:
          - 成交量 (vol)、成交额 (amount) → 0
          - 价格 (open/high/low/close) → 前向填充
          - 涨跌幅 (pct_chg) → 0
          - 标记 flag_aligned=True
        """
        if "trade_date" not in df.columns:
            return df
        
        df = df.set_index("trade_date")
        
        # 找到在交易日历范围内的数据
        cal = trade_calendar[
            (trade_calendar >= df.index.min()) & (trade_calendar <= df.index.max())
        ]
        
        if cal.empty:
            df = df.reset_index()
            return df
        
        # reindex 到交易日历
        df_aligned = df.reindex(cal)
        
        price_cols = ["open", "high", "low", "close"]
        # 新增对齐标记
        df_aligned["flag_aligned"] = df_aligned["close"].isna()
        
        # 价格前向填充（停牌日沿用前一日价格）
        for col in price_cols:
            if col in df_aligned.columns:
                df_aligned[col] = df_aligned[col].ffill()
        
        # 仅对补出的停牌行写 0，供应商未提供的字段继续保持缺失
        aligned = df_aligned["flag_aligned"]
        if "vol" in df_aligned.columns:
            df_aligned.loc[aligned, "vol"] = 0
        if "amount" in df_aligned.columns:
            df_aligned.loc[aligned, "amount"] = 0

        if "ts_code" in df_aligned.columns:
            df_aligned["ts_code"] = df_aligned["ts_code"].ffill().bfill()

        df_aligned["flag_suspended"] = df_aligned["flag_aligned"]
        df_aligned["flag_extreme"] = False
        
        df_aligned = df_aligned.reset_index().rename(columns={"index": "trade_date"})
        
        return df_aligned

    def _fill_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """填充缺失值"""
        # 价格类：前向填充
        for col in [
            "open", "high", "low", "close",
            "adj_close", "adj_open", "adj_high", "adj_low",
            "raw_open", "raw_high", "raw_low", "raw_close",
        ]:
            if col in df.columns:
                df[col] = df[col].ffill()
        
        return df


# ============================================================================
# 便捷函数
# ============================================================================

def build_trade_calendar(fetcher, config: dict, years: list = None) -> pd.DatetimeIndex:
    """
    构建交易日历 Index。
    
    Args:
        fetcher: DataFetcher 实例
        config: 全局配置
        years: 需要的年份列表，默认自动推断
    
    Returns:
        pd.DatetimeIndex，仅含交易日
    """
    if years is None:
        fetch_cfg = config.get("fetch", {})
        start_raw = str(fetch_cfg.get("start_date", "20231001")).replace("-", "")
        end_raw = str(fetch_cfg.get("end_date", "today")).replace("-", "")
        if end_raw.lower() == "today":
            end = pd.Timestamp.today()
        else:
            end = pd.Timestamp(end_raw)
        start = pd.Timestamp(start_raw)
        years = list(range(start.year, end.year + 1))
    
    all_dates = []
    for year in years:
        cal = fetcher.fetch_trade_calendar(year)
        if not cal.empty:
            trade_dates = cal[cal["is_open"] == 1]["trade_date"]
            all_dates.append(trade_dates)
    
    if not all_dates:
        logger.warning("无法构建交易日历，返回空 Index")
        return pd.DatetimeIndex([])
    
    combined = pd.concat(all_dates, ignore_index=True)
    return pd.DatetimeIndex(combined.sort_values().unique())
