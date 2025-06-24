# bot.py — Telegram AI News Бот: Повна інтеграція 500+ функцій

import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from dotenv import load_dotenv
import aiohttp
from datetime import datetime
import json

# Завантажуємо змінні оточення з файлу .env
load_dotenv()

# Отримуємо токен бота та URL веб-додатку з змінних оточення
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("WEBAPP_URL", "http://localhost:8000") # URL для взаємодії з FastAPI backend
MONOBANK_CARD_NUMBER = os.getenv("MONOBANK_CARD_NUMBER") # Номер картки Monobank, якщо є

# Ініціалізація бота та диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# Налаштування логування
logging.basicConfig(level=logging.INFO)

# ==== STATES ====
# Стани для додавання джерела
class AddSourceStates(StatesGroup):
    waiting_for_source_name = State()
    waiting_for_source_link = State()
    waiting_for_source_type = State()

# Стани для додавання новин (для адміністраторів/контент-мейкерів)
class AddNewsStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_content = State()
    waiting_for_lang = State()
    waiting_for_country = State()
    waiting_for_tags = State()
    waiting_for_source_name = State()
    waiting_for_link = State()
    waiting_for_media = State() # Для фото/file_id

# Стани для пошуку новин
class SearchNewsStates(StatesGroup):
    waiting_for_search_query = State()

# Стани для надсилання скарги на новину
class ReportNewsStates(StatesGroup):
    waiting_for_news_id_or_description = State()
    waiting_for_report_reason = State()

# Стани для перекладу тексту
class TranslateTextStates(StatesGroup):
    waiting_for_text_to_translate = State()
    waiting_for_target_language = State()

# Стани для оновлення фільтрів
class FilterUpdateStates(StatesGroup):
    waiting_for_filter_type = State()
    waiting_for_filter_value = State()

# Стани для керування персональними добірками новин
class CustomFeedStates(StatesGroup):
    waiting_for_feed_name = State()
    waiting_for_feed_filters_tags = State()
    waiting_for_feed_filters_sources = State()
    waiting_for_feed_filters_lang = State()

# Стани для додавання коментарів
class AddCommentStates(StatesGroup):
    waiting_for_comment_news_id = State()
    waiting_for_comment_text = State()
    waiting_for_parent_comment_id = State() # Для відповідей на коментарі

# Стани для керування преміум підпискою
class PremiumStates(StatesGroup):
    waiting_for_premium_confirm = State()

# Стани для email-розсилки
class EmailSubscriptionStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_frequency = State()


# == ОСНОВНІ КЛАВІАТУРИ ==

# Головне меню бота
main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(
    KeyboardButton("📰 Новини"),
    KeyboardButton("🎯 Фільтри"),
    KeyboardButton("⚙️ Налаштування"),
    KeyboardButton("📬 Розсилка новин"),
    KeyboardButton("📊 Моя Статистика"),
    KeyboardButton("❗ Скарга"),
    KeyboardButton("💬 Відгук"),
    KeyboardButton("🌐 Мова / Переклад"),
    KeyboardButton("🧠 AI-аналіз"),
    KeyboardButton("📚 Закладки"),
    KeyboardButton("🔥 Тренди"),
    KeyboardButton("🔍 Пошук новин")
)

# Інлайн-клавіатура для навігації по новинах (використовується в /myfeed)
news_navigation_keyboard = InlineKeyboardMarkup(row_width=2)
news_navigation_keyboard.add(
    InlineKeyboardButton("⬅️ Попередня", callback_data="news_prev"),
    InlineKeyboardButton("➡️ Наступна", callback_data="news_next"),
    InlineKeyboardButton("✅ Зберегти", callback_data="news_save"),
    InlineKeyboardButton("💬 Коментувати", callback_data="news_comment"),
    InlineKeyboardButton("📝 Коротко", callback_data="news_summary"),
    InlineKeyboardButton("👍 Оцінити", callback_data="news_rate_start"), # Додана кнопка оцінки
    InlineKeyboardButton("❓ Чому я це бачу?", callback_data="why_this_news")
)

# Інлайн-клавіатура для реакцій на новини (емодзі)
news_reactions_keyboard = InlineKeyboardMarkup(row_width=5)
news_reactions_keyboard.add(
    InlineKeyboardButton("❤️", callback_data="react_❤️"),
    InlineKeyboardButton("😮", callback_data="react_😮"),
    InlineKeyboardButton("🤔", callback_data="react_🤔"),
    InlineKeyboardButton("😢", callback_data="react_😢"),
    InlineKeyboardButton("😡", callback_data="react_😡")
)

# Інлайн-клавіатура для вибору типу фільтра
filter_type_keyboard = InlineKeyboardMarkup(row_width=2)
filter_type_keyboard.add(
    InlineKeyboardButton("Тема", callback_data="filter_type_tag"),
    InlineKeyboardButton("Категорія", callback_data="filter_type_category"),
    InlineKeyboardButton("Джерело", callback_data="filter_type_source"),
    InlineKeyboardButton("Мова", callback_data="filter_type_language"),
    InlineKeyboardButton("Країна", callback_data="filter_type_country"),
    InlineKeyboardButton("Тип контенту", callback_data="filter_type_content_type")
)

# Клавіатура меню налаштувань
settings_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
settings_keyboard.add(
    KeyboardButton("⚙️ Оновити фільтри"),
    KeyboardButton("🗑️ Скинути фільтри"),
    KeyboardButton("🖐️ Режим перегляду"),
    KeyboardButton("🔒 Безпечний режим"),
    KeyboardButton("➕ Додати джерело"),
    KeyboardButton("🧾 Мої джерела"),
    KeyboardButton("✍️ Створити добірку"),
    KeyboardButton("🔄 Переключити добірку"),
    KeyboardButton("💰 Преміум підписка"),
    KeyboardButton("💌 Email-розсилка"),
    KeyboardButton("🔔 Авто-сповіщення"),
    KeyboardButton("⬅️ Головне меню")
)

# Інлайн-клавіатура для вибору режиму перегляду новин
view_mode_keyboard = InlineKeyboardMarkup(row_width=2)
view_mode_keyboard.add(
    InlineKeyboardButton("🖐 Ручний (/myfeed)", callback_data="set_view_manual"),
    InlineKeyboardButton("🔔 Автоматичний дайджест", callback_data="set_view_auto")
)

# Інлайн-клавіатура для вибору частоти дайджесту
digest_frequency_keyboard = InlineKeyboardMarkup(row_width=2)
digest_frequency_keyboard.add(
    InlineKeyboardButton("Щодня", callback_data="digest_freq_daily"),
    InlineKeyboardButton("Щогодини", callback_data="digest_freq_hourly"),
    InlineKeyboardButton("Відписатись", callback_data="digest_unsubscribe")
)

