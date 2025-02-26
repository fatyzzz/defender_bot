import logging
from aiogram import types, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from config import config
from .states import UserState
from .language import language_selection_handler


async def message_handler(message: types.Message, state: FSMContext, bot: Bot, pool):
    """Обработка сообщений пользователя."""
    # Проверяем, что сообщение от пользователя, а не бота, и в нужном чате
    if message.from_user.is_bot or message.chat.id != config.ALLOWED_CHAT_ID:
        return

    # Получаем текущее состояние пользователя
    current_state = await state.get_state()

    # Если пользователь выбирает язык
    if current_state == UserState.waiting_for_language:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(
                f"Удалено сообщение {message.message_id} во время выбора языка"
            )
        except TelegramBadRequest:
            logging.warning(f"Не удалось удалить сообщение {message.message_id}")
        return

    # Если пользователь в квизе
    elif current_state == UserState.answering_quiz:
        try:
            await bot.delete_message(message.chat.id, message.message_id)
            logging.info(f"Удалено сообщение {message.message_id} во время квиза")
        except TelegramBadRequest:
            logging.warning(f"Не удалось удалить сообщение {message.message_id}")
        return

    # Если нет активного состояния, запускаем выбор языка
    await language_selection_handler(message, state, bot, pool)
