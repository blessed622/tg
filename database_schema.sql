-- Схема базы данных для бота автопостинга

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    joined_date TEXT,
    settings TEXT  -- JSON с настройками пользователя
);

-- Таблица сессий авторизации пользователей
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    api_id INTEGER NOT NULL,
    api_hash TEXT NOT NULL,  -- зашифровано
    phone TEXT NOT NULL,  -- зашифровано
    session_file TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Таблица подписок пользователей
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    subscription_type TEXT DEFAULT 'standard',  -- standard, premium, business
    payment_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Таблица задач автопостинга
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    target_chat TEXT NOT NULL,  -- ID или username целевого чата
    message_text TEXT,
    media_type TEXT,  -- photo, video, document, audio, NULL если нет медиа
    media_file_id TEXT,  -- ID медиафайла в Telegram или путь к файлу
    schedule_type TEXT NOT NULL,  -- interval, time
    interval_seconds INTEGER,  -- для interval
    execution_time TEXT,  -- для time
    is_recurring INTEGER DEFAULT 0,  -- 0 - одноразовая, 1 - повторяющаяся
    is_active INTEGER DEFAULT 1,
    execution_count INTEGER DEFAULT 0,  -- счетчик выполнений
    last_execution TEXT,  -- время последнего выполнения
    next_execution TEXT,  -- время следующего выполнения
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Таблица истории выполнения задач
CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    execution_time TEXT NOT NULL,
    status TEXT NOT NULL,  -- success, error
    error_message TEXT,
    message_id INTEGER,  -- ID отправленного сообщения
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Таблица статистики
CREATE TABLE IF NOT EXISTS statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    tasks_created INTEGER DEFAULT 0,
    tasks_executed INTEGER DEFAULT 0,
    messages_sent INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Индексы для оптимизации
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(is_active);
CREATE INDEX IF NOT EXISTS idx_tasks_next_execution ON tasks(next_execution);
CREATE INDEX IF NOT EXISTS idx_task_history_task_id ON task_history(task_id);
CREATE INDEX IF NOT EXISTS idx_statistics_user_date ON statistics(user_id, date);
