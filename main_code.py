# main.py - основной файл запуска приложения

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, OWNER_ID
from bot.dispatcher import setup_dispatcher
from database.db import Database
from scheduler.job_manager import JobManager
from utils.logger import setup_logger


async def main():
    # Настройка логирования
    setup_logger()
    logger = logging.getLogger(__name__)
    logger.info("Запуск бота...")

    # Инициализация базы данных
    db = Database()
    await db.init()
    logger.info("База данных инициализирована")

    # Инициализация планировщика задач
    scheduler = AsyncIOScheduler()
    job_manager = JobManager(db, scheduler)
    await job_manager.load_tasks()
    scheduler.start()
    logger.info("Планировщик задач запущен")

    # Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Настройка диспетчера с обработчиками
    setup_dispatcher(dp, db, job_manager, bot)
    
    # Удаляем все обновления, которые могли накопиться
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Отправляем сообщение владельцу о запуске бота
    try:
        await bot.send_message(OWNER_ID, "🤖 Бот успешно запущен и готов к работе!")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение владельцу: {e}")
    
    # Запуск бота
    logger.info(f"Бот @{(await bot.get_me()).username} запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


# config.py - основные настройки и конфигурация приложения

import os
from datetime import datetime, timedelta

# Токен бота и ID владельца
BOT_TOKEN = "7753781602:AAHdjaiBwHhrGfo0bKObp9-zWb5Jg6-kIRY"
OWNER_ID = 6103389282

# Настройки базы данных
DB_PATH = os.path.join(os.path.dirname(__file__), "database", "autopost.db")

# Настройки сессий
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Ключ для шифрования чувствительных данных (API hash, номера телефонов)
# В реальном приложении этот ключ должен храниться безопасно
# и не должен быть в коде напрямую
ENCRYPTION_KEY = "your_encryption_key_here"  # Нужно заменить на настоящий ключ

# Настройки подписки
DEFAULT_SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_PRICE = "500 руб."
SUBSCRIPTION_CONTACT = "@lovelymaxing"

# Лимиты по умолчанию
DEFAULT_TASK_LIMIT = 20
DEFAULT_TASKS_PER_DAY = 100

# Для тестирования можно установить короткий срок подписки
DEFAULT_TEST_SUBSCRIPTION = datetime.now() + timedelta(days=3)


# database/db.py - инициализация базы данных

import aiosqlite
import logging
import os
from config import DB_PATH

class Database:
    def __init__(self):
        self.db_path = DB_PATH
        self.logger = logging.getLogger(__name__)
        
        # Убедимся, что директория для базы данных существует
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
    async def init(self):
        """Инициализация базы данных: создание таблиц, если они не существуют"""
        self.logger.info(f"Инициализация базы данных: {self.db_path}")
        
        async with aiosqlite.connect(self.db_path) as db:
            # Пользователи
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,  -- Telegram ID пользователя
                    username TEXT,           -- Username в Telegram
                    first_name TEXT,         -- Имя пользователя
                    last_name TEXT,          -- Фамилия пользователя
                    is_admin INTEGER DEFAULT 0,  -- Флаг администратора (0 - нет, 1 - да)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Дата регистрации
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP   -- Последняя активность
                )
            ''')
            
            # Подписки
            await db.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,          -- ID пользователя
                    start_date TIMESTAMP,     -- Дата начала
                    end_date TIMESTAMP,       -- Дата окончания
                    is_active INTEGER DEFAULT 1,  -- Активна ли подписка (0 - нет, 1 - да)
                    subscription_type TEXT DEFAULT 'standard',  -- Тип подписки
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')
            
            # Сессии пользователей
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,          -- ID пользователя
                    api_id INTEGER,           -- API ID (зашифрованный)
                    api_hash TEXT,            -- API Hash (зашифрованный)
                    phone TEXT,               -- Телефон (зашифрованный)
                    session_file TEXT,        -- Путь к файлу сессии
                    is_active INTEGER DEFAULT 1,  -- Активна ли сессия (0 - нет, 1 - да)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Дата создания
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,   -- Последнее использование
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')
            
            # Задачи
            await db.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,          -- ID пользователя
                    session_id INTEGER,       -- ID сессии
                    task_type TEXT,           -- Тип задачи (new_message/forward)
                    content TEXT,             -- Текст или ID сообщения для пересылки
                    source_chat_id INTEGER,   -- ID исходного чата (для пересылки)
                    target_chat_id INTEGER,   -- ID целевого чата
                    topic_id INTEGER DEFAULT NULL,  -- ID топика (если есть)
                    schedule_type TEXT,       -- Тип расписания (once/periodic)
                    schedule_time TIMESTAMP,  -- Время выполнения
                    cron_expression TEXT,     -- Cron-выражение для периодических задач
                    is_active INTEGER DEFAULT 1,  -- Активна ли задача (0 - нет, 1 - да)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Дата создания
                    last_executed TIMESTAMP,  -- Последнее выполнение
                    execution_count INTEGER DEFAULT 0,  -- Счетчик выполнений
                    status TEXT DEFAULT 'pending',  -- Статус задачи
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
                )
            ''')
            
            # Логи выполнения задач
            await db.execute('''
                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,          -- ID задачи
                    execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Время выполнения
                    status TEXT,              -- Статус выполнения (success/error)
                    message TEXT,             -- Сообщение (ошибка или успех)
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            ''')
            
            await db.commit()
            
        self.logger.info("База данных инициализирована успешно")
        
        # Проверим, существует ли владелец бота в базе данных
        await self.ensure_owner_exists()
            
    async def ensure_owner_exists(self):
        """Проверка наличия владельца в базе данных и его создание, если необходимо"""
        from config import OWNER_ID
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Проверяем, существует ли владелец
            cursor = await db.execute('SELECT * FROM users WHERE id = ?', (OWNER_ID,))
            owner = await cursor.fetchone()
            
            if not owner:
                self.logger.info(f"Создание аккаунта владельца с ID {OWNER_ID}")
                
                # Создаем аккаунт владельца
                await db.execute(
                    'INSERT INTO users (id, is_admin) VALUES (?, 1)',
                    (OWNER_ID,)
                )
                
                # Создаем подписку для владельца (бессрочную)
                from datetime import datetime, timedelta
                start_date = datetime.now()
                end_date = start_date + timedelta(days=3650)  # ~10 лет
                
                await db.execute(
                    'INSERT INTO subscriptions (user_id, start_date, end_date, subscription_type) VALUES (?, ?, ?, ?)',
                    (OWNER_ID, start_date, end_date, 'owner')
                )
                
                await db.commit()
                self.logger.info(f"Аккаунт владельца создан успешно")
            else:
                self.logger.info(f"Аккаунт владельца уже существует")
                
    async def get_user(self, user_id):
        """Получение пользователя по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            return await cursor.fetchone()
            
    async def add_user(self, user_id, username=None, first_name=None, last_name=None, is_admin=0):
        """Добавление нового пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT OR IGNORE INTO users (id, username, first_name, last_name, is_admin) VALUES (?, ?, ?, ?, ?)',
                (user_id, username, first_name, last_name, is_admin)
            )
            await db.commit()
            
    async def update_user_activity(self, user_id):
        """Обновление времени последней активности пользователя"""
        from datetime import datetime
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET last_active = ? WHERE id = ?',
                (datetime.now(), user_id)
            )
            await db.commit()
            
    async def get_subscription(self, user_id):
        """Получение подписки пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM subscriptions WHERE user_id = ? ORDER BY end_date DESC LIMIT 1',
                (user_id,)
            )
            return await cursor.fetchone()
            
    async def add_subscription(self, user_id, start_date, end_date, subscription_type='standard'):
        """Добавление новой подписки для пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO subscriptions (user_id, start_date, end_date, subscription_type) VALUES (?, ?, ?, ?)',
                (user_id, start_date, end_date, subscription_type)
            )
            await db.commit()
            
    async def is_subscription_active(self, user_id):
        """Проверка активности подписки пользователя"""
        from datetime import datetime
        
        subscription = await self.get_subscription(user_id)
        if not subscription:
            return False
            
        return subscription['is_active'] == 1 and datetime.fromisoformat(subscription['end_date']) > datetime.now()
        
    async def get_all_users(self):
        """Получение списка всех пользователей"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM users ORDER BY created_at DESC')
            return await cursor.fetchall()


# bot/dispatcher.py - настройка диспетчера сообщений

from aiogram import Dispatcher, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import default_state

from bot.handlers.start import register_start_handler
from bot.handlers.auth import register_auth_handlers
from bot.handlers.subscription import register_subscription_handlers
from bot.handlers.tasks import register_task_handlers
from bot.handlers.admin import register_admin_handlers
from bot.middlewares import SubscriptionMiddleware, ActivityMiddleware, AdminMiddleware


# bot/middlewares.py - middleware для проверки активности, подписки и прав администратора

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class SubscriptionMiddleware(BaseMiddleware):
    """Middleware для проверки активности подписки пользователя"""
    
    def __init__(self, db):
        self.db = db
        super().__init__()
        
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем ID пользователя
        user_id = event.from_user.id
        
        # Проверяем, является ли пользователь администратором
        user = await self.db.get_user(user_id)
        if user and user['is_admin'] == 1:
            # Администраторы имеют полный доступ
            return await handler(event, data)
        
        # Для обычных пользователей проверяем наличие подписки
        has_subscription = await self.db.is_subscription_active(user_id)
        
        # Добавляем информацию о подписке в data
        data["has_subscription"] = has_subscription
        
        # Команды, доступные без подписки
        allowed_commands = ["/start", "/help"]
        allowed_callbacks = ["auth:start", "menu:main"]
        
        if isinstance(event, Message):
            # Для сообщений проверяем, является ли это одной из разрешенных команд
            if not has_subscription and event.text and event.text not in allowed_commands:
                from config import SUBSCRIPTION_CONTACT, SUBSCRIPTION_PRICE
                await event.answer(
                    f"❌ У вас нет активной подписки!\n\n"
                    f"💰 Стоимость: {SUBSCRIPTION_PRICE} в месяц\n\n"
                    f"📱 Для приобретения подписки напишите: {SUBSCRIPTION_CONTACT}"
                )
                return
        
        elif isinstance(event, CallbackQuery):
            # Для колбэков проверяем, является ли это одним из разрешенных колбэков
            if not has_subscription and not any(event.data.startswith(prefix) for prefix in allowed_callbacks):
                await event.answer("❌ Необходима активная подписка для этого действия", show_alert=True)
                return
        
        return await handler(event, data)


class ActivityMiddleware(BaseMiddleware):
    """Middleware для обновления информации о последней активности пользователя"""
    
    def __init__(self, db):
        self.db = db
        super().__init__()
        
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем ID пользователя
        user_id = event.from_user.id
        
        # Обновляем информацию о последней активности
        await self.db.update_user_activity(user_id)
        
        return await handler(event, data)


class AdminMiddleware(BaseMiddleware):
    """Middleware для проверки прав администратора"""
    
    def __init__(self, db):
        self.db = db
        super().__init__()
        
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем ID пользователя
        user_id = event.from_user.id
        
        # Проверяем, является ли пользователь администратором
        user = await self.db.get_user(user_id)
        is_admin = user and user['is_admin'] == 1
        
        # Добавляем информацию о правах администратора в data
        data["is_admin"] = is_admin
        
        # Для команд администратора проверяем права
        admin_commands = ["/admin"]
        admin_callbacks = ["admin:"]
        
        if isinstance(event, Message) and event.text:
            if any(event.text.startswith(cmd) for cmd in admin_commands) and not is_admin:
                await event.answer("❌ У вас недостаточно прав для использования этой команды")
                return
        
        elif isinstance(event, CallbackQuery):
            if any(event.data.startswith(prefix) for prefix in admin_callbacks) and not is_admin:
                await event.answer("❌ Эта функция доступна только администраторам", show_alert=True)
                return
        
        return await handler(event, data)


def setup_dispatcher(dp: Dispatcher, db, job_manager, bot: Bot):
    """Настройка диспетчера и регистрация всех обработчиков"""
    
    # Регистрация middlewares
    dp.message.middleware(ActivityMiddleware(db))
    dp.callback_query.middleware(ActivityMiddleware(db))
    
    dp.message.middleware(SubscriptionMiddleware(db))
    dp.callback_query.middleware(SubscriptionMiddleware(db))
    
    dp.message.middleware(AdminMiddleware(db))
    dp.callback_query.middleware(AdminMiddleware(db))
    
    # Регистрация обработчиков
    register_start_handler(dp, db, bot)
    register_auth_handlers(dp, db, bot)
    register_subscription_handlers(dp, db, bot)
    register_task_handlers(dp, db, job_manager, bot)
    register_admin_handlers(dp, db, job_manager, bot)
    
    return dp


# bot/handlers/start.py - обработчик команды /start

from aiogram import types, F, Router, Dispatcher, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from bot.keyboards.main_menu import get_main_menu
from datetime import datetime, timedelta


# bot/keyboards/main_menu.py - клавиатуры для основного меню

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu() -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру для главного меню"""
    kb = InlineKeyboardBuilder()
    
    # Основные кнопки
    kb.button(text="📋 Мои задачи", callback_data="tasks:list")
    kb.button(text="➕ Создать задачу", callback_data="tasks:create")
    kb.button(text="👤 Мой профиль", callback_data="profile:view")
    kb.button(text="⚙️ Настройки", callback_data="settings")
    kb.button(text="📊 Статистика", callback_data="stats")
    kb.button(text="🔑 Авторизация", callback_data="auth:start")
    kb.button(text="ℹ️ Помощь", callback_data="help")
    
    # Расположим кнопки в 2 колонки
    kb.adjust(2)
    
    return kb.as_markup()


