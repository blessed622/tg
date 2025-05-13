import os
import sys
import io
import logging
import asyncio
import json
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile, ParseMode
from telethon import TelegramClient
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError, FloodWaitError, SlowModeWaitError
from telethon.errors.rpcerrorlist import AuthKeyUnregisteredError, SessionPasswordNeededError

# Настройка кодировки для решения проблемы с русским текстом
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tg_poster_bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TGPosterBot')

# Конфигурация
API_ID = 23917116
API_HASH = '1065faddf3dc4efceaf29ae7ca9b76f4'
PHONE_NUMBER = '+79155653418'
BOT_TOKEN = "7771036742:AAExM-ibsAhwee-lXe_bToJlZtLIwN1rBUE"

# Пути к файлам
CONFIG_FILE = "poster_config.json"
PHOTOS_DIR = "photos"
LOGS_DIR = "logs"
SESSION_PATH = "poster_session"
FLOOD_WAIT_MAX = 120  # Максимальное время ожидания при FloodWait (в секундах)
MAX_RETRIES = 3  # Максимальное количество попыток отправки сообщения

# Создаем директории, если они не существуют
os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)


# Определение состояний FSM
class PosterStates(StatesGroup):
    main_menu = State()
    adding_group = State()
    batch_add_groups = State()  # Новое состояние для массового добавления групп
    waiting_for_group_link = State()
    selecting_topic = State()
    entering_message = State()
    uploading_photo = State()
    setting_interval = State()
    setting_random_delay = State()  # Новое состояние для случайной задержки
    confirm_add = State()
    delete_confirmation = State()
    phone_verification = State()  # Для проверки номера телефона
    code_verification = State()  # Для проверки кода
    password_verification = State()  # Для проверки двухфакторной аутентификации


# Глобальные переменные
active_tasks = {}
telethon_client = None
task_queue = asyncio.Queue()
send_semaphore = asyncio.Semaphore(5)  # Ограничиваем количество одновременных отправок
auth_lock = asyncio.Lock()  # Блокировка для авторизации


# Функции для работы с конфигурацией
def load_config() -> Dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {e}")
    return {"tasks": {}, "user_id": None, "notifications_enabled": True, "max_retries": MAX_RETRIES}


def save_config(config: Dict) -> None:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка при сохранении конфигурации: {e}")


# Генерация уникального ID для задачи
def generate_task_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


# Улучшенная функция создания и проверки клиента Telethon
async def create_telethon_client(state: Optional[FSMContext] = None) -> TelegramClient:
    global telethon_client

    async with auth_lock:  # Используем блокировку, чтобы только один процесс занимался подключением
        if telethon_client is None:
            logger.info("Создание нового клиента Telethon")
            telethon_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

        if not telethon_client.is_connected():
            try:
                logger.info("Подключение клиента Telethon...")
                await telethon_client.connect()
            except Exception as e:
                logger.error(f"Ошибка при подключении клиента Telethon: {e}")
                # Перезаписываем сессионный файл, если возникли проблемы
                if os.path.exists(f"{SESSION_PATH}.session"):
                    try:
                        os.remove(f"{SESSION_PATH}.session")
                        logger.info("Удален поврежденный файл сессии")
                    except:
                        pass
                telethon_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
                await telethon_client.connect()

        # Проверяем, авторизован ли клиент
        if not await telethon_client.is_user_authorized():
            logger.warning("Требуется авторизация Telethon")
            if state:
                config = load_config()
                owner_id = config.get('user_id')

                # Оповещаем пользователя о необходимости авторизации
                bot = Bot.get_current()
                await bot.send_message(
                    owner_id,
                    "⚠️ Требуется авторизация в Telegram. Отправьте /auth для начала процесса."
                )
            return None

        logger.info("Клиент Telethon подключен и авторизован")
        return telethon_client


