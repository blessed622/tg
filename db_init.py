# database/db_init.py - инициализация базы данных

import aiosqlite
import os
import logging


async def init_db(db_path):
    """
    Инициализация базы данных
    
    Args:
        db_path (str): Путь к файлу базы данных
        
    Returns:
        aiosqlite.Connection: Объект соединения с базой данных
    """
    # Проверяем, существует ли база данных
    is_new_db = not os.path.exists(db_path)
    
    # Создаем соединение с базой данных
    db = aiosqlite.connect(db_path)
    
    # Для получения строк в виде словарей
    db.row_factory = aiosqlite.Row
    
    if is_new_db:
        logging.info(f"Создаем новую базу данных: {db_path}")
        async with db.connect() as conn:
            # Создаем таблицу пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    is_bot BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timezone TEXT DEFAULT 'Europe/Moscow',
                    notification_enabled BOOLEAN DEFAULT 1
                )
            ''')
            
            # Создаем таблицу сессий
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    api_id INTEGER,
                    api_hash TEXT,
                    phone TEXT,
                    session_file TEXT,
                    is_active BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE
                )
            ''')
            
            # Создаем таблицу подписок
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    subscription_type TEXT DEFAULT 'standard',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE
                )
            ''')
            
            # Создаем таблицу задач
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    title TEXT,
                    description TEXT,
                    chat_id TEXT,
                    message_text TEXT,
                    interval INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    execution_count INTEGER DEFAULT 0,
                    last_execution TIMESTAMP,
                    has_media BOOLEAN DEFAULT 0,
                    media_type TEXT,
                    media_path TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE
                )
            ''')
            
            # Создаем таблицу логов задач
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY,
                    task_id INTEGER,
                    execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT,
                    message TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            ''')
            
            # Создаем индексы для оптимизации
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions (user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks (user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_task_logs_task_id ON task_logs (task_id)')
            
            await conn.commit()
            logging.info("База данных успешно инициализирована")
    else:
        logging.info(f"Подключение к существующей базе данных: {db_path}")
    
    return db
