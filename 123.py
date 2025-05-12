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

# Отправка сообщения в группу
async def send_message_to_topic(task_data: Dict) -> bool:
    client = await create_telethon_client()
    success = False

    try:
        # Получаем информацию о чате
        entity = await client.get_entity(f"@{task_data['group_username']}")

        # Отправка сообщения с фото, если указан путь
        if task_data.get('photo_path') and os.path.exists(task_data['photo_path']):
            # Если топик указан и он не равен 0, отправляем в топик
            if task_data.get('topic_id', 0) != 0:
                await client.send_file(
                    entity,
                    task_data['photo_path'],
                    caption=task_data['message'],
                    reply_to=task_data['topic_id'],
                    parse_mode='html'
                )
            else:
                # Отправка в обычную группу без топика
                await client.send_file(
                    entity,
                    task_data['photo_path'],
                    caption=task_data['message'],
                    parse_mode='html'
                )
        else:
            # Отправка только текста
            if task_data.get('topic_id', 0) != 0:
                await client.send_message(
                    entity,
                    task_data['message'],
                    reply_to=task_data['topic_id'],
                    parse_mode='html'
                )
            else:
                # Отправка в обычную группу без топика
                await client.send_message(
                    entity,
                    task_data['message'],
                    parse_mode='html'
                )

        # Обновляем время последней отправки
        task_data['last_posted'] = datetime.now().isoformat()
        success = True

    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {str(e)}")
    finally:
        # Закрываем соединение
        if client.is_connected():
            await client.disconnect()

    return success


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

# 2. Добавляем функцию для управления уведомлениями в конфигурации

