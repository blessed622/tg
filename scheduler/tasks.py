from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from config import USERBOT_SESSION, API_ID, API_HASH
from database import Database
import logging
import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
db = Database()
client = None  # Глобальный клиент для повторного использования


async def get_client():
    """Получение экземпляра клиента Telethon"""
    global client
    if client is None or not client.is_connected():
        client = TelegramClient(USERBOT_SESSION, API_ID, API_HASH)
        await client.connect()
        logger.info("Telethon client connected")
    return client


async def send_scheduled_message(task_id):
    try:
        task = db.get_task(task_id)
        if not task or not task[7]:  # Проверка is_active
            logger.info(f"Task {task_id} is inactive or not found. Skipping.")
            return

        client = await get_client()

        # Проверка авторизации
        if not await client.is_user_authorized():
            logger.error("Client is not authorized. Message not sent.")
            return

        if task[5]:  # original_message_id (для пересылки)
            try:
                # Получаем сообщение для пересылки
                messages = await client.get_messages(task[1], ids=task[5])  # from user_id
                if messages and messages[0]:
                    await client.forward_messages(task[2], messages[0])
                    logger.info(f"Message forwarded to chat {task[2]}")
                else:
                    logger.error(f"Original message {task[5]} not found")
            except Exception as e:
                logger.error(f"Error forwarding message: {e}")
        else:  # message_text (для отправки текста)
            try:
                await client.send_message(
                    task[2],  # chat_id
                    task[4],  # message_text
                    reply_to=task[3] if task[3] else None  # thread_id
                )
                logger.info(f"Text message sent to chat {task[2]}")
            except FloodWaitError as e:
                logger.error(f"Flood wait error: {e}")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"Error sending text message: {e}")

    except Exception as e:
        logger.error(f"Error in send_scheduled_message: {e}")
        await asyncio.sleep(5)  # Пауза при ошибке


async def schedule_all_tasks():
    try:
        # Инициализируем клиент Telethon при старте
        client = await get_client()

        # Проверка авторизации
        if not await client.is_user_authorized():
            logger.warning("Telethon client not authorized. Please authorize the userbot first.")

        tasks = db.get_all_active_tasks()
        logger.info(f"Scheduling {len(tasks)} tasks")

        # Очищаем все существующие задачи из планировщика
        scheduler.remove_all_jobs()

        for task in tasks:
            schedule = parse_schedule(task[6])
            if schedule:
                try:
                    scheduler.add_job(
                        send_scheduled_message,
                        trigger='cron',
                        args=[task[0]],
                        **schedule,
                        id=f"task_{task[0]}"
                    )
                    logger.info(f"Task {task[0]} scheduled with params: {schedule}")
                except Exception as e:
                    logger.error(f"Error scheduling task {task[0]}: {e}")
            else:
                logger.error(f"Invalid schedule format for task {task[0]}: {task[6]}")
    except Exception as e:
        logger.error(f"Error in schedule_all_tasks: {e}")


def parse_schedule(schedule_str):
    """
    Преобразует строку расписания в словарь параметров для APScheduler
    Примеры:
    - day_of_week=0;hour=12;minute=0 (каждый понедельник в 12:00)
    - hour=*/2;minute=0 (каждые 2 часа)
    - minute=*/10 (каждые 10 минут)
    """
    params = {}
    try:
        for part in schedule_str.split(';'):
            if '=' in part:
                key, value = part.split('=')
                key = key.strip()
                value = value.strip()

                # Проверяем и преобразуем значения
                if key in ('minute', 'hour', 'day', 'month', 'day_of_week', 'year'):
                    params[key] = value
                else:
                    logger.warning(f"Unknown schedule parameter: {key}")

        return params
    except Exception as e:
        logger.error(f"Error parsing schedule: {e}")
        return None


async def reschedule_task(task_id):
    """Обновляет расписание для конкретной задачи"""
    try:
        # Удаляем старую задачу из планировщика, если она существует
        try:
            scheduler.remove_job(f"task_{task_id}")
        except:
            pass

        task = db.get_task(task_id)
        if task and task[7]:  # если задача существует и активна
            schedule = parse_schedule(task[6])
            if schedule:
                scheduler.add_job(
                    send_scheduled_message,
                    trigger='cron',
                    args=[task[0]],
                    **schedule,
                    id=f"task_{task[0]}"
                )
                logger.info(f"Task {task_id} rescheduled")
                return True
    except Exception as e:
        logger.error(f"Error rescheduling task {task_id}: {e}")
    return False