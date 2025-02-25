from aiogram.fsm.state import State, StatesGroup


class UserState(StatesGroup):
    selecting_language = State()
    answering_quiz = State()
