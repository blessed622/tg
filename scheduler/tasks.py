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

        chat_id = task[2]
        message_text = task[4]
        thread_id = task[3]  # может быть None

        try:
            # Преобразуем chat_id в числовой формат, если это не username
            try:
                if not str(chat_id).startswith('@'):
                    chat_id = int(chat_id)
            except (ValueError, AttributeError, TypeError):
                pass  # Оставляем как есть, если не удается преобразовать

            # Если задан thread_id, используем его для отправки в топик
            kwargs = {}
            if thread_id is not None:
                try:
                    thread_id = int(thread_id)
                    # В Telethon для отправки в топик используется параметр reply_to
                    kwargs["reply_to"] = thread_id
                except (ValueError, TypeError):
                    logger.error(f"Invalid thread_id format: {thread_id}")
                    thread_id = None

            # Отправляем сообщение
            result = await client.send_message(
                entity=chat_id,
                message=message_text,
                **kwargs
            )

            logger.info(f"Text message sent to chat {chat_id}, thread {thread_id}, message_id: {result.id}")
            return True
        except FloodWaitError as e:
            logger.error(f"Flood wait error: {e}, waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            return False
        except Exception as e:
            logger.error(f"Error sending text message: {e}")
            return False

    except Exception as e:
        logger.error(f"Error in send_scheduled_message: {e}")
        return False


async def schedule_all_tasks():
    try:
        # Инициализируем клиент Telethon при старте
        client = await get_client()

        # Проверка авторизации
        if not await client.is_user_authorized():
            logger.warning("Telethon client not authorized. Please authorize the userbot first.")
            return

        tasks = db.get_all_active_tasks()
        logger.info(f"Scheduling {len(tasks)} tasks")

        # Очищаем все существующие задачи из планировщика
        scheduler.remove_all_jobs()

        for task in tasks:
            interval_seconds = parse_schedule(task[6])
            if interval_seconds:
                try:
                    scheduler.add_job(
                        send_scheduled_message,
                        'interval',
                        seconds=interval_seconds,
                        args=[task[0]],
                        id=f"task_{task[0]}"
                    )
                    logger.info(f"Task {task[0]} scheduled with interval: {interval_seconds} seconds")
                except Exception as e:
                    logger.error(f"Error scheduling task {task[0]}: {e}")
            else:
                logger.error(f"Invalid schedule format for task {task[0]}: {task[6]}")
    except Exception as e:
        logger.error(f"Error in schedule_all_tasks: {e}")


def parse_schedule(schedule_str):
    """
    Преобразует строку расписания в интервал в секундах
    с учетом ограничений по интервалу (20-1800 сек)
    """
    try:
        # Парсим число секунд из строки
        interval = int(schedule_str)

        # Применяем ограничения
        MIN_INTERVAL = 20
        MAX_INTERVAL = 1801

        if interval < MIN_INTERVAL:
            logger.warning(f"Interval {interval}s too small, setting to minimum {MIN_INTERVAL}s")
            return MIN_INTERVAL
        elif interval > MAX_INTERVAL:
            logger.warning(f"Interval {interval}s too large, setting to maximum {MAX_INTERVAL}s")
            return MAX_INTERVAL

        return interval
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
            interval_seconds = parse_schedule(task[6])
            if interval_seconds:
                scheduler.add_job(
                    send_scheduled_message,
                    'interval',
                    seconds=interval_seconds,
                    args=[task[0]],
                    id=f"task_{task[0]}"
                )
                logger.info(f"Task {task_id} rescheduled")
                return True
    except Exception as e:
        logger.error(f"Error rescheduling task {task_id}: {e}")
    return False