# Новая функция для обновления информации о последней активности
def update_task_activity(task_id: str):
    config = load_config()
    if 'tasks' in config and task_id in config['tasks']:
        config['tasks'][task_id]['last_activity'] = datetime.now().isoformat()
        save_config(config)


# Функция для поиска топиков в группе
async def find_topics(group_username: str) -> Tuple[List[Dict], str]:
    client = await create_telethon_client()
    if client is None:
        return [], "Требуется авторизация в Telegram. Отправьте /auth"

    topics_info = []
    error_message = ""

    try:
        entity = await client.get_entity(f"@{group_username}")
        is_forum = hasattr(entity, 'forum') and entity.forum

        if is_forum:
            try:
                topics = await client(GetForumTopicsRequest(
                    channel=entity,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=100
                ))

                for topic in topics.topics:
                    topics_info.append({
                        "id": topic.id,
                        "title": topic.title
                    })

            except Exception as e:
                logger.warning(f"Не удалось получить список топиков напрямую: {str(e)}")
                messages = await client(GetHistoryRequest(
                    peer=entity,
                    limit=300,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))

                found_topics = {}

                for msg in messages.messages:
                    topic_id = None
                    topic_title = None

                    if hasattr(msg, 'reply_to') and hasattr(msg.reply_to, 'forum_topic') and msg.reply_to.forum_topic:
                        topic_id = msg.reply_to.reply_to_top_id

                    elif hasattr(msg, 'action') and hasattr(msg.action, 'title'):
                        topic_id = msg.id
                        topic_title = msg.action.title

                    if topic_id and topic_id not in found_topics:
                        found_topics[topic_id] = True
                        topic_info = {"id": topic_id}

                        if topic_title:
                            topic_info["title"] = topic_title
                        elif hasattr(msg, 'message') and msg.message:
                            topic_info["title"] = (msg.message[:30] + "...") if len(msg.message) > 30 else msg.message
                        else:
                            topic_info["title"] = f"Топик #{topic_id}"

                        topics_info.append(topic_info)
        else:
            error_message = "Эта группа не является форумом или у вас нет прав для просмотра топиков"

    except ChatAdminRequiredError:
        error_message = "Для доступа к топикам требуются права администратора"
    except ChannelPrivateError:
        error_message = "Группа приватная или вас нет в группе"
    except Exception as e:
        error_message = f"Ошибка при поиске топиков: {str(e)}"
        logger.error(f"Error in find_topics: {e}", exc_info=True)

    return topics_info, error_message


