import os
import httpx
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from anthropic import AsyncAnthropic

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/ai-reports", tags=["AI Reports"])
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

STOCK_API_BASE_URL = "https://stock.indianapi.in"
INDIAN_API_KEY = os.getenv("INDIAN_API_KEY", "")
headers = {"X-Api-Key": str(INDIAN_API_KEY)}

async def fetch_company_data(symbol: str):
    # Screener wala same logic use karke financial data fetch karenge
    async with httpx.AsyncClient() as http_client:
        stock_res = await http_client.get(f"{STOCK_API_BASE_URL}/stock", params={"name": symbol}, headers=headers)
        pl_res = await http_client.get(f"{STOCK_API_BASE_URL}/historical_stats", params={"stock_name": symbol, "stats": "quarter_results"}, headers=headers)
        return {
            "overview": stock_res.json() if stock_res.status_code == 200 else {},
            "financials": pl_res.json() if pl_res.status_code == 200 else {}
        }

@router.get("/generate/{symbol}")
async def generate_report(
    symbol: str, 
    report_type: str = Query("standard"), # "standard" or custom prompt
    custom_prompt: str = Query(None),
    db: Session = Depends(get_db)
):
    symbol = symbol.upper()

    # 1. CHECK SUPABASE DB FOR EXISTING REPORT (Caching for 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    existing_report = db.query(models.AIReport).filter(
        models.AIReport.symbol == symbol,
        models.AIReport.report_type == report_type,
        models.AIReport.created_at >= seven_days_ago
    ).first()

    if existing_report:
        return {"symbol": symbol, "cached": True, "content": existing_report.content}

    # 2. IF NOT CACHED, FETCH DATA FROM INDIAN API
    company_data = await fetch_company_data(symbol)
    if not company_data["overview"]:
        raise HTTPException(status_code=404, detail="Company financials not found to generate report.")

    # 3. PREPARE CLAUDE PROMPT
    data_str = json.dumps(company_data)[:4000] # Sending summary to Claude
    
    if report_type == "standard":
        system_instructions = (
            "You are an expert SEBI-registered style Financial Analyst. "
            "Analyze the provided financial data. "
            "STRICT RULES: DO NOT give Buy/Sell/Hold recommendations. DO NOT give Target Prices. "
            "Provide: 1. Company Intelligence Summary. 2. Key Strengths & Weaknesses. 3. A Fundamental Score out of 10 based purely on balance sheet & P&L health."
        )
        user_message = f"Analyze this company '{symbol}' based on the following data: {data_str}"
    else:
        system_instructions = (
            "You are a financial assistant. Answer the user's custom query using the provided financial data. "
            "DO NOT give Buy/Sell/Hold recommendations or Target Prices under any circumstances."
        )
        user_message = f"Data: {data_str}\n\nUser Query: {custom_prompt}"

    # 4. CALL CLAUDE API (Using Claude 3.5 Sonnet)
    try:
        response = await client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1500,
            temperature=0.2,
            system=system_instructions,
            messages=[{"role": "user", "content": user_message}]
        )
        report_content = response.content[0].text

        # 5. SAVE TO SUPABASE DB
        new_report = models.AIReport(
            symbol=symbol,
            report_type=report_type,
            content=report_content
        )
        db.add(new_report)
        db.commit()

        return {"symbol": symbol, "cached": False, "content": report_content}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")