import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions

from database import ban_user_in_db, PoolType
from config import config

BAN_DURATION: int = 86_400  # 1 день в секундах


async def ban_user(bot: Bot, chat_id: int, user_id: int, pool: PoolType) -> None:
    """
    Бан пользователя в чате с ограничением отправки сообщений и последующим исключением.

    Args:
        bot (Bot): Экземпляр бота Aiogram.
        chat_id (int): ID чата, где происходит бан.
        user_id (int): ID пользователя, которого нужно забанить.
        pool (PoolType): Пул подключений к базе данных (MySQL или PostgreSQL).
    """
    until = datetime.now() + timedelta(seconds=BAN_DURATION)
    try:
        # Ограничение прав пользователя на отправку сообщений
        await bot.restrict_chat_member(
            chat_id, user_id, ChatPermissions(can_send_messages=False), until_date=until
        )
        # Запись бана в базу данных
        await ban_user_in_db(pool, user_id, until)
        logging.info(f"User {user_id} restricted until {until} in chat {chat_id}")

        # Асинхронная функция для исключения и разбана пользователя
        async def kick_and_unban():
            # Ожидание окончания срока бана
            await asyncio.sleep(BAN_DURATION)
            # Исключение пользователя из чата
            await bot.ban_chat_member(chat_id, user_id)
            await asyncio.sleep(2)
            # Разбан пользователя
            await bot.unban_chat_member(chat_id, user_id)

            # Удаление записи о бане из базы данных с учетом типа базы
            if config.DB_TYPE == "postgres":
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM banned_users WHERE user_id = $1", user_id
                    )
            elif config.DB_TYPE == "mysql":
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "DELETE FROM banned_users WHERE user_id = %s", (user_id,)
                        )
            logging.info(f"User {user_id} kicked and unbanned from chat {chat_id}")

        # Запуск задачи в фоновом режиме
        asyncio.create_task(kick_and_unban())
    except Exception as e:
        logging.error(f"Failed to ban user {user_id} in chat {chat_id}: {e}")
