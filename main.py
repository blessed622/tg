import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from config import BOT_TOKEN, USERBOT_SESSION, API_ID, API_HASH
from handlers import user_router, admin_router
from scheduler import scheduler, schedule_all_tasks
from telethon import TelegramClient
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def check_userbot_auth():
    """Проверка авторизации клиента Telethon"""
    session_file = f"{USERBOT_SESSION}.session"
    if not os.path.exists(session_file):
        logger.warning("Userbot session file not found. Please run the userbot_setup.py first.")
        return False

    try:
        client = TelegramClient(USERBOT_SESSION, API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            logger.warning("Userbot is not authorized. Please run the userbot_setup.py first.")
            await client.disconnect()
            return False

        await client.disconnect()
        return True
    except Exception as e:
        logger.error(f"Error checking userbot authorization: {e}")
        return False


async def main():
    try:
        # Проверка авторизации юзербота
        userbot_ready = await check_userbot_auth()
        if not userbot_ready:
            logger.warning("Userbot not authorized. Some features may not work properly.")

        # Инициализация бота
        bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
        dp = Dispatcher()

        # Регистрация роутеров
        dp.include_router(user_router)
        dp.include_router(admin_router)

        # Запуск планировщика
        scheduler.start()
        await schedule_all_tasks()

        # Запуск бота
        logger.info("Bot starting...")
        await dp.start_polling(bot)

    except TelegramConflictError:
        logger.error("Another bot instance is already running!")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        # Остановка планировщика при выходе
        if 'scheduler' in locals():
            scheduler.shutdown()
        # Закрытие сессии бота
        if 'bot' in locals():
            await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())