#!/bin/bash
set -e  # Прерывает выполнение при ошибке

# Имя контейнера и образа
NAME=defender_bot
ENV_FILE=".env"

# Проверка наличия файла .env
[ ! -f "$ENV_FILE" ] && { echo "Файл .env не найден!"; exit 1; }

# Загрузка переменных из .env
set -a; source "$ENV_FILE"; set +a

# Проверка обязательных переменных
[ -z "$BOT_TOKEN" ] || [ -z "$DB_TYPE" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ] || [ -z "$DB_NAME" ] && {
  echo "Не все обязательные переменные заданы в .env!"
  echo "Обязательные: BOT_TOKEN, DB_TYPE, DB_USER, DB_PASSWORD, DB_NAME"
  exit 1
}

# Проверка типа базы данных
[ "$DB_TYPE" != "mysql" ] && [ "$DB_TYPE" != "postgres" ] && {
  echo "Неподдерживаемый DB_TYPE: $DB_TYPE. Должен быть 'mysql' или 'postgres'."
  exit 1
}

# Настройка подключения к базе данных
if [ "$DB_TYPE" = "mysql" ]; then
  if [ -n "$DB_SOCKET" ] && [ -z "$DB_PORT" ]; then
    [ ! -S "$DB_SOCKET" ] && { echo "Сокет $DB_SOCKET не найден!"; exit 1; }
    MOUNT_OPTION="-v $DB_SOCKET:/var/run/mysqld/mysqld.sock"
  elif [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
    MOUNT_OPTION=""
  else
    echo "Для MySQL задай либо DB_SOCKET, либо DB_HOST и DB_PORT."
    exit 1
  fi
elif [ "$DB_TYPE" = "postgres" ]; then
  [ -z "$DB_HOST" ] || [ -z "$DB_PORT" ] && {
    echo "Для PostgreSQL необходимо задать DB_HOST и DB_PORT."
    exit 1
  }
  MOUNT_OPTION=""
fi

# Переход в директорию скрипта
cd "$(dirname "$0")"

# Остановка и удаление старого контейнера
docker stop "$NAME" 2>/dev/null || true
docker rm "$NAME" 2>/dev/null || true

# Очистка неиспользуемых образов
docker image prune -a -f

# Сборка и запуск контейнера
docker build -t "$NAME" .
docker run -d --name "$NAME" $MOUNT_OPTION --env-file "$ENV_FILE" "$NAME"

echo "Контейнер $NAME запущен с подключением к $DB_TYPE."
docker logs -f "$NAME"