def toggle_notifications_status(config: Dict) -> Dict:
    """Изменяет статус уведомлений в конфигурации"""
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
            callback_data=f"edit_task_{task_id}"
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
        InlineKeyboardButton("✏️ Изменить сообщение", callback_data=f"edit_message_{task_id}"),
        InlineKeyboardButton("🖼 Изменить фото", callback_data=f"edit_photo_{task_id}"),
        InlineKeyboardButton("⏱ Изменить интервал", callback_data=f"edit_interval_{task_id}"),
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
            "👋 Добро пожаловать в Telegram Poster Bot!\n\n"
            "Этот бот поможет вам автоматически отправлять сообщения в топики форумов Telegram.\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard()
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
            "<b>Управление задачами:</b>\n"
            "• В разделе 'Мои задачи' вы можете запускать, останавливать, редактировать или удалять задачи\n"
            "• В разделе 'Статус задач' вы можете видеть текущее состояние всех задач\n\n"
            "<b>Важно:</b>\n"
            "• У вас должны быть соответствующие права для отправки сообщений в указанные группы\n"
            "• Клиент Telegram использует указанный при настройке номер телефона\n",
            parse_mode=ParseMode.HTML
        )
    
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

    @dp.callback_query_handler(lambda c: c.data.startswith('use_without_topics_'), state='*')
    async def process_use_without_topics(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)

        # Получаем имя группы из callback_data
        group_username = callback_query.data.replace('use_without_topics_', '')

        # Сохраняем информацию о группе в состоянии
        await state.update_data(group_username=group_username, topic_id=0, topic_name="Нет топика")

        # Переходим к вводу сообщения
        await PosterStates.entering_message.set()
        await bot.send_message(
            callback_query.from_user.id,
            f"Вы выбрали отправку сообщений в группу @{group_username} без указания топика.\n\n"
            f"Введите текст сообщения, которое будет отправляться в эту группу.\n\n"
            f"Можно использовать HTML-форматирование:\n"
            f"<b>жирный</b>\n"
            f"<i>курсив</i>\n"
            f"<u>подчеркнутый</u>\n"
            f"<a href='http://example.com'>ссылка</a>\n"
            f"<code>код</code>\n"
            f"<pre>блок кода</pre>\n"
            f"<blockquote>цитата</blockquote>"
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

        # Счетчики для отчета
        started_count = 0
        already_running_count = 0

        # Активируем все задачи
        for task_id, task_data in tasks.items():
            # Если задача уже активна, пропускаем
            if task_id in active_tasks and active_tasks[task_id]:
                already_running_count += 1
                continue

            # Обновляем статус задачи в конфигурации
            config['tasks'][task_id]['active'] = True

            # Добавляем задачу в список активных
            active_tasks[task_id] = True

            # Запускаем задачу в фоновом режиме
            asyncio.create_task(run_task(task_id, task_data, bot))
            started_count += 1

        # Сохраняем конфигурацию
        save_config(config)

        # Отправляем отчет
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

        # Счетчики для отчета
        stopped_count = 0
        already_stopped_count = 0

        # Останавливаем все задачи
        for task_id, task_data in tasks.items():
            # Если задача уже остановлена, пропускаем
            if task_id not in active_tasks or not active_tasks[task_id]:
                already_stopped_count += 1
                continue

            # Обновляем статус задачи в конфигурации
            config['tasks'][task_id]['active'] = False

            # Удаляем задачу из списка активных
            active_tasks[task_id] = False
            stopped_count += 1

        # Сохраняем конфигурацию
        save_config(config)

        # Отправляем отчет
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

        # Загружаем конфигурацию и меняем статус уведомлений
        config = load_config()
        config = toggle_notifications_status(config)

        # Получаем текущий статус уведомлений
        notifications_enabled = config.get('notifications_enabled', True)
        status_text = "включены" if notifications_enabled else "отключены"

        # Отправляем сообщение о текущем статусе
        await bot.send_message(
            callback_query.from_user.id,
            f"🔔 Уведомления {status_text}.\n\n"
            f"{'Теперь вы будете получать уведомления о работе бота.' if notifications_enabled else 'Теперь вы не будете получать уведомления о работе бота.'}",
            reply_markup=get_main_menu_keyboard()
        )

    # Обработчик ввода группы
    @dp.message_handler(state=PosterStates.waiting_for_group_link)
    async def process_group_link(message: types.Message, state: FSMContext):
        group_username = message.text.strip()

        # Убираем @ в начале, если есть
        if group_username.startswith('@'):
            group_username = group_username[1:]

        # Проверяем, что имя группы не пустое
        if not group_username:
            await message.answer("Имя группы не может быть пустым. Пожалуйста, введите правильное имя группы:")
            return

        await message.answer(f"Ищем топики в группе @{group_username}...\nЭто может занять некоторое время.")

        # Получаем список топиков
        topics, error = await find_topics(group_username)

        if error or not topics:
            # Предлагаем отправку сообщений в группу без топиков
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

        # Сохраняем информацию о группе в состоянии
        await state.update_data(group_username=group_username)

        # Показываем список топиков
        await PosterStates.selecting_topic.set()
        await message.answer(
            f"Найдено {len(topics)} топиков в группе @{group_username}.\nВыберите топик:",
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
            "active": False,
            "last_posted": None
        }
        
        # Сохраняем задачу в конфигурации
        config = load_config()
        if 'tasks' not in config:
            config['tasks'] = {}
        config['tasks'][task_id] = task_data
        save_config(config)
        
        # Возвращаемся в главное меню
        await state.finish()
        await PosterStates.main_menu.set()
        
        # Отправляем сообщение об успешном добавлении
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Задача успешно добавлена!\n\n"
            f"Чтобы запустить её, перейдите в раздел 'Мои задачи' и выберите нужную задачу.",
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
        
        # Показываем список задач
        await PosterStates.select_task_to_edit.set()
        await bot.send_message(
            callback_query.from_user.id,
            "📋 Ваши задачи:\n\n"
            "Выберите задачу для управления:",
            reply_markup=get_tasks_keyboard(tasks)
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
            f"<b>Статус:</b> {'✅ Активна' if task_id in active_tasks and active_tasks[task_id] else '❌ Остановлена'}\n"
            f"<b>Последняя отправка:</b> {task_data.get('last_posted', 'Нет')} \n\n"
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
    
    # Обработчик редактирования сообщения
    @dp.callback_query_handler(lambda c: c.data.startswith('edit_message_'), state='*')
    async def process_edit_message(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        
        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('edit_message_', '')
        
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
        
        # Показываем текущее сообщение и просим ввести новое
        await PosterStates.entering_message.set()
        await bot.send_message(
            callback_query.from_user.id,
            f"<b>Текущее сообщение:</b>\n\n{tasks[task_id]['message']}\n\n"
            f"Введите новый текст сообщения:",
            parse_mode=ParseMode.HTML
        )
    
    # Обработчик редактирования фото
    @dp.callback_query_handler(lambda c: c.data.startswith('edit_photo_'), state='*')
    async def process_edit_photo(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        
        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('edit_photo_', '')
        
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
    
    # Обработчик редактирования интервала
    @dp.callback_query_handler(lambda c: c.data.startswith('edit_interval_'), state='*')
    async def process_edit_interval(callback_query: types.CallbackQuery, state: FSMContext):
        await bot.answer_callback_query(callback_query.id)
        
        # Получаем ID задачи из callback_data
        task_id = callback_query.data.replace('edit_interval_', '')
        
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
        
        # Переходим к установке нового интервала
        await PosterStates.setting_interval.set()
        await bot.send_message(
            callback_query.from_user.id,
            f"Текущий интервал: {tasks[task_id]['interval']} сек.\n\n"
            f"Введите новый интервал отправки сообщений в секундах (не менее 30):"
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
    
    # Обработчик кнопки "Статус задач"
    @dp.callback_query_handler(lambda c: c.data == 'task_status', state='*')
    async def process_task_status(callback_query: types.CallbackQuery, state: FSMContext):
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
        
        # Формируем сообщение со статусом всех задач
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
        
        # Добавляем кнопку возврата в главное меню
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
        
        # Отправляем справочное сообщение (такое же, как при команде /help)
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
            "<b>Управление задачами:</b>\n"
            "• В разделе 'Мои задачи' вы можете запускать, останавливать, редактировать или удалять задачи\n"
            "• В разделе 'Статус задач' вы можете видеть текущее состояние всех задач\n\n"
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
    config = load_config()
    for task_id, task_data in config.get('tasks', {}).items():
        if task_data.get('active', False):
            # Автоматически запускаем активные задачи
            active_tasks[task_id] = True
            asyncio.create_task(run_task(task_id, task_data, bot))
            logging.info(f"Автоматически запущена задача {task_id} для группы @{task_data['group_username']}")
    
    # Проверяем ID владельца бота
    owner_id = config.get('user_id')
    if owner_id:
        try:
            await bot.send_message(
                owner_id,
                "🤖 Telegram Poster Bot запущен!\n\n"
                "Для взаимодействия с ботом используйте команду /start",
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
        # Создаем и запускаем цикл событий
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")
    except Exception as e:
        logging.error(f"Критическая ошибка: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
