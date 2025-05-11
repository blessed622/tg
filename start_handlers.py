# bot/handlers/start_handlers.py - обработчики для команды старт

from aiogram import types, F, Router, Dispatcher, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import logging
from datetime import datetime

from bot.keyboards.main_menu import get_main_menu, get_auth_menu
from bot.handlers.subscription import check_subscription


async def start_command(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик команды /start - начало взаимодействия с ботом"""
    # Сбрасываем все состояния пользователя
    await state.clear()
    
    user = message.from_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name
    language_code = user.language_code
    is_bot = user.is_bot
    
    # Добавляем пользователя в базу, если его там нет
    try:
        async with db.connect() as conn:
            # Проверяем, есть ли пользователь в базе
            cursor = await conn.execute(
                'SELECT * FROM users WHERE telegram_id = ?',
                (user_id,)
            )
            existing_user = await cursor.fetchone()
            
            if not existing_user:
                # Если пользователя нет, добавляем его
                await conn.execute(
                    '''
                    INSERT INTO users 
                    (telegram_id, username, first_name, last_name, language_code, is_bot) 
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (user_id, username, first_name, last_name, language_code, is_bot)
                )
                await conn.commit()
                logging.info(f"Новый пользователь добавлен в базу: {user_id}")
            else:
                # Обновляем информацию о пользователе
                await conn.execute(
                    '''
                    UPDATE users 
                    SET username = ?, first_name = ?, last_name = ?, 
                    language_code = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE telegram_id = ?
                    ''',
                    (username, first_name, last_name, language_code, user_id)
                )
                await conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при работе с базой данных: {e}")
    
    # Проверяем, есть ли активная сессия у пользователя
    async with db.connect() as conn:
        cursor = await conn.execute(
            'SELECT * FROM sessions WHERE user_id = ? AND is_active = 1',
            (user_id,)
        )
        active_session = await cursor.fetchone()
    
    # Проверяем подписку
    is_active_subscription, _ = await check_subscription(user_id, db)
    
    # Приветственное сообщение
    greeting = (
        f"👋 <b>Привет, {user.first_name}!</b>\n\n"
        f"Добро пожаловать в бот для автопостинга в Telegram.\n\n"
        f"С помощью этого бота вы сможете настроить автоматическую отправку сообщений "
        f"в любые каналы, группы и личные чаты с заданным интервалом от 20 до 999 секунд.\n\n"
    )
    
    # Если у пользователя нет активной сессии
    if not active_session:
        await message.answer(
            greeting +
            "🔑 <b>Для начала работы вам необходимо авторизоваться.</b>\n\n"
            "Нажмите кнопку «Авторизоваться» ниже:",
            reply_markup=get_auth_menu()
        )
        return
    
    # Если нет активной подписки
    if not is_active_subscription:
        await message.answer(
            greeting +
            "💰 <b>Для использования функций бота необходима подписка.</b>\n\n"
            "• Автоматическая отправка сообщений по расписанию\n"
            "• Интервальная отправка (от 20 до 999 секунд)\n"
            "• Отправка в любые каналы, группы и чаты\n"
            "• Поддержка форматирования и медиафайлов\n"
            "• Неограниченное количество отправлений\n\n"
            "💰 <b>Стоимость подписки</b>: всего 500₽/месяц\n\n"
            "📱 Для оформления подписки напишите @lovelymaxing",
            reply_markup=get_main_menu()
        )
        return
    
    # Если всё в порядке
    await message.answer(
        greeting +
        "✅ <b>У вас есть активная сессия и подписка.</b>\n\n"
        "Вы можете начать создавать задачи на автопостинг прямо сейчас!",
        reply_markup=get_main_menu()
    )


def register_start_handlers(dp: Dispatcher, db, bot: Bot):
    """Регистрация обработчиков команды старт"""
    dp.message.register(lambda message, state: start_command(message, state, db, bot), Command("start"))
