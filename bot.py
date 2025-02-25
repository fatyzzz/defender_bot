import os
import json
import random
import logging
from datetime import datetime, timedelta
import mysql.connector
import nest_asyncio
nest_asyncio.apply()

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

ALLOWED_CHAT_ID = None
user_languages = {}
orig_messages = {}  # Сохраняем id первого сообщения пользователя

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)
questions = config["questions"]
dialogs = config["dialogs"]

pending_quizzes = {}

db_conn = mysql.connector.connect(
    unix_socket='/var/run/mysqld/mysqld.sock',
    user=os.getenv("DB_USER", "lk-happ"),
    password = os.getenv("DB_PASSWORD"),
    database="defender_bot"
)

# Инициализация таблиц, если их нет
cursor = db_conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS passed_users (
    user_id BIGINT PRIMARY KEY,
    passed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
db_conn.commit()
cursor.close()

cursor = db_conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS banned_users (
    user_id BIGINT PRIMARY KEY,
    banned_until TIMESTAMP
)
""")
db_conn.commit()
cursor.close()

def check_user_passed(user_id):
    cursor = db_conn.cursor()
    cursor.execute("SELECT user_id FROM passed_users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    return result is not None

def mark_user_passed(user_id):
    cursor = db_conn.cursor()
    try:
        cursor.execute("INSERT INTO passed_users (user_id) VALUES (%s)", (user_id,))
        db_conn.commit()
    except mysql.connector.errors.IntegrityError:
        pass
    finally:
        cursor.close()

def ban_user_in_db(user_id, banned_until):
    cursor = db_conn.cursor()
    try:
        cursor.execute("REPLACE INTO banned_users (user_id, banned_until) VALUES (%s, %s)", (user_id, banned_until))
        db_conn.commit()
    finally:
        cursor.close()

def remove_banned_from_db(user_id):
    cursor = db_conn.cursor()
    try:
        cursor.execute("DELETE FROM banned_users WHERE user_id = %s", (user_id,))
        db_conn.commit()
    finally:
        cursor.close()

def get_thread_id(chat, current_thread_id):
    if chat.is_forum and not current_thread_id:
        fallback = os.getenv("FALLBACK_THREAD_ID")
        if fallback:
            logging.info(f"Using fallback thread_id: {fallback}")
            return int(fallback)
        else:
            logging.error("Forum group detected but no thread id provided and FALLBACK_THREAD_ID is not set.")
            return None
    return current_thread_id

async def delete_message_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    try:
        await context.bot.delete_message(chat_id, message_id)
        logging.info(f"Deleted message {message_id} from chat {chat_id}")
    except Exception as e:
        logging.error(f"Failed to delete message {message_id}: {e}")

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOWED_CHAT_ID
    chat = update.effective_chat
    if ALLOWED_CHAT_ID is None:
        ALLOWED_CHAT_ID = chat.id
        await update.message.reply_text("Бот активирован в этом чате!")
        logging.info(f"Bot activated in chat {ALLOWED_CHAT_ID}")
    else:
        if chat.id == ALLOWED_CHAT_ID:
            await update.message.reply_text("Бот уже активен в этом чате!")
        else:
            await update.message.reply_text("Извините, бот работает только в разрешённом чате.")

async def ban_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    ban_duration = 86400  # 1 день
    until_date = datetime.now() + timedelta(seconds=ban_duration)
    await context.bot.restrict_chat_member(
        chat_id, user_id,
        ChatPermissions(can_send_messages=False),
        until_date=until_date
    )
    ban_user_in_db(user_id, until_date)
    logging.info(f"User {user_id} muted until {until_date} in chat {chat_id}.")
    context.application.job_queue.run_once(kick_callback, ban_duration, data={"chat_id": chat.id, "user_id": user_id})

async def kick_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    user_id = job_data["user_id"]
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        logging.info(f"User {user_id} kicked from chat {chat_id}.")
    except Exception as e:
        logging.error(f"Error kicking user {user_id}: {e}")
    context.application.job_queue.run_once(unban_callback, 2, data={"chat_id": chat_id, "user_id": user_id})

async def unban_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    user_id = job_data["user_id"]
    try:
        await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        logging.info(f"User {user_id} unbanned in chat {chat_id}.")
    except Exception as e:
        logging.error(f"Error unbanning user {user_id}: {e}")
    context.application.job_queue.run_once(remove_banned, 5, data={"user_id": user_id})

async def remove_banned(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    remove_banned_from_db(user_id)
    logging.info(f"Record for user {user_id} removed from banned_users table.")

async def start_quiz_for_user(user, chat, context, thread_id=None, orig_message_id=None):
    lang = user_languages[user.id]
    question = random.choice(questions)
    question_text_local = question["question"][lang]
    answers_local = question["answers"][lang]
    indices = list(range(len(answers_local)))
    random.shuffle(indices)
    correct_index = indices.index(question["correct_index"])
    keyboard = [
        [InlineKeyboardButton(text=answers_local[i], callback_data=f"{user.id}_{j}")]
        for j, i in enumerate(indices)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    job = context.application.job_queue.run_once(
        timeout_callback, 30,
        data={
            "chat_id": chat.id,
            "user_id": user.id,
            "thread_id": thread_id,
            "lang": lang,
            "orig_message_id": orig_message_id
        }
    )
    pending_quizzes[user.id] = {
        "correct_answer": correct_index,
        "job": job,
        "lang": lang,
        "orig_message_id": orig_message_id
    }
    msg_text = dialogs["greeting"][lang].format(name=user.full_name) + question_text_local
    if thread_id:
        await context.bot.send_message(chat_id=chat.id, text=msg_text, reply_markup=reply_markup, message_thread_id=thread_id)
    else:
        await context.bot.send_message(chat_id=chat.id, text=msg_text, reply_markup=reply_markup)

async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOWED_CHAT_ID, user_languages, orig_messages
    chat = update.effective_chat
    if ALLOWED_CHAT_ID is None or chat.id != ALLOWED_CHAT_ID:
        return

    message = update.message
    if not message:
        return
    user = message.from_user
    if user.id == context.bot.id:
        return

    if check_user_passed(user.id):
        return

    # Если язык ещё не выбран
    if user.id not in user_languages:
        # Если пользователь впервые написал (нет сохранённого orig_message_id)
        if user.id not in orig_messages:
            orig_messages[user.id] = message.message_id

            # Добавляем user_id в callback_data, чтобы ограничить выбор языка только для этого пользователя
            keyboard = [[
                InlineKeyboardButton("Русский",  callback_data=f"lang_{user.id}_ru"),
                InlineKeyboardButton("English", callback_data=f"lang_{user.id}_en"),
                InlineKeyboardButton("中文",    callback_data=f"lang_{user.id}_zh")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await message.reply_text(dialogs["language_selection"], reply_markup=reply_markup)
        else:
            # Пользователь уже получил клавиатуру, но продолжает игнорировать – удаляем новое сообщение
            try:
                await message.delete()
                logging.info(f"Deleted message from user {user.id} ignoring language selection.")
            except Exception as e:
                logging.error(f"Failed to delete message from user {user.id}: {e}")
        return

    # Если язык выбран, но пользователь ещё не прошёл квиз:
    if user.id in pending_quizzes:
        try:
            await message.delete()
            logging.info(f"Deleted extra message from user {user.id} (quiz already pending).")
        except Exception as e:
            logging.error(f"Failed to delete extra message from user {user.id}: {e}")
        return

    if user.id not in orig_messages:
        orig_messages[user.id] = message.message_id

    thread_id = getattr(message, "message_thread_id", None)
    thread_id = get_thread_id(chat, thread_id)
    await start_quiz_for_user(user, chat, context, thread_id, orig_message_id=orig_messages[user.id])

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOWED_CHAT_ID, user_languages
    chat = update.effective_chat
    if ALLOWED_CHAT_ID is None or chat.id != ALLOWED_CHAT_ID:
        return

    query = update.callback_query
    # Подтверждаем колбэк, чтобы Telegram не жаловался (но без сообщения)
    await query.answer()

    # Пример колбэка для языка: "lang_123456_ru"
    # Пример колбэка для квиза: "123456_0"
    data = query.data.split("_")

    # Если это выбор языка (начинается с "lang")
    if data[0] == "lang":
        if len(data) < 3:
            return  # На всякий случай, если что-то пошло не так

        target_user_id_str = data[1]  # для кого предназначена клавиатура
        chosen_lang = data[2]
        try:
            target_user_id = int(target_user_id_str)
        except ValueError:
            return

        # Если кнопку нажал не тот, кому она предназначена, – игнорируем
        if query.from_user.id != target_user_id:
            return

        # Устанавливаем язык
        user_languages[target_user_id] = chosen_lang
        orig_id = orig_messages.get(target_user_id)

        # Меняем текст сообщения на "Язык установлен"
        lang_set_msg = await query.edit_message_text(text=dialogs["language_set"][chosen_lang])
        context.application.job_queue.run_once(
            delete_message_callback,
            5,
            data={"chat_id": chat.id, "message_id": lang_set_msg.message_id}
        )

        # Запускаем квиз
        thread_id = get_thread_id(chat, getattr(query.message, "message_thread_id", None))
        user = query.from_user
        await start_quiz_for_user(user, chat, context, thread_id, orig_message_id=orig_id)
        return

    # Иначе, предполагаем, что это ответ на квиз (формат "userId_selectedIndex")
    if len(data) != 2:
        return

    try:
        quiz_user_id = int(data[0])
        selected_index = int(data[1])
    except ValueError:
        return

    # Если кнопку нажал чужой, не обрабатываем
    if quiz_user_id != query.from_user.id:
        return

    if quiz_user_id not in pending_quizzes:
        await query.edit_message_text(text="Time to answer has expired or the question has already been processed.")
        return

    lang = pending_quizzes[quiz_user_id]["lang"]
    orig_msg_id = pending_quizzes[quiz_user_id].get("orig_message_id")
    pending_quizzes[quiz_user_id]["job"].schedule_removal()

    # Проверка ответа
    if selected_index == pending_quizzes[quiz_user_id]["correct_answer"]:
        edited_message = await query.edit_message_text(text=dialogs["correct"][lang])
        mark_user_passed(quiz_user_id)
    else:
        edited_message = await query.edit_message_text(text=dialogs["incorrect"][lang].format(name=query.from_user.full_name))
        await ban_user(chat.id, quiz_user_id, context)
        if orig_msg_id:
            context.application.job_queue.run_once(
                delete_message_callback,
                5,
                data={"chat_id": chat.id, "message_id": orig_msg_id}
            )

    context.application.job_queue.run_once(
        delete_message_callback,
        60,
        data={"chat_id": chat.id, "message_id": edited_message.message_id}
    )
    del pending_quizzes[quiz_user_id]

async def timeout_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    user_id = job_data["user_id"]
    thread_id = job_data.get("thread_id")
    lang = job_data.get("lang", "en")
    orig_msg_id = job_data.get("orig_message_id")
    message_text = dialogs["timeout"][lang].format(user_id=user_id)
    try:
        if thread_id:
            await context.bot.send_message(chat_id=chat_id, text=message_text, message_thread_id=thread_id)
        else:
            await context.bot.send_message(chat_id=chat_id, text=message_text)
    except Exception as e:
        if "Topic_closed" in str(e):
            logging.error(f"Failed to send timeout message due to Topic_closed: {e}")
        else:
            raise
    await ban_user(chat_id, user_id, context)
    if orig_msg_id:
        context.application.job_queue.run_once(
            delete_message_callback,
            5,
            data={"chat_id": chat_id, "message_id": orig_msg_id}
        )
    if user_id in pending_quizzes:
        del pending_quizzes[user_id]

async def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise Exception("BOT_TOKEN environment variable not set")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_message_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    await app.run_polling(close_loop=False)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())