import logging

from aiogram import types, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from config import config
from .states import UserState


async def message_handler(message: types.Message, state: FSMContext, bot: Bot):
    """Обработка сообщений пользователя."""
    if message.from_user.is_bot or message.chat.id != config.ALLOWED_CHAT_ID:
        return

    current_state = await state.get_state()
    user_data = await state.get_data()

    if current_state == UserState.waiting_for_language:
        # Немедленно удаляем сообщения во время выбора языка
        try:
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(
                f"Deleted message {message.message_id} during language selection"
            )
        except TelegramBadRequest:
            logging.warning(f"Failed to delete message {message.message_id}")
    elif current_state == UserState.answering_quiz:
        # Немедленно удаляем сообщения во время квиза
        try:
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(f"Deleted message {message.message_id} during quiz")
        except TelegramBadRequest:
            logging.warning(f"Failed to delete message {message.message_id}")
