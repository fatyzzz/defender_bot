# Стадия сборки
FROM python:3.12-slim AS builder

WORKDIR /app

# Устанавливаем системные зависимости для сборки
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Стадия production
FROM python:3.12-slim

WORKDIR /app

# Создаём непривилегированного пользователя
RUN useradd -m botuser

# Копируем установленные пакеты из стадии сборки
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем весь проект
COPY . .

# Устанавливаем владельца для файлов
RUN chown -R botuser:botuser /app

# Переключаемся на непривилегированного пользователя
USER botuser

# Указываем команду для запуска бота
CMD ["python", "bot.py"]