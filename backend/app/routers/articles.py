import io
import time
from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import get_current_user
from ..schemas import ArticleCreate, ArticleUpdate, ArticleOut, StockTransactionOut, ArticleImportResult
from ..models import Article, StockTransaction, StockTransactionType, User, WorkOrderLine, PickListLine

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("", response_model=List[ArticleOut])
def list_articles(
    q: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
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
    return query.order_by(Article.name).offset(offset).limit(limit).all()


def _wipe_articles(db: Session):
    """Tömmer artikelregistret utan att förstöra befintliga rader.

    Alla rader som pekar på en artikel (delar/arbetsorder, inköpsrader, plockrader
    och skanningar) behålls intakta – vi nollar bara deras article_id så att raderna
    står kvar med sin benämning/art.nr. Detta måste ske för samtliga tabeller innan
    artiklarna raderas, annars stoppar en FK-referens raderingen (HTTP 500).
    """
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    cur.execute("UPDATE work_order_lines SET article_id = NULL WHERE article_id IN (SELECT id FROM articles)")
    cur.execute("UPDATE pick_list_lines SET article_id = NULL WHERE article_id IN (SELECT id FROM articles)")
    cur.execute("UPDATE purchase_lines SET article_id = NULL WHERE article_id IN (SELECT id FROM articles)")
    cur.execute("DELETE FROM stock_transactions")
    cur.execute("DELETE FROM articles")
    raw_conn.commit()
    cur.close()


@router.delete("/all", status_code=status.HTTP_204_NO_CONTENT)
def clear_all_articles(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _wipe_articles(db)


@router.post("/import-excel", response_model=ArticleImportResult)
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Skriver över hela lagret med artiklar från en uppladdad Excel-fil.

    Förväntade kolumner (SBT-artikellista): Artikelkod, Benämning, ... Företag (kol M), Lagerplats.
    """
    import openpyxl

    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception:
        raise HTTPException(400, "Kunde inte läsa Excel-filen")
    ws = wb.worksheets[0]

    t0 = time.time()
    rows_out = []
    seen = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 13:
            continue
        code, name, company, location = row[0], row[1], row[12], row[9]
        if not code or not name:
            continue
        code = str(code).strip()
        dedup_key = code.upper()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        clean = lambda v: (str(v).strip() if v else "").replace("\t", " ").replace("\r", " ").replace("\n", " ").replace('"', "'")
        rows_out.append((clean(code), clean(name) or "Okänd artikel", clean(company), clean(location)))

    if not rows_out:
        raise HTTPException(400, "Inga giltiga rader hittades i filen")

    buf = io.StringIO()
    for code, name, company, location in rows_out:
        buf.write("\t".join([code, name, company, location]) + "\n")
    buf.seek(0)

    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    cur.execute("CREATE TEMP TABLE _articles_stage (article_number text, name text, supplier text, location text)")
    cur.copy_expert(
        "COPY _articles_stage (article_number, name, supplier, location) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '')",
        buf,
    )
    _wipe_articles(db)
    cur.execute("""
        INSERT INTO articles (article_number, name, supplier, location, unit, price, stock_quantity, min_stock, created_at)
        SELECT NULLIF(article_number, ''), name, NULLIF(supplier, ''), NULLIF(location, ''), 'st', 0, 0, 0, NOW()
        FROM _articles_stage
    """)
    raw_conn.commit()
    cur.close()

    return ArticleImportResult(imported=len(rows_out), seconds=round(time.time() - t0, 1))


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
    for field, value in body.model_dump(exclude_unset=True).items():
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
    # article_id är NOT NULL på stock_transactions och refereras från order-/plockrader
    # utan cascade – städa referenserna innan artikeln tas bort
    db.query(StockTransaction).filter(StockTransaction.article_id == article_id).delete(synchronize_session=False)
    db.query(WorkOrderLine).filter(WorkOrderLine.article_id == article_id).update(
        {WorkOrderLine.article_id: None}, synchronize_session=False
    )
    db.query(PickListLine).filter(PickListLine.article_id == article_id).update(
        {PickListLine.article_id: None}, synchronize_session=False
    )
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
