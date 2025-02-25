import asyncpg
from aiogram import types
from aiogram.fsm.context import FSMContext

from config import Config, dialogs
from database import check_user_passed
from .quiz import start_quiz
from .states import UserState


async def language_selection_handler(
    message: types.Message, state: FSMContext, pool: "asyncpg.Pool"
) -> None:
    """Предложение выбора языка для пользователей в группе."""
    if message.chat.id != Config.ALLOWED_CHAT_ID or await check_user_passed(
        pool, message.from_user.id
    ):
        return

    # Отправляем сообщение и сохраняем его ID
    lang_msg = await message.reply(
        dialogs["language_selection"],
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Русский", callback_data=f"lang_{message.from_user.id}_ru"
                    ),
                    types.InlineKeyboardButton(
                        text="English", callback_data=f"lang_{message.from_user.id}_en"
                    ),
                    types.InlineKeyboardButton(
                        text="中文", callback_data=f"lang_{message.from_user.id}_zh"
                    ),
                ]
            ]
        ),
    )
    await state.set_state(UserState.selecting_language)
    await state.update_data(
        orig_message_id=message.message_id, lang_message_id=lang_msg.message_id
    )  # Сохраняем ID сообщения о выборе языка


async def language_callback_handler(
    callback: types.CallbackQuery, state: FSMContext, pool: "asyncpg.Pool"
) -> None:
    """Обработка выбора языка пользователем."""
    data = callback.data.split("_")
    if len(data) != 3 or int(data[1]) != callback.from_user.id:
        return

    lang = data[2]
    await state.update_data(language=lang)
    await callback.message.edit_text(dialogs["language_set"][lang])
    await callback.answer()

    user_data = await state.get_data()
    lang_message_id = user_data.get(
        "lang_message_id"
    )  # Получаем ID сообщения о выборе языка

    # Удаляем сообщение о выборе языка
    if lang_message_id:
        await callback.message.bot.delete_message(
            chat_id=callback.message.chat.id, message_id=lang_message_id
        )

    await start_quiz(
        callback.message,
        callback.from_user,
        state,
        pool,
        user_data.get("orig_message_id"),
    )
