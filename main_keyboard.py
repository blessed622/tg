# bot/keyboards/main_menu.py - клавиатуры для основного меню

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_menu() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру основного меню
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    # Кнопки для основного функционала
    builder.row(
        InlineKeyboardButton(text="📋 Мои задачи", callback_data="tasks:list"),
        InlineKeyboardButton(text="➕ Создать задачу", callback_data="tasks:create")
    )
    
    builder.row(
        InlineKeyboardButton(text="💼 Мой профиль", callback_data="profile:info"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:menu")
    )
    
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show"),
        InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help:show")
    )
    
    builder.row(
        InlineKeyboardButton(text="💰 Подписка", callback_data="subscription:info")
    )
    
    return builder.as_markup()


def get_auth_menu() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для меню авторизации
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🔑 Авторизоваться", callback_data="auth:start")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔄 Проверить статус", callback_data="auth:status")
    )
    
    return builder.as_markup()


def get_subscription_menu(show_extend: bool = True) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для меню подписки
    
    Args:
        show_extend (bool): Показывать ли кнопку продления
        
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    if show_extend:
        builder.row(
            InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="subscription:request")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="💳 Оформить подписку", callback_data="subscription:request")
        )
    
    builder.row(
        InlineKeyboardButton(text="📱 Связаться с администратором", url="https://t.me/lovelymaxing")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="menu:main")
    )
    
    return builder.as_markup()


def get_tasks_menu() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для меню задач
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="➕ Создать задачу", callback_data="tasks:create")
    )
    
    builder.row(
        InlineKeyboardButton(text="📋 Активные задачи", callback_data="tasks:active"),
        InlineKeyboardButton(text="📂 Все задачи", callback_data="tasks:all")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="menu:main")
    )
    
    return builder.as_markup()


def get_task_detail_menu(task_id: int) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для детальной информации о задаче
    
    Args:
        task_id (int): ID задачи
        
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"tasks:edit:{task_id}"),
        InlineKeyboardButton(text="⏸ Приостановить", callback_data=f"tasks:pause:{task_id}")
    )
    
    builder.row(
        InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"tasks:resume:{task_id}"),
        InlineKeyboardButton(text="❌ Удалить", callback_data=f"tasks:delete:{task_id}")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 К списку задач", callback_data="tasks:list")
    )
    
    return builder.as_markup()


def get_settings_menu() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для меню настроек
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🔐 Аккаунт", callback_data="settings:account"),
        InlineKeyboardButton(text="🔔 Уведомления", callback_data="settings:notifications")
    )
    
    builder.row(
        InlineKeyboardButton(text="🕒 Часовой пояс", callback_data="settings:timezone"),
        InlineKeyboardButton(text="🧩 Форматирование", callback_data="settings:formatting")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="menu:main")
    )
    
    return builder.as_markup()