# Клавіатура для меню AI-аналізу
ai_analysis_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
ai_analysis_keyboard.add(
    KeyboardButton("📝 Резюме новини"),
    KeyboardButton("💡 Рекомендації"),
    KeyboardButton("✅ Фактчекінг"),
    KeyboardButton("✍️ Переписати заголовок"),
    KeyboardButton("🎭 Аналіз тону"),
    KeyboardButton("🤔 Поясни мені новину"),
    KeyboardButton("⬅️ Головне меню")
)

# Інлайн-клавіатура для оцінки новини (зірочки)
rating_keyboard = InlineKeyboardMarkup(row_width=5)
for i in range(1, 6):
    rating_keyboard.insert(InlineKeyboardButton(str(i), callback_data=f"rate_{i}"))

# ==== ОБРОБНИКИ КОМАНД ====

@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    """
    Обробник команди /start.
    Реєструє або оновлює користувача в базі даних і надсилає привітання.
    """
    await msg.answer("👋 Ласкаво просимо до AI News Бота!", reply_markup=main_keyboard)
    async with aiohttp.ClientSession() as session:
        user_data = {
            "user_id": msg.from_user.id,
            "language": msg.from_user.language_code,
            "country": "UA" # Країна за замовчуванням, може бути змінена користувачем
        }
        # Реєстрація або оновлення профілю користувача
        await session.post(f"{API_URL}/users/register", json=user_data)
        # Отримуємо профіль, щоб перевірити статус преміум
        resp = await session.get(f"{API_URL}/users/{msg.from_user.id}/profile")
        if resp.status == 200:
            profile = await resp.json()
            if profile.get('is_premium'):
                await msg.answer("🎉 У вас активовано Преміум доступ!")
        await msg.answer("Якщо ви тут вперше, радимо налаштувати фільтри та джерела новин у розділі '⚙️ Налаштування'.")

@dp.message_handler(lambda m: m.text == "📰 Новини")
async def show_news_overview(msg: types.Message):
    """
    Надає загальний огляд новин та підказує, як їх переглядати.
    """
    await msg.answer("🗞️ Завантажую персональні новини...\n(Натисніть /myfeed для перегляду по одній, або /digest для дайджесту.)")

@dp.message_handler(lambda m: m.text == "🎯 Фільтри")
async def filters_menu(msg: types.Message):
    """
    Виводить меню фільтрів.
    """
    await msg.answer("🎯 Оберіть країну, тему, мову, джерело або заблокуйте те, що не цікавить", reply_markup=filter_type_keyboard)

@dp.message_handler(lambda m: m.text == "⚙️ Налаштування")
async def settings(msg: types.Message):
    """
    Виводить меню налаштувань.
    """
    await msg.answer("⚙️ Тут можна змінити мову, країну, добірки, джерела та інші параметри.", reply_markup=settings_keyboard)

@dp.message_handler(lambda m: m.text == "📬 Розсилка новин")
async def manage_digest_subscription(msg: types.Message):
    """
    Керування підписками на розсилки новин.
    """
    await msg.answer("📬 Керування розсилками: оберіть частоту або відпишіться.", reply_markup=digest_frequency_keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith("digest_freq_"))
async def set_digest_frequency(callback_query: types.CallbackQuery):
    """
    Обробник для вибору частоти дайджесту або відписки.
    """
    await bot.answer_callback_query(callback_query.id)
    frequency = callback_query.data.replace("digest_freq_", "")
    user_id = callback_query.from_user.id

    if frequency == "unsubscribe":
        async with aiohttp.ClientSession() as session:
            resp = await session.post(f"{API_URL}/subscriptions/unsubscribe", params={"user_id": user_id})
            if resp.status == 200:
                await callback_query.message.answer("✅ Ви успішно відписалися від розсилок.")
            else:
                await callback_query.message.answer("❌ Не вдалося відписатися. Спробуйте пізніше.")
    else:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(f"{API_URL}/subscriptions/update", json={"user_id": user_id, "frequency": frequency})
            if resp.status == 200:
                await callback_query.message.answer(f"✅ Ви підписалися на {frequency} розсилку.")
            else:
                await callback_query.message.answer("❌ Помилка підписки на розсилку. Спробуйте пізніше.")
    await callback_query.message.delete_reply_markup() # Видаляємо інлайн-клавіатуру після вибору

@dp.message_handler(lambda m: m.text == "📊 Моя Статистика")
async def analytics(msg: types.Message):
    """
    Виводить статистику користувача та інформацію про його ранг/бейджі.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/analytics/{msg.from_user.id}") as resp:
            if resp.status == 200:
                data = await resp.json()
                badges_text = ", ".join(data.get('badges', [])) if data.get('badges') else "Немає"
                await msg.answer(f"📊 Ваша Статистика та Ранг:\n"
                                 f"Рівень: {data.get('level', 0)}\n"
                                 f"Бейджі: {badges_text}\n"
                                 f"Переглянуто новин: {data.get('viewed', 0)}\n"
                                 f"Збережено новин: {data.get('saved', 0)}\n"
                                 f"Повністю прочитано: {data.get('read_full_count', 0)}\n"
                                 f"Вподобано: {data.get('liked_count', 0)}\n"
                                 f"Пропущено: {data.get('skipped_count', 0)}\n"
                                 f"Коментарів: {data.get('comments_count', 0)}\n"
                                 f"Додано джерел: {data.get('sources_added_count', 0)}\n"
                                 f"Останньо активний: {data.get('last_active', 'N/A')}")
            else:
                await msg.answer("❌ Не вдалося завантажити аналітику.")

@dp.message_handler(lambda m: m.text == "❗ Скарга")
async def report_news_start(msg: types.Message):
    """
    Початок процесу надсилання скарги на новину.
    """
    await msg.answer("❗ Введіть ID новини, на яку ви хочете поскаржитися, або коротко опишіть проблему.")
    await ReportNewsStates.waiting_for_news_id_or_description.set()

@dp.message_handler(state=ReportNewsStates.waiting_for_news_id_or_description)
async def process_report_news_id_or_description(msg: types.Message, state: FSMContext):
    """
    Обробляє введення ID новини або опису проблеми для скарги.
    """
    try:
        news_id = int(msg.text)
        await state.update_data(news_id=news_id, is_id=True)
        await msg.answer("Будь ласка, вкажіть причину скарги (наприклад, 'фейк', 'неактуально', 'образливий контент').")
        await ReportNewsStates.waiting_for_report_reason.set()
    except ValueError:
        await state.update_data(news_description=msg.text, is_id=False)
        await msg.answer("Будь ласка, вкажіть причину скарги (наприклад, 'фейк', 'неактуально', 'образливий контент').")
        await ReportNewsStates.waiting_for_report_reason.set()

@dp.message_handler(state=ReportNewsStates.waiting_for_report_reason)
async def process_report_reason(msg: types.Message, state: FSMContext):
    """
    Обробляє введення причини скарги та надсилає її на backend.
    """
    user_data = await state.get_data()
    reason = msg.text
    news_id = user_data.get('news_id')
    # news_description = user_data.get('news_description') # Не використовується API напряму, але для логування/контексту

    payload = {
        "user_id": msg.from_user.id,
        "reason": reason
    }
    if news_id:
        payload["news_id"] = news_id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/report", json=payload)
        if resp.status == 200:
            await msg.answer("✅ Ваша скарга була надіслана. Дякуємо за допомогу!")
        else:
            await msg.answer("❌ Не вдалося надіслати скаргу. Спробуйте пізніше.")
    await state.finish()

@dp.message_handler(lambda m: m.text == "💬 Відгук")
async def send_feedback_start(msg: types.Message):
    """
    Початок процесу надсилання відгуку.
    """
    await msg.answer("✍️ Напишіть ваш відгук, і ми обов'язково врахуємо його")
    await FSMContext.current().set_state("waiting_for_feedback_text")

@dp.message_handler(state="waiting_for_feedback_text")
async def process_feedback_text(msg: types.Message, state: FSMContext):
    """
    Обробляє текст відгуку та надсилає його на backend.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/feedback", json={"user_id": msg.from_user.id, "message": msg.text})
        if resp.status == 200:
            await msg.answer("✅ Ваш відгук було надіслано. Дякуємо!")
        else:
            await msg.answer("❌ Не вдалося надіслати відгук. Спробуйте пізніше.")
    await state.finish()

