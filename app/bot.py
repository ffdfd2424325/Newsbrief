import os
import asyncio
from typing import List, Optional, Dict, Tuple
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# DB imports for persisting user preferences
from sqlalchemy.orm import Session
from .db import SessionLocal, engine, Base
from .models import UserPref

load_dotenv()

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")
SITE_BASE = os.getenv("SITE_BASE", "http://127.0.0.1:8000").rstrip("/")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_TOP = int(os.getenv("BOT_TOP_LIMIT", "5"))


def _period_params(period: str) -> Dict[str, str]:
    today = date.today()
    p = period.lower()
    if p in {"24h", "day", "today", "сегодня"}:
        return {"today_only": "true"}
    if p in {"week", "неделя"}:
        start = today - timedelta(days=7)
        return {"today_only": "false", "from_date": start.isoformat(), "to_date": today.isoformat()}
    if p in {"month", "месяц"}:
        start = today - timedelta(days=30)
        return {"today_only": "false", "from_date": start.isoformat(), "to_date": today.isoformat()}
    # default
    return {"today_only": "true"}


async def _fetch_articles(limit: int = 10, q: Optional[str] = None, period: str = "24h", sources: Optional[List[str]] = None) -> List[dict]:
    params: Dict[str, str] = {"limit": str(limit), "offset": "0"}
    params.update(_period_params(period))
    if q:
        params["q"] = q
    if sources:
        params["sources"] = ",".join(sources)
    url = f"{API_BASE}/api/articles"
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0, read=15.0)) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []


def _format_article(a: dict, idx: int) -> str:
    title = a.get("title") or "📰 Без заголовка"
    url = a.get("url") or ""
    source = a.get("source_title") or a.get("source_key") or "Неизвестный источник"
    summary = a.get("summary") or a.get("snippet") or ""
    if summary and len(summary) > 400:
        summary = summary[:400].rstrip() + "…"

    # Красивое форматирование с эмодзи
    line1 = f"<b>📰 {idx}. {title}</b>"
    line2 = f"<i>📌 Источник: {source}</i>"

    # Добавляем дату если есть
    published_at = a.get("published_at")
    if published_at:
        line2 += f" • 🕐 {published_at[:10]}"  # Только дата

    line3 = f"\n{summary}" if summary else ""

    parts = [line1, line2]
    if line3:
        parts.append(line3)

    return "\n".join(parts)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "🌟 <b>Добро пожаловать в NewsBrief!</b> 🌟\n\n"
        "📰 <b>Ваш персональный агрегатор новостей</b>\n\n"
        "📱 Здесь вы можете:\n"
        "• Читать свежие новости из проверенных источников\n"
        "• Искать новости по ключевым словам\n"
        "• Выбирать интересующие вас источники\n"
        "• Получать красивые карточки с изображениями\n\n"
        "🚀 <b>Выберите период новостей:</b>"
    )

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=_main_keyboard()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


# In-memory cache for chat preferences (write-through to DB)
CHAT_PREFS: Dict[int, str] = {}
CHAT_SOURCES: Dict[int, List[str]] = {}
SOURCES_CACHE: List[Dict[str, str]] = []  # list of {key,title,...}


def _db_session() -> Session:
    return SessionLocal()


def _load_prefs(chat_id: int) -> None:
    """Hydrate in-memory caches from DB if present."""
    if chat_id in CHAT_PREFS and chat_id in CHAT_SOURCES:
        return
    with _db_session() as db:
        rec = db.query(UserPref).filter(UserPref.chat_id == chat_id).first()
        if rec:
            if chat_id not in CHAT_PREFS and rec.period:
                CHAT_PREFS[chat_id] = rec.period
            if chat_id not in CHAT_SOURCES and rec.sources_csv:
                CHAT_SOURCES[chat_id] = [s for s in (rec.sources_csv or '').split(',') if s]


def _save_period(chat_id: int, period: str) -> None:
    CHAT_PREFS[chat_id] = period
    with _db_session() as db:
        rec = db.query(UserPref).filter(UserPref.chat_id == chat_id).first()
        if not rec:
            rec = UserPref(chat_id=chat_id, period=period, sources_csv=None)
            db.add(rec)
        else:
            rec.period = period
        db.commit()


def _get_sources_list(chat_id: int) -> List[str]:
    _load_prefs(chat_id)
    return CHAT_SOURCES.get(chat_id, [])


def _set_sources_list(chat_id: int, arr: List[str]) -> None:
    CHAT_SOURCES[chat_id] = list(arr or [])
    with _db_session() as db:
        rec = db.query(UserPref).filter(UserPref.chat_id == chat_id).first()
        csv = ','.join([s for s in arr if s]) if arr else None
        if not rec:
            rec = UserPref(chat_id=chat_id, period=CHAT_PREFS.get(chat_id), sources_csv=csv)
            db.add(rec)
        else:
            rec.sources_csv = csv
        db.commit()


