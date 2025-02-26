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

LANGUAGE_SELECTION_TIMEOUT = 300  # 5 минут в секундах


async def language_selection_handler(
    message: types.Message,
    state: FSMContext,
    bot: Bot,
    pool: PoolType,
) -> None:
    """Запрашивает у новых пользователей выбор языка с таймаутом."""
    if (
        message.chat.id != config.ALLOWED_CHAT_ID
        or await check_user_passed(pool, message.from_user.id)
        or message.from_user.is_bot
    ):
        return

    thread_id = message.message_thread_id if message.message_thread_id else None

    # Получаем кликабельное имя пользователя в формате HTML
    user_mention = (
        message.from_user.mention_html()
        if message.from_user.username
        else message.from_user.first_name
    )

    # Форматируем текст сообщения с именем пользователя через {name}
    text = dialogs["language_selection"].format(name=user_mention)

    try:
        lang_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=text,  # Используем отформатированный текст
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
            parse_mode="HTML",  # Включаем разбор HTML для кликабельного имени
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
        user_messages=[message.message_id],
    )

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramBadRequest:
        logging.warning(f"Не удалось удалить сообщение {message.message_id}")

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
    await asyncio.sleep(LANGUAGE_SELECTION_TIMEOUT)  # Ждем 5 минут
    current_state = await state.get_state()
    if (
        current_state == UserState.waiting_for_language
    ):  # Проверяем, ждет ли пользователь все еще
        # Получаем сохраненные данные
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
        return  # Игнорируем клики от других пользователей

    lang = data[2]
    await state.update_data(language=lang)

    # Получаем кликабельное имя пользователя в формате HTML
    user_mention = (
        callback.from_user.mention_html()
        if callback.from_user.username
        else callback.from_user.first_name
    )

    # Форматируем сообщение с именем пользователя через {name}
    confirmation_text = dialogs["language_set"][lang].format(name=user_mention)

    # Логируем для отладки
    logging.info(
        f"Выбран язык: {lang}, пользователь: {user_mention}, текст: {confirmation_text}"
    )

    try:
        await callback.message.edit_text(
            text=confirmation_text,
            parse_mode="HTML",  # Включаем разбор HTML для кликабельного имени
        )
    except TelegramBadRequest as e:
        logging.error(f"Не удалось отредактировать сообщение: {e}")
        await callback.message.edit_text(f"Ошибка при выборе языка: {lang}")

    await callback.answer()

    user_data = await state.get_data()
    thread_id = user_data.get("thread_id")

    await callback.message.bot.delete_message(
        callback.message.chat.id, user_data["lang_message_id"]
    )
    await start_quiz(
        callback.message, callback.from_user, state, pool, thread_id=thread_id
    )