@dp.message_handler(lambda m: m.text == "🌐 Мова / Переклад")
async def language_translate(msg: types.Message):
    """
    Виводить інформацію про мову та переклад.
    """
    await msg.answer("🌍 Оберіть мову інтерфейсу та автоматичний переклад новин.\n"
                     "Ви можете також перекласти будь-який текст за допомогою команди /translate")

@dp.message_handler(commands=["translate"])
async def translate_command_start(msg: types.Message):
    """
    Початок процесу перекладу тексту.
    """
    await msg.answer("Будь ласка, надішліть текст, який ви хочете перекласти.")
    await TranslateTextStates.waiting_for_text_to_translate.set()

@dp.message_handler(state=TranslateTextStates.waiting_for_text_to_translate)
async def process_text_to_translate(msg: types.Message, state: FSMContext):
    """
    Обробляє текст для перекладу та запитує цільову мову.
    """
    await state.update_data(text_to_translate=msg.text)
    await msg.answer("На яку мову перекласти? (наприклад, en, uk, fr)")
    await TranslateTextStates.waiting_for_target_language.set()

@dp.message_handler(state=TranslateTextStates.waiting_for_target_language)
async def process_target_language(msg: types.Message, state: FSMContext):
    """
    Обробляє цільову мову та надсилає запит на переклад до backend.
    """
    data = await state.get_data()
    text_to_translate = data.get('text_to_translate')
    target_language = msg.text.lower()

    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.post(f"{API_URL}/translate", json={
                "text": text_to_translate,
                "target_language": target_language
            })
            if resp.status == 200:
                result = await resp.json()
                await msg.answer(f"Переклад: {result['translated_text']}")
            else:
                await msg.answer("❌ Помилка при перекладі. Спробуйте пізніше.")
        except Exception as e:
            await msg.answer(f"❌ Виникла помилка: {e}")
    await state.finish()


@dp.message_handler(lambda m: m.text == "🧠 AI-аналіз")
async def ai_features(msg: types.Message):
    """
    Виводить меню функцій AI-аналізу.
    """
    await msg.answer("🤖 Оберіть функцію AI-аналізу:", reply_markup=ai_analysis_keyboard)

@dp.message_handler(lambda m: m.text == "📝 Резюме новини")
@dp.message_handler(commands=["summary"])
async def summary(msg: types.Message):
    """
    Генерує резюме новини за ID або наданим текстом.
    """
    args = msg.get_args()
    news_id = None
    text_to_summarize = None

    if args and args.isdigit():
        news_id = int(args)
    elif args:
        text_to_summarize = args

    if not news_id and not text_to_summarize:
        await msg.answer("Будь ласка, вкажіть ID новини: /summary 123 або надішліть текст для резюме.")
        return

    async with aiohttp.ClientSession() as session:
        payload = {}
        if news_id:
            payload['news_id'] = news_id
        elif text_to_summarize:
            payload['text'] = text_to_summarize

        resp = await session.post(f"{API_URL}/summary", json=payload)
        if resp.status == 200:
            result = await resp.json()
            await msg.answer(f"🧠 Резюме: {result['summary']}")
        else:
            await msg.answer("❌ Помилка при генерації резюме. Можливо, новини з таким ID не існує.")

