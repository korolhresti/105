# webapp.py — FastAPI backend для Telegram AI News бота з підтримкою 500+ функцій

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import os
import asyncpg
import json
import random # Для мокованих AI функцій
import asyncio # Для асинхронних черг
import logging

# Aiogram імпорти
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# from aiogram.utils.executor import start_webhook # Використовуємо start_webhook для запуску бота
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_webhook

from dotenv import load_dotenv

load_dotenv()

# Налаштування логування
logging.basicConfig(level=logging.INFO)

# ==== DATABASE CONNECTION ====
DATABASE_URL = os.getenv("DATABASE_URL")

async def get_db_connection():
    """Функція для отримання з'єднання з базою даних."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logging.error(f"Помилка підключення до бази даних: {e}")
        raise HTTPException(status_code=500, detail="Помилка підключення до бази даних")

# ==== MODELS ====
class SummaryRequest(BaseModel):
    news_id: Optional[int] = None
    text: Optional[str] = None

class FeedbackRequest(BaseModel):
    user_id: int
    message: str

class RateRequest(BaseModel):
    user_id: int
    news_id: int
    value: int

class BlockRequest(BaseModel):
    user_id: int
    block_type: str # tag, source, language, category
    value: str

class DigestRequest(BaseModel):
    user_id: int
    frequency: Optional[str] = 'daily'

class AnalyticsRequest(BaseModel):
    user_id: int

class ReportRequest(BaseModel):
    user_id: int
    news_id: Optional[int] = None
    reason: str

class UserRegisterRequest(BaseModel):
    user_id: int
    language: Optional[str] = None
    country: Optional[str] = None
    safe_mode: Optional[bool] = None
    current_feed_id: Optional[int] = None
    is_premium: Optional[bool] = None
    email: Optional[str] = None
    auto_notifications: Optional[bool] = None
    view_mode: Optional[str] = None

class FilterUpdateRequest(BaseModel):
    user_id: int
    tag: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    content_type: Optional[str] = None

class NewsAddRequest(BaseModel):
    title: str
    content: str
    lang: str
    country: str
    tags: List[str]
    source: str
    link: Optional[str] = None
    file_id: Optional[str] = None
    media_type: Optional[str] = None

class SourceAddRequest(BaseModel):
    user_id: int
    name: str
    link: str
    type: str

class BookmarkAddRequest(BaseModel):
    user_id: int
    news_id: int

class CommentAddRequest(BaseModel):
    user_id: int
    news_id: int
    content: str

class CustomFeedCreateRequest(BaseModel):
    user_id: int
    feed_name: str
    filters: Dict[str, Any]

class CustomFeedSwitchRequest(BaseModel):
    user_id: int
    feed_id: int

class SubscriptionUpdateRequest(BaseModel):
    user_id: int
    frequency: str

class InviteGenerateRequest(BaseModel):
    inviter_user_id: int

class InviteAcceptRequest(BaseModel):
    invite_code: str
    invited_user_id: int

class RewriteHeadlineRequest(BaseModel):
    text: str

# ==== Telegram Bot Setup ====
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8000")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBAPP_URL}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage() # Використовуємо MemoryStorage для Aiogram v3+
dp = Dispatcher(storage=storage)

MONOBANK_CARD_NUMBER = os.getenv("MONOBANK_CARD_NUMBER", "XXXX XXXX XXXX XXXX")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot_username") # Для посилання-запрошення

# ==== STATES (Стани для FSM) ====
class AddSourceStates(StatesGroup):
    """Стани для додавання нового джерела."""
    waiting_for_source_name = State()
    waiting_for_source_link = State()
    waiting_for_source_type = State()

class AddNewsStates(StatesGroup): # Для адмінів/контент-мейкерів
    """Стани для додавання нової новини вручну."""
    waiting_for_title = State()
    waiting_for_content = State()
    waiting_for_lang = State()
    waiting_for_country = State()
    waiting_for_tags = State()
    waiting_for_source_name = State()
    waiting_for_link = State()
    waiting_for_media = State() # Photo/file_id

class SearchNewsStates(StatesGroup):
    """Стан для пошуку новин."""
    waiting_for_search_query = State()

class ReportNewsStates(StatesGroup):
    """Стан для відправки скарг."""
    waiting_for_report_reason = State()
    waiting_for_news_id_for_report = State()

class FeedbackStates(StatesGroup):
    """Стан для відправки відгуків."""
    waiting_for_feedback_message = State()

class FilterStates(StatesGroup):
    """Стани для налаштування фільтрів."""
    waiting_for_filter_tag = State()
    waiting_for_filter_category = State()
    waiting_for_filter_source = State()
    waiting_for_filter_language = State()
    waiting_for_filter_country = State()
    waiting_for_filter_content_type = State()

class CustomFeedStates(StatesGroup):
    """Стани для управління персональними добірками."""
    waiting_for_feed_name = State()
    waiting_for_feed_filters_tags = State()
    waiting_for_feed_filters_sources = State()
    waiting_for_feed_filters_languages = State()

class ProfileSettingsStates(StatesGroup):
    """Стани для налаштувань профілю користувача."""
    waiting_for_language_change = State()
    waiting_for_country_change = State()
    waiting_for_email = State()
    waiting_for_view_mode = State()

# Функція для екранування тексту для MarkdownV2
def escape_markdown_v2(text: str) -> str:
    """
    Екранує спеціальні символи MarkdownV2 у наданому тексті.
    """
    if not isinstance(text, (str, int, float)):
        text = str(text)

    # Список символів, які потребують екранування в MarkdownV2
    # https://core.telegram.org/bots/api#markdownv2-style
    # Важливо: зворотний слеш `\` сам по собі потребує екранування
    special_chars = [
        '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+',
        '-', '=', '|', '{', '}', '.', '!'
    ]
    
    escaped_text = text
    for char in special_chars:
        # Екрануємо символ, якщо він є в тексті, подвійним зворотним слешем
        # щоб уникнути SyntaxWarning у f-рядках, де `\` вже є спецсимволом
        escaped_text = escaped_text.replace(char, '\\' + char)
    
    # Спеціальна обробка для символів, які можуть бути частиною URL, але також є спецсимволами MDV2
    # Це спроба зробити URL більш "безпечними" без надмірного екранування
    if 'http' in text or 'https' in text:
        # Не екрануємо `/` у URL
        escaped_text = escaped_text.replace('\\/', '/')
        # Можна додати інші винятки, якщо це викликає проблеми з URL
    
    return escaped_text

# ==== ДОПОМІЖНІ ФУНКЦІЇ БД ====
async def update_user_stats(conn, user_id: int, action: str):
    """Оновлює статистику користувача."""
    try:
        if action == "viewed":
            await conn.execute("INSERT INTO user_stats (user_id, viewed, last_active) VALUES ($1, 1, NOW()) ON CONFLICT (user_id) DO UPDATE SET viewed = user_stats.viewed + 1, last_active = NOW()", user_id)
        elif action == "saved":
            await conn.execute("INSERT INTO user_stats (user_id, saved, last_active) VALUES ($1, 1, NOW()) ON CONFLICT (user_id) DO UPDATE SET saved = user_stats.saved + 1, last_active = NOW()", user_id)
        elif action == "reported":
            await conn.execute("INSERT INTO user_stats (user_id, reported, last_active) VALUES ($1, 1, NOW()) ON CONFLICT (user_id) DO UPDATE SET reported = user_stats.reported + 1, last_active = NOW()", user_id)
        # Додайте інші дії за потреби
    except Exception as e:
        logging.error(f"Помилка при оновленні статистики користувача {user_id} для дії {action}: {e}")

# ==== API ENDPOINTS ====

@app.post("/summary")
async def generate_summary_api(req: SummaryRequest):
    """Генерує AI-резюме для новини або наданого тексту."""
    # Це мокова функція. В реальності тут буде виклик до моделі AI.
    if req.news_id:
        # Fetch news content from DB based on news_id
        conn = await get_db_connection()
        try:
            news = await conn.fetchrow("SELECT content FROM news WHERE id = $1", req.news_id)
            if news:
                content = news['content']
                # Моковане резюме
                summary = f"AI-генероване резюме для новини #{req.news_id} на основі контенту: {content[:100]}..."
                return {"summary": summary}
            else:
                raise HTTPException(status_code=404, detail="Новину не знайдено.")
        finally:
            await conn.close()
    elif req.text:
        # Моковане резюме для довільного тексту
        summary = f"AI-генероване резюме для тексту: {req.text[:100]}..."
        return {"summary": summary}
    else:
        raise HTTPException(status_code=400, detail="Потрібен news_id або text.")

@app.post("/feedback")
async def save_feedback_api(req: FeedbackRequest):
    """Зберігає відгук користувача."""
    conn = await get_db_connection()
    try:
        await conn.execute("INSERT INTO feedback (user_id, message) VALUES ($1, $2)", req.user_id, req.message)
        return {"status": "saved", "user_id": req.user_id, "message": req.message}
    finally:
        await conn.close()

@app.post("/rate")
async def save_rating_api(req: RateRequest):
    """Зберігає оцінку новини користувачем."""
    if 1 <= req.value <= 5:
        conn = await get_db_connection()
        try:
            await conn.execute("INSERT INTO ratings (user_id, news_id, value) VALUES ($1, $2, $3) ON CONFLICT (user_id, news_id) DO UPDATE SET value = EXCLUDED.value", req.user_id, req.news_id, req.value)
            return {"status": "rated", "news_id": req.news_id, "value": req.value}
        finally:
            await conn.close()
    return {"error": "invalid rating"}

@app.post("/block")
async def block_source_api(req: BlockRequest):
    """Блокує джерело/тег/категорію/мову для користувача."""
    conn = await get_db_connection()
    try:
        await conn.execute("INSERT INTO blocks (user_id, block_type, value) VALUES ($1, $2, $3) ON CONFLICT (user_id, block_type, value) DO NOTHING", req.user_id, req.block_type, req.value)
        return {"blocked": True, "type": req.block_type, "value": req.value}
    finally:
        await conn.close()

@app.post("/daily")
async def subscribe_daily_api(req: DigestRequest):
    """Підписує користувача на щоденний дайджест (застаріле)."""
    # Цей ендпоінт замінено на /subscriptions/update
    conn = await get_db_connection()
    try:
        await conn.execute("INSERT INTO subscriptions (user_id, active) VALUES ($1, TRUE) ON CONFLICT (user_id) DO UPDATE SET active = TRUE", req.user_id)
        return {"subscribed": True, "user_id": req.user_id}
    finally:
        await conn.close()

@app.get("/analytics/{user_id}")
async def get_analytics_api(user_id: int):
    """Повертає аналітику використання для користувача."""
    conn = await get_db_connection()
    try:
        stats = await conn.fetchrow("SELECT viewed, saved, reported, last_active FROM user_stats WHERE user_id = (SELECT id FROM users WHERE telegram_id = $1)", user_id)
        user_info = await conn.fetchrow("SELECT level, badges FROM users WHERE telegram_id = $1", user_id)
        
        # Моковані дані для інших метрик, поки не імплементовані в БД
        read_full_count = 0
        skipped_count = 0
        liked_count = 0
        comments_count = 0
        sources_added_count = 0
        
        if stats:
            return {
                "user_id": user_id,
                "viewed": stats['viewed'],
                "saved": stats['saved'],
                "reported": stats['reported'],
                "read_full_count": read_full_count,
                "skipped_count": skipped_count,
                "liked_count": liked_count,
                "comments_count": comments_count,
                "sources_added_count": sources_added_count,
                "level": user_info['level'] if user_info else 1,
                "badges": user_info['badges'] if user_info else [],
                "last_active": stats['last_active'].isoformat() if stats['last_active'] else None
            }
        # Якщо статистики немає, повертаємо початкові значення
        return {
            "user_id": user_id,
            "viewed": 0, "saved": 0, "reported": 0,
            "read_full_count": 0, "skipped_count": 0, "liked_count": 0,
            "comments_count": 0, "sources_added_count": 0,
            "level": user_info['level'] if user_info else 1,
            "badges": user_info['badges'] if user_info else [],
            "last_active": datetime.utcnow().isoformat()
        }
    finally:
        await conn.close()

@app.post("/report")
async def send_report_api(req: ReportRequest):
    """Відправляє скаргу на новину або загальну проблему."""
    conn = await get_db_connection()
    try:
        await conn.execute("INSERT INTO reports (user_id, news_id, reason) VALUES ($1, $2, $3)", req.user_id, req.news_id, req.reason)
        return {"status": "reported", "user_id": req.user_id, "news_id": req.news_id, "reason": req.reason}
    finally:
        await conn.close()

@app.get("/recommend/{user_id}")
async def get_recommendations_api(user_id: int):
    """Повертає AI-рекомендації новин для користувача (моковано)."""
    # В реальності тут буде складна логіка рекомендацій
    # Завантажуємо якісь новини з БД для моку
    conn = await get_db_connection()
    try:
        mock_news = await conn.fetch("SELECT id, title FROM news LIMIT 3")
        return {
            "user_id": user_id,
            "recommended": [
                {"id": news['id'], "title": news['title']} for news in mock_news
            ]
        }
    finally:
        await conn.close()

@app.get("/verify/{news_id}")
async def verify_news_api(news_id: int):
    """Виконує AI-фактчекінг новини (моковано)."""
    # В реальності тут буде виклик до моделі фактчекінгу
    return {
        "news_id": news_id,
        "is_fake": random.choice([True, False]),
        "confidence": random.uniform(0.5, 0.99),
        "source": "AI Fact-Checker"
    }

@app.post("/ai/rewrite_headline")
async def rewrite_headline_api(req: RewriteHeadlineRequest):
    """Переписує заголовок новини за допомогою AI (моковано)."""
    # Простий мок: додаємо "AI-rewritten: " до заголовка
    rewritten_headline = f"AI-rewritten: {req.text}"
    return {"original_headline": req.text, "rewritten_headline": rewritten_headline}


@app.post("/users/register")
async def register_user_api(req: UserRegisterRequest):
    """
    Реєструє нового користувача або оновлює існуючого.
    Використовує telegram_id як унікальний ідентифікатор.
    """
    conn = await get_db_connection()
    try:
        # Спроба знайти користувача за telegram_id
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)

        update_parts = []
        params = []
        param_idx = 1

        if req.language is not None:
            update_parts.append(f"language = ${param_idx}")
            params.append(req.language)
            param_idx += 1
        if req.country is not None:
            update_parts.append(f"country = ${param_idx}")
            params.append(req.country)
            param_idx += 1
        if req.safe_mode is not None:
            update_parts.append(f"safe_mode = ${param_idx}")
            params.append(req.safe_mode)
            param_idx += 1
        if req.current_feed_id is not None:
            update_parts.append(f"current_feed_id = ${param_idx}")
            params.append(req.current_feed_id)
            param_idx += 1
        if req.email is not None:
            update_parts.append(f"email = ${param_idx}")
            params.append(req.email)
            param_idx += 1
        if req.auto_notifications is not None:
            update_parts.append(f"auto_notifications = ${param_idx}")
            params.append(req.auto_notifications)
            param_idx += 1
        if req.view_mode is not None:
            update_parts.append(f"view_mode = ${param_idx}")
            params.append(req.view_mode)
            param_idx += 1
        
        # Обробка is_premium та premium_expires_at
        if req.is_premium is not None:
            update_parts.append(f"is_premium = ${param_idx}")
            params.append(req.is_premium)
            param_idx += 1
            if req.is_premium:
                update_parts.append(f"premium_expires_at = ${param_idx}")
                params.append(datetime.utcnow() + timedelta(days=30)) # 30 днів преміуму
                param_idx += 1
            else:
                update_parts.append(f"premium_expires_at = NULL") # Скасувати преміум

        if user_internal_id:
            # Користувач існує, оновлюємо його
            if update_parts:
                query = f"UPDATE users SET {', '.join(update_parts)} WHERE telegram_id = ${param_idx}"
                params.append(req.user_id)
                await conn.execute(query, *params)
                return {"status": "success", "message": "Профіль оновлено"}
            return {"status": "no_changes", "message": "Немає змін для оновлення"}
        else:
            # Користувач не існує, вставляємо нового
            insert_columns = ["telegram_id"]
            insert_values = ["$1"]
            insert_params = [req.user_id]
            insert_idx = 2

            if req.language is not None:
                insert_columns.append("language")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.language)
                insert_idx += 1
            if req.country is not None:
                insert_columns.append("country")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.country)
                insert_idx += 1
            if req.safe_mode is not None:
                insert_columns.append("safe_mode")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.safe_mode)
                insert_idx += 1
            if req.current_feed_id is not None:
                insert_columns.append("current_feed_id")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.current_feed_id)
                insert_idx += 1
            if req.email is not None:
                insert_columns.append("email")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.email)
                insert_idx += 1
            if req.auto_notifications is not None:
                insert_columns.append("auto_notifications")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.auto_notifications)
                insert_idx += 1
            if req.view_mode is not None:
                insert_columns.append("view_mode")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.view_mode)
                insert_idx += 1
            if req.is_premium is not None:
                insert_columns.append("is_premium")
                insert_values.append(f"${insert_idx}")
                insert_params.append(req.is_premium)
                insert_idx += 1
                if req.is_premium:
                    insert_columns.append("premium_expires_at")
                    insert_values.append(f"${insert_idx}")
                    insert_params.append(datetime.utcnow() + timedelta(days=30))
                    insert_idx += 1

            query = f"INSERT INTO users ({', '.join(insert_columns)}) VALUES ({', '.join(insert_values)}) RETURNING id"
            new_user_id = await conn.fetchval(query, *insert_params)
            return {"status": "success", "message": "Користувача зареєстровано", "user_internal_id": new_user_id}

    finally:
        await conn.close()


@app.get("/users/{user_id}/profile")
async def get_user_profile_api(user_id: int):
    """Повертає профіль користувача за telegram_id."""
    conn = await get_db_connection()
    try:
        user_profile = await conn.fetchrow("SELECT telegram_id, language, country, safe_mode, current_feed_id, is_premium, premium_expires_at, level, badges, inviter_id, email, auto_notifications, view_mode FROM users WHERE telegram_id = $1", user_id)
        if user_profile:
            # Перетворюємо record на dict, щоб дату можна було серіалізувати
            profile_dict = dict(user_profile)
            if profile_dict.get('premium_expires_at'):
                profile_dict['premium_expires_at'] = profile_dict['premium_expires_at'].isoformat()
            return profile_dict
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    finally:
        await conn.close()

@app.get("/news/{user_id}")
async def get_news_for_user_api(user_id: int, limit: int = 10, offset: int = 0):
    """
    Повертає новини для користувача, застосовуючи його фільтри
    та враховуючи переглянуті новини.
    """
    conn = await get_db_connection()
    try:
        # Отримати внутрішній ID користувача
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            return [] # Користувача не знайдено

        # Отримати фільтри користувача
        filters = await conn.fetchrow("SELECT tag, category, source, language, country, content_type FROM filters WHERE user_id = $1", user_internal_id)
        
        # Отримати ID вже переглянутих новин
        viewed_news_ids = await conn.fetch("SELECT news_id FROM user_news_views WHERE user_id = $1", user_internal_id)
        viewed_news_ids = [r['news_id'] for r in viewed_news_ids]

        query = """
            SELECT n.id, n.title, n.content, n.lang, n.country, n.tags, n.source, n.link
            FROM news n
            LEFT JOIN user_news_views uv ON n.id = uv.news_id AND uv.user_id = $1
            WHERE uv.news_id IS NULL -- Новини, які ще не були переглянуті цим користувачем
        """
        params = [user_internal_id]
        param_idx = 2
        
        filter_conditions = []

        if filters:
            if filters['tag']:
                filter_conditions.append(f"$ {param_idx} = ANY(n.tags)")
                params.append(filters['tag'])
                param_idx += 1
            if filters['category']:
                # Припускаємо, що categories будуть окремим полем або тегом
                filter_conditions.append(f"$ {param_idx} = ANY(n.tags)") # Замість цього потрібно category
                params.append(filters['category'])
                param_idx += 1
            if filters['source']:
                filter_conditions.append(f"n.source ILIKE $ {param_idx}")
                params.append(filters['source'])
                param_idx += 1
            if filters['language']:
                filter_conditions.append(f"n.lang ILIKE $ {param_idx}")
                params.append(filters['language'])
                param_idx += 1
            if filters['country']:
                filter_conditions.append(f"n.country ILIKE $ {param_idx}")
                params.append(filters['country'])
                param_idx += 1
            if filters['content_type']:
                # Припускаємо, що content_type буде в тегах або окремим полем
                filter_conditions.append(f"$ {param_idx} = ANY(n.tags)") # Замість цього потрібно content_type
                params.append(filters['content_type'])
                param_idx += 1
        
        if filter_conditions:
            query += " AND " + " AND ".join(filter_conditions)

        query += f" ORDER BY n.published_at DESC LIMIT $ {param_idx} OFFSET $ {param_idx + 1}"
        params.extend([limit, offset])

        news_items = await conn.fetch(query, *params)
        
        # Оновлюємо user_news_views для отриманих новин
        for news_item in news_items:
            await conn.execute(
                "INSERT INTO user_news_views (user_id, news_id, viewed, first_viewed_at) VALUES ($1, $2, TRUE, NOW()) ON CONFLICT (user_id, news_id) DO UPDATE SET viewed = TRUE, last_viewed_at = NOW()",
                user_internal_id, news_item['id']
            )
            # Оновлюємо статистику переглядів
            await update_user_stats(conn, user_internal_id, "viewed")

        return [dict(n) for n in news_items]
    finally:
        await conn.close()

@app.post("/log_user_activity")
async def log_user_activity_api(user_id: int, news_id: int, action: str):
    """Логує дії користувача з новинами (like, dislike, skip)."""
    conn = await get_db_connection()
    try:
        # Отримати внутрішній ID користувача
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute("INSERT INTO interactions (user_id, news_id, action) VALUES ($1, $2, $3)", user_internal_id, news_id, action)
        await update_user_stats(conn, user_internal_id, action) # Оновлюємо статистику
        return {"status": "success", "user_id": user_id, "news_id": news_id, "action": action}
    finally:
        await conn.close()

@app.post("/filters/update")
async def update_filter_api(req: FilterUpdateRequest):
    """Оновлює або додає фільтри для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        # Оновлення або вставка фільтрів
        # Ця логіка може бути складнішою, якщо фільтрів багато і вони мають комбінуватися
        if req.tag is not None:
            await conn.execute("INSERT INTO filters (user_id, tag) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET tag = EXCLUDED.tag", user_internal_id, req.tag)
        if req.category is not None:
            await conn.execute("INSERT INTO filters (user_id, category) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET category = EXCLUDED.category", user_internal_id, req.category)
        if req.source is not None:
            await conn.execute("INSERT INTO filters (user_id, source) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET source = EXCLUDED.source", user_internal_id, req.source)
        if req.language is not None:
            await conn.execute("INSERT INTO filters (user_id, language) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET language = EXCLUDED.language", user_internal_id, req.language)
        if req.country is not None:
            await conn.execute("INSERT INTO filters (user_id, country) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET country = EXCLUDED.country", user_internal_id, req.country)
        if req.content_type is not None:
            await conn.execute("INSERT INTO filters (user_id, content_type) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET content_type = EXCLUDED.content_type", user_internal_id, req.content_type)
            
        return {"status": "success", "message": "Фільтр оновлено/додано"}
    finally:
        await conn.close()

