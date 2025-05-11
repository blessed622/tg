# bot/states/auth_states.py - состояния для авторизации пользователя

from aiogram.fsm.state import StatesGroup, State


class AuthStates(StatesGroup):
    """Состояния для процесса авторизации пользователя"""
    waiting_api_id = State()  # Ожидание ввода API ID
    waiting_api_hash = State()  # Ожидание ввода API Hash
    waiting_phone = State()  # Ожидание ввода номера телефона
    waiting_code = State()  # Ожидание ввода кода подтверждения
    waiting_2fa = State()  # Ожидание ввода пароля для двухфакторной аутентификации
