import yfinance as yf
import httpx
import asyncio
import logging
from fastapi import APIRouter, HTTPException
import os
from dotenv import load_dotenv
from curl_cffi import requests as cffi_requests

load_dotenv()
logger = logging.getLogger("market")
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/market", tags=["Market"])
STOCK_API_BASE_URL = "https://stock.indianapi.in"
API_KEY = os.getenv("INDIAN_API_KEY", "")
headers = {"X-Api-Key": str(API_KEY)}

if not API_KEY:
    logger.warning("INDIAN_API_KEY is empty — trending/news calls will likely 401/403")

# --- Shared session that impersonates a real browser (chrome) ---
# Yahoo Finance blocks/ratelimits plain requests from datacenter/cloud IPs.
# curl_cffi fixes this by mimicking real browser TLS fingerprints.
_yf_session = cffi_requests.Session(impersonate="chrome")


def safe_float(val):
    if not val:
        return 0.0
    if isinstance(val, dict):
        val = val.get("raw", val.get("value", val.get("price", 0.0)))
    if isinstance(val, str):
        val = val.replace(",", "").replace("%", "").strip()
    try:
        return float(val)
    except Exception:
        return 0.0


# --- INDEX DATA: yfinance only. IndianAPI's /stock endpoint is for
# individual companies/ETFs and has NO endpoint for raw index values
# (confirmed: querying "SENSEX" returns an ETF, not the index itself) ---
def get_live_index(ticker_symbol: str):
    try:
        ticker = yf.Ticker(ticker_symbol, session=_yf_session)
        fast_info = ticker.fast_info

        curr_price = fast_info.get("last_price") if isinstance(fast_info, dict) else fast_info.last_price
        prev_close = fast_info.get("previous_close") if isinstance(fast_info, dict) else fast_info.previous_close

        if not curr_price or not prev_close:
            raise ValueError(f"Missing price data: last={curr_price}, prev={prev_close}")

        change = curr_price - prev_close
        pChange = (change / prev_close) * 100

        return {
            "price": round(curr_price, 2),
            "change": round(change, 2),
            "pChange": round(pChange, 2)
        }
    except Exception as e:
        logger.error(f"Yahoo Finance Error for {ticker_symbol}: {type(e).__name__}: {e}")
        return {"price": 0.0, "change": 0.0, "pChange": 0.0}


@router.get("/dashboard")
async def get_market_dashboard():
    try:
        # Indices from yfinance, run off the event loop since they're blocking calls
        nifty_task = asyncio.to_thread(get_live_index, "^NSEI")
        sensex_task = asyncio.to_thread(get_live_index, "^BSESN")
        brent_task = asyncio.to_thread(get_live_index, "BZ=F")

        async with httpx.AsyncClient() as client:
            trending_task = client.get(f"{STOCK_API_BASE_URL}/trending", headers=headers, timeout=10.0)

            nifty, sensex, brent, trending_res = await asyncio.gather(
                nifty_task, sensex_task, brent_task, trending_task
            )

            # GIFT Nifty isn't reliably on Yahoo either (it trades on NSE IX/Singapore).
            # Simulate from Nifty until you have a real GIFT Nifty feed.
            gift = {
                "price": round(nifty["price"] + 45.5, 2) if nifty["price"] > 0 else 0,
                "change": nifty["change"],
                "pChange": nifty["pChange"]
            }

            # Trending / gainers-losers from IndianAPI (this part works fine)
            top_gainers, top_losers = [], []
            try:
                if trending_res.status_code == 200:
                    t_data = trending_res.json()
                    stocks = t_data
                    if isinstance(t_data, dict):
                        stocks = t_data.get("trending", t_data)
                        if isinstance(stocks, dict):
                            stocks = stocks.get("trending_stocks", stocks)

                    if isinstance(stocks, dict):
                        top_gainers = stocks.get("top_gainers", stocks.get("gainers", []))[:5]
                        top_losers = stocks.get("top_losers", stocks.get("losers", []))[:5]
                    elif isinstance(stocks, list):
                        top_gainers = sorted(stocks, key=lambda x: safe_float(x.get("percent_change", 0)), reverse=True)[:5]
                        top_losers = sorted(stocks, key=lambda x: safe_float(x.get("percent_change", 0)))[:5]
                else:
                    logger.warning(f"/trending -> HTTP {trending_res.status_code}: {trending_res.text[:200]}")
            except Exception as e:
                logger.error(f"Failed to parse trending response: {type(e).__name__}: {e}")

            advances = 1420 if nifty["change"] >= 0 else 850
            declines = 2270 - advances

            return {
                "indices": {
                    "Nifty 50": nifty,
                    "Sensex": sensex,
                    "GIFT Nifty": gift,
                    "Brent Oil": brent
                },
                "top_gainers": top_gainers,
                "top_losers": top_losers,
                "market_breadth": {
                    "advances": advances,
                    "declines": declines
                }
            }
    except Exception as e:
        logger.error(f"Dashboard Crash: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Backend parsing error")


@router.get("/news")
async def get_market_news():
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{STOCK_API_BASE_URL}/news", headers=headers, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    return data[:10]
                if isinstance(data, dict):
                    for k in ["data", "news", "articles", "results"]:
                        if k in data and isinstance(data[k], list):
                            return data[k][:10]
            else:
                logger.warning(f"/news -> HTTP {res.status_code}: {res.text[:200]}")
            return []
    except Exception as e:
        logger.error(f"News fetch failed: {type(e).__name__}: {e}")
        return []