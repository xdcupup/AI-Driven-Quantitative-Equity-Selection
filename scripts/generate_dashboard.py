#!/usr/bin/env python3
"""
生成 TradingView 风格量化看板 HTML。
从 DuckDB 拉取实时数据，嵌入到自包含 HTML 中。
"""

import duckdb
import json
from datetime import datetime, date

DB_PATH = "./data/quant.duckdb"
OUTPUT_PATH = "./docs/dashboard.html"


def query_data():
    con = duckdb.connect(DB_PATH)

    # 最新交易日
    latest = con.execute("SELECT MAX(trade_date) FROM daily_kline").fetchone()[0]
    latest_str = str(latest) if latest else str(date.today())

    # 全市场最新截面（日K线）
    cross = con.execute(f"""
        SELECT k.ts_code, s.name, k.close, k.pct_chg, k.vol, k.amount,
               k.open, k.high, k.low, k.trade_date
        FROM daily_kline k
        JOIN stock_list s ON k.ts_code = s.ts_code
        WHERE k.trade_date = '{latest_str}'
          AND k.close > 0
        ORDER BY k.vol DESC
        LIMIT 50
    """).fetchdf()

    # K线数据（默认展示成交额最大的股票）
    default_code = cross.iloc[0]["ts_code"] if not cross.empty else "000001.SZ"
    kline = con.execute(f"""
        SELECT trade_date, open, high, low, close, vol, amount
        FROM daily_kline
        WHERE ts_code = '{default_code}'
        ORDER BY trade_date
    """).fetchdf()

    con.close()
    return cross, kline, default_code, latest_str


def build_html(cross, kline, default_code, latest_str):
    # 序列化数据
    stocks_json = json.dumps([
        {"code": r["ts_code"], "name": r["name"], "close": float(r["close"]),
         "pct": round(float(r["pct_chg"]), 2) if r["pct_chg"] else 0.0, "vol": float(r["vol"])}
        for _, r in cross.iterrows()
    ], ensure_ascii=False)

    kline_json = json.dumps([
        {"time": str(r["trade_date"])[:10], "open": float(r["open"]),
         "high": float(r["high"]), "low": float(r["low"]),
         "close": float(r["close"]), "volume": float(r["vol"])}
        for _, r in kline.iterrows()
    ])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alpha Trader — AI 量化仪表盘</title>
<script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg-primary: #131722; --bg-secondary: #1e222d; --bg-tertiary: #2a2e39;
  --text-primary: #d1d4dc; --text-secondary: #787b86; --text-positive: #089981;
  --text-negative: #f23645; --border: #2a2e39; --accent: #2962ff;
  --accent-hover: #1e4bd8;
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-primary); color: var(--text-primary); font-size: 13px; overflow: hidden; height: 100vh; }}
.layout {{ display: grid; grid-template-columns: 280px 1fr 300px; grid-template-rows: auto 1fr; height: 100vh; }}

