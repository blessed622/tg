# bot/handlers/auth.py - обработчики для авторизации пользователя

from aiogram import types, F, Router, Dispatcher, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from telethon.sync import TelegramClient
from telethon.errors import PhoneNumberInvalidError, PhoneCodeInvalidError, SessionPasswordNeededError
import os
import logging
import asyncio
import re

from bot.states.auth_states import AuthStates
from bot.keyboards.main_menu import get_auth_menu, get_main_menu
from utils.validators import is_valid_api_id, is_valid_api_hash
from utils.crypto import encrypt_data, decrypt_data
from config import SESSIONS_DIR


async def auth_start(message: types.Message | types.CallbackQuery, state: FSMContext, db, bot: Bot):
    """Начало процесса авторизации"""
    # Определяем тип входящего сообщения
    if isinstance(message, types.CallbackQuery):
        await message.answer()  # Убираем часы на кнопке
        message = message.message
    
    user_id = message.chat.id
    
    # Проверяем, есть ли у пользователя активная сессия
    async with db.connect() as conn:
        cursor = await conn.execute(
            'SELECT * FROM sessions WHERE user_id = ? AND is_active = 1',
            (user_id,)
        )
        session = await cursor.fetchone()
    
    if session:
        # У пользователя уже есть активная сессия
        await message.answer(
            "🔑 У вас уже есть активная сессия в системе.\n\n"
            "Вы можете:\n"
            "• Продолжить использовать текущую сессию\n"
            "• Создать новую сессию (текущая будет деактивирована)\n"
            "• Проверить статус текущей сессии",
            reply_markup=get_auth_menu()
        )
        return
    
    # Начинаем процесс авторизации
    await message.answer(
        "🔑 Начинаем процесс авторизации в Telegram API\n\n"
        "Для работы сервиса автопостинга нам необходимы API ID и API Hash от вашего аккаунта.\n\n"
        "Чтобы получить эти данные:\n"
        "1. Перейдите на сайт https://my.telegram.org\n"
        "2. Авторизуйтесь с вашим номером телефона\n"
        "3. Перейдите в 'API development tools'\n"
        "4. Создайте новое приложение (если еще не создали)\n\n"
        "⚠️ Важно: Мы не храним ваши данные в открытом виде, они шифруются для обеспечения безопасности."
    )
    
    # Запрашиваем API ID
    await message.answer("Введите ваш API ID (только цифры):")
    
    # Устанавливаем состояние
    await state.set_state(AuthStates.waiting_api_id)


