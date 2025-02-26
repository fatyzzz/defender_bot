import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from database import ban_user_in_db, PoolType
from config import config


async def ban_user_after_timeout(bot: Bot, chat_id: int, user_id: int, pool: PoolType) -> None:
    """Мут пользователя на сутки, запись в БД, затем бан и анбан через сутки."""
    mute_duration = 86400  # 24 часа в секундах
    until = datetime.now() + timedelta(seconds=mute_duration)

    try:
        # Мут пользователя на сутки
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            ChatPermissions(can_send_messages=False),
            until_date=until
        )
        logging.info(f"User {user_id} muted for 24 hours in chat {chat_id}")

        # Запись в БД
        await ban_user_in_db(pool, user_id, until)
        logging.info(f"User {user_id} ban recorded in database until {until}")

        # Планируем бан и анбан через сутки
        async def ban_and_unban():
            await asyncio.sleep(mute_duration)
            try:
                await bot.ban_chat_member(chat_id, user_id)  # Бан
                logging.info(f"User {user_id} banned from chat {chat_id}")
                await asyncio.sleep(2)  # Пауза 2 секунды
                await bot.unban_chat_member(chat_id, user_id)  # Анбан
                logging.info(f"User {user_id} unbanned from chat {chat_id}")
            except Exception as e:
                logging.error(f"Failed to ban/unban user {user_id}: {e}")

        asyncio.create_task(ban_and_unban())
    except Exception as e:
        logging.error(f"Failed to mute user {user_id} in chat {chat_id}: {e}")