def get_task_menu(task_id=None) -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру для управления задачами"""
    kb = InlineKeyboardBuilder()
    
    if task_id:
        # Меню для конкретной задачи
        kb.button(text="▶️ Запустить", callback_data=f"tasks:start:{task_id}")
        kb.button(text="⏹ Остановить", callback_data=f"tasks:stop:{task_id}")
        kb.button(text="✏️ Редактировать", callback_data=f"tasks:edit:{task_id}")
        kb.button(text="🗑 Удалить", callback_data=f"tasks:delete:{task_id}")
        kb.button(text="📊 Статистика", callback_data=f"tasks:stats:{task_id}")
        kb.button(text="◀️ Назад", callback_data="tasks:list")
        kb.adjust(2, 2, 2)
    else:
        # Общее меню задач
        kb.button(text="📋 Активные задачи", callback_data="tasks:list:active")
        kb.button(text="📋 Все задачи", callback_data="tasks:list:all")
        kb.button(text="➕ Создать задачу", callback_data="tasks:create")
        kb.button(text="◀️ Назад", callback_data="menu:main")
        kb.adjust(2, 1, 1)
    
    return kb.as_markup()


def get_auth_menu() -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру для авторизации"""
    kb = InlineKeyboardBuilder()
    
    kb.button(text="🔑 Начать авторизацию", callback_data="auth:start")
    kb.button(text="📱 Проверить статус", callback_data="auth:status")
    kb.button(text="🔄 Обновить сессию", callback_data="auth:refresh")
    kb.button(text="◀️ Назад", callback_data="menu:main")
    
    kb.adjust(1)
    
    return kb.as_markup()


