import os
from typing import Dict, Any
import json

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
    DB_PORT: int | None = None  # Опционально, если используется сокет
    DB_SOCKET: str | None = None  # Опционально для Unix-сокета
    ALLOWED_CHAT_ID: int  # ID чата, где работает бот

    class Config:
        extra = "forbid"  # Запрещаем лишние поля


# Загружаем и валидируем конфигурацию
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
