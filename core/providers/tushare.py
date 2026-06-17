import pandas as pd


class TushareClient:
    """Tushare Pro adapter with pipeline-level field normalization."""

    def __init__(self, pro_api, rate_limit=None):
        self.pro_api = pro_api
        self.rate_limit = rate_limit or (lambda: None)

    def _wait(self):
        self.rate_limit()

    def fetch_stock_list(self) -> pd.DataFrame:
        """Fetch listed and delisted A-share metadata."""
        self._wait()
        fields = (
            "ts_code,symbol,name,area,industry,list_date,delist_date,"
            "market,exchange"
        )
        listed = self.pro_api.stock_basic(
            exchange="",
            list_status="L",
            fields=fields,
        )
        delisted = self.pro_api.stock_basic(
            exchange="",
            list_status="D",
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

    def fetch_daily_kline(
        self, ts_code: str, start: str, end: str
    ) -> pd.DataFrame:
        """Fetch daily K-line and convert Tushare amount from thousand yuan."""
        self._wait()
        df = self.pro_api.daily(
            ts_code=ts_code,
            start_date=start,
            end_date=end,
        )
        if df.empty:
            return df

        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.sort_values("trade_date").reset_index(drop=True)

    def fetch_adj_factor(self, ts_code: str) -> pd.DataFrame:
        """Fetch adjustment factors."""
        self._wait()
        df = self.pro_api.adj_factor(ts_code=ts_code)
        if df.empty:
            return df
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def fetch_trade_calendar(self, year: int) -> pd.DataFrame:
        """Fetch trade calendar for one year."""
        self._wait()
        df = self.pro_api.trade_cal(
            start_date=f"{year}0101",
            end_date=f"{year}1231",
        )
        if df.empty:
            return df
        df["trade_date"] = pd.to_datetime(df["cal_date"])
        df["is_open"] = df["is_open"].astype(int)
        return df

    def fetch_daily_basic(self, trade_date: str) -> pd.DataFrame:
        """Fetch market-wide daily valuation and turnover fields."""
        self._wait()
        df = self.pro_api.daily_basic(
            trade_date=trade_date,
            fields=(
                "ts_code,trade_date,pe,pb,turnover_rate,volume_ratio,"
                "circ_mv,total_mv"
            ),
        )
        if df.empty:
            return df
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def fetch_financial_indicators(
        self, ts_code: str, start: str, end: str
    ) -> pd.DataFrame:
        """Fetch quarterly financial indicators aligned by announcement date."""
        self._wait()
        df = self.pro_api.fina_indicator(
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
        df = df.rename(columns={"dt_debt_to_assets": "dt_debt_ratio"})
        return df.sort_values("ann_date").reset_index(drop=True)

    def fetch_name_history(self, ts_code: str) -> pd.DataFrame:
        """Fetch stock name history and mark historical ST periods."""
        self._wait()
        df = self.pro_api.namechange(
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
        return df.sort_values("start_date").reset_index(drop=True)
