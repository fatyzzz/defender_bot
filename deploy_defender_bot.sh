#!/bin/bash
set -e  # Прерывает выполнение скрипта при возникновении ошибки

NAME=defender_bot
TOKEN=""
PASSWORD=""

# Переход в нужную директорию
cd /root/$NAME

# Если аргумент равен "stop", останавливаем контейнер и выходим
if [ "$1" == "stop" ]; then
  docker stop $NAME
  docker rm $NAME
  docker image prune -a -f
  exit 0
fi

# Если первым аргументом не передан "start", то выполняем остановку, удаление контейнеров и очистку образов
if [ "$1" != "start" ]; then
  docker stop $NAME
  docker rm $NAME
  docker image prune -a -f
fi

# Сборка образа
docker build -t $NAME .

# Запуск контейнера:
# Пробрасываем unix-сокет MySQL и устанавливаем DB_HOST=localhost,
# чтобы bot.py мог подключиться через сокет, а не по TCP.
docker run --add-host=host.docker.internal:host-gateway \
  -v /var/run/mysqld/mysqld.sock:/var/run/mysqld/mysqld.sock \
  -d --name $NAME \
  -e DB_HOST=localhost \
  -e BOT_TOKEN=$TOKEN \
  -e DB_PASSWORD=$PASSWORD \
  $NAME