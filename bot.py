"""
Основной модуль Telegram-бота на базе Aiogram для управления userbot
"""
import asyncio
import logging
import datetime
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.filters import Text
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.exceptions import BotBlocked

from config import BOT_TOKEN, OWNER_ID, LOGS_PATH
from database import DatabaseManager
from scheduler import scheduler
from userbot import userbot

# Настройка логирования
os.makedirs(LOGS_PATH, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=f"{LOGS_PATH}/bot.log"
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()  # Для хранения состояний FSM
dp = Dispatcher(bot, storage=storage)
db = DatabaseManager()

# CallbackData для обработки нажатий на инлайн-кнопки
menu_cd = CallbackData("show_menu", "level", "menu_id", "action")
task_cd = CallbackData("task", "action", "task_id")
user_cd = CallbackData("user", "action", "user_id")
chat_cd = CallbackData("chat", "action", "chat_id", "topic_id")

# Определение состояний FSM для различных диалогов
class TaskStates(StatesGroup):
    # Состояния для создания задачи
    choosing_task_type = State()  # Выбор типа задачи (пересылка или сообщение)
    entering_message_text = State()  # Ввод текста сообщения
    choosing_source_chat = State()  # Выбор исходного чата для пересылки
    choosing_source_message = State()  # Выбор сообщения для пересылки
    choosing_target_chat = State()  # Выбор целевого чата
    choosing_topic = State()  # Выбор топика в супергруппе, если есть
    choosing_schedule = State()  # Настройка расписания

class AdminStates(StatesGroup):
    # Состояния для админ-действий
    adding_user = State()  # Добавление пользователя
    setting_subscription_days = State()  # Установка срока подписки
    sending_broadcast = State()  # Отправка рассылки всем пользователям

# Функция для проверки прав администратора
async def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    if user_id == OWNER_ID:
        return True
    
    user = db.get_user(user_id)
    return user and user.get('is_admin', False)

# Функция для проверки активной подписки
async def has_active_subscription(user_id):
    """Проверка, имеет ли пользователь активную подписку"""
    is_active, message = db.check_subscription(user_id)
    return is_active, message

# Создание основных меню

def make_main_keyboard(user_id):
    """Создание основной клавиатуры"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    # Основные кнопки для всех пользователей
    keyboard.add(InlineKeyboardButton("📋 Мои задачи", callback_data=menu_cd.new(level=1, menu_id=0, action="my_tasks")))
    keyboard.add(InlineKeyboardButton("➕ Добавить задачу", callback_data=menu_cd.new(level=1, menu_id=0, action="add_task")))
    keyboard.add(InlineKeyboardButton("👤 Мой профиль", callback_data=menu_cd.new(level=1, menu_id=0, action="profile")))
    keyboard.add(InlineKeyboardButton("🔔 Уведомления", callback_data=menu_cd.new(level=1, menu_id=0, action="notifications")))
    keyboard.add(InlineKeyboardButton("📊 Статистика", callback_data=menu_cd.new(level=1, menu_id=0, action="stats")))
    keyboard.add(InlineKeyboardButton("❓ Помощь", callback_data=menu_cd.new(level=1, menu_id=0, action="help")))
    
    # Дополнительные кнопки для администраторов
    if asyncio.get_event_loop().run_until_complete(is_admin(user_id)):
        keyboard.add(InlineKeyboardButton("👑 Панель админа", callback_data=menu_cd.new(level=1, menu_id=0, action="admin_panel")))
    
    return keyboard

def make_admin_keyboard():
    """Создание клавиатуры панели администратора"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("👥 Управление пользователями", callback_data=menu_cd.new(level=2, menu_id=0, action="manage_users")))
    keyboard.add(InlineKeyboardButton("📢 Рассылка сообщений", callback_data=menu_cd.new(level=2, menu_id=0, action="broadcast")))
    keyboard.add(InlineKeyboardButton("📋 Все задачи", callback_data=menu_cd.new(level=2, menu_id=0, action="all_tasks")))
    keyboard.add(InlineKeyboardButton("📊 Общая статистика", callback_data=menu_cd.new(level=2, menu_id=0, action="global_stats")))
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data=menu_cd.new(level=1, menu_id=0, action="main_menu")))
    return keyboard

