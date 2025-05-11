"""
Основной модуль userbot на базе Telethon
"""
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.types import ForumTopic
import datetime

from config import API_ID, API_HASH, PHONE, LOGS_PATH
from database import DatabaseManager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=f"{LOGS_PATH}/userbot.log"
)
logger = logging.getLogger(__name__)

class UserBot:
    def __init__(self):
        """Инициализация userbot-клиента Telethon"""
        self.client = TelegramClient('userbot_session', API_ID, API_HASH)
        self.db = DatabaseManager()
        self.is_running = False
        self.chats_info = {}  # Кэш информации о чатах

    async def connect(self):
        """Подключение к Telegram API"""
        logger.info("Запуск userbot-клиента...")
        await self.client.connect()
        
        # Проверка авторизации
        if not await self.client.is_user_authorized():
            logger.info(f"Отправка кода авторизации на {PHONE}")
            await self.client.send_code_request(PHONE)
            try:
                logger.info("Пожалуйста, введите код подтверждения:")
                code = input("Код подтверждения: ")
                await self.client.sign_in(PHONE, code)
            except SessionPasswordNeededError:
                # Если включена двухфакторная аутентификация
                password = input("Двухфакторная аутентификация включена. Введите пароль: ")
                await self.client.sign_in(password=password)
        
        logger.info("Userbot успешно авторизован")
        self.is_running = True
        
        # Загрузка чатов после авторизации
        await self.load_chats()
        
        # Запуск прослушивания событий
        await self.listen()
    
    async def load_chats(self):
        """Загрузка списка доступных чатов и каналов"""
        logger.info("Загрузка списка доступных чатов и каналов...")
        try:
            dialogs = await self.client(GetDialogsRequest(
                offset_date=None,
                offset_id=0,
                offset_peer=InputPeerEmpty(),
                limit=100,
                hash=0
            ))
            
            # Обновляем список чатов в кэше
            for dialog in dialogs.dialogs:
                try:
                    entity = dialog.entity
                    chat_id = entity.id
                    
                    # Форумные чаты (супергруппы с топиками)
                    if hasattr(entity, 'forum') and entity.forum:
                        # Получаем топики в форуме
                        topics = await self.client.get_topics(entity)
                        topics_dict = {}
                        
                        for topic in topics:
                            if isinstance(topic, ForumTopic):
                                topics_dict[topic.id] = {
                                    'title': topic.title,
                                    'id': topic.id
                                }
                        
                        self.chats_info[chat_id] = {
                            'title': entity.title,
                            'username': entity.username if hasattr(entity, 'username') else None,
                            'type': 'forum',
                            'topics': topics_dict
                        }
                    else:
                        # Обычные чаты/каналы
                        chat_type = 'channel' if hasattr(entity, 'broadcast') and entity.broadcast else 'group' if hasattr(entity, 'megagroup') and entity.megagroup else 'private'
                        
                        self.chats_info[chat_id] = {
                            'title': entity.title if hasattr(entity, 'title') else entity.first_name if hasattr(entity, 'first_name') else "Неизвестный чат",
                            'username': entity.username if hasattr(entity, 'username') else None,
                            'type': chat_type
                        }
                except Exception as e:
                    logger.error(f"Ошибка при обработке чата: {e}")
            
            logger.info(f"Загружено {len(self.chats_info)} чатов")
        except Exception as e:
            logger.error(f"Ошибка при загрузке чатов: {e}")
    
    async def get_chat_by_id(self, chat_id):
        """Получение информации о чате по его ID"""
        if chat_id in self.chats_info:
            return self.chats_info[chat_id]
        # Если чата нет в кэше, пробуем получить его
        try:
            entity = await self.client.get_entity(chat_id)
            chat_type = 'channel' if hasattr(entity, 'broadcast') and entity.broadcast else 'group' if hasattr(entity, 'megagroup') and entity.megagroup else 'private'
            
            chat_info = {
                'title': entity.title if hasattr(entity, 'title') else entity.first_name if hasattr(entity, 'first_name') else "Неизвестный чат",
                'username': entity.username if hasattr(entity, 'username') else None,
                'type': chat_type
            }
            
            # Проверяем, является ли чат форумом
            if hasattr(entity, 'forum') and entity.forum:
                topics = await self.client.get_topics(entity)
                topics_dict = {}
                
                for topic in topics:
                    if isinstance(topic, ForumTopic):
                        topics_dict[topic.id] = {
                            'title': topic.title,
                            'id': topic.id
                        }
                
                chat_info['type'] = 'forum'
                chat_info['topics'] = topics_dict
            
            # Сохраняем в кэш
            self.chats_info[chat_id] = chat_info
            return chat_info
        except Exception as e:
            logger.error(f"Ошибка при получении информации о чате {chat_id}: {e}")
            return None
    
    async def send_message(self, chat_id, message, topic_id=None):
        """Отправка нового сообщения в чат"""
        try:
            # Проверяем, есть ли данный чат
            chat_info = await self.get_chat_by_id(chat_id)
            if not chat_info:
                logger.error(f"Чат {chat_id} не найден")
                return False, "Чат не найден"
            
            # Если указан topic_id и чат является форумом, отправляем в топик
            if topic_id and chat_info.get('type') == 'forum':
                # Проверяем, существует ли топик
                if 'topics' in chat_info and int(topic_id) not in chat_info['topics']:
                    logger.error(f"Топик {topic_id} не найден в чате {chat_id}")
                    return False, "Топик не найден"
                
                # Отправляем сообщение в топик
                await self.client.send_message(
                    entity=chat_id,
                    message=message,
                    reply_to=int(topic_id)  # Отвечаем на сообщение топика
                )
            else:
                # Отправляем обычное сообщение
                await self.client.send_message(chat_id, message)
            
            logger.info(f"Сообщение успешно отправлено в чат {chat_id}" + (f" (топик {topic_id})" if topic_id else ""))
            return True, "Сообщение успешно отправлено"
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения в чат {chat_id}: {e}")
            return False, f"Ошибка при отправке: {str(e)}"
    
    async def forward_message(self, from_chat_id, message_id, to_chat_id, topic_id=None):
        """Пересылка сообщения между чатами"""
        try:
            # Проверяем, есть ли целевой чат
            chat_info = await self.get_chat_by_id(to_chat_id)
            if not chat_info:
                logger.error(f"Целевой чат {to_chat_id} не найден")
                return False, "Целевой чат не найден"
            
            # Получаем исходное сообщение
            message = await self.client.get_messages(from_chat_id, ids=message_id)
            if not message:
                logger.error(f"Сообщение {message_id} не найдено в чате {from_chat_id}")
                return False, "Исходное сообщение не найдено"
            
            # Если указан topic_id и чат является форумом, отправляем в топик
            if topic_id and chat_info.get('type') == 'forum':
                # Проверяем, существует ли топик
                if 'topics' in chat_info and int(topic_id) not in chat_info['topics']:
                    logger.error(f"Топик {topic_id} не найден в чате {to_chat_id}")
                    return False, "Топик не найден"
                
                # Пересылаем сообщение в топик
                await self.client.forward_messages(
                    entity=to_chat_id,
                    messages=message,
                    reply_to=int(topic_id)  # Отвечаем на сообщение топика
                )
            else:
                # Пересылаем обычное сообщение
                await self.client.forward_messages(to_chat_id, message)
            
            logger.info(f"Сообщение {message_id} успешно переслано из {from_chat_id} в {to_chat_id}" + (f" (топик {topic_id})" if topic_id else ""))
            return True, "Сообщение успешно переслано"
        except Exception as e:
            logger.error(f"Ошибка при пересылке сообщения {message_id} из {from_chat_id} в {to_chat_id}: {e}")
            return False, f"Ошибка при пересылке: {str(e)}"
    
    async def listen(self):
        """Запуск прослушивания событий"""
        logger.info("Запуск прослушивания событий userbot...")
        
        @self.client.on(events.NewMessage(pattern='/ping'))
        async def ping_handler(event):
            """Простой обработчик для проверки работы userbot"""
            if event.sender_id == OWNER_ID:
                await event.respond('Pong! Userbot работает')
                raise events.StopPropagation
        
        await self.client.run_until_disconnected()
    
    async def disconnect(self):
        """Отключение от Telegram API"""
        logger.info("Отключение userbot-клиента...")
        self.is_running = False
        await self.client.disconnect()
        logger.info("Userbot-клиент отключен")

    async def get_all_chats(self):
        """Возвращает все доступные чаты"""
        return self.chats_info

# Создаем экземпляр UserBot
userbot = UserBot()

# Функция для запуска userbot в асинхронном режиме
async def start_userbot():
    await userbot.connect()

# Функция для остановки userbot
async def stop_userbot():
    await userbot.disconnect()

# Для самостоятельного запуска
if __name__ == "__main__":
    try:
        asyncio.run(start_userbot())
    except KeyboardInterrupt:
        print("Завершение работы userbot...")
        # Остановка происходит при прерывании работы программы
