import logging


def setup_logging() -> None:
    """Настройка логирования."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s - [%(filename)s:%(lineno)d]",
        level=logging.INFO,
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)  # Уменьшаем шум от aiogram