def _get_period(update: Update) -> str:
    chat_id = update.effective_chat.id if update.effective_chat else 0
    _load_prefs(chat_id)
    return CHAT_PREFS.get(chat_id, "24h")


def _set_period(update: Update, val: str) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else 0
    _save_period(chat_id, val)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📰 Последние новости", callback_data="show:24h"),
        ],
        [
            InlineKeyboardButton("📅 Новости за неделю", callback_data="show:week"),
        ],
        [
            InlineKeyboardButton("📆 Новости за месяц", callback_data="show:month"),
        ],
        [
            InlineKeyboardButton("🔍 Поиск по новостям", callback_data="search"),
        ],
        [
            InlineKeyboardButton("🧰 Настроить источники", callback_data="sources"),
        ],
    ])

def _search_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")]
    ])


def _sources_keyboard(sources: List[Dict[str, str]], current: set) -> InlineKeyboardMarkup:
    rows = []
    row: List[InlineKeyboardButton] = []
    for s in sources or []:
        key = s.get("key") or ""
        title = s.get("title") or key
        mark = "✅" if key in current else "◻"
        btn = InlineKeyboardButton(f"{mark} {title}", callback_data=f"src:{key}")
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Готово", callback_data="src_done")])
    return InlineKeyboardMarkup(rows)


async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = _get_period(update)
    await update.message.reply_text(f"Текущий период: {p}", reply_markup=_main_keyboard())


def _parse_top_args(args: List[str]) -> Tuple[int, Optional[str], Optional[str]]:
    limit = DEFAULT_TOP
    q = None
    period = None
    if args:
        if args[0].isdigit():
            limit = max(1, min(20, int(args[0])))
            rest = args[1:]
        else:
            rest = args
        for t in rest:
            tl = t.lower()
            if tl in {"24h", "day", "today", "сегодня", "неделя", "week", "месяц", "month"}:
                period = tl
        if rest:
            # detect period keywords
            joined = " ".join(rest).strip()
            tokens = [t.strip() for t in joined.split() if t.strip()]
            for t in tokens:
                tl = t.lower()
                if tl in {"24h", "day", "today", "сегодня", "неделя", "week", "месяц", "month"}:
                    period = tl
            if period:
                q = " ".join([t for t in tokens if t.lower() not in {period}]) or None
            else:
                q = joined or None
    return limit, q, period


