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
from collections import defaultdict # Для трендів

# Імпорт для Gemini API (мокований, для реального використання потрібна бібліотека та автентифікація)
# from google.cloud import translate_v3beta1 as translate
# import google.generativeai as genai

app = FastAPI()

# Отримуємо Gemini API ключ з змінних оточення
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==== DATABASE CONNECTION ====
# Функція для отримання з'єднання з базою даних
async def get_db_connection():
    """
    Встановлює та повертає асинхронне з'єднання з базою даних PostgreSQL.
    Використовує змінну оточення DATABASE_URL.
    """
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        return conn
    except Exception as e:
        print(f"Помилка підключення до бази даних: {e}")
        raise HTTPException(status_code=500, detail="Помилка підключення до бази даних")

# ==== MODELS ====
# Модель для запиту на сумаризацію новини або тексту
class SummaryRequest(BaseModel):
    news_id: Optional[int] = None
    text: Optional[str] = None

# Модель для запиту на збереження відгуку
class FeedbackRequest(BaseModel):
    user_id: int
    message: str

# Модель для запиту на оцінку новини
class RateRequest(BaseModel):
    user_id: int
    news_id: int
    value: int

# Модель для запиту на блокування елемента (тег, джерело, мова, категорія)
class BlockRequest(BaseModel):
    user_id: int
    block_type: str # tag, source, language, category
    value: str

# Модель для запиту на підписку на дайджест
class DigestRequest(BaseModel):
    user_id: int
    frequency: Optional[str] = 'daily'

# Модель для запиту аналітики користувача
class AnalyticsRequest(BaseModel):
    user_id: int

# Модель для запиту на надсилання скарги
class ReportRequest(BaseModel):
    user_id: int
    news_id: Optional[int] = None # Може бути загальна скарга без ID новини
    reason: str

# Модель для запиту на додавання нового джерела
class SourceRequest(BaseModel):
    user_id: int
    name: str
    link: str
    type: str

# Модель для запиту на додавання нової новини
class NewsRequest(BaseModel):
    title: str
    content: str
    lang: str
    country: str
    tags: List[str]
    source: str
    link: Optional[str] = None
    published_at: Optional[datetime] = None
    file_id: Optional[str] = None
    media_type: Optional[str] = None
    source_type: Optional[str] = 'manual' # manual, rss, telegram, twitter etc.

# Модель для запиту на додавання новини до закладок
class BookmarkRequest(BaseModel):
    user_id: int
    news_id: int

# Модель для запиту на переклад тексту
class TranslateRequest(BaseModel):
    text: str
    target_language: str
    source_language: Optional[str] = None # Залишаємо опціональним, якщо потрібно автовизначення

# Модель для запиту на додавання реакції до новини
class ReactionRequest(BaseModel):
    user_id: int
    news_id: int
    reaction_type: str # наприклад, '❤️', '😮', '🤔'

# Модель для запиту на збереження результатів опитування
class PollResultRequest(BaseModel):
    user_id: int
    news_id: int
    question: str
    answer: str

# Модель для запиту на оновлення фільтрів користувача
class FilterUpdateRequest(BaseModel):
    user_id: int
    tag: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    content_type: Optional[str] = None

# Модель для запиту на створення персональної добірки
class CustomFeedRequest(BaseModel):
    user_id: int
    feed_name: str
    filters: Dict[str, Any] # JSONB поле для зберігання об'єкта фільтрів

# Модель для запиту на переключення активної добірки
class SwitchFeedRequest(BaseModel):
    user_id: int
    feed_id: int

# Модель для запиту на оновлення профілю користувача
class UserProfileUpdateRequest(BaseModel):
    user_id: int
    language: Optional[str] = None
    country: Optional[str] = None
    safe_mode: Optional[bool] = None
    is_premium: Optional[bool] = None
    email: Optional[str] = None
    auto_notifications: Optional[bool] = None
    view_mode: Optional[str] = None # 'manual' або 'auto'

# Модель для запиту на додавання коментаря
class CommentRequest(BaseModel):
    user_id: int
    news_id: int
    content: str
    parent_comment_id: Optional[int] = None

# Модель для запиту на адміністративні дії
class AdminActionRequest(BaseModel):
    admin_user_id: int # Telegram ID адміністратора
    action_type: str
    target_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None

# Модель для запиту на генерацію запрошувального коду
class InviteRequest(BaseModel):
    inviter_user_id: int
    invited_user_id: Optional[int] = None # Опціонально для прийняття запрошення

# Модель для запиту на логування взаємодії з новиною
class NewsInteractionRequest(BaseModel):
    user_id: int
    news_id: int
    action: str # view, read_full, skip etc.
    time_spent: Optional[int] = 0 # Для 'read_full'

# ==== UTILITY FUNCTIONS ====
async def update_user_stats(conn, user_id: int, stat_type: str, increment: int = 1):
    """
    Оновлює статистику користувача в таблиці `user_stats`.
    Створює запис, якщо його немає, або оновлює існуючий.
    """
    update_clause = ""
    if stat_type == "viewed":
        update_clause = "viewed = user_stats.viewed + $3"
    elif stat_type == "saved":
        update_clause = "saved = user_stats.saved + $3"
    elif stat_type == "reported":
        update_clause = "reported = user_stats.reported + $3"
    elif stat_type == "read_full_count":
        update_clause = "read_full_count = user_stats.read_full_count + $3"
    elif stat_type == "liked_count":
        update_clause = "liked_count = user_stats.liked_count + $3"
    elif stat_type == "disliked_count":
        update_clause = "disliked_count = user_stats.disliked_count + $3"
    elif stat_type == "comments_count":
        update_clause = "comments_count = user_stats.comments_count + $3"
    elif stat_type == "sources_added_count":
        update_clause = "sources_added_count = user_stats.sources_added_count + $3"

    if update_clause:
        await conn.execute(
            f"INSERT INTO user_stats (user_id, {stat_type}, last_active) VALUES ($1, $3, NOW()) ON CONFLICT (user_id) DO UPDATE SET {update_clause}, last_active = NOW()",
            user_id, increment
        )

# Черга для фонових задач обробки новин (наприклад, AI-аналіз)
processing_queue = asyncio.Queue()

async def news_processing_worker():
    """
    Фоновий воркер, який обробляє новини з черги.
    Виконує мокований AI-аналіз (класифікація, тональність, фактчекінг).
    """
    while True:
        news_item_id = await processing_queue.get()
        print(f"Обробка новини ID: {news_item_id} у фоновому режимі...")
        # Імітуємо роботу AI
        await asyncio.sleep(random.uniform(1, 3)) # Затримка для імітації роботи AI

        conn = await get_db_connection()
        try:
            news = await conn.fetchrow("SELECT content FROM news WHERE id = $1", news_item_id)
            if news:
                # Mock AI Classification
                topics = random.sample(["Політика", "Економіка", "Технології", "Спорт", "Культура", "Наука", "Здоров'я"], k=random.randint(1,3))
                # Mock AI Sentiment
                sentiment_map_keys = ["позитивний", "негативний", "нейтральний"]
                tone = random.choice(sentiment_map_keys)
                sentiment_score = random.uniform(-1.0, 1.0) # -1.0 до 1.0
                # Mock AI Fake Detection
                is_fake = random.random() < 0.1 # 10% шанс бути фейком

                await conn.execute(
                    """
                    UPDATE news
                    SET ai_classified_topics = $1, tone = $2, sentiment_score = $3, is_fake = $4
                    WHERE id = $5
                    """,
                    topics, tone, sentiment_score, is_fake, news_item_id
                )
                print(f"Новина ID: {news_item_id} оброблена AI.")

            # Імітуємо перевірку на дублікати
            if random.random() < 0.05: # 5% шанс, що є дублікат
                await conn.execute("UPDATE news SET is_duplicate = TRUE WHERE id = $1", news_item_id)
                print(f"Новина ID: {news_item_id} позначена як дублікат.")

        except Exception as e:
            print(f"Помилка при обробці новини ID {news_item_id}: {e}")
        finally:
            if conn:
                await conn.close()
        processing_queue.task_done()

