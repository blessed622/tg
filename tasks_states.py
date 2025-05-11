# bot/states/task_states.py - состояния для создания и редактирования задач автопостинга

from aiogram.fsm.state import StatesGroup, State


class TaskStates(StatesGroup):
    """Состояния для процесса создания/редактирования задачи автопостинга"""
    waiting_task_name = State()  # Ожидание ввода названия задачи
    waiting_target_chat = State()  # Ожидание ввода целевого чата
    waiting_message_text = State()  # Ожидание ввода текста сообщения
    waiting_media = State()  # Ожидание прикрепления медиа (опционально)
    waiting_schedule_type = State()  # Ожидание выбора типа расписания (интервал/время)
    waiting_interval = State()  # Ожидание ввода интервала в секундах
    waiting_time = State()  # Ожидание ввода конкретного времени
    waiting_recurring = State()  # Ожидание выбора повторения (да/нет)
    waiting_confirmation = State()  # Ожидание подтверждения создания задачи
    waiting_edit_field = State()  # Ожидание выбора поля для редактирования
