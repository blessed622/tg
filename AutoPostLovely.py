import os
import sys
import io
import logging
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile, ParseMode
from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError
from telethon.sessions import StringSession

MAX_CLIENTS = 5  # Количество клиентов в пуле
telethon_clients = {}  # Словарь для хранения клиентов
client_semaphore = asyncio.Semaphore(MAX_CLIENTS)  # Ограничивает одновременные подключения

# Настройка кодировки для решения проблемы с русским текстом
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tg_poster_bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Конфигурация
API_ID = 23917116
API_HASH = '1065faddf3dc4efceaf29ae7ca9b76f4'
PHONE_NUMBER = '+79155653418'

# Телеграм-бот токен (получите у @BotFather)
BOT_TOKEN = "7771036742:AAExM-ibsAhwee-lXe_bToJlZtLIwN1rBUE"  # ⚠️ Замените на свой токен

# Пути к файлам
CONFIG_FILE = "poster_config.json"
PHOTOS_DIR = "photos"

# Создаем директорию для фото, если она не существует
os.makedirs(PHOTOS_DIR, exist_ok=True)


# Определение состояний FSM
class PosterStates(StatesGroup):
    main_menu = State()
    adding_group = State()
    waiting_for_group_link = State()
    selecting_topic = State()
    entering_message = State()
    uploading_photo = State()
    setting_interval = State()
    confirm_add = State()
    select_task_to_edit = State()
    delete_confirmation = State()
    start_task = State()
    stop_task = State()


# Структура конфигурации
"""
{
    "tasks": {
        "task_id": {
            "group_username": "group_name",
            "topic_id": 123,
            "topic_name": "Topic Name",
            "message": "Message text",
            "photo_path": "photos/filename.jpg",
            "interval": 300,
            "active": false,
        }
    },
    "user_id": 123456789  # ID владельца бота
}
"""

# Глобальная переменная для хранения активных задач
active_tasks = {}


def load_config() -> Dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка при загрузке конфигурации: {e}")
    return {"tasks": {}, "user_id": None}


# Семафор для управления очередью задач
task_semaphore = asyncio.Semaphore(5)  # Только 1 задача может выполняться одновременно


def save_config(config: Dict) -> None:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка при сохранении конфигурации: {e}")


# Генерация уникального ID для задачи
def generate_task_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}"


# Добавьте в начало файла (после импортов)
telethon_client = None


async def get_telethon_client(task_id: str) -> TelegramClient:
    """Получает или создает клиент Telethon для задачи"""
    global telethon_clients

    client_num = hash(task_id) % MAX_CLIENTS
    client_key = f"client_{client_num}"

    if client_key not in telethon_clients or not telethon_clients[client_key].is_connected():
        async with client_semaphore:
            telethon_clients[client_key] = TelegramClient(
                StringSession(),  # Используем StringSession для лучшей совместимости
                API_ID,
                API_HASH
            )
            try:
                await telethon_clients[client_key].start(phone=PHONE_NUMBER)
                logging.info(f"Создан клиент Telethon #{client_num}")
            except Exception as e:
                logging.error(f"Ошибка инициализации клиента #{client_num}: {e}")
                raise

    return telethon_clients[client_key]


async def close_all_telethon_clients():
    """Закрывает все клиенты Telethon"""
    global telethon_clients
    for client in telethon_clients.values():
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception as e:
            logging.error(f"Ошибка при закрытии клиента: {e}")
    telethon_clients = {}


# Функция для поиска топиков в группе
async def find_topics(group_username: str, task_id: str) -> Tuple[List[Dict], str]:
    """Поиск топиков с использованием выделенного клиента"""
    client = await get_telethon_client(task_id)
    try:
        entity = await client.get_entity(group_username)

        # Проверяем, является ли чат форумом
        if hasattr(entity, 'forum') and entity.forum:
            try:
                topics = await client(GetForumTopicsRequest(
                    channel=entity,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=100
                ))
                return [
                    {"id": topic.id, "title": topic.title}
                    for topic in topics.topics
                ], ""
            except Exception as e:
                logging.warning(f"Альтернативный метод поиска топиков: {e}")
                messages = await client(GetHistoryRequest(
                    peer=entity,
                    limit=100,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))

                topics = []
                for msg in messages.messages:
                    if hasattr(msg, 'reply_to') and hasattr(msg.reply_to, 'forum_topic'):
                        topics.append({
                            "id": msg.reply_to.reply_to_top_id,
                            "title": getattr(msg, 'message', f"Топик {msg.reply_to.reply_to_top_id}")[:50]
                        })
                return topics, ""
        return [{"id": 0, "title": "Общий чат"}], ""
    except Exception as e:
        return [], f"Ошибка: {str(e)}"


