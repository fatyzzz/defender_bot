import logging
from datetime import datetime
from typing import Union, Optional

import asyncpg
import aiomysql
import pymysql

from config import config

PoolType = Union[asyncpg.Pool, aiomysql.Pool]


async def create_pool() -> PoolType:
    """Создание пула подключений в зависимости от DB_TYPE."""
    if config.DB_TYPE == "postgres":
        pool = await asyncpg.create_pool(
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            host=config.DB_HOST,
            port=config.DB_PORT,
        )
        print("Подключение к PostgreSQL создано")
        return pool
    elif config.DB_TYPE == "mysql":
        if config.DB_SOCKET:
            pool = await aiomysql.create_pool(
                unix_socket=config.DB_SOCKET,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                db=config.DB_NAME,
                autocommit=True,
            )
            print("Подключение к MySQL через Unix-сокет создано")
        else:
            pool = await aiomysql.create_pool(
                host=config.DB_HOST,
                port=config.DB_PORT,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                db=config.DB_NAME,
                autocommit=True,
            )
            print("Подключение к MySQL через TCP создано")
        return pool
    else:
        raise ValueError("Неподдерживаемый DB_TYPE")


async def init_db(pool: PoolType) -> None:
    """Инициализация таблиц и индексов в базе данных."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS passed_users (
                    user_id BIGINT PRIMARY KEY,
                    passed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id BIGINT PRIMARY KEY,
                    banned_until TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS active_polls (
                    poll_id VARCHAR(255) PRIMARY KEY,
                    user_id BIGINT,
                    chat_id BIGINT,
                    message_id BIGINT,
                    thread_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_banned_users_banned_until 
                ON banned_users (banned_until);
                """
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS passed_users (
                        user_id BIGINT PRIMARY KEY,
                        passed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS banned_users (
                        user_id BIGINT PRIMARY KEY,
                        banned_until TIMESTAMP
                    )
                    """
                )
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS active_polls (
                        poll_id VARCHAR(255) PRIMARY KEY,
                        user_id BIGINT,
                        chat_id BIGINT,
                        message_id BIGINT,
                        thread_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                try:
                    await cur.execute(
                        """
                        CREATE INDEX idx_banned_users_banned_until 
                        ON banned_users (banned_until)
                        """
                    )
                except pymysql.err.OperationalError as e:
                    if e.args[0] == 1061:  # Duplicate key name
                        pass
                    else:
                        raise
    logging.info("Database initialized")


async def check_user_passed(pool: PoolType, user_id: int) -> bool:
    """Проверка, прошел ли пользователь викторину."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM passed_users WHERE user_id = $1)", user_id
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM passed_users WHERE user_id = %s)",
                    (user_id,),
                )
                result = await cur.fetchone()
                return bool(result[0])


async def check_user_banned(pool: PoolType, user_id: int) -> bool:
    """Проверка, забанен ли пользователь."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM banned_users WHERE user_id = $1 AND banned_until > NOW())",
                user_id,
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM banned_users WHERE user_id = %s AND banned_until > NOW())",
                    (user_id,),
                )
                result = await cur.fetchone()
                return bool(result[0])


async def mark_user_passed(pool: PoolType, user_id: int) -> None:
    """Отметка пользователя как прошедшего викторину."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO passed_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                user_id,
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO passed_users (user_id) VALUES (%s) ON DUPLICATE KEY UPDATE user_id = user_id",
                    (user_id,),
                )


async def ban_user_in_db(pool: PoolType, user_id: int, until: datetime) -> None:
    """Запись бана пользователя в БД."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO banned_users (user_id, banned_until) VALUES ($1, $2) "
                "ON CONFLICT (user_id) DO UPDATE SET banned_until = $2",
                user_id,
                until,
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO banned_users (user_id, banned_until) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE banned_until = %s",
                    (user_id, until, until),
                )


async def cleanup_expired_bans(pool: PoolType) -> None:
    """Удаление истёкших банов."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM banned_users WHERE banned_until <= NOW()"
            )
            if result != "DELETE 0":
                logging.info(f"Removed expired bans: {result}")
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM banned_users WHERE banned_until <= NOW()"
                )
                if cur.rowcount > 0:
                    logging.info(f"Removed expired bans: {cur.rowcount}")


async def delete_user_from_db(pool: PoolType, user_id: int) -> None:
    """Удаление пользователя из таблиц passed_users и banned_users."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM passed_users WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM banned_users WHERE user_id = $1", user_id)
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM passed_users WHERE user_id = %s", (user_id,))
                await cur.execute("DELETE FROM banned_users WHERE user_id = %s", (user_id,))
    logging.info(f"User {user_id} deleted from database")


async def add_active_poll(
    pool: PoolType,
    poll_id: str,
    user_id: int,
    chat_id: int,
    message_id: int,
    thread_id: Optional[int],
) -> None:
    """Добавить активный опрос в БД."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO active_polls (poll_id, user_id, chat_id, message_id, thread_id)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (poll_id) DO NOTHING
                """,
                poll_id,
                user_id,
                chat_id,
                message_id,
                thread_id,
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO active_polls (poll_id, user_id, chat_id, message_id, thread_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE poll_id = poll_id
                    """,
                    (poll_id, user_id, chat_id, message_id, thread_id),
                )


async def get_active_poll(pool: PoolType, poll_id: str) -> Optional[dict]:
    """Получить данные активного опроса по poll_id."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, chat_id, message_id, thread_id FROM active_polls WHERE poll_id = $1",
                poll_id,
            )
            return dict(row) if row else None
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT user_id, chat_id, message_id, thread_id FROM active_polls WHERE poll_id = %s",
                    (poll_id,),
                )
                row = await cur.fetchone()
                if row:
                    return {
                        "user_id": row[0],
                        "chat_id": row[1],
                        "message_id": row[2],
                        "thread_id": row[3],
                    }
                return None


async def remove_active_poll(pool: PoolType, poll_id: str) -> None:
    """Удалить активный опрос из БД."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM active_polls WHERE poll_id = $1", poll_id)
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM active_polls WHERE poll_id = %s", (poll_id,))