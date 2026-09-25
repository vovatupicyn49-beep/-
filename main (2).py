import asyncio
import logging
import random
import string
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import ADMIN_IDS, BOT_TOKEN, DB_PATH, MAX_KEY_LENGTH, MIN_KEY_LENGTH
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database(DB_PATH)
router = Router()


class RoomStates(StatesGroup):
    waiting_key_create = State()
    waiting_key_join = State()


BTN_CREATE = "🔑 Создать комнату"
BTN_JOIN = "🚪 Присоединиться к комнате"
BTN_RANDOM = "🎲 Случайный собеседник"
BTN_CANCEL_SEARCH = "🔙 Отменить поиск"
BTN_LEAVE = "❌ Выйти из комнаты"
BTN_CANCEL = "🔙 Отмена"

CB_GENERATE_KEY = "generate_key"
CB_CUSTOM_KEY = "custom_key"


# --------------------------------------------------------------- клавиатуры


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE)],
            [KeyboardButton(text=BTN_JOIN)],
            [KeyboardButton(text=BTN_RANDOM)],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def searching_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL_SEARCH)]],
        resize_keyboard=True,
    )


def room_active_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_LEAVE)]],
        resize_keyboard=True,
    )


def create_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Сгенерировать автоматически",
                    callback_data=CB_GENERATE_KEY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Ввести свой ключ",
                    callback_data=CB_CUSTOM_KEY,
                )
            ],
        ]
    )


# ------------------------------------------------------------------ утилиты


def generate_secret_key(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        candidate = "".join(random.choices(alphabet, k=length))
        if not db.key_exists(candidate):
            return candidate


def validate_custom_key(raw_key: str) -> tuple[bool, str]:
    key = raw_key.strip()
    if " " in key or "\n" in key or "\t" in key:
        return False, "Ключ не должен содержать пробелов или переносов строк. Попробуйте ещё раз."
    if len(key) < MIN_KEY_LENGTH:
        return False, f"Ключ слишком короткий. Минимальная длина — {MIN_KEY_LENGTH} символов."
    if len(key) > MAX_KEY_LENGTH:
        return False, f"Ключ слишком длинный. Максимальная длина — {MAX_KEY_LENGTH} символов."
    return True, key


async def notify_many(bot: Bot, user_ids: list[int], text: str, **kwargs) -> None:
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, **kwargs)
        except (TelegramForbiddenError, TelegramBadRequest):
            logger.warning("Не удалось отправить сообщение пользователю %s", uid)


# -------------------------------------------------------------- middleware


@router.message.middleware()
async def track_user_middleware(handler, event: Message, data: dict):
    if event.from_user is not None:
        db.upsert_user(event.from_user.id, event.from_user.username)
    return await handler(event, data)


@router.callback_query.middleware()
async def track_user_cb_middleware(handler, event: CallbackQuery, data: dict):
    if event.from_user is not None:
        db.upsert_user(event.from_user.id, event.from_user.username)
    return await handler(event, data)


# ------------------------------------------------------------------- /start


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id

    if db.is_user_in_room(user_id):
        room = db.get_room_by_user(user_id)
        if room["status"] == "active":
            await message.answer(
                "Вы уже находитесь в анонимном чате.\n"
                "Все сообщения пересылаются остальным участникам комнаты.\n"
                "Чтобы выйти, нажмите «❌ Выйти из комнаты».",
                reply_markup=room_active_kb(),
            )
        else:
            await message.answer(
                "Вы уже создали комнату и ожидаете собеседников.\n"
                f"Ваш секретный ключ: <code>{room['secret_key']}</code>\n\n"
                "Чтобы отменить ожидание, нажмите «❌ Выйти из комнаты».",
                reply_markup=room_active_kb(),
            )
        return

    if db.queue_contains(user_id):
        await message.answer(
            "Вы уже в очереди случайного подбора. Ожидайте собеседника.",
            reply_markup=searching_kb(),
        )
        return

    await message.answer(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "🔑 «Создать комнату» — создать секретный ключ и ждать участников.\n"
        "🚪 «Присоединиться к комнате» — подключиться по чужому секретному ключу "
        "(к одной комнате может присоединиться сколько угодно человек).\n"
        "🎲 «Случайный собеседник» — бот сам найдёт вам собеседника.\n\n"
        "Все сообщения и медиа внутри комнаты пересылаются анонимно.",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ Как это работает:\n\n"
        "1. Создайте комнату (свой или случайный ключ) и поделитесь ключом с теми, "
        "с кем хотите общаться — к комнате может присоединиться несколько человек.\n"
        "2. Либо нажмите «Присоединиться к комнате» и введите чужой ключ.\n"
        "3. Либо нажмите «Случайный собеседник» — бот подберёт вам того, "
        "кто тоже ищет общения.\n"
        "4. Все сообщения, фото, видео, голосовые и файлы анонимно пересылаются "
        "остальным участникам комнаты.\n"
        "5. Комната закрывается автоматически, когда в ней остаётся только "
        "один участник. Кнопка «❌ Выйти из комнаты» доступна в любой момент.",
    )


