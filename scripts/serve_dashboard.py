"""
Alpha Trader Dashboard — API Server
=====================================
FastAPI 后端：从 DuckDB 读取数据，通过 REST API 提供给前端。

启动方式：
  pip install fastapi uvicorn
  python scripts/serve_dashboard.py

前端访问：
  http://localhost:8000/dashboard/
  http://localhost:8000/api/stocks
  http://localhost:8000/api/kline?code=000001.SZ
"""

import os
import sys
from pathlib import Path

# 确保能找到 core 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import duckdb
    import pandas as pd
except ImportError:
    print("请先安装依赖: pip install duckdb pandas")
    sys.exit(1)

try:
    from fastapi import FastAPI, Query
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:
    print("请安装: pip install fastapi uvicorn")
    sys.exit(1)

import uvicorn

# ---- Config ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "quant.duckdb"
DASHBOARD_DIR = PROJECT_ROOT / "docs" / "dashboard"

app = FastAPI(title="Alpha Trader API", version="0.1.0")


def get_db():
    """获取 DuckDB 连接"""
    if not DB_PATH.exists():
        return None
    try:
        return duckdb.connect(str(DB_PATH))
    except Exception:
        return None


@app.get("/api/stocks")
async def list_stocks():
    """获取最新交易日全市场截面数据"""
    con = get_db()
    if con is None:
        return JSONResponse(content=[], status_code=200)

    try:
        latest = con.execute("SELECT MAX(trade_date) FROM daily_kline").fetchone()[0]
        if latest is None:
            return []

        df = con.execute(f"""
            SELECT k.ts_code AS code, s.name,
                   k.close, k.pct_chg AS pct, k.vol
            FROM daily_kline k
            JOIN stock_list s ON k.ts_code = s.ts_code
            WHERE k.trade_date = '{latest}'
              AND k.close > 0
            ORDER BY k.vol DESC
            LIMIT 100
        """).fetchdf()

        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        con.close()


@app.get("/api/kline")
async def get_kline(code: str = Query("000001.SZ")):
    """获取个股日K线"""
    con = get_db()
    if con is None:
        return []

    try:
        df = con.execute(f"""
            SELECT trade_date AS time, open, high, low, close,
                   vol AS volume
            FROM daily_kline
            WHERE ts_code = '{code}'
            ORDER BY trade_date
        """).fetchdf()

        if df.empty:
            return []

        df["time"] = df["time"].astype(str)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].round(2)

        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        con.close()


@app.get("/api/meta")
async def get_meta():
    """系统元信息"""
    con = get_db()
    if con is None:
        return {"status": "no_data", "stock_count": 0, "latest_date": None}

    try:
        latest = con.execute("SELECT MAX(trade_date) FROM daily_kline").fetchone()[0]
        count = con.execute("SELECT COUNT(DISTINCT ts_code) FROM daily_kline").fetchone()[0]
        return {
            "status": "ok",
            "stock_count": count,
            "latest_date": str(latest) if latest else None,
        }
    finally:
        con.close()


# ---- 静态文件服务 ----

@app.get("/dashboard/")
async def dashboard_index():
    return FileResponse(str(DASHBOARD_DIR / "index.html"))


@app.get("/dashboard/{path:path}")
async def dashboard_static(path: str):
    file_path = DASHBOARD_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return JSONResponse(content={"error": "not found"}, status_code=404)


if __name__ == "__main__":
    print(f"\n  🚀 Alpha Trader API Server")
    print(f"  ─────────────────────────")
    print(f"  📊 DuckDB: {DB_PATH}")
    print(f"  🖥️  前端:  http://localhost:8000/dashboard/")
    print(f"  📡 API:   http://localhost:8000/api/stocks")
    print(f"  ─────────────────────────\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
