import asyncio
import logging
from functools import partial

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import BaseMiddleware

from config import config
from database import create_pool, init_db, cleanup_expired_bans
from handlers import setup_handlers
from utils.logger import setup_logging


class ErrorMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок."""
    async def __call__(self, handler, event, data: dict) -> None:
        try:
            return await handler(event, data)
        except Exception as e:
            logging.error(f"Unhandled exception for update {event.update_id}: {e}", exc_info=True)
            raise


async def main() -> None:
    """Запуск бота."""
    setup_logging()
    logging.info("Starting bot...")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    pool = await create_pool()
    await init_db(pool)

    dp.update.outer_middleware(ErrorMiddleware())
    setup_handlers(dp, bot=bot, pool=pool)  # Передаём bot и pool

    async def cleanup_task():
        while True:
            await cleanup_expired_bans(pool)
            await asyncio.sleep(300)

    asyncio.create_task(cleanup_task())

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())