@app.get("/filters/{user_id}")
async def get_filters_api(user_id: int):
    """Повертає активні фільтри для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
        
        filters = await conn.fetchrow("SELECT tag, category, source, language, country, content_type FROM filters WHERE user_id = $1", user_internal_id)
        return dict(filters) if filters else {}
    finally:
        await conn.close()

@app.delete("/filters/reset/{user_id}")
async def reset_filters_api(user_id: int):
    """Скидає всі фільтри для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute("DELETE FROM filters WHERE user_id = $1", user_internal_id)
        return {"status": "success", "message": "Фільтри скинуто"}
    finally:
        await conn.close()

@app.post("/news/add")
async def add_news_api(req: NewsAddRequest):
    """Додає нову новину (для адмінів/контент-менеджерів)."""
    conn = await get_db_connection()
    try:
        await conn.execute(
            "INSERT INTO news (title, content, lang, country, tags, source, link) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            req.title, req.content, req.lang, req.country, req.tags, req.source, req.link
        )
        return {"status": "success", "message": "Новина додана"}
    finally:
        await conn.close()

@app.post("/sources/add")
async def add_source_api(req: SourceAddRequest):
    """Додає нове джерело."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO sources (name, link, type, added_by_user_id) VALUES ($1, $2, $3, $4) ON CONFLICT (link) DO NOTHING",
            req.name, req.link, req.type, user_internal_id
        )
        return {"status": "success", "message": "Джерело додано"}
    finally:
        await conn.close()

@app.post("/bookmarks/add")
async def add_bookmark_api(req: BookmarkAddRequest):
    """Додає новину до закладок користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute("INSERT INTO bookmarks (user_id, news_id) VALUES ($1, $2) ON CONFLICT (user_id, news_id) DO NOTHING", user_internal_id, req.news_id)
        await update_user_stats(conn, user_internal_id, "saved")
        return {"status": "success", "message": "Закладку додано"}
    finally:
        await conn.close()

