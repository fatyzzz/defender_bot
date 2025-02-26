from aiogram import types
from aiogram.fsm.context import FSMContext

from config import config
from .states import UserState


async def message_handler(message: types.Message, state: FSMContext):
    """Сохраняет ID сообщений пользователя до завершения квиза."""
    if message.from_user.is_bot or message.chat.id != config.ALLOWED_CHAT_ID:
        return

    current_state = await state.get_state()
    if current_state in [UserState.waiting_for_language, UserState.answering_quiz]:
        user_data = await state.get_data()
        user_messages = user_data.get("user_messages", [])
        user_messages.append(message.message_id)
        await state.update_data(user_messages=user_messages)