@dp.message_handler(lambda m: m.text == "💡 Рекомендації")
@dp.message_handler(commands=["recommend"])
async def recommend(msg: types.Message):
    """
    Отримує та виводить рекомендації новин для користувача.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/recommend/{msg.from_user.id}")
        if resp.status == 200:
            data = await resp.json()
            if data['recommended']:
                response_text = "📌 Вам можуть сподобатись ці новини:\n"
                for news_item in data['recommended']:
                    response_text += f"- ID: {news_item['id']}, Заголовок: {news_item['title']} (Оцінка: {news_item['score']})\n"
                await msg.answer(response_text)
            else:
                await msg.answer("🤷‍♀️ Наразі немає рекомендацій для вас.")
        else:
            await msg.answer("❌ Помилка при отриманні рекомендацій.")

@dp.message_handler(lambda m: m.text == "✅ Фактчекінг")
@dp.message_handler(commands=["verify"])
async def verify_news_command(msg: types.Message):
    """
    Перевіряє новину на достовірність (фактчекінг).
    """
    args = msg.get_args()
    if not args or not args.isdigit():
        await msg.answer("Будь ласка, вкажіть ID новини для перевірки: /verify 123")
        return
    news_id = int(args)
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/verify/{news_id}")
        if resp.status == 200:
            result = await resp.json()
            status_text = "⚠️ Потенційно фейкова новина!" if result['is_fake'] else "✅ Перевірено. Ймовірно, правдива новина."
            await msg.answer(f"{status_text}\nНовина #{news_id}. Достовірність: {result['confidence']*100:.0f}% (Джерело: {result['source']})")
        else:
            await msg.answer("❌ Не вдалося перевірити новину. Спробуйте пізніше.")

@dp.message_handler(lambda m: m.text == "✍️ Переписати заголовок")
@dp.message_handler(commands=["rewrite_headline"])
async def rewrite_headline_command(msg: types.Message):
    """
    Переписує заголовок новини за допомогою AI.
    """
    args = msg.get_args()
    if not args:
        await msg.answer("Будь ласка, вкажіть текст, заголовок якого потрібно переписати: /rewrite_headline [ваш текст]")
        return
    text = args

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/ai/rewrite_headline", json={"text": text})
        if resp.status == 200:
            result = await resp.json()
            await msg.answer(f"Оригінал: \"{text}\"\nПереписаний заголовок: \"{result['rewritten_headline']}\"")
        else:
            await msg.answer("❌ Не вдалося переписати заголовок. Спробуйте пізніше.")

@dp.message_handler(lambda m: m.text == "🎭 Аналіз тону")
@dp.message_handler(commands=["analyze_tone"])
async def analyze_tone_command(msg: types.Message):
    """
    Аналізує тон наданого тексту за допомогою AI.
    """
    args = msg.get_args()
    if not args:
        await msg.answer("Будь ласка, вкажіть текст для аналізу тону: /analyze_tone [ваш текст]")
        return
    text = args

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/ai/analyze_sentiment", json={"news_id": 0, "text": text})
        if resp.status == 200:
            result = await resp.json()
            await msg.answer(f"Аналіз тону:\nТон: {result['tone']}\nОцінка: {result['sentiment_score']:.2f}")
        else:
            await msg.answer("❌ Не вдалося проаналізувати тон. Спробуйте пізніше.")

@dp.message_handler(lambda m: m.text == "🤔 Поясни мені новину")
@dp.message_handler(commands=["explain_news"])
async def explain_news_command(msg: types.Message):
    """
    Пояснює новину простими словами (AI Assistant).
    """
    args = msg.get_args()
    if not args:
        await msg.answer("Будь ласка, вкажіть ID новини, яку потрібно пояснити: /explain_news 123")
        return
    news_id = args
    # Це б ідеально отримувало вміст новини, а потім відправляло його до LLM для спрощення
    await msg.answer(f"Ось спрощене пояснення новини ID {news_id}: (моковано) Ця новина розповідає про [основна подія] простими словами.")

@dp.message_handler(lambda m: m.text == "➕ Додати джерело")
@dp.message_handler(commands=["addsource"])
async def add_source_start(msg: types.Message):
    """
    Початок процесу додавання нового джерела новин.
    """
    await msg.answer("Надішліть назву джерела (наприклад, 'Українська Правда').")
    await AddSourceStates.waiting_for_source_name.set()

@dp.message_handler(state=AddSourceStates.waiting_for_source_name)
async def process_source_name(msg: types.Message, state: FSMContext):
    """
    Обробляє назву джерела.
    """
    await state.update_data(name=msg.text)
    await msg.answer("Надішліть посилання на джерело (URL або ID Telegram-каналу).")
    await AddSourceStates.waiting_for_source_link.set()

@dp.message_handler(state=AddSourceStates.waiting_for_source_link)
async def process_source_link(msg: types.Message, state: FSMContext):
    """
    Обробляє посилання на джерело.
    """
    await state.update_data(link=msg.text)
    await msg.answer("Вкажіть тип джерела (наприклад, 'Telegram', 'RSS', 'Twitter', 'Website').")
    await AddSourceStates.waiting_for_source_type.set()

@dp.message_handler(state=AddSourceStates.waiting_for_source_type)
async def process_source_type(msg: types.Message, state: FSMContext):
    """
    Обробляє тип джерела та надсилає дані на backend для додавання.
    """
    user_data = await state.get_data()
    source_name = user_data['name']
    source_link = user_data['link']
    source_type = msg.text

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/sources/add", json={
            "user_id": msg.from_user.id,
            "name": source_name,
            "link": source_link,
            "type": source_type
        })
        if resp.status == 200:
            await msg.answer(f"✅ Джерело '{source_name}' успішно додано!")
        elif resp.status == 400:
            await msg.answer(f"❌ Помилка: {await resp.json().get('detail', 'Джерело вже існує або дані невірні.')}")
        else:
            await msg.answer("❌ Виникла помилка при додаванні джерела. Спробуйте пізніше.")
    await state.finish()

@dp.message_handler(lambda m: m.text == "🧾 Мої джерела")
@dp.message_handler(commands=["sources"])
async def list_sources(msg: types.Message):
    """
    Виводить список доступних джерел.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/sources")
        if resp.status == 200:
            sources = await resp.json()
            if sources:
                response_text = "📜 Доступні джерела:\n"
                for s in sources:
                    verified_status = "✅" if s['verified'] else "⚠️"
                    reliability = f" (Надійність: {s['reliability_score']})" if s['reliability_score'] else ""
                    response_text += f"- {s['name']} ({s['type']}) {verified_status}{reliability} [ID: {s['id']}]\n"
                await msg.answer(response_text)
            else:
                await msg.answer("🤷‍♀️ Наразі немає доданих джерел.")
        else:
            await msg.answer("❌ Не вдалося завантажити список джерел.")

@dp.message_handler(commands=["myfeed"])
async def my_feed_start(msg: types.Message, state: FSMContext):
    """
    Розпочинає режим перегляду персональної стрічки новин по одній.
    """
    await state.update_data(current_news_offset=0)
    await send_news_item(msg, state)

async def send_news_item(msg: types.Message, state: FSMContext):
    """
    Відправляє одну новину користувачеві з навігаційними кнопками.
    """
    user_data = await state.get_data()
    offset = user_data.get("current_news_offset", 0)

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/news/{msg.from_user.id}", params={"limit": 1, "offset": offset})
        if resp.status == 200:
            news_items = await resp.json()
            if news_items:
                news_item = news_items[0]
                text = f"*{news_item['title']}*\n\n{news_item['content']}\n\n" \
                       f"[Джерело: {news_item['source']}]({news_item['link']})\n\n" \
                       f"_{news_item.get('tone', '')} | ID: {news_item['id']}_" # Додаємо тон

                markup = news_navigation_keyboard
                if news_item.get('is_fake'):
                    text += "\n\n🛑 *Ця новина позначена як потенційно фейкова.*"
                
                await bot.send_message(msg.chat.id, text, parse_mode="Markdown", reply_markup=markup)
                await bot.send_message(msg.chat.id, "Як вам ця новина?", reply_markup=news_reactions_keyboard)

                await state.update_data(last_sent_news_id=news_item['id'])
                # Логуємо взаємодію "view"
                await session.post(f"{API_URL}/log_user_activity", json={"user_id": msg.from_user.id, "news_id": news_item['id'], "action": "view"})

            else:
                await msg.answer("ℹ️ Новини закінчилися або відсутні за вашими фільтрами. Спробуйте змінити фільтри.", reply_markup=main_keyboard)
                await state.finish()
        else:
            await msg.answer("❌ Не вдалося завантажити новини. Спробуйте пізніше.", reply_markup=main_keyboard)
            await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("news_"))
