import httpx
import asyncio
import logging
from fastapi import APIRouter, HTTPException
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("screener")
router = APIRouter(prefix="/screener", tags=["Screener"])

STOCK_API_BASE_URL = "https://stock.indianapi.in"
API_KEY = os.getenv("INDIAN_API_KEY", "")
headers = {"X-Api-Key": str(API_KEY)}

if not API_KEY:
    logger.warning("INDIAN_API_KEY is empty — screener calls will likely 401/403")


async def fetch_stat(client: httpx.AsyncClient, symbol: str, stats: str):
    """Calls /historical_stats?stock_name=X&stats=<stats>. Returns {} on any failure."""
    try:
        res = await client.get(
            f"{STOCK_API_BASE_URL}/historical_stats",
            params={"stock_name": symbol, "stats": stats},
            headers=headers,
            timeout=15.0
        )
        if res.status_code != 200:
            logger.warning(f"/historical_stats stats={stats} name={symbol} -> HTTP {res.status_code}: {res.text[:200]}")
            return {}
        return res.json()
    except Exception as e:
        logger.error(f"/historical_stats stats={stats} name={symbol} failed: {type(e).__name__}: {e}")
        return {}


@router.get("/{symbol}")
async def get_company_data(symbol: str):
    """
    Fetches full company details: Overview/Ratios (from /stock) plus
    Profit & Loss, Balance Sheet, and Cash Flow (from /historical_stats).
    """
    try:
        async with httpx.AsyncClient() as client:
            stock_task = client.get(f"{STOCK_API_BASE_URL}/stock", params={"name": symbol}, headers=headers, timeout=15.0)

            # Quarterly P&L. Swap to "yoy_results" if you'd rather show yearly by default.
            pl_task = fetch_stat(client, symbol, "quarter_results")
            bs_task = fetch_stat(client, symbol, "balancesheet")
            cf_task = fetch_stat(client, symbol, "cashflow")

            stock_res, pl_data, bs_data, cf_data = await asyncio.gather(
                stock_task, pl_task, bs_task, cf_task
            )

            if stock_res.status_code != 200:
                logger.warning(f"/stock?name={symbol} -> HTTP {stock_res.status_code}: {stock_res.text[:200]}")

            stock_data = stock_res.json() if stock_res.status_code == 200 else {}

            if not stock_data and not pl_data and not bs_data and not cf_data:
                raise HTTPException(status_code=404, detail="Company data not found. Check the symbol.")

            return {
                "symbol": symbol.upper(),
                "overview": stock_data,   # Basic info, ratios, shareholding, price
                "financials": {
                    "profit_loss": pl_data,
                    "balance_sheet": bs_data,
                    "cash_flow": cf_data
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Screener fetch failed for {symbol}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch company data")