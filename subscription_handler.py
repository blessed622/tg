# bot/handlers/subscription.py - обработчики для управления подписками

from aiogram import types, F, Router, Dispatcher, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import logging

from bot.keyboards.main_menu import get_main_menu, get_subscription_menu
from config import OWNER_ID


async def check_subscription(user_id, db):
    """
    Проверка активности подписки пользователя
    
    Args:
        user_id (int): ID пользователя
        db: Объект базы данных
        
    Returns:
        bool: True если подписка активна, False в противном случае
        dict: Информация о подписке или None, если подписки нет
    """
    try:
        async with db.connect() as conn:
            cursor = await conn.execute(
                '''
                SELECT * FROM subscriptions 
                WHERE user_id = ? AND is_active = 1 AND end_date > ?
                ''',
                (user_id, datetime.now().isoformat())
            )
            subscription = await cursor.fetchone()
        
        if subscription:
            return True, subscription
        return False, None
    except Exception as e:
        logging.error(f"Ошибка при проверке подписки: {e}")
        return False, None


async def get_subscription_info(message: types.Message | types.CallbackQuery, db, bot: Bot):
    """Получение информации о подписке пользователя"""
    # Определяем тип входящего сообщения
    if isinstance(message, types.CallbackQuery):
        await message.answer()  # Убираем часы на кнопке
        message = message.message
    
    user_id = message.chat.id
    
    # Проверяем подписку
    is_active, subscription = await check_subscription(user_id, db)
    
    if is_active:
        # Рассчитываем оставшееся время
        end_date = datetime.fromisoformat(subscription['end_date'])
        days_left = (end_date - datetime.now()).days
        
        # Получаем информацию о лимитах пользователя
        async with db.connect() as conn:
            # Всего задач пользователя
            cursor = await conn.execute(
                'SELECT COUNT(*) as count FROM tasks WHERE user_id = ?',
                (user_id,)
            )
            tasks_count = (await cursor.fetchone())['count']
            
            # Всего отправленных сообщений
            cursor = await conn.execute(
                'SELECT SUM(execution_count) as count FROM tasks WHERE user_id = ?',
                (user_id,)
            )
            result = await cursor.fetchone()
            sent_messages = result['count'] if result['count'] is not None else 0
        
        # Определяем максимальное количество задач в зависимости от типа подписки
        max_tasks = 20  # Стандартное значение для обычной подписки
        if subscription['subscription_type'] == 'premium':
            max_tasks = 50
        elif subscription['subscription_type'] == 'business':
            max_tasks = 100
        
        await message.answer(
            f"📌 <b>Статус подписки</b>:\n"
            f"✅ Активна до: {end_date.strftime('%d.%m.%Y')}\n"
            f"⏳ Осталось: {days_left} дней\n\n"
            f"📊 <b>Ваши лимиты</b>:\n"
            f"- Задач: {tasks_count}/{max_tasks}\n"
            f"- Отправлено сообщений: {sent_messages}\n\n"
            f"💡 Для продления подписки нажмите кнопку ниже",
            parse_mode="HTML",
            reply_markup=get_subscription_menu()
        )
    else:
        await message.answer(
            "❌ <b>У вас нет активной подписки</b>\n\n"
            "Для использования сервиса автопостинга необходима активная подписка.\n\n"
            "🔥 <b>Преимущества подписки</b>:\n"
            "• Автоматическая отправка сообщений по расписанию\n"
            "• Интервальная отправка (от 20 до 999 секунд)\n"
            "• Отправка в любые каналы, группы и чаты\n"
            "• Поддержка форматирования и медиафайлов\n"
            "• Неограниченное количество отправлений\n\n"
            "💰 <b>Стоимость подписки</b>: всего 500₽/месяц\n\n"
            "📱 Для оформления подписки напишите @lovelymaxing",
            parse_mode="HTML",
            reply_markup=get_subscription_menu(show_extend=False)
        )


