import asyncio
import logging
from functools import partial

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import BaseMiddleware

from config import config
from database import create_pool, init_db, cleanup_expired_bans, get_active_poll
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


class PMMiddleware(BaseMiddleware):
    """Middleware для проверки, что действие с опросами происходит в ЛС."""

    async def __call__(self, handler, event, data: dict) -> None:
        if isinstance(event, types.Message):
            return await handler(event, data)
        elif isinstance(event, types.PollAnswer):
            poll_data = await get_active_poll(data["pool"], event.poll_id)
            if poll_data and poll_data["chat_id"] == event.user.id:
                return await handler(event, data)
            else:
                logging.warning(f"PollAnswer not in PM for poll {event.poll_id}")
                return
        else:
            return await handler(event, data)


async def main() -> None:
    """Запуск бота."""
    setup_logging()
    logging.info("Starting bot...")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    pool = await create_pool()
    await init_db(pool)

    # Регистрируем middleware
    dp.update.outer_middleware(ErrorMiddleware())
    dp.message.outer_middleware(PMMiddleware())

    # Настраиваем обработчики
    setup_handlers(dp, bot=bot, pool=pool)

    # Задача для очистки истекших банов
    async def cleanup_task():
        while True:
            await cleanup_expired_bans(pool)
            await asyncio.sleep(config.CLEANUP_INTERVAL)

    asyncio.create_task(cleanup_task())

    # Указываем все типы обновлений явно
    allowed_updates = ["message", "chat_member", "callback_query", "poll", "poll_answer"]
    try:
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())