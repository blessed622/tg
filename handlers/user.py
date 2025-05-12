from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database import Database
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from config import OWNER_ID
from datetime import datetime
from scheduler import add_to_scheduler
from telethon import TelegramClient
from config import API_ID, API_HASH, USERBOT_SESSION

router = Router()
db = Database()
logger = logging.getLogger(__name__)


class TaskStates(StatesGroup):
    waiting_for_chat = State()
    waiting_for_thread = State()
    waiting_for_text = State()
    waiting_for_schedule = State()


@router.message(Command("start"))
async def start_command(message: types.Message):
    user = message.from_user
    db.add_user(user.id, user.username, user.full_name)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои задачи"), KeyboardButton(text="➕ Создать задачу")],
            [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="👤 Профиль")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для автоматической отправки сообщений в Telegram.\n"
        "Используй меня для настройки регулярных публикаций в каналах и группах.",
        reply_markup=keyboard
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def help_command(message: types.Message):
    help_text = (
        "📚 <b>Возможности бота:</b>\n\n"
        "➕ <b>Создать задачу</b> - настроить автоматическую отправку сообщений\n"
        "📋 <b>Мои задачи</b> - просмотр и управление вашими текущими задачами\n"
        "👤 <b>Профиль</b> - информация о вашей подписке\n\n"
        "Для создания задачи просто нажмите на кнопку <b>➕ Создать задачу</b> и следуйте инструкциям."
    )
    await message.answer(help_text)


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def profile_command(message: types.Message):
    user_id = message.from_user.id
    user_info = db.get_user(user_id)

    if user_info:
        is_subscribed = db.check_subscription(user_id)

        if is_subscribed:
            subscription_end = datetime.strptime(user_info[4], "%Y-%m-%d").strftime("%d.%m.%Y")
            status_text = f"✅ Активна до {subscription_end}"
        else:
            status_text = "❌ Нет активной подписки"

        profile_text = (
            f"👤 <b>Профиль</b>\n\n"
            f"ID: <code>{user_id}</code>\n"
            f"Имя: {user_info[2]}\n"
            f"Подписка: {status_text}\n\n"
            f"Активных задач: {len(db.get_user_tasks(user_id))}"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy_subscription")]
            ]
        )

        await message.answer(profile_text, reply_markup=keyboard)
    else:
        await message.answer("❌ Пользователь не найден")


@router.message(F.text == "📋 Мои задачи")
@router.message(Command("tasks"))
async def my_tasks_command(message: types.Message):
    user_id = message.chat.id
    tasks = db.get_user_tasks(user_id)

    if not tasks:
        await message.answer("У вас пока нет созданных задач. Нажмите '➕ Создать задачу' чтобы начать.")
        return

    text = "📋 <b>Ваши активные задачи:</b>\n\n"

    for i, task in enumerate(tasks, 1):
        # Отображаем интервал в более понятном формате
        interval_seconds = int(task[6])
        interval_text = format_interval(interval_seconds)

        text += (
            f"<b>{i}. Задача #{task[0]}</b>\n"
            f"Чат: <code>{task[2]}</code>\n"
            f"Интервал: {interval_text}\n"
            f"Статус: {'✅ Активна' if task[7] else '❌ Отключена'}\n\n"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать задачу", callback_data="create_task")],
            [InlineKeyboardButton(text="⚙️ Управление задачами", callback_data="manage_tasks")]
        ]
    )

    await message.answer(text, reply_markup=keyboard)


def format_interval(seconds):
    """Форматирует интервал в секундах в более читаемый вид"""
    if seconds < 60:
        return f"{seconds} секунд"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} {'минуту' if minutes == 1 else 'минут' if 2 <= minutes <= 4 else 'минут'}"
    else:
        hours = seconds // 3600
        return f"{hours} {'час' if hours == 1 else 'часа' if 2 <= hours <= 4 else 'часов'}"


