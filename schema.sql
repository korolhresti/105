-- schema.sql — Розширена SQL-схема Telegram AI News бота

-- Користувачі
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    language TEXT,
    country TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    safe_mode BOOLEAN DEFAULT FALSE,
    current_feed_id INT REFERENCES custom_feeds(id), -- Посилання на активну персональну добірку
    is_premium BOOLEAN DEFAULT FALSE,
    premium_expires_at TIMESTAMP,
    level INT DEFAULT 1, -- Рівень для гейміфікації
    badges TEXT[] DEFAULT ARRAY[]::TEXT[], -- Бейджі для гейміфікації
    inviter_id INT REFERENCES users(id), -- Для реферальної системи (внутрішній ID запросившого)
    email TEXT UNIQUE, -- Для email-розсилок
    auto_notifications BOOLEAN DEFAULT FALSE, -- Автоматичні сповіщення про нові новини
    view_mode TEXT DEFAULT 'manual' -- 'manual' (myfeed) або 'auto' (digest/notifications)
);

-- Фільтри
CREATE TABLE IF NOT EXISTS filters (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    tag TEXT,
    category TEXT,
    source TEXT,
    language TEXT,
    country TEXT,
    content_type TEXT, -- Тип контенту (text, video, image)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Новини
CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT,
    lang TEXT,
    country TEXT,
    tags TEXT[], -- Теги, в т.ч. з AI-класифікації
    ai_classified_topics TEXT[] DEFAULT ARRAY[]::TEXT[], -- Додаткові теми, визначені AI
    source TEXT, -- Назва джерела
    link TEXT, -- Посилання на оригінальну новину
    published_at TIMESTAMP,
    expires_at TIMESTAMP, -- Автоматичне видалення/архівування після 5 годин
    file_id TEXT, -- Для зберігання Telegram file_id (для фото/відео)
    media_type TEXT, -- Тип медіа (photo, video, document)
    source_type TEXT, -- Тип джерела (manual, rss, telegram, twitter тощо)
    tone TEXT, -- Для AI-аналізу тону (напр., 'нейтральна', 'тривожна', 'оптимістична')
    sentiment_score REAL, -- Оцінка тональності (-1.0 до 1.0)
    citation_score INT DEFAULT 0, -- Для аналізу цитованості
    is_duplicate BOOLEAN DEFAULT FALSE, -- Для дедуплікації
    is_fake BOOLEAN DEFAULT FALSE, -- Результат фактчекінгу/модерації
    moderation_status TEXT DEFAULT 'pending' -- pending, approved, rejected, flagged
);

-- Джерела
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL, -- Назва джерела
    link TEXT UNIQUE NOT NULL, -- Посилання на джерело (URL, Telegram ID)
    type TEXT, -- Тип (Telegram, RSS, Twitter, Website)
    added_by_user_id INT REFERENCES users(id),
    verified BOOLEAN DEFAULT FALSE, -- Для верифікації джерел
    reliability_score INT DEFAULT 0, -- Рейтинг надійності джерела
    status TEXT DEFAULT 'active', -- active, blocked, new, archived
    last_parsed_at TIMESTAMP -- Час останнього парсингу/оновлення
);

-- Взаємодії (базова таблиця для всіх дій користувача)
CREATE TABLE IF NOT EXISTS interactions (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    news_id INT REFERENCES news(id),
    action TEXT, -- view, like, save, share, skip, read_full, feedback, comment, rate
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Скарги
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    news_id INT REFERENCES news(id),
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Відгуки
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Аналітика користувачів (сумарна)
CREATE TABLE IF NOT EXISTS user_stats (
    id SERIAL PRIMARY KEY,
    user_id INT UNIQUE REFERENCES users(id),
    viewed INT DEFAULT 0,
    saved INT DEFAULT 0,
    reported INT DEFAULT 0,
    last_active TIMESTAMP,
    read_full_count INT DEFAULT 0,
    skipped_count INT DEFAULT 0,
    liked_count INT DEFAULT 0,
    disliked_count INT DEFAULT 0,
    comments_count INT DEFAULT 0,
    sources_added_count INT DEFAULT 0
);

-- Щоденна розсилка / Підписки на дайджести
CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INT UNIQUE REFERENCES users(id), -- Один користувач - одна підписка
    active BOOLEAN DEFAULT TRUE,
    frequency TEXT DEFAULT 'daily', -- daily, hourly, weekly, instant
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Кеш резюме (AI summary)
CREATE TABLE IF NOT EXISTS summaries (
    id SERIAL PRIMARY KEY,
    news_id INT REFERENCES news(id) UNIQUE,
    summary TEXT,
    translated TEXT, -- Зберігання перекладеного резюме
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Кеш перекладів
CREATE TABLE IF NOT EXISTS translations_cache (
    id SERIAL PRIMARY KEY,
    original_text TEXT NOT NULL,
    original_lang TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    translated_lang TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (original_text, original_lang, translated_lang)
);

-- Топи, рейтинг, оцінки (1-5 зірок)
CREATE TABLE IF NOT EXISTS ratings (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    news_id INT REFERENCES news(id),
    value INT CHECK (value BETWEEN 1 AND 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, news_id) -- Користувач може оцінити новину лише раз
);

-- Заблоковані теми/джерела/мови (мут-листи)
CREATE TABLE IF NOT EXISTS blocks (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    block_type TEXT, -- tag, source, language, category
    value TEXT, -- Значення для блокування
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, block_type, value)
);

-- Журнал подій (логування загальне)
CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    user_id INT, -- Може бути NULL для системних логів
    action TEXT,
    data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Збережені новини (Закладки)
CREATE TABLE IF NOT EXISTS bookmarks (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    news_id INT REFERENCES news(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, news_id)
);

-- Реакції на новини (emoji)
CREATE TABLE IF NOT EXISTS reactions (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    news_id INT REFERENCES news(id),
    reaction_type TEXT NOT NULL, -- наприклад, '❤️', '😮', '🤔', '😢', '😡'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, news_id) -- Користувач може мати лише одну реакцію на новину
);

