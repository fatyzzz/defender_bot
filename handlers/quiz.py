import asyncio
import logging
import random

import asyncpg
from aiogram import types, Bot
from aiogram.fsm.context import FSMContext

from config import Config, questions, dialogs
from database import check_user_passed, check_user_banned, mark_user_passed
from utils.moderation import ban_user
from .states import UserState


async def get_thread_id(chat: types.Chat, current_thread_id: int | None) -> int | None:
    """Получение thread_id для форумных групп, если применимо."""
    if chat.type == "supergroup" and chat.is_forum:
        if current_thread_id:
            return current_thread_id
        fallback = Config.FALLBACK_THREAD_ID
        if fallback:
            logging.info(f"Using fallback thread_id: {fallback}")
            return fallback
        logging.error(
            "Forum group detected but no thread id provided and FALLBACK_THREAD_ID is not set."
        )
        return None
    return None  # Для обычных чатов thread_id не нужен


async def group_message_handler(
    message: types.Message, state: FSMContext, pool: "asyncpg.Pool"
) -> None:
    """Обработка сообщений в группе."""
    user_id = message.from_user.id
    if message.chat.id != Config.ALLOWED_CHAT_ID:
        return

    if await check_user_passed(pool, user_id) or await check_user_banned(pool, user_id):
        logging.info(f"User {user_id} already passed or banned, skipping quiz")
        return

    current_state = await state.get_state()
    if current_state is None:
        from .language import language_selection_handler

        await language_selection_handler(message, state, pool)
    else:
        await message.delete()
        logging.info(f"Deleted message from user {user_id} during quiz")


async def delete_message(
    bot: Bot, chat_id: int, message_id: int, delay: int = 5
) -> None:
    """Удаление сообщения через заданное время."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logging.warning(f"Failed to delete message {message_id}: {e}")


async def start_quiz(
    message: types.Message,
    user: types.User,
    state: FSMContext,
    pool: "asyncpg.Pool",
    orig_message_id: int,
) -> None:
    """Запуск викторины для пользователя."""
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
    reply_markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)

    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    msg_text = (
        f"{dialogs['greeting'][lang].format(name=user_link)}\n"
        f"<b>{question['question'][lang]}</b>"
    )
    thread_id = await get_thread_id(message.chat, message.message_thread_id)
    msg = await message.bot.send_message(
        chat_id=message.chat.id,
        text=msg_text,
        reply_markup=reply_markup,
        message_thread_id=(
            thread_id if thread_id is not None else None
        ),  # Условно передаём thread_id
        parse_mode="HTML",
    )
    await state.set_state(UserState.answering_quiz)
    await state.update_data(quiz_message_id=msg.message_id, correct_index=correct_index)

    async def timer_task():
        await asyncio.sleep(20)
        if await state.get_state() == UserState.answering_quiz:
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=f"⏳ <b>10 секунд осталось!</b>",
                message_thread_id=thread_id if thread_id is not None else None,
                parse_mode="HTML",
            )
        await asyncio.sleep(10)
        if await state.get_state() == UserState.answering_quiz:
            await timeout_handler(message, user, state, pool, orig_message_id)

    timer = asyncio.create_task(timer_task())
    await state.update_data(timer_task=timer)


async def quiz_callback_handler(
    callback: types.CallbackQuery, state: FSMContext, pool: "asyncpg.Pool"
) -> None:
    """Обработка ответа на викторину."""
    data = callback.data.split("_")
    if len(data) != 4 or int(data[1]) != callback.from_user.id:
        return

    selected_index, correct_index = int(data[2]), int(data[3])
    user_data = await state.get_data()
    lang = user_data["language"]
    user_link = f'<a href="tg://user?id={callback.from_user.id}">{callback.from_user.full_name}</a>'
    quiz_message_id = user_data["quiz_message_id"]
    timer_task = user_data.get("timer_task")
    orig_message_id = user_data.get("orig_message_id")
    thread_id = await get_thread_id(
        callback.message.chat, callback.message.message_thread_id
    )

    if timer_task and not timer_task.done():
        timer_task.cancel()
        logging.info(f"Timer cancelled for user {callback.from_user.id}")

    if selected_index == correct_index:
        result_msg = await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"✅ {dialogs['correct'][lang]}",
            parse_mode="HTML",
            message_thread_id=thread_id if thread_id is not None else None,
        )
        await mark_user_passed(pool, callback.from_user.id)
        logging.info(f"User {callback.from_user.id} passed the quiz")
    else:
        result_msg = await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"❌ {dialogs['incorrect'][lang].format(name=user_link)}",
            parse_mode="HTML",
            message_thread_id=thread_id if thread_id is not None else None,
        )
        await ban_user(
            callback.message.bot, callback.message.chat.id, callback.from_user.id, pool
        )
        logging.info(f"User {callback.from_user.id} failed the quiz and was muted")
        if orig_message_id:
            asyncio.create_task(
                delete_message(
                    callback.message.bot, callback.message.chat.id, orig_message_id
                )
            )

    await callback.message.bot.delete_message(
        chat_id=callback.message.chat.id, message_id=quiz_message_id
    )
    asyncio.create_task(
        delete_message(
            callback.message.bot, callback.message.chat.id, result_msg.message_id, 30
        )
    )

    await callback.answer()
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
    user_link = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    quiz_message_id = user_data["quiz_message_id"]
    thread_id = await get_thread_id(message.chat, message.message_thread_id)

    timeout_msg = await message.bot.send_message(
        chat_id=message.chat.id,
        text=f"⏰ {dialogs['timeout'][lang].format(name=user_link)}",
        message_thread_id=thread_id if thread_id is not None else None,
        parse_mode="HTML",
    )
    await ban_user(message.bot, message.chat.id, user.id, pool)
    if orig_message_id:
        asyncio.create_task(
            delete_message(message.bot, message.chat.id, orig_message_id)
        )

    await message.bot.delete_message(
        chat_id=message.chat.id, message_id=quiz_message_id
    )
    await asyncio.sleep(60)
    await message.bot.delete_message(
        chat_id=message.chat.id, message_id=timeout_msg.message_id
    )

    await state.clear()