# Отправка сообщения в группу
async def send_message_to_topic(task_data: Dict) -> bool:
    """Отправка сообщения с использованием выделенного клиента"""
    client = await get_telethon_client(task_data['task_id'])
    try:
        entity = await client.get_entity(task_data['group_username'])

        if task_data.get('photo_path'):
            await client.send_file(
                entity,
                task_data['photo_path'],
                caption=task_data['message'],
                reply_to=task_data['topic_id'] if task_data['topic_id'] != 0 else None,
                parse_mode='html'
            )
        else:
            await client.send_message(
                entity,
                task_data['message'],
                reply_to=task_data['topic_id'] if task_data['topic_id'] != 0 else None,
                parse_mode='html'
            )
        return True
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")
        return False


# Функция запуска задачи
async def run_task(task_id: str, task_data: Dict, bot: Bot) -> None:
    config = load_config()
    task_data['task_id'] = task_id  # Добавляем ID задачи в данные

    while task_id in active_tasks and active_tasks[task_id]:
        try:
            async with task_semaphore:
                if not await send_message_to_topic(task_data):
                    owner_id = config.get('user_id')
                    if owner_id:
                        await bot.send_message(
                            owner_id,
                            f"Ошибка отправки в @{task_data['group_username']}"
                        )
            await asyncio.sleep(task_data['interval'])
        except Exception as e:
            logging.error(f"Ошибка задачи {task_id}: {e}")
            await asyncio.sleep(1)

# Создание клавиатуры главного меню
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task"),
        InlineKeyboardButton("📋 Мои задачи", callback_data="list_tasks"),
        InlineKeyboardButton("▶️ Включить все", callback_data="start_all_tasks"),
        InlineKeyboardButton("⏹ Выключить все", callback_data="stop_all_tasks"),
        InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
    )
    return keyboard


async def stop_all_tasks(bot: Bot):
    """Останавливает все активные задачи"""
    config = load_config()
    tasks = config.get('tasks', {})
    stopped_count = 0

    for task_id in list(active_tasks.keys()):
        if task_id in tasks and active_tasks[task_id]:
            # Обновляем статус задачи в конфигурации
            config['tasks'][task_id]['active'] = False

            # Удаляем задачу из списка активных
            active_tasks[task_id] = False
            stopped_count += 1

            # Логируем остановку задачи
            logging.info(f"Остановлена задача {task_id}")

    # Сохраняем обновленную конфигурацию
    save_config(config)

    # Возвращаем количество остановленных задач
    return stopped_count


# Обработчик команды перезапуска
async def cmd_restart(message: types.Message, state: FSMContext):
    # Проверяем, что это владелец бота
    config = load_config()
    if message.from_user.id != config.get('user_id'):
        await message.answer("Извините, этот бот приватный и работает только для владельца.")
        return

    await message.answer("🔄 Перезапуск бота...")

    # Останавливаем все активные задачи
    for task_id in list(active_tasks.keys()):
        active_tasks[task_id] = False

    # Даем время на завершение всех задач
    await asyncio.sleep(1)

    # Перезапускаем скрипт
    os.execv(sys.executable, [sys.executable] + sys.argv)


# Создание клавиатуры для выбора топика
def get_topics_keyboard(topics: List[Dict]) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    for topic in topics:
        keyboard.add(InlineKeyboardButton(
            f"#{topic['id']} - {topic['title']}",
            callback_data=f"topic_{topic['id']}_{topic['title']}"
        ))
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    return keyboard


