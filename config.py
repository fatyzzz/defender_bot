import json
import os
from typing import Dict, Any

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()


class Config(BaseModel):
    """Конфигурация бота с валидацией через pydantic."""
    BOT_TOKEN: str
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    ALLOWED_CHAT_ID: int = 0
    FALLBACK_THREAD_ID: int = 0

    class Config:
        extra = "forbid"  # Запрещаем лишние поля


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


json_config = load_json_config()
questions = json_config["questions"]
dialogs = json_config["dialogs"]