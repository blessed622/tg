from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database import Database
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from config import OWNER_ID
from datetime import datetime

router = Router()
db = Database()
logger = logging.getLogger(__name__)


class TaskStates(StatesGroup):
    waiting_for_chat = State()
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
        "<b>Примеры расписаний:</b>\n"
        "• <code>hour=12;minute=0</code> - каждый день в 12:00\n"
        "• <code>day_of_week=1,3,5;hour=15;minute=30</code> - каждый вторник, четверг и субботу в 15:30\n"
        "• <code>minute=*/30</code> - каждые 30 минут\n"
        "• <code>hour=*/2;minute=0</code> - каждые 2 часа\n\n"
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
    user_id = message.from_user.id
    tasks = db.get_user_tasks(user_id)

    if not tasks:
        await message.answer("У вас пока нет созданных задач. Нажмите '➕ Создать задачу' чтобы начать.")
        return

    text = "📋 <b>Ваши активные задачи:</b>\n\n"

    for i, task in enumerate(tasks, 1):
        text += (
            f"<b>{i}. Задача #{task[0]}</b>\n"
            f"Чат: <code>{task[2]}</code>\n"
            f"Расписание: <code>{task[6]}</code>\n"
            f"Статус: {'✅ Активна' if task[7] else '❌ Отключена'}\n\n"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать задачу", callback_data="create_task")],
            [InlineKeyboardButton(text="⚙️ Управление задачами", callback_data="manage_tasks")]
        ]
    )

    await message.answer(text, reply_markup=keyboard)


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

    task_info = (
        f"<b>Задача #{task[0]}</b>\n\n"
        f"Чат: <code>{task[2]}</code>\n"
        f"Сообщение: <code>{task[4][:50]}...</code>\n"
        f"Расписание: <code>{task[6]}</code>\n"
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
        # Здесь нужно будет обновить задачу в планировщике
        await callback.answer("✅ Статус задачи обновлен")
        await task_actions(callback)
    else:
        await callback.answer("❌ Ошибка обновления статуса")


@router.callback_query(F.data.startswith("delete_"))
async def delete_task(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[1])

    if db.delete_task(task_id):
        # Здесь нужно будет удалить задачу из планировщика
        await callback.message.edit_text("✅ Задача успешно удалена")
    else:
        await callback.answer("❌ Ошибка удаления задачи")


@router.callback_query(F.data == "back_to_tasks")
async def back_to_tasks(callback: types.CallbackQuery):
    message = callback.message
    await message.delete()
    await my_tasks_command(message)


@router.message(F.text == "➕ Создать задачу")
@router.callback_query(F.data == "create_task")
async def create_task_start(message_or_callback):
    is_callback = isinstance(message_or_callback, types.CallbackQuery)

    if is_callback:
        callback = message_or_callback
        user_id = callback.from_user.id
        message = callback.message
        await callback.answer()
    else:
        message = message_or_callback
        user_id = message.from_user.id

    # Проверяем подписку
    if not db.check_subscription(user_id) and user_id != OWNER_ID:
        text = "❌ Для создания задач необходима активная подписка"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy_subscription")]]
        )

        if is_callback:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)
        return

    instruction_text = (
        "📝 <b>Создание новой задачи</b>\n\n"
        "Для начала, укажите ID чата, куда будут отправляться сообщения.\n\n"
        "<i>Это может быть:\n"
        "• ID публичного канала или группы (например, -1001234567890)\n"
        "• Username канала или группы (например, @mychannel)</i>"
    )

    if is_callback:
        await message.edit_text(
            instruction_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
            )
        )
    else:
        await message.answer(
            instruction_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task_creation")]]
            )
        )

    # Устанавливаем состояние FSM
    state = FSMContext(user_id) if 'state' in globals() else None
    if state:
        await state.set_state(TaskStates.waiting_for_chat)


@router.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url="https://t.me/your_payment_bot")],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
        ]
    )

    await callback.message.edit_text(
        "💳 <b>Тарифы</b>\n\n"
        "• 1 месяц - 500 руб.\n"
        "• 3 месяца - 1200 руб.\n"
        "• 6 месяцев - 2000 руб.\n\n"
        "Для оплаты перейдите по ссылке ниже:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery):
    await callback.message.delete()
    await profile_command(callback.message)
    await callback.answer()


@router.callback_query(F.data == "cancel_task_creation")
async def cancel_task_creation(callback: types.CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()

    await callback.message.edit_text("❌ Создание задачи отменено")
    await callback.answer()