@app.get("/bookmarks/{user_id}")
async def get_bookmarks_api(user_id: int):
    """Повертає список закладок для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        bookmarks = await conn.fetch(
            "SELECT n.id, n.title, n.link FROM bookmarks b JOIN news n ON b.news_id = n.id WHERE b.user_id = $1 ORDER BY b.created_at DESC",
            user_internal_id
        )
        return [dict(b) for b in bookmarks]
    finally:
        await conn.close()

@app.post("/comments/add")
async def add_comment_api(req: CommentAddRequest):
    """Додає коментар до новини."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute("INSERT INTO comments (user_id, news_id, content) VALUES ($1, $2, $3)", user_internal_id, req.news_id, req.content)
        return {"status": "success", "message": "Коментар додано, очікує модерації"}
    finally:
        await conn.close()

@app.get("/comments/{news_id}")
async def get_comments_api(news_id: int):
    """Повертає схвалені коментарі для новини."""
    conn = await get_db_connection()
    try:
        comments = await conn.fetch(
            "SELECT c.content, u.telegram_id FROM comments c JOIN users u ON c.user_id = u.id WHERE c.news_id = $1 AND c.moderation_status = 'approved' ORDER BY c.created_at ASC",
            news_id
        )
        return [{"content": c['content'], "user_telegram_id": c['telegram_id']} for c in comments]
    finally:
        await conn.close()

@app.get("/trending")
async def get_trending_news_api(limit: int = 5):
    """Повертає трендові новини (моковано)."""
    conn = await get_db_connection()
    try:
        # Для моку: просто повертаємо останні 5 новин
        trending_news = await conn.fetch("SELECT id, title FROM news ORDER BY published_at DESC LIMIT $1", limit)
        return [dict(n) for n in trending_news]
    finally:
        await conn.close()

@app.post("/custom_feeds/create")
async def create_custom_feed_api(req: CustomFeedCreateRequest):
    """Створює нову персональну добірку для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
        
        # Перетворюємо filters dict на JSONB для зберігання
        filters_json = json.dumps(req.filters)
        
        # Перевірка на унікальність назви добірки для користувача
        existing_feed = await conn.fetchval("SELECT id FROM custom_feeds WHERE user_id = $1 AND feed_name ILIKE $2", user_internal_id, req.feed_name)
        if existing_feed:
            raise HTTPException(status_code=409, detail="Добірка з такою назвою вже існує.")

        await conn.execute(
            "INSERT INTO custom_feeds (user_id, feed_name, filters) VALUES ($1, $2, $3)",
            user_internal_id, req.feed_name, filters_json
        )
        return {"status": "success", "message": "Добірку створено"}
    finally:
        await conn.close()

@app.get("/custom_feeds/{user_id}")
async def get_custom_feeds_api(user_id: int):
    """Повертає список персональних добірок для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            return [] # Користувача не знайдено
        
        feeds = await conn.fetch("SELECT id, feed_name, filters FROM custom_feeds WHERE user_id = $1 ORDER BY created_at DESC", user_internal_id)
        return [dict(f) for f in feeds] # Фільтри вже JSONB, тому просто передаємо
    finally:
        await conn.close()

@app.post("/custom_feeds/switch")
async def switch_custom_feed_api(req: CustomFeedSwitchRequest):
    """Переключає активну персональну добірку для користувача."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
        
        # Перевіряємо, чи належить добірка користувачу
        feed_exists = await conn.fetchval("SELECT id FROM custom_feeds WHERE id = $1 AND user_id = $2", req.feed_id, user_internal_id)
        if not feed_exists:
            raise HTTPException(status_code=403, detail="Доступ заборонено або добірку не знайдено.")

        await conn.execute("UPDATE users SET current_feed_id = $1 WHERE id = $2", req.feed_id, user_internal_id)
        return {"status": "success", "message": f"Переключено на добірку ID {req.feed_id}"}
    finally:
        await conn.close()

@app.post("/subscriptions/update")
async def update_subscription_api(req: SubscriptionUpdateRequest):
    """Оновлює підписку користувача на розсилку."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
        
        # 'active' буде true, якщо це підписка, false якщо відписка
        active_status = True
        if req.frequency == "unsubscribe": # Якщо це запит на відписку
            active_status = False

        await conn.execute(
            "INSERT INTO subscriptions (user_id, frequency, active) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET frequency = EXCLUDED.frequency, active = EXCLUDED.active",
            user_internal_id, req.frequency, active_status
        )
        return {"status": "success", "message": f"Підписку на {req.frequency} оновлено"}
    finally:
        await conn.close()

@app.post("/subscriptions/unsubscribe")
async def unsubscribe_from_digest_api(user_id: int):
    """Відписує користувача від усіх розсилок."""
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
        
        await conn.execute("UPDATE subscriptions SET active = FALSE WHERE user_id = $1", user_internal_id)
        return {"status": "success", "message": "Успішно відписано від розсилок"}
    finally:
        await conn.close()

@app.post("/invite/generate")
async def generate_invite_code_api(req: InviteGenerateRequest):
    """Генерує унікальний код запрошення."""
    conn = await get_db_connection()
    try:
        inviter_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.inviter_user_id)
        if not inviter_internal_id:
            raise HTTPException(status_code=404, detail="Користувача, що запрошує, не знайдено.")
        
        invite_code = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))
        await conn.execute("INSERT INTO invites (inviter_user_id, invite_code) VALUES ($1, $2)", inviter_internal_id, invite_code)
        return {"status": "success", "invite_code": invite_code}
    finally:
        await conn.close()

@app.post("/invite/accept")
async def accept_invite_api(req: InviteAcceptRequest):
    """Приймає запрошення та позначає запрошеного користувача."""
    conn = await get_db_connection()
    try:
        # Знайти запрошення за кодом
        invite_record = await conn.fetchrow("SELECT id, inviter_user_id FROM invites WHERE invite_code = $1 AND invited_user_id IS NULL", req.invite_code)
        
        if not invite_record:
            raise HTTPException(status_code=400, detail="Недійсний або вже використаний код запрошення.")
        
        inviter_internal_id = invite_record['inviter_user_id']

        # Оновити користувача, що приєднався, додавши inviter_id
        await conn.execute("UPDATE users SET inviter_id = $1 WHERE telegram_id = $2", inviter_internal_id, req.invited_user_id)

        # Позначити запрошення як використане
        await conn.execute("UPDATE invites SET invited_user_id = (SELECT id FROM users WHERE telegram_id = $1), accepted_at = NOW() WHERE id = $2", req.invited_user_id, invite_record['id'])
        
        return {"status": "success", "message": "Запрошення прийнято", "inviter_user_id": inviter_internal_id, "invited_user_id": req.invited_user_id}
    finally:
        await conn.close()


