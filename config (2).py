import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise ValueError(
        "Не найден токен бота.\n"
        "Укажите переменную окружения BOT_TOKEN "
        "или создайте в корне проекта файл .env со строкой:\n"
        "BOT_TOKEN=ваш_токен_бота"
    )

DB_PATH = os.getenv("DB_PATH", "rooms.db")

MIN_KEY_LENGTH = 3
MAX_KEY_LENGTH = 32

# Telegram ID владельцев/администраторов бота, которым разрешено
# писать пользователям, ранее взаимодействовавшим с ботом, через
# команду /dm. Указывается в .env как список ID через запятую:
# ADMIN_IDS=111111111,222222222
_raw_admin_ids = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = {
    int(item) for item in _raw_admin_ids.split(",") if item.strip().isdigit()
}
