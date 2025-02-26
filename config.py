import json
import os
from typing import Dict, Any

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

# Загружаем переменные из .env файла
load_dotenv()


class Config(BaseModel):
    """Конфигурация бота с валидацией через pydantic."""
    BOT_TOKEN: str
    DB_TYPE: str  # "mysql" или "postgres"
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    DB_PORT: int | None = None  # Опционально, не требуется при использовании сокета
    DB_SOCKET: str | None = None  # Опционально для Unix-сокета в MySQL
    ALLOWED_CHAT_ID: int = 0  # ID чата, где работает бот
    FALLBACK_THREAD_ID: int = 0  # ID ветки для форумных групп

    class Config:
        extra = "forbid"  # Запрещаем лишние поля


# Загружаем переменные из .env и валидируем через pydantic
try:
    config = Config(**{key: os.getenv(key) for key in Config.__annotations__})
except ValidationError as e:
    raise ValueError(f"Ошибка в конфигурации: {e}")


def load_json_config() -> Dict[str, Any]:
    """Загрузка данных из config.json с базовой валидацией."""
    with open("data/config.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    if not all(key in data for key in ["questions", "dialogs"]):
        raise ValueError("Отсутствуют обязательные ключи в config.json")
    return data


# Загружаем JSON-конфигурацию
json_config = load_json_config()
questions = json_config["questions"]
dialogs = json_config["dialogs"]