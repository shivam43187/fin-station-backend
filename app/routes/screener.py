import httpx
import asyncio
import time
import logging
import json
from fastapi import APIRouter, Depends, HTTPException, Query
import os
from dotenv import load_dotenv
from ..auth import verify_user_token

from app.redis import RedisCache

load_dotenv()
logger = logging.getLogger("screener")
router = APIRouter(prefix="/screener", tags=["Screener"])

STOCK_API_BASE_URL = "https://stock.indianapi.in"
API_KEY = os.getenv("INDIAN_API_KEY", "")
UPSTASH_REDIS_REST_REVALIDATE_TIME = int(os.getenv("UPSTASH_REDIS_REST_REVALIDATE_TIME", "3600"))
headers = {"X-Api-Key": str(API_KEY)}

if not API_KEY:
    logger.warning("INDIAN_API_KEY is empty — screener calls will likely 401/403")

# ─────────────────────────────────────────────────────────────
# Autocomplete search — backed by a static, publicly-hosted list
# of all NSE/BSE stocks (no API key required, so it's free/unlimited
# to query, unlike the paid /stock and /historical_stats endpoints).
# We cache it in-memory and refresh once a day so a per-keystroke
# search never hits the network.
# ─────────────────────────────────────────────────────────────
ALL_STOCKS_URL = "https://dev.indianapi.in/static/all_stocks.json"
_STOCKS_CACHE: list[dict] = []
_STOCKS_CACHE_TS: float = 0.0
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


async def _get_all_stocks(client: httpx.AsyncClient) -> list[dict]:
    global _STOCKS_CACHE, _STOCKS_CACHE_TS
    now = time.time()

    if _STOCKS_CACHE and (now - _STOCKS_CACHE_TS) < _CACHE_TTL_SECONDS:
        return _STOCKS_CACHE

    try:
        res = await client.get(ALL_STOCKS_URL, timeout=15.0)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, list) and data:
            _STOCKS_CACHE = data
            _STOCKS_CACHE_TS = now
            logger.info(f"Refreshed stock list cache: {len(data)} stocks")
        return _STOCKS_CACHE
    except Exception as e:
        logger.error(f"Failed to refresh stock list, serving stale cache if any: {type(e).__name__}: {e}")
        return _STOCKS_CACHE  # serve whatever we had before, even if stale


def _query_symbol(stock: dict) -> str | None:
    """
    The value we tell the frontend to send back to /screener/{symbol}.
    Prefer the NSE ticker (the underlying /stock API resolves these reliably).
    If a stock has no NSE listing, DON'T fall back to the raw numeric BSE
    code — /stock?name=<number> won't resolve to anything. Fall back to the
    full company name instead, since that endpoint matches on name text.
    """
    nse = (stock.get("nse-code") or "").strip()
    if nse and nse.lower() != "null":
        return nse
    name = (stock.get("name") or "").strip()
    return name or None


# IMPORTANT: this must be registered BEFORE the "/{symbol}" route below,
# otherwise FastAPI will match "/screener/search" as symbol="search".
@router.get("/search")
async def search_stocks(
    q: str = Query(..., min_length=1, description="Partial company name or ticker symbol"),
    auth_payload: dict = Depends(verify_user_token),
):
    """
    Autocomplete search over the full NSE/BSE stock universe.
    Returns up to 8 matches, name-prefix and symbol-prefix matches ranked
    above plain substring matches.
    """
    query = q.strip().lower()
    if not query:
        return []

    async with httpx.AsyncClient() as client:
        stocks = await _get_all_stocks(client)

    starts_with: list[dict] = []
    contains: list[dict] = []

    for stock in stocks:
        symbol = _query_symbol(stock)
        if not symbol:
            continue

        name = (stock.get("name") or "")
        name_lower = name.lower()
        symbol_lower = symbol.lower()

        if name_lower.startswith(query) or symbol_lower.startswith(query):
            starts_with.append(stock)
        elif query in name_lower or query in symbol_lower:
            contains.append(stock)

        if len(starts_with) >= 8:
            break

    results = (starts_with + contains)[:8]

    return [
        {
            "name": s.get("name"),
            "symbol": _query_symbol(s),
            "bse_code": s.get("bse-code"),
        }
        for s in results
    ]


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
async def get_company_data(
    symbol: str,
    stockName: str | None = Query(None),
    auth_payload: dict = Depends(verify_user_token)
):
    """
    Fetches full company details: Overview/Ratios (from /stock) plus
    Profit & Loss, Balance Sheet, and Cash Flow.
    """

    symbol = symbol.upper()
    cache_key = f"company:{symbol}"

    # --------------------
    # Check Redis Cache
    # --------------------
    cached_data = RedisCache.get(cache_key)
    if cached_data:
        logger.info(f"{symbol} served from Redis")
        return json.loads(cached_data)

    try:
        async with httpx.AsyncClient() as client:
            stock_data = {}

            # 1. Try with symbol
            stock_res = await client.get(
                f"{STOCK_API_BASE_URL}/stock",
                params={"name": symbol},
                headers=headers,
                timeout=15.0,
            )

            if stock_res.status_code == 200:
                stock_data = stock_res.json()

            # 2. If not found and company name is available, try again
            if (not stock_data) and stockName:
                logger.info(f"Retrying /stock with company name: {stockName}")

                stock_res = await client.get(
                    f"{STOCK_API_BASE_URL}/stock",
                    params={"name": stockName},
                    headers=headers,
                    timeout=15.0,
                )

                if stock_res.status_code == 200:
                    stock_data = stock_res.json()

            pl_task = fetch_stat(client, symbol, "quarter_results")
            bs_task = fetch_stat(client, symbol, "balancesheet")
            cf_task = fetch_stat(client, symbol, "cashflow")

            pl_data, bs_data, cf_data = await asyncio.gather(
                pl_task,
                bs_task,
                cf_task,
            )

            if stock_res.status_code != 200:
                logger.warning(
                    f"/stock?name={symbol} -> HTTP {stock_res.status_code}: "
                    f"{stock_res.text[:200]}"
                )

            if (
                not stock_data
                and not pl_data
                and not bs_data
                and not cf_data
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Company data not found. Check the symbol.",
                )

            response = {
                "symbol": symbol,
                "overview": stock_data,
                "financials": {
                    "profit_loss": pl_data,
                    "balance_sheet": bs_data,
                    "cash_flow": cf_data,
                },
            }

            # --------------------
            # Cache for 24 hours
            # --------------------
            # RedisCache.set(
            #     cache_key,
            #     response,
            #     ex=UPSTASH_REDIS_REST_REVALIDATE_TIME,
            # )

            # logger.info(f"{symbol} cached in Redis")

            return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Screener fetch failed for {symbol}: {type(e).__name__}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch company data",
        )