import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from database import ban_user_in_db

BAN_DURATION: int = 86_400  # 1 день в секундах


async def ban_user(bot: Bot, chat_id: int, user_id: int, pool) -> None:
    """Мут пользователя на сутки с последующим исключением и разбаном."""
    until_date = datetime.now() + timedelta(seconds=BAN_DURATION)
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date,
        )
        await ban_user_in_db(pool, user_id, until_date)
        logging.info(f"User {user_id} muted until {until_date} in chat {chat_id}")

        async def kick_and_unban():
            await asyncio.sleep(BAN_DURATION)  # Ждём сутки
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                logging.info(
                    f"User {user_id} kicked from chat {chat_id} after mute expired"
                )
                await asyncio.sleep(2)  # Ждём 2 секунды
                await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                logging.info(f"User {user_id} unbanned from chat {chat_id}")
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM banned_users WHERE user_id = $1", user_id
                    )
                    logging.info(f"User {user_id} removed from banned_users")
            except Exception as e:
                logging.error(f"Failed to kick/unban user {user_id}: {e}")

        asyncio.create_task(kick_and_unban())
    except Exception as e:
        logging.error(f"Failed to restrict user {user_id} in chat {chat_id}: {e}")
