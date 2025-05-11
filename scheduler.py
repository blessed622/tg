"""
Модуль планировщика задач на основе APScheduler
"""
import asyncio
import logging
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from croniter import croniter

from config import LOGS_PATH
from database import DatabaseManager
from userbot import userbot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=f"{LOGS_PATH}/scheduler.log"
)
logger = logging.getLogger(__name__)

class TaskScheduler:
    def __init__(self):
        """Инициализация планировщика задач"""
        self.scheduler = AsyncIOScheduler()
        self.db = DatabaseManager()
        logger.info("Планировщик задач инициализирован")
    
    async def start(self):
        """Запуск планировщика и загрузка существующих задач"""
        logger.info("Запуск планировщика задач...")
        
        # Добавляем задачу для проверки и выполнения запланированных заданий
        self.scheduler.add_job(
            self.execute_pending_tasks,
            'interval',
            minutes=1,  # Проверка каждую минуту
            id='check_tasks',
            replace_existing=True
        )
        
        # Добавляем задачу для проверки истекающих подписок
        self.scheduler.add_job(
            self.check_expiring_subscriptions,
            'cron',
            hour=10,  # Проверка каждый день в 10:00
            id='check_subscriptions',
            replace_existing=True
        )
        
        # Запускаем планировщик
        self.scheduler.start()
        logger.info("Планировщик задач запущен")
    
    async def stop(self):
        """Остановка планировщика задач"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Планировщик задач остановлен")
    
    async def execute_pending_tasks(self):
        """Проверка и выполнение задач, для которых наступило время выполнения"""
        logger.info("Проверка задач для выполнения...")
        
        try:
            # Получаем задачи для выполнения
            tasks = self.db.get_tasks_for_execution()
            if not tasks:
                logger.info("Нет задач, готовых к выполнению")
                return
            
            logger.info(f"Найдено {len(tasks)} задач для выполнения")
            
            for task in tasks:
                task_id = task['task_id']
                user_id = task['user_id']
                
                # Проверяем активна ли подписка пользователя
                subscription_active, _ = self.db.check_subscription(user_id)
                if not subscription_active:
                    logger.warning(f"Задача {task_id} не выполнена: подписка пользователя {user_id} неактивна")
                    self.db.update_task_status(task_id, 'paused')
                    self.db.add_task_history(task_id, 'error', "Подписка пользователя неактивна")
                    continue
                
                # Выполняем задачу в зависимости от типа
                if task['task_type'] == 'message':
                    success, message = await self.send_message_task(task)
                elif task['task_type'] == 'forward':
                    success, message = await self.forward_message_task(task)
                else:
                    logger.error(f"Неизвестный тип задачи: {task['task_type']}")
                    success, message = False, f"Неизвестный тип задачи: {task['task_type']}"
                
                # Обновляем информацию о выполнении задачи
                status = 'success' if success else 'error'
                self.db.add_task_history(task_id, status, None if success else message)
                self.db.update_task_last_run(task_id)
                
                # Рассчитываем время следующего выполнения
                next_run = self.calculate_next_run(task['schedule'])
                if next_run:
                    self.db.update_task_next_run(task_id, next_run)
                else:
                    # Если следующего выполнения не будет, помечаем задачу как выполненную
                    self.db.update_task_status(task_id, 'completed')
                    logger.info(f"Задача {task_id} помечена как выполненная: больше нет запланированных выполнений")
        
        except Exception as e:
            logger.error(f"Ошибка при выполнении задач: {e}")
    
    async def send_message_task(self, task):
        """Выполнение задачи отправки сообщения"""
        task_id = task['task_id']
        user_id = task['user_id']
        to_chat_id = task['to_chat_id']
        topic_id = task['topic_id']
        message_text = task['message_text']
        
        logger.info(f"Выполнение задачи {task_id} (отправка сообщения) для пользователя {user_id}")
        
        try:
            # Отправляем сообщение через userbot
            success, message = await userbot.send_message(to_chat_id, message_text, topic_id)
            
            if success:
                logger.info(f"Задача {task_id} успешно выполнена: сообщение отправлено в чат {to_chat_id}")
            else:
                logger.error(f"Ошибка при выполнении задачи {task_id}: {message}")
            
            # Отправляем уведомление пользователю, если нужно
            await self.notify_user(user_id, task_id, success, message)
            
            return success, message
        except Exception as e:
            error_message = f"Ошибка при отправке сообщения: {str(e)}"
            logger.error(f"Задача {task_id}: {error_message}")
            
            # Отправляем уведомление пользователю об ошибке
            await self.notify_user(user_id, task_id, False, error_message)
            
            return False, error_message
    
    async def forward_message_task(self, task):
        """Выполнение задачи пересылки сообщения"""
        task_id = task['task_id']
        user_id = task['user_id']
        from_chat_id = task['from_chat_id']
        message_id = task['message_id']
        to_chat_id = task['to_chat_id']
        topic_id = task['topic_id']
        
        logger.info(f"Выполнение задачи {task_id} (пересылка сообщения) для пользователя {user_id}")
        
        try:
            # Пересылаем сообщение через userbot
            success, message = await userbot.forward_message(from_chat_id, message_id, to_chat_id, topic_id)
            
            if success:
                logger.info(f"Задача {task_id} успешно выполнена: сообщение {message_id} переслано из {from_chat_id} в {to_chat_id}")
            else:
                logger.error(f"Ошибка при выполнении задачи {task_id}: {message}")
            
            # Отправляем уведомление пользователю, если нужно
            await self.notify_user(user_id, task_id, success, message)
            
            return success, message
        except Exception as e:
            error_message = f"Ошибка при пересылке сообщения: {str(e)}"
            logger.error(f"Задача {task_id}: {error_message}")
            
            # Отправляем уведомление пользователю об ошибке
            await self.notify_user(user_id, task_id, False, error_message)
            
            return False, error_message
    
    async def notify_user(self, user_id, task_id, success, message):
        """Отправка уведомления пользователю о выполнении задачи"""
        # Проверяем, включены ли уведомления у пользователя
        user = self.db.get_user(user_id)
        if not user or not user['notifications']:
            return
        
        # TODO: Отправка уведомления пользователю через Telegram-бота
        # В этой версии кода функция заглушка, так как полный код бота еще не реализован
        pass
    
    def calculate_next_run(self, schedule):
        """Вычисление времени следующего запуска по расписанию (cron-выражение)"""
        try:
            # Проверяем тип расписания
            if schedule.startswith('cron:'):
                # Cron-выражение (например, "cron:0 9 * * *" - каждый день в 9:00)
                cron_expression = schedule.replace('cron:', '')
                
                # Проверяем валидность cron-выражения
                if not croniter.is_valid(cron_expression):
                    logger.error(f"Некорректное cron-выражение: {cron_expression}")
                    return None
                
                # Вычисляем следующее время запуска
                now = datetime.datetime.now()
                cron = croniter(cron_expression, now)
                return cron.get_next(datetime.datetime)
            
            elif schedule.startswith('interval:'):
                # Интервальное расписание (например, "interval:60" - каждые 60 минут)
                try:
                    minutes = int(schedule.replace('interval:', ''))
                    return datetime.datetime.now() + datetime.timedelta(minutes=minutes)
                except ValueError:
                    logger.error(f"Некорректное значение интервала: {schedule}")
                    return None
            
            elif schedule.startswith('once:'):
                # Однократное выполнение (например, "once:2023-12-31 23:59")
                try:
                    date_str = schedule.replace('once:', '')
                    target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                    
                    # Если дата в прошлом, возвращаем None (задача не будет выполнена снова)
                    if target_date <= datetime.datetime.now():
                        return None
                    
                    return target_date
                except ValueError:
                    logger.error(f"Некорректный формат даты: {schedule}")
                    return None
            
            else:
                logger.error(f"Неизвестный формат расписания: {schedule}")
                return None
        
        except Exception as e:
            logger.error(f"Ошибка при вычислении времени следующего запуска: {e}")
            return None
    
    async def add_task(self, user_id, task_type, to_chat_id, schedule, from_chat_id=None, 
                      message_id=None, topic_id=None, message_text=None):
        """Добавление новой задачи в планировщик"""
        try:
            # Добавляем задачу в базу данных
            success, message = self.db.add_task(
                user_id, task_type, to_chat_id, schedule, 
                from_chat_id, message_id, topic_id, message_text
            )
            
            if not success:
                return success, message
            
            logger.info(f"Задача успешно добавлена: {message}")
            return success, message
        except Exception as e:
            logger.error(f"Ошибка при добавлении задачи: {e}")
            return False, f"Ошибка при добавлении задачи: {str(e)}"
    
    async def check_expiring_subscriptions(self):
        """Проверка истекающих подписок и отправка уведомлений"""
        logger.info("Проверка истекающих подписок...")
        
        try:
            # Получаем пользователей с истекающей подпиской
            users = self.db.get_users_with_expiring_subscription()
            
            if not users:
                logger.info("Нет пользователей с истекающей подпиской")
                return
            
            logger.info(f"Найдено {len(users)} пользователей с истекающей подпиской")
            
            for user in users:
                user_id = user['user_id']
                subscription_end = datetime.datetime.strptime(user['subscription_end'], '%Y-%m-%d').date()
                days_left = (subscription_end - datetime.datetime.now().date()).days
                
                logger.info(f"Отправка уведомления пользователю {user_id} об истечении подписки через {days_left} дней")
                
                # TODO: Отправка уведомления через Telegram-бота
                # В этой версии кода функция заглушка, так как полный код бота еще не реализован
        
        except Exception as e:
            logger.error(f"Ошибка при проверке истекающих подписок: {e}")

# Создаем экземпляр планировщика
scheduler = TaskScheduler()

# Функции для запуска и остановки планировщика из других модулей
async def start_scheduler():
    await scheduler.start()

async def stop_scheduler():
    await scheduler.stop()
