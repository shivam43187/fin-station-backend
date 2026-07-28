import os
import httpx
import asyncio
import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .. import models
from ..database import get_db

logger = logging.getLogger("watchlist")
router = APIRouter(prefix="/watchlist", tags=["Watchlist"])

STOCK_API_BASE_URL = "https://stock.indianapi.in"
headers = {"X-Api-Key": str(os.getenv("INDIAN_API_KEY", ""))}

class WatchlistAdd(BaseModel):
    user_id: str
    stock_symbol: str

def safe_float(val):
    if not val: return 0.0
    if isinstance(val, dict): val = val.get("raw", val.get("value", val.get("price", 0.0)))
    if isinstance(val, str): val = val.replace(",", "").replace("%", "").strip()
    try: return float(val)
    except: return 0.0

async def fetch_live_price(client: httpx.AsyncClient, symbol: str):
    try:
        res = await client.get(f"{STOCK_API_BASE_URL}/stock", params={"name": symbol}, headers=headers, timeout=10.0)
        if res.status_code == 200:
            data = res.json()
            inner = data.get("data", data)
            item = inner[0] if isinstance(inner, list) and len(inner) > 0 else inner
            
            price = item.get("last_traded_price", item.get("price", item.get("currentPrice", 0)))
            change = item.get("net_change", item.get("change", 0))
            pchange = item.get("percent_change", item.get("per_change", item.get("pChange", 0)))
            
            return {
                "symbol": symbol,
                "price": safe_float(price),
                "change": safe_float(change),
                "pChange": safe_float(pchange)
            }
    except Exception as e:
        logger.error(f"Error fetching live price for {symbol}: {e}")
    
    return {"symbol": symbol, "price": 0.0, "change": 0.0, "pChange": 0.0}

@router.get("/{user_id}")
async def get_watchlist(user_id: str, db: Session = Depends(get_db)):
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid User ID format")

    items = db.query(models.Watchlist).filter(models.Watchlist.user_id == uid).all()
    if not items:
        return []
    
    # Fetch live prices concurrently for all saved stocks
    async with httpx.AsyncClient() as client:
        tasks = [fetch_live_price(client, item.stock_symbol) for item in items]
        live_data = await asyncio.gather(*tasks)
        
    return live_data

@router.post("/")
def add_to_watchlist(req: WatchlistAdd, db: Session = Depends(get_db)):
    req.stock_symbol = req.stock_symbol.upper().strip()
    try:
        uid = UUID(req.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid User ID format")

    try:
        # Check for existing stock to prevent duplicates
        existing = db.query(models.Watchlist).filter(
            models.Watchlist.user_id == uid,
            models.Watchlist.stock_symbol == req.stock_symbol
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Stock already in watchlist")
            
        new_item = models.Watchlist(user_id=uid, stock_symbol=req.stock_symbol)
        db.add(new_item)
        db.commit()
        return {"message": "Added to watchlist"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding to watchlist: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.delete("/{user_id}/{symbol}")
def remove_from_watchlist(user_id: str, symbol: str, db: Session = Depends(get_db)):
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid User ID format")

    try:
        item = db.query(models.Watchlist).filter(
            models.Watchlist.user_id == uid,
            models.Watchlist.stock_symbol == symbol.upper()
        ).first()
        
        if item:
            db.delete(item)
            db.commit()
        return {"message": "Removed from watchlist"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing from watchlist: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")