async def cleanup_old_news_task():
    """
    Фонова задача для автоматичного архівації та видалення старих новин.
    Новини, що закінчилися, переміщуються до `archived_news`.
    Новини видаляються з `news`, якщо вони не збережені в закладках.
    """
    print("Запуск задачі очищення старих новин...")
    conn = await get_db_connection()
    try:
        # Переміщуємо новини, що закінчилися, до архіву
        archived_result = await conn.execute(
            """
            INSERT INTO archived_news (original_news_id, title, content, lang, country, tags, source, link, published_at, archived_at)
            SELECT id, title, content, lang, country, tags, source, link, published_at, NOW()
            FROM news
            WHERE expires_at < NOW() AND NOT EXISTS (SELECT 1 FROM archived_news WHERE original_news_id = news.id)
            """
        )
        archived_count = int(archived_result.split()[-1]) # Extract count from result string

        # Видаляємо новини з основної таблиці після архівації, якщо вони не збережені в закладках
        deleted_result = await conn.execute(
            """
            DELETE FROM news
            WHERE expires_at < NOW()
            AND NOT EXISTS (SELECT 1 FROM bookmarks WHERE news_id = news.id)
            """
        )
        deleted_count = int(deleted_result.split()[-1]) # Extract count from result string

        print(f"Заархівовано: {archived_count}. Видалено: {deleted_count} старих новин.")
    except Exception as e:
        print(f"Помилка в задачі очищення новин: {e}")
    finally:
        if conn:
            await conn.close()

# ==== API ENDPOINTS ====

@app.post("/users/register")
async def register_user(req: UserProfileUpdateRequest):
    """
    Реєструє нового користувача або оновлює існуючий профіль.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval(
            "SELECT id FROM users WHERE telegram_id = $1", req.user_id
        )
        if user_internal_id:
            # Оновлення існуючого користувача
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
            if req.is_premium is not None:
                update_parts.append(f"is_premium = ${param_idx}")
                params.append(req.is_premium)
                param_idx += 1
                if req.is_premium:
                    update_parts.append(f"premium_expires_at = ${param_idx}")
                    params.append(datetime.utcnow() + timedelta(days=30)) # 30 днів преміум
                    param_idx += 1
                else:
                    update_parts.append(f"premium_expires_at = NULL")
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

            if update_parts:
                query = f"UPDATE users SET {', '.join(update_parts)} WHERE telegram_id = ${param_idx}"
                params.append(req.user_id)
                await conn.execute(query, *params)
            return {"status": "success", "message": "Профіль оновлено"}
        else:
            # Створення нового користувача
            await conn.execute(
                """
                INSERT INTO users (telegram_id, language, country, created_at, safe_mode, is_premium, email, auto_notifications, view_mode)
                VALUES ($1, $2, $3, NOW(), $4, $5, $6, $7, $8)
                """,
                req.user_id, req.language, req.country,
                req.safe_mode if req.safe_mode is not None else False,
                req.is_premium if req.is_premium is not None else False,
                req.email,
                req.auto_notifications if req.auto_notifications is not None else False,
                req.view_mode if req.view_mode is not None else 'manual'
            )
            # Ініціалізація статистики користувача
            new_user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
            await update_user_stats(conn, new_user_internal_id, "viewed", 0) # Просто ініціалізуємо запис
            return {"status": "success", "message": "Користувача зареєстровано"}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Користувач з таким Telegram ID або email вже існує.")
    finally:
        if conn:
            await conn.close()

@app.get("/users/{user_id}/profile")
async def get_user_profile(user_id: int):
    """
    Повертає профіль користувача за його Telegram ID.
    """
    conn = await get_db_connection()
    try:
        profile = await conn.fetchrow(
            "SELECT id, telegram_id, language, country, safe_mode, current_feed_id, is_premium, premium_expires_at, level, badges, email, auto_notifications, view_mode FROM users WHERE telegram_id = $1",
            user_id
        )
        if profile:
            return dict(profile)
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    finally:
        if conn:
            await conn.close()

@app.post("/summary")
async def generate_summary(req: SummaryRequest):
    """
    Генерує резюме новини за ID або наданим текстом.
    Використовує кешування.
    """
    conn = await get_db_connection()
    try:
        # Перевірка, чи резюме вже кешовано
        if req.news_id:
            cached_summary = await conn.fetchrow(
                "SELECT summary FROM summaries WHERE news_id = $1", req.news_id
            )
            if cached_summary:
                return {"summary": cached_summary['summary']}

        # --- Мокована генерація резюме ---
        summary_text = f"🧠 Резюме для новини #{req.news_id or 'наданого тексту'}: Згенеровано AI. Це короткий опис новини, який висвітлює ключові моменти."
        if req.text:
            # У реальному сценарії тут був би виклик LLM для сумаризації req.text
            # chatHistory = [];
            # chatHistory.push({ role: "user", parts: [{ text: `Summarize the following text: ${req.text}` }] });
            # const payload = { contents: chatHistory };
            # const apiKey = GEMINI_API_KEY; # Використовуйте отриманий ключ
            # const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;
            # const response = await fetch(apiUrl, {
            #            method: 'POST',
            #            headers: { 'Content-Type': 'application/json' },
            #            body: JSON.stringify(payload)
            #        });
            # const result = response.json();
            # if (result.candidates && result.candidates.length > 0 && result.candidates[0].content && result.candidates[0].content.parts && result.candidates[0].content.parts.length > 0) {
            #     summary_text = result.candidates[0].content.parts[0].text;
            # } else {
            #     summary_text = f"Не вдалося згенерувати резюме для наданого тексту."
            # }

            summary_text = f"🧠 Резюме для наданого тексту: AI-генерований короткий виклад змісту '{req.text[:50]}...'."

        # Збереження резюме в кеш
        if req.news_id:
            await conn.execute(
                "INSERT INTO summaries (news_id, summary) VALUES ($1, $2) ON CONFLICT (news_id) DO UPDATE SET summary = $2",
                req.news_id, summary_text
            )
        return {"summary": summary_text}
    finally:
        if conn:
            await conn.close()

@app.post("/feedback")
async def save_feedback(req: FeedbackRequest):
    """
    Зберігає відгук користувача в базі даних.
    """
    conn = await get_db_connection()
    try:
        # Отримуємо внутрішній ID користувача
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO feedback (user_id, message) VALUES ($1, $2)",
            user_internal_id, req.message
        )
        return {"status": "saved", "user_id": req.user_id, "message": req.message}
    finally:
        if conn:
            await conn.close()

@app.post("/rate")
async def save_rating(req: RateRequest):
    """
    Зберігає оцінку новини користувачем.
    """
    if not (1 <= req.value <= 5):
        raise HTTPException(status_code=400, detail="Невірне значення рейтингу. Має бути від 1 до 5.")
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO ratings (user_id, news_id, value) VALUES ($1, $2, $3) ON CONFLICT (user_id, news_id) DO UPDATE SET value = $3",
            user_internal_id, req.news_id, req.value
        )
        return {"status": "rated", "news_id": req.news_id, "value": req.value}
    finally:
        if conn:
            await conn.close()

@app.post("/block")
async def block_entity(req: BlockRequest):
    """
    Додає елемент (тег, джерело, мову, категорію) до списку заблокованих користувачем.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO blocks (user_id, block_type, value) VALUES ($1, $2, $3) ON CONFLICT (user_id, block_type, value) DO NOTHING",
            user_internal_id, req.block_type, req.value
        )
        return {"blocked": True, "type": req.block_type, "value": req.value}
    finally:
        if conn:
            await conn.close()

