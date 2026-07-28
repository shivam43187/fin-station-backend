import os
import httpx
import json
import uuid
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from anthropic import AsyncAnthropic

from .. import models, schemas
from ..database import get_db

# --- SETUP LOGGING ---
logger = logging.getLogger("ai_reports")
logger.setLevel(logging.INFO)
# Agar root logger configured nahi hai, toh basic setup kar sakte ho:
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

router = APIRouter(prefix="/ai-reports", tags=["AI Reports"])
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

STOCK_API_BASE_URL = "https://stock.indianapi.in"
INDIAN_API_KEY = os.getenv("INDIAN_API_KEY", "")
headers = {"X-Api-Key": str(INDIAN_API_KEY)}

async def fetch_company_data(symbol: str):
    logger.info(f"[{symbol}] Fetching financial data from Indian API...")
    try:
        async with httpx.AsyncClient() as http_client:
            stock_res = await http_client.get(f"{STOCK_API_BASE_URL}/stock", params={"name": symbol}, headers=headers)
            pl_res = await http_client.get(f"{STOCK_API_BASE_URL}/historical_stats", params={"stock_name": symbol, "stats": "quarter_results"}, headers=headers)
            
            if stock_res.status_code != 200:
                logger.warning(f"[{symbol}] Stock overview API returned status: {stock_res.status_code}")
            if pl_res.status_code != 200:
                logger.warning(f"[{symbol}] Stock financials API returned status: {pl_res.status_code}")

            return {
                "overview": stock_res.json() if stock_res.status_code == 200 else {},
                "financials": pl_res.json() if pl_res.status_code == 200 else {}
            }
    except Exception as e:
        logger.error(f"[{symbol}] Failed to fetch data from Indian API: {str(e)}")
        raise

@router.get("/generate/{symbol}")
async def generate_report(
    symbol: str, 
    user_id: str = Query(..., description="UUID of the requesting user"), 
    report_type: str = Query("standard"), 
    custom_prompt: str = Query(None),
    db: Session = Depends(get_db)
):
    symbol = symbol.upper()
    logger.info(f"[{symbol}] Report request received | User: {user_id} | Type: {report_type}")

    # 1. CHECK SUPABASE DB FOR EXISTING REPORT
    logger.debug(f"[{symbol}] Checking database for cached report (Last 7 days)...")
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    existing_report = db.query(models.AIReportHistory).filter(
        models.AIReportHistory.stock_symbol == symbol,
        models.AIReportHistory.report_type == report_type,
        models.AIReportHistory.generated_at >= seven_days_ago
    ).first()

    if existing_report and getattr(existing_report, "content", None):
        logger.info(f"[{symbol}] Cache HIT! Returning existing report generated at {existing_report.generated_at}")
        return {"symbol": symbol, "cached": True, "content": existing_report.content}

    logger.info(f"[{symbol}] Cache MISS. Generating fresh AI report.")

    # 2. FETCH DATA FROM INDIAN API
    company_data = await fetch_company_data(symbol)
    if not company_data.get("overview"):
        logger.error(f"[{symbol}] Aborting: No financial data found to generate report.")
        raise HTTPException(status_code=404, detail="Company financials not found to generate report.")

    # 3. PREPARE CLAUDE PROMPT
    data_str = json.dumps(company_data)[:4000] 
    
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

    # 4. CALL CLAUDE API
    try:
        logger.info(f"[{symbol}] Triggering Claude 3.5 Sonnet API...")
        response = await client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1500,
            temperature=0.2,
            system=system_instructions,
            messages=[{"role": "user", "content": user_message}]
        )
        report_content = response.content[0].text
        logger.info(f"[{symbol}] Claude API successfully generated the report.")

        # 5. SAVE TO SUPABASE DB
        logger.debug(f"[{symbol}] Saving new report to Supabase DB...")
        new_report = models.AIReportHistory(
            user_id=uuid.UUID(user_id),
            stock_symbol=symbol,
            report_type=report_type,
            content=report_content
        )
        db.add(new_report)
        db.commit()
        logger.info(f"[{symbol}] Report saved successfully to DB.")

        return {"symbol": symbol, "cached": False, "content": report_content}
        
    except Exception as e:
        # Transaction rollback on failure
        db.rollback() 
        logger.exception(f"[{symbol}] FATAL ERROR during AI generation or DB save: {str(e)}") # .exception logs the full stack trace!
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")
    
# DROP TABLE IF EXISTS user_usage CASCADE;
# DROP TABLE IF EXISTS watchlists CASCADE;
# DROP TABLE IF EXISTS subscriptions CASCADE;
# DROP TABLE IF EXISTS ai_reports_history CASCADE;
# DROP TABLE IF EXISTS users CASCADE;