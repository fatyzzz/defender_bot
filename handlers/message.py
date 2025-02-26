import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from .states import UserState
from config import config


async def message_handler(message: types.Message, state: FSMContext):
    """Удаление сообщений до выбора языка."""
    if message.from_user.is_bot or message.chat.id != config.ALLOWED_CHAT_ID:
        return

    current_state = await state.get_state()
    if current_state == UserState.waiting_for_language:
        try:
            await message.delete()
            user_data = await state.get_data()
            user_messages = user_data.get("user_messages", [])
            user_messages.append(message.message_id)
            await state.update_data(user_messages=user_messages)
        except Exception as e:
            logging.warning(f"Failed to delete message {message.message_id}: {e}")