async def process_news_navigation(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обробляє навігацію по новинах (наступна, попередня, зберегти, коментувати, резюме).
    """
    await bot.answer_callback_query(callback_query.id)
    user_data = await state.get_data()
    current_offset = user_data.get("current_news_offset", 0)
    last_sent_news_id = user_data.get("last_sent_news_id")

    if callback_query.data == "news_next":
        await state.update_data(current_news_offset=current_offset + 1)
        await send_news_item(callback_query.message, state)
        async with aiohttp.ClientSession() as session:
            await session.post(f"{API_URL}/log_user_activity", json={"user_id": callback_query.from_user.id, "news_id": last_sent_news_id, "action": "skip"})
    elif callback_query.data == "news_prev":
        if current_offset > 0:
            await state.update_data(current_news_offset=current_offset - 1)
            await send_news_item(callback_query.message, state)
        else:
            await callback_query.message.answer("Ви на першій новині.")
    elif callback_query.data == "news_save":
        if last_sent_news_id:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(f"{API_URL}/bookmarks/add", json={"user_id": callback_query.from_user.id, "news_id": last_sent_news_id})
                if resp.status == 200:
                    await callback_query.message.answer("✅ Новина збережена у закладки!")
                else:
                    await callback_query.message.answer("❌ Не вдалося зберегти новину.")
            await session.post(f"{API_URL}/log_user_activity", json={"user_id": callback_query.from_user.id, "news_id": last_sent_news_id, "action": "save"})
        else:
            await callback_query.message.answer("Немає активної новини для збереження.")
    elif callback_query.data == "news_comment":
        if last_sent_news_id:
            await state.update_data(commenting_news_id=last_sent_news_id)
            await callback_query.message.answer("Будь ласка, введіть ваш коментар:")
            await AddCommentStates.waiting_for_comment_text.set()
        else:
            await callback_query.message.answer("Немає активної новини для коментування.")
    elif callback_query.data == "news_summary":
        if last_sent_news_id:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(f"{API_URL}/summary", json={"news_id": last_sent_news_id})
                if resp.status == 200:
                    result = await resp.json()
                    await callback_query.message.answer(f"📝 Короткий зміст новини:\n{result['summary']}")
                else:
                    await callback_query.message.answer("❌ Не вдалося отримати резюме новини.")
        else:
            await callback_query.message.answer("Немає активної новини для резюме.")
    elif callback_query.data == "news_rate_start":
        if last_sent_news_id:
            await state.update_data(rating_news_id=last_sent_news_id)
            await callback_query.message.answer("Оцініть новину від 1 до 5 зірок:", reply_markup=rating_keyboard)
        else:
            await callback_query.message.answer("Немає активної новини для оцінки.")


@dp.callback_query_handler(lambda c: c.data == "why_this_news")
async def why_this_news_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Пояснює користувачеві, чому йому була показана ця новина, виходячи з його фільтрів та налаштувань.
    """
    await bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id
    async with aiohttp.ClientSession() as session:
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
        profile = await profile_resp.json()
        current_feed_id = profile.get('current_feed_id')
        
        filter_text = "Цю новину показано, тому що:\n"
        
        if current_feed_id:
            feed_resp = await session.get(f"{API_URL}/custom_feeds/{user_id}")
            feeds = await feed_resp.json()
            active_feed = next((f for f in feeds if f['id'] == current_feed_id), None)
            if active_feed:
                filter_text += f"- Ви використовуєте персональну добірку: *{active_feed['feed_name']}*\n"
                if active_feed['filters']:
                    for k, v in active_feed['filters'].items():
                        filter_text += f"  - За фільтром: {k.capitalize()}: {v}\n"
            else:
                filter_text += "- Ваша активна добірка не знайдена. Новини обираються за основними фільтрами.\n"
        
        # Використовуємо індивідуальні фільтри, якщо немає активної добірки або якщо добірка не містить певних фільтрів
        filters_resp = await session.get(f"{API_URL}/filters/{user_id}")
        filters = await filters_resp.json()
        if filters and not current_feed_id: # Показуємо, якщо немає кастомної добірки
            for key, value in filters.items():
                if value:
                    filter_text += f"- {key.capitalize()}: {value}\n"
        
        if not filters and not current_feed_id: # Якщо взагалі немає фільтрів
            filter_text += "- У вас немає активних фільтрів. Новини обираються випадково."
            
        await callback_query.message.answer(filter_text, parse_mode="Markdown")

# === Обробники для коментарів (FSM) ===
@dp.message_handler(state=AddCommentStates.waiting_for_comment_text)
async def process_comment_text(msg: types.Message, state: FSMContext):
    """
    Обробляє текст коментаря та надсилає його на backend.
    """
    user_data = await state.get_data()
    news_id = user_data.get('commenting_news_id')
    comment_content = msg.text

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/comments/add", json={
            "user_id": msg.from_user.id,
            "news_id": news_id,
            "content": comment_content
        })
        if resp.status == 200:
            await msg.answer("✅ Ваш коментар додано!")
        else:
            await msg.answer("❌ Не вдалося додати коментар.")
    await state.finish()

# === Обробники для оновлення фільтрів ===
@dp.callback_query_handler(lambda c: c.data.startswith("filter_type_"))
async def process_filter_type_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обробляє вибір типу фільтра та запитує значення.
    """
    await bot.answer_callback_query(callback_query.id)
    filter_type = callback_query.data.replace("filter_type_", "")
    await state.update_data(filter_type=filter_type)
    await callback_query.message.answer(f"Введіть значення для фільтра '{filter_type}'.")
    await FilterUpdateStates.waiting_for_filter_value.set()

@dp.message_handler(state=FilterUpdateStates.waiting_for_filter_value)
async def process_filter_value(msg: types.Message, state: FSMContext):
    """
    Обробляє значення фільтра та надсилає його на backend для оновлення.
    """
    user_data = await state.get_data()
    filter_type = user_data['filter_type']
    filter_value = msg.text

    payload = {"user_id": msg.from_user.id}
    payload[filter_type] = filter_value

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/filters/update", json=payload)
        if resp.status == 200:
            await msg.answer(f"✅ Фільтр '{filter_type}' оновлено на '{filter_value}'.")
        else:
            await msg.answer("❌ Не вдалося оновити фільтр. Спробуйте пізніше.")
    await state.finish()

@dp.message_handler(lambda m: m.text == "🗑️ Скинути фільтри")
@dp.message_handler(commands=["resetfilters"])
async def reset_filters(msg: types.Message):
    """
    Скидає всі фільтри користувача.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.delete(f"{API_URL}/filters/reset/{msg.from_user.id}")
        if resp.status == 200:
            await msg.answer("✅ Ваші фільтри були скинуті.")
        else:
            await msg.answer("❌ Не вдалося скинути фільтри. Спробуйте пізніше.")