@app.post("/subscriptions/update")
async def update_subscription(req: DigestRequest):
    """
    Оновлює або створює підписку користувача на дайджест.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO subscriptions (user_id, active, frequency) VALUES ($1, TRUE, $2) ON CONFLICT (user_id) DO UPDATE SET active = TRUE, frequency = $2",
            user_internal_id, req.frequency
        )
        return {"subscribed": True, "user_id": req.user_id, "frequency": req.frequency}
    finally:
        if conn:
            await conn.close()

@app.post("/subscriptions/unsubscribe")
async def unsubscribe(user_id: int):
    """
    Відписує користувача від розсилок.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
            
        await conn.execute(
            "UPDATE subscriptions SET active = FALSE WHERE user_id = $1", user_internal_id
        )
        return {"status": "success", "message": "Ви відписалися від розсилок"}
    finally:
        if conn:
            await conn.close()

@app.get("/analytics/{user_id}")
async def get_analytics(user_id: int):
    """
    Повертає статистику користувача, включаючи гейміфікаційні дані (рівень, бейджі).
    """
    conn = await get_db_connection()
    try:
        stats = await conn.fetchrow(
            """
            SELECT us.viewed, us.saved, us.reported, us.last_active, us.read_full_count, us.skipped_count,
                   us.liked_count, us.disliked_count, us.comments_count, us.sources_added_count,
                   u.level, u.badges
            FROM user_stats us
            JOIN users u ON us.user_id = u.id
            WHERE u.telegram_id = $1
            """,
            user_id
        )
        if stats:
            return dict(stats)
        
        # Якщо статистика користувача не знайдена, повертаємо значення за замовчуванням та рівень/бейджі користувача
        user_info = await conn.fetchrow(
            "SELECT level, badges FROM users WHERE telegram_id = $1", user_id
        )
        if user_info:
             return {"user_id": user_id, "viewed": 0, "saved": 0, "reported": 0, "last_active": None,
                "read_full_count": 0, "skipped_count": 0, "liked_count": 0, "disliked_count": 0,
                "comments_count": 0, "sources_added_count": 0, "level": user_info['level'], "badges": user_info['badges']}
        
        return {"user_id": user_id, "viewed": 0, "saved": 0, "reported": 0, "last_active": None,
                "read_full_count": 0, "skipped_count": 0, "liked_count": 0, "disliked_count": 0,
                "comments_count": 0, "sources_added_count": 0, "level": 0, "badges": []}
    finally:
        if conn:
            await conn.close()

@app.post("/report")
async def send_report(req: ReportRequest):
    """
    Зберігає скаргу на новину або загальну проблему в базі даних.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO reports (user_id, news_id, reason) VALUES ($1, $2, $3)",
            user_internal_id, req.news_id, req.reason
        )
        await update_user_stats(conn, user_internal_id, "reported")
        return {"status": "reported", "user_id": req.user_id, "news_id": req.news_id, "reason": req.reason}
    finally:
        if conn:
            await conn.close()

@app.get("/recommend/{user_id}")
async def get_recommendations(user_id: int):
    """
    Повертає рекомендовані новини для користувача.
    Наразі це мокована логіка, яка обирає випадкові новини.
    """
    conn = await get_db_connection()
    try:
        # У реальному додатку ця логіка використовувала б історію користувача, його фільтри,
        # взаємодії та AI-моделі для рекомендацій.
        news_items = await conn.fetch(
            "SELECT id, title FROM news OFFSET floor(random() * (SELECT count(*) FROM news)) LIMIT 5"
        )
        recommended_news = [{"id": n['id'], "title": n['title'], "score": round(random.uniform(0.7, 0.99), 2)}
                            for n in news_items]
        return {
            "user_id": user_id,
            "recommended": recommended_news
        }
    finally:
        if conn:
            await conn.close()

@app.get("/verify/{news_id}")
async def verify_news(news_id: int):
    """
    Імітує процес фактчекінгу новини.
    Повертає статус достовірності (фейк/не фейк) та впевненість.
    """
    conn = await get_db_connection()
    try:
        news_item = await conn.fetchrow("SELECT is_fake FROM news WHERE id = $1", news_id)
        if news_item:
            return {
                "news_id": news_id,
                "is_fake": news_item['is_fake'],
                "confidence": 0.87 if news_item['is_fake'] else 0.95, # Мокована впевненість
                "source": "AI fact-checker"
            }
        raise HTTPException(status_code=404, detail="Новину не знайдено")
    finally:
        if conn:
            await conn.close()

@app.post("/sources/add")
async def add_source(req: SourceRequest):
    """
    Додає нове джерело новин до бази даних.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        result = await conn.execute(
            "INSERT INTO sources (name, link, type, added_by_user_id) VALUES ($1, $2, $3, $4)",
            req.name, req.link, req.type, user_internal_id
        )
        if result == "INSERT 0 1":
            await update_user_stats(conn, user_internal_id, "sources_added_count")
            return {"status": "success", "message": "Джерело успішно додано", "source": req.name}
        raise HTTPException(status_code=400, detail="Не вдалося додати джерело")
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Джерело з таким посиланням або назвою вже існує.")
    finally:
        if conn:
            await conn.close()

@app.get("/sources")
async def list_sources():
    """
    Повертає список усіх зареєстрованих джерел новин.
    """
    conn = await get_db_connection()
    try:
        sources = await conn.fetch("SELECT id, name, link, type, verified, reliability_score, status FROM sources")
        return [dict(s) for s in sources]
    finally:
        if conn:
            await conn.close()

@app.post("/news/add")
async def add_news_manual(req: NewsRequest, background_tasks: BackgroundTasks):
    """
    Додає нову новину вручну (для адміністраторів/контент-мейкерів).
    Новина додається в чергу для AI-обробки.
    """
    conn = await get_db_connection()
    try:
        news_id = await conn.fetchval(
            """
            INSERT INTO news (title, content, lang, country, tags, source, link, published_at, file_id, media_type, source_type, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING id
            """,
            req.title, req.content, req.lang, req.country, req.tags, req.source, req.link,
            req.published_at if req.published_at else datetime.utcnow(), req.file_id, req.media_type, req.source_type,
            datetime.utcnow() + timedelta(hours=5) # Новина "вичерпується" через 5 годин, якщо не перевизначено
        )
        # Додаємо новину в чергу на AI-обробку
        background_tasks.add_task(processing_queue.put, news_id)
        return {"status": "success", "message": "Новина успішно додана та відправлена на обробку", "news_id": news_id}
    finally:
        if conn:
            await conn.close()

