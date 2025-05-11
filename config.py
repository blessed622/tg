import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('API_ID', 23917116))
API_HASH = os.getenv('API_HASH', "1065faddf3dc4efceaf29ae7ca9b76f4")
BOT_TOKEN = os.getenv('BOT_TOKEN', "7753781602:AAHdjaiBwHhrGfo0bKObp9-zWb5Jg6-kIRY")
OWNER_ID = int(os.getenv('OWNER_ID', 6103389282))
PHONE_NUMBER = os.getenv('PHONE_NUMBER', "+79155653418")
DB_NAME = os.getenv('DB_NAME', "autoposter.db")
USERBOT_SESSION = os.getenv('USERBOT_SESSION', "userbot_session")