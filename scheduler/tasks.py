from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from config import USERBOT_SESSION, API_ID, API_HASH
from database import Database
import logging
import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
db = Database()


async def send_scheduled_message(task_id):
    try:
        task = db.get_task(task_id)
        if not task or not task[7]:  # Проверка is_active
            return

        async with TelegramClient(USERBOT_SESSION, API_ID, API_HASH) as client:
            if not client.is_connected():
                await client.connect()

            if task[5]:  # original_message_id
                await client.forward_messages(task[2], task[5], from_peer=task[2])
            else:
                await client.send_message(task[2], task[4], reply_to=task[3])

            logger.info(f"Message sent to chat {task[2]}")

    except Exception as e:
        logger.error(f"Error in send_scheduled_message: {e}")
        await asyncio.sleep(5)  # Пауза при ошибке


async def schedule_all_tasks():
    try:
        tasks = db.get_all_active_tasks()
        logger.info(f"Scheduling {len(tasks)} tasks")

        for task in tasks:
            schedule = parse_schedule(task[6])
            if schedule:
                scheduler.add_job(
                    send_scheduled_message,
                    trigger='cron',
                    args=[task[0]],
                    **schedule
                )
    except Exception as e:
        logger.error(f"Error in schedule_all_tasks: {e}")


def parse_schedule(schedule_str):
    params = {}
    try:
        for part in schedule_str.split(';'):
            if '=' in part:
                key, value = part.split('=')
                params[key.strip()] = value.strip()
        return params
    except Exception as e:
        logger.error(f"Error parsing schedule: {e}")
        return None