# Улучшенная функция отправки сообщения в группу с обработкой ошибок и повторными попытками
async def send_message_to_topic(task_data: Dict) -> bool:
    async with send_semaphore:  # Ограничиваем количество одновременных отправок
        client = await create_telethon_client()
        if client is None:
            logger.error("Клиент Telethon не авторизован")
            return False

        success = False
        retries = 0
        max_retries = load_config().get('max_retries', MAX_RETRIES)

        while retries < max_retries and not success:
            try:
                logger.info(f"Попытка отправки сообщения в @{task_data['group_username']} (попытка {retries + 1})")
                entity = await client.get_entity(f"@{task_data['group_username']}")

                # Добавляем небольшую случайную задержку перед отправкой для имитации человеческого поведения
                await asyncio.sleep(random.uniform(1, 3))

                if task_data.get('photo_path') and os.path.exists(task_data['photo_path']):
                    if task_data.get('topic_id', 0) != 0:
                        await client.send_file(
                            entity,
                            task_data['photo_path'],
                            caption=task_data['message'],
                            reply_to=task_data['topic_id'],
                            parse_mode='html'
                        )
                    else:
                        await client.send_file(
                            entity,
                            task_data['photo_path'],
                            caption=task_data['message'],
                            parse_mode='html'
                        )
                else:
                    if task_data.get('topic_id', 0) != 0:
                        await client.send_message(
                            entity,
                            task_data['message'],
                            reply_to=task_data['topic_id'],
                            parse_mode='html'
                        )
                    else:
                        await client.send_message(
                            entity,
                            task_data['message'],
                            parse_mode='html'
                        )

                task_data['last_posted'] = datetime.now().isoformat()
                success = True
                logger.info(f"Сообщение успешно отправлено в @{task_data['group_username']}")

            except FloodWaitError as e:
                wait_time = min(e.seconds, FLOOD_WAIT_MAX)
                logger.warning(f"FloodWaitError: Превышен лимит отправки. Ожидание {wait_time} секунд")
                await asyncio.sleep(wait_time)
                retries += 1

            except SlowModeWaitError as e:
                wait_time = min(e.seconds, 60)
                logger.warning(f"SlowModeWaitError: Активен медленный режим. Ожидание {wait_time} секунд")
                await asyncio.sleep(wait_time)
                retries += 1

            except AuthKeyUnregisteredError:
                logger.error("Ошибка авторизации: ключ сессии недействителен")
                # Сбрасываем клиент, чтобы он переавторизовался
                global telethon_client
                telethon_client = None
                return False

            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения: {str(e)}", exc_info=True)
                retries += 1
                await asyncio.sleep(5)  # Небольшая пауза перед следующей попыткой

        # Записываем статистику отправки
        if task_data.get('stats') is None:
            task_data['stats'] = {"sent": 0, "failed": 0, "last_error": None}

        if success:
            task_data['stats']['sent'] = task_data['stats'].get('sent', 0) + 1
        else:
            task_data['stats']['failed'] = task_data['stats'].get('failed', 0) + 1
            task_data['stats']['last_error'] = str(datetime.now())

        return success


# Улучшенный обработчик задач из очереди
async def task_worker(bot: Bot):
    while True:
        try:
            task_id, task_data = await task_queue.get()
            try:
                if task_id in active_tasks and active_tasks[task_id]:
                    logger.info(f"Обработка задачи {task_id} для группы @{task_data['group_username']}")

                    # Добавляем случайную задержку, если она настроена
                    base_interval = task_data['interval']
                    random_delay = task_data.get('random_delay', 0)

                    actual_interval = base_interval
                    if random_delay > 0:
                        # Добавляем случайную задержку в пределах ± random_delay секунд
                        random_offset = random.randint(-random_delay, random_delay)
                        actual_interval = max(30, base_interval + random_offset)  # Минимум 30 секунд

                    success = await send_message_to_topic(task_data)

                    config = load_config()
                    owner_id = config.get('user_id')
                    notifications_enabled = config.get('notifications_enabled', True)

                    # Обновляем статистику в конфигурации
                    if task_id in config['tasks']:
                        config['tasks'][task_id]['last_posted'] = task_data['last_posted'] if success else \
                        config['tasks'][task_id].get('last_posted')
                        config['tasks'][task_id]['stats'] = task_data.get('stats', {"sent": 0, "failed": 0})
                        save_config(config)

                    # Уведомляем пользователя, если это настроено
                    if success and owner_id and notifications_enabled:
                        await bot.send_message(
                            owner_id,
                            f"✅ Сообщение успешно отправлено в группу @{task_data['group_username']}, "
                            f"топик '{task_data.get('topic_name', 'Нет топика')}'\n"
                            f"⏱ Следующая отправка через {actual_interval} сек."
                        )
                    elif not success and owner_id and notifications_enabled:
                        await bot.send_message(
                            owner_id,
                            f"❌ Не удалось отправить сообщение в группу @{task_data['group_username']}, "
                            f"топик '{task_data.get('topic_name', 'Нет топика')}'\n"
                            f"⏱ Следующая попытка через {actual_interval} сек."
                        )

                    # Добавляем задачу обратно в очередь с задержкой
                    if task_id in active_tasks and active_tasks[task_id]:
                        await asyncio.sleep(actual_interval)
                        # Проверяем еще раз, активна ли задача
                        if task_id in active_tasks and active_tasks[task_id]:
                            await task_queue.put((task_id, task_data))
                            update_task_activity(task_id)  # Обновляем время активности
            except Exception as e:
                logger.error(f"Ошибка в обработчике задачи {task_id}: {e}", exc_info=True)
                # Даже при ошибке продолжаем выполнение задачи после паузы
                await asyncio.sleep(30)
                if task_id in active_tasks and active_tasks[task_id]:
                    await task_queue.put((task_id, task_data))

            task_queue.task_done()
        except Exception as e:
            logger.critical(f"Критическая ошибка в task_worker: {e}", exc_info=True)
            await asyncio.sleep(60)  # При критической ошибке делаем паузу подольше


