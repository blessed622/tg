import logging
from database import Database
from scheduler.tasks import scheduler, send_scheduled_message

logger = logging.getLogger(__name__)
db = Database()

# Минимальные и максимальные значения интервалов в секундах
MIN_INTERVAL = 20  # минимум 20 секунд
MAX_INTERVAL = 1801  # максимум ~30 минут


async def add_to_scheduler(task_id):
    """Добавляет задачу в планировщик"""
    try:
        task = db.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return False

        # Парсим интервал из строки
        try:
            interval_seconds = int(task[6])
        except (ValueError, TypeError):
            logger.error(f"Invalid interval format for task {task_id}: {task[6]}")
            return False

        # Проверяем ограничения интервала
        if interval_seconds < MIN_INTERVAL:
            logger.warning(f"Interval too small for task {task_id}, setting to minimum {MIN_INTERVAL}s")
            interval_seconds = MIN_INTERVAL
        elif interval_seconds > MAX_INTERVAL:
            logger.warning(f"Interval too large for task {task_id}, setting to maximum {MAX_INTERVAL}s")
            interval_seconds = MAX_INTERVAL

        # Удаляем существующую задачу, если она есть
        try:
            scheduler.remove_job(f"task_{task_id}")
            logger.info(f"Removed existing job for task {task_id}")
        except:
            pass

        # Добавляем новую задачу используя триггер 'interval'
        scheduler.add_job(
            send_scheduled_message,
            trigger='interval',
            seconds=interval_seconds,
            args=[task_id],
            id=f"task_{task_id}"
        )

        logger.info(f"Task {task_id} added to scheduler with interval: {interval_seconds}s")
        return True
    except Exception as e:
        logger.error(f"Error adding task {task_id} to scheduler: {e}")
        return False


async def remove_from_scheduler(task_id):
    """Удаляет задачу из планировщика"""
    try:
        job = scheduler.get_job(f"task_{task_id}")
        if job:
            scheduler.remove_job(f"task_{task_id}")
            logger.info(f"Task {task_id} removed from scheduler")
            return True
        else:
            logger.warning(f"Task {task_id} not found in scheduler")
            return False
    except Exception as e:
        logger.error(f"Error removing task {task_id} from scheduler: {e}")
        return False


async def get_next_run_time(task_id):
    """Возвращает время следующего запуска задачи"""
    try:
        job = scheduler.get_job(f"task_{task_id}")
        if job and job.next_run_time:
            return job.next_run_time
        return None
    except Exception as e:
        logger.error(f"Error getting next run time for task {task_id}: {e}")
        return None


async def pause_task(task_id):
    """Приостанавливает выполнение задачи"""
    try:
        job = scheduler.get_job(f"task_{task_id}")
        if job:
            scheduler.pause_job(f"task_{task_id}")
            logger.info(f"Task {task_id} paused")
            return True
        return False
    except Exception as e:
        logger.error(f"Error pausing task {task_id}: {e}")
        return False


async def resume_task(task_id):
    """Возобновляет выполнение задачи"""
    try:
        job = scheduler.get_job(f"task_{task_id}")
        if job:
            scheduler.resume_job(f"task_{task_id}")
            logger.info(f"Task {task_id} resumed")
            return True
        return False
    except Exception as e:
        logger.error(f"Error resuming task {task_id}: {e}")
        return False