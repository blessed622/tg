import asyncio
import logging
import os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH, PHONE_NUMBER, USERBOT_SESSION

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def setup_userbot():
    """Инициализация и авторизация пользовательского бота"""
    try:
        # Удаление старой сессии при наличии
        session_file = f"{USERBOT_SESSION}.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info("Old session file removed")
            except Exception as e:
                logger.error(f"Error removing session file: {e}")

        # Создание клиента
        client = TelegramClient(USERBOT_SESSION, API_ID, API_HASH)
        
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.info(f"Sending code to {PHONE_NUMBER}")
            await client.send_code_request(PHONE_NUMBER)
            
            code = input("Enter the code you received: ")
            
            try:
                await client.sign_in(PHONE_NUMBER, code)
            except SessionPasswordNeededError:
                password = input("Enter your 2FA password: ")
                await client.sign_in(password=password)
        
        user = await client.get_me()
        logger.info(f"Userbot authorized as {user.first_name} (@{user.username})")
        
        await client.disconnect()
        logger.info("Setup completed successfully")

    except Exception as e:
        logger.error(f"Error during setup: {e}")


if __name__ == "__main__":
    asyncio.run(setup_userbot())