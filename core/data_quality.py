"""
AI 量化数据流水线 — 数据质量监控模块
======================================

职责:
  1. 每日自动生成数据质量报告
  2. 检测数据缺失、异常值、停牌比例
  3. 监控数据延迟（判断数据是否为当日）
  4. 生成适合飞书/Telegram 推送的格式化报告

使用方式:
  from core.data_quality import QualityMonitor
  qm = QualityMonitor(db, config)
  report = qm.generate_daily_report("2024-06-15")
  print(qm.format_for_feishu(report))
"""

import json
from typing import Dict, Any
from datetime import datetime

import pandas as pd
from loguru import logger


class QualityMonitor:
    """
    数据质量监控器。
    
    每日调用 generate_daily_report() 生成报告，
    可通过 format_for_feishu() / format_for_telegram() 格式化输出。
    """

    def __init__(self, db, config: dict):
        """
        Args:
            db: QuantDB 实例
            config: 全局配置 dict
        """
        self.db = db
        self.config = config
        quality_cfg = config.get("quality", {})
        self.alerts = quality_cfg.get("alerts", {})
        self.known_missing_fields = set(
            quality_cfg.get("known_missing_fields", [])
        )

    def generate_daily_report(self, trade_date: str = None) -> Dict[str, Any]:
        """
        生成某交易日的质量报告。
        
        Args:
            trade_date: 交易日（YYYY-MM-DD），默认最近一个交易日
            
        Returns:
            报告 dict:
            {
                "date": "2024-06-15",
                "stock_count": 5000,
                "missing_rate": {"close": 0.01, ...},
                "extreme_stats": {"pct_chg": {"count": 5, "ratio": 0.001}, ...},
                "suspension_count": 50,
                "date_range": {...},
                "anomalies": [...],
                "status": "normal" | "warning" | "critical",
            }
        """
        if trade_date is None:
            # 取最近交易日
            recent = self.db.query_recent_trade_dates(1)
            if recent.empty:
                return self._empty_report("无可用交易日")
            trade_date = str(recent.iloc[0].date())
        
        report = {
            "date": trade_date,
            "generated_at": datetime.now().isoformat(),
            "stock_count": 0,
            "missing_rate": {},
            "extreme_stats": {},
            "suspension_count": 0,
            "suspension_ratio": 0.0,
            "invalid_ohlc_count": 0,
            "date_range": {},
            "anomalies": [],
            "status": "normal",
        }
        
        try:
            # 1. 获取该日截面数据
            df = self._get_cross_section(trade_date)
            if df.empty:
                report["anomalies"].append(f"交易日 {trade_date} 无可用数据")
                report["status"] = "critical"
                report["quality_score"] = 0
                if (
                    self.config.get("quality", {})
                    .get("report", {})
                    .get("save_raw", True)
                ):
                    self._save_raw_report(trade_date, report)
                return report
            
            report["stock_count"] = len(df)
            
            # 2. 缺失率统计
            missing = self._calc_missing_rates(df)
            report["missing_rate"] = missing
            
            # 3. 极端值统计
            extreme = self._calc_extreme_stats(df)
            report["extreme_stats"] = extreme
            
            # 4. 停牌统计
            if "flag_suspended" in df.columns:
                suspended = df["flag_suspended"].fillna(False).sum()
                report["suspension_count"] = int(suspended)
                report["suspension_ratio"] = round(suspended / len(df), 4) if len(df) > 0 else 0.0

            if "flag_invalid_ohlc" in df.columns:
                report["invalid_ohlc_count"] = int(
                    df["flag_invalid_ohlc"].fillna(False).sum()
                )
            
            # 5. 数据日期范围
            report["date_range"] = self._get_date_range()
            
            # 6. 异常检测
            report["anomalies"] = self._detect_anomalies(df, report)
            
            # 7. 综合状态
            report["status"] = self._assess_status(report)
            
            # 8. 质量得分（0-100）
            report["quality_score"] = self._calc_quality_score(report)
            
        except Exception as e:
            logger.error(f"质量报告生成失败: {e}")
            report["anomalies"].append(f"报告生成异常: {str(e)}")
            report["status"] = "critical"
        
        # 保存原始报告（可选）
        if self.config.get("quality", {}).get("report", {}).get("save_raw", True):
            self._save_raw_report(trade_date, report)
        
        return report

    def format_for_feishu(self, report: Dict[str, Any]) -> str:
        """
        格式化为飞书消息（不支持表格，用标注列表替代）。
        
        格式规范:
          - **加粗** 替代标题
          - 列表项用 - 
          - 不用 # 和 ---
        """
        status_emoji = {
            "normal": "✅",
            "warning": "⚠️",
            "critical": "🚨",
        }
        emoji = status_emoji.get(report["status"], "❓")
        
        lines = [
            f"{emoji} **数据质量报告 - {report['date']}**",
            "",
            f"**📊 数据概况**",
            f"- 有数据股票: {report['stock_count']} 只",
            f"- 停牌股票: {report['suspension_count']} 只 ({report['suspension_ratio']*100:.1f}%)",
            f"- 质量得分: {report.get('quality_score', 'N/A')}/100",
            f"- 整体状态: {report['status'].upper()}",
            "",
        ]
        
        # 缺失率
        if report["missing_rate"]:
            lines.append(f"**📉 缺失率 TOP 5**")
            sorted_missing = sorted(
                report["missing_rate"].items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            for col, rate in sorted_missing:
                bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
                lines.append(f"- {col}: {rate*100:.2f}% {bar}")
            lines.append("")
        
        # 极端值
        if report["extreme_stats"]:
            lines.append(f"**🔥 极端值统计**")
            for col, stats in report["extreme_stats"].items():
                lines.append(f"- {col}: {stats['count']} 个 ({stats['ratio']*100:.2f}%)")
            lines.append("")
        
        # 异常项
        if report["anomalies"]:
            lines.append(f"**🚨 异常项 ({len(report['anomalies'])})**")
            for anomaly in report["anomalies"]:
                lines.append(f"- {anomaly}")
            lines.append("")
        
        # 时间戳
        lines.append(f"🕐 {report['generated_at']}")
        
        return "\n".join(lines)

    def format_summary_line(self, report: Dict[str, Any]) -> str:
        """生成一行摘要（用于推送标题）"""
        score = report.get("quality_score", 0)
        status = report["status"]
        emoji = {"normal": "✅", "warning": "⚠️", "critical": "🚨"}.get(status, "❓")
        anomalies = len(report.get("anomalies", []))
        return (
            f"{emoji} 数据质量 | {report['date']} | "
            f"股票 {report['stock_count']} | "
            f"得分 {score} | "
            f"异常 {anomalies} 项 | "
            f"状态 {status}"
        )

    # ========================================================================
    # 内部方法
    # ========================================================================

    def _get_cross_section(self, trade_date: str) -> pd.DataFrame:
        """获取某日截面数据"""
        try:
            return self.db.query_cross_section(trade_date)
        except Exception as e:
            logger.error(f"截面查询失败 {trade_date}: {e}")
            return pd.DataFrame()

    def _calc_missing_rates(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算各字段缺失率"""
        missing = {}
        key_cols = [
            "open", "high", "low", "close", "vol", "amount",
            "adj_factor", "flag_suspended",
        ]
        daily_basic_enabled = (
            self.config.get("fetch", {})
            .get("market_data", {})
            .get("daily_basic", False)
            and bool(
                self.config.get("data_source", {}).get("tushare_token")
            )
        )
        if daily_basic_enabled:
            key_cols.extend(["pe", "pb", "turnover_rate"])
        for col in key_cols:
            if col in self.known_missing_fields:
                continue
            if col in df.columns:
                rate = df[col].isna().mean()
                if rate > 0:
                    missing[col] = round(rate, 4)
        return missing

    def _calc_extreme_stats(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """统计极端值"""
        stats = {}
        if "pct_chg" in df.columns:
            pct = df["pct_chg"].dropna()
            # 单日涨跌幅超过 ±15%
            extreme = pct[(pct.abs() >= 15) & (pct.abs() < 100)]
            if not extreme.empty:
                stats["pct_chg"] = {
                    "count": int(len(extreme)),
                    "ratio": round(len(extreme) / len(pct), 4),
                    "min": round(pct.min(), 2),
                    "max": round(pct.max(), 2),
                }
        return stats

    def _get_date_range(self) -> Dict[str, str]:
        """获取数据库中的数据日期范围"""
        try:
            result = self.db.conn.execute("""
                SELECT MIN(trade_date), MAX(trade_date)
                FROM daily_kline
            """).fetchone()
            return {
                "min": str(result[0]) if result[0] else None,
                "max": str(result[1]) if result[1] else None,
            }
        except Exception:
            return {"min": None, "max": None}

    def _detect_anomalies(self, df: pd.DataFrame, report: Dict) -> list:
        """检测异常，生成可读的异常列表"""
        anomalies = []
        
        # 1. 数据量过少
        if report["stock_count"] < 1000:
            anomalies.append(f"有数据股票仅 {report['stock_count']} 只（< 1000）")
        
        # 2. 缺失率过高
        missing_threshold = self.alerts.get("missing_data_ratio", 0.05)
        for col, rate in report.get("missing_rate", {}).items():
            if rate > missing_threshold:
                anomalies.append(f"{col} 缺失率 {rate*100:.1f}%（阈值 {missing_threshold*100:.0f}%）")
        
        # 3. 极端值过多
        extreme_threshold = self.alerts.get("extreme_stocks_ratio", 0.02)
        for col, stats in report.get("extreme_stats", {}).items():
            if stats["ratio"] > extreme_threshold:
                anomalies.append(
                    f"{col} 极端值 {stats['count']} 个 ({stats['ratio']*100:.2f}%)"
                )
        
        # 4. 停牌比例异常
        susp_ratio = report.get("suspension_ratio", 0)
        if susp_ratio > 0.15:
            anomalies.append(f"停牌比例 {susp_ratio*100:.1f}%（异常偏高）")

        invalid_ohlc = report.get("invalid_ohlc_count", 0)
        if invalid_ohlc:
            anomalies.append(f"OHLC 关系非法 {invalid_ohlc} 条")
        
        # 5. 数据延迟检测
        report_date = datetime.strptime(report["date"], "%Y-%m-%d").date()
        today = datetime.now().date()
        if (today - report_date).days > 3:
            anomalies.append(f"数据延迟 {(today - report_date).days} 天（最新 {report['date']}）")
        
        return anomalies

    def _assess_status(self, report: Dict) -> str:
        """综合评估数据质量状态"""
        anomalies = report.get("anomalies", [])
        critical_count = 0
        warning_count = 0
        
        for a in anomalies:
            # 简单 heuristic: 包含关键字段缺失、数据量为零等关键词的为 critical
            critical_keywords = ["仅", "无", "0 只", "不可用"]
            if any(kw in a for kw in critical_keywords):
                critical_count += 1
            else:
                warning_count += 1
        
        if critical_count > 0:
            return "critical"
        elif warning_count > 0:
            return "warning"
        return "normal"

    def _calc_quality_score(self, report: Dict) -> int:
        """计算质量得分（0-100）"""
        score = 100.0
        
        # 扣分：缺失率
        for col, rate in report.get("missing_rate", {}).items():
            score -= rate * 100 * 2  # 每 1% 缺失扣 2 分
        
        # 扣分：极端值
        for col, stats in report.get("extreme_stats", {}).items():
            score -= stats["ratio"] * 100 * 5  # 每 1% 极端值扣 5 分
        
        # 扣分：异常项
        score -= len(report.get("anomalies", [])) * 5  # 每个异常扣 5 分
        
        # 扣分：停牌
        score -= report.get("suspension_ratio", 0) * 100 * 2
        
        return max(0, min(100, int(score)))

    def _empty_report(self, reason: str) -> Dict:
        """返回空白报告"""
        return {
            "date": str(datetime.now().date()),
            "generated_at": datetime.now().isoformat(),
            "stock_count": 0,
            "missing_rate": {},
            "extreme_stats": {},
            "suspension_count": 0,
            "suspension_ratio": 0.0,
            "invalid_ohlc_count": 0,
            "date_range": {},
            "anomalies": [f"数据不可用: {reason}"],
            "status": "critical",
            "quality_score": 0,
        }

    def _save_raw_report(self, trade_date: str, report: Dict):
        """保存原始质量报告为 JSON"""
        try:
            report_dir = "./data/quality_reports"
            import os
            os.makedirs(report_dir, exist_ok=True)
            path = f"{report_dir}/{trade_date}.json"
            with open(path, "w") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.debug(f"质量报告已保存: {path}")
        except Exception as e:
            logger.warning(f"保存质量报告失败: {e}")
