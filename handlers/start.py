import asyncio
import logging
import random

from aiogram import types, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from config import config, questions, dialogs
from database import PoolType, add_active_poll
from handlers.states import UserState


async def start_handler(message: types.Message, state: FSMContext, bot: Bot, pool: PoolType, dp) -> None:
    """Обработка команды /start в ЛС."""
    if message.chat.type != "private":
        return

    command_text = message.text
    if command_text.startswith("/start "):
        args = command_text.split(" ", 1)[1].split("_")
        if len(args) == 4 and args[0] == "quiz":
            try:
                user_id = int(args[1])
                lang = args[2]
                group_chat_id = int(args[3])
                if user_id != message.from_user.id:
                    await message.reply("Этот опрос не для вас.")
                    return
                # Копируем данные из группового состояния в PM состояние
                group_state = dp.fsm.get_context(bot=bot, chat_id=group_chat_id, user_id=user_id)
                group_data = await group_state.get_data()
                first_message_id = group_data.get("first_message_id")
                bot_messages = group_data.get("bot_messages", [])
                await state.update_data(
                    language=lang,
                    group_chat_id=group_chat_id,
                    first_message_id=first_message_id,
                    bot_messages=bot_messages,
                )
                await send_poll_to_pm(message, state, bot, pool, dp)
            except ValueError:
                await message.reply("Неверный формат команды.")
        else:
            await message.reply("Неверный формат команды. Используйте /quiz для начала опроса.")
    else:
        await message.reply("Добро пожаловать! Используйте /quiz для начала опроса.")


async def send_poll_to_pm(message: types.Message, state: FSMContext, bot: Bot, pool: PoolType, dp) -> None:
    """Отправляет опрос в ЛС пользователя и запускает таймер."""
    user_data = await state.get_data()
    lang = user_data.get("language", "en")
    question = random.choice(questions)
    answers = question["answers"][lang]
    correct_index = question["correct_index"]

    indices = list(range(len(answers)))
    random.shuffle(indices)
    shuffled_answers = [answers[i] for i in indices]
    new_correct_index = indices.index(correct_index)

    # Отправляем приветственное сообщение отдельно
    greeting_text = dialogs["greeting"][lang].format(name=message.from_user.mention_html())
    try:
        greeting_msg = await bot.send_message(
            chat_id=message.from_user.id,
            text=greeting_text,
            parse_mode="HTML",
        )
    except Exception as e:
        logging.warning(f"Не удалось отправить приветственное сообщение в ЛС: {e}")
        return

    # Отправляем сам опрос без приветствия
    try:
        poll = await bot.send_poll(
            chat_id=message.from_user.id,
            question=question["question"][lang],  # Только текст вопроса
            options=shuffled_answers,
            type="quiz",
            correct_option_id=new_correct_index,
            open_period=config.QUIZ_ANSWER_TIMEOUT,  # 30 секунд
            is_anonymous=False,
        )
        logging.info(f"Опрос отправлен пользователю {message.from_user.id} в ЛС")
    except Exception as e:
        logging.warning(f"Не удалось отправить опрос в ЛС: {e}")
        # Удаляем приветственное сообщение, если опрос не отправился
        await bot.delete_message(message.from_user.id, greeting_msg.message_id)
        return

    # Регистрируем опрос в базе данных
    await add_active_poll(
        pool,
        poll.poll.id,
        message.from_user.id,
        message.chat.id,
        poll.message_id,
        None,  # thread_id в ЛС не нужен
    )
    logging.info(f"Опрос {poll.poll.id} зарегистрирован для пользователя {message.from_user.id}")

    # Обновляем состояние с учётом двух сообщений
    await state.set_state(UserState.answering_quiz)
    await state.update_data(
        quiz_poll_id=poll.poll.id,
        quiz_message_id=poll.message_id,
        greeting_message_id=greeting_msg.message_id,  # Сохраняем ID приветствия
        correct_index=new_correct_index,
        has_answered=False,
        chat_id=message.from_user.id,
        language=lang,
    )

    # Запускаем таймер для проверки таймаута
    asyncio.create_task(check_poll_timeout(bot, state, message.from_user.id, dp, pool))


async def check_poll_timeout(bot: Bot, state: FSMContext, user_id: int, dp, pool: PoolType) -> None:
    """Проверяет, ответил ли пользователь на опрос за отведенное время."""
    await asyncio.sleep(config.QUIZ_ANSWER_TIMEOUT)  # Ждём 30 секунд
    user_data = await state.get_data()
    if not user_data.get("has_answered", False):
        lang = user_data.get("language", "en")
        group_chat_id = user_data.get("group_chat_id")
        first_message_id = user_data.get("first_message_id")
        bot_messages = user_data.get("bot_messages", [])
        quiz_message_id = user_data.get("quiz_message_id")
        greeting_message_id = user_data.get("greeting_message_id")
        poll_id = user_data.get("quiz_poll_id")

        # Отправляем сообщение о таймауте в ЛС
        combined_message = (
            f"⏰ {dialogs['timeout'][lang].format(name=f'<a href=\"tg://user?id={user_id}\">{user_id}</a>')} "
            f"{dialogs['blocked_message'][lang]}"
        )
        timeout_msg = await bot.send_message(
            user_id,
            combined_message,
            parse_mode="HTML",
        )

        # Моментально удаляем сообщения в чате
        if first_message_id and group_chat_id:
            from utils.message_utils import delete_message
            asyncio.create_task(delete_message(bot, group_chat_id, first_message_id, delay=0))
        for msg_id in bot_messages:
            if group_chat_id:
                asyncio.create_task(delete_message(bot, group_chat_id, msg_id, delay=0))

        # Удаляем сообщения в ЛС с задержкой
        if greeting_message_id:
            asyncio.create_task(delete_message(bot, user_id, greeting_message_id, config.MESSAGE_DELETE_DELAY_TIMEOUT))
        if quiz_message_id:
            asyncio.create_task(delete_message(bot, user_id, quiz_message_id, config.MESSAGE_DELETE_DELAY_TIMEOUT))
        asyncio.create_task(delete_message(bot, user_id, timeout_msg.message_id, config.MESSAGE_DELETE_DELAY_TIMEOUT))

        # Баним пользователя
        if group_chat_id:
            from utils.moderation import ban_user_after_timeout
            await ban_user_after_timeout(bot, group_chat_id, user_id, pool)
            logging.info(f"Пользователь {user_id} забанен из-за таймаута опроса")

        # Очищаем состояния
        group_state = dp.fsm.get_context(bot=bot, chat_id=group_chat_id, user_id=user_id)
        await group_state.clear()
        await state.clear()

        # Удаляем опрос из базы
        if poll_id:
            from database import remove_active_poll
            await remove_active_poll(pool, poll_id)