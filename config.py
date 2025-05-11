"""
Конфигурационный файл проекта
"""
import os
from pathlib import Path

# Данные для API Telegram (userbot)
API_ID = 23917116
API_HASH = "1065faddf3dc4efceaf29ae7ca9b76f4"
PHONE = "+79155653418"

# Данные для бота
BOT_TOKEN = "7753781602:AAHdjaiBwHhrGfo0bKObp9-zWb5Jg6-kIRY"

# ID владельца (администратор)
OWNER_ID = 6103389282

# Пути к файлам базы данных
BASE_DIR = Path(__file__).parent
DATABASE_PATH = os.path.join(BASE_DIR, "database", "userbot.db")
LOGS_PATH = os.path.join(BASE_DIR, "logs")

# Настройка логов
LOG_FILE = os.path.join(LOGS_PATH, "userbot.log")
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Лимиты для пользователей по умолчанию
DEFAULT_TASK_LIMIT = 50  # максимальное количество задач
DEFAULT_INTERVAL_MIN = 60  # минимальный интервал между отправками в секундах

# Время уведомления о заканчивающейся подписке (в днях)
SUBSCRIPTION_NOTIFY_DAYS = 3
