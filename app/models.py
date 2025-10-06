from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from .db import Base


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(512), nullable=False)
    url = Column(String(1024), unique=True, nullable=False)
    source_key = Column(String(128), index=True, nullable=False)
    source_title = Column(String(256), nullable=False)
    summary = Column(Text, nullable=True)
    snippet = Column(Text, nullable=True)
    image_url = Column(String(1024), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dedup_key = Column(String(64), index=True, nullable=True)


Index("ix_articles_source_time", Article.source_key, Article.published_at.desc())


# Telegram bot user preferences
class UserPref(Base):
    __tablename__ = "user_prefs"

    chat_id = Column(Integer, primary_key=True, index=True)
    # period: one of ["24h", "week", "month"], nullable for default
    period = Column(String(16), nullable=True)
    # Comma-separated list of selected source keys
    sources_csv = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

