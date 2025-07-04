# telegram_handlers.py — Містить логіку обробки повідомлень для Telegram AI News бота
# Цей файл призначений для імпортування в webapp.py для роботи з Webhook

import os
import aiohttp
from datetime import datetime
import json # Потрібен для серіалізації фільтрів в JSONB
from aiogram import Dispatcher, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# API_URL буде передано з webapp.py через змінні оточення
API_URL = os.getenv("WEBAPP_URL", "http://localhost:8000")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot_username") # Для посилання-запрошення
MONOBANK_CARD_NUMBER = os.getenv("MONOBANK_CARD_NUMBER", "XXXX XXXX XXXX XXXX")


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

class CommentStates(StatesGroup):
    """Стани для додавання та перегляду коментарів."""
    waiting_for_news_id = State()
    waiting_for_content = State()
    waiting_for_view_news_id = State()

# Функція для екранування тексту для MarkdownV2
def escape_markdown_v2(text: str) -> str:
    """
    Екранує спеціальні символи MarkdownV2 у наданому тексті.
    """
    if not isinstance(text, (str, int, float)):
        text = str(text)

    special_chars = [
        '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+',
        '-', '=', '|', '{', '}', '.', '!'
    ]
    
    escaped_text = text
    for char in special_chars:
        escaped_text = escaped_text.replace(char, '\\' + char)
    
    if 'http' in text or 'https' in text:
        escaped_text = escaped_text.replace('\\/', '/')
    
    return escaped_text

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
        resp = await session.post(f"{API_URL}/users/register", json={
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
        resp = await session.get(f"{API_URL}/news/{user_id}?limit=1")
        if resp.status == 200:
            news_items = await resp.json()
            if news_items:
                news_item = news_items[0]
                await session.post(f"{API_URL}/log_user_activity", json={
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
            resp = await session.post(f"{API_URL}/bookmarks/add", json={"user_id": user_id, "news_id": news_id})
        else:
            resp = await session.post(f"{API_URL}/log_user_activity", json={"user_id": user_id, "news_id": news_id, "action": interaction_action})

        if resp.status == 200:
            await callback_query.message.answer(response_text)
            await callback_query.message.edit_reply_markup(reply_markup=None) # Приховуємо кнопки
            if interaction_action == "skip":
                # Передаємо message об'єкт для show_news_handler
                await show_news_handler(callback_query.message)
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
    # Встановлюємо загальний стан для введення значення фільтра
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
        resp = await session.post(f"{API_URL}/filters/update", json=payload)
        if resp.status == 200:
            await msg.answer(f"✅ Фільтр '`{escape_markdown_v2(filter_type)}`: `{escape_markdown_v2(str(filter_value))}`' успішно додано/оновлено\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await msg.answer("❌ Не вдалося додати/оновити фільтр. Спробуйте ще раз.")
    await state.set_state(None)


async def show_my_filters_handler(msg: types.Message):
    """Показує поточні активні фільтри користувача."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/filters/{user_id}")
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
        resp = await session.delete(f"{API_URL}/filters/reset/{user_id}")
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
    # Переходимо в загальний стан для додавання фільтрів до добірки
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
        resp = await session.post(f"{API_URL}/custom_feeds/create", json={
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
        resp = await session.get(f"{API_URL}/custom_feeds/{user_id}")
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
        resp = await session.post(f"{API_URL}/custom_feeds/switch", json={
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
        resp = await session.get(f"{API_URL}/custom_feeds/{user_id}")
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
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            current_safe_mode = profile.get('safe_mode', False)
            new_safe_mode = not current_safe_mode

            update_resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "safe_mode": new_safe_mode})
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
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
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
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
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
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "email": email})
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
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "email": None})
        if resp.status == 200:
            await callback_query.message.answer("✅ Ви успішно відписалися від Email\\-розсилки\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await callback_query.message.answer("❌ Не вдалося відписатися від Email\\-розсилки\\.", parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None)

async def toggle_auto_notifications_handler(msg: types.Message):
    """Перемикає автоматичні сповіщення про нові новини."""
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            current_auto_notifications = profile.get('auto_notifications', False)
            new_auto_notifications = not current_auto_notifications

            resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "auto_notifications": new_auto_notifications})
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
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
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
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "view_mode": new_view_mode})
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
        resp = await session.post(f"{API_URL}/subscriptions/update", json={"user_id": user_id, "frequency": frequency})
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
        resp = await session.post(f"{API_URL}/subscriptions/unsubscribe", params={"user_id": user_id})
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
        resp = await session.get(f"{API_URL}/analytics/{user_id}")
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

        resp = await session.post(f"{API_URL}/report", json=payload)
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
        resp = await session.post(f"{API_URL}/feedback", json={
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
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "language": new_lang})
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

        resp = await session.post(f"{API_URL}/summary", json=payload)
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
        resp = await session.get(f"{API_URL}/recommend/{user_id}")
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
        resp = await session.get(f"{API_URL}/verify/{news_id}")
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
    await AddNewsStates.waiting_for_title.set() # Reusing waiting_for_title state for generic text input

async def process_headline_rewrite_handler(msg: types.Message, state: FSMContext):
    """Переписує заголовок за допомогою AI."""
    original_headline = msg.text.strip()

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/ai/rewrite_headline", json={"text": original_headline})
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
        resp = await session.post(f"{API_URL}/news/add", json=news_data)
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
        resp = await session.post(f"{API_URL}/sources/add", json=source_data)
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
        resp = await session.post(f"{API_URL}/rate", json={
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
        resp = await session.get(f"{API_URL}/bookmarks/{user_id}")
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
    await CommentStates.waiting_for_news_id.set()

async def process_comment_news_id_handler(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("Будь ласка, введіть коректний числовий ID новини\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    await state.update_data(news_id=int(msg.text))
    await msg.answer("Напишіть ваш *коментар*:", parse_mode=ParseMode.MARKDOWN_V2)
    await CommentStates.waiting_for_content.set()

async def process_comment_content_handler(msg: types.Message, state: FSMContext):
    comment_content = msg.text
    user_data = await state.get_data()
    news_id = user_data['news_id']
    user_id = msg.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/comments/add", json={
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
    await CommentStates.waiting_for_view_news_id.set()

async def process_view_comments_news_id_handler(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("Будь ласка, введіть коректний числовий ID новини\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    news_id = int(msg.text)

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/comments/{news_id}")
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
        resp = await session.get(f"{API_URL}/trending?limit=5")
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
        resp = await session.post(f"{API_URL}/invite/generate", json={"inviter_user_id": user_id})
        if resp.status == 200:
            result = await resp.json()
            invite_code = escape_markdown_v2(result['invite_code'])
            # bot.get_me().await.username - це виклик, який має бути у контексті запущеного бота
            # Для цього файлу, якщо він не знає bot, треба передавати username або брати з ENV
            # Припустимо, що BOT_USERNAME встановлено в ENV
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
        # logging.info(f"Received unknown message '{msg.text}' while in state {current_state}. Not clearing state.")
        return # Не очищаємо стан і не відповідаємо, очікуючи коректного вводу для поточного стану

    await msg.answer("🤔 Вибачте, я не розумію вашу команду\\. Будь ласка, скористайтесь меню або командою `/start`\\.", reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    await state.set_state(None) # Очищаємо стан на всяк випадок, якщо це було випадкове повідомлення

# == ФУНКЦІЯ РЕЄСТРАЦІЇ ХЕНДЛЕРІВ ==
def register_handlers(dp: Dispatcher):
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
    dp.message.register(process_filter_value_handler, FilterStates.waiting_for_filter_tag)
    dp.message.register(process_custom_feed_name_handler, CustomFeedStates.waiting_for_feed_name)
    dp.message.register(process_feed_filter_value_handler, CustomFeedStates.waiting_for_feed_filters_tags)
    dp.message.register(process_email_input_handler, ProfileSettingsStates.waiting_for_email)
    dp.message.register(process_interface_lang_change_handler, ProfileSettingsStates.waiting_for_language_change)
    dp.message.register(process_headline_rewrite_handler, AddNewsStates.waiting_for_title) # State for rewriting headline
    dp.message.register(process_news_title_handler, AddNewsStates.waiting_for_title)
    dp.message.register(process_news_content_handler, AddNewsStates.waiting_for_content)
    dp.message.register(process_news_lang_handler, AddNewsStates.waiting_for_lang)
    dp.message.register(process_news_country_handler, AddNewsStates.waiting_for_country)
    dp.message.register(process_news_tags_handler, AddNewsStates.waiting_for_tags)
    dp.message.register(process_news_source_name_handler, AddNewsStates.waiting_for_source_name)
    dp.message.register(process_news_link_handler, AddNewsStates.waiting_for_link)
    dp.message.register(process_news_media_handler, content_types=['photo', 'video', 'document', 'text'], state=AddNewsStates.waiting_for_media)
    dp.message.register(process_source_name_handler, AddSourceStates.waiting_for_source_name)
    dp.message.register(process_source_link_handler, AddSourceStates.waiting_for_source_link)
    dp.message.register(process_news_id_for_report_handler, ReportNewsStates.waiting_for_news_id_for_report)
    dp.message.register(process_report_reason_handler, ReportNewsStates.waiting_for_report_reason)
    dp.message.register(process_feedback_message_handler, FeedbackStates.waiting_for_feedback_message)
    dp.message.register(process_comment_news_id_handler, CommentStates.waiting_for_news_id)
    dp.message.register(process_comment_content_handler, CommentStates.waiting_for_content)
    dp.message.register(process_view_comments_news_id_handler, CommentStates.waiting_for_view_news_id)

    # Обробник невідомих повідомлень має бути останнім
    dp.message.register(unknown_message_handler)

