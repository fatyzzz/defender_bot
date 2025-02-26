import asyncio
import logging
import random
from typing import Optional
from aiogram import Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from config import config, questions, dialogs
from database import check_user_passed, check_user_banned, mark_user_passed, PoolType
from utils.moderation import ban_user_after_timeout
from .states import UserState


async def group_message_handler(
    update: types.ChatMemberUpdated,
    state: FSMContext,
    bot: Bot,
    pool: PoolType,
    **kwargs,
) -> None:
    """Обработка новых участников."""
    if update.chat.id != config.ALLOWED_CHAT_ID or update.new_chat_member.user.is_bot:
        return

    user = update.new_chat_member.user
    if (
        update.old_chat_member.status not in ("left", "kicked")
        or update.new_chat_member.status != "member"
        or await check_user_passed(pool, user.id)
        or await check_user_banned(pool, user.id)
    ):
        return

    from .language import language_selection_handler

    message = types.Message(
        message_id=0,
        chat=update.chat,
        from_user=user,
        date=update.date,
    )
    await language_selection_handler(message, state, bot=bot, pool=pool)


async def delete_message(
    bot: Bot, chat_id: int, message_id: int, delay: int = 5
) -> None:
    """Удаление сообщения с задержкой."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        logging.warning(f"Failed to delete message {message_id}")


async def start_quiz(
    message: types.Message,
    user: types.User,
    state: FSMContext,
    pool: PoolType,
    thread_id: Optional[int] = None,
) -> None:
    """Запуск квиза."""
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

    try:
        msg = await message.bot.send_message(
            chat_id=message.chat.id,
            text=f"{dialogs['greeting'][lang].format(name=user.mention_html())}\n<b>{question['question'][lang]}</b>",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard),
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        logging.info(f"Quiz sent to user {user.id} in chat {message.chat.id}")
    except TelegramBadRequest as e:
        logging.warning(f"Failed to send quiz: {e}")
        return

    await state.set_state(UserState.answering_quiz)
    await state.update_data(quiz_message_id=msg.message_id, correct_index=correct_index)

    async def timer_task():
        await asyncio.sleep(30)
        if await state.get_state() == UserState.answering_quiz:
            await timeout_handler(message, user, state, pool, thread_id)

    asyncio.create_task(timer_task())


async def quiz_callback_handler(
    callback: types.CallbackQuery,
    state: FSMContext,
    pool: PoolType,
) -> None:
    """Обработка ответа на квиз."""
    data = callback.data.split("_")
    if len(data) != 4 or int(data[1]) != callback.from_user.id:
        return

    selected_idx, correct_idx = int(data[2]), int(data[3])
    user_data = await state.get_data()
    lang = user_data["language"]
    quiz_message_id = user_data["quiz_message_id"]
    thread_id = user_data.get("thread_id")
    user_messages = user_data.get("user_messages", [])

    await callback.message.bot.delete_message(callback.message.chat.id, quiz_message_id)

    if selected_idx == correct_idx:
        result_msg = await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"✅ {dialogs['correct'][lang]}",
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        await mark_user_passed(pool, callback.from_user.id)
        await state.set_state(UserState.completed)
        asyncio.create_task(
            delete_message(
                callback.message.bot,
                callback.message.chat.id,
                result_msg.message_id,
                10,
            )
        )
        logging.info(f"User {callback.from_user.id} answered correctly")
    else:
        result_msg = await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=f"❌ {dialogs['incorrect'][lang].format(name=callback.from_user.mention_html())}",
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        try:
            await ban_user_after_timeout(
                callback.message.bot,
                callback.message.chat.id,
                callback.from_user.id,
                pool,
            )
            logging.info(
                f"User {callback.from_user.id} processed by ban_user_after_timeout due to incorrect answer"
            )
        except Exception as e:
            logging.error(
                f"Failed to process ban_user_after_timeout for user {callback.from_user.id}: {e}"
            )
        for msg_id in user_messages:
            asyncio.create_task(
                delete_message(callback.message.bot, callback.message.chat.id, msg_id)
            )
        asyncio.create_task(
            delete_message(
                callback.message.bot,
                callback.message.chat.id,
                result_msg.message_id,
                30,
            )
        )
        await state.clear()


async def timeout_handler(
    message: types.Message,
    user: types.User,
    state: FSMContext,
    pool: PoolType,
    thread_id: Optional[int],
) -> None:
    """Обработка таймаута квиза."""
    user_data = await state.get_data()
    lang = user_data["language"]
    quiz_message_id = user_data["quiz_message_id"]
    user_messages = user_data.get("user_messages", [])

    timeout_msg = await message.bot.send_message(
        message.chat.id,
        f"⏰ {dialogs['timeout'][lang].format(name=user.mention_html())}",
        message_thread_id=thread_id,
        parse_mode="HTML",
    )
    try:
        await ban_user_after_timeout(message.bot, message.chat.id, user.id, pool)
        logging.info(
            f"User {user.id} processed by ban_user_after_timeout due to quiz timeout"
        )
    except Exception as e:
        logging.error(
            f"Failed to process ban_user_after_timeout for user {user.id}: {e}"
        )
    for msg_id in user_messages:
        asyncio.create_task(delete_message(message.bot, message.chat.id, msg_id))
    await message.bot.delete_message(message.chat.id, quiz_message_id)
    asyncio.create_task(
        delete_message(message.bot, message.chat.id, timeout_msg.message_id, 60)
    )
    await state.clear()
