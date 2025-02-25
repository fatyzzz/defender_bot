import logging


def setup_logging() -> None:
    """Настройка логирования с указанием файла и строки."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s - [%(filename)s:%(lineno)d]",
        level=logging.INFO,
    )
