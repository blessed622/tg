import os
import sys
import io
import logging
import asyncio
import json
import random
import time
from aiogram.client.default import DefaultBotProperties
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.enums import ParseMode
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError, FloodWaitError

# Настройка кодировки
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Расширенное логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tg_poster_bot.log", encoding='utf-8', mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
CONFIG_FILE = "poster_config.json"
PHOTOS_DIR = "photos"
os.makedirs(PHOTOS_DIR, exist_ok=True)


class AuthStates(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()


class PosterStates(StatesGroup):
    main_menu = State()
    waiting_for_group_link = State()
    waiting_for_groups_list = State()
    selecting_topic = State()
    entering_message = State()
    uploading_photo = State()
    setting_interval = State()
    confirm_add = State()
    confirm_mass_add = State()


class TelegramPosterBot:
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher(storage=MemoryStorage())
        self.telethon_client = None
        self.active_tasks = {}
        self.task_queue = asyncio.Queue()
        self.config = self.load_config()
        self.current_mass_data = {}
        self.register_handlers()

    def load_config(self) -> Dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига: {e}", exc_info=True)
        return {"tasks": {}, "user_id": None, "notifications_enabled": True}

    def save_config(self) -> None:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфига: {e}", exc_info=True)

    async def create_telethon_client(self, api_id: int, api_hash: str, phone: str) -> bool:
        try:
            if self.telethon_client and self.telethon_client.is_connected():
                await self.telethon_client.disconnect()

            session_name = f"session_{phone}"
            self.telethon_client = TelegramClient(session_name, api_id, api_hash)

            await self.telethon_client.connect()
            logger.info(f"Telethon клиент создан, подключение установлено: {await self.telethon_client.is_connected()}")

            if not await self.telethon_client.is_user_authorized():
                logger.info(f"Пользователь не авторизован, отправляем запрос кода...")
                result = await self.telethon_client.send_code_request(phone)
                logger.info(f"Код запрошен: {result}")
                return False

            logger.info("Пользователь авторизован")
            return True

        except errors.PhoneNumberInvalidError:
            logger.error("Неверный номер телефона")
            return False
        except errors.PhoneNumberBannedError:
            logger.error("Номер телефона заблокирован")
            return False
        except errors.FloodWaitError as e:
            logger.error(f"Flood wait: {e.seconds} секунд")
            return False
        except Exception as e:
            logger.error(f"Ошибка создания клиента Telethon: {e}", exc_info=True)
            return False

    async def find_topics(self, group_username: str) -> Tuple[List[Dict], Optional[str]]:
        try:
            if not self.telethon_client or not await self.telethon_client.is_user_authorized():
                return [], "Клиент не авторизован"

            entity = await self.telethon_client.get_entity(f"@{group_username}")

            try:
                result = await self.telethon_client(GetForumTopicsRequest(
                    peer=entity,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=100
                ))

                topics = []
                for topic in result.topics:
                    if hasattr(topic, 'title') and topic.title:
                        topics.append({
                            'id': topic.id,
                            'name': topic.title
                        })

                return topics, None
            except ChatAdminRequiredError:
                return [], "Требуются права администратора"
            except ChannelPrivateError:
                return [], "Приватная группа"
            except Exception as e:
                return [], str(e)

        except Exception as e:
            logger.error(f"Ошибка при получении топиков: {e}", exc_info=True)
            return [], str(e)

    def get_topics_keyboard(self, topics: List[Dict]) -> InlineKeyboardMarkup:
        buttons = []
        for topic in topics[:20]:  # Ограничиваем до 20 топиков
            buttons.append([
                InlineKeyboardButton(
                    text=topic['name'],
                    callback_data=f"topic_{topic['id']}_{topic['name']}"
                )
            ])

        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def start(self):
        # Запуск обработчика задач
        asyncio.create_task(self.task_worker())

        # Загрузка активных задач
        for task_id, task_data in self.config.get('tasks', {}).items():
            if task_data.get('active', False):
                self.active_tasks[task_id] = True
                await self.task_queue.put((task_id, task_data))
                logger.info(f"Автозагрузка задачи {task_id}")

        # Уведомление владельца
        if self.config.get('user_id'):
            try:
                await self.bot.send_message(
                    self.config['user_id'],
                    "🤖 Telegram Poster Bot запущен!",
                    reply_markup=self.get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления владельца: {e}")

        await self.dp.start_polling(self.bot)

    def register_handlers(self):
        # Обработчики авторизации
        @self.dp.message(F.text == '/start')
        async def cmd_start(message: types.Message, state: FSMContext):
            if not self.config.get('user_id'):
                self.config['user_id'] = message.from_user.id
                self.save_config()

            if message.from_user.id != self.config.get('user_id'):
                await message.answer("🚫 Бот доступен только владельцу")
                return

            if not self.telethon_client or not await self.check_authorization():
                await state.set_state(AuthStates.waiting_for_api_id)
                await message.answer(
                    "🔐 Для начала работы необходимо авторизоваться.\n"
                    "Введите ваш API ID (можно получить на my.telegram.org):"
                )
            else:
                await state.set_state(PosterStates.main_menu)
                await message.answer(
                    "👋 Добро пожаловать в Telegram Poster Bot!",
                    reply_markup=self.get_main_menu_keyboard()
                )

        @self.dp.message(AuthStates.waiting_for_api_id)
        async def process_api_id(message: types.Message, state: FSMContext):
            try:
                api_id = int(message.text)
                await state.update_data(api_id=api_id)
                await state.set_state(AuthStates.waiting_for_api_hash)
                await message.answer("Введите ваш API HASH:")
            except ValueError:
                await message.answer("Пожалуйста, введите корректный API ID (число):")

        @self.dp.message(AuthStates.waiting_for_api_hash)
        async def process_api_hash(message: types.Message, state: FSMContext):
            api_hash = message.text.strip()
            await state.update_data(api_hash=api_hash)
            await state.set_state(AuthStates.waiting_for_phone)
            await message.answer("Введите ваш номер телефона в международном формате (например, +79123456789):")

        @self.dp.message(AuthStates.waiting_for_phone)
        async def process_phone(message: types.Message, state: FSMContext):
            phone = message.text.strip()
            user_data = await state.get_data()

            try:
                await state.update_data(phone=phone)

                api_id = user_data['api_id']
                api_hash = user_data['api_hash']

                # Отправляем информацию пользователю
                wait_msg = await message.answer("⌛ Подключение к серверам Telegram...")

                # Создаем клиент Telethon и проверяем авторизацию
                is_authorized = await self.create_telethon_client(api_id, api_hash, phone)

                await wait_msg.delete()

                if is_authorized:
                    await state.set_state(PosterStates.main_menu)
                    await message.answer(
                        "✅ Авторизация успешна! Сессия восстановлена.",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                else:
                    # Показываем информацию о процессе ввода кода
                    code_msg = await message.answer(
                        "📱 Telegram отправил код подтверждения на ваш телефон.\n"
                        "⚠️ Важно: введите только цифры кода без дополнительных символов.\n"
                        "Например, если код '12-345', введите '12345'"
                    )

                    await state.set_state(AuthStates.waiting_for_code)
                    await state.update_data(code_msg_id=code_msg.message_id)

            except Exception as e:
                logger.error(f"Ошибка авторизации: {e}", exc_info=True)
                await message.answer(
                    f"🚫 Ошибка авторизации: {str(e)}\n"
                    "Попробуйте снова /start"
                )
                await state.clear()

        @self.dp.callback_query(F.data == 'restart_auth')
        async def restart_auth(callback_query: types.CallbackQuery, state: FSMContext):
            await callback_query.answer()
            await state.clear()
            await state.set_state(AuthStates.waiting_for_api_id)
            await callback_query.message.answer(
                "🔐 Для начала работы необходимо авторизоваться.\n"
                "Введите ваш API ID (можно получить на my.telegram.org):"
            )

        @self.dp.message(AuthStates.waiting_for_code)
        async def process_code(message: types.Message, state: FSMContext):
            code = message.text.strip()

            # Удаляем из кода все не-цифры
            code = ''.join(c for c in code if c.isdigit())

            user_data = await state.get_data()

            try:
                if not code.isdigit():
                    await message.answer("⚠️ Код должен содержать только цифры. Попробуйте снова:")
                    return

                # Пытаемся войти с использованием кода
                wait_msg = await message.answer("⌛ Отправка кода в Telegram...")

                try:
                    # Используем более надежный способ ввода кода
                    await self.telethon_client.sign_in(
                        phone=user_data['phone'],
                        code=code
                    )

                    logger.info("Код авторизации успешно отправлен")

                    # Проверяем авторизацию
                    if await self.telethon_client.is_user_authorized():
                        await wait_msg.delete()
                        await state.set_state(PosterStates.main_menu)
                        await message.answer(
                            "✅ Авторизация успешна!",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                    else:
                        await wait_msg.delete()
                        await message.answer(
                            "❌ Авторизация не удалась. Возможно требуется пароль 2FA."
                        )
                        await state.set_state(AuthStates.waiting_for_password)
                        await message.answer("🔑 Введите пароль двухфакторной аутентификации:")

                except errors.SessionPasswordNeededError:
                    await wait_msg.delete()
                    await state.set_state(AuthStates.waiting_for_password)
                    await message.answer("🔑 Введите пароль двухфакторной аутентификации:")

                except errors.PhoneCodeInvalidError:
                    await wait_msg.delete()
                    await message.answer(
                        "❌ Неверный код подтверждения.\n"
                        "Пожалуйста, введите правильный код, только цифры:"
                    )

                except errors.PhoneCodeExpiredError:
                    await wait_msg.delete()
                    logger.warning("Код подтверждения истек")

                    new_code_msg = await message.answer("⌛ Код устарел. Запрашиваем новый код...")

                    try:
                        # Запрашиваем новый код
                        await self.telethon_client.send_code_request(user_data['phone'])
                        await new_code_msg.edit_text(
                            "🔄 Telegram отправил новый код. Пожалуйста, введите его:"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при запросе нового кода: {e}")
                        await new_code_msg.edit_text(
                            f"❌ Не удалось запросить новый код: {str(e)}\n"
                            "Попробуйте снова командой /start"
                        )
                        await state.clear()

            except Exception as e:
                logger.error(f"Неизвестная ошибка при вводе кода: {e}", exc_info=True)
                await message.answer(
                    f"⚠️ Произошла ошибка: {str(e)}.\n"
                    "Попробуйте снова командой /start"
                )
                await state.clear()

        @self.dp.message(AuthStates.waiting_for_password)
        async def process_password(message: types.Message, state: FSMContext):
            password = message.text.strip()

            try:
                wait_msg = await message.answer("⌛ Проверка пароля...")

                # Пытаемся войти с использованием 2FA пароля
                await self.telethon_client.sign_in(password=password)

                if await self.telethon_client.is_user_authorized():
                    await wait_msg.delete()
                    await state.set_state(PosterStates.main_menu)
                    await message.answer(
                        "✅ Авторизация с 2FA успешна!",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                else:
                    await wait_msg.delete()
                    await message.answer(
                        "❌ Авторизация не удалась. Попробуйте снова /start"
                    )
                    await state.clear()

            except errors.PasswordHashInvalidError:
                await message.answer("❌ Неверный пароль. Пожалуйста, попробуйте снова:")

            except Exception as e:
                logger.error(f"Ошибка при вводе пароля 2FA: {e}", exc_info=True)
                await message.answer(
                    f"⚠️ Произошла ошибка: {str(e)}.\n"
                    "Попробуйте снова командой /start"
                )
                await state.clear()

                # Основные обработчики
                @self.dp.callback_query(F.data == 'add_task', PosterStates.main_menu)
                async def process_add_task(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="➕ Одиночная задача", callback_data="single_task"),
                            InlineKeyboardButton(text="📋 Массовое добавление", callback_data="mass_task")
                        ],
                        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
                    ])
                    await state.set_state(PosterStates.waiting_for_group_link)
                    await callback_query.message.answer(
                        "Выберите тип задачи:",
                        reply_markup=markup
                    )

                @self.dp.callback_query(F.data == 'single_task', PosterStates.waiting_for_group_link)
                async def process_single_task(callback_query: types.CallbackQuery):
                    await callback_query.answer()
                    await callback_query.message.answer(
                        "Введите имя группы (без @, например: group_name)\n"
                        "Вы должны быть участником этой группы."
                    )

                @self.dp.callback_query(F.data == 'mass_task', PosterStates.waiting_for_group_link)
                async def process_mass_task(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    await state.set_state(PosterStates.waiting_for_groups_list)
                    await callback_query.message.answer(
                        "📋 Введите список групп для массовой рассылки (по одной в строке, без @):\n"
                        "Пример:\n"
                        "group1\n"
                        "group2\n"
                        "group3\n\n"
                        "Можно добавить до 50 групп за раз."
                    )

                @self.dp.message(PosterStates.waiting_for_groups_list)
                async def process_groups_list(message: types.Message, state: FSMContext):
                    groups = [g.strip() for g in message.text.split('\n') if g.strip()]

                    if not groups:
                        await message.answer("Список групп пуст. Попробуйте снова.")
                        return

                    if len(groups) > 50:
                        await message.answer("⚠️ Максимум 50 групп за раз. Будут использованы первые 50.")
                        groups = groups[:50]

                    await state.update_data(groups_list=groups)
                    await state.set_state(PosterStates.entering_message)
                    await message.answer(
                        f"✅ Получено {len(groups)} групп. Теперь введите текст сообщения:"
                    )

                @self.dp.message(PosterStates.waiting_for_group_link)
                async def process_group_link(message: types.Message, state: FSMContext):
                    group_username = message.text.strip()
                    if group_username.startswith('@'):
                        group_username = group_username[1:]

                    if not group_username:
                        await message.answer("Имя группы не может быть пустым.")
                        return

                    await state.update_data(group_username=group_username)

                    try:
                        topics, error = await self.find_topics(group_username)

                        if error or not topics:
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✅ Без топика",
                                                         callback_data=f"no_topic_{group_username}"),
                                    InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")
                                ]
                            ])

                            await message.answer(
                                f"В группе @{group_username} не найдено топиков или ошибка: {error}\n"
                                "Использовать без топика?",
                                reply_markup=markup
                            )
                            return

                        await state.set_state(PosterStates.selecting_topic)
                        await message.answer(
                            f"Найдено {len(topics)} топиков в @{group_username}. Выберите:",
                            reply_markup=self.get_topics_keyboard(topics)
                        )
                    except Exception as e:
                        logger.error(f"Ошибка поиска топиков: {e}", exc_info=True)
                        await message.answer(f"🚫 Ошибка: {e}\nПопробуйте другую группу.")

                @self.dp.callback_query(F.data.startswith('no_topic_'))
                async def process_no_topic(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    group_username = callback_query.data.replace('no_topic_', '')

                    await state.update_data(
                        group_username=group_username,
                        topic_id=0,
                        topic_name="Без топика"
                    )
                    await state.set_state(PosterStates.entering_message)
                    await callback_query.message.answer(
                        f"Выбрана группа @{group_username} без топика. Введите текст сообщения:"
                    )

                @self.dp.callback_query(F.data.startswith('topic_'), PosterStates.selecting_topic)
                async def process_topic_selection(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    _, topic_id, topic_name = callback_query.data.split('_', 2)

                    await state.update_data(topic_id=int(topic_id), topic_name=topic_name)
                    await state.set_state(PosterStates.entering_message)
                    await callback_query.message.answer(
                        "Введите текст сообщения:"
                    )

                @self.dp.message(PosterStates.entering_message)
                async def process_message_text(message: types.Message, state: FSMContext):
                    await state.update_data(message=message.html_text)

                    data = await state.get_data()
                    if 'groups_list' in data:
                        await state.set_state(PosterStates.setting_interval)
                        await message.answer(
                            "Введите интервал отправки в секундах (между сообщениями в разных группах):\n"
                            "Рекомендуемый минимум: 30 секунд",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="🔄 Авто (30-60 сек)", callback_data="auto_interval")
                            ]])
                        )
                    else:
                        await state.set_state(PosterStates.uploading_photo)
                        await message.answer(
                            "Отправьте фото или нажмите 'Пропустить'",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="⏩ Пропустить", callback_data="skip_photo")
                            ]])
                        )

                @self.dp.callback_query(F.data == 'auto_interval', PosterStates.setting_interval)
                async def process_auto_interval(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    await state.update_data(interval=random.randint(30, 60))
                    await self.confirm_mass_add(callback_query.from_user.id, state)

                @self.dp.message(PosterStates.setting_interval)
                async def process_interval(message: types.Message, state: FSMContext):
                    try:
                        interval = int(message.text.strip())
                        if interval < 5:
                            await message.answer("⚠️ Минимальный интервал - 5 секунд. Установлено 5.")
                            interval = 5
                    except ValueError:
                        await message.answer("Введите число (интервал в секундах):")
                        return

                    data = await state.get_data()
                    if 'groups_list' in data:
                        await state.update_data(interval=interval)
                        await self.confirm_mass_add(message.from_user.id, state)
                    else:
                        await state.update_data(interval=interval)
                        await self.confirm_single_add(message.from_user.id, state)

                async def confirm_mass_add(self, user_id: int, state: FSMContext):
                    data = await state.get_data()
                    groups_count = len(data['groups_list'])
                    interval = data.get('interval', 30)
                    total_time = (groups_count * interval) / 60

                    confirm_text = (
                        f"📋 <b>Массовое добавление задач</b>\n\n"
                        f"🔢 Количество групп: {groups_count}\n"
                        f"⏱ Интервал между отправками: {interval} сек\n"
                        f"🕒 Примерное время полной рассылки: {total_time:.1f} мин\n\n"
                        f"📝 <b>Текст сообщения:</b>\n"
                        f"{data['message']}\n\n"
                        f"Подтверждаете создание {groups_count} задач?"
                    )

                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_mass_add"),
                            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_mass_add")
                        ]
                    ])

                    await state.set_state(PosterStates.confirm_mass_add)
                    await self.bot.send_message(
                        user_id,
                        confirm_text,
                        reply_markup=markup
                    )

                @self.dp.callback_query(F.data == 'confirm_mass_add', PosterStates.confirm_mass_add)
                async def process_confirm_mass_add(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    data = await state.get_data()

                    created_count = 0
                    for group in data['groups_list']:
                        try:
                            task_id = self.generate_task_id()
                            task_data = {
                                "group_username": group,
                                "topic_id": data.get('topic_id', 0),
                                "topic_name": data.get('topic_name', "Без топика"),
                                "message": data['message'],
                                "photo_path": data.get('photo_path'),
                                "interval": data['interval'],
                                "active": True,
                                "last_posted": None
                            }

                            if 'tasks' not in self.config:
                                self.config['tasks'] = {}
                            self.config['tasks'][task_id] = task_data

                            self.active_tasks[task_id] = True
                            await self.task_queue.put((task_id, task_data))
                            created_count += 1

                            logger.info(f"Создана массовая задача {task_id} для @{group}")

                        except Exception as e:
                            logger.error(f"Ошибка создания задачи для @{group}: {e}", exc_info=True)

                    self.save_config()
                    await state.clear()
                    await state.set_state(PosterStates.main_menu)

                    await callback_query.message.answer(
                        f"✅ Успешно создано {created_count}/{len(data['groups_list'])} задач!",
                        reply_markup=self.get_main_menu_keyboard()
                    )

                @self.dp.callback_query(F.data == 'list_tasks')
                async def process_list_tasks(callback_query: types.CallbackQuery):
                    await callback_query.answer()

                    if not self.config.get('tasks'):
                        await callback_query.message.answer(
                            "У вас пока нет задач.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    await callback_query.message.answer(
                        "📋 Список ваших задач:",
                        reply_markup=self.get_tasks_keyboard(self.config['tasks'])
                    )

                @self.dp.callback_query(F.data.startswith('task_info_'))
                async def process_task_info(callback_query: types.CallbackQuery):
                    await callback_query.answer()
                    task_id = callback_query.data.replace('task_info_', '')

                    if task_id not in self.config.get('tasks', {}):
                        await callback_query.message.answer(
                            "Задача не найдена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    task = self.config['tasks'][task_id]
                    status = "🟢 Активна" if self.active_tasks.get(task_id, False) else "🔴 Остановлена"

                    msg = (
                        f"📌 <b>Информация о задаче</b>\n\n"
                        f"👥 <b>Группа:</b> @{task['group_username']}\n"
                        f"📚 <b>Топик:</b> {task['topic_name']}\n"
                        f"🔄 <b>Интервал:</b> {task['interval']} сек\n"
                        f"🔘 <b>Статус:</b> {status}\n"
                        f"⏱ <b>Последняя отправка:</b> {task.get('last_posted', 'еще не было')}\n\n"
                        f"📝 <b>Текст сообщения:</b>\n"
                        f"{task['message']}"
                    )

                    await callback_query.message.answer(
                        msg,
                        reply_markup=self.get_task_control_keyboard(task_id)
                    )

                def get_task_control_keyboard(self, task_id: str) -> InlineKeyboardMarkup:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⏹ Остановить" if self.active_tasks.get(task_id, False) else "▶️ Запустить",
                                callback_data=f"stop_task_{task_id}" if self.active_tasks.get(task_id,
                                                                                              False) else f"start_task_{task_id}"
                            )
                        ],
                        [
                            InlineKeyboardButton(text="✏️ Изменить интервал",
                                                 callback_data=f"change_interval_{task_id}"),
                            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_task_{task_id}")
                        ],
                        [InlineKeyboardButton(text="🔙 Назад", callback_data="list_tasks")]
                    ])
                    return keyboard

                @self.dp.callback_query(F.data.startswith('start_task_'))
                async def process_start_task(callback_query: types.CallbackQuery):
                    await callback_query.answer()
                    task_id = callback_query.data.replace('start_task_', '')

                    if task_id not in self.config.get('tasks', {}):
                        await callback_query.message.answer(
                            "Задача не найдена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    self.active_tasks[task_id] = True
                    self.config['tasks'][task_id]['active'] = True
                    self.save_config()

                    await self.task_queue.put((task_id, self.config['tasks'][task_id]))

                    await callback_query.message.answer(
                        f"✅ Задача для @{self.config['tasks'][task_id]['group_username']} запущена!",
                        reply_markup=self.get_task_control_keyboard(task_id)
                    )

                @self.dp.callback_query(F.data.startswith('stop_task_'))
                async def process_stop_task(callback_query: types.CallbackQuery):
                    await callback_query.answer()
                    task_id = callback_query.data.replace('stop_task_', '')

                    if task_id not in self.config.get('tasks', {}):
                        await callback_query.message.answer(
                            "Задача не найдена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    self.active_tasks[task_id] = False
                    self.config['tasks'][task_id]['active'] = False
                    self.save_config()

                    await callback_query.message.answer(
                        f"⏹ Задача для @{self.config['tasks'][task_id]['group_username']} остановлена.",
                        reply_markup=self.get_task_control_keyboard(task_id)
                    )

                @self.dp.callback_query(F.data.startswith('change_interval_'))
                async def process_change_interval(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    task_id = callback_query.data.replace('change_interval_', '')

                    if task_id not in self.config.get('tasks', {}):
                        await callback_query.message.answer(
                            "Задача не найдена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    await state.update_data(task_id=task_id)
                    await callback_query.message.answer(
                        f"Текущий интервал: {self.config['tasks'][task_id]['interval']} сек\n"
                        "Введите новый интервал (в секундах, минимум 5):"
                    )

                @self.dp.message(F.text.regexp(r'^\d+$'))
                async def process_new_interval(message: types.Message, state: FSMContext):
                    data = await state.get_data()
                    if 'task_id' not in data:
                        return

                    try:
                        new_interval = max(5, int(message.text))
                        task_id = data['task_id']

                        self.config['tasks'][task_id]['interval'] = new_interval
                        self.save_config()

                        await state.clear()
                        await message.answer(
                            f"✅ Интервал для задачи обновлен: {new_interval} сек",
                            reply_markup=self.get_task_control_keyboard(task_id)
                        )
                    except Exception as e:
                        logger.error(f"Ошибка изменения интервала: {e}")
                        await message.answer("Ошибка. Попробуйте снова.")

                @self.dp.callback_query(F.data.startswith('delete_task_'))
                async def process_delete_task(callback_query: types.CallbackQuery):
                    await callback_query.answer()
                    task_id = callback_query.data.replace('delete_task_', '')

                    if task_id not in self.config.get('tasks', {}):
                        await callback_query.message.answer(
                            "Задача не найдена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{task_id}"),
                            InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"task_info_{task_id}")
                        ]
                    ])

                    await callback_query.message.answer(
                        f"⚠️ Вы уверены, что хотите удалить задачу для @{self.config['tasks'][task_id]['group_username']}?",
                        reply_markup=markup
                    )

                @self.dp.callback_query(F.data.startswith('confirm_delete_'))
                async def process_confirm_delete(callback_query: types.CallbackQuery):
                    await callback_query.answer()
                    task_id = callback_query.data.replace('confirm_delete_', '')

                    if task_id in self.config.get('tasks', {}):
                        if 'photo_path' in self.config['tasks'][task_id]:
                            try:
                                os.remove(self.config['tasks'][task_id]['photo_path'])
                            except:
                                pass

                        del self.config['tasks'][task_id]
                        if task_id in self.active_tasks:
                            del self.active_tasks[task_id]
                        self.save_config()

                        await callback_query.message.answer(
                            "✅ Задача успешно удалена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                    else:
                        await callback_query.message.answer(
                            "Задача не найдена.",
                            reply_markup=self.get_main_menu_keyboard()
                        )

                @self.dp.callback_query(F.data == 'start_all_tasks')
                async def process_start_all(callback_query: types.CallbackQuery):
                    await callback_query.answer()

                    started = 0
                    for task_id in self.config.get('tasks', {}):
                        if not self.active_tasks.get(task_id, False):
                            self.active_tasks[task_id] = True
                            self.config['tasks'][task_id]['active'] = True
                            await self.task_queue.put((task_id, self.config['tasks'][task_id]))
                            started += 1

                    self.save_config()

                    await callback_query.message.answer(
                        f"✅ Запущено {started} задач.",
                        reply_markup=self.get_main_menu_keyboard()
                    )

                @self.dp.callback_query(F.data == 'stop_all_tasks')
                async def process_stop_all(callback_query: types.CallbackQuery):
                    await callback_query.answer()

                    stopped = 0
                    for task_id in self.active_tasks:
                        if self.active_tasks[task_id]:
                            self.active_tasks[task_id] = False
                            self.config['tasks'][task_id]['active'] = False
                            stopped += 1

                    self.save_config()

                    await callback_query.message.answer(
                        f"⏹ Остановлено {stopped} задач.",
                        reply_markup=self.get_main_menu_keyboard()
                    )

                @self.dp.callback_query(F.data == 'task_status')
                async def process_task_status(callback_query: types.CallbackQuery):
                    await callback_query.answer()

                    if not self.config.get('tasks'):
                        await callback_query.message.answer(
                            "Нет активных задач.",
                            reply_markup=self.get_main_menu_keyboard()
                        )
                        return

                    active_count = sum(1 for t in self.active_tasks.values() if t)
                    total_count = len(self.config['tasks'])

                    status_msg = (
                        f"📊 <b>Статус задач</b>\n\n"
                        f"🟢 Активных: {active_count}\n"
                        f"🔴 Остановленных: {total_count - active_count}\n"
                        f"📌 Всего: {total_count}\n\n"
                    )

                    for task_id, task in self.config['tasks'].items():
                        status = "🟢" if self.active_tasks.get(task_id, False) else "🔴"
                        last_post = task.get('last_posted', 'еще не было')
                        status_msg += (
                            f"{status} @{task['group_username']} - "
                            f"интервал {task['interval']} сек - "
                            f"последняя отправка: {last_post}\n"
                        )

                    await callback_query.message.answer(
                        status_msg,
                        reply_markup=self.get_main_menu_keyboard()
                    )

                @self.dp.callback_query(F.data == 'toggle_notifications')
                async def process_toggle_notifications(callback_query: types.CallbackQuery):
                    await callback_query.answer()

                    self.config['notifications_enabled'] = not self.config.get('notifications_enabled', True)
                    self.save_config()

                    status = "включены" if self.config['notifications_enabled'] else "отключены"
                    await callback_query.message.answer(
                        f"🔔 Уведомления {status}.",
                        reply_markup=self.get_main_menu_keyboard()
                    )

                @self.dp.callback_query(F.data == 'back_to_main')
                async def process_back_to_main(callback_query: types.CallbackQuery, state: FSMContext):
                    await callback_query.answer()
                    await state.clear()
                    await state.set_state(PosterStates.main_menu)
                    await callback_query.message.answer(
                        "Главное меню:",
                        reply_markup=self.get_main_menu_keyboard()
                    )

                async def task_worker(self):
                    while True:
                        task_id, task_data = await self.task_queue.get()

                        if task_id not in self.active_tasks or not self.active_tasks[task_id]:
                            self.task_queue.task_done()
                            continue

                        try:
                            jitter = random.randint(-10, 10)
                            interval = max(5, task_data['interval'] + jitter)

                            logger.info(f"Отправка в @{task_data['group_username']} (ожидание {interval} сек)")
                            await asyncio.sleep(interval)

                            success = await self.send_message_to_topic(task_data)

                            if success:
                                self.config['tasks'][task_id]['last_posted'] = datetime.now().isoformat()
                                self.save_config()

                                if self.config.get('notifications_enabled', True):
                                    try:
                                        await self.bot.send_message(
                                            self.config['user_id'],
                                            f"✅ Отправлено в @{task_data['group_username']}\n"
                                            f"Следующая отправка через ~{task_data['interval']} сек",
                                            disable_notification=True
                                        )
                                    except Exception as e:
                                        logger.error(f"Ошибка уведомления: {e}")

                            if task_id in self.active_tasks and self.active_tasks[task_id]:
                                await self.task_queue.put((task_id, task_data))

                        except FloodWaitError as e:
                            wait_time = e.seconds
                            logger.warning(f"FloodWait: ждем {wait_time} сек для @{task_data['group_username']}")
                            await asyncio.sleep(wait_time)
                            await self.task_queue.put((task_id, task_data))
                        except Exception as e:
                            logger.error(f"Ошибка отправки в @{task_data['group_username']}: {e}", exc_info=True)
                            await asyncio.sleep(30)
                            await self.task_queue.put((task_id, task_data))

                        self.task_queue.task_done()

                async def send_message_to_topic(self, task_data: Dict) -> bool:
                    try:
                        entity = await self.telethon_client.get_entity(f"@{task_data['group_username']}")

                        send_args = {
                            'entity': entity,
                            'message': task_data['message'],
                            'parse_mode': 'html'
                        }

                        if task_data.get('topic_id', 0) != 0:
                            send_args['reply_to'] = task_data['topic_id']

                        if task_data.get('photo_path') and os.path.exists(task_data['photo_path']):
                            result = await self.telethon_client.send_file(
                                file=task_data['photo_path'],
                                caption=task_data['message'],
                                parse_mode='html',
                                reply_to=task_data.get('topic_id', None)
                            )
                        else:
                            result = await self.telethon_client.send_message(**send_args)

                        logger.info(f"Сообщение отправлено в @{task_data['group_username']} (ID: {result.id})")
                        return True

                    except Exception as e:
                        logger.error(f"Ошибка отправки в @{task_data['group_username']}: {e}", exc_info=True)
                        return False

                def generate_task_id(self) -> str:
                    return f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000, 9999)}"

                async def check_authorization(self):
                    """Проверяет, авторизован ли клиент Telethon"""
                    try:
                        if not self.telethon_client:
                            return False

                        if not self.telethon_client.is_connected():
                            await self.telethon_client.connect()

                        return await self.telethon_client.is_user_authorized()
                    except Exception as e:
                        logger.error(f"Ошибка проверки авторизации: {e}")
                        return False

                def get_main_menu_keyboard(self) -> InlineKeyboardMarkup:
                    return InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task"),
                            InlineKeyboardButton(text="📋 Мои задачи", callback_data="list_tasks")
                        ],
                        [
                            InlineKeyboardButton(text="▶️ Включить все", callback_data="start_all_tasks"),
                            InlineKeyboardButton(text="⏹ Отключить все", callback_data="stop_all_tasks")
                        ],
                        [
                            InlineKeyboardButton(text="📊 Статус задач", callback_data="task_status"),
                            InlineKeyboardButton(text="🔔 Уведомления", callback_data="toggle_notifications")
                        ]
                    ])
                
if __name__ == "__main__":
    # Укажите ваш токен бота здесь
    BOT_TOKEN = "7771036742:AAExM-ibsAhwee-lXe_bToJlZtLIwN1rBUE"

    bot = TelegramPosterBot(BOT_TOKEN)

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)