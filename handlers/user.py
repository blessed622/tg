from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import Database
from config import OWNER_ID

router = Router()
db = Database()


# Keyboards
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📌 Мои задачи"), KeyboardButton(text="➕ Добавить задачу")],
            [KeyboardButton(text="📅 Подписка"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="📊 Статистика")]
        ],
        resize_keyboard=True
    )


def get_task_type_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Текст", callback_data="task_type_text")],
            [InlineKeyboardButton(text="🔄 Переслать", callback_data="task_type_forward")]
        ]
    )


# States
class TaskStates(StatesGroup):
    waiting_for_content = State()
    waiting_for_chat = State()
    waiting_for_schedule = State()


# Handlers
@router.message(Command("start", "menu"))
async def cmd_start(message: types.Message):
    user = db.get_user(message.from_user.id)
    if not user:
        db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    if message.from_user.id == OWNER_ID:
        await message.answer("👑 Привет, владелец!", reply_markup=get_main_menu())
    else:
        await message.answer("👤 Добро пожаловать в ваш личный кабинет!", reply_markup=get_main_menu())


@router.message(F.text == "📌 Мои задачи")
async def show_user_tasks(message: types.Message):
    tasks = db.get_user_tasks(message.from_user.id)
    if not tasks:
        await message.answer("У вас нет активных задач", reply_markup=get_main_menu())
        return

    text = "📌 Ваши задачи:\n\n"
    for task in tasks:
        status = "✅ Активна" if task[7] else "❌ Неактивна"
        text += f"ID: {task[0]}\nЧат: {task[2]}\nСтатус: {status}\n\n"

    await message.answer(text, reply_markup=get_main_menu())


@router.message(F.text == "➕ Добавить задачу")
async def add_task_menu(message: types.Message):
    if not db.check_subscription(message.from_user.id):
        await message.answer("❌ У вас нет активной подписки!")
        return

    await message.answer(
        "Выберите тип задачи:",
        reply_markup=get_task_type_menu()
    )


@router.callback_query(F.data.startswith("task_type_"))
async def process_task_type(callback: types.CallbackQuery, state: FSMContext):
    task_type = callback.data.split("_")[-1]
    await state.update_data(task_type=task_type)

    if task_type == "text":
        await callback.message.answer("Введите текст сообщения:")
    else:
        await callback.message.answer("Перешлите сообщение для автопостинга:")

    await state.set_state(TaskStates.waiting_for_content)
    await callback.answer()


@router.message(TaskStates.waiting_for_content)
async def process_task_content(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data["task_type"] == "text" and not message.text:
        await message.answer("Пожалуйста, введите текст сообщения")
        return

    await state.update_data(content=message.text or message.message_id)
    await message.answer("Теперь укажите chat_id назначения:")
    await state.set_state(TaskStates.waiting_for_chat)


@router.message(TaskStates.waiting_for_chat)
async def process_task_chat(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Chat ID должен быть числом")
        return

    await state.update_data(chat_id=int(message.text))
    await message.answer("Укажите расписание в формате:\n\nПример: day=1;hour=12;minute=0\n(каждую неделю в 12:00)")
    await state.set_state(TaskStates.waiting_for_schedule)


@router.message(TaskStates.waiting_for_schedule)
async def process_task_schedule(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        task_id = db.add_task(
            user_id=message.from_user.id,
            chat_id=data["chat_id"],
            thread_id=None,
            message_text=data["content"] if data["task_type"] == "text" else None,
            original_message_id=data["content"] if data["task_type"] == "forward" else None,
            schedule=message.text
        )
        await message.answer(f"✅ Задача #{task_id} создана!", reply_markup=get_main_menu())
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=get_main_menu())

    await state.clear()