def make_task_list_keyboard(tasks, page=0, items_per_page=5):
    """Создание клавиатуры со списком задач пользователя"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    # Пагинация
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(tasks))
    
    # Добавляем кнопки для каждой задачи
    for i in range(start_idx, end_idx):
        task = tasks[i]
        status = "✅" if task['is_active'] else "⏸"
        task_name = f"{status} {task['name'][:30]}"
        keyboard.add(InlineKeyboardButton(
            task_name, 
            callback_data=task_cd.new(action="view", task_id=task['id'])
        ))
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️ Назад", 
            callback_data=menu_cd.new(level=1, menu_id=page-1, action="my_tasks_page")
        ))
    
    if end_idx < len(tasks):
        nav_buttons.append(InlineKeyboardButton(
            "➡️ Вперед", 
            callback_data=menu_cd.new(level=1, menu_id=page+1, action="my_tasks_page")
        ))
    
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    # Кнопка возврата в основное меню
    keyboard.add(InlineKeyboardButton("⬅️ В главное меню", callback_data=menu_cd.new(level=1, menu_id=0, action="main_menu")))
    
    return keyboard

def make_task_keyboard(task_id):
    """Создание клавиатуры для управления конкретной задачей"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    # Управление задачей
    keyboard.row(
        InlineKeyboardButton("▶️ Запустить", callback_data=task_cd.new(action="start", task_id=task_id)),
        InlineKeyboardButton("⏸ Остановить", callback_data=task_cd.new(action="stop", task_id=task_id))
    )
    
    keyboard.row(
        InlineKeyboardButton("✏️ Редактировать", callback_data=task_cd.new(action="edit", task_id=task_id)),
        InlineKeyboardButton("🗑️ Удалить", callback_data=task_cd.new(action="delete", task_id=task_id))
    )
    
    # Кнопка возврата к списку задач
    keyboard.add(InlineKeyboardButton("⬅️ К списку задач", callback_data=menu_cd.new(level=1, menu_id=0, action="my_tasks")))
    
    return keyboard

def make_user_management_keyboard(users, page=0, items_per_page=5):
    """Создание клавиатуры для управления пользователями (для админов)"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    # Пагинация
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(users))
    
    # Добавляем кнопки для каждого пользователя
    for i in range(start_idx, end_idx):
        user = users[i]
        status = "🟢" if user['is_active'] else "🔴"
        admin_badge = "👑 " if user['is_admin'] else ""
        user_text = f"{status} {admin_badge}{user['username'] or user['user_id']}"
        keyboard.add(InlineKeyboardButton(
            user_text, 
            callback_data=user_cd.new(action="manage", user_id=user['user_id'])
        ))
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️ Назад", 
            callback_data=menu_cd.new(level=2, menu_id=page-1, action="users_page")
        ))
    
    if end_idx < len(users):
        nav_buttons.append(InlineKeyboardButton(
            "➡️ Вперед", 
            callback_data=menu_cd.new(level=2, menu_id=page+1, action="users_page")
        ))
    
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    # Кнопка добавления нового пользователя
    keyboard.add(InlineKeyboardButton("➕ Добавить пользователя", callback_data=menu_cd.new(level=2, menu_id=0, action="add_user")))
    
    # Кнопка возврата в админ-панель
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data=menu_cd.new(level=1, menu_id=0, action="admin_panel")))
    
    return keyboard

def make_user_manage_keyboard(user_id):
    """Создание клавиатуры для управления конкретным пользователем"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    user = db.get_user(user_id)
    
    if user:
        # Обновление подписки
        keyboard.add(InlineKeyboardButton("⏱️ Изменить срок подписки", callback_data=user_cd.new(action="subscription", user_id=user_id)))
        
        # Переключение статуса админа
        admin_action = "remove_admin" if user.get('is_admin') else "make_admin"
        admin_text = "🔽 Удалить права админа" if user.get('is_admin') else "🔼 Сделать админом"
        keyboard.add(InlineKeyboardButton(admin_text, callback_data=user_cd.new(action=admin_action, user_id=user_id)))
        
        # Блокировка/разблокировка
        block_action = "block" if user.get('is_active') else "unblock"
        block_text = "🔒 Заблокировать" if user.get('is_active') else "🔓 Разблокировать"
        keyboard.add(InlineKeyboardButton(block_text, callback_data=user_cd.new(action=block_action, user_id=user_id)))
        
        # Просмотр задач пользователя
        keyboard.add(InlineKeyboardButton("📋 Задачи пользователя", callback_data=user_cd.new(action="tasks", user_id=user_id)))
    
    # Кнопка возврата к списку пользователей
    keyboard.add(InlineKeyboardButton("⬅️ К списку пользователей", callback_data=menu_cd.new(level=2, menu_id=0, action="manage_users")))
    
    return keyboard