async def start_command(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик команды /start"""
    await state.clear()  # Очищаем состояние FSM
    
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Добавляем пользователя в БД, если его там еще нет
    await db.add_user(user_id, username, first_name, last_name)
    
    # Проверяем, есть ли у пользователя активная подписка
    subscription = await db.get_subscription(user_id)
    
    if subscription and await db.is_subscription_active(user_id):
        # У пользователя есть активная подписка
        end_date = datetime.fromisoformat(subscription['end_date'])
        days_left = (end_date - datetime.now()).days
        
        welcome_text = (
            f"👋 Добро пожаловать, {first_name or 'уважаемый пользователь'}!\n\n"
            f"🔓 У вас есть активная подписка до {end_date.strftime('%d.%m.%Y')}.\n"
            f"⏳ Осталось дней: {days_left}\n\n"
            f"Выберите действие в главном меню:"
        )
        
        await message.answer(welcome_text, reply_markup=get_main_menu())
    else:
        # У пользователя нет активной подписки
        from config import SUBSCRIPTION_PRICE, SUBSCRIPTION_CONTACT
        
        no_subscription_text = (
            f"👋 Добро пожаловать, {first_name or 'уважаемый пользователь'}!\n\n"
            f"❌ У вас нет активной подписки для использования сервиса автопостинга.\n\n"
            f"💰 Стоимость подписки: {SUBSCRIPTION_PRICE} в месяц\n\n"
            f"🔐 С нашим сервисом вы сможете:\n"
            f"• Настраивать отправку сообщений по расписанию\n"
            f"• Пересылать сообщения в любые чаты, группы и каналы\n"
            f"• Использовать топики в супергруппах\n"
            f"• Управлять всеми задачами из удобного интерфейса\n\n"
            f"📱 Для приобретения подписки напишите: {SUBSCRIPTION_CONTACT}"
        )
        
        await message.answer(no_subscription_text)


def register_start_handler(dp: Dispatcher, db, bot: Bot):
    """Регистрация обработчика команды /start"""
    dp.message.register(lambda message, state: start_command(message, state, db, bot), CommandStart())