@app.get("/news/{user_id}")
async def get_filtered_news(user_id: int, limit: int = 5, offset: int = 0):
    """
    Повертає відфільтровані новини для конкретного користувача з пагінацією.
    Враховує індивідуальні фільтри, заблоковані елементи, безпечний режим,
    активну персональну добірку та вже переглянуті новини.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        user_settings = await conn.fetchrow(
            "SELECT safe_mode, current_feed_id FROM users WHERE telegram_id = $1", user_id
        )
        safe_mode = user_settings['safe_mode'] if user_settings else False
        current_feed_id = user_settings['current_feed_id'] if user_settings else None

        query = """
            SELECT n.id, n.title, n.content, n.lang, n.country, n.tags, n.ai_classified_topics,
                   n.source, n.link, n.published_at, n.file_id, n.media_type, n.tone, n.sentiment_score, n.is_fake
            FROM news n
            WHERE n.expires_at > NOW() AND n.is_duplicate = FALSE AND n.moderation_status = 'approved'
        """
        params = []
        param_idx = 1

        # Застосування фільтрів з персональної добірки, якщо вона активована
        if current_feed_id:
            feed_filters_data = await conn.fetchrow("SELECT filters FROM custom_feeds WHERE id = $1", current_feed_id)
            if feed_filters_data and feed_filters_data['filters']:
                # filters - це JSONB, тому потрібно розпарсити
                feed_filters = feed_filters_data['filters']
                if 'tags' in feed_filters and feed_filters['tags']:
                    query += f" AND (n.tags && ${param_idx}::TEXT[] OR n.ai_classified_topics && ${param_idx}::TEXT[])"
                    params.append(feed_filters['tags'])
                    param_idx += 1
                if 'sources' in feed_filters and feed_filters['sources']:
                    query += f" AND n.source IN (SELECT unnest(${param_idx}::TEXT[]))"
                    params.append(feed_filters['sources'])
                    param_idx += 1
                if 'languages' in feed_filters and feed_filters['languages']:
                    query += f" AND n.lang IN (SELECT unnest(${param_idx}::TEXT[]))"
                    params.append(feed_filters['languages'])
                    param_idx += 1
        else: # Застосування індивідуальних фільтрів користувача, якщо добірка не активована
            filters = await conn.fetchrow(
                "SELECT tag, category, source, language, country, content_type FROM filters WHERE user_id = $1", user_internal_id
            )
            if filters:
                if filters['tag']:
                    query += f" AND (n.tags && ARRAY[$ {param_idx}]::TEXT[] OR n.ai_classified_topics && ARRAY[$ {param_idx}]::TEXT[])"
                    params.append(filters['tag'])
                    param_idx += 1
                if filters['category']: # Припускаємо, що категорія є частиною тегів або AI-тем
                    query += f" AND (n.tags && ARRAY[$ {param_idx}]::TEXT[] OR n.ai_classified_topics && ARRAY[$ {param_idx}]::TEXT[])"
                    params.append(filters['category'])
                    param_idx += 1
                if filters['source']:
                    query += f" AND n.source = ${param_idx}"
                    params.append(filters['source'])
                    param_idx += 1
                if filters['language']:
                    query += f" AND n.lang = ${param_idx}"
                    params.append(filters['language'])
                    param_idx += 1
                if filters['country']:
                    query += f" AND n.country = ${param_idx}"
                    params.append(filters['country'])
                    param_idx += 1
                if filters['content_type']:
                    query += f" AND n.media_type = ${param_idx}"
                    params.append(filters['content_type'])
                    param_idx += 1

        # Виключаємо заблоковані елементи
        blocked_items = await conn.fetch(
            "SELECT block_type, value FROM blocks WHERE user_id = $1", user_internal_id
        )
        for block in blocked_items:
            if block['block_type'] == 'tag':
                query += f" AND NOT (n.tags && ARRAY[$ {param_idx}]::TEXT[] OR n.ai_classified_topics && ARRAY[$ {param_idx}]::TEXT[])"
                params.append(block['value'])
                param_idx += 1
            elif block['block_type'] == 'source':
                query += f" AND n.source != ${param_idx}"
                params.append(block['value'])
                param_idx += 1
            elif block['block_type'] == 'language':
                query += f" AND n.lang != ${param_idx}"
                params.append(block['value'])
                param_idx += 1
            elif block['block_type'] == 'category': # Блокування категорій, якщо вони окремо блокуються
                query += f" AND NOT (n.tags && ARRAY[$ {param_idx}]::TEXT[] OR n.ai_classified_topics && ARRAY[$ {param_idx}]::TEXT[])"
                params.append(block['value'])
                param_idx += 1

        # Застосування безпечного режиму (виключаємо "тривожні" та "негативні" тони, а також теги '18+', 'NSFW')
        if safe_mode:
            query += " AND (n.tone != 'тривожна' AND n.tone != 'негативний' OR n.tone IS NULL)"
            query += " AND NOT (n.tags && ARRAY['18+', 'NSFW']::TEXT[]) AND NOT (n.ai_classified_topics && ARRAY['18+', 'NSFW']::TEXT[])"


        # Виключаємо новини, які користувач вже переглянув у стрічці
        query += f" AND n.id NOT IN (SELECT news_id FROM user_news_views WHERE user_id = ${param_idx} AND viewed = TRUE)"
        params.append(user_internal_id)
        param_idx += 1

        query += f" ORDER BY n.published_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.append(limit)
        params.append(offset)

        news_items = await conn.fetch(query, *params)

        # Оновлення статистики переглядів (для новин, які були фактично повернуті)
        # Ця частина переміщена до bot.py в `send_news_item` для більш точного логування
        # того, що новина дійсно була "показана" користувачеві.
        # Однак, якщо ви хочете логувати тут, це також можливо.

        return [dict(n) for n in news_items]
    finally:
        if conn:
            await conn.close()

@app.post("/filters/update")
async def update_user_filters(req: FilterUpdateRequest):
    """
    Оновлює фільтри для конкретного користувача або створює їх, якщо не існують.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        existing_filter = await conn.fetchrow("SELECT id FROM filters WHERE user_id = $1", user_internal_id)

        update_parts = []
        params = []
        param_idx = 1
        if req.tag is not None:
            update_parts.append(f"tag = ${param_idx}")
            params.append(req.tag)
            param_idx += 1
        if req.category is not None:
            update_parts.append(f"category = ${param_idx}")
            params.append(req.category)
            param_idx += 1
        if req.source is not None:
            update_parts.append(f"source = ${param_idx}")
            params.append(req.source)
            param_idx += 1
        if req.language is not None:
            update_parts.append(f"language = ${param_idx}")
            params.append(req.language)
            param_idx += 1
        if req.country is not None:
            update_parts.append(f"country = ${param_idx}")
            params.append(req.country)
            param_idx += 1
        if req.content_type is not None:
            update_parts.append(f"content_type = ${param_idx}")
            params.append(req.content_type)
            param_idx += 1

        if existing_filter:
            if update_parts:
                query = f"UPDATE filters SET {', '.join(update_parts)} WHERE user_id = ${param_idx}"
                params.append(user_internal_id)
                await conn.execute(query, *params)
            return {"status": "success", "message": "Фільтри оновлено"}
        else:
            insert_fields = ["user_id"]
            insert_values = ["$1"]
            insert_params = [user_internal_id]
            current_param_idx = 2

            if req.tag is not None:
                insert_fields.append("tag")
                insert_values.append(f"${current_param_idx}")
                insert_params.append(req.tag)
                current_param_idx += 1
            if req.category is not None:
                insert_fields.append("category")
                insert_values.append(f"${current_param_idx}")
                insert_params.append(req.category)
                current_param_idx += 1
            if req.source is not None:
                insert_fields.append("source")
                insert_values.append(f"${current_param_idx}")
                insert_params.append(req.source)
                current_param_idx += 1
            if req.language is not None:
                insert_fields.append("language")
                insert_values.append(f"${current_param_idx}")
                insert_params.append(req.language)
                current_param_idx += 1
            if req.country is not None:
                insert_fields.append("country")
                insert_values.append(f"${current_param_idx}")
                insert_params.append(req.country)
                current_param_idx += 1
            if req.content_type is not None:
                insert_fields.append("content_type")
                insert_values.append(f"${current_param_idx}")
                insert_params.append(req.content_type)
                current_param_idx += 1

            query = f"INSERT INTO filters ({', '.join(insert_fields)}) VALUES ({', '.join(insert_values)})"
            await conn.execute(query, *insert_params)
            return {"status": "success", "message": "Фільтри створено"}
    finally:
        if conn:
            await conn.close()

