import logging

from aiogram import types

from config import Config


async def start_handler(message: types.Message) -> None:
    """Обработка команды /start для активации бота в чате."""
    if Config.ALLOWED_CHAT_ID == 0:  # Если чат не задан
        Config.ALLOWED_CHAT_ID = message.chat.id
        await message.reply("Бот активирован в этом чате!")
        logging.info(f"Bot activated in chat {Config.ALLOWED_CHAT_ID}")
    elif message.chat.id == Config.ALLOWED_CHAT_ID:
        await message.reply("Бот уже активен в этом чате!")
    else:
        await message.reply("Извините, бот работает только в разрешённом чате.")
