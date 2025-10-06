from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class ArticleOut(BaseModel):
    id: int
    title: str
    url: str
    source_key: str
    source_title: str
    summary: Optional[str] = None
    snippet: Optional[str] = None
    image_url: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    reason: Optional[str] = None

    class Config:
        from_attributes = True
