import asyncio
import logging
import random
from typing import Optional

from aiogram import Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from config import config, questions, dialogs
from database import check_user_passed, check_user_banned, mark_user_passed
from utils.moderation import ban_user
from .states import UserState


async def get_thread_id(chat: types.Chat, thread_id: Optional[int]) -> Optional[int]:
    """Определение thread_id для форумов."""
    if chat.type == "supergroup" and chat.is_forum and thread_id:
        logging.info(f"Using thread_id={thread_id} for chat {chat.id}")
        return thread_id
    logging.info(f"No valid thread_id for chat {chat.id}, forum={chat.is_forum}")
    return None


async def group_message_handler(
    update: types.ChatMemberUpdated,
    state: FSMContext,
    bot: Bot,
    pool: "asyncpg.Pool",
    **kwargs,
) -> None:
    """Обработка новых участников в группе."""
    # Проверяем, что это нужный чат
    if update.chat.id != config.ALLOWED_CHAT_ID:
        return

    user = update.new_chat_member.user

    # Явная проверка на вступление
    if (
        update.old_chat_member.status not in ("left", "kicked")
        or update.new_chat_member.status != "member"
    ):
        logging.info(f"Skipping event for user {user.id}: not a join event")
        return

    # Минимальные проверки: бот, прошел викторину, забанен
    if (
        user.is_bot
        or await check_user_passed(pool, user.id)
        or await check_user_banned(pool, user.id)
    ):
        logging.info(
            f"Skipping event for user {user.id}: bot or already passed or banned"
        )
        return

    # Проверка на дубликаты событий
    update_id = kwargs.get("update_id")
    user_data = await state.get_data()
    last_update_id = user_data.get("last_update_id")
    if last_update_id == update_id:
        logging.info(
            f"Duplicate event skipped for user {user.id}, update_id={update_id}"
        )
        return

    # Запускаем выбор языка
    from .language import language_selection_handler

    message = types.Message(
        message_id=0,
        chat=update.chat,
        from_user=user,
        date=update.date,
    )
    logging.info(
        f"New member {user.id} joined, triggering language selection, update_id={update_id}"
    )
    await language_selection_handler(message, state, bot=bot, pool=pool)
    await state.update_data(last_update_id=update_id)


async def delete_message(
    bot: Bot, chat_id: int, message_id: int, delay: int = 5
) -> None:
    """Удаление сообщения с задержкой."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.warning(f"Failed to delete message {message_id}: {e}")


async def start_quiz(
    message: types.Message,
    user: types.User,
    state: FSMContext,
    pool: "asyncpg.Pool",
    orig_message_id: int,
) -> None:
    """Запуск викторины."""
    user_data = await state.get_data()
    lang = user_data["language"]
    question = random.choice(questions)
    answers = question["answers"][lang]
    indices = list(range(len(answers)))
    random.shuffle(indices)
    correct_index = indices.index(question["correct_index"])

    keyboard = [
        [
            types.InlineKeyboardButton(
                text=answers[i], callback_data=f"quiz_{user.id}_{j}_{correct_index}"
            )
        ]
        for j, i in enumerate(indices)
    ]
    thread_id = await get_thread_id(
        message.chat, message.message_thread_id or config.FALLBACK_THREAD_ID
    )

    try:
        # Пробуем отправить сообщение с thread_id, если он есть и валиден
        msg = await message.bot.send_message(
            chat_id=message.chat.id,
            text=f"{dialogs['greeting'][lang].format(name=user.mention_html())}\n<b>{question['question'][lang]}</b>",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard),
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        logging.info(
            f"Message sent to chat {message.chat.id} with thread_id={thread_id}"
        )
    except TelegramBadRequest as e:
        logging.warning(f"Failed to send message with thread_id={thread_id}: {e}")
        # Повторная попытка без thread_id
        msg = await message.bot.send_message(
            chat_id=message.chat.id,
            text=f"{dialogs['greeting'][lang].format(name=user.mention_html())}\n<b>{question['question'][lang]}</b>",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML",
        )
        logging.info(f"Message sent to chat {message.chat.id} without thread_id")

    await state.set_state(UserState.answering_quiz)
    await state.update_data(quiz_message_id=msg.message_id, correct_index=correct_index)

    async def timer_task():
        await asyncio.sleep(20)
        if await state.get_state() == UserState.answering_quiz:
            try:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text="⏳ <b>10 секунд осталось!</b>",
                    message_thread_id=thread_id,
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text="⏳ <b>10 секунд осталось!</b>",
                    parse_mode="HTML",
                )
        await asyncio.sleep(10)
        if await state.get_state() == UserState.answering_quiz:
            await timeout_handler(message, user, state, pool, orig_message_id)

    asyncio.create_task(timer_task())


async def quiz_callback_handler(
    callback: types.CallbackQuery, state: FSMContext, pool: "asyncpg.Pool"
) -> None:
    """Обработка ответа на викторину."""
    data = callback.data.split("_")
    if len(data) != 4 or int(data[1]) != callback.from_user.id:
        return

    selected_idx, correct_idx = int(data[2]), int(data[3])
    user_data = await state.get_data()
    lang = user_data["language"]
    quiz_message_id = user_data["quiz_message_id"]
    orig_message_id = user_data["orig_message_id"]
    thread_id = user_data.get("thread_id")  # Получаем thread_id из состояния

    await callback.message.bot.delete_message(callback.message.chat.id, quiz_message_id)
    if selected_idx == correct_idx:
        result_msg = await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"✅ {dialogs['correct'][lang]}",
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        await mark_user_passed(pool, callback.from_user.id)
        logging.info(
            f"Correct answer reported in chat {callback.message.chat.id} with thread_id={thread_id}"
        )
    else:
        result_msg = await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"❌ {dialogs['incorrect'][lang].format(name=callback.from_user.mention_html())}",
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        await ban_user(
            callback.message.bot, callback.message.chat.id, callback.from_user.id, pool
        )
        if orig_message_id:
            asyncio.create_task(
                delete_message(
                    callback.message.bot, callback.message.chat.id, orig_message_id
                )
            )
        logging.info(
            f"Incorrect answer reported in chat {callback.message.chat.id} with thread_id={thread_id}"
        )

    asyncio.create_task(
        delete_message(
            callback.message.bot, callback.message.chat.id, result_msg.message_id, 30
        )
    )
    await state.clear()


async def timeout_handler(
    message: types.Message,
    user: types.User,
    state: FSMContext,
    pool: "asyncpg.Pool",
    orig_message_id: int,
) -> None:
    """Обработка таймаута викторины."""
    user_data = await state.get_data()
    lang = user_data["language"]
    quiz_message_id = user_data["quiz_message_id"]

    timeout_msg = await message.bot.send_message(
        message.chat.id,
        f"⏰ {dialogs['timeout'][lang].format(name=user.mention_html())}",
        parse_mode="HTML",
    )
    await ban_user(message.bot, message.chat.id, user.id, pool)
    if orig_message_id:
        asyncio.create_task(
            delete_message(message.bot, message.chat.id, orig_message_id)
        )
    await message.bot.delete_message(message.chat.id, quiz_message_id)
    asyncio.create_task(
        delete_message(message.bot, message.chat.id, timeout_msg.message_id, 60)
    )
    await state.clear()