# Создание клавиатуры для списка задач
def get_tasks_keyboard(tasks: Dict[str, Dict], page: int = 0) -> Tuple[InlineKeyboardMarkup, int]:
    keyboard = InlineKeyboardMarkup(row_width=1)
    tasks_list = list(tasks.items())
    total_pages = (len(tasks_list) + 9) // 10  # Округляем вверх

    # Получаем задачи для текущей страницы
    start_idx = page * 10
    end_idx = start_idx + 10
    page_tasks = tasks_list[start_idx:end_idx]

    for task_id, task_data in page_tasks:
        status = "✅ Активна" if task_id in active_tasks and active_tasks[task_id] else "❌ Остановлена"
        keyboard.add(InlineKeyboardButton(
            f"{status} - @{task_data['group_username']} - {task_data['topic_name']}",
            callback_data=f"edit_task_{task_id}"
        ))

    # Добавляем кнопки пагинации, если нужно
    if len(tasks_list) > 10:
        row_buttons = []
        if page > 0:
            row_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"tasks_page_{page - 1}"))
        if end_idx < len(tasks_list):
            row_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"tasks_page_{page + 1}"))
        if row_buttons:
            keyboard.row(*row_buttons)

    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    return keyboard, total_pages


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
        InlineKeyboardButton("🔙 Назад", callback_data="list_tasks")
    )
    return keyboard