async def api_id_received(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик для получения API ID"""
    api_id = message.text.strip()
    
    # Проверяем валидность API ID
    if not is_valid_api_id(api_id):
        await message.answer(
            "❌ Неверный формат API ID. Должны быть только цифры.\n\n"
            "Пожалуйста, проверьте и введите еще раз:"
        )
        return
    
    # Сохраняем API ID в состоянии
    await state.update_data(api_id=api_id)
    
    # Запрашиваем API Hash
    await message.answer("Теперь введите ваш API Hash (32 символа):")
    await state.set_state(AuthStates.waiting_api_hash)


async def api_hash_received(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик для получения API Hash"""
    api_hash = message.text.strip()
    
    # Проверяем валидность API Hash
    if not is_valid_api_hash(api_hash):
        await message.answer(
            "❌ Неверный формат API Hash. Должен содержать 32 символа.\n\n"
            "Пожалуйста, проверьте и введите еще раз:"
        )
        return
    
    # Сохраняем API Hash в состоянии
    await state.update_data(api_hash=api_hash)
    
    # Запрашиваем номер телефона
    await message.answer(
        "Введите номер телефона в международном формате (например, +79123456789):"
    )
    await state.set_state(AuthStates.waiting_phone)


async def phone_received(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик для получения номера телефона"""
    phone = message.text.strip()
    
    # Проверяем формат телефона
    phone_pattern = r'^\+\d{10,15}$'
    if not re.match(phone_pattern, phone):
        await message.answer(
            "❌ Неверный формат номера телефона.\n\n"
            "Введите номер в международном формате, например: +79123456789"
        )
        return
    
    # Сохраняем телефон в состоянии
    await state.update_data(phone=phone)
    
    # Получаем данные из состояния
    data = await state.get_data()
    api_id = int(data['api_id'])
    api_hash = data['api_hash']
    
    # Создаем директорию для сессии, если её нет
    user_session_dir = os.path.join(SESSIONS_DIR, str(message.from_user.id))
    os.makedirs(user_session_dir, exist_ok=True)
    
    # Путь к файлу сессии
    session_file = os.path.join(user_session_dir, f"user_{message.from_user.id}")
    
    try:
        # Сообщаем пользователю о начале процесса авторизации
        status_msg = await message.answer("⏳ Подключаемся к Telegram API...")
        
        # Создаем клиента Telethon
        client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()
        
        # Если уже авторизован
        if await client.is_user_authorized():
            await status_msg.edit_text("✅ Вы уже авторизованы! Ваша сессия активна и готова к использованию.")
            
            # Сохраняем данные сессии в БД
            user_id = message.from_user.id
            
            # Шифруем чувствительные данные
            encrypted_api_hash = encrypt_data(api_hash)
            encrypted_phone = encrypt_data(phone)
            
            # Записываем в БД
            async with db.connect() as conn:
                await conn.execute(
                    '''
                    INSERT INTO sessions 
                    (user_id, api_id, api_hash, phone, session_file, is_active) 
                    VALUES (?, ?, ?, ?, ?, 1)
                    ''',
                    (user_id, api_id, encrypted_api_hash, encrypted_phone, str(session_file))
                )
                await conn.commit()
            
            await client.disconnect()
            
            # Возвращаемся в главное меню
            await message.answer(
                "🎉 Авторизация успешно завершена!\n\n"
                "Теперь вы можете создавать задачи на автопостинг.",
                reply_markup=get_main_menu()
            )
            await state.clear()
            return
        
        # Отправляем код авторизации
        await status_msg.edit_text("📲 Отправляем код подтверждения на ваш телефон...")
        await client.send_code_request(phone)
        await client.disconnect()
        
        # Просим пользователя ввести код
        await message.answer(
            "📱 Код подтверждения отправлен на ваш телефон.\n\n"
            "Пожалуйста, введите его:"
        )
        await state.set_state(AuthStates.waiting_code)
        
    except PhoneNumberInvalidError:
        await message.answer(
            "❌ Указан неверный номер телефона.\n\n"
            "Пожалуйста, проверьте и введите номер еще раз:"
        )
        await state.set_state(AuthStates.waiting_phone)
    except Exception as e:
        logging.error(f"Ошибка при авторизации: {e}")
        await message.answer(
            f"❌ Произошла ошибка при авторизации: {str(e)}\n\n"
            f"Пожалуйста, попробуйте еще раз позже или обратитесь в поддержку."
        )
        await state.clear()


async def code_received(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик для получения кода подтверждения"""
    code = message.text.strip()
    
    # Проверяем формат кода
    if not code.isdigit() or len(code) < 5:
        await message.answer(
            "❌ Неверный формат кода. Должны быть только цифры (обычно 5 цифр).\n\n"
            "Пожалуйста, проверьте и введите код еще раз:"
        )
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    api_id = int(data['api_id'])
    api_hash = data['api_hash']
    phone = data['phone']
    
    # Путь к файлу сессии
    user_session_dir = os.path.join(SESSIONS_DIR, str(message.from_user.id))
    session_file = os.path.join(user_session_dir, f"user_{message.from_user.id}")
    
    try:
        # Сообщаем о процессе авторизации
        status_msg = await message.answer("⏳ Проверяем код подтверждения...")
        
        # Создаем клиента Telethon
        client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()
        
        # Пробуем войти с кодом
        try:
            await client.sign_in(phone, code)
            
            # Успешная авторизация
            await status_msg.edit_text("✅ Код подтверждения принят! Авторизация успешна.")
            
            # Сохраняем данные сессии в БД
            user_id = message.from_user.id
            
            # Шифруем чувствительные данные
            encrypted_api_hash = encrypt_data(api_hash)
            encrypted_phone = encrypt_data(phone)
            
            # Записываем в БД
            async with db.connect() as conn:
                await conn.execute(
                    '''
                    INSERT INTO sessions 
                    (user_id, api_id, api_hash, phone, session_file, is_active) 
                    VALUES (?, ?, ?, ?, ?, 1)
                    ''',
                    (user_id, api_id, encrypted_api_hash, encrypted_phone, str(session_file))
                )
                await conn.commit()
            
            await client.disconnect()
            
            # Возвращаемся в главное меню
            await message.answer(
                "🎉 Авторизация успешно завершена!\n\n"
                "Теперь вы можете создавать задачи на автопостинг.",
                reply_markup=get_main_menu()
            )
            await state.clear()
            
        except PhoneCodeInvalidError:
            await status_msg.edit_text("❌ Неверный код подтверждения.")
            await message.answer("Пожалуйста, введите код еще раз:")
            
        except SessionPasswordNeededError:
            # Для аккаунтов с двухфакторной аутентификацией
            await status_msg.edit_text(
                "🔐 Обнаружена двухфакторная аутентификация.\n"
                "Пожалуйста, введите ваш пароль:"
            )
            await state.set_state(AuthStates.waiting_2fa)
            
    except Exception as e:
        logging.error(f"Ошибка при вводе кода: {e}")
        await message.answer(
            f"❌ Произошла ошибка при авторизации: {str(e)}\n\n"
            f"Пожалуйста, попробуйте еще раз позже или обратитесь в поддержку."
        )
        await state.clear()


async def password_received(message: types.Message, state: FSMContext, db, bot: Bot):
    """Обработчик для получения пароля 2FA"""
    password = message.text.strip()
    
    # Получаем данные из состояния
    data = await state.get_data()
    api_id = int(data['api_id'])
    api_hash = data['api_hash']
    phone = data['phone']
    
    # Путь к файлу сессии
    user_session_dir = os.path.join(SESSIONS_DIR, str(message.from_user.id))
    session_file = os.path.join(user_session_dir, f"user_{message.from_user.id}")
    
    try:
        # Сообщаем о процессе авторизации
        status_msg = await message.answer("⏳ Проверяем пароль...")
        
        # Создаем клиента Telethon
        client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()
        
        # Пробуем ввести пароль 2FA
        try:
            await client.sign_in(password=password)
            
            # Успешная авторизация
            await status_msg.edit_text("✅ Пароль принят! Авторизация успешна.")
            
            # Сохраняем данные сессии в БД
            user_id = message.from_user.id
            
            # Шифруем чувствительные данные
            encrypted_api_hash = encrypt_data(api_hash)
            encrypted_phone = encrypt_data(phone)
            
            # Записываем в БД
            async with db.connect() as conn:
                await conn.execute(
                    '''
                    INSERT INTO sessions 
                    (user_id, api_id, api_hash, phone, session_file, is_active) 
                    VALUES (?, ?, ?, ?, ?, 1)
                    ''',
                    (user_id, api_id, encrypted_api_hash, encrypted_phone, str(session_file))
                )
                await conn.commit()
            
            await client.disconnect()
            
            # Возвращаемся в главное меню
            await message.answer(
                "🎉 Авторизация успешно завершена!\n\n"
                "Теперь вы можете создавать задачи на автопостинг.",
                reply_markup=get_main_menu()
            )
            await state.clear()
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка при вводе пароля: {str(e)}")
            await message.answer("Пожалуйста, введите пароль еще раз:")
            
    except Exception as e:
        logging.error(f"Ошибка при вводе пароля 2FA: {e}")
        await message.answer(
            f"❌ Произошла ошибка при авторизации: {str(e)}\n\n"
            f"Пожалуйста, попробуйте еще раз позже или обратитесь в поддержку."
        )
        await state.clear()


async def check_auth_status(message: types.Message | types.CallbackQuery, state: FSMContext, db, bot: Bot):
    """Проверка статуса авторизации пользователя"""
    # Определяем тип входящего сообщения
    if isinstance(message, types.CallbackQuery):
        await message.answer()  # Убираем часы на кнопке
        message = message.message
    
    user_id = message.chat.id
    
    # Проверяем, есть ли у пользователя активная сессия
    async with db.connect() as conn:
        cursor = await conn.execute(
            'SELECT * FROM sessions WHERE user_id = ? AND is_active = 1',
            (user_id,)
        )
        session = await cursor.fetchone()
    
    if not session:
        await message.answer(
            "❌ У вас нет активной сессии.\n\n"
            "Для использования сервиса автопостинга необходимо авторизоваться.",
            reply_markup=get_auth_menu()
        )
        return
    
    # Получаем данные сессии
    api_id = session['api_id']
    api_hash = decrypt_data(session['api_hash'])
    session_file = session['session_file']
    
    try:
        # Сообщаем о процессе проверки
        status_msg = await message.answer("⏳ Проверяем статус сессии...")
        
        # Создаем клиента Telethon
        client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()
        
        # Проверяем, авторизован ли пользователь
        if await client.is_user_authorized():
            # Получаем информацию о пользователе
            me = await client.get_me()
            await client.disconnect()
            
            await status_msg.edit_text(
                f"✅ Сессия активна!\n\n"
                f"👤 Аккаунт: {me.first_name} {me.last_name or ''}\n"
                f"🆔 Username: @{me.username or 'отсутствует'}\n"
                f"📱 ID: {me.id}\n\n"
                f"Вы можете создавать задачи на автопостинг."
            )
        else:
            await client.disconnect()
            await status_msg.edit_text(
                "❌ Сессия не активна.\n\n"
                "Необходимо пройти процесс авторизации заново."
            )
            
    except Exception as e:
        logging.error(f"Ошибка при проверке статуса сессии: {e}")
        await message.answer(
            f"❌ Произошла ошибка при проверке статуса сессии: {str(e)}\n\n"
            f"Возможно, сессия устарела или была отозвана. Попробуйте авторизоваться заново."
        )


def register_auth_handlers(dp: Dispatcher, db, bot: Bot):
    """Регистрация обработчиков для авторизации"""
    # Команды
    dp.message.register(lambda message, state: auth_start(message, state, db, bot), Command("auth"))
    
    # Callback запросы
    dp.callback_query.register(lambda call, state: auth_start(call, state, db, bot), F.data == "auth:start")
    dp.callback_query.register(lambda call, state: check_auth_status(call, state, db, bot), F.data == "auth:status")
    
    # Состояния FSM
    dp.message.register(lambda message, state: api_id_received(message, state, db, bot), AuthStates.waiting_api_id)
    dp.message.register(lambda message, state: api_hash_received(message, state, db, bot), AuthStates.waiting_api_hash)
    dp.message.register(lambda message, state: phone_received(message, state, db, bot), AuthStates.waiting_phone)
    dp.message.register(lambda message, state: code_received(message, state, db, bot), AuthStates.waiting_code)
    dp.message.register(lambda message, state: password_received(message, state, db, bot), AuthStates.waiting_2fa)
