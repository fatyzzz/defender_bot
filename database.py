import logging
from datetime import datetime

import asyncpg

from config import Config


async def create_pool() -> asyncpg.Pool:
    """Создание пула подключений к PostgreSQL."""
    return await asyncpg.create_pool(
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        host=Config.DB_HOST,
        port=5432,
    )


async def init_db(pool: asyncpg.Pool) -> None:
    """Инициализация таблиц в базе данных."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS passed_users (
                user_id BIGINT PRIMARY KEY,
                passed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY,
                banned_until TIMESTAMP
            )
        """
        )


async def check_user_passed(pool: asyncpg.Pool, user_id: int) -> bool:
    """Проверка, прошел ли пользователь викторину."""
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT user_id FROM passed_users WHERE user_id = $1", user_id
        )
        return result is not None


async def check_user_banned(pool: asyncpg.Pool, user_id: int) -> bool:
    """Проверка, забанен ли пользователь."""
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT user_id FROM banned_users WHERE user_id = $1 AND banned_until > NOW()",
            user_id,
        )
        return result is not None


async def mark_user_passed(pool: asyncpg.Pool, user_id: int) -> None:
    """Отметка пользователя как прошедшего викторину."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO passed_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id,
        )


async def ban_user_in_db(
    pool: asyncpg.Pool, user_id: int, banned_until: datetime
) -> None:
    """Запись бана пользователя в БД."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO banned_users (user_id, banned_until)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET banned_until = $2
            """,
            user_id,
            banned_until,
        )


async def cleanup_expired_bans(pool: asyncpg.Pool) -> None:
    """Удаление истёкших записей о банах из базы данных (для старых записей)."""
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM banned_users WHERE banned_until <= NOW()"
        )
        if deleted != "DELETE 0":
            logging.info(f"Cleaned up expired bans: {deleted}")
