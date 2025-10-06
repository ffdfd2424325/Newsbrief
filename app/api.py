from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text, func, case
from datetime import date
from urllib.parse import urlparse

from .db import get_db
from .models import Article
from .schemas import ArticleOut
from .config import DEFAULT_SOURCES
from .ingest import fetch_and_store

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        # simple DB connectivity check and article count
        count = db.execute(text("SELECT count(*) FROM articles")).scalar() or 0
        return {"status": "ok", "articles": int(count)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"health check failed: {e}")

@router.get("/sources")
def list_sources():
    return [{"key": k, **v} for k, v in DEFAULT_SOURCES.items()]


@router.get("/articles", response_model=List[ArticleOut])
def get_articles(
    sources: Optional[str] = Query(None, description="Comma-separated source keys"),
    q: Optional[str] = Query(None, description="Keyword filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    today_only: bool = Query(True, description="Return only items from today"),
    from_date: Optional[date] = Query(None, description="Filter: from date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="Filter: to date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    # Если есть текстовый запрос — используем FTS5 для лучшей релевантности
    keys: List[str] = []
    if sources:
        keys = [s.strip() for s in sources.split(",") if s.strip()]

    # Normalize date filters
    if today_only:
        from_date = to_date = date.today()

    if q:
        clauses = ["articles_fts MATCH :match"]
        # Quote special queries (e.g., C++, C#) for FTS5 to avoid syntax errors
        safe_q = q
        if any(ch in q for ch in ['"', "'", '+', '-', '*', '(', ')']):
            # escape internal quotes by doubling
            safe_q = '"' + q.replace('"', '""') + '"'
        params = {"match": safe_q}
        if keys:
            in_params = {f"s{i}": k for i, k in enumerate(keys)}
            clauses.append("a.source_key IN (" + ",".join([f":{k}" for k in in_params.keys()]) + ")")
            params.update(in_params)
        if from_date:
            clauses.append("date(a.published_at) >= :from")
            params["from"] = from_date.isoformat()
        if to_date:
            clauses.append("date(a.published_at) <= :to")
            params["to"] = to_date.isoformat()
        params["limit"] = int(limit)
        params["offset"] = int(offset)
        sql = (
            "SELECT a.id FROM articles a "
            "JOIN articles_fts ON articles_fts.rowid = a.id "
            "WHERE " + " AND ".join(clauses) + " "
            "ORDER BY bm25(articles_fts) ASC, a.published_at IS NULL, a.published_at DESC, a.id DESC "
            "LIMIT :limit OFFSET :offset"
        )
        rows = db.execute(text(sql), params).fetchall()
        if not rows:
            return []
        id_order = [r[0] for r in rows]
        items = db.query(Article).filter(Article.id.in_(id_order)).all()
        order_map = {id_: i for i, id_ in enumerate(id_order)}
        items.sort(key=lambda x: order_map.get(x.id, 10**9))
        # annotate reason
        for it in items:
            it.reason = "совпадает с запросом"
        return items

    # Иначе — обычная выдача c простым приоритизатором
    query = db.query(Article)
    if keys:
        query = query.filter(Article.source_key.in_(keys))
    if from_date:
        query = query.filter(func.date(Article.published_at) >= from_date)
    if to_date:
        query = query.filter(func.date(Article.published_at) <= to_date)
    # Простое ранжирование:
    # 1) источники (например, Habr чуть выше)
    # 2) наличие изображения
    # 3) дата (nulls last, desc)
    source_weight = case(
        (Article.source_key == 'habr_dev', 0),
        (Article.source_key.like('habr_%'), 1),
        (Article.source_key == 'vc_all', 2),
        else_=3,
    )
    has_image = case((Article.image_url.isnot(None), 0), else_=1)
    query = query.order_by(source_weight, has_image, Article.published_at.is_(None), Article.published_at.desc(), Article.id.desc())
    items = query.offset(offset).limit(limit).all()
    # annotate reason
    for it in items:
        if today_only:
            it.reason = "новости за сегодня"
        elif from_date or to_date:
            if from_date and to_date:
                it.reason = f"за период {from_date.isoformat()}–{to_date.isoformat()}"
            elif from_date:
                it.reason = f"начиная с {from_date.isoformat()}"
            else:
                it.reason = f"до {to_date.isoformat()}"
        else:
            it.reason = "подходит по источникам/сортировке"
    return items


class RefreshRequest(BaseModel):
    sources: Optional[List[str]] = None  # source keys
    limit_per_source: int = 20
    extra_rss: Optional[List[str]] = None  # user-provided RSS URLs


@router.post("/refresh")
async def refresh_feed(payload: RefreshRequest, db: Session = Depends(get_db)):
    # Validate extra RSS: limit count and URL shape
    extra_rss: List[str] = []
    if payload.extra_rss:
        if len(payload.extra_rss) > 10:
            raise HTTPException(status_code=400, detail="Слишком много RSS ссылок (макс 10)")
        for u in payload.extra_rss:
            u = (u or "").strip()
            if not u:
                continue
            if len(u) > 2048:
                raise HTTPException(status_code=400, detail="Слишком длинный URL")
            pr = urlparse(u)
            if pr.scheme not in {"http", "https"} or not pr.netloc:
                raise HTTPException(status_code=400, detail=f"Некорректный URL: {u}")
            extra_rss.append(u)

    stats = await fetch_and_store(
        db,
        selected_source_keys=payload.sources,
        limit_per_source=payload.limit_per_source,
        extra_rss=extra_rss,
    )
    return {"status": "ok", "added": stats}
