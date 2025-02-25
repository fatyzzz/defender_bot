import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from database import ban_user_in_db

BAN_DURATION: int = 86_400  # 1 день в секундах


async def ban_user(bot: Bot, chat_id: int, user_id: int, pool: "asyncpg.Pool") -> None:
    """Бан пользователя с ограничением сообщений и последующим исключением."""
    until = datetime.now() + timedelta(seconds=BAN_DURATION)
    try:
        await bot.restrict_chat_member(
            chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=until
        )
        await ban_user_in_db(pool, user_id, until)
        logging.info(f"User {user_id} restricted until {until} in chat {chat_id}")

        async def kick_and_unban():
            await asyncio.sleep(BAN_DURATION)
            await bot.ban_chat_member(chat_id, user_id)
            await asyncio.sleep(2)
            await bot.unban_chat_member(chat_id, user_id)
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM banned_users WHERE user_id = $1", user_id)
            logging.info(f"User {user_id} kicked and unbanned from chat {chat_id}")

        asyncio.create_task(kick_and_unban())
    except Exception as e:
        logging.error(f"Failed to ban user {user_id} in chat {chat_id}: {e}")