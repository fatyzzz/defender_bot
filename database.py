import asyncpg
import aiomysql
from typing import Union
from config import config

# Тип пула подключений
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
        if config.DB_SOCKET:  # Подключение через Unix-сокет
            pool = await aiomysql.create_pool(
                unix_socket=config.DB_SOCKET,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                db=config.DB_NAME,
                autocommit=True,
            )
            print("Подключение к MySQL через Unix-сокет создано")
        else:  # Подключение через TCP
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
    """Инициализация таблиц."""
    if config.DB_TYPE == "postgres":
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY
                )
            """
            )
    elif config.DB_TYPE == "mysql":
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY
                    )
                """
                )
