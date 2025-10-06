import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Scheduling
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "15"))

# Project root and DB path
_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = (_ROOT / "newsbrief.db").as_posix()
SQLITE_PATH = os.getenv("SQLITE_PATH", _DEFAULT_DB)
DATABASE_URL = f"sqlite:///{SQLITE_PATH}"

# Исходная рабочая конфигурация источников (восстановлена полностью)
DEFAULT_SOURCES = {
    # VC.ru
    "vc_all": {
        "title": "VC.ru — Все",
        "type": "rss",
        "url": "https://vc.ru/rss/all",
        "enabled": True,
    },
    # Habr (все разделы как было изначально)
    "habr_dev": {
        "title": "Habr — Разработка",
        "type": "rss",
        "url": "https://habr.com/ru/rss/hub/develop/",
        "enabled": True,
    },
    "habr_ai": {
        "title": "Habr — Искусственный интеллект",
        "type": "rss",
        "url": "https://habr.com/ru/rss/hub/artificial_intelligence/",
        "enabled": True,
    },
    "habr_infosec": {
        "title": "Habr — Информационная безопасность",
        "type": "rss",
        "url": "https://habr.com/ru/rss/hub/infosecurity/",
        "enabled": True,
    },
    "habr_management": {
        "title": "Habr — Управление IT",
        "type": "rss",
        "url": "https://habr.com/ru/rss/hub/management/",
        "enabled": True,
    },
    # Tproger (RU)
    "tproger": {
        "title": "Tproger",
        "type": "rss",
        "url": "https://tproger.ru/feed",
        "enabled": True,
    },
    # 3DNews (RU)
    "3dnews": {
        "title": "3DNews — Новости",
        "type": "rss",
        "url": "https://3dnews.ru/news/rss",
        "enabled": True,
    },
}
