import asyncio
import logging
from datetime import datetime, timedelta
from config import config
from aiogram import Bot
from aiogram.types import ChatPermissions

from database import ban_user_in_db, PoolType, delete_user_from_db


async def ban_user_after_timeout(
    bot: Bot, chat_id: int, user_id: int, pool: PoolType
) -> None:
    """Мут пользователя на сутки, запись в БД, затем бан и анбан через сутки."""
    mute_duration = config.MUTE_DURATION  # 24 часа в секундах
    until = datetime.now() + timedelta(seconds=mute_duration)

    try:
        # Мут пользователя на сутки
        await bot.restrict_chat_member(
            chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=until
        )
        logging.info(f"User {user_id} muted for 24 hours in chat {chat_id}")

        # Запись в БД
        await ban_user_in_db(pool, user_id, until)
        logging.info(f"User {user_id} ban recorded in database until {until}")

        # Планируем бан, анбан и удаление из БД
        async def ban_and_unban():
            await asyncio.sleep(mute_duration)
            try:
                await bot.ban_chat_member(chat_id, user_id)  # Бан
                logging.info(f"User {user_id} banned from chat {chat_id}")
                await asyncio.sleep(config.UNBAN_DELAY)  # Пауза 2 секунды перед анбаном
                await bot.unban_chat_member(chat_id, user_id)  # Анбан
                logging.info(f"User {user_id} unbanned from chat {chat_id}")
                await asyncio.sleep(
                    config.DB_DELETE_DELAY
                )  # Пауза 5 секунд перед удалением из БД
                await delete_user_from_db(pool, user_id)  # Удаление из БД
                logging.info(f"User {user_id} removed from database after unban")
            except Exception as e:
                logging.error(f"Failed to ban/unban or delete user {user_id}: {e}")

        asyncio.create_task(ban_and_unban())
    except Exception as e:
        logging.error(f"Failed to mute user {user_id} in chat {chat_id}: {e}")
