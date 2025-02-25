import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from config import Config
from database import (
    create_pool,
    init_db,
    cleanup_expired_bans,
)
from handlers.language import language_callback_handler
from handlers.quiz import group_message_handler, quiz_callback_handler
from handlers.start import start_handler
from utils.logger import setup_logging


async def main() -> None:
    setup_logging()
    logging.info("Starting bot...")

    bot = Bot(token=Config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    pool = await create_pool()
    await init_db(pool)

    @dp.message(Command(commands=["start"]))
    async def _(message: types.Message) -> None:
        await start_handler(message)

    @dp.message(
        lambda message: message.chat.type in ["group", "supergroup"]
        and message.new_chat_members is not None
    )
    async def _(message: types.Message, state: "FSMContext") -> None:
        for member in message.new_chat_members:
            if not member.is_bot:
                await group_message_handler(message, state, pool)
                break

    @dp.callback_query(lambda c: c.data.startswith("lang_"))
    async def _(callback: types.CallbackQuery, state: "FSMContext") -> None:
        await language_callback_handler(callback, state, pool)

    @dp.callback_query(lambda c: c.data.startswith("quiz_"))
    async def _(callback: types.CallbackQuery, state: "FSMContext") -> None:
        await quiz_callback_handler(callback, state, pool)

    @dp.errors()
    async def error_handler(update: types.Update, exception: Exception) -> None:
        logging.error(
            f"Unhandled exception for update {update.update_id}: {exception}",
            exc_info=True,
        )

    async def cleanup_task():
        while True:
            await cleanup_expired_bans(pool)
            await asyncio.sleep(300)

    asyncio.create_task(cleanup_task())

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logging.error(f"Polling failed: {e}", exc_info=True)
    finally:
        await bot.session.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
