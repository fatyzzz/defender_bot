import logging

from aiogram import Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from config import config, dialogs
from database import check_user_passed
from .quiz import start_quiz, get_thread_id
from .states import UserState


async def language_selection_handler(
    message: types.Message, state: FSMContext, bot: Bot, pool: "asyncpg.Pool"
) -> None:
    """Предложение выбора языка для новых пользователей."""
    if message.chat.id != config.ALLOWED_CHAT_ID or await check_user_passed(pool, message.from_user.id):
        return

    thread_id = await get_thread_id(message.chat, message.message_thread_id or config.FALLBACK_THREAD_ID)

    try:
        lang_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=dialogs["language_selection"],
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(text="Русский", callback_data=f"lang_{message.from_user.id}_ru"),
                        types.InlineKeyboardButton(text="English", callback_data=f"lang_{message.from_user.id}_en"),
                        types.InlineKeyboardButton(text="中文", callback_data=f"lang_{message.from_user.id}_zh"),
                    ]
                ]
            ),
            message_thread_id=thread_id,
        )
        logging.info(f"Language selection sent to chat {message.chat.id} with thread_id={thread_id}")
    except TelegramBadRequest as e:
        logging.warning(f"Failed to send language selection with thread_id={thread_id}: {e}")
        lang_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=dialogs["language_selection"],
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(text="Русский", callback_data=f"lang_{message.from_user.id}_ru"),
                        types.InlineKeyboardButton(text="English", callback_data=f"lang_{message.from_user.id}_en"),
                        types.InlineKeyboardButton(text="中文", callback_data=f"lang_{message.from_user.id}_zh"),
                    ]
                ]
            ),
        )
        thread_id = None  # Если thread_id не сработал, сбрасываем его
        logging.info(f"Language selection sent to chat {message.chat.id} without thread_id")

    await state.set_state(UserState.selecting_language)
    await state.update_data(orig_message_id=message.message_id, lang_message_id=lang_msg.message_id, thread_id=thread_id)


async def language_callback_handler(
    callback: types.CallbackQuery, state: FSMContext, pool: "asyncpg.Pool"
) -> None:
    """Обработка выбора языка."""
    data = callback.data.split("_")
    if len(data) != 3 or int(data[1]) != callback.from_user.id:
        return

    lang = data[2]
    await state.update_data(language=lang)
    await callback.message.edit_text(dialogs["language_set"][lang])
    await callback.answer()

    user_data = await state.get_data()
    if user_data.get("lang_message_id"):
        await callback.message.bot.delete_message(callback.message.chat.id, user_data["lang_message_id"])

    await start_quiz(callback.message, callback.from_user, state, pool, user_data["orig_message_id"])