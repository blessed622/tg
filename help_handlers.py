# bot/handlers/help_handlers.py - обработчики для раздела помощи

from aiogram import types, F, Router, Dispatcher, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_menu import get_main_menu


async def help_command(message: types.Message | types.CallbackQuery, state: FSMContext, db, bot: Bot):
    """Обработчик команды /help - показывает справку по боту"""
    # Определяем тип входящего сообщения
    if isinstance(message, types.CallbackQuery):
        await message.answer()  # Убираем часы на кнопке
        message = message.message
    
    # Содержимое справки
    help_text = (
        "🤖 <b>Справка по использованию бота автопостинга</b>\n\n"
        "<b>Основные команды:</b>\n"
        "• /start - начать работу с ботом\n"
        "• /help - показать эту справку\n"
        "• /auth - авторизация в системе\n"
        "• /subscription - информация о подписке\n\n"
        
        "<b>Порядок работы с ботом:</b>\n"
        "1. Авторизуйтесь в системе с помощью API ID и API Hash\n"
        "   (как получить API ID и Hash - см. ниже)\n"
        "2. Оформите подписку, написав @lovelymaxing\n"
        "3. Создайте задачу автопостинга, указав:\n"
        "   - Целевой чат/канал\n"
        "   - Текст сообщения\n"
        "   - Интервал отправки (от 20 до 999 секунд)\n\n"
        
        "<b>Как получить API ID и API Hash:</b>\n"
        "1. Перейдите на сайт https://my.telegram.org\n"
        "2. Войдите в свой аккаунт\n"
        "3. Перейдите в раздел 'API development tools'\n"
        "4. Создайте новое приложение, если требуется\n"
        "5. Скопируйте API ID (цифры) и API Hash (буквы и цифры)\n\n"
        
        "<b>Возможности автопостинга:</b>\n"
        "• Отправка сообщений с заданным интервалом\n"
        "• Отправка в любые каналы, где вы являетесь администратором\n"
        "• Отправка в любые группы, где вы являетесь участником\n"
        "• Отправка в личные чаты\n"
        "• Поддержка форматирования текста (HTML)\n\n"
        
        "<b>По всем вопросам обращайтесь:</b>\n"
        "• @lovelymaxing - техническая поддержка и оплата подписки\n\n"
        
        "💡 <b>Совет:</b> Убедитесь, что бот имеет необходимые права для отправки сообщений в указанных каналах и группах."
    )
    
    await message.answer(help_text, reply_markup=get_main_menu())


def register_help_handlers(dp: Dispatcher, db, bot: Bot):
    """Регистрация обработчиков помощи"""
    # Команда help
    dp.message.register(lambda message, state: help_command(message, state, db, bot), Command("help"))
    
    # Callback запросы
    dp.callback_query.register(lambda call, state: help_command(call, state, db, bot), F.data == "help:show")