@dp.message_handler(commands=["digest"])
async def send_digest(msg: types.Message):
    """
    Надсилає користувачеві дайджест новин.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/digest/{msg.from_user.id}", params={"hours": 5})
        if resp.status == 200:
            news_items = await resp.json()
            if news_items:
                digest_text = "📚 Ваш дайджест новин за останні 5 годин:\n\n"
                for item in news_items:
                    digest_text += f"▪️ *{item['title']}*\n"
                    digest_text += f"[Читати більше]({item['link']})\n\n"
                await msg.answer(digest_text, parse_mode="Markdown")
            else:
                await msg.answer("🤷‍♀️ Наразі немає новин для дайджесту за вашими фільтрами.")
        else:
            await msg.answer("❌ Не вдалося завантажити дайджест.")

@dp.message_handler(commands=["addnews"])
async def add_news_start(msg: types.Message):
    """
    Початок процесу ручного додавання новини (для адмінів/контент-мейкерів).
    """
    # Ця команда, ймовірно, повинна бути обмежена для адміністраторів у реальному додатку
    await msg.answer("📝 Введіть заголовок новини:")
    await AddNewsStates.waiting_for_title.set()

@dp.message_handler(state=AddNewsStates.waiting_for_title)
async def process_add_news_title(msg: types.Message, state: FSMContext):
    """
    Обробляє заголовок новини.
    """
    await state.update_data(title=msg.text)
    await msg.answer("📰 Введіть текст новини:")
    await AddNewsStates.waiting_for_content.set()

@dp.message_handler(state=AddNewsStates.waiting_for_content)
async def process_add_news_content(msg: types.Message, state: FSMContext):
    """
    Обробляє текст новини.
    """
    await state.update_data(content=msg.text)
    await msg.answer("🌐 Введіть мову новини (наприклад, uk, en):")
    await AddNewsStates.waiting_for_lang.set()

@dp.message_handler(state=AddNewsStates.waiting_for_lang)
async def process_add_news_lang(msg: types.Message, state: FSMContext):
    """
    Обробляє мову новини.
    """
    await state.update_data(lang=msg.text)
    await msg.answer("🗺️ Введіть країну новини (наприклад, UA, US):")
    await AddNewsStates.waiting_for_country.set()

@dp.message_handler(state=AddNewsStates.waiting_for_country)
async def process_add_news_country(msg: types.Message, state: FSMContext):
    """
    Обробляє країну новини.
    """
    await state.update_data(country=msg.text)
    await msg.answer("🏷️ Введіть теги через кому (наприклад, політика, економіка):")
    await AddNewsStates.waiting_for_tags.set()

@dp.message_handler(state=AddNewsStates.waiting_for_tags)
async def process_add_news_tags(msg: types.Message, state: FSMContext):
    """
    Обробляє теги новини.
    """
    await state.update_data(tags=[tag.strip() for tag in msg.text.split(',')])
    await msg.answer("📚 Введіть назву джерела новини:")
    await AddNewsStates.waiting_for_source_name.set()

@dp.message_handler(state=AddNewsStates.waiting_for_source_name)
async def process_add_news_source(msg: types.Message, state: FSMContext):
    """
    Обробляє назву джерела для новини.
    """
    await state.update_data(source=msg.text)
    await msg.answer("🔗 (Опціонально) Додайте посилання на оригінал новини:")
    await AddNewsStates.waiting_for_link.set()

@dp.message_handler(state=AddNewsStates.waiting_for_link)
async def process_add_news_link(msg: types.Message, state: FSMContext):
    """
    Обробляє посилання на оригінал новини.
    """
    await state.update_data(link=msg.text if msg.text.lower() != "/skip" else None)
    await msg.answer("📎 (Опціонально) Надішліть фото або документ, або /skip:")
    await AddNewsStates.waiting_for_media.set()

@dp.message_handler(content_types=types.ContentType.PHOTO | types.ContentType.DOCUMENT | types.ContentType.TEXT, state=AddNewsStates.waiting_for_media)
async def process_add_news_media(msg: types.Message, state: FSMContext):
    """
    Обробляє медіа (фото/документ) для новини та завершує додавання новини.
    """
    file_id = None
    media_type = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
        media_type = "photo"
    elif msg.document:
        file_id = msg.document.file_id
        media_type = "document"
    elif msg.text.lower() == "/skip":
        pass
    else:
        await msg.answer("Будь ласка, надішліть фото, документ або /skip.")
        return

    await state.update_data(file_id=file_id, media_type=media_type)
    user_data = await state.get_data()

    payload = {
        "title": user_data['title'],
        "content": user_data['content'],
        "lang": user_data['lang'],
        "country": user_data['country'],
        "tags": user_data['tags'],
        "source": user_data['source'],
        "link": user_data.get('link'),
        "file_id": user_data.get('file_id'),
        "media_type": user_data.get('media_type'),
        "source_type": "manual"
    }

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/news/add", json=payload)
        if resp.status == 200:
            await msg.answer("✅ Новина успішно додана!")
        else:
            await msg.answer("❌ Не вдалося додати новину. Спробуйте пізніше.")
    await state.finish()

@dp.message_handler(lambda m: m.text == "📚 Закладки")
@dp.message_handler(commands=["bookmarks"])
async def show_bookmarks(msg: types.Message, state: FSMContext):
    """
    Виводить список збережених новин (закладок).
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/bookmarks/{msg.from_user.id}")
        if resp.status == 200:
            bookmarks = await resp.json()
            if bookmarks:
                response_text = "📖 Ваші збережені новини:\n\n"
                for item in bookmarks:
                    response_text += f"▪️ *{item['title']}*\n"
                    response_text += f"[Читати більше]({item['link']})\n\n"
                await msg.answer(response_text, parse_mode="Markdown")
            else:
                await msg.answer("У вас ще немає збережених новин.")
        else:
            await msg.answer("❌ Не вдалося завантажити закладки.")

