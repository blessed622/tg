import sqlite3
from datetime import datetime, timedelta
from config import DB_NAME, OWNER_ID
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME)
        self.cursor = self.conn.cursor()
        self._create_tables()
        logger.info("Database initialized")

    def _create_tables(self):
        tables = {
            "users": """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    subscription_end TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
            "tasks": """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    thread_id INTEGER,
                    message_text TEXT,
                    original_message_id INTEGER,
                    schedule TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )"""
        }

        for name, sql in tables.items():
            try:
                self.cursor.execute(sql)
                self.conn.commit()
            except sqlite3.Error as e:
                logger.error(f"Error creating table {name}: {e}")
                raise

        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, is_admin) VALUES (?, TRUE)",
            (OWNER_ID,)
        )
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()

    def add_user(self, user_id, username, full_name):
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        self.conn.commit()

    def get_all_users(self):
        self.cursor.execute("SELECT * FROM users")
        return self.cursor.fetchall()

    def get_all_active_tasks(self):
        self.cursor.execute("SELECT * FROM tasks WHERE is_active = TRUE")
        return self.cursor.fetchall()

    def get_user_tasks(self, user_id):
        self.cursor.execute("SELECT * FROM tasks WHERE user_id = ?", (user_id,))
        return self.cursor.fetchall()

    def get_task(self, task_id):
        self.cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        return self.cursor.fetchone()

    def add_task(self, user_id, chat_id, thread_id, message_text, original_message_id, schedule):
        self.cursor.execute(
            """INSERT INTO tasks 
            (user_id, chat_id, thread_id, message_text, original_message_id, schedule) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, chat_id, thread_id, message_text, original_message_id, schedule)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_task_status(self, task_id, is_active):
        self.cursor.execute(
            "UPDATE tasks SET is_active = ? WHERE task_id = ?",
            (is_active, task_id)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def delete_task(self, task_id):
        self.cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def check_subscription(self, user_id):
        self.cursor.execute(
            "SELECT subscription_end FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        if not result or not result[0]:
            return False
        end_date = datetime.strptime(result[0], "%Y-%m-%d")
        return end_date > datetime.now()

    def set_subscription(self, user_id, days):
        """Установка или продление подписки"""
        try:
            self.cursor.execute(
                "SELECT subscription_end FROM users WHERE user_id = ?",
                (user_id,)
            )
            current_end = self.cursor.fetchone()

            if current_end and current_end[0]:
                new_end = datetime.strptime(current_end[0], "%Y-%m-%d") + timedelta(days=days)
            else:
                new_end = datetime.now() + timedelta(days=days)

            self.cursor.execute(
                "UPDATE users SET subscription_end = ? WHERE user_id = ?",
                (new_end.strftime("%Y-%m-%d"), user_id)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting subscription: {e}")
            return False

    def close(self):
        self.conn.close()