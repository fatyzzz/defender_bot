import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config import config, questions, dialogs
from database import (
    check_user_passed,
    check_user_banned,
    mark_user_passed,
    PoolType,
    get_active_poll,
    remove_active_poll,
)
from utils.moderation import ban_user_after_timeout
from utils.message_utils import delete_message
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
    await state.update_data(first_message_id=message.message_id)
    await language_selection_handler(message, state, bot=bot, pool=pool)


async def poll_answer_handler(
    poll_answer: types.PollAnswer,
    dp: Dispatcher,
    bot: Bot,
    pool: PoolType,
) -> None:
    """Обработка ответа на опрос в ЛС."""
    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id

    poll_data = await get_active_poll(pool, poll_id)
    if not poll_data or poll_data["user_id"] != user_id:
        return

    chat_id = poll_data["chat_id"]
    message_id = poll_data["message_id"]

    state = dp.fsm.get_context(bot=bot, chat_id=chat_id, user_id=user_id)
    user_data = await state.get_data()

    if user_data.get("quiz_poll_id") != poll_id:
        return

    selected_option = poll_answer.option_ids[0]
    correct_index = user_data["correct_index"]
    lang = user_data["language"]

    await state.update_data(has_answered=True)

    if selected_option == correct_index:
        await state.set_state(UserState.completed)
        await mark_user_passed(pool, user_id)
        result_msg = await bot.send_message(
            chat_id=chat_id,
            text=f"✅ {dialogs['correct'][lang]}",
            parse_mode="HTML",
        )
        group_chat_id = user_data.get("group_chat_id")
        bot_messages = user_data.get("bot_messages", [])
        greeting_message_id = user_data.get("greeting_message_id")
        for msg_id in bot_messages:
            if group_chat_id:
                asyncio.create_task(
                    delete_message(
                        bot, group_chat_id, msg_id, config.MESSAGE_DELETE_DELAY_CORRECT
                    )
                )
        if greeting_message_id:
            asyncio.create_task(
                delete_message(
                    bot,
                    chat_id,
                    greeting_message_id,
                    config.MESSAGE_DELETE_DELAY_CORRECT,
                )
            )
        asyncio.create_task(
            delete_message(
                bot, chat_id, result_msg.message_id, config.MESSAGE_DELETE_DELAY_CORRECT
            )
        )
        logging.info(f"Пользователь {user_id} ответил правильно в ЛС")

        group_state = dp.fsm.get_context(
            bot=bot, chat_id=group_chat_id, user_id=user_id
        )
        await group_state.set_state(UserState.completed)
        logging.info(
            f"Установлено состояние completed для пользователя {user_id} в чате {group_chat_id}"
        )
    else:
        combined_message = (
            f"❌ {dialogs['incorrect'][lang].format(name=poll_answer.user.mention_html())} "
            f"{dialogs['blocked_message'][lang]}"
        )
        result_msg = await bot.send_message(
            chat_id=chat_id,
            text=combined_message,
            parse_mode="HTML",
        )
        group_chat_id = user_data.get("group_chat_id")
        first_message_id = user_data.get("first_message_id")
        bot_messages = user_data.get("bot_messages", [])
        quiz_message_id = user_data.get("quiz_message_id")
        greeting_message_id = user_data.get("greeting_message_id")

        if first_message_id and group_chat_id:
            asyncio.create_task(
                delete_message(bot, group_chat_id, first_message_id, delay=0)
            )
        for msg_id in bot_messages:
            if group_chat_id:
                asyncio.create_task(delete_message(bot, group_chat_id, msg_id, delay=0))
        if greeting_message_id:
            asyncio.create_task(
                delete_message(
                    bot,
                    chat_id,
                    greeting_message_id,
                    config.MESSAGE_DELETE_DELAY_INCORRECT,
                )
            )
        if quiz_message_id:
            asyncio.create_task(
                delete_message(
                    bot, user_id, quiz_message_id, config.MESSAGE_DELETE_DELAY_INCORRECT
                )
            )
        asyncio.create_task(
            delete_message(
                bot,
                chat_id,
                result_msg.message_id,
                config.MESSAGE_DELETE_DELAY_INCORRECT,
            )
        )

        if group_chat_id:
            await ban_user_after_timeout(bot, group_chat_id, user_id, pool)
            logging.info(f"Пользователь {user_id} забанен из-за неправильного ответа")

        group_state = dp.fsm.get_context(
            bot=bot, chat_id=group_chat_id, user_id=user_id
        )
        await group_state.clear()
        logging.info(
            f"Очищено состояние группы для пользователя {user_id} в чате {group_chat_id}"
        )
        await state.clear()

    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        logging.warning(f"Не удалось удалить опрос {poll_id} в чате {chat_id}")
    await remove_active_poll(pool, poll_id)


async def poll_handler(
    poll: types.Poll,
    dp: Dispatcher,
    bot: Bot,
    pool: PoolType,
) -> None:
    """Обработка закрытия опроса (таймаут) в ЛС как запасной вариант."""
    if not poll.is_closed:
        return

    poll_data = await get_active_poll(pool, poll.id)
    if not poll_data:
        return

    user_id = poll_data["user_id"]
    chat_id = poll_data["chat_id"]
    message_id = poll_data["message_id"]

    state = dp.fsm.get_context(bot=bot, chat_id=chat_id, user_id=user_id)
    user_data = await state.get_data()

    if not user_data.get("has_answered", False):
        lang = user_data.get("language", "en")
        combined_message = (
            f"⏰ {dialogs['timeout'][lang].format(name=f'<a href=\"tg://user?id={user_id}\">{user_id}</a>')} "
            f"{dialogs['blocked_message'][lang]}"
        )
        timeout_msg = await bot.send_message(
            chat_id,
            combined_message,
            parse_mode="HTML",
        )
        group_chat_id = user_data.get("group_chat_id")
        first_message_id = user_data.get("first_message_id")
        bot_messages = user_data.get("bot_messages", [])
        quiz_message_id = user_data.get("quiz_message_id")
        greeting_message_id = user_data.get("greeting_message_id")

        if first_message_id and group_chat_id:
            asyncio.create_task(
                delete_message(bot, group_chat_id, first_message_id, delay=0)
            )
        for msg_id in bot_messages:
            if group_chat_id:
                asyncio.create_task(delete_message(bot, group_chat_id, msg_id, delay=0))
        if greeting_message_id:
            asyncio.create_task(
                delete_message(
                    bot,
                    chat_id,
                    greeting_message_id,
                    config.MESSAGE_DELETE_DELAY_TIMEOUT,
                )
            )
        if quiz_message_id:
            asyncio.create_task(
                delete_message(
                    bot, user_id, quiz_message_id, config.MESSAGE_DELETE_DELAY_TIMEOUT
                )
            )
        asyncio.create_task(
            delete_message(
                bot,
                chat_id,
                timeout_msg.message_id,
                config.MESSAGE_DELETE_DELAY_TIMEOUT,
            )
        )

        if group_chat_id:
            await ban_user_after_timeout(bot, group_chat_id, user_id, pool)
            logging.info(
                f"Пользователь {user_id} забанен из-за таймаута опроса (запасной обработчик)"
            )

        group_state = dp.fsm.get_context(
            bot=bot, chat_id=group_chat_id, user_id=user_id
        )
        await group_state.clear()
        logging.info(
            f"Очищено состояние группы для пользователя {user_id} в чате {group_chat_id}"
        )
        await state.clear()

    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        logging.warning(f"Не удалось удалить опрос {poll.id} в чате {chat_id}")
    await remove_active_poll(pool, poll.id)
