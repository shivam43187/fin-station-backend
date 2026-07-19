from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from typing import List, Optional
from uuid import UUID

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/watchlist",
    tags=["Watchlist"]
)

# 1. ADD TO WATCHLIST
@router.post("/", response_model=schemas.WatchlistResponse)
def add_to_watchlist(user_id: UUID, item: schemas.WatchlistCreate, db: Session = Depends(get_db)):
    # Check if stock already exists for this user
    existing_item = db.query(models.Watchlist).filter(
        models.Watchlist.user_id == user_id,
        models.Watchlist.stock_symbol == item.stock_symbol
    ).first()
    
    if existing_item:
        raise HTTPException(status_code=400, detail="Stock already in watchlist")

    new_watchlist_item = models.Watchlist(
        user_id=user_id,
        stock_symbol=item.stock_symbol
    )
    db.add(new_watchlist_item)
    db.commit()
    db.refresh(new_watchlist_item)
    return new_watchlist_item

# 2. GET WATCHLIST (With Pagination, Search, and Sort)
@router.get("/{user_id}", response_model=List[schemas.WatchlistResponse])
def get_user_watchlist(
    user_id: UUID,
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0, description="Kitne items skip karne hain (Pagination)"),
    limit: int = Query(10, le=100, description="Max kitne items chahiye"),
    search: Optional[str] = Query(None, description="Stock symbol search query"),
    sort_by: str = Query("added_at_desc", description="Sort order: added_at_desc, added_at_asc, symbol_asc")
):
    # Base query for the specific user
    query = db.query(models.Watchlist).filter(models.Watchlist.user_id == user_id)

    # Apply Search (if user types 'REL', it will match 'RELIANCE')
    if search:
        search_term = f"%{search.upper()}%"
        query = query.filter(models.Watchlist.stock_symbol.ilike(search_term))

    # Apply Sorting
    if sort_by == "added_at_desc":
        query = query.order_by(desc(models.Watchlist.added_at))
    elif sort_by == "added_at_asc":
        query = query.order_by(asc(models.Watchlist.added_at))
    elif sort_by == "symbol_asc":
        query = query.order_by(asc(models.Watchlist.stock_symbol))
    
    # Apply Pagination and execute
    watchlist_items = query.offset(skip).limit(limit).all()
    return watchlist_items

# 3. DELETE FROM WATCHLIST
@router.delete("/{watchlist_id}")
def remove_from_watchlist(watchlist_id: UUID, db: Session = Depends(get_db)):
    item = db.query(models.Watchlist).filter(models.Watchlist.id == watchlist_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    db.delete(item)
    db.commit()
    return {"message": "Stock removed from watchlist successfully"}