@router.callback_query(F.data == "manage_tasks")
async def manage_tasks(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    tasks = db.get_user_tasks(user_id)

    if not tasks:
        await callback.message.edit_text("У вас нет активных задач.")
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for task in tasks:
        status = "✅" if task[7] else "❌"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{status} Задача #{task[0]}",
                callback_data=f"task_{task[0]}"
            )
        ])

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="« Назад", callback_data="back_to_tasks")
    ])

    await callback.message.edit_text("⚙️ Выберите задачу для управления:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("task_"))
async def task_actions(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    task = db.get_task(task_id)

    if not task:
        await callback.message.edit_text("❌ Задача не найдена")
        await callback.answer()
        return

    interval_seconds = int(task[6])
    interval_text = format_interval(interval_seconds)

    task_info = (
        f"<b>Задача #{task[0]}</b>\n\n"
        f"Чат: <code>{task[2]}</code>\n"
        f"Сообщение: <code>{task[4][:50]}...</code>\n"
        f"Интервал: {interval_text}\n"
        f"Статус: {'✅ Активна' if task[7] else '❌ Отключена'}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Включить" if not task[7] else "❌ Отключить",
                    callback_data=f"toggle_{task[0]}"
                )
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{task[0]}")],
            [InlineKeyboardButton(text="« Назад", callback_data="manage_tasks")]
        ]
    )

    await callback.message.edit_text(task_info, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_"))
async def toggle_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    task = db.get_task(task_id)

    if not task:
        await callback.message.edit_text("❌ Задача не найдена")
        await callback.answer()
        return

    new_status = not task[7]
    if db.update_task_status(task_id, new_status):
        # Обновляем задачу в планировщике
        await callback.answer("✅ Статус задачи обновлен")
        await task_actions(callback)
    else:
        await callback.answer("❌ Ошибка обновления статуса")


@router.callback_query(F.data.startswith("delete_"))
async def delete_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[1])

    if db.delete_task(task_id):
        # Удаляем задачу из планировщика
        await callback.message.edit_text("✅ Задача успешно удалена")
    else:
        await callback.answer("❌ Ошибка удаления задачи")


@router.callback_query(F.data == "back_to_tasks")
async def back_to_tasks(callback: types.CallbackQuery):
    message = callback.message
    await message.delete()
    await my_tasks_command(message)


# Функция для получения списка доступных топиков в чате
async def get_forum_topics(chat_id):
    try:
        client = TelegramClient(USERBOT_SESSION, API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            logger.error("Client is not authorized")
            await client.disconnect()
            return []

        # Преобразуем chat_id в числовой формат, если это не username
        try:
            if not str(chat_id).startswith('@'):
                chat_id = int(chat_id)
        except (ValueError, TypeError):
            pass  # Оставляем как есть, если не удается преобразовать

        # Получаем информацию о чате
        chat_entity = await client.get_entity(chat_id)

        # Проверяем, является ли чат форумом
        if not hasattr(chat_entity, 'forum') or not chat_entity.forum:
            logger.info(f"Chat {chat_id} is not a forum")
            await client.disconnect()
            return []  # Это не форум

        # Получаем топики форума
        topics = await client.get_topics(chat_entity)

        result = []
        for topic in topics:
            if hasattr(topic, 'title') and hasattr(topic, 'id'):
                result.append({
                    'id': topic.id,
                    'title': topic.title
                })

        await client.disconnect()
        logger.info(f"Found {len(result)} topics in chat {chat_id}")
        return result
    except Exception as e:
        logger.error(f"Error getting forum topics: {e}")
        if 'client' in locals() and client:
            await client.disconnect()
        return []


@router.message(F.text == "➕ Создать задачу")
async def create_task_cmd(message: types.Message, state: FSMContext):
    await create_task_start(message, state)


@router.callback_query(F.data == "create_task")
async def create_task_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await create_task_start(callback.message, state)


async def create_task_start(message: types.Message, state: FSMContext):
    """Начало создания задачи"""
    user_id = message.chat.id

    # Проверяем подписку
    if not db.check_subscription(user_id) and user_id != OWNER_ID:
        text = "❌ Для создания задач необходима активная подписка"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy_subscription")]]
        )
        await message.answer(text, reply_markup=keyboard)
        return

    instruction_text = (
        "📝 <b>Создание новой задачи</b>\n\n"
        "Для начала, укажите ID чата, куда будут отправляться сообщения.\n\n"
        "<i>Это может быть:\n"
        "• ID публичного канала или группы (например, -1001234567890)\n"
        "• Username канала или группы (например, @mychannel)</i>"
    )

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
    )

    await message.answer(instruction_text, reply_markup=cancel_kb)
    # Устанавливаем состояние FSM
    await state.set_state(TaskStates.waiting_for_chat)


# Обработчик для получения ID чата
@router.message(TaskStates.waiting_for_chat)
async def process_chat_id(message: types.Message, state: FSMContext):
    chat_id = message.text.strip()

    # Сохраняем ID чата в данных состояния
    await state.update_data(chat_id=chat_id)

    # Отправляем сообщение о проверке чата
    wait_message = await message.answer("⏳ Проверяю чат и ищу доступные топики...")

    # Проверяем наличие топиков в чате
    topics = await get_forum_topics(chat_id)

    # Удаляем сообщение о ожидании
    await wait_message.delete()

    if topics:
        # Если это форум, предлагаем выбрать топик
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        for topic in topics[:10]:  # Ограничиваем показ первых 10 топиков
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=topic['title'],
                    callback_data=f"topic_{topic['id']}"
                )
            ])

        # Добавляем кнопку "Отправлять в основной канал"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="📢 Отправлять в основной канал", callback_data="topic_main")
        ])

        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")
        ])

        await message.answer("Выберите топик для отправки сообщений:", reply_markup=keyboard)
        await state.set_state(TaskStates.waiting_for_thread)
    else:
        # Если нет топиков, сразу переходим к вводу текста
        await state.update_data(thread_id=None)  # Устанавливаем thread_id в None

        await message.answer(
            "Теперь введите текст сообщения, которое нужно отправлять:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
            )
        )
        await state.set_state(TaskStates.waiting_for_text)


