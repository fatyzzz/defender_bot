import logging
from datetime import datetime
from typing import Optional

import asyncpg


async def create_pool() -> asyncpg.Pool:
    """Создание пула подключений к PostgreSQL."""
    from config import config  # Локальный импорт для избежания циклических зависимостей

    return await asyncpg.create_pool(
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        host=config.DB_HOST,
        port=5432,
    )


async def init_db(pool: asyncpg.Pool) -> None:
    """Инициализация таблиц и индексов в базе данных."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS passed_users (
                user_id BIGINT PRIMARY KEY,
                passed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY,
                banned_until TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_banned_users_banned_until 
            ON banned_users (banned_until);
        """)
        logging.info("Database initialized")


async def check_user_passed(pool: asyncpg.Pool, user_id: int) -> bool:
    """Проверка, прошел ли пользователь викторину."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM passed_users WHERE user_id = $1)", user_id
        )


async def check_user_banned(pool: asyncpg.Pool, user_id: int) -> bool:
    """Проверка, забанен ли пользователь."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM banned_users WHERE user_id = $1 AND banned_until > NOW())",
            user_id,
        )


async def mark_user_passed(pool: asyncpg.Pool, user_id: int) -> None:
    """Отметка пользователя как прошедшего викторину."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO passed_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id,
        )


async def ban_user_in_db(pool: asyncpg.Pool, user_id: int, until: datetime) -> None:
    """Запись бана пользователя в БД."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO banned_users (user_id, banned_until) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET banned_until = $2",
            user_id,
            until,
        )


async def cleanup_expired_bans(pool: asyncpg.Pool) -> None:
    """Удаление истёкших банов."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM banned_users WHERE banned_until <= NOW()"
        )
        if result != "DELETE 0":
            logging.info(f"Removed expired bans: {result}")