-- Результати опитувань/голосувань під новинами
CREATE TABLE IF NOT EXISTS poll_results (
    id SERIAL PRIMARY KEY,
    news_id INT REFERENCES news(id),
    user_id INT REFERENCES users(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (news_id, user_id, question) -- Щоб користувач не голосував двічі в одному опитуванні
);

-- Архів новин (для старих новин замість повного видалення)
CREATE TABLE IF NOT EXISTS archived_news (
    id SERIAL PRIMARY KEY,
    original_news_id INT UNIQUE, -- Посилання на оригінальну новину, якщо вона була в news
    title TEXT,
    content TEXT,
    lang TEXT,
    country TEXT,
    tags TEXT[],
    source TEXT,
    link TEXT,
    published_at TIMESTAMP,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Персональні добірки (користувач може створювати свої фільтри)
CREATE TABLE IF NOT EXISTS custom_feeds (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    feed_name TEXT NOT NULL,
    filters JSONB, -- JSONB для зберігання об'єкта фільтрів (tags, sources, etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, feed_name) -- Користувач не може мати дві добірки з однаковою назвою
);

-- Для відстеження переглядів користувачем (для статистики та myfeed)
CREATE TABLE IF NOT EXISTS user_news_views (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    news_id INT REFERENCES news(id),
    viewed BOOLEAN DEFAULT FALSE, -- Чи була новина показана/побачена
    read_full BOOLEAN DEFAULT FALSE, -- Чи була новина прочитана повністю
    first_viewed_at TIMESTAMP,
    last_viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_spent_seconds INT DEFAULT 0, -- Час, проведений за читанням
    UNIQUE (user_id, news_id)
);

-- Для авто-блокування спамних джерел
CREATE TABLE IF NOT EXISTS blocked_sources (
    id SERIAL PRIMARY KEY,
    source_id INT REFERENCES sources(id) UNIQUE NOT NULL,
    reason TEXT,
    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Коментарі до новин
CREATE TABLE IF NOT EXISTS comments (
    id SERIAL PRIMARY KEY,
    news_id INT REFERENCES news(id),
    user_id INT REFERENCES users(id),
    parent_comment_id INT REFERENCES comments(id), -- Для ієрархії коментарів
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    moderated_at TIMESTAMP,
    moderation_status TEXT DEFAULT 'pending' -- pending, approved, rejected, flagged
);

-- Запрошення / Реферальна система
CREATE TABLE IF NOT EXISTS invites (
    id SERIAL PRIMARY KEY,
    inviter_user_id INT REFERENCES users(id),
    invited_user_id INT UNIQUE REFERENCES users(id), -- ID користувача, який прийняв запрошення
    invite_code TEXT UNIQUE, -- Унікальний код запрошення
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accepted_at TIMESTAMP
);

-- Адмін-дії (для логування дій адміністраторів)
CREATE TABLE IF NOT EXISTS admin_actions (
    id SERIAL PRIMARY KEY,
    admin_user_id INT, -- Telegram ID адміністратора, не обов'язково REFERENCES users(id), якщо адміни не в users
    action_type TEXT NOT NULL, -- e.g., 'block_source', 'approve_news', 'delete_comment'
    target_id INT, -- ID об'єкта, на який дія спрямована
    details JSONB, -- Додаткові деталі дії
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Статистика джерел
CREATE TABLE IF NOT EXISTS source_stats (
    id SERIAL PRIMARY KEY,
    source_id INT REFERENCES sources(id) UNIQUE,
    publication_count INT DEFAULT 0,
    avg_rating REAL DEFAULT 0.0,
    report_count INT DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Додано індекс для прискорення пошуку новин за публікацією та статусом
CREATE INDEX IF NOT EXISTS idx_news_published_expires_moderation ON news (published_at DESC, expires_at, moderation_status);

-- Додано індекс для прискорення пошуку по фільтрах
CREATE INDEX IF NOT EXISTS idx_filters_user_id ON filters (user_id);
CREATE INDEX IF NOT EXISTS idx_blocks_user_type_value ON blocks (user_id, block_type, value);

-- Додано індекс для прискорення пошуку закладок
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks (user_id);

-- Додано індекс для user_stats
CREATE INDEX IF NOT EXISTS idx_user_stats_user_id ON user_stats (user_id);

-- Додано індекс для коментарів
CREATE INDEX IF NOT EXISTS idx_comments_news_id ON comments (news_id);

-- Додано індекс для переглядів новин
CREATE INDEX IF NOT EXISTS idx_user_news_views_user_news ON user_news_views (user_id, news_id);

-- Додано індекс для прискорення пошуку по telegram_id в таблиці users
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users (telegram_id);