# Проверка работоспособности системы
async def health_check(bot: Bot):
    while True:
        try:
            await asyncio.sleep(3600)  # Проверка каждый час

            # Проверяем подключение Telethon
            if telethon_client is None or not telethon_client.is_connected():
                logger.warning("Health check: Telethon не подключен, переподключаемся...")
                await create_telethon_client()

            # Проверяем активные задачи
            current_time = datetime.now()
            config = load_config()

            for task_id, task_data in config.get('tasks', {}).items():
                if task_id in active_tasks and active_tasks[task_id]:
                    last_activity = task_data.get('last_activity')

                    if last_activity:
                        last_activity_time = datetime.fromisoformat(last_activity)
                        elapsed = (current_time - last_activity_time).total_seconds()

                        # Если прошло больше 3 интервалов, а задача должна быть активна
                        if elapsed > task_data['interval'] * 3:
                            logger.warning(f"Health check: Задача {task_id} неактивна слишком долго, перезапускаем")
                            # Перезапускаем задачу
                            await task_queue.put((task_id, config['tasks'][task_id]))
                            update_task_activity(task_id)

            logger.info("Health check завершен")

        except Exception as e:
            logger.error(f"Ошибка в health_check: {e}", exc_info=True)


# Создание клавиатуры главного меню
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task"),
        InlineKeyboardButton("📋 Мои задачи", callback_data="list_tasks")
    )
    keyboard.add(
        InlineKeyboardButton("➕➕ Массовое добавление", callback_data="batch_add_tasks"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
    )
    keyboard.add(
        InlineKeyboardButton("▶️ Включить все", callback_data="start_all_tasks"),
        InlineKeyboardButton("⏹ Отключить все", callback_data="stop_all_tasks")
    )
    keyboard.add(
        InlineKeyboardButton("📊 Статус задач", callback_data="task_status"),
        InlineKeyboardButton("🔔 Уведомления", callback_data="toggle_notifications")
    )
    keyboard.add(
        InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
    )
    return keyboard


# Функция для переключения статуса уведомлений
def toggle_notifications_status(config: Dict) -> Dict:
    if 'notifications_enabled' not in config:
        config['notifications_enabled'] = False
    else:
        config['notifications_enabled'] = not config['notifications_enabled']
    save_config(config)
    return config


# Создание клавиатуры настроек
def get_settings_keyboard() -> InlineKeyboardMarkup:
    config = load_config()
    notifications_status = "✅ Включены" if config.get('notifications_enabled', True) else "❌ Отключены"
    max_retries = config.get('max_retries', MAX_RETRIES)

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(f"🔔 Уведомления: {notifications_status}", callback_data="toggle_notifications"),
        InlineKeyboardButton(f"🔄 Макс. количество попыток: {max_retries}", callback_data="change_max_retries"),
        InlineKeyboardButton("🔄 Проверить авторизацию", callback_data="check_auth"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
    )
    return keyboard


# Создание клавиатуры для выбора топика
def get_topics_keyboard(topics: List[Dict]) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    for topic in topics:
        keyboard.add(InlineKeyboardButton(
            f"#{topic['id']} - {topic['title']}",
            callback_data=f"topic_{topic['id']}_{topic['title']}"
        ))
    keyboard.add(
        InlineKeyboardButton("📝 Использовать без топика", callback_data="no_topic"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
    )
    return keyboard


# Создание клавиатуры для списка задач
def get_tasks_keyboard(tasks: Dict[str, Dict]) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    for task_id, task_data in tasks.items():
        status = "✅ Активна" if task_id in active_tasks and active_tasks[task_id] else "❌ Остановлена"
        keyboard.add(InlineKeyboardButton(
            f"{status} - @{task_data['group_username']} - {task_data['topic_name']}",
            callback_data=f"task_info_{task_id}"
        ))
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    return keyboard


# Создание клавиатуры для управления задачей
def get_task_control_keyboard(task_id: str) -> InlineKeyboardMarkup:
    is_active = task_id in active_tasks and active_tasks[task_id]
    keyboard = InlineKeyboardMarkup(row_width=2)

    if is_active:
        keyboard.add(InlineKeyboardButton("⏹ Остановить", callback_data=f"stop_task_{task_id}"))
    else:
        keyboard.add(InlineKeyboardButton("▶️ Запустить", callback_data=f"start_task_{task_id}"))

    keyboard.add(
        InlineKeyboardButton("🗑 Удалить задачу", callback_data=f"delete_task_{task_id}"),
        InlineKeyboardButton("🔙 К списку задач", callback_data="list_tasks")
    )
    keyboard.add(
        InlineKeyboardButton("🔄 Отправить сейчас", callback_data=f"send_now_{task_id}"),
        InlineKeyboardButton("📊 Статистика", callback_data=f"task_stats_{task_id}")
    )
    return keyboard


# Запускаем бота
async def main():
    global telethon_client

    # Загружаем конфигурацию при запуске
    config = load_config()

    # Создаем бота и диспетчер
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)

    # Запускаем обработчик задач и проверку здоровья системы
    asyncio.create_task(task_worker(bot))
    asyncio.create_task(health_check(bot))

    # Обработчик команды /start
    @dp.message_handler(commands=['start'], state='*')
    async def cmd_start(message: types.Message, state: FSMContext):
        config = load_config()
        if not config.get('user_id'):
            config['user_id'] = message.from_user.id
            save_config(config)

        if message.from_user.id != config.get('user_id'):
            await message.answer("Извините, этот бот приватный и работает только для владельца.")
            return

        await state.finish()
        await PosterStates.main_menu.set()

        await message.answer(
            "👋 Добро пожаловать в улучшенный Telegram Poster Bot!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик команды /help
    @dp.message_handler(commands=['help'], state='*')
    async def cmd_help(message: types.Message):
        config = load_config()
        if message.from_user.id != config.get('user_id'):
            await message.answer("Извините, этот бот приватный и работает только для владельца.")
            return

        await message.answer(
            "📚 <b>Справка по использованию Telegram Poster Bot</b>\n\n"
            "<b>Основные команды:</b>\n"
            "/start - Запустить бота и перейти в главное меню\n"
            "/help - Показать эту справку\n"
            "/cancel - Отменить текущее действие и вернуться в главное меню\n"
            "/auth - Авторизация клиента Telethon\n"
            "/status - Проверка статуса всех систем\n\n"
            "<b>Как использовать бота:</b>\n"
            "1. Нажмите '➕ Добавить задачу'\n"
            "2. Укажите имя группы (без @, например: 'gifts_buy')\n"
            "3. Выберите топик из списка доступных\n"
            "4. Введите текст сообщения (поддерживается HTML)\n"
            "5. Отправьте фото или пропустите этот шаг\n"
            "6. Укажите интервал отправки в секундах\n"
            "7. Укажите случайную задержку (для естественности)\n"
            "8. Подтвердите создание задачи\n\n"
            "<b>Массовое добавление групп:</b>\n"
            "Используйте функцию массового добавления в главном меню для быстрого создания нескольких задач.\n\n"
            "<b>Важно:</b>\n"
            "• У вас должны бы