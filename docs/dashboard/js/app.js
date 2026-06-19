/* ==========================================================================
   Alpha Trader Dashboard — Application
   ==========================================================================
   Architecture: Presentation layer separated from data layer.
   Components are functions that render into named outlets.
   ========================================================================== */

/* ---- Utilities ---- */

function fmt(n, d) {
  if (n == null || isNaN(n)) return "—";
  return Number(n).toFixed(d);
}

function fmtVol(v) {
  if (v == null || isNaN(v)) return "—";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(2) + "万";
  return fmt(v, 0);
}

function priceClass(v) {
  if (v > 0) return "up";
  if (v < 0) return "down";
  return "muted";
}

/* ==========================================================================
   Data Store
   ========================================================================== */

const store = {
  stocks: [],
  kline: {},
  currentCode: null,
  selectedIndex: null,

  async loadAll() {
    try {
      const [stocksRes, klineRes] = await Promise.all([
        fetch("/api/stocks"),
        fetch("/api/kline?code=000001.SZ"),
      ]);
      if (!stocksRes.ok || !klineRes.ok) throw new Error("数据加载失败");

      this.stocks = await stocksRes.json();
      this.kline["000001.SZ"] = await klineRes.json();
      this.currentCode = "000001.SZ";
      this.selectedIndex = this.stocks.findIndex(s => s.code === "000001.SZ");
      return true;
    } catch (e) {
      console.warn("API 不可用，使用内置演示数据");
      this.loadDemoData();
      return false;
    }
  },

  loadDemoData() {
    this.stocks = window.__DEMO_STOCKS || [];
    this.kline["000001.SZ"] = window.__DEMO_KLINE || [];
    this.currentCode = "000001.SZ";
    this.selectedIndex = this.stocks.findIndex(s => s.code === "000001.SZ");
  },

  async selectStock(code) {
    if (code === this.currentCode) return;
    this.currentCode = code;
    this.selectedIndex = this.stocks.findIndex(s => s.code === code);

    if (!this.kline[code]) {
      try {
        const res = await fetch(`/api/kline?code=${encodeURIComponent(code)}`);
        if (res.ok) this.kline[code] = await res.json();
      } catch {
        this.kline[code] = [];
      }
    }

    renderAll();
  },

  filterStocks(query) {
    if (!query) return this.stocks;
    const q = query.toUpperCase();
    return this.stocks.filter(
      s => s.code.toUpperCase().includes(q) || s.name.includes(q)
    );
  },
};

/* ==========================================================================
   Component: Watchlist
   ========================================================================== */

function renderWatchlist(data) {
  const el = document.getElementById("watchlist-items");
  if (!data || data.length === 0) {
    el.innerHTML = "";
    return;
  }

  el.innerHTML = data.map(s => {
    const selected = s.code === store.currentCode;
    return `
      <div class="watchlist-row"
           role="option"
           aria-selected="${selected}"
           tabindex="0"
           data-code="${s.code}"
           onclick="store.selectStock('${s.code}')"
           onkeydown="if(event.key==='Enter')store.selectStock('${s.code}')">
        <div>
          <div class="watchlist-row-code">${s.code.split(".")[0]}</div>
          <div class="watchlist-row-name">${s.name}</div>
        </div>
        <div class="watchlist-row-price ${priceClass(s.pct)}">${fmt(s.close)}</div>
        <div class="watchlist-row-change ${priceClass(s.pct)}">${s.pct > 0 ? "+" : ""}${fmt(s.pct, 2)}%</div>
      </div>
    `;
  }).join("");
}

/* ==========================================================================
   Component: Chart
   ========================================================================== */

let chartInstance = null;