# Запускаем бота
async def main():

    # Загружаем конфигурацию при запуске
    config = load_config()

    # Создаем бота и диспетчер
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)

    # Обработчик команды /start
    @dp.message_handler(commands=['start'], state='*')
    async def cmd_start(message: types.Message, state: FSMContext):
        # Сохраняем ID пользователя как владельца бота
        config = load_config()
        if not config.get('user_id'):
            config['user_id'] = message.from_user.id
            save_config(config)

        # Проверяем, что это владелец бота
        if message.from_user.id != config.get('user_id'):
            await message.answer("Извините, этот бот приватный и работает только для владельца.")
            return

        await state.finish()
        await PosterStates.main_menu.set()

        await message.answer(
            "👋 Добро пожаловать в\n"
            "⭐️AutoPostLovely Sell 1.5₽ stars⭐️!\n\n"
            "Для покупки звезд обращаться @lovelymaxing\n\n"
            "Этот бот поможет вам автоматически отправлять сообщения\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик команды /stars
    @dp.message_handler(commands=['stars'], state='*')
    async def cmd_stars(message: types.Message):
        # Проверяем, что это владелец бота
        config = load_config()
        if message.from_user.id != config.get('user_id'):
            await message.answer("Извините, этот бот приватный и работает только для владельца.")
            return

        # Создаем инлайн-кнопку с ссылкой на канал
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("⭐️ LovelyPerexod ⭐️", url="https://t.me/lovelyperexod"))

        await message.answer(
            "⭐️ Купить звезды по 1.5₽ ⭐️\n\n"
            "Перейдите в наш канал, чтобы приобрести звезды:",
            reply_markup=keyboard
        )

    # Обработчик команды /help
    @dp.message_handler(commands=['help'], state='*')
    async def cmd_help(message: types.Message):
        # Проверяем, что это владелец бота
        config = load_config()
        if message.from_user.id != config.get('user_id'):
            await message.answer("Извините, этот бот приватный и работает только для владельца.")
            return

        await message.answer(
            "📚 <b>Справка по использованию</b>\n\n"
            "<b>⭐️ AutoPostLovely Sell 1.5₽ stars ⭐️</b>\n\n"
            "/stars - Перейти в канал для покупки звезд\n\n"
            "<b>Основные команды:</b>\n"
            "/start - Запустить бота и перейти в главное меню\n"
            "/help - Показать эту справку\n"
            "/cancel - Отменить текущее действие и вернуться в главное меню\n\n"
            "<b>Как использовать бота:</b>\n"
            "1. Нажмите '➕ Добавить задачу'\n"
            "2. Укажите ссылку на группу (например, 'lovelyperexod' без @)\n"
            "3. Выберите топик из списка доступных\n"
            "4. Введите текст сообщения (поддерживается HTML)\n"
            "5. Отправьте фото или пропустите этот шаг\n"
            "6. Укажите интервал отправки в секундах\n"
            "7. Подтвердите создание задачи\n\n"
            "<b>Управление задачами:</b>\n"
            "• В разделе 'Мои задачи' вы можете запускать, останавливать, редактировать или удалять задачи\n"
            "• В разделе 'Статус задач' вы можете видеть текущее состояние всех задач\n\n"
            "<b>Важно:</b>\n"
            "• У вас должны быть соответствующие права для отправки сообщений в указанные группы\n"
            "• Клиент Telegram использует указанный при настройке номер телефона\n",
            parse_mode=ParseMode.HTML
        )

    @dp.callback_query_handler(lambda c: c.data == 'start_all_tasks', state='*')
    async def process_start_all_tasks(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        # Фильтруем только неактивные задачи
        inactive_tasks = {
            task_id: task_data
            for task_id, task_data in tasks.items()
            if not active_tasks.get(task_id, False)
        }

        if not inactive_tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "✅ Все задачи уже запущены.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Сообщаем о начале запуска
        await bot.send_message(
            callback_query.from_user.id,
            f"🔄 Запускаю {len(inactive_tasks)} задач с задержкой 2 секунды...",
            reply_markup=get_main_menu_keyboard()
        )

        # Запускаем задачи по одной с задержкой
        for task_id, task_data in inactive_tasks.items():
            config['tasks'][task_id]['active'] = True
            active_tasks[task_id] = True
            asyncio.create_task(run_task(task_id, task_data, bot))
            logging.info(f"Запущена задача {task_id} для группы @{task_data['group_username']}")
            await asyncio.sleep(1)  # Задержка 1 секунда между запусками

        save_config(config)

        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Успешно запущено {len(inactive_tasks)} задач!",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик кнопки "Выключить все"
    @dp.callback_query_handler(lambda c: c.data == 'stop_all_tasks', state='*')
    async def process_stop_all_tasks(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Останавливаем все задачи
        stopped_count = await stop_all_tasks(bot)

        # Отправляем сообщение о результате
        if stopped_count > 0:
            await bot.send_message(
                callback_query.from_user.id,
                f"⏹ Остановлено {stopped_count} активных задач.",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await bot.send_message(
                callback_query.from_user.id,
                "Нет активных задач для остановки.",
                reply_markup=get_main_menu_keyboard()
            )

    # Для регистрации обработчиков в main:
    # 1. Добавить обработчик для команды перезапуска
    @dp.message_handler(commands=['restart'], state='*')
    async def handle_restart(message: types.Message, state: FSMContext):
        await cmd_restart(message, state)

    # 2. Добавить обработчик для переключения уведомлений
    @dp.callback_query_handler(lambda c: c.data == 'toggle_notifications', state='*')
    async def handle_toggle_notifications(callback_query: types.CallbackQuery, state: FSMContext):
        await process_toggle_notifications(callback_query, state)

    # Обработчик команды /cancel
    @dp.message_handler(commands=['cancel'], state='*')
    async def cmd_cancel(message: types.Message, state: FSMContext):
        # Проверяем, что это владелец бота
        config = load_config()
        if message.from_user.id != config.get('user_id'):
            return

        current_state = await state.get_state()
        if current_state is not None:
            await state.finish()
            await PosterStates.main_menu.set()
            await message.answer(
                "Действие отменено. Вы вернулись в главное меню:",
                reply_markup=get_main_menu_keyboard()
            )

    # Обработчик кнопки "Добавить задачу"
    @dp.callback_query_handler(lambda c: c.data == 'add_task', state=PosterStates.main_menu)
    async def process_add_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        await PosterStates.waiting_for_group_link.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Введите имя группы (без @, например: lovelyperexod)\n"
            "Важно: вы должны быть участником этой группы."
        )

    # Обработчик ввода группы
    @dp.message_handler(state=PosterStates.waiting_for_group_link)
    async def process_group_link(message: types.Message, state: FSMContext):
        group_username = message.text.strip()
        if group_username.startswith('@'):
            group_username = group_username[1:]

        temp_task_id = f"temp_{time.time()}"
        topics, error = await find_topics(group_username, temp_task_id)

        if error:
            await message.answer(f"Ошибка: {error}")
            return

        await state.update_data(group_username=group_username)
        await PosterStates.selecting_topic.set()
        await message.answer(
            f"Найдено топиков: {len(topics)}",
            reply_markup=get_topics_keyboard(topics)
        )

    # Обработчик выбора топика
    @dp.callback_query_handler(lambda c: c.data.startswith('topic_'), state=PosterStates.selecting_topic)
    async def process_topic_selection(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Извлекаем ID и название топика из callback_data
        _, topic_id, *topic_name_parts = callback_query.data.split('_')
        topic_name = '_'.join(topic_name_parts) if topic_name_parts else f"Топик #{topic_id}"

        # Сохраняем информацию о топике в состоянии
        await state.update_data(topic_id=int(topic_id), topic_name=topic_name)

        # Переходим к вводу сообщения
        await PosterStates.entering_message.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Введите текст сообщения, которое будет отправляться в этот топик.\n\n"
            "Можно использовать HTML-форматирование:\n"
            "<b>жирный</b>\n"
            "<i>курсив</i>\n"
            "<u>подчеркнутый</u>\n"
            "<a href='http://example.com'>ссылка</a>\n"
            "<code>код</code>\n"
            "<pre>блок кода</pre>\n"
            "<blockquote>цитата</blockquote>"
        )

    # Обработчик ввода сообщения
    @dp.message_handler(state=PosterStates.entering_message)
    async def process_message_text(message: types.Message, state: FSMContext):
        # Сохраняем текст сообщения в состоянии
        await state.update_data(message=message.text)

        # Переходим к загрузке фото
        await PosterStates.uploading_photo.set()
        await message.answer(
            "Теперь отправьте фото, которое будет прикреплено к сообщению, или нажмите кнопку 'Пропустить'",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⏩ Пропустить", callback_data="skip_photo")
            )
        )

    # Обработчик загрузки фото
    @dp.message_handler(content_types=types.ContentType.PHOTO, state=PosterStates.uploading_photo)
    async def process_photo_upload(message: types.Message, state: FSMContext):
        # Получаем текущие данные из состояния
        data = await state.get_data()

        # Создаем уникальное имя файла
        task_id = generate_task_id()
        photo_filename = f"{task_id}.jpg"
        photo_path = os.path.join(PHOTOS_DIR, photo_filename)

        # Скачиваем фото
        await message.photo[-1].download(destination_file=photo_path)

        # Сохраняем путь к фото в состоянии
        await state.update_data(photo_path=photo_path, task_id=task_id)

        # Переходим к установке интервала
        await PosterStates.setting_interval.set()
        await message.answer(
            "Фото успешно загружено. Теперь введите интервал отправки сообщений в секундах.\n"
            "Например: 300 (для отправки каждые 5 минут)"
        )

    # Обработчик кнопки "Пропустить фото"
    @dp.callback_query_handler(lambda c: c.data == 'skip_photo', state=PosterStates.uploading_photo)
    async def process_skip_photo(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Генерируем ID задачи
        task_id = generate_task_id()
        await state.update_data(photo_path=None, task_id=task_id)

        # Переходим к установке интервала
        await PosterStates.setting_interval.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Фото пропущено. Введите интервал отправки сообщений в секундах.\n"
            "Например: 300 (для отправки каждые 5 минут)"
        )

    # Обработчик ввода интервала
    @dp.message_handler(state=PosterStates.setting_interval)
    async def process_interval(message: types.Message, state: FSMContext):
        try:
            interval = int(message.text.strip())
            if interval < 30:
                await message.answer(
                    "Интервал не может быть меньше 30 секунд. "
                    "Пожалуйста, введите значение не менее 30:"
                )
                return
        except ValueError:
            await message.answer(
                "Пожалуйста, введите корректное число секунд (целое число не меньше 30):"
            )
            return

        # Сохраняем интервал в состоянии
        await state.update_data(interval=interval)

        # Получаем все данные из состояния для подтверждения
        data = await state.get_data()

        # Формируем сообщение для подтверждения
        confirm_message = (
            f"<b>📝 Новая задача:</b>\n\n"
            f"<b>Группа:</b> @{data['group_username']}\n"
            f"<b>Топик:</b> {data['topic_name']} (ID: {data['topic_id']})\n"
            f"<b>Интервал:</b> {data['interval']} сек. ({data['interval'] // 60} мин. {data['interval'] % 60} сек.)\n"
            f"<b>Фото:</b> {'✅ Прикреплено' if data.get('photo_path') else '❌ Нет'}\n\n"
            f"<b>Текст сообщения:</b>\n"
            f"{data['message']}\n\n"
            f"Все верно? Нажмите 'Подтвердить' для сохранения задачи:"
        )

        # Создаем клавиатуру для подтверждения
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_task"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_task")
        )

        # Показываем данные для подтверждения
        await PosterStates.confirm_add.set()
        await message.answer(confirm_message, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # Обработчик подтверждения добавления задачи
    @dp.callback_query_handler(lambda c: c.data == 'confirm_task', state=PosterStates.confirm_add)
    async def process_confirm_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем все данные из состояния
        data = await state.get_data()
        task_id = data['task_id']

        # Создаем запись задачи
        task_data = {
            "group_username": data['group_username'],
            "topic_id": data['topic_id'],
            "topic_name": data['topic_name'],
            "message": data['message'],
            "photo_path": data['photo_path'],
            "interval": data['interval'],
            "active": True,  # Изменено на True, чтобы задача сразу запускалась
        }

        # Сохраняем задачу в конфигурации
        config = load_config()
        if 'tasks' not in config:
            config['tasks'] = {}
        config['tasks'][task_id] = task_data
        save_config(config)

        # Если задача активна, запускаем ее
        if task_data['active']:
            active_tasks[task_id] = True
            asyncio.create_task(run_task(task_id, task_data, bot))
            logging.info(f"Задача {task_id} сразу запущена после добавления")

        # Возвращаемся в главное меню
        await state.finish()
        await PosterStates.main_menu.set()

        # Отправляем сообщение об успешном добавлении
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Задача успешно добавлена и запущена!\n\n"
            f"Бот будет отправлять сообщения в группу @{task_data['group_username']}, "
            f"топик '{task_data['topic_name']}' каждые {task_data['interval']} секунд.",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик отмены добавления задачи
    @dp.callback_query_handler(lambda c: c.data == 'cancel_task', state=PosterStates.confirm_add)
    async def process_cancel_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем данные из состояния
        data = await state.get_data()

        # Удаляем временный файл фото, если он был загружен
        if data.get('photo_path') and os.path.exists(data['photo_path']):
            try:
                os.remove(data['photo_path'])
            except:
                pass

        # Возвращаемся в главное меню
        await state.finish()
        await PosterStates.main_menu.set()

        await bot.send_message(
            callback_query.from_user.id,
            "❌ Добавление задачи отменено.",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик переключения страниц задач
    @dp.callback_query_handler(lambda c: c.data.startswith('tasks_page_'), state=PosterStates.select_task_to_edit)
    async def process_tasks_page(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем номер страницы
        page = int(callback_query.data.replace('tasks_page_', ''))

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        # Показываем запрошенную страницу задач
        keyboard, total_pages = get_tasks_keyboard(tasks, page=page)
        await bot.edit_message_text(
            f"📋 Ваши задачи (страница {page + 1}/{total_pages}):\n\n"
            "Выберите задачу для управления:",
            chat_id=callback_query.from_user.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard
        )
    
    # Обработчик кнопки "Мои задачи"
    @dp.callback_query_handler(lambda c: c.data == 'list_tasks', state='*')
    async def process_list_tasks(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        if not tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "У вас пока нет задач. Добавьте новую задачу с помощью кнопки '➕ Добавить задачу'.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Показываем первую страницу задач
        keyboard, total_pages = get_tasks_keyboard(tasks, page=0)
        await PosterStates.select_task_to_edit.set()
        await bot.send_message(
            callback_query.from_user.id,
            f"📋 Ваши задачи (страница 1/{total_pages}):\n\n"
            "Выберите задачу для управления:",
            reply_markup=keyboard
        )

    # Обработчик выбора задачи для редактирования
    @dp.callback_query_handler(lambda c: c.data.startswith('edit_task_'), state=PosterStates.select_task_to_edit)
    async def process_edit_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('edit_task_', '')

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Сохраняем ID задачи в состоянии
        await state.update_data(task_id=task_id)

        # Получаем данные задачи
        task_data = tasks[task_id]

        # Формируем сообщение с информацией о задаче
        task_message = (
            f"<b>📝 Информация о задаче:</b>\n\n"
            f"<b>Группа:</b> @{task_data['group_username']}\n"
            f"<b>Топик:</b> {task_data['topic_name']} (ID: {task_data['topic_id']})\n"
            f"<b>Интервал:</b> {task_data['interval']} сек. ({task_data['interval'] // 60} мин. {task_data['interval'] % 60} сек.)\n"
            f"<b>Фото:</b> {'✅ Есть' if task_data.get('photo_path') else '❌ Нет'}\n"
            f"<b>Статус:</b> {'✅ Активна' if task_id in active_tasks and active_tasks[task_id] else '❌ Остановлена'}\n\n"
            f"<b>Текст сообщения:</b>\n"
            f"{task_data['message']}\n\n"
            f"Выберите действие:"
        )

        # Показываем информацию о задаче и кнопки управления
        await bot.send_message(
            callback_query.from_user.id,
            task_message,
            reply_markup=get_task_control_keyboard(task_id),
            parse_mode=ParseMode.HTML
        )

    # Обработчик запуска задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('start_task_'), state='*')
    async def process_start_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('start_task_', '')

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Обновляем статус задачи в конфигурации
        config['tasks'][task_id]['active'] = True
        save_config(config)

        # Добавляем задачу в список активных
        task_data = tasks[task_id]
        active_tasks[task_id] = True

        # Запускаем задачу в фоновом режиме
        asyncio.create_task(run_task(task_id, task_data, bot))

        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Задача запущена!\n\n"
            f"Бот будет отправлять сообщения в группу @{task_data['group_username']}, "
            f"топик '{task_data['topic_name']}' каждые {task_data['interval']} секунд.",
            reply_markup=get_task_control_keyboard(task_id)
        )

    # Обработчик остановки задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('stop_task_'), state='*')
    async def process_stop_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('stop_task_', '')

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Обновляем статус задачи в конфигурации
        config['tasks'][task_id]['active'] = False
        save_config(config)

        # Удаляем задачу из списка активных
        active_tasks[task_id] = False

        await bot.send_message(
            callback_query.from_user.id,
            f"⏹ Задача остановлена.",
            reply_markup=get_task_control_keyboard(task_id)
        )

        # Сохраняем ID задачи в состоянии
        await state.update_data(task_id=task_id)

        # Переходим к загрузке нового фото
        await PosterStates.uploading_photo.set()

        # Показываем текущее фото, если есть
        if tasks[task_id].get('photo_path') and os.path.exists(tasks[task_id]['photo_path']):
            with open(tasks[task_id]['photo_path'], 'rb') as photo:
                await bot.send_photo(
                    callback_query.from_user.id,
                    photo,
                    caption="Текущее фото. Отправьте новое фото или нажмите 'Пропустить'",
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton("⏩ Пропустить", callback_data="skip_photo")
                    )
                )
        else:
            await bot.send_message(
                callback_query.from_user.id,
                "Фото не установлено. Отправьте фото или нажмите 'Пропустить'",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("⏩ Пропустить", callback_data="skip_photo")
                )
            )

    # Обработчик удаления задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('delete_task_'), state='*')
    async def process_delete_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('delete_task_', '')

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Сохраняем ID задачи в состоянии
        await state.update_data(task_id=task_id)

        # Просим подтверждение на удаление
        await PosterStates.delete_confirmation.set()

        # Создаем клавиатуру для подтверждения
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{task_id}"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data=f"cancel_delete_{task_id}")
        )

        await bot.send_message(
            callback_query.from_user.id,
            f"⚠️ Вы действительно хотите удалить задачу для группы @{tasks[task_id]['group_username']}, "
            f"топик '{tasks[task_id]['topic_name']}'?\n\n"
            f"Это действие нельзя отменить.",
            reply_markup=keyboard
        )

    # Обработчик подтверждения удаления задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('confirm_delete_'), state=PosterStates.delete_confirmation)
    async def process_confirm_delete(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('confirm_delete_', '')

        # Загружаем конфигурацию
        config = load_config()
        tasks = config.get('tasks', {})

        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Останавливаем задачу, если она активна
        if task_id in active_tasks:
            active_tasks[task_id] = False

        # Удаляем фото, если оно есть
        if tasks[task_id].get('photo_path') and os.path.exists(tasks[task_id]['photo_path']):
            try:
                os.remove(tasks[task_id]['photo_path'])
            except:
                pass

        # Удаляем задачу из конфигурации
        del config['tasks'][task_id]
        save_config(config)

        # Возвращаемся к списку задач
        await state.finish()
        await PosterStates.main_menu.set()

        await bot.send_message(
            callback_query.from_user.id,
            "🗑 Задача успешно удалена.",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик отмены удаления задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('cancel_delete_'), state=PosterStates.delete_confirmation)
    async def process_cancel_delete(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('cancel_delete_', '')

        # Возвращаемся к просмотру задачи
        await state.update_data(task_id=task_id)
        await bot.send_message(
            callback_query.from_user.id,
            "Удаление отменено.",
            reply_markup=get_task_control_keyboard(task_id)
        )

    # Обработчик кнопки "Помощь"
    @dp.callback_query_handler(lambda c: c.data == 'help', state='*')
    async def process_help(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Отправляем справочное сообщение (такое же, как при команде /help)
        await bot.send_message(
            callback_query.from_user.id,
            "📚 <b>Справка по использованию ⭐️ AutoPostLovely Sell 1.5₽ stars ⭐️</b>\n\n"
            "/stars - Запустить бота и перейти в главное меню\n\n"
            "<b>Основные команды:</b>\n"
            "/start - Запустить бота и перейти в главное меню\n"
            "/restart - Перезапустить бота\n"
            "/help - Показать эту справку\n"
            "/cancel - Отменить текущее действие и вернуться в главное меню\n\n"
            "<b>Как использовать бота:</b>\n"
            "1. Нажмите '➕ Добавить задачу'\n"
            "2. Укажите ссылку на группу (например, 'lovelyperexod' без @)\n"
            "3. Выберите топик из списка доступных\n"
            "4. Введите текст сообщения (поддерживается HTML)\n"
            "5. Отправьте фото или пропустите этот шаг\n"
            "6. Укажите интервал отправки в секундах\n"
            "7. Подтвердите создание задачи\n\n"
            "<b>Управление задачами:</b>\n"
            "• В разделе 'Мои задачи' вы можете запускать, останавливать, редактировать или удалять задачи\n\n"
            "<b>Важно:</b>\n"
            "• У вас должны быть соответствующие права для отправки сообщений в указанные группы\n"
            "• Клиент Telegram использует указанный при настройке номер телефона\n",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
            )
        )

    # Обработчик кнопки "Назад" в главное меню
    @dp.callback_query_handler(lambda c: c.data == 'back_to_main', state='*')
    async def process_back_to_main(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Возвращаемся в главное меню
        current_state = await state.get_state()
        if current_state is not None:
            await state.finish()

        await PosterStates.main_menu.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Вы вернулись в главное меню:",
            reply_markup=get_main_menu_keyboard()
        )

    # Загружаем активные задачи при запуске бота
    try:
        # Автозапуск задач
        config = load_config()
        for task_id, task_data in config.get('tasks', {}).items():
            if task_data.get('active'):
                active_tasks[task_id] = True
                asyncio.create_task(run_task(task_id, task_data, bot))
                await asyncio.sleep(0.5)  # Задержка между запуском задач

        await dp.start_polling()

    except asyncio.CancelledError:
        logging.info("Получен сигнал остановки")
    except Exception as e:
        logging.error(f"Ошибка в основном цикле: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        # Гарантированная очистка ресурсов
        logging.info("Завершение работы...")

        # Остановка всех задач
        for task_id in list(active_tasks.keys()):
            active_tasks[task_id] = False

        # Закрытие соединений
        await dp.storage.close()
        await dp.storage.wait_closed()
        await close_all_telethon_clients()
        await bot.close()

        logging.info("Все соединения закрыты. Бот остановлен.")


if __name__ == "__main__":
    logging.info("Запуск бота...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logging.error(f"Критическая ошибка: {str(e)}")
        import traceback

        logging.error(traceback.format_exc())