#!/bin/bash
set -e  # Прерывает выполнение при ошибке

# Имя контейнера и образа
NAME=defender_bot

# Путь к файлу .env
ENV_FILE=".env"

# Проверяем, существует ли файл .env
if [ ! -f "$ENV_FILE" ]; then
  echo "Файл .env не найден!"
  exit 1
fi

# Загружаем переменные из .env
set -a
source "$ENV_FILE"
set +a

# Проверяем обязательные переменные
if [ -z "$BOT_TOKEN" ] || [ -z "$DB_TYPE" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ] || [ -z "$DB_NAME" ]; then
  echo "Не все обязательные переменные заданы в .env!"
  echo "Обязательные: BOT_TOKEN, DB_TYPE, DB_USER, DB_PASSWORD, DB_NAME"
  exit 1
fi

# Проверяем, что DB_TYPE поддерживается
if [ "$DB_TYPE" != "mysql" ] && [ "$DB_TYPE" != "postgres" ]; then
  echo "Неподдерживаемый DB_TYPE: $DB_TYPE. Должен быть 'mysql' или 'postgres'."
  exit 1
fi

# Определяем способ подключения к базе данных
if [ "$DB_TYPE" == "mysql" ]; then
  if [ -n "$DB_SOCKET" ] && [ -z "$DB_PORT" ]; then
    # Используем Unix-сокет для MySQL
    SOCKET_PATH="$DB_SOCKET"
    if [ ! -S "$SOCKET_PATH" ]; then
      echo "Сокет $SOCKET_PATH не найден или не является сокетом!"
      exit 1
    fi
    MOUNT_OPTION="-v $SOCKET_PATH:/var/run/mysqld/mysqld.sock"
    echo "Используется Unix-сокет для MySQL: $SOCKET_PATH"
  elif [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
    # Используем TCP для MySQL
    MOUNT_OPTION=""
    echo "Используется TCP-подключение для MySQL: $DB_HOST:$DB_PORT"
  else
    echo "Для MySQL задай либо DB_SOCKET, либо DB_HOST и DB_PORT."
    exit 1
  fi
elif [ "$DB_TYPE" == "postgres" ]; then
  # Для PostgreSQL используем TCP
  if [ -z "$DB_HOST" ] || [ -z "$DB_PORT" ]; then
    echo "Для PostgreSQL необходимо задать DB_HOST и DB_PORT."
    exit 1
  fi
  MOUNT_OPTION=""
  echo "Используется TCP-подключение для PostgreSQL: $DB_HOST:$DB_PORT"
fi

# Переход в директорию с проектом
cd "$(dirname "$0")"

# Останавливаем и удаляем старый контейнер, если он существует
docker stop "$NAME" 2>/dev/null || true
docker rm "$NAME" 2>/dev/null || true

# Удаляем неиспользуемые образы
docker image prune -a -f

# Сборка Docker-образа
docker build -t "$NAME" .

# Запуск контейнера с передачей всех переменных окружения
docker run -d --name "$NAME" \
  $MOUNT_OPTION \
  -e BOT_TOKEN="$BOT_TOKEN" \
  -e DB_TYPE="$DB_TYPE" \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  -e DB_NAME="$DB_NAME" \
  -e DB_HOST="$DB_HOST" \
  -e DB_PORT="$DB_PORT" \
  -e DB_SOCKET="$DB_SOCKET" \
  -e ALLOWED_CHAT_ID="$ALLOWED_CHAT_ID" \
  -e FALLBACK_THREAD_ID="$FALLBACK_THREAD_ID" \
  "$NAME"

echo "Контейнер $NAME успешно запущен с подключением к $DB_TYPE."

# Просмотр логов контейнера
docker logs -f "$NAME"