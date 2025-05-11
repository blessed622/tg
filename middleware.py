# bot/middlewares.py - промежуточные обработчики запросов

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Dict, Any, Awaitable, Callable
import logging
from datetime import datetime

from bot.handlers.subscription import check_subscription
from bot.keyboards.main_menu import get_subscription_menu


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware для проверки активной подписки пользователя перед выполнением запросов
    
    Пропускает только команды и callback-запросы, которые не требуют активной подписки
    """
    
    def __init__(self, db):
        self.db = db
        
        # Список допустимых команд и callback-запросов без подписки
        self.allowed_commands = [
            "/start", "/help", "/auth", "/subscription",
            "auth:start", "auth:status", 
            "subscription:info", "subscription:request"
        ]
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем идентификатор пользователя
        user_id = event.from_user.id
        
        # Проверяем тип входящего события
        if isinstance(event, Message):
            # Для команд проверяем, разрешена ли она без подписки
            if event.text and event.text.startswith('/'):
                command = event.text.split()[0].lower()
                if command in self.allowed_commands:
                    return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            # Для callback-запросов проверяем, разрешен ли он без подписки
            if event.data in self.allowed_commands:
                return await handler(event, data)
        
        # Проверяем наличие активной подписки
        is_active, _ = await check_subscription(user_id, self.db)
        
        if is_active:
            # Если подписка активна, продолжаем обработку запроса
            return await handler(event, data)
        else:
            # Если подписки нет, отправляем сообщение о необходимости оформления
            if isinstance(event, CallbackQuery):
                await event.answer("Для использования этой функции необходима подписка", show_alert=True)
                
                # Отправляем сообщение с информацией о подписке
                await event.message.answer(
                    "❌ <b>Для использования этой функции необходима подписка</b>\n\n"
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
            elif isinstance(event, Message):
                await event.answer(
                    "❌ <b>Для использования этой функции необходима подписка</b>\n\n"
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
            
            # Не продолжаем обработку запроса
            return
