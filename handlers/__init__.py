from aiogram import Dispatcher

from .language import language_selection_handler, language_callback_handler
from .quiz import group_message_handler, quiz_callback_handler
from .start import start_handler


def setup_handlers(dp: Dispatcher):
    dp.message.register(start_handler, commands=["start"])
    dp.message.register(
        group_message_handler,
        content_types=["text"],
        chat_types=["group", "supergroup"],
    )
    dp.message.register(
        language_selection_handler,
        content_types=["text"],
        chat_types=["group", "supergroup"],
    )
    dp.callback_query.register(
        language_callback_handler, lambda c: c.data.startswith("lang_")
    )
    dp.callback_query.register(
        quiz_callback_handler, lambda c: c.data.startswith("quiz_")
    )
