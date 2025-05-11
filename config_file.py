# config.py - настройки и конфигурация проекта

import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "7753781602:AAHdjaiBwHhrGfo0bKObp9-zWb5Jg6-kIRY")

# ID владельца бота
OWNER_ID = int(os.getenv("OWNER_ID", "6103389282"))

# Директория для хранения файлов сессий
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")

# Ключ для шифрования чувствительных данных
# ВАЖНО: в продакшене используйте сложный случайный ключ длиной 32 символа
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "your_secret_key_should_be_32_chars")

# Путь к файлу базы данных
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/autopost.db")

# Максимальное количество задач для стандартной подписки
MAX_TASKS_STANDARD = int(os.getenv("MAX_TASKS_STANDARD", "20"))

# Минимальный интервал между сообщениями в секундах
MIN_INTERVAL = int(os.getenv("MIN_INTERVAL", "20"))

# Максимальный интервал между сообщениями в секундах
MAX_INTERVAL = int(os.getenv("MAX_INTERVAL", "999"))

# Длительность стандартной подписки в днях
SUBSCRIPTION_DURATION = int(os.getenv("SUBSCRIPTION_DURATION", "30"))

# Стоимость подписки в рублях
SUBSCRIPTION_PRICE = int(os.getenv("SUBSCRIPTION_PRICE", "500"))

# Контакт администратора для связи по поводу подписки
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "lovelymaxing")

# Настройки логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")

# Настройки планировщика задач
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/Moscow")
SCHEDULER_MISFIRE_GRACE_TIME = int(os.getenv("SCHEDULER_MISFIRE_GRACE_TIME", "60"))