@app.get("/filters/{user_id}")
async def get_user_filters(user_id: int):
    """
    Повертає поточні фільтри користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        filters = await conn.fetchrow(
            "SELECT tag, category, source, language, country, content_type FROM filters WHERE user_id = $1", user_internal_id
        )
        if filters:
            return dict(filters)
        return {} # Повертаємо порожній словник, якщо фільтрів немає
    finally:
        if conn:
            await conn.close()

@app.delete("/filters/reset/{user_id}")
async def reset_user_filters(user_id: int):
    """
    Видаляє всі фільтри для конкретного користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")
            
        await conn.execute("DELETE FROM filters WHERE user_id = $1", user_internal_id)
        return {"status": "success", "message": "Фільтри скинуто"}
    finally:
        if conn:
            await conn.close()

@app.get("/digest/{user_id}")
async def get_digest(user_id: int, hours: int = 24):
    """
    Повертає дайджест новин за останні 'hours' для конкретного користувача.
    Враховує фільтри користувача або активну персональну добірку.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        user_settings = await conn.fetchrow("SELECT current_feed_id FROM users WHERE telegram_id = $1", user_id)
        current_feed_id = user_settings['current_feed_id'] if user_settings else None

        query = """
            SELECT id, title, content, lang, country, tags, ai_classified_topics, source, link, published_at, file_id, media_type
            FROM news
            WHERE published_at >= NOW() - INTERVAL '$1 hours' AND is_duplicate = FALSE AND moderation_status = 'approved'
        """
        params = [hours]
        param_idx = 2

        if current_feed_id:
            feed_filters_data = await conn.fetchrow("SELECT filters FROM custom_feeds WHERE id = $1", current_feed_id)
            if feed_filters_data and feed_filters_data['filters']:
                feed_filters = feed_filters_data['filters'] # JSONB вже розпарсений
                if 'tags' in feed_filters and feed_filters['tags']:
                    query += f" AND (tags && ${param_idx}::TEXT[] OR ai_classified_topics && ${param_idx}::TEXT[])"
                    params.append(feed_filters['tags'])
                    param_idx += 1
                if 'sources' in feed_filters and feed_filters['sources']:
                    query += f" AND source IN (SELECT unnest(${param_idx}::TEXT[]))"
                    params.append(feed_filters['sources'])
                    param_idx += 1
                if 'languages' in feed_filters and feed_filters['languages']:
                    query += f" AND lang IN (SELECT unnest(${param_idx}::TEXT[]))"
                    params.append(feed_filters['languages'])
                    param_idx += 1
        else: # Застосування індивідуальних фільтрів, якщо добірка не активна
            filters_data = await conn.fetchrow(
                "SELECT tag, category, source, language, country, content_type FROM filters WHERE user_id = $1", user_internal_id
            )
            if filters_data:
                if filters_data['tag']:
                    query += f" AND (tags && ARRAY[$ {param_idx}]::TEXT[] OR ai_classified_topics && ARRAY[$ {param_idx}]::TEXT[])"
                    params.append(filters_data['tag'])
                    param_idx += 1
                if filters_data['source']:
                    query += f" AND source = ${param_idx}"
                    params.append(filters_data['source'])
                    param_idx += 1
                if filters_data['language']:
                    query += f" AND lang = ${param_idx}"
                    params.append(filters_data['language'])
                    param_idx += 1
                if filters_data['country']:
                    query += f" AND country = ${param_idx}"
                    params.append(filters_data['country'])
                    param_idx += 1
                if filters_data['content_type']:
                    query += f" AND media_type = ${param_idx}"
                    params.append(filters_data['content_type'])
                    param_idx += 1

        news_items = await conn.fetch(query + " ORDER BY published_at DESC", *params)
        return [dict(n) for n in news_items]
    finally:
        if conn:
            await conn.close()

@app.get("/news/search")
async def search_news(query: str, user_id: int, limit: int = 10, offset: int = 0):
    """
    Здійснює пошук новин за запитом у заголовках, вмісті, тегах та AI-класифікованих темах.
    """
    conn = await get_db_connection()
    try:
        search_pattern = f"%{query.lower()}%"
        # Пошук у заголовку, вмісті, тегах та AI-класифікованих темах
        news_items = await conn.fetch(
            """
            SELECT id, title, content, lang, country, tags, ai_classified_topics, source, link, published_at, file_id, media_type
            FROM news
            WHERE expires_at > NOW() AND moderation_status = 'approved'
            AND (LOWER(title) LIKE $1 OR LOWER(content) LIKE $1 OR $1 = ANY(tags) OR $1 = ANY(ai_classified_topics))
            ORDER BY published_at DESC
            LIMIT $2 OFFSET $3
            """,
            search_pattern, limit, offset
        )
        return [dict(n) for n in news_items]
    finally:
        if conn:
            await conn.close()

@app.post("/bookmarks/add")
async def add_bookmark(req: BookmarkRequest):
    """
    Додає новину до закладок користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO bookmarks (user_id, news_id) VALUES ($1, $2) ON CONFLICT (user_id, news_id) DO NOTHING",
            user_internal_id, req.news_id
        )
        await update_user_stats(conn, user_internal_id, "saved")
        return {"status": "success", "message": "Новина збережена в закладки"}
    finally:
        if conn:
            await conn.close()