/* === Header === */
.header {{ grid-column: 1 / -1; background: var(--bg-secondary); border-bottom: 1px solid var(--border); padding: 8px 16px; display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 16px; font-weight: 600; color: var(--text-primary); }}
.header h1 span {{ color: var(--accent); }}
.header-time {{ color: var(--text-secondary); font-size: 12px; }}
.header-actions {{ display: flex; gap: 8px; }}
.btn {{ padding: 6px 14px; border-radius: 4px; border: none; cursor: pointer; font-size: 12px; font-weight: 500; }}
.btn-primary {{ background: var(--accent); color: #fff; }}
.btn-primary:hover {{ background: var(--accent-hover); }}
.btn-secondary {{ background: var(--bg-tertiary); color: var(--text-primary); }}
.btn-secondary:hover {{ background: #3a3e49; }}

/* === Watchlist (Sidebar Left) === */
.watchlist {{ background: var(--bg-secondary); border-right: 1px solid var(--border); overflow-y: auto; }}
.watchlist-header {{ padding: 12px 12px 8px; border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.5px; display: flex; justify-content: space-between; }}
.watchlist-search {{ padding: 8px 12px; }}
.watchlist-search input {{ width: 100%; padding: 6px 10px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 4px; color: var(--text-primary); font-size: 12px; outline: none; }}
.watchlist-search input:focus {{ border-color: var(--accent); }}
.watchlist-item {{ display: grid; grid-template-columns: 1fr auto auto; gap: 8px; padding: 8px 12px; cursor: pointer; border-left: 3px solid transparent; transition: background 0.15s; align-items: center; }}
.watchlist-item:hover {{ background: var(--bg-tertiary); }}
.watchlist-item.active {{ border-left-color: var(--accent); background: rgba(41,98,255,0.08); }}
.watchlist-code {{ font-weight: 500; font-size: 13px; }}
.watchlist-name {{ font-size: 11px; color: var(--text-secondary); }}
.watchlist-price {{ text-align: right; font-weight: 500; }}
.watchlist-pct {{ text-align: right; font-size: 12px; font-weight: 500; min-width: 60px; }}
.positive {{ color: var(--text-positive); }}
.negative {{ color: var(--text-negative); }}
.neutral {{ color: var(--text-secondary); }}

/* === Chart Area === */
.chart-area {{ position: relative; }}
.chart-toolbar {{ padding: 8px 16px; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid var(--border); background: var(--bg-primary); }}
.chart-toolbar .stock-label {{ font-size: 18px; font-weight: 600; }}
.chart-toolbar .stock-price {{ font-size: 22px; font-weight: 700; margin-left: 16px; }}
.chart-toolbar .stock-change {{ font-size: 14px; margin-left: 8px; }}
.chart-toolbar .timeframe {{ display: flex; gap: 4px; margin-left: auto; }}
.chart-toolbar .timeframe button {{ padding: 4px 10px; background: transparent; border: 1px solid transparent; border-radius: 4px; color: var(--text-secondary); cursor: pointer; font-size: 12px; }}
.chart-toolbar .timeframe button:hover,.chart-toolbar .timeframe button.active {{ color: var(--text-primary); border-color: var(--border); background: var(--bg-tertiary); }}
#chart {{ width: 100%; height: calc(100% - 48px); }}

/* === Info Panel (Sidebar Right) === */
.info-panel {{ background: var(--bg-secondary); border-left: 1px solid var(--border); overflow-y: auto; }}
.info-header {{ padding: 12px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }}
.info-header h3 {{ font-size: 13px; font-weight: 500; }}
.info-section {{ padding: 12px; border-bottom: 1px solid var(--border); }}
.info-section h4 {{ font-size: 11px; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.5px; margin-bottom: 8px; }}
.info-row {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }}
.info-label {{ color: var(--text-secondary); }}
.info-value {{ font-weight: 500; }}
.info-value.positive {{ color: var(--text-positive); }}
.info-value.negative {{ color: var(--text-negative); }}

/* === Volume Profile === */
.volume-bar {{ display: flex; align-items: center; gap: 8px; padding: 1px 0; }}
.volume-fill {{ height: 12px; border-radius: 2px; background: rgba(41,98,255,0.3); min-width: 2px; transition: width 0.3s; }}

/* === Status Bar === */
.status-bar {{ grid-column: 1 / -1; background: var(--bg-secondary); border-top: 1px solid var(--border); padding: 4px 16px; font-size: 11px; color: var(--text-secondary); display: flex; gap: 24px; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 5px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>
<div class="layout">

  <!-- Header -->
  <div class="header">
    <h1><span>α</span> Alpha Trader</h1>
    <div class="header-actions">
      <button class="btn btn-secondary">数据对账</button>
      <button class="btn btn-secondary">因子看板</button>
      <button class="btn btn-primary">刷新数据</button>
    </div>
    <div class="header-time">📅 {latest_str}</div>
  </div>

  <!-- Watchlist -->
  <div class="watchlist" id="watchlist">
    <div class="watchlist-header">
      <span>自选股观察</span>
      <span>{len(cross)} 只</span>
    </div>
    <div class="watchlist-search">
      <input type="text" placeholder="搜索股票代码/名称..." id="searchInput" oninput="filterStocks(this.value)">
    </div>
    <div id="stockList"></div>
  </div>

  <!-- Chart -->
  <div class="chart-area">
    <div class="chart-toolbar">
      <span class="stock-label" id="stockLabel">{default_code}</span>
      <span class="stock-price" id="stockPrice"></span>
      <span class="stock-change" id="stockChange"></span>
      <div class="timeframe">
        <button class="active">日线</button>
        <button>周线</button>
        <button>月线</button>
      </div>
    </div>
    <div id="chart"></div>
  </div>

  <!-- Info Panel -->
  <div class="info-panel">
    <div class="info-header">
      <h3>📍 {default_code}</h3>
      <span style="color:var(--text-secondary);font-size:12px;">详情</span>
    </div>
    <div class="info-section">
      <h4>行情概览</h4>
      <div class="info-row"><span class="info-label">最新价</span><span class="info-value" id="infoClose">—</span></div>
      <div class="info-row"><span class="info-label">涨跌幅</span><span class="info-value" id="infoPct">—</span></div>
      <div class="info-row"><span class="info-label">最高</span><span class="info-value" id="infoHigh">—</span></div>
      <div class="info-row"><span class="info-label">最低</span><span class="info-value" id="infoLow">—</span></div>
      <div class="info-row"><span class="info-label">开盘</span><span class="info-value" id="infoOpen">—</span></div>
      <div class="info-row"><span class="info-label">成交量</span><span class="info-value" id="infoVol">—</span></div>
    </div>
    <div class="info-section">
      <h4>成交量分布（近10日）</h4>
      <div id="volumeProfile"></div>
    </div>
    <div class="info-section">
      <h4>系统状态</h4>
      <div class="info-row"><span class="info-label">数据源</span><span class="info-value">mootdx + 腾讯</span></div>
      <div class="info-row"><span class="info-label">有数据股票</span><span class="info-value">{len(cross)} 只</span></div>
      <div class="info-row"><span class="info-label">最新交易日</span><span class="info-value">{latest_str}</span></div>
    </div>
  </div>

  <!-- Status Bar -->
  <div class="status-bar">
    <span>🟢 Pipeline: 正常</span>
    <span>📊 {len(cross)} 只股票已更新</span>
    <span>🔄 上次更新: {latest_str}</span>
  </div>
</div>

<script>
const STOCKS = {stocks_json};
const KLINE_DATA = {kline_json};
let currentCode = "{default_code}";

function fmt(v, d=2) {{ return Number(v).toFixed(d); }}
function fmtVol(v) {{ if (v >= 1e8) return (v/1e8).toFixed(2)+'亿'; if (v >= 1e4) return (v/1e4).toFixed(2)+'万'; return fmt(v); }}
function pctClass(v) {{ return v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral'; }}

// Render watchlist
function renderWatchlist(data) {{
  const el = document.getElementById('stockList');
  el.innerHTML = data.map(s => `
    <div class="watchlist-item ${{s.code === currentCode ? 'active' : ''}}" onclick="switchStock('${{s.code}}')">
      <div>
        <div class="watchlist-code">${{s.code.split('.')[0]}}</div>
        <div class="watchlist-name">${{s.name}}</div>
      </div>
      <div class="watchlist-price ${{pctClass(s.pct)}}">${{fmt(s.close)}}</div>
      <div class="watchlist-pct ${{pctClass(s.pct)}}">${{s.pct > 0 ? '+' : ''}}${{fmt(s.pct, 2)}}%</div>
    </div>
  `).join('');
}}

function filterStocks(q) {{
  const data = q ? STOCKS.filter(s => s.code.includes(q) || s.name.includes(q)) : STOCKS;
  renderWatchlist(data);
}}

// Switch stock
function switchStock(code) {{
  currentCode = code;
  renderWatchlist(STOCKS);
  // Reload chart — in production would fetch from API
  alert('切换到: ' + code + '\\n(生产环境中会从DuckDB加载K线数据)');
}}

// Render chart
function initChart() {{
  const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{ background: {{ type: 'solid', color: '#131722' }}, textColor: '#d1d4dc' }},
    grid: {{ vertLines: {{ color: '#2a2e39' }}, horzLines: {{ color: '#2a2e39' }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    rightPriceScale: {{ borderColor: '#2a2e39' }},
    timeScale: {{ borderColor: '#2a2e39', timeVisible: false, secondsVisible: false }},
    width: document.getElementById('chart').clientWidth,
    height: document.getElementById('chart').clientHeight,
  }});

  const candleSeries = chart.addCandlestickSeries({{
    upColor: '#089981', downColor: '#f23645', borderDownColor: '#f23645',
    borderUpColor: '#089981', wickDownColor: '#f23645', wickUpColor: '#089981',
  }});
  candleSeries.setData(KLINE_DATA);

  const volSeries = chart.addHistogramSeries({{
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'volume',
  }});
  chart.priceScale('volume').applyOptions({{
    scaleMargins: {{ top: 0.8, bottom: 0 }},
  }});
  volSeries.setData(KLINE_DATA.map(d => ({{
    time: d.time, value: d.volume,
    color: d.close >= d.open ? 'rgba(8,153,129,0.4)' : 'rgba(242,54,69,0.4)',
  }})));

  // Update info panel
  const last = KLINE_DATA[KLINE_DATA.length-1];
  if (last) {{
    const prev = KLINE_DATA[KLINE_DATA.length-2] || last;
    const pct = ((last.close - prev.close) / prev.close * 100);
    document.getElementById('stockPrice').textContent = fmt(last.close);
    document.getElementById('stockPrice').className = pctClass(pct);
    document.getElementById('stockChange').textContent = (pct > 0 ? '+' : '') + fmt(pct,2) + '%';
    document.getElementById('stockChange').className = pctClass(pct);
    document.getElementById('infoClose').textContent = fmt(last.close);
    document.getElementById('infoPct').textContent = (pct > 0 ? '+' : '') + fmt(pct,2) + '%';
    document.getElementById('infoPct').className = pctClass(pct);
    document.getElementById('infoHigh').textContent = fmt(last.high);
    document.getElementById('infoLow').textContent = fmt(last.low);
    document.getElementById('infoOpen').textContent = fmt(last.open);
    document.getElementById('infoVol').textContent = fmtVol(last.volume);
  }}

  // Volume profile
  const recentVols = KLINE_DATA.slice(-10);
  const maxVol = Math.max(...recentVols.map(d => d.volume));
  document.getElementById('volumeProfile').innerHTML = recentVols.map(d =>
    `<div class="volume-bar">
      <span style="width:80px;text-align:right;font-size:11px;color:var(--text-secondary)">${{d.time.slice(5)}}</span>
      <div class="volume-fill" style="width:${{(d.volume/maxVol*100).toFixed(0)}}%"></div>
      <span style="font-size:11px">${{fmtVol(d.volume)}}</span>
    </div>`
  ).join('');

  // Resize
  window.addEventListener('resize', () => {{
    const w = document.getElementById('chart').clientWidth;
    const h = document.getElementById('chart').clientHeight;
    if (w > 0 && h > 0) chart.resize(w, h);
  }});

  return chart;
}}

renderWatchlist(STOCKS);
initChart();
</script>
</body>
</html>"""


def main():
    print("📊 从 DuckDB 查询数据...")
    cross, kline, default_code, latest_str = query_data()
    print(f"   截面数据: {len(cross)} 只股票")
    print(f"   K线数据: {len(kline)} 行 ({default_code})")
    print(f"   最新交易日: {latest_str}")

    html = build_html(cross, kline, default_code, latest_str)

    import os
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(html)
    print(f"\n✅ 仪表盘已生成: {OUTPUT_PATH}")
    print(f"   用浏览器打开即可查看 (file://{os.path.abspath(OUTPUT_PATH)})")


if __name__ == "__main__":
    main()