async def show_news(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str = "24h", search_query: str = None) -> None:
    try:
        chat_id = update.effective_chat.id
        sel = _get_sources_list(chat_id)
        items = await _fetch_articles(limit=10, q=search_query, period=period, sources=sel)
        if not items:
            empty_messages = [
                "📭 По вашему запросу ничего не найдено.\n\nПопробуйте:\n• Другие ключевые слова\n• Более широкий период времени\n• Проверить источники",
                "🤷‍♂️ Новости не найдены!\n\nВозможно:\n• Измените поисковый запрос\n• Выберите другой период\n• Проверьте выбранные источники",
                "🔍 Результаты не найдены\n\nСоветы:\n• Попробуйте синонимы\n• Уменьшите количество слов в запросе\n• Выберите более широкий период"
            ]
            import random
            empty_text = random.choice(empty_messages)

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=empty_text,
                reply_markup=_main_keyboard()
            )
            return
            
        period_text = {
            "24h": "свежих новостей за последние 24 часа 📰",
            "week": "новостей за неделю 📅",
            "month": "новостей за месяц 📆"
        }.get(period, "новостей")

        header = f"📰 <b>Последние {period_text}</b>"
        if search_query:
            header = f"🔍 <b>Результаты поиска: «{search_query}»</b>"
            
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=header,
            parse_mode=ParseMode.HTML
        )

        for i, article in enumerate(items, 1):
            text = _format_article(article, i)
            buttons = []
            if article.get("url"):
                buttons.append(InlineKeyboardButton("📖 Читать статью", url=article["url"]))

            # Prefer sending photo when available to improve UX
            image_url = article.get("image_url")
            reply_kb = InlineKeyboardMarkup([buttons]) if buttons else None
            if image_url:
                try:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=image_url,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_kb,
                        has_spoiler=False,
                    )
                    continue
                except BadRequest:
                    # fall back to text message if photo cannot be sent
                    pass

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
                reply_markup=reply_kb,
            )

        # Show main menu after last article
        if items:
            menu_text = (
                f"✅ Показаны {len(items)} новостей\n\n"
                "🎯 Что дальше?\n"
                "• Выберите другой период\n"
                "• Используйте поиск по ключевым словам\n"
                "• Настройте источники новостей"
            )

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=menu_text,
                reply_markup=_main_keyboard()
            )

    except Exception as e:
        error_messages = [
            "❌ Произошла ошибка при получении новостей.\n\nПопробуйте:\n• Выбрать другой период времени\n• Проверить подключение к интернету\n• Попробовать позже",
            "⚠️ Что-то пошло не так!\n\nВозможные причины:\n• Проблемы с источниками новостей\n• Временные технические неполадки\n• Проверьте подключение к интернету",
            "🚫 Ошибка загрузки новостей\n\nПопробуйте:\n• Перезапустить бота командой /start\n• Выбрать другой период новостей\n• Попробовать позже"
        ]
        import random
        error_text = random.choice(error_messages)

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=error_text,
            reply_markup=_main_keyboard()
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок для graceful завершения"""
    try:
        if update and hasattr(update, 'effective_chat') and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Произошла техническая ошибка. Попробуйте позже или перезапустите бота командой /start",
                reply_markup=_main_keyboard()
            )
    except Exception:
        pass  # Игнорируем ошибки в обработчике ошибок

    # Логируем ошибку для отладки
    print(f"Bot error: {context.error}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if SEARCH_STATE.get(chat_id):
        SEARCH_STATE.pop(chat_id, None)
        await show_news(update, context, period="24h", search_query=text)
    else:
        await start(update, context)


# Store search state per chat
SEARCH_STATE: Dict[int, bool] = {}

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data:
        return

    # Проверяем что callback query не устарел
    if not q.message:
        print("Received callback query for deleted message")
        return

    chat_id = update.effective_chat.id
    data = q.data

    try:
        if data == "search":
            SEARCH_STATE[chat_id] = True
            # Try to remove previous inline keyboard to not confuse the user
            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except BadRequest:
                pass
            await q.message.reply_text(
                "🔍 <b>Поиск новостей</b>\n\n"
                "Напишите ключевые слова для поиска новостей.\n"
                "Например:\n"
                "• Python программирование\n"
                "• Искусственный интеллект\n"
                "• Машинное обучение\n"
                "• Веб-разработка\n\n"
                "<i>Поиск будет выполнен по всем активным источникам новостей.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ForceReply(selective=True)
            )
            await q.answer()
            return

        if data == "cancel_search":
            SEARCH_STATE.pop(chat_id, None)
            await q.message.reply_text(
                "❌ Поиск отменен.\n\nВыберите период новостей или попробуйте другие функции:",
                reply_markup=_main_keyboard()
            )
            await q.answer()
            return

        if data.startswith("show:"):
            period = data.split(":", 1)[1]
            await show_news(update, context, period)
            await q.answer()
            return

        # Sources menu
        if data == "sources":
            # fetch sources from API if cache empty
            if not SOURCES_CACHE:
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0, read=10.0)) as client:
                        r = await client.get(f"{API_BASE}/api/sources")
                        r.raise_for_status()
                        arr = r.json()
                        if isinstance(arr, list):
                            SOURCES_CACHE.clear()
                            SOURCES_CACHE.extend(arr)
                except Exception as e:
                    print(f"Error fetching sources: {e}")
                    await q.answer("❌ Ошибка загрузки источников")
                    return

            current = set(_get_sources_list(chat_id))
            kb = _sources_keyboard(SOURCES_CACHE, current)
            await q.message.edit_text(
                "🧰 <b>Настройка источников новостей</b>\n\n"
                "Выберите источники, новости которых хотите получать:\n"
                "• ✅ - источник включен\n"
                "• ◻ - источник отключен\n\n"
                "<i>Вы можете включить/отключить любой источник.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb
            )
            await q.answer()
            return

        if data.startswith("src:"):
            key = data.split(":", 1)[1]
            cur = set(_get_sources_list(chat_id))
            if key in cur:
                cur.remove(key)
            else:
                cur.add(key)
            _set_sources_list(chat_id, list(cur))
            kb = _sources_keyboard(SOURCES_CACHE, cur)
            try:
                await q.edit_message_reply_markup(reply_markup=kb)
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    # Message content is the same, just answer without editing
                    await q.answer()
                    return
                # fallback: re-send text with keyboard
                await q.message.edit_text(
                    "🧰 <b>Настройка источников новостей</b>\n\n"
                    "Выберите источники, новости которых хотите получать:\n"
                    "• ✅ - источник включен\n"
                    "• ◻ - источник отключен\n\n"
                    "<i>Вы можете включить/отключить любой источник.</i>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb
                )
            await q.answer()
            return

        if data == "src_done":
            sel = _get_sources_list(chat_id)
            if sel:
                sources_text = f"✅ Выбрано {len(sel)} источников новостей"
            else:
                sources_text = "📋 Выбраны все доступные источники"

            await q.message.edit_text(
                f"{sources_text}\n\n"
                "🎯 Теперь вы будете получать новости только из выбранных источников.\n\n"
                "Попробуйте посмотреть новости или изменить период!",
                reply_markup=_main_keyboard()
            )
            await q.answer()
            return

    except Exception as e:
        print(f"Error in callback handler: {e}")
        try:
            await q.answer("❌ Произошла ошибка")
        except Exception:
            pass


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в окружении")
    # Ensure DB schema exists (includes user_prefs)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))  # Reuse start as help
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Бот запущен и готов к работе!")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