@dp.message_handler(lambda m: m.text == "🔥 Тренди")
@dp.message_handler(commands=["trending"])
async def show_trending_news(msg: types.Message):
    """
    Виводить список трендових новин.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/trending")
        if resp.status == 200:
            trending = await resp.json()
            if trending:
                response_text = "📈 Найпопулярніше сьогодні:\n\n"
                for item in trending:
                    response_text += f"▪️ *{item['title']}*\n"
                    response_text += f"[Читати більше]({item['link']})\n\n"
                await msg.answer(response_text, parse_mode="Markdown")
            else:
                await msg.answer("🤷‍♀️ Наразі немає трендових новин.")
        else:
            await msg.answer("❌ Не вдалося завантажити тренди.")

@dp.message_handler(lambda m: m.text == "🔍 Пошук новин")
@dp.message_handler(commands=["search"])
async def search_news_start(msg: types.Message):
    """
    Початок процесу пошуку новин.
    """
    await msg.answer("Будь ласка, введіть ваш запит для пошуку новин:")
    await SearchNewsStates.waiting_for_search_query.set()

@dp.message_handler(state=SearchNewsStates.waiting_for_search_query)
async def process_search_query(msg: types.Message, state: FSMContext):
    """
    Обробляє пошуковий запит та виводить результати.
    """
    search_query = msg.text
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/news/search", params={"query": search_query, "user_id": msg.from_user.id})
        if resp.status == 200:
            news_items = await resp.json()
            if news_items:
                response_text = f"🔎 Результати пошуку за '{search_query}':\n\n"
                for item in news_items:
                    response_text += f"▪️ *{item['title']}*\n"
                    response_text += f"[Читати більше]({item['link']})\n\n"
                await msg.answer(response_text, parse_mode="Markdown")
            else:
                await msg.answer(f"🤷‍♀️ За запитом '{search_query}' нічого не знайдено.")
        else:
            await msg.answer("❌ Помилка при виконанні пошуку. Спробуйте пізніше.")
    await state.finish()


@dp.callback_query_handler(lambda c: c.data.startswith("react_"))
async def process_reaction_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обробляє реакції користувача на новини (емодзі).
    """
    await bot.answer_callback_query(callback_query.id)
    reaction_type = callback_query.data.split('_')[1]
    user_id = callback_query.from_user.id
    user_data = await state.get_data()
    news_id = user_data.get("last_sent_news_id")

    if not news_id:
        await callback_query.message.answer("Не вдалося визначити новину для реакції.")
        return

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/reactions/add", json={
            "user_id": user_id,
            "news_id": news_id,
            "reaction_type": reaction_type
        })
        if resp.status == 200:
            await callback_query.message.answer(f"Ви відреагували на новину '{reaction_type}'!")
            # За бажанням, можна видалити клавіатуру реакцій, щоб запобігти множинним реакціям
            # await callback_query.message.edit_reply_markup(reply_markup=None)
        else:
            await callback_query.message.answer("❌ Не вдалося додати реакцію.")

@dp.callback_query_handler(lambda c: c.data.startswith("rate_"))
async def process_rating_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обробляє оцінку новини (зірочки).
    """
    await bot.answer_callback_query(callback_query.id)
    rating_value = int(callback_query.data.split('_')[1])
    user_id = callback_query.from_user.id
    user_data = await state.get_data()
    news_id = user_data.get("rating_news_id")

    if not news_id:
        await callback_query.message.answer("Не вдалося визначити новину для оцінки.")
        return

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/rate", json={
            "user_id": user_id,
            "news_id": news_id,
            "value": rating_value
        })
        if resp.status == 200:
            await callback_query.message.answer(f"Ви оцінили новину на {rating_value} зірок!")
            # await callback_query.message.edit_reply_markup(reply_markup=None) # Видалити кнопки оцінки
        else:
            await callback_query.message.answer("❌ Не вдалося додати оцінку.")

@dp.message_handler(lambda m: m.text == "🔒 Безпечний режим")
async def toggle_safe_mode(msg: types.Message):
    """
    Перемикає безпечний режим (вмикає/вимикає фільтрацію NSFW контенту).
    """
    user_id = msg.from_user.id
    async with aiohttp.ClientSession() as session:
        # Отримуємо поточний статус безпечного режиму, щоб його переключити
        profile_resp = await session.get(f"{API_URL}/users/{user_id}/profile")
        if profile_resp.status == 200:
            profile = await profile_resp.json()
            current_safe_mode = profile.get('safe_mode', False)
            new_safe_mode = not current_safe_mode
            resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "safe_mode": new_safe_mode})
            if resp.status == 200:
                status_text = "увімкнено" if new_safe_mode else "вимкнено"
                await msg.answer(f"✅ Безпечний режим {status_text}. Тепер ви будете бачити/не бачити контент '18+'.")
            else:
                await msg.answer("❌ Не вдалося змінити безпечний режим.")
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача.")


@dp.message_handler(lambda m: m.text == "🖐️ Режим перегляду")
async def choose_view_mode(msg: types.Message):
    """
    Дозволяє користувачеві вибрати режим перегляду новин (ручний або автоматичний дайджест).
    """
    await msg.answer("Оберіть, як ви бажаєте отримувати новини:", reply_markup=view_mode_keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith("set_view_"))
async def set_view_mode(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Встановлює обраний користувачем режим перегляду новин.
    """
    await bot.answer_callback_query(callback_query.id)
    view_mode = callback_query.data.replace("set_view_", "")
    user_id = callback_query.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "view_mode": view_mode})
        if resp.status == 200:
            if view_mode == "manual":
                await callback_query.message.answer("Ви обрали ручний режим перегляду новин. Використовуйте /myfeed.")
            elif view_mode == "auto":
                await callback_query.message.answer("Ви обрали автоматичний режим дайджесту. Новини надходитимуть регулярно.")
        else:
            await callback_query.message.answer("❌ Не вдалося змінити режим перегляду.")
    await callback_query.message.delete_reply_markup()

@dp.message_handler(lambda m: m.text == "✍️ Створити добірку")
async def create_custom_feed_start(msg: types.Message):
    """
    Початок процесу створення нової персональної добірки новин.
    """
    await msg.answer("Введіть назву для вашої нової добірки:")
    await CustomFeedStates.waiting_for_feed_name.set()

@dp.message_handler(state=CustomFeedStates.waiting_for_feed_name)
async def process_custom_feed_name(msg: types.Message, state: FSMContext):
    """
    Обробляє назву добірки та запитує теги.
    """
    await state.update_data(feed_name=msg.text, new_feed_filters={})
    await msg.answer("Тепер налаштуйте фільтри для цієї добірки. Введіть теги через кому (напр., політика, економіка) або /skip:")
    await CustomFeedStates.waiting_for_feed_filters_tags.set()

@dp.message_handler(state=CustomFeedStates.waiting_for_feed_filters_tags)
async def process_custom_feed_tags(msg: types.Message, state: FSMContext):
    """
    Обробляє теги для добірки та запитує джерела.
    """
    if msg.text.lower() != "/skip":
        tags = [t.strip() for t in msg.text.split(',')]
        await state.update_data(new_feed_filters_tags=tags)
    await msg.answer("Введіть джерела через кому (напр., Українська Правда, BBC) або /skip:")
    await CustomFeedStates.waiting_for_feed_filters_sources.set()

@dp.message_handler(state=CustomFeedStates.waiting_for_feed_filters_sources)
async def process_custom_feed_sources(msg: types.Message, state: FSMContext):
    """
    Обробляє джерела для добірки та запитує мови.
    """
    if msg.text.lower() != "/skip":
        sources = [s.strip() for s in msg.text.split(',')]
        await state.update_data(new_feed_filters_sources=sources)
    await msg.answer("Введіть мови через кому (напр., uk, en) або /skip:")
    await CustomFeedStates.waiting_for_feed_filters_lang.set()