@app.get("/bookmarks/{user_id}")
async def get_bookmarks(user_id: int, limit: int = 10, offset: int = 0):
    """
    Повертає список збережених новин (закладок) для користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        saved_news = await conn.fetch(
            """
            SELECT n.id, n.title, n.content, n.lang, n.country, n.tags, n.source, n.link, n.published_at, n.file_id, n.media_type
            FROM news n
            JOIN bookmarks b ON n.id = b.news_id
            WHERE b.user_id = $1
            ORDER BY b.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_internal_id, limit, offset
        )
        return [dict(n) for n in saved_news]
    finally:
        if conn:
            await conn.close()

@app.post("/translate")
async def translate_text(req: TranslateRequest):
    """
    Перекладає наданий текст на вказану цільову мову.
    Використовує кешування. Місце для інтеграції з Gemini API.
    """
    conn = await get_db_connection()
    try:
        # Перевірка кешу
        cached_translation = await conn.fetchrow(
            "SELECT translated_text FROM translations_cache WHERE original_text = $1 AND original_lang = $2 AND translated_lang = $3",
            req.text, req.source_language if req.source_language else 'auto', req.target_language
        )
        if cached_translation:
            return {"translated_text": cached_translation['translated_text']}

        # --- Мокований переклад ---
        mock_translated_text = f"[[Переклад на {req.target_language}]: {req.text} (моковано)]"

        # --- Приклад інтеграції з Gemini API для перекладу (потрібна реальна імплементація) ---
        # if GEMINI_API_KEY:
        #     try:
        #         # genai.configure(api_key=GEMINI_API_KEY)
        #         # model = genai.GenerativeModel('gemini-pro') # Або інша модель, що підтримує переклад
        #         # response = model.generate_content(f"Translate the following text into {req.target_language}: {req.text}")
        #         # mock_translated_text = response.text
        #         print("Gemini API інтеграція для перекладу тут (моковано)")
        #     except Exception as e:
        #         print(f"Помилка при виклику Gemini API для перекладу: {e}")

        # Збереження в кеш
        await conn.execute(
            "INSERT INTO translations_cache (original_text, original_lang, translated_text, translated_lang) VALUES ($1, $2, $3, $4)",
            req.text, req.source_language if req.source_language else 'auto', mock_translated_text, req.target_language
        )
        return {"translated_text": mock_translated_text}
    finally:
        if conn:
            await conn.close()

@app.post("/reactions/add")
async def add_reaction(req: ReactionRequest):
    """
    Додає або оновлює реакцію користувача на новину.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO reactions (user_id, news_id, reaction_type) VALUES ($1, $2, $3) ON CONFLICT (user_id, news_id) DO UPDATE SET reaction_type = $3",
            user_internal_id, req.news_id, req.reaction_type
        )
        # Оновлення статистики користувача для лайків/дизлайків
        if req.reaction_type == '❤️': # Або інші позитивні реакції
            await update_user_stats(conn, user_internal_id, "liked_count")
        # Додайте логіку для disliked_count для інших реакцій, якщо потрібно
        return {"status": "success", "message": f"Реакція '{req.reaction_type}' додана/оновлена"}
    finally:
        if conn:
            await conn.close()

@app.post("/polls/submit")
async def submit_poll_result(req: PollResultRequest):
    """
    Зберігає результат опитування/голосування користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO poll_results (user_id, news_id, question, answer) VALUES ($1, $2, $3, $4)",
            user_internal_id, req.news_id, req.question, req.answer
        )
        return {"status": "success", "message": "Результат опитування збережено"}
    finally:
        if conn:
            await conn.close()

@app.get("/trending")
async def get_trending_news(limit: int = 5):
    """
    Повертає список трендових новин, ґрунтуючись на переглядах та середньому рейтингу
    за останній період.
    """
    conn = await get_db_connection()
    try:
        # Логіка для трендових новин: базується на переглядах та середньому рейтингу за останні 24/48 годин
        trending_news = await conn.fetch(
            """
            SELECT n.id, n.title, n.content, n.lang, n.country, n.tags, n.source, n.link, n.published_at, n.file_id, n.media_type,
                   (COALESCE(unv.view_count, 0) + COALESCE(r.avg_rating, 0) * 10) AS trend_score
            FROM news n
            LEFT JOIN (SELECT news_id, COUNT(*) as view_count FROM user_news_views WHERE last_viewed_at >= NOW() - INTERVAL '24 hours' GROUP BY news_id) unv ON n.id = unv.news_id
            LEFT JOIN (SELECT news_id, AVG(value) as avg_rating FROM ratings WHERE created_at >= NOW() - INTERVAL '24 hours' GROUP BY news_id) r ON n.id = r.news_id
            WHERE n.expires_at > NOW() AND n.published_at >= NOW() - INTERVAL '48 hours' AND n.moderation_status = 'approved' AND n.is_duplicate = FALSE
            ORDER BY trend_score DESC, n.published_at DESC
            LIMIT $1
            """,
            limit
        )
        return [dict(n) for n in trending_news]
    finally:
        if conn:
            await conn.close()

@app.post("/custom_feeds/create")
async def create_custom_feed(req: CustomFeedRequest):
    """
    Створює нову персональну добірку новин для користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        result = await conn.fetchrow(
            "INSERT INTO custom_feeds (user_id, feed_name, filters) VALUES ($1, $2, $3::jsonb) RETURNING id",
            user_internal_id, req.feed_name, json.dumps(req.filters) # json.dumps для збереження JSONB
        )
        return {"status": "success", "message": "Персональна добірка створена", "feed_id": result['id']}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Добірка з такою назвою вже існує для цього користувача.")
    finally:
        if conn:
            await conn.close()

@app.get("/custom_feeds/{user_id}")
async def get_custom_feeds(user_id: int):
    """
    Повертає список усіх персональних добірок користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        feeds = await conn.fetch(
            "SELECT id, feed_name, filters FROM custom_feeds WHERE user_id = $1", user_internal_id
        )
        # Фільтри повертаються як JSONB, тому вони вже розпарсені asyncpg
        return [{"id": f['id'], "feed_name": f['feed_name'], "filters": f['filters']} for f in feeds]
    finally:
        if conn:
            await conn.close()