def make_task_type_keyboard():
    """Создание клавиатуры для выбора типа задачи"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("📤 Отправка текста", callback_data="task_type:text"))
    keyboard.add(InlineKeyboardButton("↩️ Пересылка сообщения", callback_data="task_type:forward"))
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data=menu_cd.new(level=1, menu_id=0, action="main_menu")))
    return keyboard

def make_schedule_keyboard():
    """Создание клавиатуры для выбора типа расписания"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🕒 Отправить один раз", callback_data="schedule:once"))
    keyboard.add(InlineKeyboardButton("🔄 Отправлять по расписанию", callback_data="schedule:recurring"))
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data=menu_cd.new(level=1, menu_id=0, action="my_tasks")))
    return keyboard

def make_notifications_keyboard(user_id):
    """Создание клавиатуры для настройки уведомлений"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    user = db.get_user(user_id)
    success_notify = user.get('notify_success', True)
    error_notify = user.get('notify_error', True)
    
    success_text = "✅ Уведомления об успехе: ВКЛ" if success_notify else "⭕ Уведомления об успехе: ВЫКЛ"
    error_text = "⚠️ Уведомления об ошибках: ВКЛ" if error_notify else "⭕ Уведомления об ошибках: ВЫКЛ"
    
    keyboard.add(InlineKeyboardButton(success_text, callback_data="notify:success"))
    keyboard.add(InlineKeyboardButton(error_text, callback_data="notify:error"))
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data=menu_cd.new(level=1, menu_id=0, action="main_menu")))
    
    return keyboard

# Обработчики команд и коллбэков

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """Обработчик команды /start и /help"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Проверяем, есть ли пользователь в базе данных
    user = db.get_user(user_id)
    
    if not user:
        # Проверяем, является ли пользователь владельцем бота
        if user_id == OWNER_ID:
            db.add_user(user_id, username, is_admin=True)
            logger.info(f"Добавлен владелец бота: {user_id} ({username})")
            await message.answer(
                "👋 Добро пожаловать, владелец бота!\n\n"
                "🤖 Вы автоматически добавлены как администратор.\n"
                "Используйте меню ниже для управления ботом:"
            )
        else:
            # Проверяем, разрешен ли пользователь
            if not db.is_user_allowed(user_id):
                logger.info(f"Попытка доступа от неразрешенного пользователя: {user_id} ({username})")
                await message.answer(
                    "⛔ Доступ запрещен. Свяжитесь с администратором для получения доступа."
                )
                return
            
            # Добавляем нового пользователя
            db.add_user(user_id, username)
            logger.info(f"Добавлен новый пользователь: {user_id} ({username})")
            
            await message.answer(
                "👋 Добро пожаловать!\n\n"
                "🤖 Это бот для управления автопостингом в Telegram.\n"
                "Используйте меню ниже для работы с ботом:"
            )
    else:
        # Проверяем активность пользователя
        if not user.get('is_active'):
            await message.answer(
                "⛔ Ваш аккаунт заблокирован. "
                "Свяжитесь с администратором для получения доступа."
            )
            return
        
        # Приветствуем пользователя
        await message.answer(
            f"👋 С возвращением!\n\n"
            f"🤖 Используйте меню ниже для работы с ботом:"
        )
    
    # Проверяем подписку
    is_active, subscription_message = await has_active_subscription(user_id)
    if not is_active:
        await message.answer(subscription_message)
    
    # Отправка основного меню
    await message.answer(
        "Выберите действие:",
        reply_markup=make_main_keyboard(user_id)
    )

@dp.callback_query_handler(menu_cd.filter(action="main_menu"))
async def show_main_menu(callback: types.CallbackQuery, callback_data: dict):
    """Обработчик возврата в главное меню"""
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=make_main_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query_handler(menu_cd.filter(action="my_tasks"))
async def show_my_tasks(callback: types.CallbackQuery, callback_data: dict):
    """Обработчик показа списка задач пользователя"""
    user_id = callback.from_user.id
    
    # Проверяем подписку
    is_active, message = await has_active_subscription(user_id)
    if not is_active:
        await callback.message.edit_text(
            message + "\n\nВыберите действие:",
            reply_markup=make_main_keyboard(user_id)
        )
        await callback.answer("Подписка неактивна", show_alert=True)
        return
    
    # Получаем задачи пользователя
    tasks = db.get_user_tasks(user_id)
    
    if not tasks:
        await callback.message.edit_text(
            "📋 У вас пока нет задач.\n\n"
            "Нажмите кнопку «Добавить задачу», чтобы создать новую задачу.",
            reply_markup=make_main_keyboard(user_id)
        )
    else:
        await callback.message.edit_text(
            f"📋 Ваши задачи ({len(tasks)}):\n"
            f"✅ - активна, ⏸ - приостановлена\n\n"
            f"Выберите задачу для просмотра деталей:",
            reply_markup=make_task_list_keyboard(tasks)
        )
    
    await callback.answer()