# ==== Автоматичні сповіщення ====
async def send_auto_notifications_task():
    """
    Фонова задача для відправлення автоматичних сповіщень про нові новини
    користувачам, у яких увімкнені auto_notifications.
    """
    while True:
        conn = None
        try:
            conn = await get_db_connection()
            # Отримуємо користувачів, які увімкнули auto_notifications
            users_for_notifications = await conn.fetch("SELECT id AS user_internal_id, telegram_id, language, current_feed_id FROM users WHERE auto_notifications = TRUE")

            for user in users_for_notifications:
                # Отримуємо нові новини для кожного користувача, що відповідають його фільтрам
                # Використовуємо ту ж логіку, що й get_news_for_user, але без оновлення viewed
                # і без пропуску вже переглянутих, оскільки це "нові" сповіщення
                
                # Завантаження фільтрів для користувача
                filters = await conn.fetchrow("SELECT tag, category, source, language, country, content_type FROM filters WHERE user_id = $1", user['user_internal_id'])
                
                query = """
                    SELECT n.id, n.title, n.content, n.source, n.link
                    FROM news n
                    LEFT JOIN user_news_views uv ON n.id = uv.news_id AND uv.user_id = $1
                    WHERE uv.news_id IS NULL -- Новини, які ще не були переглянуті цим користувачем
                """
                params = [user['user_internal_id']]
                param_idx = 2
                
                filter_conditions = []

                if filters:
                    if filters['tag']:
                        filter_conditions.append(f"$ {param_idx} = ANY(n.tags)")
                        params.append(filters['tag'])
                        param_idx += 1
                    if filters['category']:
                        filter_conditions.append(f"$ {param_idx} = ANY(n.tags)") 
                        params.append(filters['category'])
                        param_idx += 1
                    if filters['source']:
                        filter_conditions.append(f"n.source ILIKE $ {param_idx}")
                        params.append(filters['source'])
                        param_idx += 1
                    if filters['language']:
                        filter_conditions.append(f"n.lang ILIKE $ {param_idx}")
                        params.append(filters['language'])
                        param_idx += 1
                    if filters['country']:
                        filter_conditions.append(f"n.country ILIKE $ {param_idx}")
                        params.append(filters['country'])
                        param_idx += 1
                    if filters['content_type']:
                        filter_conditions.append(f"$ {param_idx} = ANY(n.tags)")
                        params.append(filters['content_type'])
                        param_idx += 1
                
                if filter_conditions:
                    query += " AND " + " AND ".join(filter_conditions)

                query += " ORDER BY n.published_at DESC LIMIT 1" # По одній новині за раз

                news_item = await conn.fetchrow(query, *params)
                
                if news_item:
                    # Відправляємо сповіщення
                    title = escape_markdown_v2(news_item['title'])
                    content = escape_markdown_v2(news_item['content'])
                    link = news_item.get('link') # URL не екрануємо
                    
                    text_message = (
                        f"🔔 Нова новина: *{title}*\n\n"
                        f"{content}\n\n"
                        f"[Читати більше]({escape_markdown_v2(link) if link else ''})" # Посилання на оригінальний URL новини
                    )
                    
                    try:
                        await bot.send_message(chat_id=user['telegram_id'], text=text_message, parse_mode=ParseMode.MARKDOWN_V2)
                        logging.info(f"Відправлено автоматичне сповіщення користувачу {user['telegram_id']} про новину: {news_item['title']}")
                        # Позначаємо новину як переглянуту після відправки сповіщення
                        await conn.execute(
                            "INSERT INTO user_news_views (user_id, news_id, viewed, first_viewed_at) VALUES ($1, $2, TRUE, NOW()) ON CONFLICT (user_id, news_id) DO UPDATE SET viewed = TRUE, last_viewed_at = NOW()",
                            user['user_internal_id'], news_item['id']
                        )
                        await update_user_stats(conn, user['user_internal_id'], "viewed")
                    except Exception as e:
                        logging.error(f"Помилка відправки сповіщення користувачу {user['telegram_id']}: {e}")

        except Exception as e:
            logging.error(f"Помилка в задачі автоматичних сповіщень: {e}")
        finally:
            if conn:
                await conn.close()
        await asyncio.sleep(15 * 60) # Перевіряємо кожні 15 хвилин


# == КЛАВІАТУРИ ==
main_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="📰 Новини"), types.KeyboardButton(text="🎯 Фільтри")],
    [types.KeyboardButton(text="⚙️ Налаштування"), types.KeyboardButton(text="📬 Щоденна розсилка")],
    [types.KeyboardButton(text="📊 Аналітика"), types.KeyboardButton(text="❗ Скарга")],
    [types.KeyboardButton(text="💬 Відгук"), types.KeyboardButton(text="🌐 Мова / Переклад")],
    [types.KeyboardButton(text="🧠 AI-аналіз")]
])

settings_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="🔒 Безпечний режим"), types.KeyboardButton(text="✨ Преміум")],
    [types.KeyboardButton(text="📧 Email розсилка"), types.KeyboardButton(text="🔔 Авто-сповіщення")],
    [types.KeyboardButton(text="👁️ Режим перегляду"), types.KeyboardButton(text="⬅️ Головне меню")]
])

filters_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="➕ Додати фільтр"), types.KeyboardButton(text="📝 Мої фільтри")],
    [types.KeyboardButton(text="🗑️ Скинути фільтри"), types.KeyboardButton(text="🆕 Створити добірку")],
    [types.KeyboardButton(text="🔄 Переключити добірку"), types.KeyboardButton(text="✏️ Редагувати добірку")],
    [types.KeyboardButton(text="⬅️ Головне меню")]
])

ai_analysis_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="🧠 AI Summary"), types.KeyboardButton(text="🔍 Фактчекінг")],
    [types.KeyboardButton(text="💡 Рекомендації"), types.KeyboardButton(text="✍️ Переписати заголовок")],
    [types.KeyboardButton(text="⬅️ Головне меню")]
])

extra_features_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="➕ Додати новину (Адмін)"), types.KeyboardButton(text="➕ Додати джерело")],
    [types.KeyboardButton(text="⭐ Оцінити новину"), types.KeyboardButton(text="🔖 Закладки")],
    [types.KeyboardButton(text="💬 Коментарі"), types.KeyboardButton(text="📊 Тренд")],
    [types.KeyboardButton(text="✉️ Запросити друга"), types.KeyboardButton(text="⬅️ Головне меню")]
])

# == ХЕНДЛЕРИ ==

async def start_command_handler(msg: types.Message, state: FSMContext):
    """
    Обробляє команду /start.
    Реєструє або оновлює користувача в базі даних та відображає головне меню.
    """
    user_id = msg.from_user.id
    language_code = msg.from_user.language_code
    country_code = msg.from_user.locale.language if msg.from_user.locale else None
    
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/users/register", json={
            "user_id": user_id,
            "language": language_code,
            "country": country_code
        })
        if resp.status == 200:
            await msg.answer("👋 Ласкаво просимо до AI News Бота!", reply_markup=main_keyboard)
        else:
            await msg.answer("👋 Ласкаво просимо! Виникла проблема з реєстрацією, але ви можете продовжувати користуватися.")
    await state.set_state(None) # Очищаємо стан, якщо був


async def show_news_handler(msg: types.Message):
    """
    Відправляє користувачеві одну нову новину, застосовуючи фільтри.
    """
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/news/{user_id}?limit=1")
        if resp.status == 200:
            news_items = await resp.json()
            if news_items:
                news_item = news_items[0]
                await session.post(f"{WEBAPP_URL}/log_user_activity", json={
                    "user_id": user_id,
                    "news_id": news_item['id'],
                    "action": "view"
                })
                
                # Екранування тексту для MarkdownV2
                title = escape_markdown_v2(news_item['title'])
                content = escape_markdown_v2(news_item['content'])
                source = escape_markdown_v2(news_item['source'])
                # Не екрануємо link, оскільки це URL
                link = news_item.get('link')

                keyboard = types.InlineKeyboardMarkup(row_width=2)
                keyboard.add(
                    types.InlineKeyboardButton(text="👍 Подобається", callback_data=f"like_{news_item['id']}"),
                    types.InlineKeyboardButton(text="👎 Не подобається", callback_data=f"dislike_{news_item['id']}"),
                    types.InlineKeyboardButton(text="🔖 Зберегти", callback_data=f"save_{news_item['id']}"),
                    types.InlineKeyboardButton(text="➡️ Пропустити", callback_data=f"skip_{news_item['id']}")
                )
                if link:
                     keyboard.add(types.InlineKeyboardButton(text="🌐 Читати повністю", url=link)) # URL не потребує екранування

                await msg.answer(
                    f"*{title}*\n\n"
                    f"{content}\n\n"
                    f"Джерело: {source}\n",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await msg.answer("Наразі немає нових новин за вашими фільтрами. Спробуйте змінити налаштування фільтрів або повторіть спробу пізніше.")
        else:
            await msg.answer("❌ Виникла проблема при завантаженні новин.")


async def process_news_interaction_handler(callback_query: types.CallbackQuery):
    """
    Обробляє інтеракції користувача з новинами (лайк, дизлайк, зберегти, пропустити).
    """
    await callback_query.bot.answer_callback_query(callback_query.id)
    action, news_id_str = callback_query.data.split('_', 1)
    news_id = int(news_id_str)
    user_id = callback_query.from_user.id
    
    interaction_action = ""
    response_text = ""
    if action == "like":
        interaction_action = "like"
        response_text = "❤️ Новину лайкнуто!"
    elif action == "dislike":
        interaction_action = "dislike"
        response_text = "💔 Новина дизлайкнута."
    elif action == "save":
        interaction_action = "save"
        response_text = "🔖 Новину збережено в закладки!"
    elif action == "skip":
        interaction_action = "skip"
        response_text = "➡️ Новина пропущена."

    async with aiohttp.ClientSession() as session:
        if interaction_action == "save":
            resp = await session.post(f"{WEBAPP_URL}/bookmarks/add", json={"user_id": user_id, "news_id": news_id})
        else:
            resp = await session.post(f"{WEBAPP_URL}/log_user_activity", json={"user_id": user_id, "news_id": news_id, "action": interaction_action})

        if resp.status == 200:
            await callback_query.message.answer(response_text)
            await callback_query.message.edit_reply_markup(reply_markup=None) # Приховуємо кнопки
            if interaction_action == "skip":
                await show_news_handler(callback_query.message) # Передаємо message об'єкт
        else:
            await callback_query.message.answer("❌ Виникла проблема з обробкою вашої дії.")

async def show_filters_menu_handler(msg: types.Message, state: FSMContext):
    """Відкриває меню фільтрів."""
    await msg.answer("Оберіть дію з фільтрами:", reply_markup=filters_keyboard)
    await state.set_state(None) # Очищаємо стан, якщо був

async def add_filter_start_handler(msg: types.Message):
    """Починає процес додавання нового фільтра."""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton(text="Тег", callback_data="filter_type_tag"),
        types.InlineKeyboardButton(text="Категорія", callback_data="filter_type_category"),
        types.InlineKeyboardButton(text="Джерело", callback_data="filter_type_source"),
        types.InlineKeyboardButton(text="Мова", callback_data="filter_type_language"),
        types.InlineKeyboardButton(text="Країна", callback_data="filter_type_country"),
        types.InlineKeyboardButton(text="Тип контенту", callback_data="filter_type_content_type")
    )
    await msg.answer("Оберіть тип фільтра, який бажаєте додати:", reply_markup=keyboard)