@app.post("/custom_feeds/switch")
async def switch_custom_feed(req: SwitchFeedRequest):
    """
    Переключає активну персональну добірку для користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        # Перевіряємо, чи існує добірка і належить вона цьому користувачеві
        feed_exists = await conn.fetchval(
            "SELECT id FROM custom_feeds WHERE id = $1 AND user_id = $2", req.feed_id, user_internal_id
        )
        if not feed_exists:
            raise HTTPException(status_code=404, detail="Добірку не знайдено або вона не належить цьому користувачеві.")

        await conn.execute(
            "UPDATE users SET current_feed_id = $1 WHERE id = $2",
            req.feed_id, user_internal_id
        )
        return {"status": "success", "message": f"Переключено на добірку ID: {req.feed_id}"}
    finally:
        if conn:
            await conn.close()

@app.post("/ai/classify_news")
async def classify_news(news_id: int, text: str):
    """
    Мокований AI-ендпоінт для класифікації новин.
    """
    # У реальному сценарії тут був би виклик LLM для класифікації
    topics = random.sample(["Політика", "Економіка", "Технології", "Спорт", "Культура", "Наука", "Здоров'я"], k=random.randint(1,3))
    return {
        "news_id": news_id,
        "topics": topics,
        "message": "AI класифікація виконана (моковано)"
    }

@app.post("/ai/analyze_sentiment")
async def analyze_sentiment(news_id: int, text: str):
    """
    Мокований AI-ендпоінт для аналізу тональності тексту.
    """
    # У реальному сценарії тут був би виклик LLM для аналізу тональності
    sentiment_map = {
        "позитивний": "оптимістична",
        "негативний": "тривожна",
        "нейтральний": "нейтральна"
    }
    sentiment_label = random.choice(list(sentiment_map.keys()))
    return {
        "news_id": news_id,
        "tone": sentiment_map[sentiment_label],
        "sentiment_score": random.uniform(-1.0, 1.0),
        "message": "AI аналіз тону виконаний (моковано)"
    }

@app.post("/ai/rewrite_headline")
async def rewrite_headline(text: str):
    """
    Мокований AI-ендпоінт для переписування заголовків.
    """
    # У реальному сценарії тут був би виклик LLM для генерації заголовків
    return {
        "original_text": text,
        "rewritten_headline": f"AI-заголовок: {text[:random.randint(15, 30)]}... (моковано)",
        "message": "AI переписав заголовок (моковано)"
    }

@app.post("/ai/deduplicate")
async def deduplicate_news_api(news_id: int, content: str):
    """
    Мокований AI-ендпоінт для дедуплікації новин.
    """
    # У реальності тут порівнювалися б хеші вмісту/вбудовування з існуючими новинами
    is_duplicate = random.random() < 0.1 # 10% шанс бути дублікатом
    potential_duplicates = []
    if is_duplicate:
        potential_duplicates = [{"id": 999, "title": "Мокована дублікат новини"}] # Приклад
    return {
        "news_id": news_id,
        "is_duplicate": is_duplicate,
        "potential_duplicates": potential_duplicates,
        "message": "AI дедуплікація виконана (моковано)"
    }

@app.get("/users/{user_id}/gamification_stats")
async def get_user_gamification_stats(user_id: int):
    """
    Повертає статистику гейміфікації для користувача.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        stats = await conn.fetchrow(
            """
            SELECT u.level, u.badges, us.viewed, us.saved, us.liked_count, us.comments_count, us.sources_added_count
            FROM users u
            JOIN user_stats us ON u.id = us.user_id
            WHERE u.id = $1
            """,
            user_internal_id
        )
        if stats:
            return dict(stats)
        raise HTTPException(status_code=404, detail="Статистика користувача не знайдена")
    finally:
        if conn:
            await conn.close()

@app.post("/log_user_activity")
async def log_user_activity(req: NewsInteractionRequest):
    """
    Логує деталізовану активність користувача щодо новин.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        await conn.execute(
            "INSERT INTO interactions (user_id, news_id, action, created_at) VALUES ($1, $2, $3, NOW())",
            user_internal_id, req.news_id, req.action
        )
        if req.action == 'read_full':
            await conn.execute(
                "UPDATE user_news_views SET read_full = TRUE, time_spent_seconds = $3 WHERE user_id = $1 AND news_id = $2",
                user_internal_id, req.news_id, req.time_spent
            )
            await update_user_stats(conn, user_internal_id, "read_full_count")
        elif req.action == 'skip':
             await update_user_stats(conn, user_internal_id, "skipped_count")
        # Додайте інші дії, які потребують оновлення статистики
        return {"status": "success", "message": "Дія зареєстрована"}
    finally:
        if conn:
            await conn.close()

@app.post("/comments/add")
async def add_comment(req: CommentRequest):
    """
    Додає новий коментар до новини.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача не знайдено.")

        comment_id = await conn.fetchval(
            "INSERT INTO comments (news_id, user_id, parent_comment_id, content) VALUES ($1, $2, $3, $4) RETURNING id",
            req.news_id, user_internal_id, req.parent_comment_id, req.content
        )
        await update_user_stats(conn, user_internal_id, "comments_count")
        return {"status": "success", "message": "Коментар додано", "comment_id": comment_id}
    finally:
        if conn:
            await conn.close()

@app.get("/comments/{news_id}")
async def get_comments(news_id: int):
    """
    Повертає список схвалених коментарів для конкретної новини.
    """
    conn = await get_db_connection()
    try:
        comments = await conn.fetch(
            """
            SELECT c.id, c.content, c.created_at, u.telegram_id as user_telegram_id, u.language as user_lang, c.parent_comment_id
            FROM comments c JOIN users u ON c.user_id = u.id
            WHERE c.news_id = $1 AND c.moderation_status = 'approved'
            ORDER BY c.created_at ASC
            """,
            news_id
        )
        return [dict(c) for c in comments]
    finally:
        if conn:
            await conn.close()

@app.post("/admin/moderate")
async def moderate_content(req: AdminActionRequest):
    """
    Ендпоінт для адміністраторів для модерації контенту (новини, коментарі, джерела).
    """
    conn = await get_db_connection()
    try:
        # Тут зазвичай перевіряється, чи має admin_user_id права адміністратора
        # Для цього моку припускаємо, що має.
        
        message = ""
        if req.action_type == "approve_news":
            await conn.execute("UPDATE news SET moderation_status = 'approved' WHERE id = $1", req.target_id)
            message = f"Новину ID {req.target_id} схвалено."
        elif req.action_type == "reject_news":
            await conn.execute("UPDATE news SET moderation_status = 'rejected' WHERE id = $1", req.target_id)
            message = f"Новину ID {req.target_id} відхилено."
        elif req.action_type == "approve_comment":
            await conn.execute("UPDATE comments SET moderation_status = 'approved' WHERE id = $1", req.target_id)
            message = f"Коментар ID {req.target_id} схвалено."
        elif req.action_type == "block_source":
            await conn.execute("UPDATE sources SET status = 'blocked' WHERE id = $1", req.target_id)
            await conn.execute("INSERT INTO blocked_sources (source_id, reason) VALUES ($1, $2) ON CONFLICT (source_id) DO UPDATE SET reason = $2", req.target_id, req.details.get("reason", "N/A") if req.details else "N/A")
            message = f"Джерело ID {req.target_id} заблоковано."
        else:
            raise HTTPException(status_code=400, detail="Невідома дія модерації")

        await conn.execute(
            "INSERT INTO admin_actions (admin_user_id, action_type, target_id, details) VALUES ($1, $2, $3, $4::jsonb)",
            req.admin_user_id, req.action_type, req.target_id, json.dumps(req.details) if req.details else {}
        )
        return {"status": "success", "message": message}
    finally:
        if conn:
            await conn.close()

@app.post("/invite/generate")
async def generate_invite_code(req: InviteRequest):
    """
    Генерує унікальний код запрошення для реферальної системи.
    """
    conn = await get_db_connection()
    try:
        user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", req.inviter_user_id)
        if not user_internal_id:
            raise HTTPException(status_code=404, detail="Користувача-запрошувача не знайдено.")

        # Генеруємо унікальний короткий код
        invite_code = f"INV{user_internal_id}-{datetime.utcnow().timestamp():.0f}{random.randint(1000, 9999)}"
        await conn.execute(
            "INSERT INTO invites (inviter_user_id, invite_code) VALUES ($1, $2)",
            user_internal_id, invite_code
        )
        return {"status": "success", "invite_code": invite_code}
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Вибачте, сталася помилка при генерації коду. Спробуйте ще раз.")
    finally:
        if conn:
            await conn.close()

