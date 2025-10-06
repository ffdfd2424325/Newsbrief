from sqlalchemy import text
from sqlalchemy.engine import Engine

DDL_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
  title, summary, snippet,
  content='articles', content_rowid='id'
);
"""

DDL_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
      INSERT INTO articles_fts(rowid, title, summary, snippet)
      VALUES (new.id, new.title, new.summary, new.snippet);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
      INSERT INTO articles_fts(articles_fts, rowid, title, summary, snippet)
      VALUES('delete', old.id, old.title, old.summary, old.snippet);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
      INSERT INTO articles_fts(articles_fts, rowid, title, summary, snippet)
      VALUES('delete', old.id, old.title, old.summary, old.snippet);
      INSERT INTO articles_fts(rowid, title, summary, snippet)
      VALUES (new.id, new.title, new.summary, new.snippet);
    END;
    """,
]


def setup_fts(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text(DDL_CREATE_FTS))
        for ddl in DDL_TRIGGERS:
            conn.execute(text(ddl))
        # Backfill existing rows if FTS table is empty
        count = conn.execute(text("SELECT count(*) FROM articles_fts")).scalar() or 0
        if count == 0:
            conn.execute(
                text(
                    "INSERT INTO articles_fts(rowid, title, summary, snippet) "
                    "SELECT id, title, summary, snippet FROM articles"
                )
            )
        conn.commit()
