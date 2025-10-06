from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_schema_updates(engine: Engine) -> None:
    """Apply lightweight in-place migrations for SQLite.
    - Add image_url column to articles if missing
    """
    with engine.connect() as conn:
        cols = conn.execute(text("PRAGMA table_info(articles)")).fetchall()
        col_names = {c[1] for c in cols}
        if "image_url" not in col_names:
            conn.execute(text("ALTER TABLE articles ADD COLUMN image_url VARCHAR(1024)"))
        conn.commit()