# --------------------------------------------------------------- создание


@router.message(F.text == BTN_CREATE, StateFilter(None))
async def create_room_start(message: Message) -> None:
    user_id = message.from_user.id

    if db.is_user_in_room(user_id) or db.queue_contains(user_id):
        await message.answer(
            "У вас уже есть активная комната, комната ожидания или поиск. "
            "Сначала выйдите из неё.",
            reply_markup=room_active_kb(),
        )
        return

    await message.answer(
        "Выберите, как получить секретный ключ комнаты:",
        reply_markup=create_choice_kb(),
    )


@router.callback_query(F.data == CB_GENERATE_KEY)
async def create_room_generate(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    if db.is_user_in_room(user_id) or db.queue_contains(user_id):
        await callback.answer("У вас уже есть комната или активный поиск.", show_alert=True)
        return

    secret_key = generate_secret_key()
    created = db.create_room(secret_key, user_id)

    if not created:
        await callback.answer("Не удалось создать комнату, попробуйте ещё раз.", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✅ Комната создана!\n\n"
        f"Ваш секретный ключ: <code>{secret_key}</code>\n\n"
        "Отправьте этот ключ тем, с кем хотите анонимно пообщаться. "
        "К комнате может присоединиться несколько человек.",
        reply_markup=room_active_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == CB_CUSTOM_KEY)
async def create_room_custom(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id

    if db.is_user_in_room(user_id) or db.queue_contains(user_id):
        await callback.answer("У вас уже есть комната или активный поиск.", show_alert=True)
        return

    await state.set_state(RoomStates.waiting_key_create)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Введите свой секретный ключ "
        f"(от {MIN_KEY_LENGTH} до {MAX_KEY_LENGTH} символов, без пробелов):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(RoomStates.waiting_key_create, F.text)
async def process_custom_key(message: Message, state: FSMContext) -> None:
    is_valid, result = validate_custom_key(message.text)

    if not is_valid:
        await message.answer(result, reply_markup=cancel_kb())
        return

    secret_key = result
    user_id = message.from_user.id

    if db.key_exists(secret_key):
        await message.answer(
            "Этот ключ уже занят. Введите другой ключ:",
            reply_markup=cancel_kb(),
        )
        return

    created = db.create_room(secret_key, user_id)
    await state.clear()

    if not created:
        await message.answer(
            "Не удалось создать комнату (ключ уже занят). Попробуйте снова.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        "✅ Комната создана!\n\n"
        f"Ваш секретный ключ: <code>{secret_key}</code>\n\n"
        "Отправьте этот ключ тем, с кем хотите анонимно пообщаться. "
        "К комнате может присоединиться несколько человек.",
        reply_markup=room_active_kb(),
    )


# ---------------------------------------------------------- присоединение


@router.message(F.text == BTN_JOIN, StateFilter(None))
async def join_room_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    if db.is_user_in_room(user_id) or db.queue_contains(user_id):
        await message.answer(
            "У вас уже есть активная комната, комната ожидания или поиск. "
            "Сначала выйдите из неё.",
            reply_markup=room_active_kb(),
        )
        return

    await state.set_state(RoomStates.waiting_key_join)
    await message.answer(
        "Введите секретный ключ комнаты, к которой хотите присоединиться:",
        reply_markup=cancel_kb(),
    )


@router.message(RoomStates.waiting_key_join, F.text)
async def process_join_key(message: Message, state: FSMContext) -> None:
    secret_key = message.text.strip()
    user_id = message.from_user.id

    existing_members = db.join_room(secret_key, user_id)
    await state.clear()

    if existing_members is None:
        await message.answer(
            "❌ Комната с таким ключом не найдена, либо вы уже в ней состоите.\n"
            "Проверьте ключ и попробуйте снова через меню.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        "✅ Вы присоединились к комнате!\n"
        "Теперь все ваши сообщения анонимно пересылаются остальным участникам.\n"
        "Чтобы выйти, нажмите «❌ Выйти из комнаты».",
        reply_markup=room_active_kb(),
    )

    await notify_many(
        message.bot,
        existing_members,
        "✅ К комнате присоединился новый участник.",
        reply_markup=room_active_kb(),
    )


# ------------------------------------------------------------- случайный


@router.message(F.text == BTN_RANDOM, StateFilter(None))
async def random_search_start(message: Message) -> None:
    user_id = message.from_user.id

    if db.is_user_in_room(user_id):
        await message.answer(
            "У вас уже есть комната. Сначала выйдите из неё.",
            reply_markup=room_active_kb(),
        )
        return

    if db.queue_contains(user_id):
        await message.answer(
            "Вы уже в очереди поиска. Ожидайте собеседника.",
            reply_markup=searching_kb(),
        )
        return

    partner_id = db.queue_pop_any(exclude_user_id=user_id)

    if partner_id is None:
        db.queue_add(user_id)
        await message.answer(
            "🔎 Ищем вам собеседника... Как только кто-то найдётся, "
            "вы получите уведомление.",
            reply_markup=searching_kb(),
        )
        return

    secret_key = generate_secret_key()
    db.create_room_with_members(secret_key, [partner_id, user_id])

    await message.answer(
        "✅ Собеседник найден! Можете начинать анонимный диалог.\n"
        "Чтобы выйти, нажмите «❌ Выйти из комнаты».",
        reply_markup=room_active_kb(),
    )
    await notify_many(
        message.bot,
        [partner_id],
        "✅ Собеседник найден! Можете начинать анонимный диалог.\n"
        "Чтобы выйти, нажмите «❌ Выйти из комнаты».",
        reply_markup=room_active_kb(),
    )


@router.message(F.text == BTN_CANCEL_SEARCH)
async def random_search_cancel(message: Message) -> None:
    db.queue_remove(message.from_user.id)
    await message.answer("Поиск отменён.", reply_markup=main_menu_kb())


# ------------------------------------------------------------------- выход


@router.message(F.text == BTN_CANCEL, StateFilter(RoomStates.waiting_key_create, RoomStates.waiting_key_join))
async def cancel_input(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu_kb())


@router.message(F.text == BTN_LEAVE)
async def leave_room(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id
    result = db.leave_room(user_id)

    if result is None:
        await message.answer("Вы не состоите ни в одной комнате.", reply_markup=main_menu_kb())
        return

    await message.answer("Вы вышли из комнаты. Сессия завершена.", reply_markup=main_menu_kb())

    if result["closed"] and result["remaining"]:
        # Остался ровно один участник — комната закрывается и для него тоже.
        await notify_many(
            message.bot,
            result["remaining"],
            "⚠️ Все остальные участники покинули чат. Комната закрыта.",
            reply_markup=main_menu_kb(),
        )
    elif not result["closed"] and result["remaining"]:
        # В комнате остаётся больше одного участника — просто уведомляем.
        await notify_many(
            message.bot,
            result["remaining"],
            "⚠️ Один из участников покинул чат.",
            reply_markup=room_active_kb(),
        )


# ------------------------------------------------------------- админ /dm


@router.message(Command("dm"))
async def admin_dm(message: Message) -> None:
    """
    Позволяет администратору бота отправить сообщение любому пользователю,
    который ранее уже писал боту, указав его ID или username.
    Использование: /dm <id_или_@username> <текст сообщения>
    """
    if message.from_user.id not in ADMIN_IDS:
        return  # Молча игнорируем для не-администраторов.

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Использование: <code>/dm ID_или_@username текст сообщения</code>"
        )
        return

    _, target_raw, text = parts
    target_id: Optional[int] = None

    if target_raw.lstrip("-").isdigit():
        candidate = int(target_raw)
        if db.user_known(candidate):
            target_id = candidate
    else:
        target_id = db.find_user_by_username(target_raw)

    if target_id is None:
        await message.answer(
            "Пользователь не найден среди тех, кто уже писал боту."
        )
        return

    try:
        await message.bot.send_message(target_id, text)
        await message.answer("✅ Сообщение отправлено.")
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("❌ Не удалось доставить сообщение (бот заблокирован пользователем).")


# ------------------------------------------------------------ пересылка


@router.message(StateFilter(None))
async def relay_message(message: Message) -> None:
    user_id = message.from_user.id

    if message.text and message.text.startswith("/"):
        await message.answer("Неизвестная команда. Используйте /start, чтобы открыть меню.")
        return

    if db.queue_contains(user_id):
        await message.answer(
            "Вы в очереди поиска собеседника. Ожидайте или отмените поиск.",
            reply_markup=searching_kb(),
        )
        return

    room = db.get_room_by_user(user_id)

    if room is None:
        await message.answer(
            "Вы не находитесь в комнате. Используйте меню ниже.",
            reply_markup=main_menu_kb(),
        )
        return

    if room["status"] != "active":
        await message.answer(
            "Вы ожидаете участников. Сообщения начнут пересылаться, "
            "как только кто-то присоединится по вашему ключу.",
            reply_markup=room_active_kb(),
        )
        return

    other_members = db.get_other_members(user_id)

    for member_id in other_members:
        try:
            await message.bot.copy_message(
                chat_id=member_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            logger.warning("Не удалось переслать сообщение пользователю %s", member_id)


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
