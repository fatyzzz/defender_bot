import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from config import config
from database import ban_user_in_db, PoolType, delete_user_from_db


async def ban_user_after_timeout(bot: Bot, chat_id: int, user_id: int, pool: PoolType) -> None:
    """Мут пользователя на сутки, запись в БД, затем бан и анбан через сутки."""
    mute_duration = config.MUTE_DURATION
    until = datetime.now() + timedelta(seconds=mute_duration)

    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            ChatPermissions(can_send_messages=False),
            until_date=until
        )
        logging.info(f"Пользователь {user_id} замьючен на 24 часа в чате {chat_id}")

        await ban_user_in_db(pool, user_id, until)
        logging.info(f"Бан пользователя {user_id} записан в БД до {until}")

        async def ban_and_unban():
            await asyncio.sleep(mute_duration)
            try:
                await bot.ban_chat_member(chat_id, user_id)
                logging.info(f"Пользователь {user_id} забанен в чате {chat_id}")
                await asyncio.sleep(config.UNBAN_DELAY)
                await bot.unban_chat_member(chat_id, user_id)
                logging.info(f"Пользователь {user_id} разбанен в чате {chat_id}")
                await asyncio.sleep(config.DB_DELETE_DELAY)
                await delete_user_from_db(pool, user_id)
                logging.info(f"Пользователь {user_id} удалён из БД после разбана")
            except Exception as e:
                logging.error(f"Ошибка при бане/разбане пользователя {user_id}: {e}")

        asyncio.create_task(ban_and_unban())
    except Exception as e:
        logging.error(f"Ошибка при муте пользователя {user_id} в чате {chat_id}: {e}")