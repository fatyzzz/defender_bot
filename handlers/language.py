import asyncio
import logging

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config import config, dialogs
from database import check_user_passed, PoolType
from .states import UserState
from utils.moderation import ban_user_after_timeout
from utils.message_utils import delete_message


async def language_selection_handler(
    message: types.Message,
    state: FSMContext,
    bot: Bot,
    pool: PoolType,
) -> None:
    """Запрашивает у новых пользователей выбор языка с таймаутом."""
    current_state = await state.get_state()
    if current_state in [UserState.waiting_for_language, UserState.answering_quiz]:
        return

    if (
        message.chat.id != config.ALLOWED_CHAT_ID
        or await check_user_passed(pool, message.from_user.id)
        or message.from_user.is_bot
    ):
        return

    thread_id = message.message_thread_id if message.message_thread_id else None
    user_mention = message.from_user.mention_html()
    text = dialogs["language_selection"].format(name=user_mention)

    try:
        lang_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="Русский",
                            callback_data=f"lang_{message.from_user.id}_ru",
                        ),
                        types.InlineKeyboardButton(
                            text="English",
                            callback_data=f"lang_{message.from_user.id}_en",
                        ),
                        types.InlineKeyboardButton(
                            text="中文",
                            callback_data=f"lang_{message.from_user.id}_zh",
                        ),
                    ]
                ]
            ),
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        logging.info(
            f"Language selection sent to chat {message.chat.id}, thread_id={thread_id}"
        )
    except TelegramBadRequest as e:
        logging.warning(f"Failed to send language selection: {e}")
        return

    # Сохраняем данные в состоянии
    await state.set_state(UserState.waiting_for_language)
    await state.update_data(
        lang_message_id=lang_msg.message_id,
        thread_id=thread_id,
        first_message_id=message.message_id,
        bot_messages=[lang_msg.message_id],
    )

    asyncio.create_task(
        language_selection_timeout(
            bot, state, message.chat.id, thread_id, message.from_user.id, pool
        )
    )


async def language_selection_timeout(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    thread_id: int,
    user_id: int,
    pool: PoolType,
) -> None:
    """Обрабатывает таймаут для выбора языка."""
    await asyncio.sleep(config.LANGUAGE_SELECTION_TIMEOUT)
    current_state = await state.get_state()
    if current_state != UserState.waiting_for_language:
        return

    user_data = await state.get_data()
    lang_message_id = user_data.get("lang_message_id")
    first_message_id = user_data.get("first_message_id")
    bot_messages = user_data.get("bot_messages", [])

    # Отправляем сообщение о таймауте в чат
    timeout_text = dialogs["language_timeout"]["ru"].format(
        name=f'<a href="tg://user?id={user_id}">{user_id}</a>'
    )
    timeout_msg = await bot.send_message(
        chat_id=chat_id,
        text=timeout_text,
        parse_mode="HTML",
        message_thread_id=thread_id,
    )

    # Моментально удаляем сообщения в чате
    if first_message_id:
        asyncio.create_task(delete_message(bot, chat_id, first_message_id, delay=0))
    if lang_message_id:
        asyncio.create_task(delete_message(bot, chat_id, lang_message_id, delay=0))
    for msg_id in bot_messages:
        asyncio.create_task(delete_message(bot, chat_id, msg_id, delay=0))
    asyncio.create_task(
        delete_message(
            bot, chat_id, timeout_msg.message_id, config.DEFAULT_MESSAGE_DELETE_DELAY
        )
    )

    # Блокируем пользователя
    await ban_user_after_timeout(bot, chat_id, user_id, pool)
    logging.info(f"Пользователь {user_id} забанен из-за таймаута выбора языка")
    await state.clear()


async def language_callback_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    pool: PoolType,
) -> None:
    """Обрабатывает выбор языка через callback."""
    data = callback.data.split("_")
    if len(data) != 3 or int(data[1]) != callback.from_user.id:
        return

    lang = data[2]
    await state.update_data(language=lang)

    user_mention = callback.from_user.mention_html()
    confirmation_text = dialogs["language_set"][lang].format(name=user_mention)

    logging.info(f"Language selected: {lang}, user: {user_mention}")
    try:
        await callback.message.edit_text(text=confirmation_text, parse_mode="HTML")
    except TelegramBadRequest as e:
        logging.error(f"Failed to edit message: {e}")
        await callback.message.edit_text(f"Ошибка при выборе языка: {lang}")

    await callback.answer()

    user_data = await state.get_data()
    thread_id = user_data.get("thread_id")
    group_chat_id = callback.message.chat.id

    button_text = dialogs["quiz_button"][lang]
    instruction_text = dialogs["quiz_instruction"][lang]

    bot_username = (await callback.message.bot.get_me()).username
    quiz_button_msg = await callback.message.bot.send_message(
        chat_id=group_chat_id,
        text=instruction_text,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=button_text,
                        url=f"https://t.me/{bot_username}?start=quiz_{callback.from_user.id}_{lang}_{group_chat_id}",
                    )
                ]
            ]
        ),
        message_thread_id=thread_id,
    )

    # Обновляем bot_messages
    bot_messages = user_data.get("bot_messages", [])
    bot_messages.append(quiz_button_msg.message_id)
    await state.update_data(bot_messages=bot_messages)

    # Удаляем сообщение выбора языка
    try:
        await callback.message.bot.delete_message(
            group_chat_id, user_data["lang_message_id"]
        )
    except TelegramBadRequest:
        logging.warning(
            f"Не удалось удалить сообщение выбора языка {user_data['lang_message_id']}"
        )
