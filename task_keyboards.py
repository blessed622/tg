# bot/keyboards/task_keyboards.py - клавиатуры для управления задачами автопостинга

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_schedule_type_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора типа расписания
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="⏱ Интервал", callback_data="schedule:interval"),
        InlineKeyboardButton(text="🕒 Конкретное время", callback_data="schedule:time")
    )
    
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:cancel")
    )
    
    return builder.as_markup()


def get_recurring_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора повторения задачи
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✅ Да, повторять", callback_data="recurring:yes"),
        InlineKeyboardButton(text="❌ Нет, одноразово", callback_data="recurring:no")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="tasks:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:cancel")
    )
    
    return builder.as_markup()


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для подтверждения создания задачи
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="task:confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:cancel")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔄 Изменить данные", callback_data="task:edit")
    )
    
    return builder.as_markup()


def get_task_edit_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора поля для редактирования
    
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="📝 Название", callback_data="edit:name"),
        InlineKeyboardButton(text="💬 Целевой чат", callback_data="edit:chat")
    )
    
    builder.row(
        InlineKeyboardButton(text="📄 Текст", callback_data="edit:text"),
        InlineKeyboardButton(text="🖼 Медиа", callback_data="edit:media")
    )
    
    builder.row(
        InlineKeyboardButton(text="⏱ Расписание", callback_data="edit:schedule"),
        InlineKeyboardButton(text="🔄 Повторение", callback_data="edit:recurring")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="task:back_to_confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:cancel")
    )
    
    return builder.as_markup()


def get_task_list_keyboard(tasks, page=0, page_size=5) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для списка задач с пагинацией
    
    Args:
        tasks (list): Список задач
        page (int): Текущая страница
        page_size (int): Количество задач на странице
        
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    # Вычисляем общее количество страниц
    total_pages = (len(tasks) + page_size - 1) // page_size
    
    # Вычисляем начальный и конечный индекс для текущей страницы
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(tasks))
    
    # Добавляем кнопки для задач на текущей странице
    for i in range(start_idx, end_idx):
        task = tasks[i]
        # Отображаем имя задачи и её статус (активна/неактивна)
        status = "✅" if task["is_active"] == 1 else "⏸"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {task['name']}",
                callback_data=f"task:view:{task['id']}"
            )
        )
    
    # Добавляем кнопки навигации
    nav_buttons = []
    
    # Кнопка "Назад", если это не первая страница
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"tasks:page:{page-1}")
        )
    
    # Информация о текущей странице
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="tasks:noop")
    )
    
    # Кнопка "Вперед", если это не последняя страница
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="➡️", callback_data=f"tasks:page:{page+1}")
        )
    
    # Добавляем кнопки навигации
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Добавляем кнопки действий
    builder.row(
        InlineKeyboardButton(text="➕ Создать задачу", callback_data="tasks:create")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="tasks:refresh"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")
    )
    
    return builder.as_markup()


def get_task_actions_keyboard(task_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для действий с конкретной задачей
    
    Args:
        task_id (int): ID задачи
        is_active (bool): Активна ли задача
        
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    # Кнопка приостановки/возобновления в зависимости от статуса
    if is_active:
        builder.row(
            InlineKeyboardButton(text="⏸ Приостановить", callback_data=f"task:pause:{task_id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"task:resume:{task_id}")
        )
    
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"task:edit:{task_id}"),
        InlineKeyboardButton(text="❌ Удалить", callback_data=f"task:delete:{task_id}")
    )
    
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data=f"task:stats:{task_id}")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 К списку задач", callback_data="tasks:list")
    )
    
    return builder.as_markup()


def get_task_edit_field_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора поля для редактирования существующей задачи
    
    Args:
        task_id (int): ID задачи
        
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="📝 Название", callback_data=f"edit:{task_id}:name"),
        InlineKeyboardButton(text="💬 Целевой чат", callback_data=f"edit:{task_id}:chat")
    )
    
    builder.row(
        InlineKeyboardButton(text="📄 Текст", callback_data=f"edit:{task_id}:text"),
        InlineKeyboardButton(text="🖼 Медиа", callback_data=f"edit:{task_id}:media")
    )
    
    builder.row(
        InlineKeyboardButton(text="⏱ Расписание", callback_data=f"edit:{task_id}:schedule"),
        InlineKeyboardButton(text="🔄 Повторение", callback_data=f"edit:{task_id}:recurring")
    )
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"task:view:{task_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:list")
    )
    
    return builder.as_markup()


def get_delete_confirmation_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для подтверждения удаления задачи
    
    Args:
        task_id (int): ID задачи
        
    Returns:
        InlineKeyboardMarkup: Объект клавиатуры
    """
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"task:delete_confirm:{task_id}"),
        InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"task:view:{task_id}")
    )
    
    return builder.as_markup()
