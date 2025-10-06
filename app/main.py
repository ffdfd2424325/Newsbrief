import os
import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .db import Base, engine, SessionLocal
from .api import router as api_router
from .config import REFRESH_MINUTES
from .ingest import fetch_and_store
from .fts import setup_fts
from .migrate import ensure_schema_updates
from .bot import BOT_TOKEN


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB
    Base.metadata.create_all(bind=engine)
    # Apply lightweight schema migrations (e.g., add image_url)
    ensure_schema_updates(engine)
    # Initialize FTS5 virtual table and triggers
    setup_fts(engine)

    # Start background scheduler task (disabled for debugging)
    # async def scheduler():
    #     while True:
    #         try:
    #             db: Session = SessionLocal()
    #             await fetch_and_store(db)
    #         except asyncio.CancelledError:
    #             break
    #         except Exception as e:
    #             print("Ingest error:", e)
    #         finally:
    #             try:
    #                 db.close()
    #             except Exception:
    #                 pass
    #         try:
    #             await asyncio.sleep(REFRESH_MINUTES * 60)
    #             break

    # task = asyncio.create_task(scheduler())
# Асинхронная функция для запуска бота как отдельного процесса
import subprocess
import sys
import os

def start_bot_process():
    """Запуск бота как отдельного процесса"""
    try:
        # Получаем токен из окружения
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            print("⚠️ TELEGRAM_BOT_TOKEN не найден")
            return None
        
        print("🤖 Запуск Telegram бота как отдельного процесса...")
        
        # Запускаем бота в отдельном процессе
        process = subprocess.Popen([
            sys.executable, "-m", "app.bot"
        ], cwd=os.getcwd())
        
        print(f"✅ Бот запущен с PID: {process.pid}")
        return process
        
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")
        return None

# Запуск Telegram бота в фоне
bot_process = None
if BOT_TOKEN:
    try:
        bot_process = start_bot_process()
        if bot_process:
            print(f"🤖 Telegram бот запущен с токеном: {BOT_TOKEN[:10]}...")
        else:
            print("❌ Не удалось запустить бота")
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
else:
    print("⚠️ TELEGRAM_BOT_TOKEN не настроен - бот отключен")

try:
    yield
finally:
    # Остановка бота при завершении приложения
    if bot_process:
        print("🛑 Остановка бота...")
        bot_process.terminate()
        bot_process.wait()
        print("✅ Бот остановлен")
    print("🛑 Приложение остановлено")



app = FastAPI(lifespan=lifespan, title="NewsBrief")
allow_origins = os.getenv("ALLOW_ORIGINS", "").strip()
if allow_origins:
    origins = [o.strip() for o in allow_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
app.include_router(api_router, prefix="/api")
# Mount static directory relative to the project root
_ROOT = Path(__file__).resolve().parents[1]
_STATIC_DIR = str((_ROOT / "static").resolve())
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
