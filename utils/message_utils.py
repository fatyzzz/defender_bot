import asyncio
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
import logging

async def delete_message(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    """Удаление сообщения с задержкой."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
        logging.info(f"Удалено сообщение {message_id} в чате {chat_id}")
    except TelegramBadRequest:
        logging.warning(f"Не удалось удалить сообщение {message_id} в чате {chat_id}")