@app.post("/invite/accept")
async def accept_invite(invite_code: str, invited_user_id: int):
    """
    Приймає запрошення. Якщо запрошення дійсне, пов'язує запрошеного користувача
    і надає бонуси (моковано).
    """
    conn = await get_db_connection()
    try:
        invite_record = await conn.fetchrow(
            "SELECT inviter_user_id FROM invites WHERE invite_code = $1 AND invited_user_id IS NULL AND accepted_at IS NULL", invite_code
        )
        if invite_record:
            inviter_user_internal_id = invite_record['inviter_user_id']
            
            # Отримуємо внутрішній ID запрошеного користувача (або реєструємо, якщо новий)
            invited_user_internal_id = await conn.fetchval("SELECT id FROM users WHERE telegram_id = $1", invited_user_id)
            if not invited_user_internal_id:
                # Реєструємо запрошеного користувача, якщо його немає
                invited_user_internal_id = await conn.fetchval(
                    "INSERT INTO users (telegram_id, created_at, inviter_id) VALUES ($1, NOW(), $2) RETURNING id",
                    invited_user_id, inviter_user_internal_id
                )
                await update_user_stats(conn, invited_user_internal_id, "viewed", 0) # Ініціалізація статистики
            else:
                # Оновлюємо inviter_id, якщо користувач вже існував, але приєднався за рефералом
                await conn.execute(
                    "UPDATE users SET inviter_id = $1 WHERE id = $2 AND inviter_id IS NULL",
                    inviter_user_internal_id, invited_user_internal_id
                )

            await conn.execute(
                "UPDATE invites SET invited_user_id = $1, accepted_at = NOW() WHERE invite_code = $2",
                invited_user_internal_id, invite_code
            )
            
            # Надаємо бонуси запрошувачу та запрошеному (моковано)
            await conn.execute("UPDATE users SET level = level + 1 WHERE id = $1", inviter_user_internal_id)
            await conn.execute("UPDATE users SET is_premium = TRUE, premium_expires_at = NOW() + INTERVAL '7 days' WHERE id = $1", invited_user_internal_id)
            
            return {"status": "success", "message": "Запрошення прийнято! Ви отримали бонус."}
        raise HTTPException(status_code=400, detail="Недійсний або вже використаний код запрошення.")
    finally:
        if conn:
            await conn.close()

@app.get("/api/news")
async def get_public_news_api(
    topic: Optional[str] = None,
    lang: Optional[str] = None,
    sentiment: Optional[str] = None,
    limit: int = 10,
    offset: int = 0
):
    """
    Публічний API-ендпоінт для отримання новин з можливістю фільтрації.
    """
    conn = await get_db_connection()
    try:
        query = "SELECT id, title, content, lang, country, tags, ai_classified_topics, source, link, published_at, tone, sentiment_score FROM news WHERE moderation_status = 'approved' AND expires_at > NOW() AND is_duplicate = FALSE"
        params = []
        param_idx = 1

        if topic:
            query += f" AND (ARRAY[${param_idx}] && tags OR ARRAY[${param_idx}] && ai_classified_topics)"
            params.append([topic]) # Передаємо як масив для оператора &&
            param_idx += 1
        if lang:
            query += f" AND lang = ${param_idx}"
            params.append(lang)
            param_idx += 1
        if sentiment:
            query += f" AND tone = ${param_idx}"
            params.append(sentiment)
            param_idx += 1

        query += f" ORDER BY published_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.append(limit)
        params.append(offset)

        news_items = await conn.fetch(query, *params)
        return [dict(n) for n in news_items]
    finally:
        if conn:
            await conn.close()

# Placeholder for cron jobs/background tasks for auto-cleanup and auto-notifications
@app.on_event("startup")
async def startup_event():
    """
    Виконується при запуску FastAPI додатка.
    Перевіряє підключення до БД, запускає фонові воркери та періодичні задачі.
    """
    print("FastAPI додаток запускається...")
    try:
        conn = await get_db_connection()
        await conn.close()
        print("Підключення до бази даних успішне.")
    except Exception as e:
        print(f"Помилка підключення до бази даних при старті: {e}")

    # Запускаємо фоновий воркер для AI-обробки новин
    asyncio.create_task(news_processing_worker())

    # Запускаємо періодичну задачу для очищення старих новин (кожні 4 години)
    async def schedule_cleanup():
        while True:
            await cleanup_old_news_task()
            await asyncio.sleep(4 * 3600) # 4 години

    asyncio.create_task(schedule_cleanup())

    # Запускаємо періодичну задачу для автоматичних сповіщень (наприклад, кожні 15 хвилин)
    async def schedule_auto_notifications():
        while True:
            conn = await get_db_connection()
            try:
                users_to_notify = await conn.fetch("SELECT telegram_id, id AS user_internal_id FROM users WHERE auto_notifications = TRUE AND view_mode = 'auto'")
                for user in users_to_notify:
                    # Отримуємо новини, які користувач ще не бачив і які відповідають його фільтрам
                    # Логіка тут має бути схожою на get_filtered_news, але без пагінації та з акцентом на нові новини
                    news_to_send = await conn.fetch(
                        """
                        SELECT n.id, n.title, n.content, n.lang, n.country, n.tags, n.source, n.link, n.published_at
                        FROM news n
                        WHERE n.expires_at > NOW()
                        AND n.id NOT IN (SELECT news_id FROM user_news_views WHERE user_id = $1 AND viewed = TRUE)
                        AND n.moderation_status = 'approved'
                        ORDER BY n.published_at DESC
                        LIMIT 1 -- Відправляємо по одній новішій новині за раз
                        """,
                        user['user_internal_id']
                    )
                    if news_to_send:
                        news_item = news_to_send[0]
                        # У реальному застосунку тут буде виклик Telegram Bot API для відправки повідомлення
                        # Це повинно бути асинхронним викликом, щоб не блокувати цикл
                        # import requests_async
                        # telegram_api_url = f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendMessage"
                        # text_message = f"🔔 Нова новина: *{news_item['title']}*\n\n{news_item['content']}\n\n[Читати більше]({news_item['link']})"
                        # await requests_async.post(telegram_api_url, json={'chat_id': user['telegram_id'], 'text': text_message, 'parse_mode': 'Markdown'})
                        
                        print(f"Відправлено автоматичне сповіщення користувачу {user['telegram_id']} про новину: {news_item['title']}")
                        # Позначаємо новину як переглянуту після відправки сповіщення
                        await conn.execute(
                            "INSERT INTO user_news_views (user_id, news_id, viewed, first_viewed_at) VALUES ($1, $2, TRUE, NOW()) ON CONFLICT (user_id, news_id) DO UPDATE SET viewed = TRUE, last_viewed_at = NOW()",
                            user['user_internal_id'], news_item['id']
                        )
                        await update_user_stats(conn, user['user_internal_id'], "viewed")

            except Exception as e:
                print(f"Помилка в задачі автоматичних сповіщень: {e}")
            finally:
                if conn:
                    await conn.close()
            await asyncio.sleep(15 * 60) # Кожні 15 хвилин

    asyncio.create_task(schedule_auto_notifications())