# Обработчик для выбора топика
@router.callback_query(F.data.startswith("topic_"))
async def process_topic_selection(callback: types.CallbackQuery, state: FSMContext):
    topic_id_str = callback.data.split("_")[1]

    if topic_id_str == "main":
        # Если выбран основной канал, устанавливаем thread_id в None
        await state.update_data(thread_id=None)
    else:
        # Иначе устанавливаем ID топика
        topic_id = int(topic_id_str)
        await state.update_data(thread_id=topic_id)

    await callback.message.edit_text(
        "Теперь введите текст сообщения, которое нужно отправлять:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
        )
    )

    await state.set_state(TaskStates.waiting_for_text)
    await callback.answer()


# Обработчик для получения текста сообщения
@router.message(TaskStates.waiting_for_text)
async def process_message_text(message: types.Message, state: FSMContext):
    # Сохраняем текст сообщения
    await state.update_data(message_text=message.text)

    schedule_info = (
        "Введите интервал отправки сообщений в секундах:\n\n"
        "Примеры:\n"
        "• 20 - минимально возможный интервал (каждые 20 секунд)\n"
        "• 60 - каждую минуту\n"
        "• 300 - каждые 5 минут\n"
        "• 600 - каждые 10 минут\n"
        "• 1800 - каждые 30 минут (максимальный интервал)\n\n"
        "<i>Интервал должен быть от 20 до 1800 секунд</i>"
    )

    await message.answer(
        schedule_info,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
        )
    )

    # Переходим к следующему состоянию
    await state.set_state(TaskStates.waiting_for_schedule)


# Обработчик для получения интервала и завершения создания задачи
@router.message(TaskStates.waiting_for_schedule)
async def process_schedule(message: types.Message, state: FSMContext):
    try:
        interval_seconds = int(message.text.strip())

        # Проверка на соответствие ограничениям интервала
        MIN_INTERVAL = 20  # минимум 20 секунд
        MAX_INTERVAL = 1801  # максимум ~30 минут

        if interval_seconds < MIN_INTERVAL:
            await message.answer(f"❌ Интервал должен быть не менее {MIN_INTERVAL} секунд")
            return
        elif interval_seconds > MAX_INTERVAL:
            await message.answer(f"❌ Интервал должен быть не более {MAX_INTERVAL} секунд (примерно 30 минут)")
            return

    except ValueError:
        await message.answer("❌ Пожалуйста, введите число (количество секунд)")
        return

    user_data = await state.get_data()
    user_id = message.from_user.id

    # Получаем все данные для создания задачи
    chat_id = user_data.get('chat_id')
    thread_id = user_data.get('thread_id')  # Может быть None
    message_text = user_data.get('message_text')

    # Отправляем сообщение о создании задачи
    wait_message = await message.answer("⏳ Создаю задачу...")

    # Создаем задачу в базе данных
    try:
        # Сохраняем интервал в секундах как строку
        task_id = db.add_task(user_id, chat_id, thread_id, message_text, None, str(interval_seconds))

        # Добавляем задачу в планировщик
        success = await add_to_scheduler(task_id)

        # Удаляем сообщение об ожидании
        await wait_message.delete()

        if success:
            interval_text = format_interval(interval_seconds)
            thread_info = f", топик ID: {thread_id}" if thread_id else ""

            # Укорачиваем длинное сообщение для показа
            message_preview = message_text[:50] + "..." if len(message_text) > 50 else message_text

            await message.answer(
                f"✅ Задача #{task_id} успешно создана!\n\n"
                f"Чат: {chat_id}{thread_info}\n"
                f"Интервал: {interval_text}\n"
                f"Текст: {message_preview}"
            )
        else:
            await message.answer(
                "⚠️ Задача создана, но возникла проблема с планировщиком. "
                "Задача может не выполняться по расписанию."
            )
    except Exception as e:
        logger.error(f"Ошибка при создании задачи: {e}")
        await message.answer(f"❌ Ошибка при создании задачи: {str(e)}")

    # Очищаем состояние FSM
    await state.clear()


@router.callback_query(F.data == "cancel_task_creation")
async def cancel_task_creation(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание задачи отменено")
    await callback.answer()


@router.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url="https://t.me/lovelymaxing")],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
        ]
    )

    await callback.message.edit_text(
        "💳 <b>Тарифы</b>\n\n"
        "• 7 дней - 99 руб.\n"
        "• 14 дней - 169 руб.\n"
        "• 1 месяц - 299 руб.\n"
        "• 3 месяца - 799 руб.\n"
        "• 6 месяцев - 1599 руб.\n\n"
        "Для оплаты перейдите по ссылке ниже:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery):
    await callback.message.delete()
    await profile_command(callback.message)