@dp.callback_query_handler(menu_cd.filter(action="my_tasks_page"))
async def show_my_tasks_page(callback: types.CallbackQuery, callback_data: dict):
    """Обработчик пагинации по страницам задач"""
    user_id = callback.from_user.id
    page = int(callback_data.get("menu_id", 0))
    
    # Получаем задачи пользователя
    tasks = db.get_user_tasks(user_id)
    
    await callback.message.edit_text(
        f"📋 Ваши задачи ({len(tasks)}):\n"
        f"✅ - активна, ⏸ - приостановлена\n\n"
        f"Выберите задачу для просмотра деталей:",
        reply_markup=make_task_list_keyboard(tasks, page)
    )
    
    await callback.answer()

@dp.callback_query_handler(task_cd.filter(action="view"))
async def view_task(callback: types.CallbackQuery, callback_data: dict):
    """Обработчик просмотра деталей задачи"""
    user_id = callback.from_user.id
    task_id = int(callback_data.get("task_id"))
    
    # Получаем задачу
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != user_id:
        await callback.message.edit_text(
            "⚠️ Задача не найдена или у вас нет доступа к ней.",
            reply_markup=make_main_keyboard(user_id)
        )
        await callback.answer("Задача не найдена", show_alert=True)
        return
    
    # Формируем информацию о задаче
    status = "✅ Активна" if task['is_active'] else "⏸ Приостановлена"
    task_type = "Отправка текста" if task['task_type'] == 'text' else "Пересылка сообщения"
    
    # Получаем информацию о чате назначения
    chat_info = await userbot.get_chat_info(task['target_chat_id'])
    chat_name = chat_info.get('title', str(task['target_chat_id']))
    
    # Информация о топике, если есть
    topic_info = ""
    if task.get('topic_id'):
        topic = await userbot.get_topic_info(task['target_chat_id'], task['topic_id'])
        topic_info = f"\n📑 Топик: {topic.get('title', str(task['topic_id']))}"
    
    # Информация о расписании
    schedule_info = "⏰ Расписание: "
    if task['schedule_type'] == 'once':
        scheduled_time = datetime.datetime.fromisoformat(task['scheduled_time'])
        schedule_info += f"Однократно {scheduled_time.strftime('%d.%m.%Y %H:%M')}"
    else:
        schedule_info += f"Повторяющееся ({task['schedule_interval']})"
    
    # Информация о содержимом
    content_info = ""
    if task['task_type'] == 'text':
        text_preview = task['message_text'][:100] + "..." if len(task['message_text']) > 100 else task['message_text']
        content_info = f"📝 Текст: {text_preview}"
    else:
        content_info = f"↩️ Пересылка из: {task['source_chat_id']}, сообщение #{task['source_message_id']}"
    
    next_run = task.get('next_run')
    next_run_info = ""
    if next_run:
        next_run_time = datetime.datetime.fromisoformat(next_run)
        next_run_info = f"\n⏱️ Следующий запуск: {next_run_time.strftime('%d.%m.%Y %H:%M')}"
    
    # Информация о выполнениях
    execution_info = f"\n🔢 Выполнено отправок: {task.get('execution_count', 0)}"
    
    message_text = (
        f"📋 Задача #{task_id}\n\n"
        f"🔹 Название: {task['name']}\n"
        f"🔹 Статус: {status}\n"
        f"🔹 Тип: {task_type}\n"
        f"🔹 Чат назначения: {chat_name}{topic_info}\n"
        f"🔹 {schedule_info}{next_run_info}\n"
        f"🔹 {content_info}{execution_info}\n\n"
        f"Для управления задачей используйте кнопки ниже:"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=make_task_keyboard(task_id)
    )
    
    await callback.answer()

