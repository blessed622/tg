# bot/states/task_states.py - состояния для создания и редактирования задач

from aiogram.fsm.state import StatesGroup, State


class TaskStates(StatesGroup):
    """Состояния для процесса создания задачи автопостинга"""
    waiting_title = State()  # Ожидание ввода названия задачи
    waiting_description = State()  # Ожидание ввода описания задачи
    waiting_chat_id = State()  # Ожидание ввода ID чата
    waiting_message_text = State()  # Ожидание ввода текста сообщения
    waiting_interval = State()  # Ожидание ввода интервала
    waiting_media = State()  # Ожидание загрузки медиафайла (опционально)
    confirm_task = State()  # Подтверждение задачи


class TaskEditStates(StatesGroup):
    """Состояния для процесса редактирования задачи"""
    select_field = State()  # Выбор поля для редактирования
    edit_title = State()  # Изменение названия
    edit_description = State()  # Изменение описания
    edit_chat_id = State()  # Изменение ID чата
    edit_message_text = State()  # Изменение текста сообщения
    edit_interval = State()  # Изменение интервала
    edit_media = State()  # Изменение медиафайла
    confirm_edit = State()  # Подтверждение изменений
