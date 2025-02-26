from aiogram.fsm.state import State, StatesGroup

class UserState(StatesGroup):
    waiting_for_language = State()  # Ожидание выбора языка
    answering_quiz = State()       # Ответ на квиз
    completed = State()            # Прошёл квиз успешно