@dp.callback_query_handler(task_cd.filter(action="start"))
async def start_task(callback: types.CallbackQuery, callback_data: dict):
    """Обработчик запуска задачи"""
    user_id = callback.from_user.id
    task_id = int(callback_data.get("task_id"))
    
    # Проверяем подписку
    is_active, message = await has_active_subscription(user_id)
    if not is_active:
        await callback.answer("Подписка неактивна", show_alert=True)
        return
    
    # Получаем задачу
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != user_id:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    
    # Активируем задачу
    db.update_task_status(task_id, True)
    
    # Перезапускаем задачу в планировщике
    scheduler.restart_task(task_id)
    
    # Обновляем информацию о задаче
    await view_task(callback, {"task_id": task_id, "action": "view"})
    
    await callback.answer("✅ Задача запущена", show_alert=True)

@dp.callback_query_handler(task_cd.filter(action="stop"))
async def stop_task(callback: types.CallbackQuery, callback_data: dict):
    """Обработчик остановки задачи"""
    user_id = callback.from_user.id
    task_id = int(callback_data.get("task_id"))
    
    # Получаем задачу
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != user_id:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    
    # Деактивируем задачу
    db.update_task_status(task_id, False)
    
    # Останавливаем задачу в планировщике
    scheduler.stop_task(task_id)
    
    # Обновляем информацию о задаче
    await view_task(callback, {"task_id": task_id, "action": "view"})
    
    await callback.answer("⏸ Задача остановлена", show_alert=True)

@dp.callback_query_handler(task_cd.filter(action="delete"))
async def delete_task_confirm(callback: types.CallbackQuery, callback_data: dict):
    """Подтверждение удаления задачи"""
    user_id = callback.from_user.id
    task_id = int(callback_data.get("task_id"))
    
    # Получаем задачу
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != user_id:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    
    # Создаем клавиатуру для подтверждения
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete:{task_id}"),
        InlineKeyboardButton("❌ Отмена", callback_data=task_cd.new(action="view", task_id=task_id))
    )
    
    await callback.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить задачу #{task_id}?\n\n"
        f"Название: {task['name']}\n\n"
        f"Это действие невозможно отменить.",
        reply_markup=keyboard
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(startswith="confirm_delete:"))
async def delete_task(callback: types.CallbackQuery):
    """Обработчик удаления задачи после подтверждения"""
    user_id = callback.from_user.id
    task_id = int(callback.data.split(":")[1])
    
    # Получаем задачу
    task = db.get_task(task_id)
    
    if not task or task['user_id'] != user_id:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    
    # Останавливаем задачу в планировщике
    scheduler.remove_task(task_id)
    
    # Удаляем задачу из базы данных
    db.delete_task(task_id)
    
    logger.info(f"Задача #{task_id} удалена пользователем {user_id}")
    
    # Возвращаемся к списку задач
    await show_my_tasks(callback, {})
    
    await callback.answer("✅ Задача успешно удалена", show_alert=True)