function renderChart(klineData, code) {
  const container = document.getElementById("chart-container");
  container.innerHTML = "";

  if (!klineData || klineData.length === 0) {
    container.innerHTML = '<div class="state-message">暂无K线数据</div>';
    return;
  }

  // Toolbar update
  const last = klineData[klineData.length - 1];
  const prev = klineData.length > 1 ? klineData[klineData.length - 2] : last;
  const pct = prev.close ? ((last.close - prev.close) / prev.close * 100) : 0;

  document.getElementById("chart-code").textContent = code;
  document.getElementById("chart-price").textContent = fmt(last.close);
  document.getElementById("chart-price").className = "chart-toolbar-price " + priceClass(pct);
  document.getElementById("chart-change").textContent = (pct > 0 ? "+" : "") + fmt(pct, 2) + "%";
  document.getElementById("chart-change").className = "chart-toolbar-change " + priceClass(pct);

  // Lightweight chart
  const w = container.clientWidth || 600;
  const h = container.clientHeight || 400;
  chartInstance = LightweightCharts.createChart(container, {
    layout: {
      background: { type: "solid", color: "#0d0f14" },
      textColor: "#8b8f9a",
      fontSize: 11,
    },
    grid: {
      vertLines: { color: "#1c1e26" },
      horzLines: { color: "#1c1e26" },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "#282a32", scaleMargins: { top: 0.05, bottom: 0.25 } },
    timeScale: { borderColor: "#282a32", timeVisible: false },
    width: w,
    height: h,
    handleScroll: true,
    handleScale: true,
  });

  const candleSeries = chartInstance.addCandlestickSeries({
    upColor: "#089981",
    downColor: "#f23645",
    borderDownColor: "#f23645",
    borderUpColor: "#089981",
    wickDownColor: "#f23645",
    wickUpColor: "#089981",
  });
  candleSeries.setData(klineData);

  const volSeries = chartInstance.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "volume-scale",
  });
  chartInstance.priceScale("volume-scale").applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 },
  });
  volSeries.setData(
    klineData.map(d => ({
      time: d.time,
      value: d.volume,
      color: d.close >= d.open ? "rgba(8,153,129,0.35)" : "rgba(242,54,69,0.35)",
    }))
  );

  // Resize observer
  const ro = new ResizeObserver(() => {
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    if (cw > 0 && ch > 0) chartInstance.resize(cw, ch);
  });
  ro.observe(container);
}

/* ==========================================================================
   Component: Info Panel
   ========================================================================== */

function renderInfoPanel(klineData) {
  if (!klineData || klineData.length === 0) {
    document.getElementById("info-overview").innerHTML = '<div class="state-message">—</div>';
    document.getElementById("info-volume").innerHTML = '<div class="state-message">—</div>';
    return;
  }

  const last = klineData[klineData.length - 1];
  const prev = klineData.length > 1 ? klineData[klineData.length - 2] : last;
  const pct = prev.close ? ((last.close - prev.close) / prev.close * 100) : 0;

  document.getElementById("info-overview").innerHTML = `
    <div class="info-row"><span class="info-row-label">最新价</span><span class="info-row-value ${priceClass(pct)}">${fmt(last.close)}</span></div>
    <div class="info-row"><span class="info-row-label">涨跌幅</span><span class="info-row-value ${priceClass(pct)}">${pct > 0 ? "+" : ""}${fmt(pct, 2)}%</span></div>
    <div class="info-row"><span class="info-row-label">开盘</span><span class="info-row-value">${fmt(last.open)}</span></div>
    <div class="info-row"><span class="info-row-label">最高</span><span class="info-row-value">${fmt(last.high)}</span></div>
    <div class="info-row"><span class="info-row-label">最低</span><span class="info-row-value">${fmt(last.low)}</span></div>
    <div class="info-row"><span class="info-row-label">成交量</span><span class="info-row-value">${fmtVol(last.volume)}</span></div>
  `;

  // Volume profile: last 10 days
  const recent = klineData.slice(-10);
  const maxVol = Math.max(...recent.map(d => d.volume));
  const green = getComputedStyle(document.documentElement).getPropertyValue("--green").trim() || "#089981";
  const red = getComputedStyle(document.documentElement).getPropertyValue("--red").trim() || "#f23645";

  document.getElementById("info-volume").innerHTML = recent.map(d => {
    const isUp = d.close >= d.open;
    const pct2 = maxVol > 0 ? (d.volume / maxVol * 100) : 0;
    return `
      <div class="volume-bar">
        <span class="volume-bar-date">${d.time.slice(5)}</span>
        <div class="volume-bar-track">
          <div class="volume-bar-fill" style="width:${pct2}%;background:${isUp ? green : red}"></div>
        </div>
        <span class="volume-bar-value">${fmtVol(d.volume)}</span>
      </div>
    `;
  }).join("");
}

/* ==========================================================================
   Component: Status Bar
   ========================================================================== */

function renderStatusBar(stockCount, dateStr) {
  document.getElementById("status-stocks").textContent = stockCount + " 只已更新";
  document.getElementById("status-date").textContent = dateStr || "—";
}

/* ==========================================================================
   Search
   ========================================================================== */

let searchInput = null;

function initSearch() {
  searchInput = document.getElementById("search-input");
  if (!searchInput) return;
  searchInput.addEventListener("input", function () {
    const filtered = store.filterStocks(this.value);
    renderWatchlist(filtered);
  });
}

/* ==========================================================================
   Render All
   ========================================================================== */

function renderAll() {
  const code = store.currentCode;
  renderWatchlist(store.stocks);
  renderChart(store.kline[code], code);
  renderInfoPanel(store.kline[code]);
}

/* ==========================================================================
   Init
   ========================================================================== */

async function init() {
  await store.loadAll();
  initSearch();
  renderAll();
}

document.addEventListener("DOMContentLoaded", init);
