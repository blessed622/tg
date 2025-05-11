"""
Модуль для работы с базой данных SQLite
"""
import os
import sqlite3
import logging
import datetime
from pathlib import Path
from config import DATABASE_PATH, LOGS_PATH

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=f"{LOGS_PATH}/database.log"
)
logger = logging.getLogger(__name__)

# Создаем директории, если они не существуют
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
os.makedirs(LOGS_PATH, exist_ok=True)

class DatabaseManager:
    def __init__(self):
        """Инициализация подключения к базе данных"""
        self.conn = sqlite3.connect(DATABASE_PATH)
        self.conn.row_factory = sqlite3.Row  # Чтобы получать словари вместо кортежей
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        """Создание необходимых таблиц в базе данных"""
        try:
            # Таблица пользователей
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_admin BOOLEAN DEFAULT 0,
                subscription_start DATE,
                subscription_end DATE,
                task_limit INTEGER DEFAULT 50,
                interval_min INTEGER DEFAULT 60,
                notifications BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # Таблица задач
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_type TEXT NOT NULL,  -- 'forward' или 'message'
                status TEXT DEFAULT 'active',  -- 'active', 'paused', 'completed', 'failed'
                from_chat_id INTEGER,  -- Только для типа 'forward'
                message_id INTEGER,  -- Только для типа 'forward'
                to_chat_id INTEGER NOT NULL,
                topic_id INTEGER,  -- NULL для обычных чатов
                message_text TEXT,  -- Только для типа 'message'
                schedule TEXT NOT NULL,  -- Cron-выражение для расписания
                next_run TIMESTAMP,
                last_run TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            # Таблица истории выполнения задач
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                status TEXT NOT NULL,  -- 'success' или 'error'
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                error_message TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id) ON DELETE CASCADE
            )
            ''')
            
            # Таблица логов действий пользователя
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
            ''')
            
            self.conn.commit()
            logger.info("Таблицы базы данных успешно созданы или уже существуют")
        except Exception as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise
    
    def add_user(self, user_id, username=None, first_name=None, last_name=None, is_admin=False, days=30):
        """Добавление нового пользователя в базу данных"""
        try:
            # Проверка, существует ли пользователь
            self.cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            existing_user = self.cursor.fetchone()
            
            subscription_start = datetime.datetime.now().date()
            subscription_end = (datetime.datetime.now() + datetime.timedelta(days=days)).date()
            
            if existing_user:
                # Если пользователь существует, обновляем его данные
                self.cursor.execute('''
                UPDATE users 
                SET username = ?, first_name = ?, last_name = ?, 
                    is_admin = ?, subscription_start = ?, subscription_end = ?
                WHERE user_id = ?
                ''', (username, first_name, last_name, is_admin, subscription_start, subscription_end, user_id))
                logger.info(f"Обновлен пользователь с ID {user_id}")
            else:
                # Если пользователь не существует, добавляем его
                self.cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, is_admin, subscription_start, subscription_end)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name, is_admin, subscription_start, subscription_end))
                logger.info(f"Добавлен новый пользователь с ID {user_id}")
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении/обновлении пользователя: {e}")
            self.conn.rollback()
            return False
    
    def get_user(self, user_id):
        """Получение информации о пользователе по его ID"""
        try:
            self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = self.cursor.fetchone()
            return dict(user) if user else None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о пользователе {user_id}: {e}")
            return None
    
    def check_subscription(self, user_id):
        """Проверка активности подписки пользователя"""
        try:
            self.cursor.execute('''
            SELECT subscription_end FROM users WHERE user_id = ?
            ''', (user_id,))
            result = self.cursor.fetchone()
            
            if not result:
                return False, "Пользователь не найден"
            
            subscription_end = datetime.datetime.strptime(result['subscription_end'], '%Y-%m-%d').date()
            current_date = datetime.datetime.now().date()
            
            if current_date > subscription_end:
                return False, f"Подписка истекла {subscription_end}"
            
            days_left = (subscription_end - current_date).days
            return True, f"Подписка активна. Осталось дней: {days_left}"
        except Exception as e:
            logger.error(f"Ошибка при проверке подписки пользователя {user_id}: {e}")
            return False, f"Ошибка при проверке подписки: {str(e)}"
    
    def extend_subscription(self, user_id, days):
        """Продление подписки пользователя на указанное количество дней"""
        try:
            self.cursor.execute('''
            SELECT subscription_end FROM users WHERE user_id = ?
            ''', (user_id,))
            result = self.cursor.fetchone()
            
            if not result:
                return False, "Пользователь не найден"
            
            current_end = datetime.datetime.strptime(result['subscription_end'], '%Y-%m-%d').date()
            new_end = current_end + datetime.timedelta(days=days)
            
            self.cursor.execute('''
            UPDATE users SET subscription_end = ? WHERE user_id = ?
            ''', (new_end, user_id))
            
            self.conn.commit()
            logger.info(f"Подписка пользователя {user_id} продлена до {new_end}")
            return True, f"Подписка продлена до {new_end}"
        except Exception as e:
            logger.error(f"Ошибка при продлении подписки пользователя {user_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при продлении подписки: {str(e)}"
    
    def set_admin(self, user_id, is_admin):
        """Установка/снятие прав администратора для пользователя"""
        try:
            self.cursor.execute('''
            UPDATE users SET is_admin = ? WHERE user_id = ?
            ''', (is_admin, user_id))
            
            self.conn.commit()
            status = "назначен администратором" if is_admin else "снят с прав администратора"
            logger.info(f"Пользователь {user_id} {status}")
            return True, f"Пользователь {status}"
        except Exception as e:
            logger.error(f"Ошибка при изменении прав администратора для пользователя {user_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при изменении прав администратора: {str(e)}"
    
    def get_all_users(self):
        """Получение списка всех пользователей"""
        try:
            self.cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
            users = self.cursor.fetchall()
            return [dict(user) for user in users]
        except Exception as e:
            logger.error(f"Ошибка при получении списка пользователей: {e}")
            return []
    
    def add_task(self, user_id, task_type, to_chat_id, schedule, from_chat_id=None, 
                 message_id=None, topic_id=None, message_text=None):
        """Добавление новой задачи в базу данных"""
        try:
            # Проверяем существование пользователя
            user = self.get_user(user_id)
            if not user:
                return False, "Пользователь не найден"
            
            # Проверяем количество активных задач пользователя
            self.cursor.execute('''
            SELECT COUNT(*) as task_count FROM tasks 
            WHERE user_id = ? AND status = 'active'
            ''', (user_id,))
            result = self.cursor.fetchone()
            
            if result['task_count'] >= user['task_limit']:
                return False, f"Достигнут лимит задач ({user['task_limit']})"
            
            # Вычисляем время следующего запуска
            # В реальном проекте здесь будет более сложная логика на основе cron-выражения
            next_run = datetime.datetime.now() + datetime.timedelta(minutes=1)
            
            # Проверяем тип задачи и необходимые параметры
            if task_type == 'forward' and (not from_chat_id or not message_id):
                return False, "Для пересылки необходимо указать исходный чат и ID сообщения"
            
            if task_type == 'message' and not message_text:
                return False, "Для отправки сообщения необходимо указать текст"
            
            # Добавляем задачу
            self.cursor.execute('''
            INSERT INTO tasks (
                user_id, task_type, from_chat_id, message_id, 
                to_chat_id, topic_id, message_text, schedule, next_run
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, task_type, from_chat_id, message_id, 
                  to_chat_id, topic_id, message_text, schedule, next_run))
            
            task_id = self.cursor.lastrowid
            self.conn.commit()
            
            # Добавляем запись в лог действий пользователя
            self.add_user_log(user_id, 'create_task', f"Создана задача {task_id} типа {task_type}")
            
            logger.info(f"Добавлена новая задача ID {task_id} для пользователя {user_id}")
            return True, f"Задача создана успешно (ID: {task_id})"
        except Exception as e:
            logger.error(f"Ошибка при добавлении задачи для пользователя {user_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при добавлении задачи: {str(e)}"
    
    def get_task(self, task_id):
        """Получение информации о задаче по её ID"""
        try:
            self.cursor.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,))
            task = self.cursor.fetchone()
            return dict(task) if task else None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о задаче {task_id}: {e}")
            return None
    
    def get_user_tasks(self, user_id, status=None):
        """Получение списка задач пользователя с возможностью фильтрации по статусу"""
        try:
            query = 'SELECT * FROM tasks WHERE user_id = ?'
            params = [user_id]
            
            if status:
                query += ' AND status = ?'
                params.append(status)
            
            query += ' ORDER BY created_at DESC'
            
            self.cursor.execute(query, params)
            tasks = self.cursor.fetchall()
            return [dict(task) for task in tasks]
        except Exception as e:
            logger.error(f"Ошибка при получении задач пользователя {user_id}: {e}")
            return []
    
    def update_task_status(self, task_id, status):
        """Обновление статуса задачи"""
        try:
            self.cursor.execute('''
            UPDATE tasks SET status = ? WHERE task_id = ?
            ''', (status, task_id))
            
            self.conn.commit()
            logger.info(f"Статус задачи {task_id} изменен на {status}")
            return True, f"Статус задачи изменен на {status}"
        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса задачи {task_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при обновлении статуса: {str(e)}"
    
    def update_task_schedule(self, task_id, schedule):
        """Обновление расписания задачи"""
        try:
            # Вычисляем время следующего запуска
            next_run = datetime.datetime.now() + datetime.timedelta(minutes=1)
            
            self.cursor.execute('''
            UPDATE tasks SET schedule = ?, next_run = ? WHERE task_id = ?
            ''', (schedule, next_run, task_id))
            
            self.conn.commit()
            logger.info(f"Расписание задачи {task_id} обновлено")
            return True, "Расписание задачи обновлено"
        except Exception as e:
            logger.error(f"Ошибка при обновлении расписания задачи {task_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при обновлении расписания: {str(e)}"
    
    def delete_task(self, task_id):
        """Удаление задачи"""
        try:
            # Получаем информацию о пользователе, владеющем задачей для логирования
            self.cursor.execute('SELECT user_id FROM tasks WHERE task_id = ?', (task_id,))
            result = self.cursor.fetchone()
            
            if not result:
                return False, "Задача не найдена"
            
            user_id = result['user_id']
            
            # Удаляем задачу
            self.cursor.execute('DELETE FROM tasks WHERE task_id = ?', (task_id,))
            
            self.conn.commit()
            
            # Добавляем запись в лог действий пользователя
            self.add_user_log(user_id, 'delete_task', f"Удалена задача {task_id}")
            
            logger.info(f"Задача {task_id} удалена")
            return True, "Задача удалена"
        except Exception as e:
            logger.error(f"Ошибка при удалении задачи {task_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при удалении задачи: {str(e)}"
    
    def update_task_next_run(self, task_id, next_run):
        """Обновление времени следующего запуска задачи"""
        try:
            self.cursor.execute('''
            UPDATE tasks SET next_run = ? WHERE task_id = ?
            ''', (next_run, task_id))
            
            self.conn.commit()
            logger.info(f"Время следующего запуска задачи {task_id} обновлено на {next_run}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени следующего запуска задачи {task_id}: {e}")
            self.conn.rollback()
            return False
    
    def update_task_last_run(self, task_id):
        """Обновление времени последнего запуска задачи"""
        try:
            last_run = datetime.datetime.now()
            self.cursor.execute('''
            UPDATE tasks SET last_run = ? WHERE task_id = ?
            ''', (last_run, task_id))
            
            self.conn.commit()
            logger.info(f"Время последнего запуска задачи {task_id} обновлено на {last_run}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени последнего запуска задачи {task_id}: {e}")
            self.conn.rollback()
            return False
    
    def add_task_history(self, task_id, status, error_message=None):
        """Добавление записи в историю выполнения задач"""
        try:
            self.cursor.execute('''
            INSERT INTO task_history (task_id, status, error_message)
            VALUES (?, ?, ?)
            ''', (task_id, status, error_message))
            
            self.conn.commit()
            logger.info(f"Добавлена запись в историю выполнения задачи {task_id} со статусом {status}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении записи в историю выполнения задачи {task_id}: {e}")
            self.conn.rollback()
            return False
    
    def get_task_history(self, task_id, limit=10):
        """Получение истории выполнения задачи"""
        try:
            self.cursor.execute('''
            SELECT * FROM task_history 
            WHERE task_id = ? 
            ORDER BY executed_at DESC 
            LIMIT ?
            ''', (task_id, limit))
            history = self.cursor.fetchall()
            return [dict(item) for item in history]
        except Exception as e:
            logger.error(f"Ошибка при получении истории выполнения задачи {task_id}: {e}")
            return []
    
    def add_user_log(self, user_id, action, details=None):
        """Добавление записи в лог действий пользователя"""
        try:
            self.cursor.execute('''
            INSERT INTO user_logs (user_id, action, details)
            VALUES (?, ?, ?)
            ''', (user_id, action, details))
            
            self.conn.commit()
            logger.info(f"Добавлена запись в лог действий пользователя {user_id}: {action}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении записи в лог действий пользователя {user_id}: {e}")
            self.conn.rollback()
            return False
    
    def get_user_logs(self, user_id, limit=50):
        """Получение лога действий пользователя"""
        try:
            self.cursor.execute('''
            SELECT * FROM user_logs 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
            ''', (user_id, limit))
            logs = self.cursor.fetchall()
            return [dict(log) for log in logs]
        except Exception as e:
            logger.error(f"Ошибка при получении лога действий пользователя {user_id}: {e}")
            return []
    
    def get_tasks_for_execution(self):
        """Получение задач, которые нужно выполнить (next_run <= текущее время)"""
        try:
            current_time = datetime.datetime.now()
            self.cursor.execute('''
            SELECT * FROM tasks 
            WHERE next_run <= ? AND status = 'active'
            ''', (current_time,))
            tasks = self.cursor.fetchall()
            return [dict(task) for task in tasks]
        except Exception as e:
            logger.error(f"Ошибка при получении задач для выполнения: {e}")
            return []
    
    def toggle_user_notifications(self, user_id):
        """Включение/выключение уведомлений для пользователя"""
        try:
            # Получаем текущее состояние
            self.cursor.execute('SELECT notifications FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            
            if not result:
                return False, "Пользователь не найден"
            
            new_state = not bool(result['notifications'])
            
            # Обновляем состояние
            self.cursor.execute('''
            UPDATE users SET notifications = ? WHERE user_id = ?
            ''', (new_state, user_id))
            
            self.conn.commit()
            status = "включены" if new_state else "выключены"
            logger.info(f"Уведомления для пользователя {user_id} {status}")
            return True, f"Уведомления {status}"
        except Exception as e:
            logger.error(f"Ошибка при изменении настроек уведомлений пользователя {user_id}: {e}")
            self.conn.rollback()
            return False, f"Ошибка при изменении настроек уведомлений: {str(e)}"
    
    def get_users_with_expiring_subscription(self, days=3):
        """Получение пользователей с истекающей подпиской"""
        try:
            current_date = datetime.datetime.now().date()
            expiry_date = current_date + datetime.timedelta(days=days)
            
            self.cursor.execute('''
            SELECT * FROM users 
            WHERE subscription_end BETWEEN ? AND ? 
            AND notifications = 1
            ''', (current_date, expiry_date))
            
            users = self.cursor.fetchall()
            return [dict(user) for user in users]
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей с истекающей подпиской: {e}")
            return []
    
    def __del__(self):
        """Закрытие соединения с базой данных при уничтожении объекта"""
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
                logger.info("Соединение с базой данных закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии соединения с базой данных: {e}")

            