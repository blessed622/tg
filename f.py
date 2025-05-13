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
from telethon import TelegramClient
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError

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
BOT_TOKEN = "7771036742:AAExM-ibsAhwee-lXe_bToJlZtLIwN1rBUE"

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
    delete_confirmation = State()

# Глобальные переменные
active_tasks = {}
telethon_client = None
task_queue = asyncio.Queue()

# Функции для работы с конфигурацией
def load_config() -> Dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка при загрузке конфигурации: {e}")
    return {"tasks": {}, "user_id": None}

def save_config(config: Dict) -> None:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка при сохранении конфигурации: {e}")

# Генерация уникального ID для задачи
def generate_task_id() -> str:
    return f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}"

# Создание клиента Telethon
async def create_telethon_client() -> TelegramClient:
    global telethon_client
    if telethon_client is None or not telethon_client.is_connected():
        telethon_client = TelegramClient("poster_session", API_ID, API_HASH)
        await telethon_client.start(phone=PHONE_NUMBER)
        logging.info("Telethon client created and connected")
    return telethon_client

# Функция для поиска топиков в группе
async def find_topics(group_username: str) -> Tuple[List[Dict], str]:
    client = await create_telethon_client()
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
                logging.warning(f"Не удалось получить список топиков напрямую: {str(e)}")
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
        logging.error(f"Error in find_topics: {e}", exc_info=True)
    
    return topics_info, error_message

# Отправка сообщения в группу
async def send_message_to_topic(task_data: Dict) -> bool:
    client = await create_telethon_client()
    success = False

    try:
        entity = await client.get_entity(f"@{task_data['group_username']}")

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
        logging.info(f"Message successfully sent to @{task_data['group_username']}")

    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {str(e)}", exc_info=True)
    
    return success

# Обработчик задач из очереди
async def task_worker(bot: Bot):
    while True:
        task_id, task_data = await task_queue.get()
        try:
            if task_id in active_tasks and active_tasks[task_id]:
                success = await send_message_to_topic(task_data)
                
                config = load_config()
                owner_id = config.get('user_id')
                notifications_enabled = config.get('notifications_enabled', True)

                if success:
                    config['tasks'][task_id]['last_posted'] = task_data['last_posted']
                    save_config(config)
                    
                    if owner_id and notifications_enabled:
                        await bot.send_message(
                            owner_id,
                            f"✅ Сообщение успешно отправлено в группу @{task_data['group_username']}, "
                            f"топик '{task_data.get('topic_name', 'Нет топика')}'\n"
                            f"⏱ Следующая отправка через {task_data['interval']} сек."
                        )
                
                # Добавляем задачу обратно в очередь с задержкой
                if task_id in active_tasks and active_tasks[task_id]:
                    await asyncio.sleep(task_data['interval'])
                    await task_queue.put((task_id, task_data))
        except Exception as e:
            logging.error(f"Ошибка в обработчике задачи {task_id}: {e}", exc_info=True)
            await asyncio.sleep(30)
            if task_id in active_tasks and active_tasks[task_id]:
                await task_queue.put((task_id, task_data))
        
        task_queue.task_done()

# Создание клавиатуры главного меню
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task"),
        InlineKeyboardButton("📋 Мои задачи", callback_data="list_tasks")
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

