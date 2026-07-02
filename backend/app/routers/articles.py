from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import get_current_user
from ..schemas import ArticleCreate, ArticleUpdate, ArticleOut, StockTransactionOut
from ..models import Article, StockTransaction, StockTransactionType, User

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("", response_model=List[ArticleOut])
def list_articles(
    q: Optional[str] = Query(None),
    low_stock: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Article)
    if q:
        query = query.filter(
            Article.name.ilike(f"%{q}%") |
            Article.article_number.ilike(f"%{q}%") |
            Article.barcode.ilike(f"%{q}%") |
            Article.supplier.ilike(f"%{q}%") |
            Article.location.ilike(f"%{q}%")
        )
    if low_stock:
        query = query.filter(Article.stock_quantity <= Article.min_stock)
    return query.order_by(Article.name).all()


@router.post("", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
def create_article(
    body: ArticleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    article = Article(**body.model_dump())
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


@router.get("/{article_id}", response_model=ArticleOut)
def get_article(
    article_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Artikel ej hittad")
    return article


@router.put("/{article_id}", response_model=ArticleOut)
def update_article(
    article_id: int,
    body: ArticleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Artikel ej hittad")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(article, field, value)
    db.commit()
    db.refresh(article)
    return article


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Artikel ej hittad")
    db.delete(article)
    db.commit()


@router.get("/{article_id}/transactions", response_model=List[StockTransactionOut])
def get_transactions(
    article_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return (
        db.query(StockTransaction)
        .filter(StockTransaction.article_id == article_id)
        .order_by(StockTransaction.created_at.desc())
        .limit(100)
        .all()
    )


@router.post("/{article_id}/adjust", response_model=ArticleOut)
def adjust_stock(
    article_id: int,
    quantity: Decimal,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Artikel ej hittad")
    article.stock_quantity += quantity
    tx = StockTransaction(
        article_id=article_id,
        quantity=quantity,
        transaction_type=StockTransactionType.justering,
        user_id=current_user.id,
        notes=notes,
    )
    db.add(tx)
    db.commit()
    db.refresh(article)
    return article
