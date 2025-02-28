import logging

from aiogram import types, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config import config
from .states import UserState
from .language import language_selection_handler


async def message_handler(message: types.Message, state: FSMContext, bot: Bot, pool) -> None:
    """Обработка сообщений пользователя."""
    if message.from_user.is_bot or message.chat.id != config.ALLOWED_CHAT_ID:
        return

    current_state = await state.get_state()

    # Сохраняем ID первого сообщения пользователя
    user_data = await state.get_data()
    if not user_data.get("first_message_id"):
        await state.update_data(first_message_id=message.message_id)

    # Удаляем сообщения во время выбора языка
    if current_state == UserState.waiting_for_language:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(f"Удалено сообщение {message.message_id} во время выбора языка")
        except TelegramBadRequest:
            logging.warning(f"Не удалось удалить сообщение {message.message_id}")
        return

    # Удаляем сообщения во время квиза
    elif current_state == UserState.answering_quiz:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(f"Удалено сообщение {message.message_id} во время квиза")
        except TelegramBadRequest:
            logging.warning(f"Не удалось удалить сообщение {message.message_id}")
        return

    await language_selection_handler(message, state, bot, pool)