def toggle_notifications_status(config: Dict) -> Dict:
    if 'notifications_enabled' not in config:
        config['notifications_enabled'] = False
    else:
        config['notifications_enabled'] = not config['notifications_enabled']
    save_config(config)
    return config

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
        InlineKeyboardButton("🔙 Назад", callback_data="list_tasks")
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
    
    # Запускаем обработчик задач
    asyncio.create_task(task_worker(bot))
    
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
            "👋 Добро пожаловать в Telegram Poster Bot!\n\n"
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
            "/cancel - Отменить текущее действие и вернуться в главное меню\n\n"
            "<b>Как использовать бота:</b>\n"
            "1. Нажмите '➕ Добавить задачу'\n"
            "2. Укажите ссылку на группу (например, 'gifts_buy' без @)\n"
            "3. Выберите топик из списка доступных\n"
            "4. Введите текст сообщения (поддерживается HTML)\n"
            "5. Отправьте фото или пропустите этот шаг\n"
            "6. Укажите интервал отправки в секундах\n"
            "7. Подтвердите создание задачи\n\n"
            "<b>Важно:</b>\n"
            "• У вас должны быть соответствующие права для отправки сообщений в указанные группы\n"
            "• Клиент Telegram использует указанный при настройке номер телефона\n",
            parse_mode=ParseMode.HTML
        )
    
    # Обработчик команды /cancel
    @dp.message_handler(commands=['cancel'], state='*')
    async def cmd_cancel(message: types.Message, state: FSMContext):
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

    @dp.callback_query_handler(lambda c: c.data.startswith('use_without_topics_'), state='*')
    async def process_use_without_topics(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        group_username = callback_query.data.replace('use_without_topics_', '')

        await state.update_data(group_username=group_username, topic_id=0, topic_name="Нет топика")
        await PosterStates.entering_message.set()
        await bot.send_message(
            callback_query.from_user.id,
            f"Вы выбрали отправку сообщений в группу @{group_username} без указания топика.\n\n"
            f"Введите текст сообщения:",
            parse_mode=ParseMode.HTML
        )

    # Обработчик кнопки "Добавить задачу"
    @dp.callback_query_handler(lambda c: c.data == 'add_task', state=PosterStates.main_menu)
    async def process_add_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        await PosterStates.waiting_for_group_link.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Введите имя группы (без @, например: gifts_buy)\n"
            "Важно: вы должны быть участником этой группы."
        )

    @dp.callback_query_handler(lambda c: c.data == 'start_all_tasks', state='*')
    async def process_start_all_tasks(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        config = load_config()
        tasks = config.get('tasks', {})

        if not tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "У вас пока нет задач.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        started_count = 0
        already_running_count = 0

        for task_id, task_data in tasks.items():
            if task_id in active_tasks and active_tasks[task_id]:
                already_running_count += 1
                continue

            config['tasks'][task_id]['active'] = True
            active_tasks[task_id] = True
            
            # Добавляем задержку между запусками задач
            if started_count > 0:
                await asyncio.sleep(2)
            
            await task_queue.put((task_id, task_data))
            started_count += 1

        save_config(config)

        await bot.send_message(
            callback_query.from_user.id,
            f"🚀 Задачи активированы!\n\n"
            f"✅ Запущено новых задач: {started_count}\n"
            f"ℹ️ Уже работающих задач: {already_running_count}",
            reply_markup=get_main_menu_keyboard()
        )

    @dp.callback_query_handler(lambda c: c.data == 'stop_all_tasks', state='*')
    async def process_stop_all_tasks(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        config = load_config()
        tasks = config.get('tasks', {})

        if not tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "У вас пока нет задач.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        stopped_count = 0
        already_stopped_count = 0

        for task_id, task_data in tasks.items():
            if task_id not in active_tasks or not active_tasks[task_id]:
                already_stopped_count += 1
                continue

            config['tasks'][task_id]['active'] = False
            active_tasks[task_id] = False
            stopped_count += 1

        save_config(config)

        await bot.send_message(
            callback_query.from_user.id,
            f"⏹ Задачи остановлены!\n\n"
            f"✅ Остановлено задач: {stopped_count}\n"
            f"ℹ️ Уже остановленных задач: {already_stopped_count}",
            reply_markup=get_main_menu_keyboard()
        )

    @dp.callback_query_handler(lambda c: c.data == 'toggle_notifications', state='*')
    async def process_toggle_notifications(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        config = load_config()
        config = toggle_notifications_status(config)
        notifications_enabled = config.get('notifications_enabled', True)
        status_text = "включены" if notifications_enabled else "отключены"

        await bot.send_message(
            callback_query.from_user.id,
            f"🔔 Уведомления {status_text}.",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик ввода группы
    @dp.message_handler(state=PosterStates.waiting_for_group_link)
    async def process_group_link(message: types.Message, state: FSMContext):
        group_username = message.text.strip()
        if group_username.startswith('@'):
            group_username = group_username[1:]

        if not group_username:
            await message.answer("Имя группы не может быть пустым.")
            return

        await message.answer(f"Ищем топики в группе @{group_username}...")

        topics, error = await find_topics(group_username)

        if error or not topics:
            keyboard = InlineKeyboardMarkup(row_width=2)
            keyboard.add(
                InlineKeyboardButton("✅ Да, использовать без топиков",
                                     callback_data=f"use_without_topics_{group_username}"),
                InlineKeyboardButton("❌ Нет, отмена", callback_data="back_to_main")
            )

            await message.answer(
                f"В группе @{group_username} не найдено доступных топиков или произошла ошибка: {error}\n\n"
                f"Хотите использовать эту группу без указания топика?",
                reply_markup=keyboard
            )
            return

        await state.update_data(group_username=group_username)
        await PosterStates.selecting_topic.set()
        await message.answer(
            f"Найдено {len(topics)} топиков в группе @{group_username}.\nВыберите топик:",
            reply_markup=get_topics_keyboard(topics)
        )
    
    # Обработчик выбора топика
    @dp.callback_query_handler(lambda c: c.data.startswith('topic_'), state=PosterStates.selecting_topic)
    async def process_topic_selection(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        _, topic_id, *topic_name_parts = callback_query.data.split('_')
        topic_name = '_'.join(topic_name_parts) if topic_name_parts else f"Топик #{topic_id}"
        
        await state.update_data(topic_id=int(topic_id), topic_name=topic_name)
        await PosterStates.entering_message.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Введите текст сообщения:",
            parse_mode=ParseMode.HTML
        )
    
    # Обработчик ввода сообщения
    @dp.message_handler(state=PosterStates.entering_message)
    async def process_message_text(message: types.Message, state: FSMContext):
        await state.update_data(message=message.text)
        await PosterStates.uploading_photo.set()
        await message.answer(
            "Отправьте фото или нажмите 'Пропустить'",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⏩ Пропустить", callback_data="skip_photo")
            )
        )
    
    # Обработчик загрузки фото
    @dp.message_handler(content_types=types.ContentType.PHOTO, state=PosterStates.uploading_photo)
    async def process_photo_upload(message: types.Message, state: FSMContext):
        data = await state.get_data()
        task_id = generate_task_id()
        photo_filename = f"{task_id}.jpg"
        photo_path = os.path.join(PHOTOS_DIR, photo_filename)
        
        await message.photo[-1].download(destination_file=photo_path)
        await state.update_data(photo_path=photo_path, task_id=task_id)
        await PosterStates.setting_interval.set()
        await message.answer(
            "Фото успешно загружено. Введите интервал отправки в секундах (не менее 30):"
        )
    
    # Обработчик кнопки "Пропустить фото"
    @dp.callback_query_handler(lambda c: c.data == 'skip_photo', state=PosterStates.uploading_photo)
    async def process_skip_photo(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        task_id = generate_task_id()
        await state.update_data(photo_path=None, task_id=task_id)
        await PosterStates.setting_interval.set()
        await bot.send_message(
            callback_query.from_user.id,
            "Введите интервал отправки в секундах (не менее 30):"
        )
    
    # Обработчик ввода интервала
    @dp.message_handler(state=PosterStates.setting_interval)
    async def process_interval(message: types.Message, state: FSMContext):
        try:
            interval = int(message.text.strip())
            if interval < 30:
                await message.answer("Интервал не может быть меньше 30 секунд.")
                return
        except ValueError:
            await message.answer("Пожалуйста, введите корректное число секунд (не менее 30):")
            return
        
        await state.update_data(interval=interval)
        data = await state.get_data()
        
        confirm_message = (
            f"<b>📝 Новая задача:</b>\n\n"
            f"<b>Группа:</b> @{data['group_username']}\n"
            f"<b>Топик:</b> {data['topic_name']} (ID: {data['topic_id']})\n"
            f"<b>Интервал:</b> {data['interval']} сек.\n"
            f"<b>Фото:</b> {'✅ Прикреплено' if data.get('photo_path') else '❌ Нет'}\n\n"
            f"<b>Текст сообщения:</b>\n"
            f"{data['message']}\n\n"
            f"Все верно?"
        )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_task"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_task")
        )
        
        await PosterStates.confirm_add.set()
        await message.answer(confirm_message, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    # Обработчик подтверждения добавления задачи
    @dp.callback_query_handler(lambda c: c.data == 'confirm_task', state=PosterStates.confirm_add)
    async def process_confirm_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        data = await state.get_data()
        task_id = data['task_id']
        
        task_data = {
            "group_username": data['group_username'],
            "topic_id": data['topic_id'],
            "topic_name": data['topic_name'],
            "message": data['message'],
            "photo_path": data['photo_path'],
            "interval": data['interval'],
            "active": False,
            "last_posted": None
        }
        
        config = load_config()
        if 'tasks' not in config:
            config['tasks'] = {}
        config['tasks'][task_id] = task_data
        save_config(config)
        
        await state.finish()
        await PosterStates.main_menu.set()
        
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Задача успешно добавлена!",
            reply_markup=get_main_menu_keyboard()
        )
    
    # Обработчик отмены добавления задачи
    @dp.callback_query_handler(lambda c: c.data == 'cancel_task', state=PosterStates.confirm_add)
    async def process_cancel_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        data = await state.get_data()
        
        if data.get('photo_path') and os.path.exists(data['photo_path']):
            try:
                os.remove(data['photo_path'])
            except:
                pass
        
        await state.finish()
        await PosterStates.main_menu.set()
        
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Добавление задачи отменено.",
            reply_markup=get_main_menu_keyboard()
        )
    
    # Обработчик кнопки "Мои задачи"
    @dp.callback_query_handler(lambda c: c.data == 'list_tasks', state='*')
    async def process_list_tasks(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        config = load_config()
        tasks = config.get('tasks', {})
        
        if not tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "У вас пока нет задач.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        await bot.send_message(
            callback_query.from_user.id,
            "📋 Ваши задачи:",
            reply_markup=get_tasks_keyboard(tasks)
        )
    
    # Обработчик выбора задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('task_info_'), state='*')
    async def process_task_info(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        task_id = callback_query.data.replace('task_info_', '')
        config = load_config()
        tasks = config.get('tasks', {})
        
        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        task_data = tasks[task_id]
        task_message = (
            f"<b>📝 Информация о задаче:</b>\n\n"
            f"<b>Группа:</b> @{task_data['group_username']}\n"
            f"<b>Топик:</b> {task_data['topic_name']} (ID: {task_data['topic_id']})\n"
            f"<b>Интервал:</b> {task_data['interval']} сек.\n"
            f"<b>Статус:</b> {'✅ Активна' if task_id in active_tasks and active_tasks[task_id] else '❌ Остановлена'}\n"
            f"<b>Последняя отправка:</b> {task_data.get('last_posted', 'Нет')}\n\n"
            f"<b>Текст сообщения:</b>\n"
            f"{task_data['message']}"
        )
        
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
        task_id = callback_query.data.replace('start_task_', '')
        config = load_config()
        tasks = config.get('tasks', {})
        
        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        config['tasks'][task_id]['active'] = True
        save_config(config)
        active_tasks[task_id] = True
        await task_queue.put((task_id, tasks[task_id]))
        
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Задача запущена!",
            reply_markup=get_task_control_keyboard(task_id)
        )
    
    # Обработчик остановки задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('stop_task_'), state='*')
    async def process_stop_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        task_id = callback_query.data.replace('stop_task_', '')
        config = load_config()
        tasks = config.get('tasks', {})
        
        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        config['tasks'][task_id]['active'] = False
        save_config(config)
        active_tasks[task_id] = False
        
        await bot.send_message(
            callback_query.from_user.id,
            f"⏹ Задача остановлена.",
            reply_markup=get_task_control_keyboard(task_id)
        )
    
    # Обработчик удаления задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('delete_task_'), state='*')
    async def process_delete_task(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        task_id = callback_query.data.replace('delete_task_', '')
        config = load_config()
        tasks = config.get('tasks', {})
        
        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        await state.update_data(task_id=task_id)
        await PosterStates.delete_confirmation.set()
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{task_id}"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data=f"cancel_delete_{task_id}")
        )
        
        await bot.send_message(
            callback_query.from_user.id,
            f"⚠️ Вы действительно хотите удалить задачу для группы @{tasks[task_id]['group_username']}?",
            reply_markup=keyboard
        )
    
    # Обработчик подтверждения удаления задачи
    @dp.callback_query_handler(lambda c: c.data.startswith('confirm_delete_'), state=PosterStates.delete_confirmation)
    async def process_confirm_delete(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        task_id = callback_query.data.replace('confirm_delete_', '')
        config = load_config()
        tasks = config.get('tasks', {})
        
        if task_id not in tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "Задача не найдена.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        if task_id in active_tasks:
            active_tasks[task_id] = False
        
        if tasks[task_id].get('photo_path') and os.path.exists(tasks[task_id]['photo_path']):
            try:
                os.remove(tasks[task_id]['photo_path'])
            except:
                pass
        
        del config['tasks'][task_id]
        save_config(config)
        
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
        task_id = callback_query.data.replace('cancel_delete_', '')
        await bot.send_message(
            callback_query.from_user.id,
            "Удаление отменено.",
            reply_markup=get_task_control_keyboard(task_id)
        )
    
    # Обработчик кнопки "Статус задач"
    @dp.callback_query_handler(lambda c: c.data == 'task_status', state='*')
    async def process_task_status(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        config = load_config()
        tasks = config.get('tasks', {})
        
        if not tasks:
            await bot.send_message(
                callback_query.from_user.id,
                "У вас пока нет задач.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        status_message = "<b>📊 Статус задач:</b>\n\n"
        
        for task_id, task_data in tasks.items():
            is_active = task_id in active_tasks and active_tasks[task_id]
            status = "✅ Активна" if is_active else "❌ Остановлена"
            
            status_message += (
                f"<b>{status}</b>\n"
                f"👥 Группа: @{task_data['group_username']}\n"
                f"📌 Топик: {task_data['topic_name']}\n"
                f"⏱ Интервал: {task_data['interval']} сек.\n"
                f"🕒 Последняя отправка: {task_data.get('last_posted', 'Нет')}\n\n"
            )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        
        await bot.send_message(
            callback_query.from_user.id,
            status_message,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    
    # Обработчик кнопки "Помощь"
    @dp.callback_query_handler(lambda c: c.data == 'help', state='*')
    async def process_help(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        await bot.send_message(
            callback_query.from_user.id,
            "📚 <b>Справка по использованию Telegram Poster Bot</b>\n\n"
            "<b>Основные команды:</b>\n"
            "/start - Запустить бота и перейти в главное меню\n"
            "/help - Показать эту справку\n"
            "/cancel - Отменить текущее действие и вернуться в главное меню\n\n"
            "<b>Как использовать бота:</b>\n"
            "1. Нажмите '➕ Добавить задачу'\n"
            "2. Укажите ссылку на группу (например, 'gifts_buy' без @)\n"
            "3. Выберите топик из списка доступных\n"
            "4. Введите текст сообщения (поддерживается HTML)\n"
            "5. Отправьте фото или пропустите этот шаг\n"
            "6. Укажите интервал отправки в секундах\n"
            "7. Подтвердите создание задачи\n\n"
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
    config = load_config()
    for task_id, task_data in config.get('tasks', {}).items():
        if task_data.get('active', False):
            active_tasks[task_id] = True
            await task_queue.put((task_id, task_data))
            logging.info(f"Автоматически запущена задача {task_id}")
    
    # Проверяем ID владельца бота
    owner_id = config.get('user_id')
    if owner_id:
        try:
            await bot.send_message(
                owner_id,
                "🤖 Telegram Poster Bot запущен!",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение владельцу: {e}")
    
    # Запускаем пуллинг обновлений
    await dp.start_polling()

# Запускаем бота
if __name__ == "__main__":
    logging.info("Запуск Telegram Poster Bot...")
    
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")
    except Exception as e:
        logging.error(f"Критическая ошибка: {str(e)}", exc_info=True)