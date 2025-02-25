import logging

from aiogram import types

from config import config


async def start_handler(message: types.Message) -> None:
    """Обработка команды /start."""
    if config.ALLOWED_CHAT_ID == 0:
        config.ALLOWED_CHAT_ID = message.chat.id
        await message.reply("Бот активирован в этом чате!")
        logging.info(f"Bot activated in chat {message.chat.id}")
    elif message.chat.id == config.ALLOWED_CHAT_ID:
        await message.reply("Бот уже активен в этом чате!")
    else:
        await message.reply("Бот работает только в разрешённом чате.")