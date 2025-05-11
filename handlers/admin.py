from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from config import OWNER_ID
import logging
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

router = Router()
db = Database()
logger = logging.getLogger(__name__)


class SubscriptionStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()


@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступ запрещен")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
            [InlineKeyboardButton(text="🔧 Управление подписками", callback_data="admin_subscriptions")],
            [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin_add_sub")]
        ]
    )
    await message.answer("👑 Админ-панель:", reply_markup=keyboard)


@router.callback_query(F.data == "admin_users")
async def show_all_users(callback: types.CallbackQuery):
    try:
        users = db.get_all_users()
        if not users:
            await callback.message.edit_text("Нет зарегистрированных пользователей")
            return

        text = "📋 Список пользователей:\n\n"
        for user in users:
            text += f"ID: {user[0]}\n"
            text += f"Username: @{user[1]}\n" if user[1] else ""
            text += f"Имя: {user[2]}\n"
            text += "Статус: " + ("✅ Активна" if db.check_subscription(user[0]) else "❌ Неактивна") + "\n"
            text += f"Дата окончания: {user[4]}\n\n" if user[4] else ""

        await callback.message.edit_text(text)
    except Exception as e:
        logger.error(f"Ошибка в show_all_users: {e}")
        await callback.message.edit_text("⚠️ Ошибка при получении списка пользователей")
    finally:
        await callback.answer()


@router.callback_query(F.data == "admin_subscriptions")
async def manage_subscriptions(callback: types.CallbackQuery):
    try:
        users = db.get_all_users()
        text = "🔧 Активные подписки:\n\n"

        active_count = 0
        for user in users:
            if db.check_subscription(user[0]):
                text += f"ID: {user[0]}\n"
                text += f"Username: @{user[1]}\n" if user[1] else ""
                text += f"Окончание: {user[4]}\n\n"
                active_count += 1

        if active_count == 0:
            text = "❌ Нет активных подписок"

        await callback.message.edit_text(text)
    except Exception as e:
        logger.error(f"Ошибка в manage_subscriptions: {e}")
        await callback.message.edit_text("⚠️ Ошибка при получении подписок")
    finally:
        await callback.answer()


@router.callback_query(F.data == "admin_add_sub")
async def start_add_subscription(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите ID пользователя для выдачи подписки:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]]
        )
    )
    await state.set_state(SubscriptionStates.waiting_for_user_id)
    await callback.answer()


@router.message(SubscriptionStates.waiting_for_user_id)
async def process_user_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите количество дней подписки:")
        await state.set_state(SubscriptionStates.waiting_for_days)
    except ValueError:
        await message.answer("❌ Некорректный ID. Введите число:")


@router.message(SubscriptionStates.waiting_for_days)
async def process_days(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        user_id = data['user_id']
        days = int(message.text)

        if days <= 0:
            await message.answer("❌ Количество дней должно быть больше 0")
            return

        if db.set_subscription(user_id, days):
            await message.answer(f"✅ Пользователю {user_id} выдана подписка на {days} дней")
        else:
            await message.answer("❌ Ошибка при выдаче подписки")

    except ValueError:
        await message.answer("❌ Некорректное количество дней. Введите число:")
    finally:
        await state.clear()


@router.callback_query(F.data == "admin_cancel")
async def cancel_action(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено")
    await callback.answer()