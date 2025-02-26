import asyncio
import logging
from aiogram import Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from config import config, dialogs
from database import check_user_passed, PoolType
from .quiz import start_quiz
from .states import UserState
from utils.moderation import ban_user_after_timeout


async def language_selection_handler(
    message: types.Message,
    state: FSMContext,
    bot: Bot,
    pool: PoolType,
) -> None:
    """Запрашивает у новых пользователей выбор языка с таймаутом."""
    current_state = await state.get_state()
    if current_state == UserState.waiting_for_language:
        # Если пользователь уже ждет выбора языка, сохраняем ID сообщения
        user_data = await state.get_data()
        user_messages = user_data.get("user_messages", [])
        user_messages.append(message.message_id)
        await state.update_data(user_messages=user_messages)
        return

    if (
        message.chat.id != config.ALLOWED_CHAT_ID
        or await check_user_passed(pool, message.from_user.id)
        or message.from_user.is_bot
    ):
        return

    thread_id = message.message_thread_id if message.message_thread_id else None

    user_mention = (
        message.from_user.mention_html()
        if message.from_user.username
        else message.from_user.first_name
    )

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
                            text="中文", callback_data=f"lang_{message.from_user.id}_zh"
                        ),
                    ]
                ]
            ),
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        logging.info(
            f"Сообщение о выборе языка отправлено в чат {message.chat.id}, thread_id={thread_id}, текст: {text}"
        )
    except TelegramBadRequest as e:
        logging.warning(f"Не удалось отправить сообщение о выборе языка: {e}")
        return

    await state.set_state(UserState.waiting_for_language)
    await state.update_data(
        lang_message_id=lang_msg.message_id,
        thread_id=thread_id,
        user_messages=[message.message_id],  # Сохраняем ID первого сообщения
    )

    # Запускаем таймаут на 5 минут
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
    if current_state == UserState.waiting_for_language:
        user_data = await state.get_data()
        lang_message_id = user_data.get("lang_message_id")
        if lang_message_id:
            try:
                await bot.delete_message(chat_id, lang_message_id)
                logging.info(
                    f"Удалено сообщение о выборе языка {lang_message_id} после таймаута"
                )
            except TelegramBadRequest:
                logging.warning(f"Не удалось удалить сообщение {lang_message_id}")

        # Удаляем все сообщения пользователя
        user_messages = user_data.get("user_messages", [])
        for msg_id in user_messages:
            try:
                await bot.delete_message(chat_id, msg_id)
            except TelegramBadRequest:
                logging.warning(f"Не удалось удалить сообщение {msg_id}")

        # Пример действия: забанить пользователя после таймаута
        try:
            await ban_user_after_timeout(bot, chat_id, user_id, pool)
            logging.info(
                f"Пользователь {user_id} забанен из-за превышения времени выбора языка"
            )
        except Exception as e:
            logging.error(f"Не удалось забанить пользователя {user_id}: {e}")

        # Очищаем состояние
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

    user_mention = (
        callback.from_user.mention_html()
        if callback.from_user.username
        else callback.from_user.first_name
    )

    confirmation_text = dialogs["language_set"][lang].format(name=user_mention)

    logging.info(
        f"Выбран язык: {lang}, пользователь: {user_mention}, текст: {confirmation_text}"
    )

    try:
        await callback.message.edit_text(
            text=confirmation_text,
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        logging.error(f"Не удалось отредактировать сообщение: {e}")
        await callback.message.edit_text(f"Ошибка при выборе языка: {lang}")

    await callback.answer()

    user_data = await state.get_data()
    thread_id = user_data.get("thread_id")

    # Удаляем только сообщение с выбором языка
    await callback.message.bot.delete_message(
        callback.message.chat.id, user_data["lang_message_id"]
    )

    await start_quiz(
        callback.message, callback.from_user, state, pool, thread_id=thread_id
    )