@dp.message_handler(state=CustomFeedStates.waiting_for_feed_filters_lang)
async def process_custom_feed_lang(msg: types.Message, state: FSMContext):
    """
    Обробляє мови для добірки та надсилає дані на backend для створення добірки.
    """
    if msg.text.lower() != "/skip":
        languages = [l.strip() for l in msg.text.split(',')]
        await state.update_data(new_feed_filters_lang=languages)

    user_data = await state.get_data()
    feed_name = user_data['feed_name']
    filters = {}
    if 'new_feed_filters_tags' in user_data:
        filters['tags'] = user_data['new_feed_filters_tags']
    if 'new_feed_filters_sources' in user_data:
        filters['sources'] = user_data['new_feed_filters_sources']
    if 'new_feed_filters_lang' in user_data:
        filters['languages'] = user_data['new_feed_filters_lang']

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/custom_feeds/create", json={
            "user_id": msg.from_user.id,
            "feed_name": feed_name,
            "filters": filters
        })
        if resp.status == 200:
            await msg.answer(f"✅ Добірка '{feed_name}' успішно створена!")
        else:
            await msg.answer("❌ Не вдалося створити добірку. Спробуйте пізніше.")
    await state.finish()

@dp.message_handler(lambda m: m.text == "🔄 Переключити добірку")
async def switch_custom_feed_start(msg: types.Message):
    """
    Дозволяє користувачеві переключитися на одну зі своїх персональних добірок.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{API_URL}/custom_feeds/{msg.from_user.id}")
        if resp.status == 200:
            feeds = await resp.json()
            if feeds:
                keyboard = InlineKeyboardMarkup(row_width=1)
                for feed in feeds:
                    keyboard.add(InlineKeyboardButton(feed['feed_name'], callback_data=f"switch_feed_{feed['id']}"))
                await msg.answer("Оберіть добірку, на яку хочете переключитися:", reply_markup=keyboard)
            else:
                await msg.answer("У вас ще немає створених добірок. Створіть одну за допомогою '✍️ Створити добірку'.")
        else:
            await msg.answer("❌ Не вдалося завантажити ваші добірки.")

@dp.callback_query_handler(lambda c: c.data.startswith("switch_feed_"))
async def process_switch_feed(callback_query: types.CallbackQuery):
    """
    Обробляє вибір добірки та переключає на неї користувача.
    """
    await bot.answer_callback_query(callback_query.id)
    feed_id = int(callback_query.data.replace("switch_feed_", ""))
    user_id = callback_query.from_user.id

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/custom_feeds/switch", json={
            "user_id": user_id,
            "feed_id": feed_id
        })
        if resp.status == 200:
            await callback_query.message.answer(f"✅ Ви успішно переключилися на добірку ID: {feed_id}.")
        else:
            await callback_query.message.answer("❌ Не вдалося переключити добірку. Спробуйте пізніше.")
    await callback_query.message.delete_reply_markup() # Видаляємо інлайн-клавіатуру після вибору

# === Преміум Підписка ===
@dp.message_handler(lambda m: m.text == "💰 Преміум підписка")
async def premium_subscription_start(msg: types.Message):
    """
    Виводить інформацію про преміум підписку та пропонує її оформити.
    """
    await msg.answer("🚀 Оформіть преміум підписку, щоб отримати доступ до ексклюзивних функцій, таких як:\n"
                     "- Переклад усіх мов\n- Пошук в архіві новин\n- Більше фільтрів\n- Збереження новин на довгий термін\n\n"
                     f"Вартість: $9.99/місяць (моковано). Оформити підписку? {MONOBANK_CARD_NUMBER}", # Виводимо номер картки
                     reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("✅ Підписатись", callback_data="buy_premium")))

@dp.callback_query_handler(lambda c: c.data == "buy_premium")
async def confirm_premium_purchase(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Підтверджує покупку преміум підписки (моковано).
    """
    await bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": user_id, "is_premium": True})
        if resp.status == 200:
            await callback_query.message.answer("🎉 Вітаємо! Ваша преміум підписка активована на 30 днів!")
        else:
            await callback_query.message.answer("❌ Не вдалося оформити підписку. Спробуйте пізніше.")
    await callback_query.message.delete_reply_markup()

# === Email-розсилка ===
@dp.message_handler(lambda m: m.text == "💌 Email-розсилка")
async def email_subscription_start(msg: types.Message):
    """
    Початок процесу підписки на email-розсилку.
    """
    await msg.answer("Введіть вашу адресу електронної пошти для щоденної розсилки новин:")
    await EmailSubscriptionStates.waiting_for_email.set()

@dp.message_handler(state=EmailSubscriptionStates.waiting_for_email)
async def process_email_for_subscription(msg: types.Message, state: FSMContext):
    """
    Обробляє введену адресу електронної пошти.
    """
    user_email = msg.text
    if "@" not in user_email or "." not in user_email:
        await msg.answer("Будь ласка, введіть дійсну адресу електронної пошти.")
        return

    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/users/register", json={"user_id": msg.from_user.id, "email": user_email})
        if resp.status == 200:
            await msg.answer("Вашу електронну пошту збережено. Оберіть частоту розсилки:", reply_markup=digest_frequency_keyboard)
        else:
            await msg.answer("❌ Не вдалося зберегти вашу електронну пошту.")
    await state.finish() # Завершуємо цей стан, подальша взаємодія обробляється колбеком digest_freq_


@dp.message_handler(lambda m: m.text == "🔔 Авто-сповіщення")
async def toggle_auto_notifications(msg: types.Message):
    """
    Перемикає автоматичні сповіщення про нові новини.
    """
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
                await msg.answer(f"✅ Автоматичні сповіщення про нові новини {status_text}.")
            else:
                await msg.answer("❌ Не вдалося змінити налаштування авто-сповіщень.")
        else:
            await msg.answer("❌ Не вдалося завантажити профіль користувача.")


@dp.message_handler(commands=["invite"])
async def invite_friend(msg: types.Message):
    """
    Генерує посилання-запрошення для реферальної системи.
    """
    user_id = msg.from_user.id
    async with aiohttp.ClientSession() as session:
        resp = await session.post(f"{API_URL}/invite/generate", json={"inviter_user_id": user_id})
        if resp.status == 200:
            result = await resp.json()
            invite_code = result['invite_code']
            # bot.get_me().await.username отримує ім'я користувача бота
            await msg.answer(f"Запросіть друга, надіславши йому це посилання: `https://t.me/{ (await bot.get_me()).username }?start={invite_code}`\n\n"
                             "Коли ваш друг приєднається за цим посиланням, ви отримаєте бонус!", parse_mode="Markdown")
        else:
            await msg.answer("❌ Не вдалося згенерувати запрошення.")


@dp.message_handler(lambda m: m.text == "⬅️ Головне меню")
async def back_to_main_menu(msg: types.Message):
    """
    Повертає користувача до головного меню.
    """
    await msg.answer("Повертаємося до головного меню.", reply_markup=main_keyboard)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
