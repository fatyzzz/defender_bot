from functools import partial
from aiogram import Dispatcher
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from .language import language_selection_handler, language_callback_handler
from .quiz import group_message_handler, quiz_callback_handler
from .start import start_handler
from .message import message_handler


def setup_handlers(dp: Dispatcher, bot, pool) -> None:
    """Регистрация хэндлеров."""
    dp.message.register(start_handler, Command(commands=["start"]))
    dp.chat_member.register(
        partial(group_message_handler, bot=bot, pool=pool),
        ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION),
    )
    dp.callback_query.register(
        partial(language_callback_handler, pool=pool),
        lambda c: c.data.startswith("lang_"),
    )
    dp.callback_query.register(
        partial(quiz_callback_handler, pool=pool),
        lambda c: c.data.startswith("quiz_"),
    )
    dp.message.register(
        partial(message_handler, bot=bot, pool=pool),
        lambda m: m.chat.type in ["group", "supergroup"] and not m.from_user.is_bot,
    )
