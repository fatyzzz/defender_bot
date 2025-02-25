import json
import os
from dataclasses import dataclass
from typing import Dict, Any

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN")
    DB_USER: str = os.getenv("DB_USER")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD")
    DB_NAME: str = os.getenv("DB_NAME")
    DB_HOST: str = os.getenv("DB_HOST")
    ALLOWED_CHAT_ID: int = int(os.getenv("ALLOWED_CHAT_ID", 0))
    FALLBACK_THREAD_ID: int = int(
        os.getenv("FALLBACK_THREAD_ID", 0)
    )  # Добавили для форумов

    def __post_init__(self):
        required = ["BOT_TOKEN", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_HOST"]
        missing = [field for field in required if not getattr(self, field)]
        if missing:
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing)}")


def load_json_config() -> Dict[str, Any]:
    with open("data/config.json", "r", encoding="utf-8") as f:
        return json.load(f)


config = Config()
json_config = load_json_config()
questions = json_config["questions"]
dialogs = json_config["dialogs"]