async def process_filter_type_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обробляє вибір типу фільтра і просить ввести значення.
    """
    await callback_query.bot.answer_callback_query(callback_query.id)
    filter_type = callback_query.data.replace('filter_type_', '')
    
    await state.update_data(filter_type=filter_type)
    await callback_query.message.answer(f"Будь ласка, введіть значення для фільтра '*{escape_markdown_v2(filter_type)}*':", parse_mode=ParseMode.MARKDOWN_V2)
    await FilterStates.waiting_for_filter_tag.set()

async def process_filter_value_handler(msg: types.Message, state: FSMContext):
    """
    Обробляє введене значення фільтра та зберігає його.
    """
    user_data = await state.get_data()
    filter_type = user_data['filter_type']
    filter_value = msg.text.strip()
    user_id = msg.from_user.id
    
    payload = {"user_id": user_id, filter_type: filter_value}
    
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/filters/update", json=payload)
        if resp.status == 200:
            await msg.answer(f"✅ Фільтр '`{escape_markdown_v2(filter_type)}`: `{escape_markdown_v2(str(filter_value))}`' успішно додано/оновлено\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося додати/оновити фільтр. Спробуйте ще раз.")
    await state.set_state(None)


async def show_my_filters_handler(msg: types.Message):
    """Показує поточні активні фільтри користувача."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/filters/{user_id}")
        if resp.status == 200:
            filters = await resp.json()
            if filters:
                filter_text = "*Ваші активні фільтри:*\n"
                for k, v in filters.items():
                    if v:
                        filter_text += f"\\- *{escape_markdown_v2(k.capitalize())}*: `{escape_markdown_v2(str(v))}`\n" # Екрануємо значення V
                await msg.answer(filter_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("У вас немає активних фільтрів.")
        else:
            await msg.answer("❌ Не вдалося завантажити ваші фільтри.")

async def reset_filters_handler(msg: types.Message):
    """Скидає всі фільтри користувача."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.delete(f"{WEBAPP_URL}/filters/reset/{user_id}")
        if resp.status == 200:
            await msg.answer("✅ Усі ваші фільтри успішно скинуто\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося скинути фільтри. Спробуйте пізніше.")

async def create_custom_feed_start_handler(msg: types.Message, state: FSMContext):
    """Починає процес створення нової персональної добірки."""
    await msg.answer("Будь ласка, введіть назву для вашої нової добірки:")
    await CustomFeedStates.waiting_for_feed_name.set()

async def process_custom_feed_name_handler(msg: types.Message, state: FSMContext):
    """Зберігає назву добірки і просить ввести фільтри."""
    feed_name = msg.text.strip()
    await state.update_data(feed_name=feed_name, filters={})
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton(text="Додати теги", callback_data="add_feed_filter_tags"),
        types.InlineKeyboardButton(text="Додати джерела", callback_data="add_feed_filter_sources"),
        types.InlineKeyboardButton(text="Додати мови", callback_data="add_feed_filter_languages"),
        types.InlineKeyboardButton(text="✅ Завершити створення добірки", callback_data="finish_create_feed")
    )
    await msg.answer(f"Добірка '`{escape_markdown_v2(feed_name)}`' створена. Тепер ви можете додати до неї фільтри:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    await CustomFeedStates.waiting_for_feed_filters_tags.set()


async def add_feed_filter_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Починає додавання конкретного типу фільтра до добірки."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    filter_type = callback_query.data.replace('add_feed_filter_', '')
    await state.update_data(current_feed_filter_type=filter_type)
    await callback_query.message.answer(f"Введіть *{escape_markdown_v2(filter_type)}* (через кому, якщо кілька):", parse_mode=ParseMode.MARKDOWN_V2)

async def process_feed_filter_value_handler(msg: types.Message, state: FSMContext):
    """Зберігає значення фільтра для поточної добірки."""
    user_data = await state.get_data()
    current_feed_filter_type = user_data.get('current_feed_filter_type')
    
    if current_feed_filter_type:
        values = [v.strip() for v in msg.text.split(',') if v.strip()]
        user_data['filters'][current_feed_filter_type] = values
        await state.update_data(filters=user_data['filters'])
        
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            types.InlineKeyboardButton(text="Додати теги", callback_data="add_feed_filter_tags"),
            types.InlineKeyboardButton(text="Додати джерела", callback_data="add_feed_filter_sources"),
            types.InlineKeyboardButton(text="Додати мови", callback_data="add_feed_filter_languages"),
            types.InlineKeyboardButton(text="✅ Завершити створення добірки", callback_data="finish_create_feed")
        )
        await msg.answer(f"Фільтри для '`{escape_markdown_v2(current_feed_filter_type)}`' додано. Можете додати ще або завершити.", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await msg.answer("Будь ласка, спочатку оберіть тип фільтра для добірки.")


async def finish_create_feed_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Завершує створення добірки та відправляє її на бекенд."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    user_data = await state.get_data()
    feed_name = user_data['feed_name']
    filters = user_data['filters']
    user_id = callback_query.from_user.id
    
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/custom_feeds/create", json={
            "user_id": user_id,
            "feed_name": feed_name,
            "filters": filters
        })
        if resp.status == 200:
            await callback_query.message.answer(f"✅ Персональна добірка '`{escape_markdown_v2(feed_name)}`' успішно збережена!", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            error_details = await resp.json()
            await callback_query.message.answer(f"❌ Не вдалося створити добірку: {escape_markdown_v2(error_details.get('detail', 'Невідома помилка'))}")
    await state.set_state(None)
    await callback_query.message.delete_reply_markup()


async def switch_custom_feed_menu_handler(msg: types.Message, state: FSMContext):
    """Показує список добірок для переключення."""
    user_id = msg.from_user.id
    
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/custom_feeds/{user_id}")
        if resp.status == 200:
            feeds = await resp.json()
            if feeds:
                keyboard = types.InlineKeyboardMarkup(row_width=1)
                for feed in feeds:
                    keyboard.add(types.InlineKeyboardButton(text=feed['feed_name'], callback_data=f"switch_feed_{feed['id']}"))
                await msg.answer("Оберіть добірку, на яку хочете переключитися:", reply_markup=keyboard)
            else:
                await msg.answer("У вас ще немає створених добірок. Створіть одну за допомогою '🆕 Створити добірку'.")
        else:
            await msg.answer("❌ Не вдалося завантажити ваші добірки.")
    await state.set_state(None)


async def process_switch_feed_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Обробляє вибір добірки для переключення."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    feed_id = int(callback_query.data.replace("switch_feed_", ""))
    user_id = callback_query.from_user.id
    
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/custom_feeds/switch", json={
            "user_id": user_id,
            "feed_id": feed_id
        })
        if resp.status == 200:
            await callback_query.message.answer(f"✅ Ви успішно переключилися на добірку ID: `{escape_markdown_v2(str(feed_id))}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося переключити добірку. Спробуйте пізніше.")
    await callback_query.message.edit_reply_markup(reply_markup=None) # Remove inline keyboard after selection
    await state.set_state(None)


async def edit_custom_feed_menu_handler(msg: types.Message, state: FSMContext):
    """Пропонує користувачу обрати добірку для редагування."""
    user_id = msg.from_user.id
    
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/custom_feeds/{user_id}")
        if resp.status == 200:
            feeds = await resp.json()
            if feeds:
                keyboard = types.InlineKeyboardMarkup(row_width=1)
                for feed in feeds:
                    keyboard.add(types.InlineKeyboardButton(text=feed['feed_name'], callback_data=f"edit_feed_{feed['id']}"))
                await msg.answer("Оберіть добірку для редагування:", reply_markup=keyboard)
            else:
                await msg.answer("У вас ще немає створених добірок для редагування.")
        else:
            await msg.answer("❌ Не вдалося завантажити ваші добірки.")
    await state.set_state(None)


async def show_settings_handler(msg: types.Message, state: FSMContext):
    """Відкриває меню налаштувань."""
    await msg.answer("Оберіть налаштування:", reply_markup=settings_keyboard)
    await state.set_state(None)

async def toggle_safe_mode_handler(msg: types.Message):
    """Перемикає безпечний режим для користувача."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{WEBAPP_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            current_safe_mode = profile.get('safe_mode', False)
            new_safe_mode = not current_safe_mode

            update_resp = await session.post(f"{WEBAPP_URL}/users/register", json={"user_id": user_id, "safe_mode": new_safe_mode})
            if update_resp.status == 200:
                status_text = "увімкнено" if new_safe_mode else "вимкнено"
                await msg.answer(f"✅ Безпечний режим {status_text}\\.", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("❌ Не вдалося змінити налаштування безпечного режиму.")
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача.")

async def premium_info_handler(msg: types.Message):
    """Надає інформацію про преміум-підписку."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{WEBAPP_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            is_premium = profile.get('is_premium', False)
            premium_expires_at = profile.get('premium_expires_at')

            if is_premium:
                expires_date = datetime.fromisoformat(premium_expires_at).strftime("%d.%m.%Y %H:%M") if premium_expires_at else "невідомо"
                await msg.answer(f"🎉 У вас активна *Преміум\\-підписка* до `{escape_markdown_v2(expires_date)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                keyboard = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(text="Купити Преміум (100 UAH/міс)", callback_data="buy_premium")
                )
                await msg.answer("✨ Отримайте *Преміум\\-підписку* для доступу до розширених функцій!\n\n"
                                 "**Переваги:**\n"
                                 "\\- Розширений AI\\-аналіз\n"
                                 "\\- Персоналізовані рекомендації\n"
                                 "\\- Відсутність реклами\n"
                                 "\\- Пріоритетна підтримка\n"
                                 "\\- Інші ексклюзивні функції\n\n"
                                 f"Вартість: `100 UAH/місяць`\\. Оплатити можна на Monobank: `{escape_markdown_v2(MONOBANK_CARD_NUMBER)}`",
                                 reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача.")

async def handle_buy_premium_callback(callback_query: types.CallbackQuery):
    """Обробляє натискання кнопки 'Купити Преміум'."""
    await callback_query.bot.answer_callback_query(callback_query.id, show_alert=True, text="Для оплати перейдіть до Monobank або скористайтеся іншим банківським додатком та перекажіть 100 UAH на вказаний номер картки. Після оплати ваш преміум буде активовано автоматично протягом кількох хвилин.")
    await callback_query.message.answer(f"Для активації *Преміум\\-підписки* перекажіть `100 UAH` на картку Monobank: `{escape_markdown_v2(MONOBANK_CARD_NUMBER)}`\\.\n\n"
                                        "Активація відбудеться автоматично після підтвердження оплати\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def email_subscription_menu_handler(msg: types.Message, state: FSMContext):
    """Меню для управління email-розсилками."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{WEBAPP_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            user_email = profile.get('email')

            if user_email:
                keyboard = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(text="Змінити Email", callback_data="change_email"),
                    types.InlineKeyboardButton(text="Відписатись від Email", callback_data="unsubscribe_email")
                )
                await msg.answer(f"Ваша поточна Email\\-адреса для розсилки: `{escape_markdown_v2(user_email)}`\\.", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                keyboard = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(text="Додати Email", callback_data="add_email")
                )
                await msg.answer("У вас ще не налаштована Email\\-розсилка\\. Додайте вашу Email\\-адресу:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача.")
    await state.set_state(None)

async def request_email_input_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Запитує Email адресу у користувача."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    await callback_query.message.answer("Будь ласка, введіть вашу Email\\-адресу:", parse_mode=ParseMode.MARKDOWN_V2)
    await ProfileSettingsStates.waiting_for_email.set()

async def process_email_input_handler(msg: types.Message, state: FSMContext):
    """Обробляє введену Email адресу та зберігає її."""
    user_id = msg.from_user.id
    email = msg.text.strip()
    
    if "@" not in email or "." not in email:
        await msg.answer("Будь ласка, введіть коректну Email\\-адресу\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/users/register", json={"user_id": user_id, "email": email})
        if resp.status == 200:
            await msg.answer(f"✅ Вашу Email\\-адресу `{escape_markdown_v2(email)}` успішно збережено для розсилки\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося зберегти Email\\. Можливо, ця адреса вже використовується\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def unsubscribe_email_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Відписує користувача від email-розсилок."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/users/register", json={"user_id": user_id, "email": None})
        if resp.status == 200:
            await callback_query.message.answer("✅ Ви успішно відписалися від Email\\-розсилки\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося відписатися від Email\\-розсилки\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def toggle_auto_notifications_handler(msg: types.Message):
    """Перемикає автоматичні сповіщення про нові новини."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{WEBAPP_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            current_auto_notifications = profile.get('auto_notifications', False)
            new_auto_notifications = not current_auto_notifications

            resp = await session.post(f"{WEBAPP_URL}/users/register", json={"user_id": user_id, "auto_notifications": new_auto_notifications})
            if resp.status == 200:
                status_text = "увімкнено" if new_auto_notifications else "вимкнено"
                await msg.answer(f"✅ Автоматичні сповіщення про нові новини {status_text}\\.", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("❌ Не вдалося змінити налаштування авто\\-сповіщень\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def set_view_mode_handler(msg: types.Message, state: FSMContext):
    """Дозволяє користувачеві обрати режим перегляду новин."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{WEBAPP_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            current_view_mode = profile.get('view_mode', 'manual')

            keyboard = types.InlineKeyboardMarkup(row_width=1)
            keyboard.add(
                types.InlineKeyboardButton(text="Ручний перегляд (MyFeed)", callback_data="set_view_mode_manual"),
                types.InlineKeyboardButton(text="Автоматичний дайджест", callback_data="set_view_mode_auto")
            )
            await msg.answer(f"Ваш поточний режим перегляду: *{escape_markdown_v2(current_view_mode)}*\\.\nОберіть новий режим:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def process_view_mode_selection_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обробляє вибір режиму перегляду новин."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    new_view_mode = callback_query.data.replace('set_view_mode_', '')
    user_id = callback_query.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/users/register", json={"user_id": user_id, "view_mode": new_view_mode})
        if resp.status == 200:
            await callback_query.message.answer(f"✅ Режим перегляду успішно змінено на *{escape_markdown_v2(new_view_mode)}*\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося змінити режим перегляду\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await callback_query.message.edit_reply_markup(reply_markup=None)
    await state.set_state(None)

async def daily_digest_menu_handler(msg: types.Message, state: FSMContext):
    """Відкриває меню управління щоденною розсилкою."""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton(text="Підписатись на щоденну", callback_data="subscribe_daily_daily"),
        types.InlineKeyboardButton(text="Підписатись на погодинну", callback_data="subscribe_daily_hourly"),
        types.InlineKeyboardButton(text="Відписатись", callback_data="unsubscribe_daily")
    )
    await msg.answer("Оберіть частоту розсилки новин:", reply_markup=keyboard)
    await state.set_state(None)

async def process_subscribe_daily_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обробляє підписку на дайджест з різною частотою."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    frequency = callback_query.data.replace('subscribe_daily_', '')
    user_id = callback_query.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/subscriptions/update", json={"user_id": user_id, "frequency": frequency})
        if resp.status == 200:
            await callback_query.message.answer(f"✅ Ви успішно підписалися на `{escape_markdown_v2(frequency)}` дайджест\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося оформити підписку\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await callback_query.message.edit_reply_markup(reply_markup=None)
    await state.set_state(None)

async def process_unsubscribe_daily_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обробляє відписку від щоденної розсилки."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/subscriptions/unsubscribe", params={"user_id": user_id})
        if resp.status == 200:
            await callback_query.message.answer("✅ Ви успішно відписалися від розсилок\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося відписатися\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await callback_query.message.edit_reply_markup(reply_markup=None)
    await state.set_state(None)

async def show_analytics_handler(msg: types.Message, state: FSMContext):
    """Показує статистику використання бота для користувача."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/analytics/{user_id}")
        if resp.status == 200:
            analytics_data = await resp.json()
            if analytics_data:
                # Екранування всіх значень для MarkdownV2
                viewed = escape_markdown_v2(str(analytics_data.get('viewed', 0)))
                saved = escape_markdown_v2(str(analytics_data.get('saved', 0)))
                read_full_count = escape_markdown_v2(str(analytics_data.get('read_full_count', 0)))
                skipped_count = escape_markdown_v2(str(analytics_data.get('skipped_count', 0)))
                liked_count = escape_markdown_v2(str(analytics_data.get('liked_count', 0)))
                comments_count = escape_markdown_v2(str(analytics_data.get('comments_count', 0)))
                sources_added_count = escape_markdown_v2(str(analytics_data.get('sources_added_count', 0)))
                level = escape_markdown_v2(str(analytics_data.get('level', 1)))
                badges = escape_markdown_v2(', '.join(analytics_data.get('badges', [])) if analytics_data.get('badges') else 'Немає')
                last_active_dt = datetime.fromisoformat(analytics_data['last_active']) if analytics_data.get('last_active') else None
                last_active = escape_markdown_v2(last_active_dt.strftime('%d.%m.%Y %H:%M') if last_active_dt else 'Невідомо')

                stats_text = (
                    "*📊 Ваша статистика:*\n"
                    f"\\- Переглянуто новин: `{viewed}`\n"
                    f"\\- Збережено новин: `{saved}`\n"
                    f"\\- Прочитано повністю: `{read_full_count}`\n"
                    f"\\- Пропущено новин: `{skipped_count}`\n"
                    f"\\- Вподобано новин: `{liked_count}`\n"
                    f"\\- Залишено коментарів: `{comments_count}`\n"
                    f"\\- Додано джерел: `{sources_added_count}`\n"
                    f"\\- Поточний рівень: `{level}`\n"
                    f"\\- Ваші бейджі: `{badges}`\n"
                    f"\\- Остання активність: `{last_active}`"
                )
                await msg.answer(stats_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("Поки що немає даних для аналітики.")
        else:
            await msg.answer("❌ Не вдалося завантажити аналітику.")
    await state.set_state(None)

async def start_report_process_handler(msg: types.Message, state: FSMContext):
    """Починає процес подачі скарги."""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton(text="На новину", callback_data="report_news"),
        types.InlineKeyboardButton(text="Загальна проблема", callback_data="report_general")
    )
    await msg.answer("На що ви бажаєте подати скаргу?", reply_markup=keyboard)
    await state.set_state(None)

async def process_report_type_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Обробляє тип скарги та запитує додаткову інформацію."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    report_type = callback_query.data.replace('report_', '')
    await state.update_data(report_type=report_type)

    if report_type == "news":
        await callback_query.message.answer("Будь ласка, вкажіть *ID новини*, на яку ви скаржитесь\\.", parse_mode=ParseMode.MARKDOWN_V2)
        await ReportNewsStates.waiting_for_news_id_for_report.set()
    else: # report_general
        await callback_query.message.answer("Будь ласка, опишіть вашу проблему або причину скарги\\.", parse_mode=ParseMode.MARKDOWN_V2)
        await ReportNewsStates.waiting_for_report_reason.set()


async def process_news_id_for_report_handler(msg: types.Message, state: FSMContext):
    """Зберігає ID новини для скарги та просить ввести причину."""
    news_id_str = msg.text.strip()
    if not news_id_str.isdigit():
        await msg.answer("Будь ласка, введіть коректний числовий ID новини\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    await state.update_data(news_id=int(news_id_str))
    await msg.answer("Дякуємо\\. Тепер, будь ласка, опишіть причину вашої скарги на цю новину\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await ReportNewsStates.waiting_for_report_reason.set()

async def process_report_reason_handler(msg: types.Message, state: FSMContext):
    """Зберігає причину скарги та відправляє її на бекенд."""
    user_data = await state.get_data()
    report_type = user_data['report_type']
    news_id = user_data.get('news_id')
    reason = msg.text.strip()
    user_id = msg.from_user.id
    
    async with aiohttp.ClientSession() as session:
        payload = {
            "user_id": user_id,
            "reason": reason
        }
        if news_id: # Додаємо news_id тільки якщо він є
            payload["news_id"] = news_id

        resp = await session.post(f"{WEBAPP_URL}/report", json=payload)
        if resp.status == 200:
            await msg.answer("✅ Вашу скаргу отримано\\. Дякуємо за допомогу\\!", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося відправити скаргу\\. Спробуйте пізніше\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def start_feedback_process_handler(msg: types.Message, state: FSMContext):
    """Починає процес залишення відгуку."""
    await msg.answer("✍️ Напишіть ваш відгук, і ми обов'язково врахуємо його\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await FeedbackStates.waiting_for_feedback_message.set()

async def process_feedback_message_handler(msg: types.Message, state: FSMContext):
    """Обробляє повідомлення відгуку та відправляє його на бекенд."""
    feedback_message = msg.text.strip()
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/feedback", json={
            "user_id": user_id,
            "message": feedback_message
        })
        if resp.status == 200:
            await msg.answer("✅ Дякуємо за ваш відгук\\!", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося відправити відгук\\. Спробуйте пізніше\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def language_translate_handler(msg: types.Message, state: FSMContext):
    """Меню для вибору мови інтерфейсу та налаштування перекладу новин."""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton(text="Змінити мову інтерфейсу", callback_data="change_interface_lang"),
        types.InlineKeyboardButton(text="Увімкнути/вимкнути переклад новин", callback_data="toggle_news_translation")
    )
    await msg.answer("🌍 Оберіть опцію мови:", reply_markup=keyboard)
    await state.set_state(None)

async def request_interface_lang_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Запитує нову мову інтерфейсу у користувача."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    await callback_query.message.answer("Будь ласка, введіть код нової мови інтерфейсу (наприклад, `en` для англійської, `uk` для української)\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await ProfileSettingsStates.waiting_for_language_change.set()

async def process_interface_lang_change_handler(msg: types.Message, state: FSMContext):
    """Обробляє зміну мови інтерфейсу."""
    new_lang = msg.text.strip().lower()
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/users/register", json={"user_id": user_id, "language": new_lang})
        if resp.status == 200:
            await msg.answer(f"✅ Мову інтерфейсу успішно змінено на `{escape_markdown_v2(new_lang)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося змінити мову інтерфейсу\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def toggle_news_translation_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Перемикає функцію автоматичного перекладу новин."""
    await callback_query.bot.answer_callback_query(callback_query.id)
    await callback_query.message.answer("Функція автоматичного перекладу новин перемкнена (моковано)\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)


async def ai_features_handler(msg: types.Message, state: FSMContext):
    """Відкриває меню функцій AI-аналізу."""
    await msg.answer("🤖 Доступні функції AI-аналізу:", reply_markup=ai_analysis_keyboard)
    await state.set_state(None)

async def summary_start_handler(msg: types.Message, state: FSMContext):
    """Запитує ID новини для генерації AI-резюме."""
    await msg.answer("🧠 Вкажіть ID новини для резюме: `/summary ID_НОВИНИ`", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None) # Clear state in case it was stuck

async def summary_command_handler(msg: types.Message, state: FSMContext):
    """Генерує AI-резюме для вказаної новини."""
    args = msg.get_args()
    news_id = None
    text_to_summarize = None

    if args:
        if args.isdigit():
            news_id = int(args)
        else:
            text_to_summarize = args
    else:
        await msg.answer("🧠 Будь ласка, вкажіть ID новини (наприклад, `/summary 123`) або надайте текст для резюме (наприклад, `/summary Ваш текст тут`)", parse_mode=ParseMode.MARKDOWN_V2)
        await state.set_state(None)
        return

    async with aiohttp.ClientSession() as session:
        payload = {"news_id": news_id}
        if text_to_summarize:
            payload["text"] = text_to_summarize

        resp = await session.post(f"{WEBAPP_URL}/summary", json=payload)
        if resp.status == 200:
            result = await resp.json()
            summary_text = escape_markdown_v2(result['summary'])
            await msg.answer(f"🧠 *Резюме:*\n`{summary_text}`", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося згенерувати резюме. Спробуйте ще раз.")
    await state.set_state(None)

async def recommend_handler(msg: types.Message, state: FSMContext):
    """Показує AI-рекомендації новин."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/recommend/{user_id}")
        if resp.status == 200:
            result = await resp.json()
            recommended = result.get('recommended', [])
            if recommended:
                recommendations_text = "*📌 Вам можуть сподобатись ці новини:*\n\n"
                for item in recommended:
                    title_escaped = escape_markdown_v2(item['title'])
                    recommendations_text += f"\\- `{escape_markdown_v2(str(item['id']))}`: {title_escaped}\n"
                await msg.answer(recommendations_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("Наразі немає рекомендацій. Продовжуйте читати, щоб AI зміг краще вас зрозуміти!")
        else:
            await msg.answer("❌ Не вдалося отримати рекомендації.")
    await state.set_state(None)

async def fact_check_start_handler(msg: types.Message, state: FSMContext):
    """Запитує ID новини для фактчекінгу."""
    await msg.answer("🔍 Вкажіть ID новини для фактчекінгу: `/verify ID_НОВИНИ`", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def verify_command_handler(msg: types.Message, state: FSMContext):
    """Виконує фактчекінг для вказаної новини."""
    args = msg.get_args()
    if not args or not args.isdigit():
        await msg.answer("🔍 Будь ласка, вкажіть коректний ID новини: `/verify 123`", parse_mode=ParseMode.MARKDOWN_V2)
        await state.set_state(None)
        return
    news_id = int(args)

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/verify/{news_id}")
        if resp.status == 200:
            result = await resp.json()
            is_fake_status = "❌ Фейк!" if result['is_fake'] else "✅ Достовірна новина"
            confidence = round(result['confidence'] * 100)
            source = escape_markdown_v2(result['source'])
            await msg.answer(f"🔍 *Результат фактчекінгу новини ID `{escape_markdown_v2(str(news_id))}`:*\n\n"
                             f"Статус: `{is_fake_status}`\n"
                             f"Впевненість AI: `{escape_markdown_v2(str(confidence))}`%\\.\n"
                             f"Джерело: `{source}`",
                             parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося провести фактчекінг для цієї новини.")
    await state.set_state(None)

async def rewrite_headline_start_handler(msg: types.Message, state: FSMContext):
    """Запитує заголовок для переписування."""
    await msg.answer("✍️ Будь ласка, надішліть заголовок, який ви хочете переписати:")
    await state.set_state(AddNewsStates.waiting_for_title) # Using AddNewsStates.waiting_for_title for general text input

async def process_headline_rewrite_handler(msg: types.Message, state: FSMContext):
    """Переписує заголовок за допомогою AI."""
    original_headline = msg.text.strip()

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/ai/rewrite_headline", json={"text": original_headline})
        if resp.status == 200:
            result = await resp.json()
            rewritten = escape_markdown_v2(result['rewritten_headline'])
            await msg.answer(f"✅ *Оригінальний заголовок:*\n`{escape_markdown_v2(original_headline)}`\n\n"
                             f"*✍️ Переписаний AI:*\n`{rewritten}`",
                             parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося переписати заголовок.")
    await state.set_state(None)

# == Додаткові функції (не в меню AI-аналізу) ==

async def add_news_admin_start_handler(msg: types.Message, state: FSMContext):
    """
    Починає процес додавання нової новини вручну (для адмінів).
    """
    await msg.answer("Введіть *заголовок* новини:", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_title.set()

async def process_news_title_handler(msg: types.Message, state: FSMContext):
    await state.update_data(title=msg.text)
    await msg.answer("Введіть *повний зміст* новини:", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_content.set()

async def process_news_content_handler(msg: types.Message, state: FSMContext):
    await state.update_data(content=msg.text)
    await msg.answer("Введіть *мову* новини (наприклад, `uk`, `en`):", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_lang.set()

async def process_news_lang_handler(msg: types.Message, state: FSMContext):
    await state.update_data(lang=msg.text.lower())
    await msg.answer("Введіть *країну* новини (наприклад, `UA`, `US`):", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_country.set()

async def process_news_country_handler(msg: types.Message, state: FSMContext):
    await state.update_data(country=msg.text.upper())
    await msg.answer("Введіть *теги* для новини через кому (наприклад, `політика, економіка`):", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_tags.set()

async def process_news_tags_handler(msg: types.Message, state: FSMContext):
    tags = [tag.strip() for tag in msg.text.split(',') if tag.strip()]
    await state.update_data(tags=tags)
    await msg.answer("Введіть *назву джерела* новини:", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_source_name.set()

async def process_news_source_name_handler(msg: types.Message, state: FSMContext):
    await state.update_data(source=msg.text)
    await msg.answer("Введіть *посилання* на оригінальну новину (URL, якщо є, інакше `-`):", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_link.set()

async def process_news_link_handler(msg: types.Message, state: FSMContext):
    link = msg.text.strip()
    await state.update_data(link=link if link != '-' else None)
    await msg.answer("Надішліть *фото/відео* або інший медіа\\-файл для новини, або введіть `-` якщо немає:", parse_mode=ParseMode.MARKDOWN_V2)
    await AddNewsStates.waiting_for_media.set()

async def process_news_media_handler(msg: types.Message, state: FSMContext):
    file_id = None
    media_type = None
    if msg.photo:
        file_id = msg.photo[-1].file_id # Обираємо найбільший розмір фото
        media_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        media_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        media_type = "document"
    elif msg.text == '-':
        pass # Немає медіа

    await state.update_data(file_id=file_id, media_type=media_type)
    
    news_data = await state.get_data()
    
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/news/add", json=news_data)
        if resp.status == 200:
            await msg.answer("✅ Новина успішно додана та відправлена на обробку AI\\!", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося додати новину\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def add_source_start_handler(msg: types.Message, state: FSMContext):
    """Починає процес додавання нового джерела."""
    await msg.answer("Введіть *назву* джерела:", parse_mode=ParseMode.MARKDOWN_V2)
    await AddSourceStates.waiting_for_source_name.set()

async def process_source_name_handler(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await msg.answer("Введіть *посилання* на джерело (URL або Telegram ID):", parse_mode=ParseMode.MARKDOWN_V2)
    await AddSourceStates.waiting_for_source_link.set()

async def process_source_link_handler(msg: types.Message, state: FSMContext):
    await state.update_data(link=msg.text)
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton(text="Telegram", callback_data="source_type_telegram"),
        types.InlineKeyboardButton(text="RSS", callback_data="source_type_rss"),
        types.InlineKeyboardButton(text="Website", callback_data="source_type_website"),
        types.InlineKeyboardButton(text="Twitter", callback_data="source_type_twitter")
    )
    await msg.answer("Оберіть *тип* джерела:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    await AddSourceStates.waiting_for_source_type.set()

async def process_source_type_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.bot.answer_callback_query(callback_query.id)
    source_type = callback_query.data.replace('source_type_', '')
    await state.update_data(type=source_type)

    source_data = await state.get_data()
    user_id = callback_query.from_user.id
    source_data['user_id'] = user_id
    
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/sources/add", json=source_data)
        if resp.status == 200:
            await callback_query.message.answer("✅ Джерело успішно додано! Воно буде перевірено адміністрацією\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося додати джерело\\. Можливо, воно вже існує або виникла помилка\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)
    await callback_query.message.edit_reply_markup(reply_markup=None)

async def rate_news_start_handler(msg: types.Message, state: FSMContext):
    """Просить користувача ввести ID новини для оцінки."""
    await msg.answer("Будь ласка, вкажіть ID новини, яку ви хочете оцінити: `/rate ID_НОВИНИ ОЦІНКА` (від 1 до 5)", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def rate_news_command_handler(msg: types.Message, state: FSMContext):
    """Обробляє команду оцінки новини."""
    args = msg.get_args().split()
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await msg.answer("Будь ласка, вкажіть ID новини та оцінку (від 1 до 5): `/rate ID_НОВИНИ ОЦІНКА`", parse_mode=ParseMode.MARKDOWN_V2)
        await state.set_state(None)
        return

    news_id = int(args[0])
    rating_value = int(args[1])
    user_id = msg.from_user.id

    if not (1 <= rating_value <= 5):
        await msg.answer("Оцінка повинна бути числом від 1 до 5\\.", parse_mode=ParseMode.MARKDOWN_V2)
        await state.set_state(None)
        return

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/rate", json={
            "user_id": user_id,
            "news_id": news_id,
            "value": rating_value
        })
        if resp.status == 200:
            await msg.answer(f"✅ Новина ID `{escape_markdown_v2(str(news_id))}` оцінена на `{escape_markdown_v2(str(rating_value))}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося оцінити новину\\. Можливо, ви вже оцінювали її або сталася помилка\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def show_bookmarks_handler(msg: types.Message, state: FSMContext):
    """Показує список новин, збережених у закладках користувача."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/bookmarks/{user_id}")
        if resp.status == 200:
            bookmarks = await resp.json()
            if bookmarks:
                bookmarks_text = "*🔖 Ваші збережені новини:*\n\n"
                for item in bookmarks:
                    title_escaped = escape_markdown_v2(item['title'])
                    bookmarks_text += f"\\- `{escape_markdown_v2(str(item['id']))}`: {title_escaped}\n"
                await msg.answer(bookmarks_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("У вас немає збережених новин у закладках\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити закладки\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def comments_menu_handler(msg: types.Message, state: FSMContext):
    """Меню для управління коментарями."""
    await msg.answer("Оберіть дію з коментарями:", reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
        types.InlineKeyboardButton(text="Додати коментар", callback_data="add_comment"),
        types.InlineKeyboardButton(text="Переглянути коментарі до новини", callback_data="view_comments")
    ))
    await state.set_state(None)

async def start_add_comment_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.bot.answer_callback_query(callback_query.id)
    await callback_query.message.answer("Вкажіть *ID новини*, до якої ви хочете додати коментар:", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(CommentStates.waiting_for_news_id) # Set state here

async def process_comment_news_id_handler(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("Будь ласка, введіть коректний числовий ID новини\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    await state.update_data(news_id=int(msg.text))
    await msg.answer("Напишіть ваш *коментар*:", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(CommentStates.waiting_for_content) # Set state here

async def process_comment_content_handler(msg: types.Message, state: FSMContext):
    comment_content = msg.text
    user_data = await state.get_data()
    news_id = user_data['news_id']
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/comments/add", json={
            "user_id": user_id,
            "news_id": news_id,
            "content": comment_content
        })
        if resp.status == 200:
            await msg.answer("✅ Ваш коментар успішно додано і очікує модерації\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося додати коментар\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def start_view_comments_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.bot.answer_callback_query(callback_query.id)
    await callback_query.message.answer("Вкажіть *ID новини*, коментарі до якої ви хочете переглянути:", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(CommentStates.waiting_for_view_news_id) # Set state here

async def process_view_comments_news_id_handler(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("Будь ласка, введіть коректний числовий ID новини\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    news_id = int(msg.text)

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/comments/{news_id}")
        if resp.status == 200:
            comments = await resp.json()
            if comments:
                comments_text = f"*💬 Коментарі до новини ID `{escape_markdown_v2(str(news_id))}`:*\n\n"
                for comment in comments:
                    comment_content = escape_markdown_v2(comment['content'])
                    user_telegram_id = escape_markdown_v2(str(comment['user_telegram_id']) if comment['user_telegram_id'] else 'Невідомий')
                    comments_text += f"\\_\\*{user_telegram_id}*\\_ \n`{comment_content}`\n\n" # Виправлено екранування для імені користувача
                await msg.answer(comments_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("До цієї новини ще немає коментарів або вони очікують модерації\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити коментарі\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def show_trending_news_handler(msg: types.Message, state: FSMContext):
    """Показує трендові новини."""
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{WEBAPP_URL}/trending?limit=5")
        if resp.status == 200:
            trending_news = await resp.json()
            if trending_news:
                trend_text = "*🔥 Трендові новини:*\n\n"
                for item in trending_news:
                    title_escaped = escape_markdown_v2(item['title'])
                    trend_text += f"\\- `{escape_markdown_v2(str(item['id']))}`: {title_escaped}\n"
                await msg.answer(trend_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await msg.answer("Наразі немає трендових новин\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося завантажити трендові новини\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def invite_friend_handler(msg: types.Message, state: FSMContext):
    """Генерує унікальне посилання-запрошення для реферальної системи."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{WEBAPP_URL}/invite/generate", json={"inviter_user_id": user_id})
        if resp.status == 200:
            result = await resp.json()
            invite_code = escape_markdown_v2(result['invite_code'])
            await msg.answer(f"Запросіть друга, надіславши йому це посилання: `https://t.me/{BOT_USERNAME}?start={invite_code}`\n\n"
                             "Коли ваш друг приєднається за цим посиланням, ви отримаєте бонус!", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося згенерувати запрошення\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def back_to_main_menu_handler(msg: types.Message, state: FSMContext):
    """Повернення до головного меню."""
    await msg.answer("Ви повернулись до головного меню\\.", reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None) # Завжди очищаємо стан при поверненні в головне меню

async def unknown_message_handler(msg: types.Message, state: FSMContext):
    """Обробляє всі невідомі текстові повідомлення."""
    # Якщо бот знаходиться в стані FSM, не обробляємо як невідому команду
    current_state = await state.get_state()
    if current_state:
        logging.info(f"Received unknown message '{msg.text}' while in state {current_state}. Not clearing state.")
        return # Не очищаємо стан і не відповідаємо, очікуючи коректного вводу для поточного стану

    await msg.answer("🤔 Вибачте, я не розумію вашу команду\\. Будь ласка, скористайтесь меню або командою `/start`\\.", reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None) # Очищаємо стан на всяк випадок, якщо це було випадкове повідомлення

# Custom state group for comments
class CommentStates(StatesGroup):
    waiting_for_news_id = State()
    waiting_for_content = State()
    waiting_for_view_news_id = State()

# == ФУНКЦІЯ РЕЄСТРАЦІЇ ХЕНДЛЕРІВ ==
def register_telegram_handlers(dp: Dispatcher):
    """
    Реєструє всі хендлери та FSM стани у Aiogram Dispatcher.
    Ця функція буде викликана з webapp.py.
    """
    # Команди
    dp.message.register(start_command_handler, commands=["start"])
    dp.message.register(summary_command_handler, commands=["summary"])
    dp.message.register(verify_command_handler, commands=["verify"])
    dp.message.register(rate_news_command_handler, commands=["rate"])
    dp.message.register(invite_friend_handler, commands=["invite"])

    # Обробники кнопок головного меню
    dp.message.register(show_news_handler, lambda m: m.text == "📰 Новини")
    dp.message.register(show_filters_menu_handler, lambda m: m.text == "🎯 Фільтри")
    dp.message.register(show_settings_handler, lambda m: m.text == "⚙️ Налаштування")
    dp.message.register(daily_digest_menu_handler, lambda m: m.text == "📬 Щоденна розсилка")
    dp.message.register(show_analytics_handler, lambda m: m.text == "📊 Аналітика")
    dp.message.register(start_report_process_handler, lambda m: m.text == "❗ Скарга")
    dp.message.register(start_feedback_process_handler, lambda m: m.text == "💬 Відгук")
    dp.message.register(language_translate_handler, lambda m: m.text == "🌐 Мова / Переклад")
    dp.message.register(ai_features_handler, lambda m: m.text == "🧠 AI-аналіз")
    dp.message.register(back_to_main_menu_handler, lambda m: m.text == "⬅️ Головне меню")

    # Обробники кнопок меню AI-аналізу
    dp.message.register(summary_start_handler, lambda m: m.text == "🧠 AI Summary")
    dp.message.register(recommend_handler, lambda m: m.text == "💡 Рекомендації")
    dp.message.register(fact_check_start_handler, lambda m: m.text == "🔍 Фактчекінг")
    dp.message.register(rewrite_headline_start_handler, lambda m: m.text == "✍️ Переписати заголовок")

    # Обробники кнопок налаштувань
    dp.message.register(toggle_safe_mode_handler, lambda m: m.text == "🔒 Безпечний режим")
    dp.message.register(premium_info_handler, lambda m: m.text == "✨ Преміум")
    dp.message.register(email_subscription_menu_handler, lambda m: m.text == "📧 Email розсилка")
    dp.message.register(toggle_auto_notifications_handler, lambda m: m.text == "🔔 Авто-сповіщення")
    dp.message.register(set_view_mode_handler, lambda m: m.text == "👁️ Режим перегляду")

    # Обробники кнопок фільтрів
    dp.message.register(add_filter_start_handler, lambda m: m.text == "➕ Додати фільтр")
    dp.message.register(show_my_filters_handler, lambda m: m.text == "📝 Мої фільтри")
    dp.message.register(reset_filters_handler, lambda m: m.text == "🗑️ Скинути фільтри")
    dp.message.register(create_custom_feed_start_handler, lambda m: m.text == "🆕 Створити добірку")
    dp.message.register(switch_custom_feed_menu_handler, lambda m: m.text == "🔄 Переключити добірку")
    dp.message.register(edit_custom_feed_menu_handler, lambda m: m.text == "✏️ Редагувати добірку")

    # Обробники додаткових функцій
    dp.message.register(add_news_admin_start_handler, lambda m: m.text == "➕ Додати новину (Адмін)")
    dp.message.register(add_source_start_handler, lambda m: m.text == "➕ Додати джерело")
    dp.message.register(rate_news_start_handler, lambda m: m.text == "⭐ Оцінити новину")
    dp.message.register(show_bookmarks_handler, lambda m: m.text == "🔖 Закладки")
    dp.message.register(comments_menu_handler, lambda m: m.text == "💬 Коментарі")
    dp.message.register(show_trending_news_handler, lambda m: m.text == "📊 Тренд")


    # Callback Query handlers
    dp.callback_query.register(process_news_interaction_handler, lambda c: c.data.startswith('like_') or c.data.startswith('dislike_') or c.data.startswith('save_') or c.data.startswith('skip_'))
    dp.callback_query.register(process_filter_type_handler, lambda c: c.data.startswith('filter_type_'))
    dp.callback_query.register(add_feed_filter_handler, lambda c: c.data.startswith('add_feed_filter_'))
    dp.callback_query.register(finish_create_feed_handler, lambda c: c.data == 'finish_create_feed')
    dp.callback_query.register(process_switch_feed_handler, lambda c: c.data.startswith("switch_feed_"))
    dp.callback_query.register(handle_buy_premium_callback, lambda c: c.data == "buy_premium")
    dp.callback_query.register(request_email_input_callback, lambda c: c.data == "add_email" or c.data == "change_email")
    dp.callback_query.register(unsubscribe_email_callback, lambda c: c.data == "unsubscribe_email")
    dp.callback_query.register(process_view_mode_selection_callback, lambda c: c.data.startswith('set_view_mode_'))
    dp.callback_query.register(process_subscribe_daily_callback, lambda c: c.data.startswith('subscribe_daily_'))
    dp.callback_query.register(process_unsubscribe_daily_callback, lambda c: c.data == "unsubscribe_daily")
    dp.callback_query.register(process_report_type_handler, lambda c: c.data.startswith('report_'))
    dp.callback_query.register(request_interface_lang_callback, lambda c: c.data == "change_interface_lang")
    dp.callback_query.register(toggle_news_translation_callback, lambda c: c.data == "toggle_news_translation")
    dp.callback_query.register(process_source_type_callback, lambda c: c.data.startswith('source_type_'))
    dp.callback_query.register(start_add_comment_callback, lambda c: c.data == "add_comment")
    dp.callback_query.register(start_view_comments_callback, lambda c: c.data == "view_comments")

    # FSM handlers
    dp.message.register(process_filter_value_handler, state=FilterStates.waiting_for_filter_tag)
    dp.message.register(process_custom_feed_name_handler, state=CustomFeedStates.waiting_for_feed_name)
    dp.message.register(process_feed_filter_value_handler, state=CustomFeedStates.waiting_for_feed_filters_tags)
    dp.message.register(process_email_input_handler, state=ProfileSettingsStates.waiting_for_email)
    dp.message.register(process_interface_lang_change_handler, state=ProfileSettingsStates.waiting_for_language_change)
    dp.message.register(process_headline_rewrite_handler, state=AddNewsStates.waiting_for_title) # State for rewriting headline
    dp.message.register(process_news_title_handler, state=AddNewsStates.waiting_for_title)
    dp.message.register(process_news_content_handler, state=AddNewsStates.waiting_for_content)
    dp.message.register(process_news_lang_handler, state=AddNewsStates.waiting_for_lang)
    dp.message.register(process_news_country_handler, state=AddNewsStates.waiting_for_country)
    dp.message.register(process_news_tags_handler, state=AddNewsStates.waiting_for_tags)
    dp.message.register(process_news_source_name_handler, state=AddNewsStates.waiting_for_source_name)
    dp.message.register(process_news_link_handler, state=AddNewsStates.waiting_for_link)
    dp.message.register(process_news_media_handler, content_types=['photo', 'video', 'document', 'text'], state=AddNewsStates.waiting_for_media)
    dp.message.register(process_source_name_handler, state=AddSourceStates.waiting_for_source_name)
    dp.message.register(process_source_link_handler, state=AddSourceStates.waiting_for_source_link)
    dp.message.register(process_news_id_for_report_handler, state=ReportNewsStates.waiting_for_news_id_for_report)
    dp.message.register(process_report_reason_handler, state=ReportNewsStates.waiting_for_report_reason)
    dp.message.register(process_feedback_message_handler, state=FeedbackStates.waiting_for_feedback_message)
    dp.message.register(process_comment_news_id_handler, state=CommentStates.waiting_for_news_id)
    dp.message.register(process_comment_content_handler, state=CommentStates.waiting_for_content)
    dp.message.register(process_view_comments_news_id_handler, state=CommentStates.waiting_for_view_news_id)

    # Обробник невідомих повідомлень має бути останнім
    dp.message.register(unknown_message_handler)


# Flask/FastAPI app definition
app = FastAPI()

# Функція для запуску бота через webhook
@app.on_event("startup")
async def on_startup():
    logging.info("FastAPI додаток запускається...")
    # Приклад: перевірка підключення до БД при старті
    try:
        conn = await get_db_connection()
        await conn.close()
        logging.info("Підключення до бази даних успішне.")
    except Exception as e:
        logging.error(f"Помилка підключення до бази даних при старті: {e}")

    # Set webhook
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook встановлено на: {WEBHOOK_URL}")
    else:
        logging.info(f"Webhook вже встановлено на: {WEBHOOK_URL}")

    # Register handlers
    register_telegram_handlers(dp)
    
    # Start background task for auto notifications
    asyncio.create_task(send_auto_notifications_task())

@app.on_event("shutdown")
async def on_shutdown():
    logging.warning('Завершення роботи...')
    await bot.delete_webhook()
    await dp.storage.close()
    await bot.session.close()
    logging.warning('Завершено.')

# Telegram Bot Webhook Endpoint
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    telegram_update = types.Update(**await request.json())
    await dp.feed_update(bot, telegram_update)
    return {"ok": True}

