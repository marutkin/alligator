import random
import logging
import asyncio
import sqlite3
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from asyncio import TimeoutError
from datetime import datetime, timedelta

# Загружаем переменные из .env файла
load_dotenv()
TOKEN = os.getenv("TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp = Dispatcher()

question_of_the_day = None  # Хранение вопроса дня

# Храним время последнего вызова команд
last_pick_time = None
last_history_time = None

# Создание или подключение к базе данных SQLite
def init_db():
    connection = sqlite3.connect('bot_history.db')
    cursor = connection.cursor()
    
    # Создаём таблицы, если их нет
    cursor.execute('''CREATE TABLE IF NOT EXISTS pick_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        admin_id INTEGER,
                        admin_name TEXT,
                        question TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        question TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                      )''')
    
    connection.commit()
    connection.close()

def update_db_schema():
    connection = sqlite3.connect('bot_history.db')
    cursor = connection.cursor()

    # Добавляем столбец question, если его нет
    cursor.execute('''PRAGMA foreign_keys=off;''')  # Отключаем проверки
    cursor.execute('''ALTER TABLE pick_history ADD COLUMN question TEXT;''')
    cursor.execute('''PRAGMA foreign_keys=on;''')  # Включаем проверки обратно
    
    connection.commit()
    connection.close()

# Добавляем запись о выбранном администраторе и вопросе в базу данных
def add_pick_history(admin_id, admin_name, question):
    connection = sqlite3.connect('bot_history.db')
    cursor = connection.cursor()
    
    cursor.execute('INSERT INTO pick_history (admin_id, admin_name, question) VALUES (?, ?, ?)', 
                   (admin_id, admin_name, question))
    
    connection.commit()
    connection.close()

# Получаем всю историю выбора
def get_pick_history():
    connection = sqlite3.connect('bot_history.db')
    cursor = connection.cursor()
    
    cursor.execute('SELECT admin_name, question, timestamp FROM pick_history ORDER BY timestamp DESC LIMIT 10')
    history = cursor.fetchall()
    
    connection.close()
    
    return history

@dp.message(Command("question"))
async def set_question(message: Message):
    if message.text == "/question":
        await message.reply("Введите вопрос после команды /question")
        return
    """Сохраняет вопрос дня в базу данных"""
    global question_of_the_day
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply("Этот бот работает только в группах!")
        return

    question_of_the_day = message.text[len("/question "):].strip()
    
    """Выбирает случайного администратора чата с тайм-аутом"""
    global last_pick_time

    # Проверка на cooldown
    if not check_cooldown(last_pick_time):
        remaining_time = timedelta(minutes=1) - (datetime.now() - last_pick_time)
        await message.reply(f"Подождите, еще {remaining_time.seconds} секунд до следующего вызова команды.")
        return

    try:
        # Устанавливаем тайм-аут в 1 минуту
        await asyncio.wait_for(pick_admin_logic(message), timeout=60)
        last_pick_time = datetime.now()  # Обновляем время последнего вызова
    
    except TimeoutError:
        await message.reply("Время ожидания для команды /pick истекло!")


    # Добавляем вопрос в базу
    connection = sqlite3.connect('bot_history.db')
    cursor = connection.cursor()
    cursor.execute('INSERT INTO questions (question) VALUES (?)', (question_of_the_day,))
    connection.commit()
    connection.close()
    
    # await message.reply(f"Олегатор запомнил: {question_of_the_day}")

def check_cooldown(last_time):
    """Проверяет, прошло ли достаточно времени с последнего вызова (1)"""
    if last_time is None:
        return True
    return datetime.now() - last_time > timedelta(minutes=1)

async def pick_admin_logic(message: Message):
    """Логика выбора случайного администратора"""
    try:
        chat_admins = await bot.get_chat_administrators(message.chat.id)
        admin_list = [admin.user for admin in chat_admins if not admin.user.is_bot]

        if not admin_list:
            await message.reply("Не удалось найти администраторов для выбора.")
            return

        chosen_admin = random.choice(admin_list)
        chosen_mention = f"[{chosen_admin.first_name}](tg://user?id={chosen_admin.id})"

        # Добавляем выбор и вопрос в базу данных
        add_pick_history(chosen_admin.id, chosen_admin.first_name, question_of_the_day)

        logging.info(f"Chosen admin: {chosen_admin.first_name}")
        logging.info(f"Admin list: {', '.join([admin.first_name for admin in admin_list])}")

        if question_of_the_day:
            await message.reply(f"Это {chosen_mention} 🎉")
        else:
            await message.reply(f"🎉 {chosen_mention}, ты выбран!")

    except Exception as e:
        logging.error(f"Ошибка при получении администраторов: {e}")
        await message.reply("Произошла ошибка при выборе администратора.")

@dp.message(Command("history"))
async def show_history(message: Message):
    """Показывает историю выборов и вопросов"""
    global last_history_time

    # Проверка на cooldown
    if not check_cooldown(last_history_time):
        remaining_time = timedelta(minutes=1) - (datetime.now() - last_history_time)
        await message.reply(f"Подождите, еще {remaining_time.seconds} секунд до следующего вызова команды, Олегатор чилит.")
        return

    history = get_pick_history()

    if not history:
        await message.reply("История пуста.")
        return

    history_message = "История выборов администраторов:\n"
    for admin_name, question, timestamp in history:
        history_message += f"{timestamp} - {admin_name} - Вопрос: {question}\n"
    
    await message.reply(history_message)
    last_history_time = datetime.now()  # Обновляем время последнего вызова

async def main():
    """Запускает бота"""
    logging.basicConfig(level=logging.INFO)
    init_db()  # Инициализируем базу данных
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
