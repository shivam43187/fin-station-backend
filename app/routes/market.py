import os
import json
import httpx
import redis
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional

router = APIRouter(
    prefix="/market",
    tags=["Market & Stocks"]
)

# 1. Setup Redis Client
# Make sure your Memurai/Redis server is running on localhost:6379
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

# 2. IndianAPI Setup
INDIAN_API_BASE_URL = "https://stock.indianapi.in"
headers = {
    "X-API-Key": os.getenv("INDIAN_API_KEY", "your_test_key_here")
}

# Helper function for Caching
async def fetch_and_cache(cache_key: str, api_url: str, cache_expiry_seconds: int = 900): # 900s = 15 mins
    # Pehle Redis cache check karo
    cached_data = redis_client.get(cache_key)
    if cached_data:
        print(f"Serving {cache_key} from REDIS CACHE ⚡")
        return json.loads(cached_data)

    # Agar cache mein nahi hai, toh IndianAPI hit karo
    print(f"Fetching {cache_key} from INDIAN API 🌐")
    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, headers=headers)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error fetching data from IndianAPI")
        
        data = response.json()
        # Data ko Redis mein save karo with expiry
        redis_client.setex(cache_key, cache_expiry_seconds, json.dumps(data))
        return data

# --- ENDPOINTS ---

@router.get("/dashboard")
async def get_market_dashboard():
    # Screenshot ke according available endpoints use kar rahe hain
    trending_url = f"{INDIAN_API_BASE_URL}/trending"
    active_url = f"{INDIAN_API_BASE_URL}/NSE_most_active"
    
    # Dono ko fetch aur cache karenge (5 minutes ke liye)
    trending_data = await fetch_and_cache(cache_key="market_trending", api_url=trending_url, cache_expiry_seconds=300)
    active_data = await fetch_and_cache(cache_key="market_active_nse", api_url=active_url, cache_expiry_seconds=300)
    
    # Frontend ko ek combined response bhejenge
    return {
        "trending": trending_data,
        "most_active": active_data
    }

@router.get("/news")
async def get_market_news():
    # Yeh tumhare screenshot mein perfectly available hai
    url = f"{INDIAN_API_BASE_URL}/news"
    data = await fetch_and_cache(cache_key="market_news", api_url=url, cache_expiry_seconds=1800)
    return data

@router.get("/stocks/{symbol}")
async def get_stock_financials(symbol: str):
    # Screenshot mein /stock endpoint available hai
    url = f"{INDIAN_API_BASE_URL}/stock?name={symbol}"
    data = await fetch_and_cache(cache_key=f"stock_{symbol}", api_url=url, cache_expiry_seconds=86400)
    return data