async def request_subscription(message: types.CallbackQuery, db, bot: Bot):
    """Запрос на оформление/продление подписки"""
    await message.answer()  # Убираем часы на кнопке
    
    await message.message.answer(
        "📲 <b>Оформление подписки</b>\n\n"
        "Для оформления или продления подписки на сервис автопостинга, "
        "пожалуйста, свяжитесь с администратором:\n\n"
        "👨‍💻 @lovelymaxing\n\n"
        "💰 <b>Стоимость подписки</b>: 500₽/месяц\n\n"
        "🔥 <b>С нашим сервисом вы сможете</b>:\n"
        "• Экономить время на регулярных публикациях\n"
        "• Автоматизировать рассылку по всем вашим каналам и группам\n"
        "• Планировать контент заранее\n"
        "• Настраивать интервальную отправку от 20 до 999 секунд\n"
        "• Получать статистику по всем публикациям\n\n"
        "⚡️ Оформите подписку сейчас и получите бонусные дни в подарок!",
        parse_mode="HTML"
    )
    
    # Отправляем уведомление владельцу бота
    try:
        await bot.send_message(
            OWNER_ID,
            f"💼 <b>Новый запрос на подписку</b>\n\n"
            f"👤 Пользователь: {message.from_user.full_name}\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"👤 Username: @{message.from_user.username or 'отсутствует'}\n\n"
            f"📅 Дата запроса: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления владельцу: {e}")


async def add_subscription(message: types.Message, db, bot: Bot, duration_days=30):
    """
    Добавление подписки пользователю (только для владельца бота)
    
    Args:
        message: Объект сообщения
        db: Объект базы данных
        bot: Объект бота
        duration_days: Длительность подписки в днях
    """
    # Проверяем, что команда от владельца бота
    if message.from_user.id != OWNER_ID:
        return
    
    # Формат команды: /add_sub ID DAYS
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Неверный формат команды. Используйте: /add_sub ID [DAYS]")
        return
    
    try:
        user_id = int(parts[1])
        
        # Проверяем, указано ли количество дней
        if len(parts) >= 3:
            duration_days = int(parts[2])
    except ValueError:
        await message.answer("❌ ID пользователя и количество дней должны быть числами")
        return
    
    try:
        # Проверяем, есть ли уже активная подписка
        is_active, subscription = await check_subscription(user_id, db)
        
        start_date = datetime.now()
        end_date = start_date + timedelta(days=duration_days)
        
        async with db.connect() as conn:
            if is_active:
                # Продлеваем существующую подписку
                current_end_date = datetime.fromisoformat(subscription['end_date'])
                new_end_date = current_end_date + timedelta(days=duration_days)
                
                await conn.execute(
                    '''
                    UPDATE subscriptions 
                    SET end_date = ? 
                    WHERE id = ?
                    ''',
                    (new_end_date.isoformat(), subscription['id'])
                )
                action = "продлена"
            else:
                # Создаем новую подписку
                await conn.execute(
                    '''
                    INSERT INTO subscriptions 
                    (user_id, start_date, end_date, is_active, subscription_type) 
                    VALUES (?, ?, ?, 1, 'standard')
                    ''',
                    (user_id, start_date.isoformat(), end_date.isoformat())
                )
                action = "добавлена"
            
            await conn.commit()
        
        # Уведомляем администратора
        await message.answer(
            f"✅ Подписка {action} для пользователя {user_id}\n"
            f"📅 Срок действия: до {end_date.strftime('%d.%m.%Y')}"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"🎉 <b>Поздравляем! Ваша подписка {action}!</b>\n\n"
                f"📅 Срок действия: до {end_date.strftime('%d.%m.%Y')}\n"
                f"⏳ Длительность: {duration_days} дней\n\n"
                f"Теперь вы можете в полной мере использовать все возможности нашего сервиса автопостинга.",
                parse_mode="HTML",
                reply_markup=get_main_menu()
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления пользователю: {e}")
            await message.answer(f"⚠️ Не удалось отправить уведомление пользователю: {e}")
        
    except Exception as e:
        logging.error(f"Ошибка при добавлении подписки: {e}")
        await message.answer(f"❌ Произошла ошибка: {e}")


def register_subscription_handlers(dp: Dispatcher, db, bot: Bot):
    """Регистрация обработчиков для управления подписками"""
    # Команды
    dp.message.register(lambda message: get_subscription_info(message, db, bot), Command("subscription"))
    dp.message.register(lambda message: add_subscription(message, db, bot), Command("add_sub"))
    
    # Callback запросы
    dp.callback_query.register(lambda call: get_subscription_info(call, db, bot), F.data == "subscription:info")
    dp.callback_query.register(lambda call: request_subscription(call, db, bot), F.data == "subscription:request")