@dp.callback_query_handler(menu_cd.filter(action="add_task"))
async def add_task_start(callback: types.CallbackQuery):
    """Обработчик начала создания задачи"""
    user_id = callback.from_user.id
    
    # Проверяем подписку
    is_active, message = await has_active_subscription(user_id)
    if not is_active:
        await callback.message.edit_text(
            message + "\n\nВыберите действие:",
            reply_markup=make_main_keyboard(user_id)
        )
        await callback.answer("Подписка неактивна", show_alert=True)
        return
    
    # Переходим в состояние выбора типа задачи
    await TaskStates.choosing_task_type.set()
    
    await callback.message.edit_text(
        "📝 Создание новой задачи\n\n"
        "Выберите тип задачи:",
        reply_markup=make_task_type_keyboard()
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(startswith="task_type:"), state=TaskStates.choosing_task_type)
async def process_task_type(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора типа задачи"""
    task_type = callback.data.split(":")[1]
    
    # Сохраняем тип задачи в FSM
    await state.update_data(task_type=task_type)
    
    if task_type == "text":
        # Запрашиваем текст сообщения
        await TaskStates.entering_message_text.set()
        
        # Создаем клавиатуру с кнопкой отмены
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
        
        await callback.message.edit_text(
            "📝 Введите текст сообщения, которое нужно отправить.\n\n"
            "Поддерживается форматирование Markdown:\n"
            "**жирный** - окружите текст двумя звездочками\n"
            "*курсив* - окружите текст одной звездочкой\n"
            "[ссылка](URL) - указывайте ссылки в таком формате",
            reply_markup=keyboard
        )
    elif task_type == "forward":
        # Переходим к выбору исходного чата
        await TaskStates.choosing_source_chat.set()
        
        # Получаем список доступных чатов
        chats = await userbot.get_dialogs()
        
        # Создаем клавиатуру с чатами
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        for chat in chats[:10]:  # Ограничиваем до 10 чатов
            keyboard.add(InlineKeyboardButton(
                chat['title'], 
                callback_data=f"source_chat:{chat['id']}"
            ))
        
        keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
        
        await callback.message.edit_text(
            "🔍 Выберите чат, из которого нужно переслать сообщение:",
            reply_markup=keyboard
        )
    
    await callback.answer()

@dp.message_handler(state=TaskStates.entering_message_text)
async def process_message_text(message: types.Message, state: FSMContext):
    """Обработчик ввода текста сообщения"""
    # Сохраняем текст сообщения в FSM
    await state.update_data(message_text=message.text, name=message.text[:30]+"...")
    
    # Удаляем предыдущее сообщение с инструкциями
    try:
        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id - 1
        )
    except Exception:
        pass
    
    # Переходим к выбору целевого чата
    await TaskStates.choosing_target_chat.set()
    
    # Получаем список доступных чатов
    chats = await userbot.get_dialogs()
    
    # Создаем клавиатуру с чатами
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for chat in chats[:10]:  # Ограничиваем до 10 чатов
        if chat['can_post']:  # Проверяем, можно ли отправлять сообщения
            keyboard.add(InlineKeyboardButton(
                chat['title'], 
                callback_data=f"target_chat:{chat['id']}"
            ))
    
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
    
    await message.answer(
        "🔍 Выберите чат, куда нужно отправить сообщение:",
        reply_markup=keyboard
    )

@dp.callback_query_handler(Text(startswith="source_chat:"), state=TaskStates.choosing_source_chat)
async def process_source_chat(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора исходного чата для пересылки"""
    chat_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID чата в FSM
    await state.update_data(source_chat_id=chat_id)
    
    # Получаем последние сообщения из выбранного чата
    messages = await userbot.get_chat_messages(chat_id, limit=10)
    
    # Создаем клавиатуру с сообщениями
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for msg in messages:
        # Ограничиваем длину текста для отображения
        text = msg.get('text', 'Медиа')[:30] + "..." if len(msg.get('text', 'Медиа')) > 30 else msg.get('text', 'Медиа')
        keyboard.add(InlineKeyboardButton(
            f"ID: {msg['id']} - {text}", 
            callback_data=f"source_message:{msg['id']}"
        ))
    
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_source_chat"))
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
    
    # Переходим к выбору сообщения
    await TaskStates.choosing_source_message.set()
    
    await callback.message.edit_text(
        "🔍 Выберите сообщение для пересылки:",
        reply_markup=keyboard
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(startswith="source_message:"), state=TaskStates.choosing_source_message)
async def process_source_message(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора сообщения для пересылки"""
    message_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID сообщения в FSM
    await state.update_data(source_message_id=message_id)
    
    # Получаем сообщение для превью
    state_data = await state.get_data()
    source_chat_id = state_data.get('source_chat_id')
    message = await userbot.get_message(source_chat_id, message_id)
    
    # Сохраняем название задачи (краткое описание сообщения)
    msg_text = message.get('text', 'Медиа')
    task_name = msg_text[:30] + "..." if len(msg_text) > 30 else msg_text
    await state.update_data(name=task_name)
    
    # Переходим к выбору целевого чата
    await TaskStates.choosing_target_chat.set()
    
    # Получаем список доступных чатов
    chats = await userbot.get_dialogs()
    
    # Создаем клавиатуру с чатами
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for chat in chats[:10]:  # Ограничиваем до 10 чатов
        if chat['can_post']:  # Проверяем, можно ли отправлять сообщения
            keyboard.add(InlineKeyboardButton(
                chat['title'], 
                callback_data=f"target_chat:{chat['id']}"
            ))
    
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_source_message"))
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
    
    await callback.message.edit_text(
        "🔍 Выберите чат, куда нужно переслать сообщение:",
        reply_markup=keyboard
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(startswith="target_chat:"), state=[TaskStates.choosing_target_chat])
async def process_target_chat(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора целевого чата"""
    chat_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID чата в FSM
    await state.update_data(target_chat_id=chat_id)
    
    # Проверяем, есть ли топики в чате
    has_topics = await userbot.chat_has_topics(chat_id)
    
    if has_topics:
        # Если есть топики, переходим к выбору топика
        await TaskStates.choosing_topic.set()
        
        # Получаем список топиков
        topics = await userbot.get_topics(chat_id)
        
        # Создаем клавиатуру с топиками
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        # Опция "Без топика" (основной чат)
        keyboard.add(InlineKeyboardButton(
            "🌐 Основной чат (без топика)", 
            callback_data="topic:0"
        ))
        
        for topic in topics:
            keyboard.add(InlineKeyboardButton(
                topic['title'], 
                callback_data=f"topic:{topic['id']}"
            ))
        
        keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_target_chat"))
        keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
        
        await callback.message.edit_text(
            "🔍 Выберите топик, куда нужно отправить сообщение:",
            reply_markup=keyboard
        )
    else:
        # Если нет топиков, переходим к настройке расписания
        await TaskStates.choosing_schedule.set()
        
        await callback.message.edit_text(
            "⏰ Выберите тип расписания:",
            reply_markup=make_schedule_keyboard()
        )
    
    await callback.answer()

@dp.callback_query_handler(Text(startswith="topic:"), state=TaskStates.choosing_topic)
async def process_topic(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора топика"""
    topic_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID топика в FSM (0 означает без топика)
    await state.update_data(topic_id=topic_id if topic_id > 0 else None)
    
    # Переходим к настройке расписания
    await TaskStates.choosing_schedule.set()
    
    await callback.message.edit_text(
        "⏰ Выберите тип расписания:",
        reply_markup=make_schedule_keyboard()
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(startswith="schedule:"), state=TaskStates.choosing_schedule)
async def process_schedule_type(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора типа расписания"""
    schedule_type = callback.data.split(":")[1]
    
    # Сохраняем тип расписания в FSM
    await state.update_data(schedule_type=schedule_type)
    
    # Создаем клавиатуру для отмены
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
    
    if schedule_type == "once":
        await callback.message.edit_text(
            "⏰ Введите дату и время для отправки в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: 15.06.2025 14:30",
            reply_markup=keyboard
        )
    elif schedule_type == "recurring":
        await callback.message.edit_text(
            "⏰ Введите интервал в формате:\n\n"
            "- Для минут: 10m (каждые 10 минут)\n"
            "- Для часов: 2h (каждые 2 часа)\n"
            "- Для дней: 1d (каждый день)\n"
            "- Для недель: 1w (каждую неделю)\n\n"
            "Например: 30m для отправки каждые 30 минут",
            reply_markup=keyboard
        )
    
    await callback.answer()

@dp.message_handler(state=TaskStates.choosing_schedule)
async def process_schedule_input(message: types.Message, state: FSMContext):
    """Обработчик ввода параметров расписания"""
    state_data = await state.get_data()
    schedule_type = state_data.get('schedule_type')
    
    # Удаляем предыдущее сообщение с инструкциями
    try:
        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id - 1
        )
    except Exception:
        pass
    
    if schedule_type == "once":
        # Парсим дату и время
        try:
            scheduled_time = datetime.datetime.strptime(message.text, "%d.%m.%Y %H:%M")
            
            # Проверяем, что дата в будущем
            if scheduled_time <= datetime.datetime.now():
                await message.answer(
                    "⚠️ Дата должна быть в будущем. Пожалуйста, введите корректную дату и время."
                )
                return
            
            # Сохраняем время в ISO формате
            await state.update_data(scheduled_time=scheduled_time.isoformat())
            await state.update_data(schedule_interval=None)
        except ValueError:
            await message.answer(
                "⚠️ Неверный формат даты. Пожалуйста, используйте формат ДД.ММ.ГГГГ ЧЧ:ММ"
            )
            return
    elif schedule_type == "recurring":
        # Парсим интервал
        interval_text = message.text.strip().lower()
        
        # Проверяем формат интервала
        if not (interval_text[-1] in "mhdw" and interval_text[:-1].isdigit()):
            await message.answer(
                "⚠️ Неверный формат интервала. Пожалуйста, используйте формат: "
                "число + буква (m, h, d, w). Например: 30m"
            )
            return
        
        # Сохраняем интервал
        await state.update_data(schedule_interval=interval_text)
        await state.update_data(scheduled_time=datetime.datetime.now().isoformat())
    
    # Завершаем создание задачи
    await create_task(message, state)

async def create_task(message: types.Message, state: FSMContext):
    """Функция создания задачи"""
    state_data = await state.get_data()
    user_id = message.from_user.id
    
    try:
        # Создаем задачу в базе данных
        task_id = db.create_task(
            user_id=user_id,
            name=state_data.get('name', 'Новая задача'),
            task_type=state_data.get('task_type'),
            source_chat_id=state_data.get('source_chat_id'),
            source_message_id=state_data.get('source_message_id'),
            target_chat_id=state_data.get('target_chat_id'),
            topic_id=state_data.get('topic_id'),
            message_text=state_data.get('message_text'),
            schedule_type=state_data.get('schedule_type'),
            scheduled_time=state_data.get('scheduled_time'),
            schedule_interval=state_data.get('schedule_interval'),
            is_active=True
        )
        
        # Добавляем задачу в планировщик
        scheduler.add_task(db.get_task(task_id))
        
        logger.info(f"Создана новая задача #{task_id} пользователем {user_id}")
        
        # Очищаем состояние FSM
        await state.finish()
        
        # Отправляем сообщение об успехе
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(InlineKeyboardButton("📋 К списку задач", callback_data=menu_cd.new(level=1, menu_id=0, action="my_tasks")))
        keyboard.add(InlineKeyboardButton("🏠 В главное меню", callback_data=menu_cd.new(level=1, menu_id=0, action="main_menu")))
        
        await message.answer(
            f"✅ Задача #{task_id} успешно создана!\n\n"
            f"Вы можете управлять ей в разделе «Мои задачи».",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка создания задачи: {e}")
        await message.answer(
            f"⚠️ Произошла ошибка при создании задачи: {str(e)}\n\n"
            f"Пожалуйста, попробуйте еще раз."
        )
        
        # Очищаем состояние FSM
        await state.finish()
        
        # Отправляем основное меню
        await message.answer(
            "Выберите действие:",
            reply_markup=make_main_keyboard(user_id)
        )

@dp.callback_query_handler(Text(equals="cancel_task"), state="*")
async def cancel_task_creation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик отмены создания задачи"""
    # Очищаем состояние FSM
    await state.finish()
    
    # Возвращаемся в главное меню
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "❌ Создание задачи отменено.\n\n"
        "Выберите действие:",
        reply_markup=make_main_keyboard(user_id)
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(equals="back_to_source_chat"), state=TaskStates.choosing_source_message)
async def back_to_source_chat(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик возврата к выбору исходного чата"""
    # Переходим обратно к выбору исходного чата
    await TaskStates.choosing_source_chat.set()
    
    # Получаем список доступных чатов
    chats = await userbot.get_dialogs()
    
    # Создаем клавиатуру с чатами
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for chat in chats[:10]:  # Ограничиваем до 10 чатов
        keyboard.add(InlineKeyboardButton(
            chat['title'], 
            callback_data=f"source_chat:{chat['id']}"
        ))
    
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
    
    await callback.message.edit_text(
        "🔍 Выберите чат, из которого нужно переслать сообщение:",
        reply_markup=keyboard
    )
    
    await callback.answer()

@dp.callback_query_handler(Text(equals="back_to_source_message"), state=TaskStates.choosing_target_chat)
async def back_to_source_message(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик возврата к выбору исходного сообщения"""
    # Получаем данные из FSM
    state_data = await state.get_data()
    source_chat_id = state_data.get('source_chat_id')
    
    # Переходим обратно к выбору сообщения
    await TaskStates.choosing_source_message.set()
    
    # Получаем последние сообщения из выбранного чата
    messages = await userbot.get_chat_messages(source_chat_id, limit=10)
    
    # Создаем клавиатуру с сообщениями
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for msg in messages:
        # Ограничиваем длину текста для отображения
        text = msg.get('text', 'Медиа')[:30] + "..." if len(msg.get('text', 'Медиа')) > 30 else msg.get('text', 'Медиа')
        keyboard.add(InlineKeyboardButton(
            f"ID: {msg['id']} - {text}", 
            callback_data=f"source_message:{msg['id']}"
        ))
    
    keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_source_chat"))
    keyboard.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_task"))
    
    await callback.message.edit_text(
        "🔍 Выберите сообщение для пересылки:",
        reply_markup=keyboard
    )
    
    await callback.answer()

", callback_data="cancel_task"))
    
    await callback.message.edit_text(
        "🔍 Выберите чат, куда нужно отправить сообщение:",
        reply_markup=keyboard
    )
    
    await callback.answer()