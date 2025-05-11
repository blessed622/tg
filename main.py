import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError
from config import BOT_TOKEN, USERBOT_SESSION
from handlers import user, admin
from scheduler import scheduler, schedule_all_tasks
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    # Очистка старых сессий
    session_file = f"{USERBOT_SESSION}.session"
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
            logger.info("Old session file removed")
        except Exception as e:
            logger.error(f"Error removing session file: {e}")

    try:
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()

        dp.include_router(user.router)
        dp.include_router(admin.router)

        scheduler.start()
        await schedule_all_tasks()

        logger.info("Bot starting...")
        await dp.start_polling(bot)

    except TelegramConflictError:
        logger.error("Another bot instance is already running!")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        if 'scheduler' in locals():
            scheduler.shutdown()
        if 'bot' in locals():
            await bot.session.close()
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())